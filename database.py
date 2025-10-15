"""
Gestión de base de datos Firebird para el sistema de IA.

Este módulo maneja la conexión, extracción de esquema y ejecución de consultas
con soporte para streaming de grandes volúmenes de datos.
"""

import os
import time
import threading
from typing import Dict, List, Tuple, Optional, Any, Generator, Iterator
from dataclasses import dataclass
from contextlib import contextmanager
from queue import Queue, Empty
import pandas as pd

from config import config, StatusMessages
from utils import logger, Timer, timing_decorator, SQLValidator, DataFormatter, SchemaStatsCache


@dataclass
class TableInfo:
    """Información de una tabla de la base de datos."""
    name: str
    owner: str
    type: str  # TABLE, VIEW, etc.
    row_count: int = 0
    columns: List[Dict[str, Any]] = None
    primary_keys: List[str] = None
    foreign_keys: List[Dict[str, Any]] = None
    indexes: List[Dict[str, Any]] = None
    last_update: Optional[str] = None
    is_active: bool = True
    description: str = ""
    
    def __post_init__(self):
        if self.columns is None:
            self.columns = []
        if self.primary_keys is None:
            self.primary_keys = []
        if self.foreign_keys is None:
            self.foreign_keys = []
        if self.indexes is None:
            self.indexes = []


@dataclass
class QueryResult:
    """Resultado de una consulta SQL."""
    sql: str
    columns: List[str]
    row_count: int
    execution_time: float
    has_more_data: bool = False
    preview_data: List[List[Any]] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.preview_data is None:
            self.preview_data = []


class ConnectionPool:
    """Pool de conexiones a Firebird para manejo eficiente."""
    
    def __init__(self, max_connections: int = 5):
        self.max_connections = max_connections
        self._connections: Queue = Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created_connections = 0
        
    def get_connection(self):
        """Obtener conexión del pool."""
        try:
            # Intentar obtener conexión existente
            return self._connections.get_nowait()
        except Empty:
            # Crear nueva conexión si no hay disponibles
            with self._lock:
                if self._created_connections < self.max_connections:
                    conn = self._create_connection()
                    self._created_connections += 1
                    return conn
                else:
                    # Esperar por una conexión disponible
                    return self._connections.get()
    
    def return_connection(self, conn):
        """Devolver conexión al pool."""
        if conn and not conn.is_closed():
            try:
                self._connections.put_nowait(conn)
            except:
                # Pool lleno, cerrar conexión
                conn.close()
                with self._lock:
                    self._created_connections -= 1
    
    def _create_connection(self):
        """Crear nueva conexión a Firebird con configuración óptima de transacción."""
        dsn = config.get_database_dsn()

        # Importar aquí para evitar errores en tiempo de importación del módulo
        from firebird.driver import connect as fb_connect, tpb, Isolation, TraAccessMode

        # Configurar TPB (Transaction Parameter Block) para READ COMMITTED
        # Esto es MUCHO más rápido que SNAPSHOT (default) para queries complejas
        custom_tpb = tpb(
            isolation=Isolation.READ_COMMITTED_RECORD_VERSION,  # READ COMMITTED - más rápido
            access_mode=TraAccessMode.READ,  # Solo lectura (queries SELECT)
            lock_timeout=30  # Timeout de 30 segundos para locks
        )

        conn = fb_connect(
            dsn,
            user=config.database.username,
            password=config.database.password,
            charset=config.database.charset
        )

        # Configurar transacción por defecto
        conn.default_tpb = custom_tpb

        return conn
    
    def close_all(self):
        """Cerrar todas las conexiones."""
        while True:
            try:
                conn = self._connections.get_nowait()
                conn.close()
            except Empty:
                break
        
        with self._lock:
            self._created_connections = 0


class FirebirdDB:
    """Gestor principal de base de datos Firebird."""
    
    def __init__(self):
        self._pool = None
        self._schema_cache = {}
        self._connection_test_time = None
        self._is_connected = False
        self._stats_cache = SchemaStatsCache(ttl_seconds=12*3600)  # Caché de 12 horas
        
    @contextmanager
    def get_connection(self):
        """Context manager para obtener conexión del pool."""
        conn = None
        try:
            if not self._pool:
                self.connect()
            
            conn = self._pool.get_connection()
            yield conn
            
        except Exception as e:
            logger.error("Error en conexión de base de datos", e)
            raise
        finally:
            if conn:
                self._pool.return_connection(conn)
    
    @timing_decorator("Database Connection")
    def connect(self) -> bool:
        """Establecer conexión con la base de datos."""
        try:
            if self._pool:
                self._pool.close_all()
            
            self._pool = ConnectionPool(config.database.connection_pool_size)
            
            # Probar conexión
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT CURRENT_TIMESTAMP FROM RDB$DATABASE")
                result = cursor.fetchone()
                self._connection_test_time = result[0]
            
            self._is_connected = True
            logger.info("Conexión establecida con Firebird")
            return True
            
        except Exception as e:
            logger.error("Error conectando a Firebird", e)
            self._is_connected = False
            return False
    
    def is_connected(self) -> bool:
        """Verificar si hay conexión activa."""
        return self._is_connected
    
    def test_connection(self) -> Tuple[bool, str]:
        """Probar conexión y retornar estado."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT CURRENT_TIMESTAMP FROM RDB$DATABASE")
                timestamp = cursor.fetchone()[0]
                return True, f"Conexión OK - Servidor: {timestamp}"
        except Exception as e:
            return False, f"Error de conexión: {str(e)}"
    
    @timing_decorator("Schema Extraction")
    def get_full_schema(self, force_refresh: bool = False) -> Dict[str, TableInfo]:
        """Extraer esquema completo de la base de datos."""
        cache_key = "full_schema"

        if not force_refresh and cache_key in self._schema_cache:
            logger.info("Usando esquema desde caché")
            return self._schema_cache[cache_key]

        logger.info("Extrayendo esquema completo de la base de datos...")

        schema = {}

        try:
            with self.get_connection() as conn:
                # Obtener información de tablas con timeout
                tables_info = self._get_tables_info_with_timeout(conn, timeout_seconds=30)

                if not tables_info:
                    logger.warning("No se encontraron tablas")
                    return {}

                logger.info(f"Procesando {len(tables_info)} tablas...")

                # Procesar tablas por prioridad para evitar bloqueos largos
                table_names = list(tables_info.keys())

                # Procesar tablas importantes primero
                priority_tables = []
                regular_tables = []

                for table_name in table_names:
                    table_info = tables_info[table_name]
                    # Tablas con nombres de catálogo o importantes primero
                    if any(keyword in table_name.upper() for keyword in ['CATALOGO', 'CODIGO', 'ARTICULOS', 'CLIENTES', 'PROVEEDORES']):
                        priority_tables.append(table_name)
                    else:
                        regular_tables.append(table_name)

                # Procesar prioridad primero, luego el resto
                all_tables = priority_tables + regular_tables

                processed_count = 0
                for table_name in all_tables:
                    try:
                        table_info = tables_info[table_name]

                        # Obtener columnas, claves, índices (rápido)
                        try:
                            table_info.columns = self._get_table_columns(conn, table_name)
                        except Exception as e:
                            logger.debug(f"Error obteniendo columnas de {table_name}: {e}")
                            table_info.columns = []

                        try:
                            table_info.primary_keys = self._get_primary_keys(conn, table_name)
                        except Exception as e:
                            logger.debug(f"Error obteniendo PKs de {table_name}: {e}")
                            table_info.primary_keys = []

                        try:
                            table_info.foreign_keys = self._get_foreign_keys(conn, table_name)
                        except Exception as e:
                            logger.debug(f"Error obteniendo FKs de {table_name}: {e}")
                            table_info.foreign_keys = []

                        try:
                            table_info.indexes = self._get_indexes(conn, table_name)
                        except Exception as e:
                            logger.debug(f"Error obteniendo índices de {table_name}: {e}")
                            table_info.indexes = []

                        # NO CONTAR REGISTROS en inicialización (es muy lento)
                        # Solo usar caché si existe, sino marcar como pendiente
                        cached_count = self._stats_cache.get_row_count(table_name)
                        if cached_count is not None:
                            table_info.row_count = cached_count
                        else:
                            # Marcar como "pendiente de contar" para procesar en background
                            table_info.row_count = -1

                        # Determinar si la tabla está activa
                        table_info.is_active = self._is_table_active(table_info)

                        schema[table_name] = table_info
                        processed_count += 1

                        # Log progress cada 50 tablas (reducir I/O)
                        if processed_count % 50 == 0:
                            logger.info(f"Procesadas {processed_count}/{len(all_tables)} tablas...")

                    except Exception as e:
                        logger.warning(f"Error procesando tabla {table_name}: {str(e)}")
                        # Continuar con la siguiente tabla
                        processed_count += 1
                        continue

            self._schema_cache[cache_key] = schema
            logger.info(f"✅ Esquema extraído: {len(schema)} tablas")

            return schema

        except Exception as e:
            logger.error("❌ Error extrayendo esquema", e)
            return {}

    def _get_tables_info_with_timeout(self, conn, timeout_seconds: int = 30) -> Dict[str, TableInfo]:
        """Obtener información básica de tablas con timeout."""
        try:
            start_time = time.time()

            # Verificar timeout básico
            if time.time() - start_time > timeout_seconds:
                logger.warning(f"Timeout obteniendo información de tablas")
                return {}

            tables_info = self._get_tables_info(conn)

            return tables_info

        except Exception as e:
            logger.error(f"Error obteniendo información de tablas: {e}")
            return {}
    
    def _get_tables_info(self, conn) -> Dict[str, TableInfo]:
        """Obtener información básica de tablas."""
        query = """
        SELECT 
            RDB$RELATION_NAME,
            RDB$OWNER_NAME,
            RDB$RELATION_TYPE
        FROM RDB$RELATIONS 
        WHERE RDB$SYSTEM_FLAG = 0 
          AND RDB$RELATION_TYPE IN (0, 1)
        ORDER BY RDB$RELATION_NAME
        """
        
        cursor = conn.cursor()
        cursor.execute(query)
        
        tables = {}
        for row in cursor.fetchall():
            table_name = row[0].strip()
            owner = row[1].strip() if row[1] else 'SYSDBA'
            relation_type = 'TABLE' if row[2] == 0 else 'VIEW'
            
            tables[table_name] = TableInfo(
                name=table_name,
                owner=owner,
                type=relation_type
            )
        
        return tables
    
    def _get_table_columns(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Obtener información de columnas de una tabla."""
        query = """
        SELECT 
            rf.RDB$FIELD_NAME,
            rf.RDB$FIELD_POSITION,
            rf.RDB$NULL_FLAG,
            f.RDB$FIELD_TYPE,
            f.RDB$FIELD_SUB_TYPE,
            f.RDB$FIELD_LENGTH,
            f.RDB$FIELD_SCALE,
            f.RDB$FIELD_PRECISION,
            rf.RDB$DEFAULT_SOURCE,
            rf.RDB$DESCRIPTION
        FROM RDB$RELATION_FIELDS rf
        JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME
        WHERE rf.RDB$RELATION_NAME = ?
        ORDER BY rf.RDB$FIELD_POSITION
        """
        
        cursor = conn.cursor()
        cursor.execute(query, (table_name,))
        
        columns = []
        for row in cursor.fetchall():
            field_name = row[0].strip()
            field_type = self._get_field_type_name(row[3], row[4], row[5], row[6], row[7])
            
            column_info = {
                'name': field_name,
                'position': row[1],
                'nullable': row[2] is None,
                'data_type': field_type,
                'length': row[5],
                'scale': row[6],
                'precision': row[7],
                'has_default': row[8] is not None,
                'description': row[9].strip() if row[9] else None
            }
            
            columns.append(column_info)
        
        return columns
    
    def _get_field_type_name(self, field_type: int, sub_type: int, length: int, 
                           scale: int, precision: int) -> str:
        """Convertir código de tipo Firebird a nombre legible."""
        type_map = {
            7: "SMALLINT",
            8: "INTEGER", 
            10: "FLOAT",
            12: "DATE",
            13: "TIME",
            14: "CHAR",
            16: "BIGINT",
            23: "BOOLEAN",
            27: "DOUBLE PRECISION",
            35: "TIMESTAMP",
            37: "VARCHAR",
            261: "BLOB"
        }
        
        base_type = type_map.get(field_type, f"UNKNOWN({field_type})")
        
        if field_type == 14:  # CHAR
            return f"CHAR({length})"
        elif field_type == 37:  # VARCHAR
            return f"VARCHAR({length})"
        elif field_type in [7, 8, 16] and scale < 0:  # NUMERIC/DECIMAL
            return f"NUMERIC({precision},{abs(scale)})"
        
        return base_type
    
    def _get_primary_keys(self, conn, table_name: str) -> List[str]:
        """Obtener claves primarias de una tabla."""
        query = """
        SELECT DISTINCT s.RDB$FIELD_NAME
        FROM RDB$RELATION_CONSTRAINTS rc
        JOIN RDB$INDEX_SEGMENTS s ON rc.RDB$INDEX_NAME = s.RDB$INDEX_NAME
        WHERE rc.RDB$RELATION_NAME = ? 
          AND rc.RDB$CONSTRAINT_TYPE = 'PRIMARY KEY'
        ORDER BY s.RDB$FIELD_POSITION
        """
        
        cursor = conn.cursor()
        cursor.execute(query, (table_name,))
        
        return [row[0].strip() for row in cursor.fetchall()]
    
    def _get_foreign_keys(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Obtener claves foráneas de una tabla con información completa."""
        try:
            # Consulta corregida sin columnas que no existen en esta versión de Firebird
            query = """
            SELECT
                rc.RDB$CONSTRAINT_NAME,
                s.RDB$FIELD_NAME,
                rc2.RDB$RELATION_NAME,
                s2.RDB$FIELD_NAME
            FROM RDB$RELATION_CONSTRAINTS rc
            JOIN RDB$INDEX_SEGMENTS s ON rc.RDB$INDEX_NAME = s.RDB$INDEX_NAME
            JOIN RDB$REF_CONSTRAINTS ref ON rc.RDB$CONSTRAINT_NAME = ref.RDB$CONSTRAINT_NAME
            JOIN RDB$RELATION_CONSTRAINTS rc2 ON ref.RDB$CONST_NAME_UQ = rc2.RDB$CONSTRAINT_NAME
            JOIN RDB$INDEX_SEGMENTS s2 ON rc2.RDB$INDEX_NAME = s2.RDB$INDEX_NAME
            WHERE rc.RDB$RELATION_NAME = ?
              AND rc.RDB$CONSTRAINT_TYPE = 'FOREIGN KEY'
            ORDER BY rc.RDB$CONSTRAINT_NAME, s.RDB$FIELD_POSITION
            """

            cursor = conn.cursor()
            cursor.execute(query, (table_name,))

            foreign_keys = []
            current_fk = {}
            current_columns = []

            for row in cursor.fetchall():
                constraint_name = row[0].strip()

                # Si es un nuevo constraint, guardar el anterior y empezar nuevo
                if current_fk and current_fk.get('constraint_name') != constraint_name:
                    # Agregar columnas al FK anterior
                    current_fk['columns'] = current_columns
                    foreign_keys.append(current_fk)
                    current_fk = {}
                    current_columns = []

                # Si es el primer registro de este constraint
                if not current_fk:
                    current_fk = {
                        'constraint_name': constraint_name,
                        'referenced_table': row[2].strip(),
                        'referenced_columns': [],
                        'columns': [],
                        'update_rule': None,  # No disponible en esta versión
                        'delete_rule': None   # No disponible en esta versión
                    }

                # Agregar columnas
                current_fk['columns'].append(row[1].strip())
                current_fk['referenced_columns'].append(row[3].strip())

            # Agregar el último FK si existe
            if current_fk:
                current_fk['columns'] = current_columns if current_columns else current_fk['columns']
                foreign_keys.append(current_fk)

            return foreign_keys

        except Exception as e:
            logger.debug(f"Error obteniendo FKs de {table_name}: {e}")
            return []
    
    def _get_indexes(self, conn, table_name: str) -> List[Dict[str, Any]]:
        """Obtener índices de una tabla con sus columnas."""
        try:
            # Primero obtener información básica de los índices
            query = """
            SELECT DISTINCT
                i.RDB$INDEX_NAME,
                i.RDB$UNIQUE_FLAG,
                i.RDB$INDEX_TYPE
            FROM RDB$INDICES i
            WHERE i.RDB$RELATION_NAME = ?
              AND i.RDB$SYSTEM_FLAG = 0
            """

            cursor = conn.cursor()
            cursor.execute(query, (table_name,))

            indexes = []
            index_names = []

            for row in cursor.fetchall():
                index_info = {
                    'name': row[0].strip(),
                    'unique': row[1] == 1,
                    'descending': row[2] == 1,
                    'columns': []  # Inicializar lista de columnas
                }
                indexes.append(index_info)
                index_names.append(row[0].strip())

            # Si hay índices, obtener las columnas que los forman
            if index_names:
                # Crear placeholders para la consulta IN
                placeholders = ','.join(['?' for _ in index_names])

                columns_query = f"""
                SELECT
                    s.RDB$INDEX_NAME,
                    s.RDB$FIELD_NAME,
                    s.RDB$FIELD_POSITION
                FROM RDB$INDEX_SEGMENTS s
                WHERE s.RDB$INDEX_NAME IN ({placeholders})
                ORDER BY s.RDB$INDEX_NAME, s.RDB$FIELD_POSITION
                """

                try:
                    cursor.execute(columns_query, index_names)

                    # Organizar columnas por índice
                    index_columns = {}
                    for row in cursor.fetchall():
                        index_name = row[0].strip()
                        field_name = row[1].strip()
                        field_position = row[2]

                        if index_name not in index_columns:
                            index_columns[index_name] = []
                        index_columns[index_name].append({
                            'name': field_name,
                            'position': field_position
                        })

                    # Agregar columnas a cada índice
                    for index_info in indexes:
                        index_name = index_info['name']
                        if index_name in index_columns:
                            index_info['columns'] = index_columns[index_name]
                except Exception as e:
                    logger.debug(f"Error obteniendo columnas de índices para {table_name}: {e}")
                    # Continuar sin columnas de índices

            return indexes

        except Exception as e:
            logger.debug(f"Error obteniendo índices de {table_name}: {e}")
            return []
    
    def _get_row_count(self, conn, table_name: str, timeout_seconds: int = 3) -> int:
        """Obtener número de registros con timeout más estricto usando threading."""
        import threading

        result_container = {'count': -1, 'error': None}

        def count_worker():
            """Worker thread para contar registros."""
            try:
                query = f"SELECT COUNT(*) FROM {table_name}"
                cursor = conn.cursor()
                cursor.execute(query)
                result = cursor.fetchone()
                result_container['count'] = result[0] if result else 0
                cursor.close()
            except Exception as e:
                result_container['error'] = str(e)

        try:
            # Ejecutar conteo en thread separado con timeout real
            worker_thread = threading.Thread(target=count_worker, daemon=True)
            worker_thread.start()
            worker_thread.join(timeout=timeout_seconds)

            # Si el thread todavía está vivo, hubo timeout
            if worker_thread.is_alive():
                logger.debug(f"⏱️ Timeout contando {table_name} (>{timeout_seconds}s), estimando -1")
                return -1

            # Si hubo error
            if result_container['error']:
                error_msg = result_container['error']
                if "doesn't exist" not in error_msg and "not found" not in error_msg:
                    logger.debug(f"Error contando {table_name}: {error_msg}")
                return -1

            return result_container['count']

        except Exception as e:
            logger.debug(f"Error en thread de conteo para {table_name}: {str(e)}")
            return -1
    
    def _is_table_active(self, table_info: TableInfo) -> bool:
        """Determinar si una tabla está activa usando heurísticas mejoradas."""
        table_name_upper = table_info.name.upper()

        # Verificar nombres que indican tablas obsoletas
        inactive_prefixes = ['OLD_', 'BAK_', 'TMP_', 'TEMP_', 'TEST_', 'DEL_', 'LOG_']
        inactive_suffixes = ['_OLD', '_BAK', '_TMP', '_TEMP', '_TEST', '_DEL', '_LOG']

        for prefix in inactive_prefixes:
            if table_name_upper.startswith(prefix):
                return False

        for suffix in inactive_suffixes:
            if table_name_upper.endswith(suffix):
                return False

        # Tablas con nombres de catálogo generalmente están activas
        catalog_keywords = ['CATALOGO', 'CATALOG', 'CODIGO', 'CODIGOS', 'TIPO', 'TIPOS', 'ARTICULOS', 'CLIENTES', 'PROVEEDORES']
        for keyword in catalog_keywords:
            if keyword in table_name_upper:
                return True

        # Si tiene foreign keys, generalmente está activa (es referenciada)
        if table_info.foreign_keys and len(table_info.foreign_keys) > 0:
            return True

        # Si tiene índices únicos, generalmente está activa
        if table_info.indexes:
            for index in table_info.indexes:
                if index.get('unique_flag', False):
                    return True

        # Si tiene muchas columnas, generalmente es una tabla maestra activa
        if len(table_info.columns) > 15:
            return True

        # Si tiene pocos registros pero tiene FKs o índices, puede estar activa
        if table_info.row_count > 0 and table_info.row_count < 100 and (table_info.foreign_keys or table_info.indexes):
            return True

        # Si tiene pocos registros pero nombre indica tabla maestra
        if table_info.row_count > 0 and table_info.row_count < 100:
            master_keywords = ['MAESTRO', 'MASTER', 'CABECERA', 'HEADER', 'PRINCIPAL']
            for keyword in master_keywords:
                if keyword in table_name_upper:
                    return True

        # Por defecto, considerar activa si tiene algún registro o es tabla de catálogo
        return table_info.row_count > 0
    
    def _is_table_active_quick(self, table_info: TableInfo) -> bool:
        """Determinar si una tabla está activa SIN contar registros (rápido)."""
        table_name_upper = table_info.name.upper()

        # Verificar nombres que indican tablas obsoletas
        inactive_prefixes = ['OLD_', 'BAK_', 'TMP_', 'TEMP_', 'TEST_', 'DEL_', 'BACKUP_', 'COPY_', 'LOG_']
        inactive_suffixes = ['_OLD', '_BAK', '_TMP', '_TEMP', '_TEST', '_DEL', '_BACKUP', '_COPY', '_LOG']

        for prefix in inactive_prefixes:
            if table_name_upper.startswith(prefix):
                return False

        for suffix in inactive_suffixes:
            if table_name_upper.endswith(suffix):
                return False

        # Tablas con nombres de catálogo generalmente están activas
        catalog_keywords = ['CATALOGO', 'CATALOG', 'CODIGO', 'CODIGOS', 'TIPO', 'TIPOS', 'ARTICULOS', 'CLIENTES', 'PROVEEDORES']
        for keyword in catalog_keywords:
            if keyword in table_name_upper:
                return True

        # Si tiene foreign keys, generalmente está activa (es referenciada)
        if table_info.foreign_keys and len(table_info.foreign_keys) > 0:
            return True

        # Si tiene índices únicos, generalmente está activa
        if table_info.indexes:
            for index in table_info.indexes:
                if index.get('unique_flag', False):
                    return True

        # Si tiene muchas columnas, generalmente es una tabla maestra activa
        if len(table_info.columns) > 15:
            return True

        # Si tiene primary keys, generalmente es una tabla importante
        if table_info.primary_keys and len(table_info.primary_keys) > 0:
            return True

        # Por defecto considerar activa (mejor pecar de activo que de inactivo)
        return True
    
    @timing_decorator("SQL Query Execution")
    def execute_query_limited(self, sql: str, limit: int = None) -> QueryResult:
        """Ejecutar query con límite de filas para preview."""
        if limit is None:
            limit = config.ui.preview_row_limit
        
        # Validar seguridad del SQL
        is_safe, error_msg = SQLValidator.is_safe_query(sql)
        if not is_safe:
            return QueryResult(
                sql=sql,
                columns=[],
                row_count=0,
                execution_time=0,
                has_more_data=False,
                preview_data=[],
                error=f"Query no válido: {error_msg}"
            )
        
        try:
            with Timer("Query execution") as timer:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Ejecutar query
                    cursor.execute(sql)
                    
                    # Obtener metadatos
                    columns = [desc[0] for desc in cursor.description]
                    
                    # Obtener datos limitados
                    preview_data = []
                    row_count = 0
                    
                    for row in cursor:
                        if row_count < limit:
                            preview_data.append(list(row))
                        row_count += 1
                        
                        # Salir si alcanzamos el límite + 1 (para saber si hay más datos)
                        if row_count > limit:
                            break
            
            has_more = row_count > limit
            actual_rows = min(row_count, limit)
            
            logger.sql_query(sql, execution_time=timer.elapsed_time)
            
            return QueryResult(
                sql=sql,
                columns=columns,
                row_count=actual_rows,
                execution_time=timer.elapsed_time,
                has_more_data=has_more,
                preview_data=preview_data[:limit]
            )
            
        except Exception as e:
            logger.error(f"Error ejecutando query: {sql}", e)
            return QueryResult(
                sql=sql,
                columns=[],
                row_count=0,
                execution_time=0,
                has_more_data=False,
                preview_data=[],
                error=str(e)
            )
    
    def execute_query_streaming(self, sql: str) -> Iterator[List[Any]]:
        """Ejecutar query con streaming para grandes volúmenes."""
        is_safe, error_msg = SQLValidator.is_safe_query(sql)
        if not is_safe:
            raise ValueError(f"Query no válido: {error_msg}")
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                
                batch_size = config.export.batch_size
                batch = []
                
                for row in cursor:
                    batch.append(list(row))
                    
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                
                # Yield último batch si no está vacío
                if batch:
                    yield batch
                    
        except Exception as e:
            logger.error(f"Error en streaming query: {sql}", e)
            raise
    
    def get_table_sample_data(self, table_name: str, limit: int = 5) -> List[List[Any]]:
        """Obtener muestra de datos de una tabla."""
        try:
            query = f"SELECT FIRST {limit} * FROM {table_name}"
            result = self.execute_query_limited(query, limit)
            
            if result.error:
                return []
            
            return result.preview_data
            
        except Exception as e:
            logger.error(f"Error obteniendo muestra de {table_name}", e)
            return []
    
    def get_table_relationships(self, table_name: str) -> Dict[str, List[Dict[str, Any]]]:
        """Obtener relaciones detalladas de una tabla con otras."""
        try:
            schema = self.get_full_schema()
            if table_name not in schema:
                return {}

            table_info = schema[table_name]
            relationships = {
                'references': [],  # Esta tabla referencia a otras
                'referenced_by': []  # Otras tablas referencian a esta
            }

            # Tablas que esta tabla referencia (foreign keys salientes)
            for fk in table_info.foreign_keys:
                relationships['references'].append({
                    'table': fk['referenced_table'],
                    'columns': fk.get('columns', []),
                    'referenced_columns': fk.get('referenced_columns', []),
                    'constraint_name': fk.get('constraint_name', ''),
                    'type': 'foreign_key'
                })

            # Buscar tablas que referencian a esta (foreign keys entrantes)
            for other_table_name, other_table in schema.items():
                if other_table_name == table_name:
                    continue

                for fk in other_table.foreign_keys:
                    if fk['referenced_table'] == table_name:
                        relationships['referenced_by'].append({
                            'table': other_table_name,
                            'columns': fk.get('columns', []),
                            'referenced_columns': fk.get('referenced_columns', []),
                            'constraint_name': fk.get('constraint_name', ''),
                            'type': 'referenced_by'
                        })

            return relationships

        except Exception as e:
            logger.error(f"Error obteniendo relaciones de {table_name}", e)
            return {}
    
    def close(self):
        """Cerrar todas las conexiones."""
        if self._pool:
            self._pool.close_all()
            self._pool = None
        
        self._is_connected = False
        logger.info("Conexiones cerradas")
    
    def disconnect(self):
        """Alias para close() - desconectar de la base de datos."""
        self.close()
    
    def update_table_stats(self, table_names: List[str] = None, force: bool = False) -> Dict[str, int]:
        """
        Actualizar estadísticas de tablas (conteo de registros).
        
        Args:
            table_names: Lista de nombres de tablas a actualizar. Si es None, actualiza todas.
            force: Si True, fuerza actualización aunque el caché esté fresco.
            
        Returns:
            Diccionario con {table_name: row_count}
        """
        results = {}
        
        try:
            with self.get_connection() as conn:
                # Si no se especifican tablas, obtener todas las del esquema
                if table_names is None:
                    schema = self.get_full_schema()
                    table_names = list(schema.keys())
                
                logger.info(f"Actualizando estadísticas de {len(table_names)} tablas...")
                
                for table_name in table_names:
                    # Verificar si necesita actualización
                    if not force and not self._stats_cache.is_stale(table_name):
                        cached_count = self._stats_cache.get_row_count(table_name)
                        if cached_count is not None:
                            results[table_name] = cached_count
                            continue
                    
                    # Obtener conteo actualizado
                    count = self._get_row_count(conn, table_name, timeout_seconds=5)
                    if count >= 0:
                        results[table_name] = count
                        self._stats_cache.set_row_count(table_name, count)
                        
                        # Actualizar también en el schema_cache si existe
                        schema_key = "full_schema"
                        if schema_key in self._schema_cache and table_name in self._schema_cache[schema_key]:
                            self._schema_cache[schema_key][table_name].row_count = count
                
                logger.info(f"Estadísticas actualizadas: {len(results)} tablas")
                return results
                
        except Exception as e:
            logger.error("Error actualizando estadísticas de tablas", e)
            return results
    
    def get_stats_cache_info(self) -> Dict[str, Any]:
        """
        Obtener información sobre el estado del caché de estadísticas.
        
        Returns:
            Diccionario con información del caché
        """
        cache_info = {
            'total_entries': len(self._stats_cache.cache),
            'ttl_seconds': self._stats_cache.ttl,
            'tables': {}
        }
        
        for table_name in self._stats_cache.cache:
            age = self._stats_cache.get_cache_age(table_name)
            cache_info['tables'][table_name] = {
                'row_count': self._stats_cache.cache[table_name]['count'],
                'age_seconds': age,
                'is_stale': self._stats_cache.is_stale(table_name)
            }
        
        return cache_info


    def test_schema_extraction(self) -> Dict[str, Any]:
        """
        Función de prueba para verificar que la extracción de esquema funciona correctamente.
        Retorna información detallada sobre índices y foreign keys para verificación.

        Returns:
            Diccionario con estadísticas de extracción
        """
        try:
            logger.info("🔍 Probando extracción completa de esquema...")

            # Obtener esquema completo
            schema = self.get_full_schema(force_refresh=True)

            if not schema:
                return {'error': 'No se pudo obtener esquema'}

            # Estadísticas generales
            total_tables = len(schema)
            tables_with_indexes = 0
            tables_with_fks = 0
            total_indexes = 0
            total_fks = 0

            # Análisis detallado de índices y FKs
            index_details = []
            fk_details = []

            for table_name, table_info in schema.items():
                # Contar tablas con índices
                if table_info.indexes:
                    tables_with_indexes += 1
                    total_indexes += len(table_info.indexes)

                    # Detallar índices de esta tabla
                    for idx in table_info.indexes[:3]:  # Solo primeros 3 por tabla
                        index_details.append({
                            'table': table_name,
                            'index_name': idx.get('name', ''),
                            'unique': idx.get('unique', False),
                            'column_count': len(idx.get('columns', [])),
                            'columns': [col.get('name', '') for col in idx.get('columns', [])[:3]]
                        })

                # Contar tablas con foreign keys
                if table_info.foreign_keys:
                    tables_with_fks += 1
                    total_fks += len(table_info.foreign_keys)

                    # Detallar FKs de esta tabla
                    for fk in table_info.foreign_keys[:3]:  # Solo primeros 3 por tabla
                        fk_details.append({
                            'table': table_name,
                            'referenced_table': fk.get('referenced_table', ''),
                            'constraint': fk.get('constraint_name', ''),
                            'column_count': len(fk.get('columns', [])),
                            'columns': fk.get('columns', [])[:3],
                            'referenced_columns': fk.get('referenced_columns', [])[:3]
                        })

            # Probar relaciones bidireccionales
            test_table = None
            for table_name in schema.keys():
                if 'ARTICULOS' in table_name or 'CLIENTES' in table_name or 'VENTAS' in table_name:
                    test_table = table_name
                    break

            relationships = {}
            if test_table:
                relationships = self.get_table_relationships(test_table)

            return {
                'total_tables': total_tables,
                'tables_with_indexes': tables_with_indexes,
                'tables_with_foreign_keys': tables_with_fks,
                'total_indexes': total_indexes,
                'total_foreign_keys': total_fks,
                'index_samples': index_details[:10],  # Solo primeros 10 para no saturar
                'fk_samples': fk_details[:10],  # Solo primeros 10 para no saturar
                'test_table_relationships': relationships,
                'extraction_successful': True
            }

        except Exception as e:
            logger.error(f"Error en prueba de extracción: {e}")
            return {'error': str(e)}

    def get_table_columns_info(self, table_name: str) -> Dict[str, Any]:
        """
        Obtener información detallada de columnas de una tabla específica.
        Útil para debugging y verificación de esquema.

        Args:
            table_name: Nombre de la tabla

        Returns:
            Diccionario con información de columnas
        """
        try:
            with self.get_connection() as conn:
                columns = self._get_table_columns(conn, table_name)

                return {
                    'table_name': table_name,
                    'column_count': len(columns),
                    'columns': [
                        {
                            'name': col['name'],
                            'type': col['data_type'],
                            'nullable': col['nullable'],
                            'length': col.get('length'),
                            'position': col.get('position')
                        }
                        for col in columns[:20]  # Primeras 20 columnas
                    ],
                    'sample_columns': [col['name'] for col in columns[:10]]
                }

        except Exception as e:
            return {
                'table_name': table_name,
                'error': str(e)
            }

    def test_query_embedding_similarity(self, query: str, table_name: str) -> Dict[str, Any]:
        """
        Probar similitud entre una consulta y una tabla específica para debugging RAG.

        Args:
            query: Consulta del usuario
            table_name: Nombre de la tabla a comparar

        Returns:
            Diccionario con similitud y detalles
        """
        try:
            from schema_manager import schema_manager

            # Obtener embedding de la consulta
            query_embedding = schema_manager.embedding_generator.generate_embedding(query)

            # Obtener descripción de la tabla
            if table_name in schema_manager.schema_cache.get('full_schema', {}):
                table_info = schema_manager.schema_cache['full_schema'][table_name]
                sample_data = []
                description = schema_manager.TableDescriptor.describe_table(table_info, sample_data)

                # Obtener embedding de la tabla
                table_embedding = schema_manager.embedding_generator.generate_embedding(description)

                # Calcular similitud coseno manualmente
                import numpy as np
                similarity = np.dot(query_embedding, table_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(table_embedding)
                )

                return {
                    'query': query,
                    'table_name': table_name,
                    'query_embedding_length': len(query_embedding),
                    'table_embedding_length': len(table_embedding),
                    'similarity': float(similarity),
                    'description': description[:200] + "..." if len(description) > 200 else description,
                    'threshold': config.rag.similarity_threshold
                }
            else:
                return {'error': f'Tabla {table_name} no encontrada en esquema'}

        except Exception as e:
            return {'error': str(e)}


# Instancia global de base de datos
db = FirebirdDB()