"""
Script rápido para revisar qué hay en ChromaDB sin cargar todo el esquema.
"""

import sys
import io

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import chromadb
from sentence_transformers import SentenceTransformer
import numpy as np

# Conectar a ChromaDB existente
client = chromadb.PersistentClient(path="./data/chroma_db")
collection = client.get_collection(name="schema_embeddings")

print("=" * 80)
print("🔍 Inspección de ChromaDB")
print("=" * 80)

# Estadísticas
count = collection.count()
print(f"\n📊 Total de tablas en ChromaDB: {count}")

# Consulta de prueba
test_query = "artículos más vendidos febrero 2025"
print(f"\n📝 Consulta de prueba: '{test_query}'")

# Cargar modelo para generar embedding
print("\n🧠 Cargando modelo de embeddings...")
model = SentenceTransformer("all-MiniLM-L6-v2")
query_embedding = model.encode(test_query).tolist()
print(f"✓ Embedding generado (dimensiones: {len(query_embedding)})")

# Buscar en ChromaDB (top 15)
print("\n🔍 Buscando en ChromaDB (top 15, sin threshold)...")
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=15
)

print(f"\n📋 Resultados (ordenados por similitud):")
print("-" * 80)

if results['ids'] and results['ids'][0]:
    for i in range(len(results['ids'][0])):
        table_name = results['ids'][0][i]
        distance = results['distances'][0][i]
        similarity = 1 - distance
        description = results['documents'][0][i]

        print(f"\n{i+1}. 📊 {table_name}")
        print(f"   Similitud: {similarity:.4f} | Distancia: {distance:.4f}")

        # Mostrar primeras 3 líneas de descripción
        desc_lines = description.split('|')[:3]
        for line in desc_lines:
            print(f"   • {line.strip()}")

        # Estado threshold
        threshold = 0.5
        if similarity >= threshold:
            print(f"   ✅ SUPERA threshold ({threshold})")
        else:
            print(f"   ❌ NO supera threshold ({threshold}) - Diferencia: {threshold - similarity:.4f}")
else:
    print("⚠️ No se encontraron resultados")

# Buscar tabla específica
print("\n" + "=" * 80)
print("🔍 Información de tabla específica: DOCTOS_PV_DET")
print("=" * 80)

try:
    result = collection.get(ids=["DOCTOS_PV_DET"])
    if result and result['ids']:
        print(f"\n✓ Tabla encontrada en ChromaDB")
        print(f"\n📋 Descripción completa:")
        description = result['documents'][0]
        for i, part in enumerate(description.split('|'), 1):
            print(f"  {i}. {part.strip()}")

        # Calcular similitud directa
        table_embedding = result['embeddings'][0]
        query_vec = np.array(query_embedding)
        table_vec = np.array(table_embedding)
        cosine_sim = np.dot(query_vec, table_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(table_vec))

        print(f"\n📏 Similitud directa con la consulta: {cosine_sim:.4f}")
        print(f"   Threshold: 0.5")
        print(f"   ¿Supera?: {'✅ SÍ' if cosine_sim >= 0.5 else '❌ NO'}")
    else:
        print("❌ Tabla no encontrada")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 80)
print("✅ Inspección completada")
print("=" * 80)
