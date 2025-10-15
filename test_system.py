#!/usr/bin/env python3
"""
Script de prueba para verificar el funcionamiento del sistema paso a paso.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_config():
    """Probar carga de configuración."""
    try:
        from config import config
        print("✅ Configuración cargada correctamente")
        print(f"   DB Path: {config.database.database_path}")
        print(f"   Vector DB Path: {config.rag.vector_db_path}")
        print(f"   Similarity Threshold: {config.rag.similarity_threshold}")
        return True
    except Exception as e:
        print(f"❌ Error cargando configuración: {e}")
        return False

def test_database_connection():
    """Probar conexión a base de datos."""
    try:
        from database import db
        if db.connect():
            print("✅ Conexión a base de datos exitosa")
            return True
        else:
            print("❌ No se pudo conectar a base de datos")
            return False
    except Exception as e:
        print(f"❌ Error conectando a base de datos: {e}")
        return False

def test_schema_loading():
    """Probar carga de esquema."""
    try:
        from schema_manager import schema_manager

        # Probar carga básica primero
        schema_data = schema_manager.load_and_process_schema_basic()
        if schema_data:
            stats = schema_data.get('stats', {})
            print(f"✅ Esquema básico cargado: {stats.get('total_tables', 0)} tablas")
            return True
        else:
            print("❌ No se pudo cargar esquema básico")
            return False
    except Exception as e:
        print(f"❌ Error cargando esquema: {e}")
        return False

def test_chroma_initialization():
    """Probar inicialización de ChromaDB."""
    try:
        from schema_manager import schema_manager

        # Probar inicialización del vector store
        schema_manager.vector_store.initialize()
        print("✅ Vector store inicializado correctamente")
        return True
    except Exception as e:
        print(f"❌ Error inicializando vector store: {e}")
        return False

def main():
    """Ejecutar todas las pruebas."""
    print("🔍 Iniciando pruebas del sistema...\n")

    tests = [
        ("Configuración", test_config),
        ("Conexión BD", test_database_connection),
        ("Carga esquema", test_schema_loading),
        ("ChromaDB", test_chroma_initialization),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n📋 Probando {test_name}:")
        result = test_func()
        results.append((test_name, result))

    print("\n" + "="*50)
    print("📊 RESULTADOS DE PRUEBAS:")
    for test_name, result in results:
        status = "✅ PASÓ" if result else "❌ FALLÓ"
        print(f"  {test_name}: {status}")

    all_passed = all(result for _, result in results)
    if all_passed:
        print("\n🎉 Todas las pruebas pasaron exitosamente!")
    else:
        print("\n⚠️ Algunas pruebas fallaron. Revisa los errores arriba.")

    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
