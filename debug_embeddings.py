"""
Script de debug para inspeccionar embeddings y similitudes en ChromaDB.
"""

import sys
from schema_manager import schema_manager, TableDescriptor
from database import db

def main():
    print("=" * 80)
    print("DEBUG: Inspección de Embeddings y Similitud RAG")
    print("=" * 80)

    # Inicializar sistema
    print("\n🔄 Inicializando sistema...")
    try:
        # Inicializar vector store
        schema_manager.vector_store.initialize()
        print("✓ Vector store inicializado")

        # Cargar esquema si no está cargado
        if not schema_manager.schema_cache:
            print("📚 Cargando esquema...")
            schema_manager.load_and_process_schema()
            print("✓ Esquema cargado")
        else:
            print("✓ Esquema ya en caché")
    except Exception as e:
        print(f"❌ Error inicializando: {e}")
        return

    # Consulta de prueba
    test_query = "artículos más vendidos febrero 2025"
    print(f"\n📝 Consulta de prueba: '{test_query}'")

    # Generar embedding de la consulta
    print("\n🧠 Generando embedding de la consulta...")
    query_embedding = schema_manager.embedding_generator.generate_embedding(test_query)
    print(f"✓ Embedding generado (dimensiones: {len(query_embedding)})")

    # Buscar en ChromaDB SIN filtro de threshold
    print("\n🔍 Buscando en ChromaDB (top 10 sin threshold)...")
    try:
        results = schema_manager.vector_store.collection.query(
            query_embeddings=[query_embedding],
            n_results=10
        )

        print(f"\n📊 Resultados de ChromaDB (top 10):")
        print("-" * 80)

        if results['ids'] and results['ids'][0]:
            for i in range(len(results['ids'][0])):
                table_name = results['ids'][0][i]
                distance = results['distances'][0][i]
                similarity = 1 - distance
                description = results['documents'][0][i][:150]  # Primeros 150 chars

                print(f"\n{i+1}. Tabla: {table_name}")
                print(f"   Similitud: {similarity:.4f} (distancia: {distance:.4f})")
                print(f"   Descripción: {description}...")

                # Verificar si supera threshold
                threshold = 0.5
                status = "✓ PASA" if similarity >= threshold else "✗ RECHAZADA"
                print(f"   Threshold 0.5: {status}")
        else:
            print("⚠️ No se encontraron resultados en ChromaDB")

    except Exception as e:
        print(f"❌ Error consultando ChromaDB: {e}")

    # Mostrar descripciones de tablas clave
    print("\n" + "=" * 80)
    print("📋 Descripciones de tablas clave en el sistema:")
    print("=" * 80)

    key_tables = ['DOCTOS_PV_DET', 'ARTICULOS', 'DOCTOS_PV', 'CLIENTES']

    for table_name in key_tables:
        if table_name in schema_manager.schema_cache.get('full_schema', {}):
            table_info = schema_manager.schema_cache['full_schema'][table_name]

            # Obtener muestra de datos
            sample_data = []
            try:
                sample_query = f"SELECT FIRST 5 * FROM {table_name}"
                result = db.execute_query(sample_query)
                if result and result.data:
                    sample_data = result.data[:5]
            except:
                pass

            # Generar descripción
            description = TableDescriptor.describe_table(table_info, sample_data)

            print(f"\n🗂️  {table_name}")
            print(f"   Registros: {table_info.row_count}")
            print(f"   Columnas: {len(table_info.columns)}")
            print(f"   Descripción completa:")
            print(f"   {description}")
            print("-" * 80)

    # Comparación directa: consulta vs tabla específica
    print("\n" + "=" * 80)
    print("🔬 Comparación directa: Consulta vs DOCTOS_PV_DET")
    print("=" * 80)

    if 'DOCTOS_PV_DET' in schema_manager.schema_cache.get('full_schema', {}):
        table_info = schema_manager.schema_cache['full_schema']['DOCTOS_PV_DET']

        # Obtener descripción de la tabla
        try:
            sample_query = "SELECT FIRST 5 * FROM DOCTOS_PV_DET"
            result = db.execute_query(sample_query)
            sample_data = result.data[:5] if result and result.data else []
        except:
            sample_data = []

        table_description = TableDescriptor.describe_table(table_info, sample_data)
        table_embedding = schema_manager.embedding_generator.generate_embedding(table_description)

        # Calcular similitud coseno manualmente
        import numpy as np
        query_vec = np.array(query_embedding)
        table_vec = np.array(table_embedding)

        cosine_similarity = np.dot(query_vec, table_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(table_vec))

        print(f"\n📏 Similitud coseno: {cosine_similarity:.4f}")
        print(f"   Threshold configurado: 0.5")
        print(f"   ¿Supera threshold?: {'✓ SÍ' if cosine_similarity >= 0.5 else '✗ NO'}")

        print(f"\n📝 Consulta: '{test_query}'")
        print(f"📋 Descripción tabla:")
        print(f"   {table_description}")

    print("\n" + "=" * 80)
    print("✅ Debug completado")
    print("=" * 80)

if __name__ == "__main__":
    main()
