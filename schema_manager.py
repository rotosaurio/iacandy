"""
Gestor de esquema con sistema RAG para identificar tablas relevantes.

Este módulo implementa un sistema de Retrieval-Augmented Generation (RAG)
que utiliza embeddings vectoriales para encontrar las tablas más relevantes
para una consulta específica.
"""

import json
import time
import threading
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import numpy as np
import pandas as pd

from config import config, StatusMessages
from database import db, TableInfo
from utils import logger, timing_decorator, cache_manager, DataFormatter


# Diccionario de semántica de columnas para enriquecer el contexto RAG
COLUMN_SEMANTICS = {
    'CVE_ART': 'Código de artículo (puede contener valores especiales como GLOBAL, CORTE)',
    'DESCRIPCION1': 'Descripción principal (puede incluir artículos de sistema como VENTA GLOBAL)',
    'TIPO_DOCTO': 'Tipo de documento (F=Factura, T=Ticket, D=Devolución)',
    'UNIDADES': 'Cantidad vendida (debe ser > 0 para ventas reales)',
    'IMPORTE': 'Valor monetario (debe ser > 0 para transacciones válidas)',
    'FECHA': 'Fecha de la transacción (formato DATE)',
    'FOLIO': 'Número de documento (no confundir con SERIE)',
    'CLIENTE_ID': 'Identificador único del cliente',
    'ARTICULO_ID': 'Identificador único del artículo',
    'ALMACEN_ID': 'Identificador del almacén',
    'PROVEEDOR_ID': 'Identificador del proveedor',
    'NOMBRE': 'Nombre del artículo o entidad (verificar si contiene palabras de sistema)',
    'EXISTENCIA': 'Cantidad disponible en inventario',
    'PRECIO': 'Precio unitario del artículo',
    'COSTO': 'Costo del artículo para compras',
    'SERIE': 'Campo especial - NO existe en DOCTOS_PV, DOCTOS_VE, DOCTOS_CC (solo TIPO_DOCTO + FOLIO)',
    'FECHA_DOCUMENTO': 'Campo especial - NO existe en DOCTOS_PV, DOCTOS_VE (solo FECHA)',
}


class EmbeddingGenerator:
    """Generador de embeddings usando SentenceTransformers."""
    
    def __init__(self):
        self.model = None
        self._model_lock = threading.Lock()
    
    def _load_model(self):
        """Cargar modelo de embeddings lazy loading."""
        if self.model is None:
            with self._model_lock:
                if self.model is None:
                    logger.info(f"Cargando modelo de embeddings: {config.rag.embeddings_model}")
                    self.model = SentenceTransformer(config.rag.embeddings_model)
                    logger.info("Modelo de embeddings cargado")
    
    def generate_embedding(self, text: str) -> List[float]:
        """Generar embedding para un texto."""
        self._load_model()
        
        if not text or not text.strip():
            return [0.0] * 384  # Dimensiones del modelo all-MiniLM-L6-v2
        
        embedding = self.model.encode(text.strip())
        return embedding.tolist()
    
    def generate_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generar embeddings para múltiples textos."""
        self._load_model()
        
        if not texts:
            return []
        
        # Filtrar textos vacíos
        clean_texts = [text.strip() if text else "" for text in texts]
        embeddings = self.model.encode(clean_texts)
        return [emb.tolist() for emb in embeddings]


class TableDescriptor:
    """Generador de descripciones semánticas de tablas."""
    
    # Cargar diccionario de MicroSIP si existe
    _microsip_dict = None
    
    @classmethod
    def _load_microsip_dict(cls):
        """Cargar diccionario de MicroSIP una sola vez."""
        if cls._microsip_dict is None:
            try:
                import os
                dict_path = os.path.join(os.path.dirname(__file__), 'microsip_dictionary.json')
                if os.path.exists(dict_path):
                    with open(dict_path, 'r', encoding='utf-8') as f:
                        cls._microsip_dict = json.load(f)
                        logger.info("Diccionario de MicroSIP cargado exitosamente")
                else:
                    cls._microsip_dict = {}
            except Exception as e:
                logger.warning(f"No se pudo cargar diccionario de MicroSIP: {e}")
                cls._microsip_dict = {}
        return cls._microsip_dict
    
    @classmethod
    def describe_table(cls, table_info: TableInfo, sample_data: List[List[Any]] = None) -> str:
        """Generar descripción semántica enriquecida de una tabla."""
        description_parts = []

        # Cargar diccionario de MicroSIP
        microsip_dict = cls._load_microsip_dict()

        # Nombre de tabla procesado
        table_name = table_info.name.lower()
        table_name_upper = table_info.name.upper()

        # === PARTE 1: PROPÓSITO DE NEGOCIO (lo más importante para embeddings) ===
        business_purpose = cls._infer_business_purpose(table_name, table_info.columns)
        if business_purpose:
            description_parts.append(business_purpose)

        # Información de MicroSIP para keywords adicionales
        if microsip_dict and 'tablas' in microsip_dict and table_name_upper in microsip_dict['tablas']:
            ms_info = microsip_dict['tablas'][table_name_upper]
            categoria = ms_info.get('categoria', '')

            if categoria and categoria != 'OTROS':
                description_parts.append(f"Categoría: {categoria.lower().replace('_', ' ')}")

            # Agregar keywords de búsqueda de MicroSIP
            if 'keywords_busqueda' in microsip_dict and table_name_upper in microsip_dict['keywords_busqueda']:
                keywords = microsip_dict['keywords_busqueda'][table_name_upper][:10]
                description_parts.append(f"Búsquedas comunes: {', '.join(keywords)}")

        # === PARTE 2: ANÁLISIS SEMÁNTICO DE CONTENIDO ===
        semantic_summary = cls._generate_semantic_summary(table_info.columns)
        if semantic_summary:
            description_parts.append(semantic_summary)

        # === PARTE 3: DATOS DE MUESTRA (si están disponibles) ===
        if sample_data and table_info.columns:
            sample_desc = cls._describe_sample_data_enriched(table_info.columns, sample_data)
            if sample_desc:
                description_parts.append(f"Ejemplos: {sample_desc}")

            # Análisis de patrones avanzados
            patterns = cls._analyze_data_patterns(table_info.columns, sample_data)
            if patterns:
                description_parts.append(f"Características: {patterns}")

        # === PARTE 4: RELACIONES Y CONTEXTO ===
        relationship_desc = cls._describe_relationships(table_info.foreign_keys)
        if relationship_desc:
            description_parts.append(relationship_desc)

        # === PARTE 5: CAMPOS CLAVE ===
        key_fields_desc = cls._describe_key_fields(table_info.columns, table_info.primary_keys)
        if key_fields_desc:
            description_parts.append(key_fields_desc)

        # === PARTE 6: METADATOS TÉCNICOS (menos peso para embeddings) ===
        if table_info.row_count > 0:
            volume_desc = cls._describe_data_volume(table_info.row_count)
            description_parts.append(f"Volumen: {volume_desc}")

        # === PARTE 7: OPTIMIZACIÓN PARA EMBEDDINGS ===
        # Unir con separadores optimizados para modelos de embeddings
        # El separador " | " ayuda a que el modelo sentence-transformer
        # mantenga la estructura semántica de cada segmento
        full_description = " | ".join(description_parts)

        # Agregar sinónimos y términos de búsqueda para mejorar recall
        search_terms = cls._generate_search_terms(table_name, table_info.columns)
        if search_terms:
            full_description += f" | Términos: {search_terms}"

        return full_description
    
    @staticmethod
    def _infer_business_purpose(table_name: str, columns: List[Dict[str, Any]]) -> str:
        """
        Inferir el propósito de negocio combinando nombre de tabla y análisis de columnas.
        Genera descripciones orientadas al negocio, no técnicas.
        """
        name_lower = table_name.lower()
        col_names = [col['name'].lower() for col in columns]
        col_names_str = ' '.join(col_names)

        # Detectar tipo de tabla por patrón de columnas + nombre
        purposes = []

        # Transacciones de venta
        if any(k in name_lower for k in ['venta', 'factura', 'ticket', 'pos', 'doctos_pv', 'doctos_ve']):
            if any(k in col_names_str for k in ['importe', 'precio', 'unidades', 'cantidad']):
                purposes.append("Registra transacciones de venta")
                if 'det' in name_lower or 'detalle' in name_lower:
                    purposes.append("Detalle de productos vendidos en cada operación")
                else:
                    purposes.append("Encabezado de documentos de venta con cliente, fecha y totales")

        # Clientes
        elif any(k in name_lower for k in ['cliente', 'customer']):
            purposes.append("Información de clientes y compradores")
            if 'direccion' in col_names_str or 'domicilio' in col_names_str:
                purposes.append("Incluye datos de contacto y ubicación")

        # Productos/Artículos
        elif any(k in name_lower for k in ['articulo', 'producto', 'item']):
            purposes.append("Catálogo de productos y artículos comercializados")
            if 'precio' in col_names_str:
                purposes.append("Contiene precios y características de venta")
            if 'existencia' in col_names_str or 'stock' in col_names_str:
                purposes.append("Incluye información de inventario disponible")

        # Inventario y existencias
        elif any(k in name_lower for k in ['existencia', 'inventario', 'stock']):
            purposes.append("Control de inventario y cantidades disponibles por almacén")
            if 'movimiento' in name_lower or 'movto' in name_lower:
                purposes.append("Registra movimientos de entrada y salida de mercancía")

        # Compras
        elif any(k in name_lower for k in ['compra', 'purchase', 'orden_compra']):
            purposes.append("Gestión de compras y adquisiciones")
            if 'proveedor' in col_names_str:
                purposes.append("Relaciona órdenes con proveedores")

        # Proveedores
        elif any(k in name_lower for k in ['proveedor', 'vendor', 'supplier']):
            purposes.append("Información de proveedores y vendedores")

        # Empleados/Personal
        elif any(k in name_lower for k in ['empleado', 'employee', 'personal', 'vendedor']):
            purposes.append("Datos de empleados y personal de la empresa")

        # Pagos y cobranza
        elif any(k in name_lower for k in ['pago', 'cobranza', 'abono']):
            purposes.append("Gestión de pagos y cobranzas")
            if 'saldo' in col_names_str:
                purposes.append("Incluye seguimiento de saldos y deudas")

        # Catálogos
        elif any(k in name_lower for k in ['categoria', 'grupo', 'familia', 'linea', 'marca', 'tipo']):
            purposes.append("Catálogo de clasificación y agrupación")

        # Configuración
        elif any(k in name_lower for k in ['config', 'parametro', 'param']):
            purposes.append("Configuración y parámetros del sistema")

        # Si no detectamos nada específico, análisis genérico
        if not purposes:
            if 'fecha' in col_names_str and ('importe' in col_names_str or 'monto' in col_names_str):
                purposes.append("Registros transaccionales con fechas y valores monetarios")
            elif 'nombre' in col_names_str or 'descripcion' in col_names_str:
                purposes.append("Catálogo o maestro de datos")
            else:
                purposes.append(f"Tabla {table_name}")

        return ". ".join(purposes)

    @staticmethod
    def _generate_semantic_summary(columns: List[Dict[str, Any]]) -> str:
        """
        Generar resumen semántico enfocado en QUÉ información contiene, no cómo se estructura.
        """
        col_names = [col['name'].lower() for col in columns]
        col_names_str = ' '.join(col_names)

        semantic_elements = []

        # Identificadores
        ids = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['_id', 'codigo', 'cve_', 'clave'])]
        if ids:
            semantic_elements.append(f"Identificadores: {', '.join(ids[:5])}")

        # Datos monetarios
        monetary = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['precio', 'importe', 'costo', 'monto', 'total', 'subtotal'])]
        if monetary:
            semantic_elements.append(f"Valores monetarios: {', '.join(monetary[:5])}")

        # Cantidades
        quantities = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['cantidad', 'unidades', 'qty', 'existencia', 'stock'])]
        if quantities:
            semantic_elements.append(f"Cantidades: {', '.join(quantities[:3])}")

        # Fechas
        dates = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['fecha', 'date', 'timestamp', 'hora'])]
        if dates:
            semantic_elements.append(f"Fechas: {', '.join(dates[:3])}")

        # Personas
        persons = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['cliente', 'proveedor', 'empleado', 'vendedor', 'usuario'])]
        if persons:
            semantic_elements.append(f"Personas/Entidades: {', '.join(persons[:3])}")

        # Descripciones/Nombres
        descriptions = [col['name'] for col in columns if any(k in col['name'].lower() for k in ['nombre', 'descripcion', 'name', 'desc'])]
        if descriptions:
            semantic_elements.append(f"Descripciones: {', '.join(descriptions[:3])}")

        return " | ".join(semantic_elements)

    @staticmethod
    def _describe_sample_data_enriched(columns: List[Dict[str, Any]], sample_data: List[List[Any]]) -> str:
        """
        Describir datos de muestra con enfoque en PATRONES y CONTENIDO real, no estadísticas.
        """
        if not sample_data or not columns:
            return ""

        descriptions = []

        for i, col in enumerate(columns[:8]):  # Primeras 8 columnas
            if i >= len(sample_data[0]):
                continue

            col_name = col['name']
            sample_values = [row[i] for row in sample_data[:10] if i < len(row) and row[i] is not None]

            if not sample_values:
                continue

            # Para textos, mostrar ejemplos reales
            if col['data_type'] in ['VARCHAR', 'CHAR']:
                unique_values = list(set(str(v) for v in sample_values))[:5]
                if len(unique_values) <= 5 and all(len(str(v)) < 50 for v in unique_values):
                    descriptions.append(f"{col_name}: \"{', '.join(unique_values)}\"")
                elif unique_values:
                    # Mostrar patrón
                    first_val = str(unique_values[0])
                    if first_val:
                        descriptions.append(f"{col_name} ejemplo: \"{first_val[:40]}\"")

            # Para números, mostrar rango significativo
            elif col['data_type'] in ['INTEGER', 'SMALLINT', 'BIGINT', 'DECIMAL', 'NUMERIC']:
                try:
                    numeric_vals = [float(v) for v in sample_values if v is not None]
                    if numeric_vals:
                        min_val = min(numeric_vals)
                        max_val = max(numeric_vals)
                        avg_val = sum(numeric_vals) / len(numeric_vals)
                        if min_val == max_val:
                            descriptions.append(f"{col_name}: {min_val}")
                        else:
                            descriptions.append(f"{col_name}: rango {min_val:.2f} a {max_val:.2f}")
                except:
                    pass

            # Para fechas, mostrar rango temporal
            elif col['data_type'] in ['DATE', 'TIMESTAMP']:
                try:
                    date_strs = [str(v) for v in sample_values if v]
                    if date_strs:
                        first_date = date_strs[0][:10] if len(date_strs[0]) >= 10 else date_strs[0]
                        last_date = date_strs[-1][:10] if len(date_strs[-1]) >= 10 else date_strs[-1]
                        if first_date == last_date:
                            descriptions.append(f"{col_name}: {first_date}")
                        else:
                            descriptions.append(f"{col_name}: desde {first_date}")
                except:
                    pass

        return " | ".join(descriptions[:6])  # Máximo 6 descripciones

    @staticmethod
    def _describe_relationships(foreign_keys: List[Dict[str, Any]]) -> str:
        """Describir relaciones en lenguaje de negocio."""
        if not foreign_keys:
            return ""

        relationships = []
        for fk in foreign_keys[:5]:  # Primeras 5 FKs
            ref_table = fk.get('referenced_table', '')
            columns = fk.get('columns', [])

            if ref_table and columns:
                # Traducir a lenguaje de negocio
                col_name = columns[0].lower() if columns else ''
                if 'cliente' in col_name:
                    relationships.append(f"vinculada a clientes ({ref_table})")
                elif 'articulo' in col_name or 'producto' in col_name:
                    relationships.append(f"vinculada a productos ({ref_table})")
                elif 'proveedor' in col_name:
                    relationships.append(f"vinculada a proveedores ({ref_table})")
                elif 'almacen' in col_name:
                    relationships.append(f"vinculada a almacenes ({ref_table})")
                else:
                    relationships.append(f"relacionada con {ref_table}")

        if relationships:
            return "Relaciones: " + ", ".join(relationships)
        return ""

    @staticmethod
    def _describe_key_fields(columns: List[Dict[str, Any]], primary_keys: List[str]) -> str:
        """Describir campos clave de manera semántica."""
        key_desc = []

        # Primary keys
        if primary_keys:
            key_desc.append(f"Clave: {', '.join(primary_keys[:3])}")

        # Campos requeridos importantes (NOT NULL)
        required = [col['name'] for col in columns if not col.get('nullable', True)]
        important_required = [r for r in required if r not in primary_keys and len(r) < 25][:5]
        if important_required:
            key_desc.append(f"Obligatorios: {', '.join(important_required)}")

        return " | ".join(key_desc)

    @staticmethod
    def _describe_data_volume(row_count: int) -> str:
        """Describir volumen de datos en términos de negocio."""
        if row_count < 100:
            return f"catálogo pequeño ({row_count} registros)"
        elif row_count < 1000:
            return f"catálogo mediano ({row_count} registros)"
        elif row_count < 10000:
            return f"volumen moderado ({DataFormatter.format_number(row_count)} registros)"
        elif row_count < 100000:
            return f"volumen alto ({DataFormatter.format_number(row_count)} registros)"
        else:
            return f"volumen muy alto ({DataFormatter.format_number(row_count)} registros)"

    @staticmethod
    def _generate_search_terms(table_name: str, columns: List[Dict[str, Any]]) -> str:
        """
        Generar términos de búsqueda adicionales y sinónimos para mejorar recuperación.
        Estos términos ayudan a que la búsqueda vectorial capture consultas con vocabulario variado.
        """
        search_terms = set()
        name_lower = table_name.lower()
        col_names = [col['name'].lower() for col in columns]

        # Sinónimos por tipo de tabla
        synonyms_map = {
            'venta': ['vender', 'vendido', 'transacción', 'ingreso', 'ticket', 'factura', 'cobro'],
            'cliente': ['comprador', 'consumidor', 'usuario final', 'socio comercial'],
            'articulo': ['producto', 'mercancía', 'ítem', 'SKU', 'inventario'],
            'proveedor': ['vendor', 'supplier', 'abastecedor', 'distribuidor'],
            'inventario': ['existencia', 'stock', 'almacén', 'bodega', 'disponible'],
            'compra': ['adquisición', 'orden de compra', 'procurement', 'abastecimiento'],
            'precio': ['costo', 'importe', 'valor', 'monto', 'tarifa'],
            'pago': ['abono', 'cobranza', 'liquidación', 'transacción financiera'],
            'empleado': ['trabajador', 'personal', 'colaborador', 'staff'],
            'pedido': ['orden', 'solicitud', 'requerimiento', 'order'],
            'factura': ['invoice', 'comprobante', 'documento fiscal'],
        }

        # Agregar sinónimos basados en el nombre de la tabla
        for key, synonyms in synonyms_map.items():
            if key in name_lower:
                search_terms.update(synonyms[:4])  # Máximo 4 sinónimos por categoría

        # Sinónimos por columnas presentes
        if any('fecha' in col or 'date' in col for col in col_names):
            search_terms.update(['temporal', 'histórico', 'cronológico'])

        if any('importe' in col or 'precio' in col or 'monto' in col for col in col_names):
            search_terms.update(['financiero', 'monetario', 'económico'])

        if any('cantidad' in col or 'unidades' in col for col in col_names):
            search_terms.update(['volumen', 'conteo', 'suma'])

        # Términos de análisis comunes
        if 'det' in name_lower or 'detalle' in name_lower:
            search_terms.update(['línea', 'ítem', 'movimiento individual', 'partida'])

        if any(k in name_lower for k in ['encab', 'header', 'docto']):
            search_terms.update(['documento', 'cabecera', 'resumen'])

        # Limitar a los términos más relevantes
        return ', '.join(list(search_terms)[:15])

    @staticmethod
    def _infer_table_purpose(table_name: str) -> Optional[str]:
        """Inferir el propósito de una tabla por su nombre."""
        name_lower = table_name.lower()
        
        purpose_keywords = {
            # Comercial y ventas
            'ventas': 'ventas y transacciones comerciales',
            'venta': 'ventas y transacciones comerciales',
            'facturas': 'facturación',
            'factura': 'facturación',
            'pedidos': 'gestión de pedidos',
            'pedido': 'gestión de pedidos',
            'cotizaciones': 'cotizaciones y presupuestos',
            'cotizacion': 'cotizaciones y presupuestos',
            'remisiones': 'remisiones y entregas',
            'remision': 'remisiones y entregas',
            
            # Clientes y proveedores
            'clientes': 'información de clientes',
            'cliente': 'información de clientes',
            'proveedores': 'información de proveedores',
            'proveedor': 'información de proveedores',
            'contactos': 'contactos y relaciones',
            'contacto': 'contactos y relaciones',
            
            # Productos e inventario
            'productos': 'catálogo de productos y artículos',
            'producto': 'catálogo de productos y artículos',
            'articulos': 'catálogo de productos y artículos',
            'articulo': 'catálogo de productos y artículos',
            'items': 'catálogo de productos y artículos',
            'inventario': 'control de inventarios y existencias',
            'existencias': 'control de inventarios y existencias',
            'stock': 'control de inventarios y existencias',
            'almacen': 'gestión de almacenes',
            'almacenes': 'gestión de almacenes',
            'bodega': 'gestión de almacenes',
            'bodegas': 'gestión de almacenes',
            'movimientos': 'movimientos de inventario',
            'movimiento': 'movimientos de inventario',
            
            # Personal
            'empleados': 'información de empleados',
            'empleado': 'información de empleados',
            'personal': 'información de empleados',
            'usuarios': 'gestión de usuarios',
            'usuario': 'gestión de usuarios',
            
            # Financiero
            'pagos': 'gestión de pagos',
            'pago': 'gestión de pagos',
            'cobranza': 'cobranza y cuentas por cobrar',
            'cobranzas': 'cobranza y cuentas por cobrar',
            'cuentas': 'cuentas y contabilidad',
            'cuenta': 'cuentas y contabilidad',
            'movtos': 'movimientos financieros',
            'bancos': 'movimientos bancarios',
            'banco': 'movimientos bancarios',
            
            # Catálogos
            'categorias': 'categorización y clasificación',
            'categoria': 'categorización y clasificación',
            'grupos': 'agrupación y clasificación',
            'grupo': 'agrupación y clasificación',
            'tipos': 'tipos y clasificaciones',
            'tipo': 'tipos y clasificaciones',
            'familias': 'familias de productos',
            'familia': 'familias de productos',
            'lineas': 'líneas de productos',
            'linea': 'líneas de productos',
            'marcas': 'marcas de productos',
            'marca': 'marcas de productos',
            
            # Ubicación
            'zonas': 'zonas geográficas',
            'zona': 'zonas geográficas',
            'rutas': 'rutas de distribución',
            'ruta': 'rutas de distribución',
            'sucursales': 'sucursales y ubicaciones',
            'sucursal': 'sucursales y ubicaciones',
            
            # Sistema
            'logs': 'registro de eventos y auditoría',
            'log': 'registro de eventos y auditoría',
            'configuracion': 'configuración del sistema',
            'config': 'configuración del sistema',
            'parametros': 'parámetros del sistema',
            'parametro': 'parámetros del sistema',
            'reportes': 'generación de reportes',
            'reporte': 'generación de reportes',
            'audit': 'auditoría del sistema',
            'auditoria': 'auditoría del sistema',
            'temp': 'datos temporales',
            'temporal': 'datos temporales',
            'backup': 'respaldo de datos',
            'respaldo': 'respaldo de datos',
            
            # Documentos
            'documentos': 'documentos y archivos',
            'documento': 'documentos y archivos',
            'notas': 'notas y comentarios',
            'nota': 'notas y comentarios',
            
            # Procesos
            'compras': 'compras y adquisiciones',
            'compra': 'compras y adquisiciones',
            'produccion': 'producción y manufactura',
            'ordenes': 'órdenes de trabajo',
            'orden': 'órdenes de trabajo',
        }
        
        for keyword, purpose in purpose_keywords.items():
            if keyword in name_lower:
                return purpose
        
        return None
    
    @staticmethod
    def _identify_key_columns(columns: List[Dict[str, Any]]) -> List[str]:
        """Identificar columnas clave de una tabla."""
        key_columns = []
        
        for col in columns[:10]:  # Solo primeras 10 columnas
            col_name = col['name'].lower()
            
            # IDs y claves
            if any(keyword in col_name for keyword in ['id', 'key', 'codigo', 'code']):
                key_columns.append(col['name'])
            
            # Nombres y descripciones
            elif any(keyword in col_name for keyword in ['nombre', 'name', 'descripcion', 'desc']):
                key_columns.append(col['name'])
            
            # Fechas importantes
            elif any(keyword in col_name for keyword in ['fecha', 'date', 'time', 'created', 'updated']):
                key_columns.append(col['name'])
            
            # Montos y cantidades
            elif any(keyword in col_name for keyword in ['monto', 'amount', 'cantidad', 'qty', 'precio', 'price']):
                key_columns.append(col['name'])
        
        return key_columns[:5]  # Máximo 5 columnas clave
    
    @staticmethod
    def _identify_semantic_fields(columns: List[Dict[str, Any]]) -> List[str]:
        """Identificar tipos semánticos de campos para mejorar búsqueda RAG."""
        semantic_types = set()
        
        field_semantics = {
            'identificación': ['id', 'codigo', 'code', 'clave', 'key', 'folio', 'numero'],
            'nombres y descripciones': ['nombre', 'name', 'descripcion', 'desc', 'titulo', 'title'],
            'fechas y tiempos': ['fecha', 'date', 'time', 'hora', 'timestamp', 'created', 'updated', 'modified'],
            'importes y precios': ['precio', 'price', 'monto', 'amount', 'importe', 'costo', 'cost', 'total', 'subtotal'],
            'cantidades': ['cantidad', 'qty', 'quantity', 'stock', 'existencia', 'unidades'],
            'estados': ['status', 'estado', 'activo', 'active', 'vigente', 'eliminado', 'deleted'],
            'personas': ['cliente', 'customer', 'proveedor', 'vendor', 'empleado', 'employee', 'usuario', 'user'],
            'ubicaciones': ['direccion', 'address', 'ciudad', 'city', 'pais', 'country', 'zona', 'region', 'almacen', 'warehouse'],
            'contacto': ['email', 'mail', 'telefono', 'phone', 'celular', 'mobile', 'contacto', 'contact'],
            'financiero': ['pago', 'payment', 'saldo', 'balance', 'credito', 'credit', 'deuda', 'debt'],
            'impuestos': ['iva', 'tax', 'impuesto', 'ieps', 'retencion'],
            'documentos': ['factura', 'invoice', 'pedido', 'order', 'nota', 'recibo', 'receipt', 'documento', 'document'],
        }
        
        for col in columns:
            col_name = col['name'].lower()
            for semantic_category, keywords in field_semantics.items():
                if any(keyword in col_name for keyword in keywords):
                    semantic_types.add(semantic_category)
        
        return sorted(list(semantic_types))
    
    @staticmethod
    def _describe_sample_data(columns: List[Dict[str, Any]], sample_data: List[List[Any]]) -> str:
        """Describir datos de muestra (método antiguo, mantenido por compatibilidad)."""
        # Redirigir al nuevo método enriquecido
        return TableDescriptor._describe_sample_data_enriched(columns, sample_data)

    @staticmethod
    def _analyze_data_patterns(columns: List[Dict[str, Any]], sample_data: List[List[Any]]) -> str:
        """
        Analizar patrones avanzados en datos para detectar características especiales.
        Ejemplos: tablas transaccionales vs maestros, datos históricos vs actuales, etc.
        """
        if not sample_data or not columns:
            return ""

        patterns = []

        # Analizar distribución temporal
        date_cols = [(i, col) for i, col in enumerate(columns) if 'DATE' in col.get('data_type', '') or 'TIMESTAMP' in col.get('data_type', '')]
        if date_cols:
            for col_idx, col in date_cols[:2]:  # Primeras 2 columnas de fecha
                try:
                    date_values = [row[col_idx] for row in sample_data if col_idx < len(row) and row[col_idx]]
                    if date_values:
                        date_strs = [str(d) for d in date_values]
                        first = date_strs[0][:10] if len(date_strs[0]) >= 10 else date_strs[0]
                        last = date_strs[-1][:10] if len(date_strs[-1]) >= 10 else date_strs[-1]

                        # Detectar si son fechas recientes (datos operacionales)
                        if '2024' in last or '2025' in last:
                            patterns.append("datos operacionales actuales")
                        elif first != last:
                            patterns.append(f"datos desde {first[:4]}")
                except:
                    pass

        # Detectar si es tabla transaccional (tiene ID secuencial + fecha)
        has_sequential_id = False
        for i, col in enumerate(columns[:5]):
            if any(k in col['name'].lower() for k in ['_id', 'id', 'folio', 'numero']):
                try:
                    ids = [row[i] for row in sample_data[:10] if i < len(row) and row[i] is not None]
                    if len(ids) >= 3:
                        numeric_ids = [int(v) for v in ids if str(v).isdigit()]
                        if len(numeric_ids) >= 3:
                            # Verificar si son secuenciales
                            diffs = [numeric_ids[i+1] - numeric_ids[i] for i in range(len(numeric_ids)-1)]
                            avg_diff = sum(diffs) / len(diffs) if diffs else 0
                            if 0 < avg_diff < 100:  # Diferencias pequeñas = secuencial
                                has_sequential_id = True
                                patterns.append("registros secuenciales")
                                break
                except:
                    pass

        # Detectar si es catálogo (pocos registros únicos en columnas clave)
        is_catalog = False
        for i, col in enumerate(columns[:3]):
            if 'nombre' in col['name'].lower() or 'descripcion' in col['name'].lower():
                try:
                    values = [row[i] for row in sample_data if i < len(row) and row[i]]
                    unique_count = len(set(str(v) for v in values))
                    if unique_count == len(values) and len(values) < 20:
                        is_catalog = True
                        patterns.append("catálogo maestro")
                        break
                except:
                    pass

        # Detectar campos monetarios significativos
        monetary_cols = [col for col in columns if any(k in col['name'].lower() for k in ['precio', 'importe', 'total', 'costo', 'monto'])]
        if monetary_cols and len(monetary_cols) >= 2:
            patterns.append("gestión financiera")

        # Detectar si tiene campos de auditoría
        audit_fields = [col for col in columns if any(k in col['name'].lower() for k in ['creado', 'modificado', 'usuario', 'created', 'updated'])]
        if audit_fields:
            patterns.append("con auditoría")

        return " | ".join(patterns) if patterns else ""


class VectorStore:
    """Almacén vectorial usando ChromaDB."""
    
    def __init__(self):
        self.client = None
        self.collection = None
        self._initialized = False
    
    def initialize(self):
        """Inicializar ChromaDB."""
        if self._initialized:
            return
        
        try:
            logger.info("Inicializando almacén vectorial ChromaDB...")
            
            # Configurar ChromaDB con nueva API (sin configuración deprecated)
            self.client = chromadb.PersistentClient(
                path=config.rag.vector_db_path
            )
            
            # Obtener o crear colección con función de distancia COSINE
            try:
                self.collection = self.client.get_collection(name="schema_embeddings")
                logger.info("Colección existente encontrada")
            except:
                # IMPORTANTE: Usar 'cosine' distance para embeddings normalizados
                self.collection = self.client.create_collection(
                    name="schema_embeddings",
                    metadata={"hnsw:space": "cosine"}  # Usar distancia coseno
                )
                logger.info("Nueva colección creada con distancia coseno")
            
            self._initialized = True
            logger.info("Almacén vectorial inicializado")
            
        except Exception as e:
            logger.error("Error inicializando ChromaDB", e)
            raise
    
    def add_table_embeddings(self, table_embeddings: Dict[str, Dict[str, Any]]):
        """Agregar embeddings de tablas al almacén."""
        if not self._initialized:
            self.initialize()
        
        try:
            # Preparar datos para ChromaDB
            ids = list(table_embeddings.keys())
            embeddings = [data['embedding'] for data in table_embeddings.values()]
            metadatas = [
                {
                    'table_name': table_name,
                    'description': data['description'],
                    'row_count': data.get('row_count', 0),
                    'is_active': data.get('is_active', True),
                    'column_count': data.get('column_count', 0),
                    'has_foreign_keys': data.get('has_foreign_keys', False),
                    'created_at': datetime.now().isoformat()
                }
                for table_name, data in table_embeddings.items()
            ]
            documents = [data['description'] for data in table_embeddings.values()]
            
            # Limpiar IDs existentes para evitar duplicados
            try:
                existing_ids = self.collection.get()['ids']
                if existing_ids:
                    # Eliminar IDs que vamos a reemplazar
                    ids_to_delete = [id for id in ids if id in existing_ids]
                    if ids_to_delete:
                        self.collection.delete(ids=ids_to_delete)
            except:
                pass
            
            # Agregar embeddings en lotes usando upsert para evitar duplicados
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i + batch_size]
                batch_embeddings = embeddings[i:i + batch_size]
                batch_metadatas = metadatas[i:i + batch_size]
                batch_documents = documents[i:i + batch_size]
                
                self.collection.upsert(
                    ids=batch_ids,
                    embeddings=batch_embeddings,
                    metadatas=batch_metadatas,
                    documents=batch_documents
                )
            
            logger.info(f"Agregados {len(ids)} embeddings de tablas al almacén vectorial")
            
        except Exception as e:
            logger.error("Error agregando embeddings al almacén", e)
            raise
    
    def search_similar_tables(self, query_embedding: List[float], 
                            top_k: int = None, 
                            filter_active: bool = True) -> List[Dict[str, Any]]:
        """Buscar tablas similares usando embedding de consulta."""
        if not self._initialized:
            self.initialize()
        
        if top_k is None:
            top_k = config.rag.top_k_tables
        
        try:
            # Preparar filtros
            where_filter = {}
            if filter_active:
                where_filter["is_active"] = True
            
            # Buscar vectores similares
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter if where_filter else None
            )
            
            # Procesar resultados
            similar_tables = []
            
            if results['ids'] and results['ids'][0]:
                logger.info(f"ChromaDB retornó {len(results['ids'][0])} resultados candidatos")
                
                for i in range(len(results['ids'][0])):
                    table_info = {
                        'table_name': results['ids'][0][i],
                        'description': results['documents'][0][i],
                        'similarity': 1 - results['distances'][0][i],  # ChromaDB usa distancia coseno
                        'metadata': results['metadatas'][0][i]
                    }
                    
                    # Logging detallado de similaridad
                    logger.debug(f"Tabla: {table_info['table_name']}, Similaridad: {table_info['similarity']:.3f}, Threshold: {config.rag.similarity_threshold}")
                    
                    # Solo incluir si supera threshold
                    if table_info['similarity'] >= config.rag.similarity_threshold:
                        similar_tables.append(table_info)
                        logger.debug(f"✓ Tabla {table_info['table_name']} incluida (similaridad: {table_info['similarity']:.3f})")
                    else:
                        logger.debug(f"✗ Tabla {table_info['table_name']} excluida (similaridad: {table_info['similarity']:.3f} < {config.rag.similarity_threshold})")
            else:
                logger.warning("ChromaDB no retornó ningún resultado")
            
            logger.info(f"Encontradas {len(similar_tables)} de {len(results['ids'][0]) if results['ids'] and results['ids'][0] else 0} tablas que superan threshold {config.rag.similarity_threshold}")
            return similar_tables
            
        except Exception as e:
            logger.error("Error buscando tablas similares", e)
            return []
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Obtener estadísticas de la colección."""
        if not self._initialized:
            return {}
        
        try:
            count = self.collection.count()
            return {
                'total_tables': count,
                'collection_name': 'schema_embeddings',
                'initialized': self._initialized
            }
        except Exception as e:
            logger.error("Error obteniendo estadísticas de colección", e)
            return {}


class SchemaManager:
    """Gestor principal del esquema con capacidades RAG."""
    
    def __init__(self):
        self.embedding_generator = EmbeddingGenerator()
        self.vector_store = VectorStore()
        self.schema_cache = {}
        self.last_schema_update = None
        self.active_tables_cache = None
        self.relationships_graph = None
        self._load_relationships_graph()
        
        # Auto-actualización
        self.auto_update_interval = 12 * 3600  # 12 horas en segundos
        self._auto_update_thread = None
        self._stop_auto_update = threading.Event()
        self.start_auto_update_thread()
    
    def _load_relationships_graph(self):
        """Cargar grafo de relaciones de MicroSIP"""
        try:
            import os
            rel_path = os.path.join(os.path.dirname(__file__), 'microsip_relationships.json')
            if os.path.exists(rel_path):
                with open(rel_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.relationships_graph = data.get('graph', {})
                    logger.info(f"Grafo de relaciones cargado: {len(self.relationships_graph)} tablas con relaciones")
            else:
                self.relationships_graph = {}
                logger.warning("No se encontró microsip_relationships.json, continuando sin expansión de relaciones")
        except Exception as e:
            logger.warning(f"Error cargando grafo de relaciones: {e}")
            self.relationships_graph = {}
    
    def _get_fk_related_tables(self, table_name: str) -> List[str]:
        """
        Obtener tablas relacionadas a través de foreign keys.
        
        Args:
            table_name: Nombre de la tabla
            
        Returns:
            Lista de nombres de tablas relacionadas por FK
        """
        related = []
        
        if not self.schema_cache or 'full_schema' not in self.schema_cache:
            return related
        
        full_schema = self.schema_cache['full_schema']
        
        if table_name not in full_schema:
            return related
        
        table_info = full_schema[table_name]
        
        # Tablas referenciadas (padres)
        for fk in table_info.foreign_keys:
            ref_table = fk.get('referenced_table')
            if ref_table and ref_table not in related:
                related.append(ref_table)
        
        # Tablas que referencian a esta (hijos)
        for other_table_name, other_table_info in full_schema.items():
            if other_table_name == table_name:
                continue
            
            for fk in other_table_info.foreign_keys:
                if fk.get('referenced_table') == table_name and other_table_name not in related:
                    related.append(other_table_name)
        
        return related
    
    def _adjust_scores_by_context(self, tables: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """
        Ajustar scores de tablas basado en contexto adicional.
        
        Args:
            tables: Lista de tablas con scores
            query: Consulta original del usuario
            
        Returns:
            Lista de tablas con scores ajustados
        """
        query_lower = query.lower()
        
        for table in tables:
            original_score = table['similarity_score']
            adjustments = 0
            
            # Penalizar tablas vacías
            if table.get('row_count', 0) == 0:
                adjustments -= 0.2
            
            # Bonificar tablas con muchos registros (posiblemente activas)
            elif table.get('row_count', 0) > 1000:
                adjustments += 0.1
            
            # Bonificar si tiene FKs (mejor conectividad)
            if table.get('foreign_keys') and len(table['foreign_keys']) > 0:
                adjustments += 0.05
            
            # Bonificar si nombres de columnas coinciden con la query
            if table.get('columns'):
                for col in table['columns']:
                    col_name = col.get('name', '').lower()
                    # Buscar palabras de la query en nombres de columnas
                    query_words = query_lower.split()
                    for word in query_words:
                        if len(word) > 3 and word in col_name:
                            adjustments += 0.03
                            break
            
            # Aplicar ajustes
            table['similarity_score'] = max(0, min(1, original_score + adjustments))
            table['score_adjustments'] = adjustments
        
        # Reordenar por score ajustado
        tables.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        return tables
    
    def _expand_with_related_tables(self, tables: List[Dict[str, Any]], max_related: int = 5) -> List[Dict[str, Any]]:
        """
        Expandir lista de tablas con tablas relacionadas importantes.
        Incluye expansión dinámica basada en foreign keys reales.
        
        Args:
            tables: Lista de tablas encontradas por RAG
            max_related: Máximo de tablas relacionadas a agregar por tabla principal
        
        Returns:
            Lista expandida de tablas incluyendo las relacionadas
        """
        expanded = []
        added_tables = set()
        
        # Primero agregar las tablas originales
        for table in tables:
            table_name = table['name']
            expanded.append(table)
            added_tables.add(table_name)
        
        # Expandir dinámicamente usando foreign keys reales
        for table in tables[:3]:  # Solo las 3 más relevantes
            table_name = table['name']
            
            # Obtener tablas relacionadas por FK
            fk_related = self._get_fk_related_tables(table_name)
            
            for related_name in fk_related[:max_related]:
                if related_name not in added_tables and related_name in self.schema_cache.get('full_schema', {}):
                    table_info = self.schema_cache['full_schema'][related_name]
                    
                    related_table = {
                        'name': related_name,
                        'similarity_score': table['similarity_score'] * 0.75,
                        'description': f"Relacionada por FK con {table_name}",
                        'row_count': table_info.row_count,
                        'columns': [
                            {'name': col['name'], 'type': col['data_type'], 'nullable': col['nullable']}
                            for col in table_info.columns
                        ],
                        'primary_keys': table_info.primary_keys,
                        'foreign_keys': table_info.foreign_keys,
                        'relationships': db.get_table_relationships(related_name),
                        'is_related': True,
                        'relation_type': 'foreign_key'
                    }
                    
                    expanded.append(related_table)
                    added_tables.add(related_name)
        
        # Luego agregar tablas relacionadas para cada una
        for table in tables[:3]:  # Solo expandir las 3 más relevantes
            table_name = table['name']
            
            if table_name not in self.relationships_graph:
                continue
            
            related_tables = self.relationships_graph[table_name]
            
            # Priorizar tablas relacionadas por importancia semántica
            scored_related = []
            for rel_table in related_tables:
                if rel_table in added_tables:
                    continue
                
                # Calcular score de importancia
                score = 0
                rel_lower = rel_table.lower()
                
                # Tablas de detalle/códigos/claves son muy importantes
                if any(k in rel_lower for k in ['codigo', 'clave', 'detalle', 'det', 'linea']):
                    score += 10
                
                # Catálogos relacionados
                if any(k in rel_lower for k in ['tipo', 'grupo', 'categoria', 'familia']):
                    score += 7
                
                # Existencias y precios muy importantes
                if any(k in rel_lower for k in ['existencia', 'precio', 'costo']):
                    score += 9
                
                # Relaciones con el nombre de la tabla principal
                table_base = table_name.rstrip('S')  # ARTICULOS -> ARTICULO
                if table_base.lower() in rel_lower:
                    score += 8
                
                scored_related.append((rel_table, score))
            
            # Ordenar por score y tomar las mejores
            scored_related.sort(key=lambda x: x[1], reverse=True)
            
            # Agregar las tablas relacionadas más importantes
            for rel_table, score in scored_related[:max_related]:
                if rel_table in self.schema_cache.get('full_schema', {}):
                    table_info = self.schema_cache['full_schema'][rel_table]
                    
                    related_table = {
                        'name': rel_table,
                        'similarity_score': table['similarity_score'] * 0.7,  # Score reducido para relacionadas
                        'description': f"Tabla relacionada con {table_name}",
                        'row_count': table_info.row_count,
                        'columns': [
                            {
                                'name': col['name'],
                                'type': col['data_type'],
                                'nullable': col['nullable']
                            }
                            for col in table_info.columns
                        ],
                        'primary_keys': table_info.primary_keys,
                        'foreign_keys': table_info.foreign_keys,
                        'relationships': db.get_table_relationships(rel_table),
                        'is_related': True,  # Marcar como tabla relacionada
                        'related_to': table_name
                    }
                    
                    expanded.append(related_table)
                    added_tables.add(rel_table)
        
        if len(expanded) > len(tables):
            logger.info(f"Expandidas {len(tables)} tablas a {len(expanded)} (incluyendo {len(expanded) - len(tables)} relacionadas)")
        
        return expanded
        
    @timing_decorator("Schema Loading")
    def load_and_process_schema(self, force_refresh: bool = False, skip_embeddings: bool = False) -> Dict[str, Any]:
        """
        Cargar y procesar esquema completo con TODOS los embeddings.

        Args:
            force_refresh: Forzar recarga desde BD
            skip_embeddings: Si True, solo carga estructura sin embeddings
        """
        try:
            # Verificar si necesitamos actualizar
            if not force_refresh and self._is_schema_cache_valid():
                # Verificar si ya tenemos embeddings completos
                embeddings_complete = self.schema_cache.get('embeddings_pending', True) == False
                if embeddings_complete or skip_embeddings:
                    logger.info("✓ Usando esquema procesado desde caché")
                return self.schema_cache
                # Si faltan embeddings, continuar procesándolos
            
            logger.info("🔄 Cargando esquema completo de la base de datos...")
            
            # Cargar esquema de la base de datos (usa caché si existe)
            full_schema = self.schema_cache.get('full_schema') if not force_refresh else None
            if not full_schema:
                full_schema = db.get_full_schema(force_refresh=True)
            
            if not full_schema:
                raise Exception("No se pudo cargar el esquema de la base de datos")
            
            # Inicializar table_embeddings ANTES del condicional
            table_embeddings = {}

            # Procesar TODAS las tablas para embeddings (no limitar)
            if not skip_embeddings:
                logger.info(f"🧠 Procesando TODAS las tablas para embeddings ({len(full_schema)} tablas)...")
                table_embeddings = self._process_tables_for_embeddings(full_schema, max_tables=None)
            
            # Agregar embeddings al almacén vectorial (degradar si falla Chroma)
            try:
                logger.info("💾 Guardando embeddings en ChromaDB...")
                self.vector_store.add_table_embeddings(table_embeddings)
                logger.info("✅ ChromaDB actualizado")
            except Exception as e:
                logger.warning(f"⚠️ ChromaDB no disponible, continúo sin vector store: {e}")
                # No borrar table_embeddings si falla ChromaDB
            
            # Identificar tablas activas
            active_tables = self._identify_active_tables(full_schema)
            
            # Actualizar caché (aunque falle el vector store)
            self.schema_cache = {
                'full_schema': full_schema,
                'table_embeddings': table_embeddings,
                'active_tables': active_tables,
                'stats': self._calculate_schema_stats(full_schema, active_tables),
                'is_basic': False,
                'embeddings_pending': skip_embeddings  # False si se procesaron todos
            }
            
            self.last_schema_update = datetime.now()
            self.active_tables_cache = active_tables
            
            logger.info(f"✅ Esquema procesado completamente: {len(full_schema)} tablas totales, "
                       f"{len(active_tables)} activas, {len(table_embeddings)} con embeddings")
            
            return self.schema_cache
            
        except Exception as e:
            # No abortar completamente: devolver caché mínima si existe para que la UI funcione
            logger.error("❌ Error cargando y procesando esquema", e)
            if self.schema_cache:
                return self.schema_cache
            raise

    def load_and_process_schema_basic(self, force_refresh: bool = False, force_minimal: bool = False) -> Dict[str, Any]:
        """
        Cargar esquema básico SOLO estructura (sin embeddings) para inicialización ultra-rápida.
        Los embeddings se procesan después en background.
        """
        try:
            logger.info("⚡ Cargando esquema básico (solo estructura, sin embeddings)...")

            # Cargar esquema de la base de datos
            full_schema = db.get_full_schema(force_refresh=True)

            if not full_schema:
                raise Exception("No se pudo cargar el esquema de la base de datos")

            # NO procesar embeddings aquí - será en background
            table_embeddings = {}

            # Identificar tablas activas
            active_tables = self._identify_active_tables(full_schema)

            # Crear caché básico (sin embeddings)
            self.schema_cache = {
                'full_schema': full_schema,
                'table_embeddings': table_embeddings,
                'active_tables': active_tables,
                'stats': self._calculate_schema_stats(full_schema, active_tables),
                'is_basic': True,  # Marcar como carga básica
                'embeddings_pending': True  # Indicar que faltan embeddings
            }

            self.last_schema_update = datetime.now()
            self.active_tables_cache = active_tables

            stats = self.schema_cache.get('stats', {})
            logger.info(f"✅ Esquema básico cargado: {len(full_schema)} tablas totales, "
                       f"{len(active_tables)} activas (embeddings pendientes)")

            return self.schema_cache

        except Exception as e:
            logger.error("Error cargando esquema básico", e)
            # Intentar devolver algo mínimo si existe
            if self.schema_cache:
                return self.schema_cache
            raise
    
    def _is_schema_cache_valid(self) -> bool:
        """Verificar si el caché del esquema sigue siendo válido."""
        if not self.schema_cache or not self.last_schema_update:
            return False
        
        time_diff = datetime.now() - self.last_schema_update
        return time_diff < timedelta(minutes=config.rag.cache_ttl_minutes)
    
    def _process_tables_for_embeddings(self, schema: Dict[str, TableInfo], max_tables: int = None) -> Dict[str, Dict[str, Any]]:
        """
        Procesar tablas para generar embeddings con priorización inteligente.

        Args:
            schema: Diccionario de tablas
            max_tables: Límite de tablas a procesar (None = todas)
        """
        table_embeddings = {}

        # Limitar el procesamiento a tablas más importantes primero
        tables_to_process = []
        
        for table_name, table_info in schema.items():
            # Priorizar tablas con datos y relaciones
            priority = 0

            # Tablas con relaciones son MUY importantes (catálogos principales)
            priority += len(table_info.foreign_keys) * 15

            # Tablas con muchas columnas suelen ser importantes
            priority += len(table_info.columns) * 2

            # Tablas con datos conocidos (pero no penalizar si row_count = -1)
            if table_info.row_count > 0:
                priority += min(table_info.row_count / 1000, 50)
            elif table_info.row_count == -1:
                # Tabla sin contar aún, asumir prioridad media
                priority += 10

            # Tablas con nombres importantes
            name_upper = table_name.upper()
            if any(kw in name_upper for kw in ['ARTICULO', 'CLIENTE', 'PROVEEDOR', 'VENTA', 'COMPRA', 'FACTURA', 'PEDIDO']):
                priority += 20

            tables_to_process.append((table_name, table_info, priority))

        # Ordenar por prioridad
        tables_to_process.sort(key=lambda x: x[2], reverse=True)

        # Aplicar límite si se especifica
        if max_tables is not None:
            limited_tables = tables_to_process[:max_tables]
        else:
            limited_tables = tables_to_process

        # Procesar tablas con progreso DETALLADO
        total = len(limited_tables)
        processed = 0

        logger.info(f"📊 Iniciando generación de embeddings para {total} tablas...")

        for table_name, table_info, priority in limited_tables:
            try:
                # Log ANTES de procesar cada tabla
                logger.info(f"🔄 [{processed + 1}/{total}] Procesando: {table_name}")

                # Obtener muestra de datos para TODAS las tablas con registros
                sample_data = []
                if table_info.row_count != 0:  # -1 o > 0
                    try:
                        # Intentar obtener muestra (limitada a 10 registros)
                        sample_query = f"SELECT FIRST 10 * FROM {table_name}"
                        result = db.execute_query(sample_query)
                        if result and result.data:
                            sample_data = result.data[:10]
                            logger.debug(f"  ✓ Obtenida muestra de {len(sample_data)} registros")
                    except Exception as e:
                        # No abortar si falla la muestra, continuar sin ella
                        logger.debug(f"  ⚠ No se pudo obtener muestra: {str(e)[:50]}")

                # Generar descripción semántica ENRIQUECIDA
                description = TableDescriptor.describe_table(table_info, sample_data)
                
                # Generar embedding
                embedding = self.embedding_generator.generate_embedding(description)
                
                table_embeddings[table_name] = {
                    'embedding': embedding,
                    'description': description,
                    'row_count': table_info.row_count,
                    'is_active': table_info.is_active,
                    'column_count': len(table_info.columns),
                    'primary_key_count': len(table_info.primary_keys),
                    'foreign_key_count': len(table_info.foreign_keys),
                    'index_count': len(table_info.indexes),
                    'has_foreign_keys': len(table_info.foreign_keys) > 0,
                    'has_unique_indexes': any(idx.get('unique', False) for idx in table_info.indexes),
                    'table_info': table_info
                }
                
                processed += 1

                # Log DESPUÉS de completar cada tabla
                logger.info(f"✓ [{processed}/{total}] {table_name} completada ({(processed/total*100):.1f}%)")
                
            except Exception as e:
                logger.error(f"✗ Error procesando tabla {table_name}: {str(e)}")
                # Continuar con la siguiente tabla
                processed += 1
                continue
        
        logger.info(f"✅ Procesadas {len(table_embeddings)}/{total} tablas para embeddings")
        return table_embeddings
    
    def _identify_active_tables(self, schema: Dict[str, TableInfo]) -> List[str]:
        """Identificar tablas activas usando heurísticas avanzadas."""
        active_tables = []
        
        # Ordenar por relevancia
        tables_by_relevance = []
        
        for table_name, table_info in schema.items():
            relevance_score = 0
            
            # Factor 1: Número de registros
            if table_info.row_count > 0:
                relevance_score += min(table_info.row_count / 1000, 100)
            
            # Factor 2: Relaciones activas
            relevance_score += len(table_info.foreign_keys) * 10
            
            # Factor 3: Nombre no obsoleto
            if table_info.is_active:
                relevance_score += 20
            
            # Factor 4: Complejidad (más columnas = más importante)
            relevance_score += len(table_info.columns) * 2
            
            # Factor 5: Tiene clave primaria
            if table_info.primary_keys:
                relevance_score += 15
            
            tables_by_relevance.append((table_name, relevance_score, table_info))
        
        # Ordenar por relevancia
        tables_by_relevance.sort(key=lambda x: x[1], reverse=True)
        
        # Seleccionar tablas activas
        for table_name, score, table_info in tables_by_relevance:
            if score > 10:  # Threshold mínimo
                active_tables.append(table_name)
        
        return active_tables
    
    def _calculate_schema_stats(self, schema: Dict[str, TableInfo], 
                              active_tables: List[str]) -> Dict[str, Any]:
        """Calcular estadísticas del esquema."""
        total_rows = sum(table.row_count for table in schema.values() if table.row_count > 0)
        
        return {
            'total_tables': len(schema),
            'active_tables': len(active_tables),
            'inactive_tables': len(schema) - len(active_tables),
            'total_rows': total_rows,
            'tables_with_data': len([t for t in schema.values() if t.row_count > 0]),
            'tables_with_foreign_keys': len([t for t in schema.values() if t.foreign_keys]),
            'last_update': datetime.now().isoformat()
        }
    
    @timing_decorator("Table Search")
    def find_relevant_tables(self, query: str, max_tables: int = None, expand_relations: bool = True) -> List[Dict[str, Any]]:
        """
        Encontrar tablas relevantes para una consulta usando RAG.
        
        Args:
            query: Consulta del usuario
            max_tables: Número máximo de tablas principales a buscar
            expand_relations: Si True, expande automáticamente con tablas relacionadas
        
        Returns:
            Lista de tablas relevantes (incluyendo relacionadas si expand_relations=True)
        """
        if max_tables is None:
            max_tables = config.rag.top_k_tables
        
        try:
            # Verificar que el esquema esté cargado
            if not self.schema_cache:
                logger.info("Esquema no cargado, cargando ahora...")
                self.load_and_process_schema()
            
            # Generar embedding de la consulta
            query_embedding = self.embedding_generator.generate_embedding(query)
            
            # Buscar tablas similares
            similar_tables = self.vector_store.search_similar_tables(
                query_embedding, 
                top_k=max_tables * 2,  # Buscar más para filtrar mejor
                filter_active=True
            )
            
            # Enriquecer con información adicional
            relevant_tables = []
            
            for table_result in similar_tables[:max_tables]:
                table_name = table_result['table_name']
                
                # Obtener información completa de la tabla
                if table_name in self.schema_cache['full_schema']:
                    table_info = self.schema_cache['full_schema'][table_name]
                    
                    relevant_table = {
                        'name': table_name,
                        'similarity_score': table_result['similarity'],
                        'description': table_result['description'],
                        'row_count': table_info.row_count,
                        'columns': [
                            {
                                'name': col['name'],
                                'type': col['data_type'],
                                'nullable': col['nullable']
                            }
                            for col in table_info.columns
                        ],
                        'primary_keys': table_info.primary_keys,
                        'foreign_keys': table_info.foreign_keys,
                        'relationships': db.get_table_relationships(table_name),
                        'is_related': False  # Es una tabla principal, no relacionada
                    }
                    
                    relevant_tables.append(relevant_table)
            
            # Logging detallado de las tablas encontradas
            logger.info(f"📊 Encontradas {len(relevant_tables)} tablas principales para: '{query}'")
            if relevant_tables:
                logger.info("🔍 Tablas principales seleccionadas:")
                for i, table in enumerate(relevant_tables, 1):
                    logger.info(f"  {i}. {table['name']} (similitud: {table['similarity_score']:.4f}, {table.get('row_count', 0)} registros)")

            # Expandir con tablas relacionadas si está habilitado
            if expand_relations and relevant_tables:
                relevant_tables = self._expand_with_related_tables(relevant_tables)
                # Mejorar scoring basado en relaciones y datos
                relevant_tables = self._adjust_scores_by_context(relevant_tables, query)

                # Logging final de todas las tablas (principales + relacionadas)
                logger.info(f"📋 Total de tablas tras expansión: {len(relevant_tables)}")
                logger.info("🎯 Tablas finales (principales + relacionadas):")
                for i, table in enumerate(relevant_tables[:15], 1):  # Primeras 15
                    is_related = " [RELACIONADA]" if table.get('is_related', False) else " [PRINCIPAL]"
                    logger.info(f"  {i}. {table['name']}{is_related} (score: {table.get('similarity_score', 0):.4f})")

            return relevant_tables
            
        except Exception as e:
            logger.error(f"Error buscando tablas relevantes para '{query}'", e)
            return []
    
    def get_table_context(self, table_names: List[str]) -> str:
        """Generar contexto textual de tablas para enviar a la IA."""
        if not table_names:
            return ""
        
        context_parts = ["Tablas relevantes para esta consulta:\n"]
        
        for table_name in table_names:
            if table_name not in self.schema_cache.get('full_schema', {}):
                continue
            
            table_info = self.schema_cache['full_schema'][table_name]
            
            # Información básica
            context_parts.append(f"- {table_name} ({DataFormatter.format_number(table_info.row_count)} registros):")
            
            # Mostrar TODAS las columnas importantes (máximo 30 para RAG, todas para refinamiento)
            max_cols = min(30, len(table_info.columns))
            main_columns = table_info.columns[:max_cols]

            # Agrupar columnas por línea para mejor legibilidad
            col_names = [col['name'] for col in main_columns]
            context_parts.append(f"  Columnas: {', '.join(col_names)}")

            # Si hay más columnas, indicarlo
            if len(table_info.columns) > max_cols:
                remaining = len(table_info.columns) - max_cols
                context_parts.append(f"  ... y {remaining} columnas más")

            # Información adicional sobre claves e índices
            if table_info.primary_keys:
                context_parts.append(f"  Clave primaria: {', '.join(table_info.primary_keys)}")

            if table_info.indexes:
                indexed_cols = []
                for idx in table_info.indexes[:5]:  # Primeros 5 índices
                    if idx.get('columns'):
                        for col in idx['columns']:
                            if col['name'] not in indexed_cols:
                                indexed_cols.append(col['name'])
                if indexed_cols:
                    context_parts.append(f"  Columnas indexadas: {', '.join(indexed_cols[:10])}")

            if table_info.foreign_keys:
                fk_info = []
                for fk in table_info.foreign_keys[:3]:  # Primeras 3 FKs
                    ref_table = fk.get('referenced_table', '')
                    if ref_table:
                        fk_info.append(f"{', '.join(fk.get('columns', []))} → {ref_table}")
                if fk_info:
                    context_parts.append(f"  Relaciones: {'; '.join(fk_info)}")

            # Añadir semántica de columnas clave
            semantic_cols = []
            for col in main_columns:
                col_name = col['name'].upper()
                if col_name in COLUMN_SEMANTICS:
                    semantic_cols.append(f"    {col_name}: {COLUMN_SEMANTICS[col_name]}")

            if semantic_cols:
                context_parts.append(f"  💡 Información clave de columnas:")
                context_parts.extend(semantic_cols)

            # Añadir notas especiales para tablas críticas
            if 'DOCTOS_PV_DET' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: Filtrar DESCRIPCION1 para excluir VENTA GLOBAL y artículos de sistema")
            if 'ARTICULOS' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: Excluir artículos con NOMBRE conteniendo GLOBAL, CORTE, SISTEMA")
            if 'DOCTOS_PV' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: NO tiene columna SERIE (solo TIPO_DOCTO + FOLIO)")
            if 'DOCTOS_VE' in table_name:
                context_parts.append("  ⚠️ IMPORTANTE: NO tiene columna SERIE (solo TIPO_DOCTO + FOLIO)")
            
            # Claves primarias
            if table_info.primary_keys:
                context_parts.append(f"  Clave primaria: {', '.join(table_info.primary_keys)}")
            
            # Relaciones
            relationships = db.get_table_relationships(table_name)
            if relationships['references']:
                referenced_tables = [ref['table'] for ref in relationships['references']]
                context_parts.append(f"  Referencia a: {', '.join(referenced_tables)}")

            context_parts.append("")  # Línea vacía
        
        return "\n".join(context_parts)
    
    def get_schema_summary(self) -> Dict[str, Any]:
        """Obtener resumen del esquema procesado."""
        if not self.schema_cache:
            return {'error': 'Esquema no cargado'}
        
        stats = self.schema_cache.get('stats', {})
        vector_stats = self.vector_store.get_collection_stats()
        
        return {
            **stats,
            **vector_stats,
            'cache_valid': self._is_schema_cache_valid(),
            'active_tables_sample': self.active_tables_cache[:10] if self.active_tables_cache else [],
            'last_update': self.last_schema_update.isoformat() if self.last_schema_update else None,
            'next_auto_update': (self.last_schema_update + timedelta(seconds=self.auto_update_interval)).isoformat() if self.last_schema_update else None
        }
    
    def start_auto_update_thread(self):
        """Iniciar thread para actualización automática cada 12 horas."""
        if self._auto_update_thread and self._auto_update_thread.is_alive():
            logger.warning("Thread de auto-actualización ya está corriendo")
            return
        
        self._stop_auto_update.clear()
        self._auto_update_thread = threading.Thread(
            target=self._auto_update_worker,
            daemon=True,
            name="SchemaAutoUpdate"
        )
        self._auto_update_thread.start()
        logger.info(f"Thread de auto-actualización iniciado (intervalo: {self.auto_update_interval/3600:.1f} horas)")
    
    def _auto_update_worker(self):
        """Worker thread para actualización automática de estadísticas."""
        while not self._stop_auto_update.is_set():
            try:
                # Esperar el intervalo de actualización
                if self._stop_auto_update.wait(self.auto_update_interval):
                    break  # Se solicitó detener
                
                logger.info("🔄 Iniciando actualización automática de estadísticas...")
                
                # Actualizar solo estadísticas (conteos), no todo el esquema
                stats = db.update_table_stats(force=True)
                
                if stats:
                    logger.info(f"✅ Actualización automática completada: {len(stats)} tablas actualizadas")
                    # Actualizar timestamp
                    self.last_schema_update = datetime.now()
                else:
                    logger.warning("⚠️ Actualización automática no retornó resultados")
                    
            except Exception as e:
                logger.error(f"Error en actualización automática: {e}")
                # Continuar a pesar del error
    
    def stop_auto_update_thread(self):
        """Detener thread de auto-actualización."""
        if self._auto_update_thread and self._auto_update_thread.is_alive():
            logger.info("Deteniendo thread de auto-actualización...")
            self._stop_auto_update.set()
            self._auto_update_thread.join(timeout=5)
            logger.info("Thread de auto-actualización detenido")
    
    def update_statistics_only(self, table_names: List[str] = None) -> Dict[str, int]:
        """
        Actualizar solo las estadísticas de tablas sin recargar el esquema completo.
        
        Args:
            table_names: Lista de tablas a actualizar. Si es None, actualiza todas.
            
        Returns:
            Diccionario con conteos actualizados
        """
        stats = db.update_table_stats(table_names=table_names, force=True)
        
        if stats:
            self.last_schema_update = datetime.now()
            logger.info(f"Estadísticas actualizadas manualmente: {len(stats)} tablas")
        
        return stats


# Instancia global del gestor de esquema
schema_manager = SchemaManager()