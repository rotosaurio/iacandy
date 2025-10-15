"""
Script para recrear ChromaDB con la función de distancia coseno correcta.
IMPORTANTE: Este script ELIMINA la colección existente y la recrea.
"""

import sys
import io
import shutil
import os

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import chromadb
from schema_manager import schema_manager

print("=" * 80)
print("🔧 CORRECCIÓN DE CHROMADB: Cambio a Distancia Coseno")
print("=" * 80)

print("\n⚠️  ADVERTENCIA: Este script eliminará la colección actual y la recreará.")
print("    La colección se regenerará automáticamente con los embeddings correctos.")

input("\nPresiona ENTER para continuar o Ctrl+C para cancelar...")

print("\n🗑️  Paso 1: Eliminando colección existente...")

try:
    # Conectar a ChromaDB
    client = chromadb.PersistentClient(path="./data/chroma_db")

    # Intentar eliminar la colección existente
    try:
        client.delete_collection(name="schema_embeddings")
        print("✓ Colección 'schema_embeddings' eliminada")
    except Exception as e:
        print(f"⚠️  No se pudo eliminar la colección (puede que no existiera): {e}")

    print("\n✨ Paso 2: Creando nueva colección con distancia coseno...")

    # Crear nueva colección CON distancia coseno
    collection = client.create_collection(
        name="schema_embeddings",
        metadata={"hnsw:space": "cosine"}  # ¡CLAVE! Usar distancia coseno
    )
    print("✓ Nueva colección creada con metadata:")
    print(f"  - Función de distancia: cosine")
    print(f"  - Metadata: {collection.metadata}")

    print("\n📊 Paso 3: Regenerando embeddings...")
    print("⏳ Esto tomará aproximadamente 60-90 segundos...")

    # Forzar recarga completa del esquema para regenerar embeddings
    schema_manager.load_and_process_schema(force_refresh=True, skip_embeddings=False)

    print("\n✅ ChromaDB recreado exitosamente con distancia coseno")
    print("\n🔍 Verificación: Probando búsqueda...")

    # Probar una búsqueda rápida
    test_query = "artículos más vendidos"
    query_embedding = schema_manager.embedding_generator.generate_embedding(test_query)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5
    )

    if results['ids'] and results['ids'][0]:
        print(f"\n📋 Top 5 resultados para '{test_query}':")
        for i in range(min(5, len(results['ids'][0]))):
            table_name = results['ids'][0][i]
            distance = results['distances'][0][i]
            similarity = 1 - distance

            print(f"  {i+1}. {table_name}")
            print(f"     Similitud: {similarity:.4f}")

            if similarity > 0:
                print(f"     ✅ Similitud POSITIVA (correcto)")
            else:
                print(f"     ❌ Similitud NEGATIVA (error persistente)")

    print("\n" + "=" * 80)
    print("✅ ¡PROCESO COMPLETADO!")
    print("=" * 80)
    print("\nAhora puedes:")
    print("  1. Reiniciar el servidor web (app.py)")
    print("  2. Probar la consulta: 'artículos más vendidos de febrero 2025'")
    print("=" * 80)

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
