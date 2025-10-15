#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firebird AI Assistant - Sistema conversacional avanzado de IA para consulta de base de datos.

Este es el punto de entrada principal del sistema que inicializa todos los componentes
y lanza la interfaz gráfica.

Autor: AI Database Solutions
Versión: 1.0.0
"""

import sys
import os
import io
import traceback
from pathlib import Path

# Configurar encoding UTF-8 para Windows
if sys.platform == 'win32':
    # Establecer variable de entorno para UTF-8
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    # Reconfigurar stdout y stderr para usar UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    else:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Agregar el directorio actual al path para imports
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

try:
    # Importar configuración y verificar dependencias
    from config import config, SYSTEM_NAME, VERSION
    from utils import logger, clean_temp_files
    
    logger.info(f"Iniciando {SYSTEM_NAME} v{VERSION}")
    
    # Validar configuración
    is_valid, validation_message = config.validate_configuration()
    if not is_valid:
        logger.error(f"Configuración inválida: {validation_message}")
        print(f"❌ Error de configuración: {validation_message}")
        sys.exit(1)
    
    logger.info("Configuración validada exitosamente")
    
    # Limpiar archivos temporales antiguos
    try:
        cleaned_files = clean_temp_files()
        if cleaned_files > 0:
            logger.info(f"Archivos temporales limpiados: {cleaned_files}")
    except Exception as e:
        logger.warning(f"No se pudieron limpiar archivos temporales: {e}")
    
    # Verificar dependencias críticas
    missing_deps = []
    
    try:
        import firebird.driver
    except ImportError:
        missing_deps.append("firebird-driver")
    
    try:
        import openai
    except ImportError:
        missing_deps.append("openai")
    
    try:
        import chromadb
    except ImportError:
        missing_deps.append("chromadb")
    
    try:
        import sentence_transformers
    except ImportError:
        missing_deps.append("sentence-transformers")
    
    try:
        import tf_keras # Import tf_keras for Keras 3 compatibility
    except ImportError:
        missing_deps.append("tf-keras")
        # Add a placeholder for the user to install tf-keras
        print("Por favor, instala la versión compatible de Keras: pip install tf-keras")
    
    try:
        import pandas
    except ImportError:
        missing_deps.append("pandas")
    
    try:
        import openpyxl
    except ImportError:
        missing_deps.append("openpyxl")
    
    try:
        import xlsxwriter
    except ImportError:
        missing_deps.append("xlsxwriter")
    
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        missing_deps.append("PySide6")
    
    if missing_deps:
        error_message = f"""
❌ Dependencias faltantes detectadas:

{chr(10).join(f"  • {dep}" for dep in missing_deps)}

Por favor, instala las dependencias faltantes:
pip install {' '.join(missing_deps)}
"""
        print(error_message)
        logger.error(f"Dependencias faltantes: {missing_deps}")
        sys.exit(1)
    
    logger.info("Todas las dependencias están disponibles")
    
    # Importar módulos principales
    from database import db
    from ui_main import main as ui_main
    
except Exception as e:
    error_msg = f"Error crítico durante la inicialización: {str(e)}"
    print(f"❌ {error_msg}")
    
    # Intentar log si es posible
    try:
        logger.error(error_msg, e)
    except:
        pass
    
    # Mostrar traceback completo para debugging
    traceback.print_exc()
    sys.exit(1)


def check_system_requirements():
    """Verificar requisitos del sistema."""
    issues = []
    
    # Verificar versión de Python
    if sys.version_info < (3, 8):
        issues.append("Se requiere Python 3.8 o superior")
    
    # Verificar espacio en disco para logs y cache
    try:
        import shutil
        free_space = shutil.disk_usage(".")[2] / (1024**3)  # GB
        if free_space < 1:
            issues.append("Espacio en disco insuficiente (< 1GB disponible)")
    except:
        pass
    
    # Verificar permisos de escritura
    test_dirs = [
        config.export.output_directory,
        config.export.temp_directory,
        os.path.dirname(config.logging.log_file)
    ]
    
    for test_dir in test_dirs:
        if test_dir:
            try:
                os.makedirs(test_dir, exist_ok=True)
                test_file = os.path.join(test_dir, "test_write")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                issues.append(f"Sin permisos de escritura en: {test_dir}")
    
    return issues


def show_startup_info():
    """Mostrar información de inicio."""
    print(f"""
🤖 {SYSTEM_NAME} v{VERSION}
{'='*50}

Sistema conversacional avanzado de IA para consultar bases de datos Firebird 3.0
de forma completamente automática usando lenguaje natural.

Características:
✅ Consultas en lenguaje natural  
✅ Generación automática de SQL
✅ Sistema RAG para identificar tablas relevantes
✅ Análisis inteligente de resultados
✅ Exportación masiva con streaming
✅ Interfaz minimalista

Configuración:
📂 Base de datos: {config.database.database_path}
🔑 Usuario: {config.database.username}
🤖 Modelo IA: {config.ai.model}
📊 Tablas a analizar: ~500
🎯 Modo: Completamente automático

""")


def main():
    """Función principal del sistema."""
    try:
        # Mostrar información de inicio
        show_startup_info()
        
        # Verificar requisitos del sistema
        logger.info("Verificando requisitos del sistema...")
        system_issues = check_system_requirements()
        
        if system_issues:
            print("⚠️  Advertencias del sistema:")
            for issue in system_issues:
                print(f"   • {issue}")
            print()
        
        # Verificar configuración de la base de datos
        print("🔍 Verificando configuración de base de datos...")
        if not os.path.exists(config.database.database_path):
            print(f"❌ Base de datos no encontrada: {config.database.database_path}")
            print("\n💡 Asegúrate de que:")
            print("   1. La ruta de la base de datos sea correcta")
            print("   2. Tengas permisos de lectura sobre el archivo")
            print("   3. El servidor Firebird esté corriendo si es remoto")
            return 1
        
        print("✅ Base de datos encontrada")
        
        # Verificar API Key de OpenAI
        print("🔍 Verificando configuración de OpenAI...")
        if not config.ai.api_key or config.ai.api_key.startswith("sk-proj-se-"):
            print("⚠️  API Key de OpenAI detectada en configuración")
            print("   Asegúrate de que sea válida y tenga créditos disponibles")
        print("✅ API Key configurada")
        
        # Inicializar logging
        logger.info("=== INICIO DE SESIÓN ===")
        logger.info(f"Iniciando {SYSTEM_NAME} v{VERSION}")
        logger.info(f"Python {sys.version}")
        logger.info(f"Configuración: {config.to_dict()}")
        
        # Probar conexión a base de datos (opcional)
        print("🔌 Probando conexión inicial a base de datos...")
        try:
            connection_ok, conn_message = db.test_connection()
            if connection_ok:
                print(f"✅ {conn_message}")
                logger.info(f"Conexión a BD exitosa: {conn_message}")
            else:
                print(f"⚠️  {conn_message}")
                print("   La aplicación intentará conectar automáticamente al iniciar")
                logger.warning(f"Conexión inicial falló: {conn_message}")
        except Exception as e:
            print(f"⚠️  No se pudo probar la conexión: {str(e)}")
            print("   La aplicación intentará conectar automáticamente al iniciar")
            logger.warning(f"Error probando conexión: {e}")
        
        print("\n🚀 Iniciando interfaz gráfica...")
        print("   • La primera carga puede tomar unos minutos")
        print("   • Se analizará el esquema completo automáticamente") 
        print("   • El sistema estará listo cuando veas '✅ Sistema listo'\n")
        
        # Lanzar interfaz gráfica
        logger.info("Lanzando interfaz gráfica...")
        exit_code = ui_main()
        
        logger.info(f"Aplicación terminada con código: {exit_code}")
        return exit_code
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Aplicación interrumpida por el usuario")
        logger.info("Aplicación interrumpida por el usuario")
        return 0
        
    except Exception as e:
        error_msg = f"Error crítico en función principal: {str(e)}"
        print(f"\n❌ {error_msg}")
        logger.error(error_msg, e)
        
        print("\n🔧 Para debugging:")
        print("   1. Revisa el archivo de log para detalles completos")
        print(f"   2. Log ubicado en: {config.logging.log_file}")
        print("   3. Verifica que todas las dependencias estén instaladas")
        print("   4. Comprueba la configuración de la base de datos")
        
        return 1
    
    finally:
        # Limpiar recursos si es posible
        try:
            db.close()
        except:
            pass
        
        logger.info("=== FIN DE SESIÓN ===")


if __name__ == "__main__":
    sys.exit(main())