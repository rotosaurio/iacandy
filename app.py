#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firebird AI Assistant - Servidor Web
Interfaz web para consultar bases de datos Firebird usando IA
"""

import os
import sys
import io
import json
import uuid
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# Configurar encoding UTF-8 para Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    else:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from flask import Flask, render_template, request, jsonify, send_file, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import pandas as pd

# Importar módulos del sistema
from config import config, SYSTEM_NAME, VERSION
from database import db
from schema_manager import schema_manager
from ai_assistant import ai_assistant
from report_generator import report_generator
from utils import logger, DataFormatter

# Crear aplicación Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

# Habilitar CORS
CORS(app)

# Inicializar SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Estado global de la aplicación
app_state = {
    'initialized': False,
    'db_connected': False,
    'schema_loaded': False,
    'sessions': {}
}

# Función para inicializar el sistema de forma bloqueante
def initialize_blocking():
    """
    Inicialización BLOQUEANTE con logging detallado.
    El sistema NO estará disponible hasta que TODO esté cargado.
    Esta función bloquea completamente hasta que todas las fases se completen.
    """
    import time

    try:
        logger.info("🚀 Iniciando inicialización completa (bloqueante)...")

        # ========== FASE 1: CONEXIÓN A BASE DE DATOS ==========
        logger.info("📡 Fase 1/3: Conectando a base de datos...")
        start_time = time.time()
        if not db.connect():
            logger.error("❌ No se pudo conectar a la base de datos")
            return False

        connection_time = time.time() - start_time
        app_state['db_connected'] = True
        logger.info(f"✅ Fase 1 completada en {connection_time:.2f}s")

        # ========== FASE 2: CARGA COMPLETA CON EMBEDDINGS (TODO EN UNO) ==========
        logger.info("📋 Fase 2/2: Cargando esquema completo CON embeddings...")
        logger.info("⏳ Este proceso puede tardar 3-5 minutos, por favor espere...")
        start_time = time.time()

        # Cargar esquema COMPLETO directamente (sin fase básica primero)
        # force_refresh=True para asegurar que se regeneren los embeddings
        # skip_embeddings=False para procesar TODOS los embeddings
        schema_data = schema_manager.load_and_process_schema(
            force_refresh=True,
            skip_embeddings=False
        )

        if not schema_data:
            logger.error("❌ No se pudo cargar el esquema")
            return False

        schema_time = time.time() - start_time
        stats = schema_data.get('stats', {})
        embeddings_count = len(schema_data.get('table_embeddings', {}))

        logger.info(f"✅ Fase 2 completada en {schema_time:.1f}s")
        logger.info(f"   - Tablas cargadas: {stats.get('total_tables', 0)}")
        logger.info(f"   - Tablas activas: {stats.get('active_tables', 0)}")
        logger.info(f"   - Embeddings generados: {embeddings_count}")

        # AHORA SÍ marcar como inicializado (todo está completo)
        app_state['schema_loaded'] = True
        app_state['initialized'] = True

        total_time = connection_time + schema_time
        logger.info(f"✅ Sistema COMPLETAMENTE inicializado en {total_time:.1f}s")
        logger.info(f"✅ Sistema listo para uso con máxima precisión")

        return True

    except Exception as e:
        logger.error(f"❌ Error en inicialización automática: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

@app.route('/')
def index():
    """Página principal"""
    return render_template('index.html', 
                         system_name=SYSTEM_NAME,
                         version=VERSION,
                         db_path=config.database.database_path)

@app.route('/api/status', methods=['GET'])
def get_status():
    """Obtener estado del sistema"""
    try:
        # Verificar conexión a DB
        connected = db.is_connected()
        db_status = "connected" if connected else "disconnected"

        # Consultar esquema en caché para no depender solo de app_state
        schema_data = schema_manager.schema_cache if getattr(schema_manager, 'schema_cache', None) else None
        schema_stats = schema_data.get('stats', {}) if schema_data else None
        schema_loaded = app_state['schema_loaded'] or (schema_data is not None)

        # Derivar "initialized" de condiciones reales
        initialized = app_state['initialized'] or (connected and schema_loaded)

        # Auto-corregir app_state si hay desincronización
        if initialized and not app_state['initialized']:
            app_state['initialized'] = True
        if connected and not app_state['db_connected']:
            app_state['db_connected'] = True
        if schema_loaded and not app_state['schema_loaded']:
            app_state['schema_loaded'] = True
        
        return jsonify({
            'status': 'ok',
            'initialized': initialized,
            'database': {
                'connected': connected,
                'status': db_status,
                'path': config.database.database_path
            },
            'schema': {
                'loaded': schema_loaded,
                'stats': schema_stats
            },
            'ai': {
                'model': config.ai.model,
                'provider': 'OpenAI'
            }
        })
    except Exception as e:
        logger.error("Error obteniendo estado", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/initialize', methods=['POST'])
def initialize_system():
    """Inicializar el sistema (versión mejorada con mejor manejo de errores)"""
    import time

    try:
        if app_state['initialized']:
            return jsonify({'status': 'already_initialized'})

        logger.info("🚀 Iniciando inicialización del sistema...")

        # Paso 1: Conectar a base de datos con timeout
        socketio.emit('status_update', {'message': '🔌 Conectando a base de datos...'})

        start_time = time.time()
        if not db.connect():
            logger.error("❌ No se pudo conectar a la base de datos")
            return jsonify({'error': 'No se pudo conectar a la base de datos'}), 500

        connection_time = time.time() - start_time
        app_state['db_connected'] = True
        logger.info(f"✅ Base de datos conectada en {connection_time:.2f}s")
        socketio.emit('status_update', {'message': '✅ Base de datos conectada'})

        # Paso 2: Cargar esquema básico primero
        socketio.emit('status_update', {'message': '📊 Cargando esquema básico...'})

        start_time = time.time()
        schema_data = schema_manager.load_and_process_schema_basic()

        if not schema_data:
            logger.warning("⚠️ No se pudo cargar esquema básico, intentando con esquema mínimo...")
            schema_data = schema_manager.load_and_process_schema_basic(force_minimal=True)

        if not schema_data:
            logger.error("❌ No se pudo cargar ningún esquema")
            return jsonify({'error': 'No se pudo cargar el esquema de la base de datos'}), 500

        schema_time = time.time() - start_time
        app_state['schema_loaded'] = True

        stats = schema_data.get('stats', {})
        logger.info(f"✅ Esquema básico cargado en {schema_time:.2f}s: {stats.get('active_tables', 0)} tablas activas")

        socketio.emit('status_update', {
            'message': f"✅ Esquema cargado: {stats.get('active_tables', 0)} tablas activas"
        })

        # Paso 3: Procesar embeddings en segundo plano si es posible
        if not schema_data.get('is_basic', False):
            logger.info("🧠 Procesando embeddings en segundo plano...")
            import threading
            def process_embeddings():
                try:
                    logger.info("🔄 Procesando embeddings avanzados...")
                    schema_manager.load_and_process_schema(force_refresh=True)
                    logger.info("✅ Procesamiento de embeddings completado")
                except Exception as e:
                    logger.warning(f"⚠️ Error procesando embeddings avanzados: {e}")

            # Iniciar procesamiento avanzado después de 10 segundos
            threading.Timer(10.0, process_embeddings).start()

        # Marcar como inicializado
        app_state['initialized'] = True

        total_time = connection_time + schema_time
        logger.info(f"✅ Sistema inicializado completamente en {total_time:.2f}s")

        return jsonify({
            'status': 'initialized',
            'schema_stats': stats,
            'initialization_time': total_time,
            'is_basic_schema': schema_data.get('is_basic', False)
        })

    except Exception as e:
        logger.error(f"❌ Error inicializando sistema: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """Procesar consulta de chat"""
    try:
        logger.info("🎯 [/api/chat] Endpoint llamado")

        data = request.json
        logger.info(f"📝 [/api/chat] Datos recibidos: {data}")

        message = data.get('message', '').strip()
        session_id = data.get('session_id', str(uuid.uuid4()))

        logger.info(f"💬 [/api/chat] Mensaje: '{message[:100]}...' (Session: {session_id})")

        if not message:
            logger.warning("⚠️ [/api/chat] Mensaje vacío recibido")
            return jsonify({'error': 'Mensaje vacío'}), 400

        if not app_state['initialized']:
            logger.warning("⚠️ [/api/chat] Sistema no inicializado")
            return jsonify({'error': 'Sistema no inicializado'}), 503

        # Procesar con IA
        logger.info(f"🤖 [/api/chat] Procesando consulta con IA: {message[:100]}...")

        response = ai_assistant.chat(message, session_id)
        logger.info(f"✅ [/api/chat] Respuesta generada correctamente")
        
        # Formatear respuesta
        result = {
            'session_id': session_id,
            'message': response.message,
            'sql_query': response.sql_generated,
            'has_data': response.has_data,
            'timestamp': datetime.now().isoformat()
        }
        
        # Agregar datos si hay resultados
        if response.has_data and response.data:
            df = pd.DataFrame(response.data)

            # Convertir tipos no serializables a string
            for col in df.columns:
                # Convertir datetime.time, datetime.date, datetime.datetime a strings
                if df[col].dtype == 'object':
                    df[col] = df[col].apply(lambda x: str(x) if hasattr(x, '__str__') and not isinstance(x, str) else x)

            # Limitar preview a 100 filas
            preview_df = df.head(100)

            result['data'] = {
                'columns': df.columns.tolist(),
                'rows': preview_df.values.tolist(),
                'total_rows': len(df),
                'preview_rows': len(preview_df),
                'truncated': len(df) > 100
            }

            # Guardar DataFrame completo en sesión para exportación
            if session_id not in app_state['sessions']:
                app_state['sessions'][session_id] = {}
            app_state['sessions'][session_id]['last_data'] = df

        logger.info(f"📤 [/api/chat] Enviando respuesta al cliente")
        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ [/api/chat] Error procesando chat: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/export/<format>', methods=['POST'])
def export_data(format):
    """Exportar datos en diferentes formatos"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if not session_id or session_id not in app_state['sessions']:
            return jsonify({'error': 'Sesión inválida'}), 400
        
        session_data = app_state['sessions'][session_id]
        if 'last_data' not in session_data:
            return jsonify({'error': 'No hay datos para exportar'}), 400
        
        df = session_data['last_data']
        
        # Generar archivo según formato
        import tempfile
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}"
        
        # Usar directorio temporal de Windows
        temp_dir = tempfile.gettempdir()
        
        if format == 'excel':
            filepath = os.path.join(temp_dir, f"{filename}.xlsx")
            df.to_excel(filepath, index=False, engine='xlsxwriter')
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            download_name = f"{filename}.xlsx"
            
        elif format == 'csv':
            filepath = os.path.join(temp_dir, f"{filename}.csv")
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            mimetype = 'text/csv'
            download_name = f"{filename}.csv"
            
        elif format == 'json':
            filepath = os.path.join(temp_dir, f"{filename}.json")
            df.to_json(filepath, orient='records', force_ascii=False, indent=2)
            mimetype = 'application/json'
            download_name = f"{filename}.json"
            
        else:
            return jsonify({'error': f'Formato no soportado: {format}'}), 400
        
        return send_file(
            filepath,
            mimetype=mimetype,
            as_attachment=True,
            download_name=download_name
        )
        
    except Exception as e:
        logger.error(f"Error exportando datos en formato {format}", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/schema/tables', methods=['GET'])
def get_tables():
    """Obtener lista de tablas"""
    try:
        if not app_state['schema_loaded']:
            return jsonify({'error': 'Esquema no cargado'}), 503
        
        schema_data = schema_manager.schema_cache if getattr(schema_manager, 'schema_cache', None) else None
        if not schema_data:
            return jsonify({'error': 'No hay datos de esquema'}), 500
        
        tables = []
        full_schema = schema_data.get('full_schema', {})
        for table_name, tinfo in full_schema.items():
            # tinfo es instancia de TableInfo
            is_active = getattr(tinfo, 'is_active', True)
            if is_active:
                tables.append({
                    'name': table_name,
                    'type': getattr(tinfo, 'type', 'TABLE'),
                    'row_count': max(0, getattr(tinfo, 'row_count', 0) or 0),
                    'columns_count': len(getattr(tinfo, 'columns', []) or []),
                    'description': getattr(tinfo, 'description', '')
                })
        
        # Ordenar por nombre
        tables.sort(key=lambda x: x['name'])
        
        return jsonify({
            'tables': tables,
            'total': len(tables)
        })
        
    except Exception as e:
        logger.error("Error obteniendo tablas", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/schema/table/<table_name>', methods=['GET'])
def get_table_details(table_name):
    """Obtener detalles de una tabla específica"""
    try:
        if not app_state['schema_loaded']:
            return jsonify({'error': 'Esquema no cargado'}), 503
        
        schema_data = schema_manager.schema_cache if getattr(schema_manager, 'schema_cache', None) else None
        if not schema_data:
            return jsonify({'error': 'No hay datos de esquema'}), 500
        
        full_schema = schema_data.get('full_schema', {})
        if table_name not in full_schema:
            return jsonify({'error': f'Tabla no encontrada: {table_name}'}), 404
        
        tinfo = full_schema[table_name]
        
        return jsonify({
            'name': table_name,
            'type': getattr(tinfo, 'type', 'TABLE'),
            'columns': getattr(tinfo, 'columns', []),
            'primary_keys': getattr(tinfo, 'primary_keys', []),
            'foreign_keys': getattr(tinfo, 'foreign_keys', []),
            'indexes': getattr(tinfo, 'indexes', []),
            'row_count': max(0, getattr(tinfo, 'row_count', 0) or 0),
            'description': getattr(tinfo, 'description', '')
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo detalles de tabla {table_name}", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/schema/refresh', methods=['POST'])
def refresh_schema():
    """Forzar recarga del esquema (modo seguro para UI)."""
    try:
        # Obtener parámetros opcionales
        data_json = request.get_json() or {}
        update_stats = data_json.get('update_stats', False)
        
        if update_stats:
            # Solo actualizar estadísticas, no recargar esquema completo
            socketio.emit('status_update', {'message': '📊 Actualizando estadísticas...'})
            stats = schema_manager.update_statistics_only()
            socketio.emit('status_update', {'message': '✅ Estadísticas actualizadas'})
            return jsonify({
                'status': 'stats_updated',
                'schema_stats': stats,
                'last_update': schema_manager.last_schema_update.isoformat() if schema_manager.last_schema_update else None
            })
        else:
            # Recarga completa del esquema
            socketio.emit('status_update', {'message': '🔄 Actualizando esquema...'})
            data = schema_manager.load_and_process_schema(force_refresh=True)
            if not data:
                return jsonify({'error': 'No se pudo actualizar el esquema'}), 500
            app_state['schema_loaded'] = True
            app_state['initialized'] = True
            stats = data.get('stats', {})
            socketio.emit('status_update', {'message': f"✅ Esquema actualizado: {stats.get('active_tables', 0)} tablas activas"})
            return jsonify({
                'status': 'refreshed',
                'schema_stats': stats,
                'last_update': schema_manager.last_schema_update.isoformat() if schema_manager.last_schema_update else None
            })
    except Exception as e:
        logger.error("Error refrescando esquema", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/schema/stats/update', methods=['POST'])
def update_schema_stats():
    """Actualizar solo estadísticas (conteos) sin recargar todo el esquema."""
    try:
        # Obtener parámetros opcionales
        data_json = request.get_json() or {}
        table_names = data_json.get('tables', None)  # Lista de tablas o None para todas
        
        logger.info(f"Actualizando estadísticas de tablas: {len(table_names) if table_names else 'todas'}")
        
        # Actualizar estadísticas
        stats = schema_manager.update_statistics_only(table_names=table_names)
        
        return jsonify({
            'status': 'success',
            'updated': len(stats) > 0,
            'stats': stats,
            'total_updated': len(stats),
            'last_update': schema_manager.last_schema_update.isoformat() if schema_manager.last_schema_update else None,
            'next_auto_update': (schema_manager.last_schema_update + timedelta(seconds=schema_manager.auto_update_interval)).isoformat() if schema_manager.last_schema_update else None
        })
        
    except Exception as e:
        logger.error("Error actualizando estadísticas", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/schema/cache/info', methods=['GET'])
def get_cache_info():
    """Obtener información sobre el estado del caché de estadísticas."""
    try:
        cache_info = db.get_stats_cache_info()

        return jsonify({
            'status': 'success',
            'cache': cache_info,
            'schema_last_update': schema_manager.last_schema_update.isoformat() if schema_manager.last_schema_update else None
        })

    except Exception as e:
        logger.error("Error obteniendo info de caché", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/test/schema-extraction', methods=['GET'])
def test_schema_extraction():
    """Probar extracción completa de esquema con detalles de índices y FKs."""
    try:
        # Ejecutar prueba de extracción
        test_results = db.test_schema_extraction()

        return jsonify({
            'status': 'success',
            'test_results': test_results,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error("Error en prueba de extracción de esquema", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/table/<table_name>/columns', methods=['GET'])
def get_table_columns(table_name):
    """Obtener información detallada de columnas de una tabla específica."""
    try:
        columns_info = db.get_table_columns_info(table_name)

        return jsonify({
            'status': 'success',
            'table_info': columns_info,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error obteniendo columnas de tabla {table_name}", e)
        return jsonify({'error': str(e)}), 500

@app.route('/api/test/query-similarity/<table_name>', methods=['POST'])
def test_query_similarity(table_name):
    """Probar similitud entre una consulta y una tabla específica para debugging RAG."""
    try:
        data = request.json
        query = data.get('query', '')

        if not query:
            return jsonify({'error': 'Query requerida'}), 400

        similarity_info = db.test_query_embedding_similarity(query, table_name)

        return jsonify({
            'status': 'success',
            'similarity_info': similarity_info,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error probando similitud con tabla {table_name}", e)
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    """Manejar conexión de WebSocket"""
    logger.info(f"Cliente conectado: {request.sid}")
    emit('connected', {'message': 'Conectado al servidor'})

@socketio.on('disconnect')
def handle_disconnect():
    """Manejar desconexión de WebSocket"""
    logger.info(f"Cliente desconectado: {request.sid}")

@app.errorhandler(404)
def not_found(error):
    """Manejar errores 404"""
    return jsonify({'error': 'Endpoint no encontrado'}), 404

@app.errorhandler(500)
def internal_error(error):
    """Manejar errores 500"""
    logger.error(f"Error interno del servidor: {error}")
    return jsonify({'error': 'Error interno del servidor'}), 500

def cleanup():
    """Limpiar recursos al cerrar"""
    try:
        if db.is_connected():
            db.disconnect()
        logger.info("Recursos liberados")
    except Exception as e:
        logger.error("Error liberando recursos", e)

if __name__ == '__main__':
    try:
        # Registrar cleanup
        import atexit
        atexit.register(cleanup)
        
        # Mostrar información de inicio
        print(f"""
╔══════════════════════════════════════════════════════════╗
║          🤖 FIREBIRD AI ASSISTANT v{VERSION}              ║
║          Sistema Web de Consulta con IA                  ║
╚══════════════════════════════════════════════════════════╝

📂 Base de datos: {config.database.database_path}
🤖 Modelo IA: {config.ai.model}
🌐 Puerto: 8050
🔗 URL: http://localhost:8050
""")
        
        # Lanzar inicialización en background para no bloquear el arranque del servidor
        print("\n🔄 Inicializando sistema en segundo plano...")
        import threading
        threading.Thread(target=initialize_blocking, daemon=True).start()
        
        print("\n🚀 Iniciando servidor web...\n")
        
        # Iniciar servidor
        socketio.run(app, 
                    host='0.0.0.0', 
                    port=8050, 
                    debug=False,
                    use_reloader=False)
                    
    except KeyboardInterrupt:
        print("\n\n👋 Servidor detenido por el usuario")
    except Exception as e:
        print(f"\n❌ Error fatal: {e}")
        traceback.print_exc()