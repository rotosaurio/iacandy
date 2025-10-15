"""
Configuración centralizada del sistema de IA para consulta de base de datos Firebird.

Este módulo contiene todas las configuraciones, credenciales y parámetros
del sistema de forma centralizada y segura.
"""

import os
from typing import Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class DatabaseConfig:
    """Configuración de la base de datos Firebird."""
    host: str = "localhost"
    database_path: str = r"C:\Microsip Datos\CANDY MART CONCENTRADORA.FDB"
    username: str = "SYSDBA"
    password: str = "masterkey"
    port: int = 3050
    charset: str = "WIN1252"  # Cambiado de UTF8 a WIN1252 para compatibilidad con datos existentes
    timeout: int = 0  # Sin timeout (espera indefinidamente)
    connection_pool_size: int = 5


@dataclass
class AIConfig:
    """Configuración de OpenAI y parámetros de IA."""
    api_key: str = "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"
    
    # Modelo principal - GPT-5 para máximo rendimiento (2025)
    model: str = "gpt-5"
    
    # Modelos alternativos para estrategia inteligente
    model_simple: str = "gpt-4o"  # Para consultas simples
    model_complex: str = "gpt-5"  # Para consultas complejas
    model_fallback: str = "gpt-4o"  # Fallback si GPT-5 no disponible
    
    # Parámetros optimizados para GPT-5
    max_tokens: int = 8000  # Aumentado para consultas complejas que usan reasoning tokens
    temperature: float = 0.1  # Más determinístico para SQL
    timeout: int = 0  # Sin timeout (espera indefinidamente)
    max_retries: int = 3  # Más reintentos
    
    # Configuración de selección inteligente de modelo
    enable_smart_model_selection: bool = True
    complexity_threshold: int = 3  # Número de tablas para usar modelo complejo


@dataclass
class EdgeCaseConfig:
    """Configuración para manejo de casos especiales y exclusiones automáticas."""
    # Artículos de sistema/control que deben excluirse
    excluded_article_patterns: List[str] = field(default_factory=lambda: [
        'VENTA GLOBAL', 'VENTAS GLOBALES', 'CORTE DE CAJA',
        'CORTE DIARIO', 'APERTURA DE CAJA', 'CIERRE DE CAJA',
        'AJUSTE DE INVENTARIO', 'TRANSFERENCIA INTERNA',
        '%GLOBAL%', '%CORTE%', '%SISTEMA%', '%INTERNO%'
    ])

    # Clientes especiales a excluir
    excluded_client_patterns: List[str] = field(default_factory=lambda: [
        'CLIENTE MOSTRADOR', 'PUBLICO GENERAL', '%INTERNO%'
    ])

    # CVE_ART (códigos) a excluir
    excluded_cve_art: List[str] = field(default_factory=lambda: [
        'GLOBAL', 'CORTE', 'SISTEMA', 'CTRL'
    ])

    # Patrones adicionales de detección automática
    auto_exclude_patterns: List[str] = field(default_factory=lambda: [
        r'^[A-Z]{2,3}\d{3,6}$',  # Patrones de códigos internos
        r'.*(CONTROL|SYS|INT)$',  # Palabras clave al final
        r'^(GLOBAL|CORTE|SISTEMA)',  # Prefijos especiales
    ])

    # Configuración de filtros post-SQL
    enable_post_sql_filtering: bool = True
    max_description_length: int = 100  # Longitud máxima para descripciones sospechosas


@dataclass
class RAGConfig:
    """Configuración del sistema RAG (Retrieval-Augmented Generation)."""
    embeddings_model: str = "all-MiniLM-L6-v2"
    vector_db_path: str = "./data/chroma_db"
    top_k_tables: int = 8  # Aumentado para consultas complejas
    similarity_threshold: float = 0.25  # Threshold más bajo para capturar tablas relevantes (distancia coseno)
    chunk_size: int = 512
    cache_ttl_minutes: int = 30
    
    # Soporte para procedimientos almacenados
    enable_stored_procedures: bool = True
    procedures_cache_path: str = "./data/procedures_cache.json"
    include_procedures_in_context: bool = True


@dataclass
class UIConfig:
    """Configuración de la interfaz de usuario."""
    window_title: str = "🤖 Asistente IA - Base de Datos"
    window_width: int = 1200
    window_height: int = 800
    preview_row_limit: int = 1000
    max_display_chars: int = 10000
    refresh_interval_ms: int = 100


@dataclass
class ExportConfig:
    """Configuración de exportación de reportes."""
    default_format: str = "xlsx"
    batch_size: int = 5000
    max_memory_mb: int = 500
    temp_directory: str = "./temp"
    output_directory: str = "./reports"


@dataclass
class SecurityConfig:
    """Configuración de seguridad del sistema."""
    allowed_sql_operations: list = None
    query_timeout_seconds: int = 60
    max_result_rows: int = 1000000
    enable_query_logging: bool = True
    log_retention_days: int = 30
    
    def __post_init__(self):
        if self.allowed_sql_operations is None:
            self.allowed_sql_operations = ["SELECT"]


@dataclass
class LoggingConfig:
    """Configuración del sistema de logging."""
    log_level: str = "INFO"
    log_file: str = "logs/firebird_ai_assistant.log"
    max_log_size_mb: int = 50
    backup_count: int = 5
    console_output: bool = True
    detailed_sql_logging: bool = True


class Config:
    """Configuración principal del sistema."""
    
    def __init__(self):
        self.database = DatabaseConfig()
        self.ai = AIConfig()
        self.rag = RAGConfig()
        self.edge_case = EdgeCaseConfig()
        self.ui = UIConfig()
        self.export = ExportConfig()
        self.security = SecurityConfig()
        self.logging = LoggingConfig()
        
        # Crear directorios necesarios
        self._create_directories()
        
        # Cargar configuraciones desde variables de entorno si existen
        self._load_from_environment()
    
    def _create_directories(self) -> None:
        """Crear directorios necesarios para el sistema."""
        directories = [
            os.path.dirname(self.logging.log_file),
            self.rag.vector_db_path,
            self.export.temp_directory,
            self.export.output_directory,
            "./data",
            "./cache"
        ]
        
        for directory in directories:
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
    
    def _load_from_environment(self) -> None:
        """Cargar configuraciones desde variables de entorno."""
        # Database
        self.database.host = os.getenv("FB_HOST", self.database.host)
        self.database.database_path = os.getenv("FB_DATABASE", self.database.database_path)
        self.database.username = os.getenv("FB_USER", self.database.username)
        self.database.password = os.getenv("FB_PASSWORD", self.database.password)
        
        # OpenAI
        env_api_key = os.getenv("OPENAI_API_KEY")
        if env_api_key:
            self.ai.api_key = env_api_key
        
        # Logging
        self.logging.log_level = os.getenv("LOG_LEVEL", self.logging.log_level)
    
    def get_database_dsn(self) -> str:
        """Obtener DSN para conexión a Firebird."""
        return f"{self.database.host}/{self.database.port}:{self.database.database_path}"
    
    def get_openai_headers(self) -> Dict[str, str]:
        """Obtener headers para OpenAI API."""
        return {
            "Authorization": f"Bearer {self.ai.api_key}",
            "Content-Type": "application/json"
        }
    
    def validate_configuration(self) -> tuple[bool, str]:
        """Validar la configuración del sistema."""
        errors = []
        
        # Validar base de datos
        if not os.path.exists(self.database.database_path):
            errors.append(f"Base de datos no encontrada: {self.database.database_path}")
        
        # Validar API key
        if not self.ai.api_key or len(self.ai.api_key) < 10:
            errors.append("API Key de OpenAI inválida")
        
        # Validar directorios de escritura
        try:
            test_file = os.path.join(self.export.output_directory, "test")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
        except Exception:
            errors.append(f"No se puede escribir en directorio: {self.export.output_directory}")
        
        if errors:
            return False, "; ".join(errors)
        
        return True, "Configuración válida"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertir configuración a diccionario."""
        return {
            "database": {
                "host": self.database.host,
                "database_path": self.database.database_path,
                "username": self.database.username,
                "port": self.database.port,
                "charset": self.database.charset
            },
            "ai": {
                "model": self.ai.model,
                "max_tokens": self.ai.max_tokens,
                "temperature": self.ai.temperature
            },
            "rag": {
                "embeddings_model": self.rag.embeddings_model,
                "top_k_tables": self.rag.top_k_tables,
                "similarity_threshold": self.rag.similarity_threshold
            },
            "ui": {
                "window_title": self.ui.window_title,
                "preview_row_limit": self.ui.preview_row_limit
            }
        }


# Instancia global de configuración
config = Config()

# Constantes del sistema
SYSTEM_NAME = "Firebird AI Assistant"
VERSION = "1.0.0"
SUPPORTED_FORMATS = ["xlsx", "csv", "json", "html", "pdf"]
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Emojis para la UI
class Emojis:
    LOADING = "🔄"
    READY = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    SEARCH = "🔍"
    AI = "🤖"
    DATABASE = "⚙️"
    ANALYSIS = "📊"
    EXPORT = "📥"
    INSIGHT = "💡"
    CONNECTED = "🟢"
    DISCONNECTED = "🔴"
    PROCESSING = "📈"

# Mensajes de estado del sistema
class StatusMessages:
    CONNECTING = f"{Emojis.LOADING} Conectando a base de datos..."
    LOADING_SCHEMA = f"{Emojis.LOADING} Analizando base de datos..."
    SCHEMA_READY = f"{Emojis.READY} Sistema listo. {{}} tablas activas identificadas"
    ANALYZING_QUERY = f"{Emojis.SEARCH} Analizando consulta..."
    GENERATING_SQL = f"{Emojis.AI} Generando SQL..."
    EXECUTING_QUERY = f"{Emojis.DATABASE} Ejecutando consulta..."
    PROCESSING_RESULTS = f"{Emojis.ANALYSIS} Procesando resultados..."
    ANALYZING_DATA = f"{Emojis.PROCESSING} Analizando datos..."
    REPORT_READY = f"{Emojis.READY} Reporte listo. {{}} registros procesados"
    EXPORTING = f"{Emojis.EXPORT} Exportando... {{}}% ({{:,}}/{{:,}})"
    EXPORT_COMPLETE = f"{Emojis.READY} Exportado a {{}}"
    USING_CACHE = f"⚡ Usando resultados en caché (actualizados hace {{}} min)"
    CONNECTION_ERROR = f"{Emojis.ERROR} Error de conexión: {{}}"
    QUERY_ERROR = f"{Emojis.WARNING} La consulta tuvo un error. Déjame intentar de nuevo..."
    RETRY_FAILED = f"{Emojis.ERROR} No pude generar la consulta. ¿Puedes reformular?"