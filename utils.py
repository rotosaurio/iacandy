"""
Utilidades del sistema de IA para consulta de base de datos Firebird.

Este módulo contiene funciones auxiliares para logging, formateo, validación
y otras operaciones comunes del sistema.
"""

import os
import re
import json
import time
import hashlib
import logging
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple
from functools import wraps
from pathlib import Path

import pandas as pd

from config import config, DEFAULT_DATE_FORMAT


class SchemaStatsCache:
    """Sistema de caché para estadísticas de tablas (conteo de registros)."""
    
    def __init__(self, ttl_seconds=12*3600):
        """
        Inicializar caché de estadísticas.
        
        Args:
            ttl_seconds: Tiempo de vida del caché en segundos (default: 12 horas)
        """
        self.cache = {}  # {table_name: {'count': int, 'timestamp': float}}
        self.ttl = ttl_seconds
    
    def get_row_count(self, table_name: str) -> Optional[int]:
        """
        Obtener conteo de registros del caché si está fresco.
        
        Args:
            table_name: Nombre de la tabla
            
        Returns:
            Número de registros o None si no está en caché o está obsoleto
        """
        if table_name not in self.cache:
            return None
        
        entry = self.cache[table_name]
        
        # Verificar si el caché está obsoleto
        if self.is_stale(table_name):
            del self.cache[table_name]
            return None
        
        return entry['count']
    
    def set_row_count(self, table_name: str, count: int):
        """
        Guardar conteo de registros en caché con timestamp.
        
        Args:
            table_name: Nombre de la tabla
            count: Número de registros
        """
        self.cache[table_name] = {
            'count': count,
            'timestamp': time.time()
        }
    
    def is_stale(self, table_name: str) -> bool:
        """
        Verificar si el caché de una tabla necesita actualización.
        
        Args:
            table_name: Nombre de la tabla
            
        Returns:
            True si está obsoleto o no existe
        """
        if table_name not in self.cache:
            return True
        
        entry = self.cache[table_name]
        age = time.time() - entry['timestamp']
        return age > self.ttl
    
    def clear(self):
        """Limpiar todo el caché."""
        self.cache.clear()
    
    def get_cache_age(self, table_name: str) -> Optional[float]:
        """
        Obtener antigüedad del caché en segundos.
        
        Args:
            table_name: Nombre de la tabla
            
        Returns:
            Segundos desde la última actualización o None si no existe
        """
        if table_name not in self.cache:
            return None
        
        return time.time() - self.cache[table_name]['timestamp']


class Logger:
    """Sistema de logging centralizado y configurable."""
    
    _instance = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._setup_logging()
        return cls._instance
    
    @classmethod
    def _setup_logging(cls):
        """Configurar el sistema de logging."""
        # Crear directorio de logs si no existe
        log_dir = os.path.dirname(config.logging.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # Configurar logger principal
        cls._logger = logging.getLogger("firebird_ai")
        cls._logger.setLevel(getattr(logging, config.logging.log_level))
        
        # Evitar duplicar handlers
        if cls._logger.handlers:
            return
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt=DEFAULT_DATE_FORMAT
        )
        
        # File handler con rotación y encoding UTF-8
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            config.logging.log_file,
            maxBytes=config.logging.max_log_size_mb * 1024 * 1024,
            backupCount=config.logging.backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        cls._logger.addHandler(file_handler)
        
        # Console handler con encoding UTF-8
        if config.logging.console_output:
            import sys
            # Configurar stdout para usar UTF-8
            if sys.platform == 'win32':
                import codecs
                # Reconfigurar stdout para Windows con UTF-8
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            # Establecer encoding UTF-8 para el handler
            if hasattr(console_handler.stream, 'reconfigure'):
                console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
            cls._logger.addHandler(console_handler)
    
    def info(self, message: str, **kwargs):
        """Log mensaje de información."""
        self._logger.info(message, extra=kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log mensaje de advertencia."""
        self._logger.warning(message, extra=kwargs)
    
    def error(self, message: str, error: Exception = None, **kwargs):
        """Log mensaje de error."""
        if error:
            message = f"{message}: {str(error)}"
            if config.logging.detailed_sql_logging:
                message += f"\nTraceback: {traceback.format_exc()}"
        self._logger.error(message, extra=kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log mensaje de debug."""
        self._logger.debug(message, extra=kwargs)
    
    def sql_query(self, sql: str, params: dict = None, execution_time: float = None):
        """Log específico para queries SQL."""
        if not config.logging.detailed_sql_logging:
            return
        
        log_data = {
            "sql": sql.strip(),
            "timestamp": datetime.now().isoformat(),
        }
        
        if params:
            log_data["parameters"] = params
        
        if execution_time is not None:
            log_data["execution_time_seconds"] = round(execution_time, 4)
        
        self._logger.info(f"SQL_QUERY: {json.dumps(log_data)}")


# Instancia global del logger
logger = Logger()


class Timer:
    """Contexto para medir tiempos de ejecución."""
    
    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        execution_time = self.elapsed_time
        
        if exc_type:
            logger.error(f"{self.name} failed after {execution_time:.4f}s", exc_val)
        else:
            logger.info(f"{self.name} completed in {execution_time:.4f}s")
    
    @property
    def elapsed_time(self) -> float:
        """Tiempo transcurrido en segundos."""
        if self.start_time is None:
            return 0.0
        
        end = self.end_time or time.time()
        return end - self.start_time


def timing_decorator(name: str = None):
    """Decorador para medir tiempo de ejecución de funciones."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            operation_name = name or f"{func.__module__}.{func.__name__}"
            with Timer(operation_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


class SQLValidator:
    """Validador de consultas SQL para seguridad."""
    
    # Patrones prohibidos
    DANGEROUS_PATTERNS = [
        r'\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE|EXEC)\b',
        r'\b(xp_|sp_)\w+',  # Procedimientos del sistema
        r'--',  # Comentarios SQL
        r'/\*.*?\*/',  # Comentarios multilínea
        # Nota: Los múltiples statements se validan después con lógica más precisa
        r'\b(UNION|EXCEPT|INTERSECT)\b.*\b(SELECT)\b',  # UNION con SELECT anidado
    ]
    
    @classmethod
    def is_safe_query(cls, sql: str) -> Tuple[bool, str]:
        """Validar si una query SQL es segura para ejecutar."""
        if not sql or not sql.strip():
            return False, "Query vacía"
        
        sql_upper = sql.upper().strip()
        
        # Permitir SELECT y CTEs (WITH)
        if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
            return False, "Solo se permiten consultas SELECT o WITH (CTEs)"
        
        # Verificar patrones peligrosos
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return False, f"Patrón prohibido detectado: {pattern}"
        
        # Verificar que no tenga múltiples statements
        statements = sql.strip().split(';')
        if len(statements) > 1 and any(s.strip() for s in statements[1:]):
            return False, "No se permiten múltiples statements"
        
        return True, "Query válida"
    
    @classmethod
    def sanitize_query(cls, sql: str) -> str:
        """Sanitizar query SQL básico."""
        # Remover comentarios
        sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        
        # Limpiar espacios extras
        sql = ' '.join(sql.split())
        
        return sql.strip()


class DataFormatter:
    """Formateador de datos para visualización."""
    
    @staticmethod
    def format_number(value: Union[int, float], decimals: int = 2) -> str:
        """Formatear números con separadores de miles."""
        if value is None:
            return "N/A"
        
        if isinstance(value, float) and decimals > 0:
            return f"{value:,.{decimals}f}"
        
        return f"{int(value):,}"
    
    @staticmethod
    def format_bytes(bytes_value: int) -> str:
        """Formatear tamaño en bytes a formato legible."""
        if bytes_value == 0:
            return "0 B"
        
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        size = float(bytes_value)
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        
        return f"{size:.1f} {units[unit_index]}"
    
    @staticmethod
    def format_duration(seconds: float) -> str:
        """Formatear duración en segundos a formato legible."""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        else:
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds:.0f}s"
    
    @staticmethod
    def format_datetime(dt: datetime, include_time: bool = True) -> str:
        """Formatear datetime para visualización."""
        if dt is None:
            return "N/A"
        
        if include_time:
            return dt.strftime(DEFAULT_DATE_FORMAT)
        else:
            return dt.strftime("%Y-%m-%d")
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 100) -> str:
        """Truncar texto largo con elipsis."""
        if not text:
            return ""
        
        if len(text) <= max_length:
            return text
        
        return text[:max_length-3] + "..."
    
    @staticmethod
    def format_sql(sql: str) -> str:
        """Formatear SQL para mejor legibilidad."""
        if not sql:
            return ""
        
        # Formateo básico de SQL
        keywords = [
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN',
            'INNER JOIN', 'OUTER JOIN', 'GROUP BY', 'ORDER BY', 'HAVING',
            'UNION', 'AND', 'OR', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END'
        ]
        
        formatted_sql = sql
        for keyword in keywords:
            pattern = f"\\b{keyword}\\b"
            formatted_sql = re.sub(pattern, f"\n{keyword}", formatted_sql, flags=re.IGNORECASE)
        
        # Limpiar espacios y saltos de línea extras
        lines = [line.strip() for line in formatted_sql.split('\n') if line.strip()]
        return '\n'.join(lines)


class CacheManager:
    """Gestor de caché simple basado en archivos."""
    
    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
    
    def _get_cache_path(self, key: str) -> Path:
        """Obtener ruta del archivo de caché."""
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"
    
    def get(self, key: str, ttl_minutes: int = None) -> Any:
        """Obtener valor del caché."""
        cache_file = self._get_cache_path(key)
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # Verificar TTL
            if ttl_minutes:
                cache_time = datetime.fromisoformat(cache_data['timestamp'])
                if datetime.now() - cache_time > timedelta(minutes=ttl_minutes):
                    cache_file.unlink()  # Eliminar caché expirado
                    return None
            
            return cache_data['value']
        
        except Exception as e:
            logger.error(f"Error leyendo caché para {key}", e)
            return None
    
    def set(self, key: str, value: Any) -> bool:
        """Guardar valor en caché."""
        cache_file = self._get_cache_path(key)
        
        cache_data = {
            'timestamp': datetime.now().isoformat(),
            'value': value
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            return True
        
        except Exception as e:
            logger.error(f"Error guardando caché para {key}", e)
            return False
    
    def clear(self, pattern: str = None) -> int:
        """Limpiar archivos de caché."""
        cleared = 0
        
        for cache_file in self.cache_dir.glob("*.json"):
            if pattern is None or pattern in cache_file.name:
                cache_file.unlink()
                cleared += 1
        
        return cleared


class DataAnalyzer:
    """Analizador de datos para generar insights automáticos."""
    
    @staticmethod
    def analyze_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
        """Analizar DataFrame y generar estadísticas básicas."""
        if df.empty:
            return {"error": "DataFrame vacío"}
        
        analysis = {
            "rows": len(df),
            "columns": len(df.columns),
            "column_info": {},
            "summary": {}
        }
        
        for column in df.columns:
            col_data = df[column]
            col_info = {
                "type": str(col_data.dtype),
                "non_null_count": col_data.count(),
                "null_count": col_data.isnull().sum(),
                "unique_values": col_data.nunique()
            }
            
            # Análisis específico por tipo
            if col_data.dtype in ['int64', 'float64']:
                col_info.update({
                    "min": col_data.min(),
                    "max": col_data.max(),
                    "mean": col_data.mean(),
                    "median": col_data.median(),
                    "std": col_data.std()
                })
            
            elif col_data.dtype == 'object':
                # Asumir string
                col_info["most_frequent"] = col_data.mode().iloc[0] if len(col_data.mode()) > 0 else None
                
                # Verificar si podría ser fecha
                if col_data.count() > 0:
                    sample_value = str(col_data.iloc[0])
                    if re.match(r'\d{4}-\d{2}-\d{2}', sample_value):
                        col_info["potential_date"] = True
            
            analysis["column_info"][column] = col_info
        
        # Resumen general
        analysis["summary"] = {
            "completeness": f"{(1 - df.isnull().sum().sum() / (len(df) * len(df.columns))) * 100:.1f}%",
            "duplicates": df.duplicated().sum(),
            "numeric_columns": len(df.select_dtypes(include=['number']).columns),
            "text_columns": len(df.select_dtypes(include=['object']).columns)
        }
        
        return analysis
    
    @staticmethod
    def suggest_visualizations(df: pd.DataFrame) -> List[Dict[str, str]]:
        """Sugerir tipos de visualización basados en los datos."""
        suggestions = []
        
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
        date_cols = []
        
        # Detectar columnas de fecha
        for col in categorical_cols:
            sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else ""
            if isinstance(sample, str) and re.match(r'\d{4}-\d{2}-\d{2}', sample):
                date_cols.append(col)
        
        # Sugerencias basadas en tipos de columnas
        if len(numeric_cols) >= 2:
            suggestions.append({
                "type": "scatter",
                "title": f"Gráfico de dispersión: {numeric_cols[0]} vs {numeric_cols[1]}",
                "description": "Muestra la relación entre dos variables numéricas"
            })
        
        if len(categorical_cols) >= 1 and len(numeric_cols) >= 1:
            suggestions.append({
                "type": "bar",
                "title": f"Gráfico de barras: {numeric_cols[0]} por {categorical_cols[0]}",
                "description": "Compara valores numéricos entre categorías"
            })
        
        if len(date_cols) >= 1 and len(numeric_cols) >= 1:
            suggestions.append({
                "type": "line",
                "title": f"Evolución temporal: {numeric_cols[0]} a lo largo del tiempo",
                "description": "Muestra tendencias temporales"
            })
        
        if len(numeric_cols) >= 1:
            suggestions.append({
                "type": "histogram",
                "title": f"Distribución de {numeric_cols[0]}",
                "description": "Muestra la distribución de valores"
            })
        
        return suggestions[:3]  # Máximo 3 sugerencias


# Instancia global del gestor de caché
cache_manager = CacheManager()


def safe_execute(func, default=None, log_error=True):
    """Ejecutar función de forma segura con manejo de errores."""
    try:
        return func()
    except Exception as e:
        if log_error:
            logger.error(f"Error en {func.__name__ if hasattr(func, '__name__') else 'función'}", e)
        return default


def get_memory_usage() -> Dict[str, str]:
    """Obtener información de uso de memoria del proceso."""
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            "rss": DataFormatter.format_bytes(memory_info.rss),
            "vms": DataFormatter.format_bytes(memory_info.vms),
            "percent": f"{process.memory_percent():.1f}%"
        }
    except ImportError:
        return {"error": "psutil no disponible"}
    except Exception as e:
        logger.error("Error obteniendo información de memoria", e)
        return {"error": str(e)}


def ensure_directory(path: str) -> bool:
    """Asegurar que un directorio existe."""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Error creando directorio {path}", e)
        return False


def clean_temp_files(directory: str = None, max_age_hours: int = 24) -> int:
    """Limpiar archivos temporales antiguos."""
    if directory is None:
        directory = config.export.temp_directory
    
    if not os.path.exists(directory):
        return 0
    
    cutoff_time = time.time() - (max_age_hours * 3600)
    cleaned = 0
    
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path) and os.path.getctime(file_path) < cutoff_time:
                os.remove(file_path)
                cleaned += 1
        
        logger.info(f"Archivos temporales limpiados: {cleaned}")
        return cleaned
    
    except Exception as e:
        logger.error(f"Error limpiando archivos temporales en {directory}", e)
        return 0