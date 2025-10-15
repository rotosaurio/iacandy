"""
Verificar configuración de ChromaDB
"""

import sys
import io

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import chromadb

# Conectar
client = chromadb.PersistentClient(path="./data/chroma_db")
collection = client.get_collection(name="schema_embeddings")

print("=" * 80)
print("🔧 Configuración de ChromaDB")
print("=" * 80)

# Metadata de la colección
metadata = collection.metadata
print(f"\n📋 Metadata de la colección:")
for key, value in metadata.items():
    print(f"   {key}: {value}")

# Inspeccionar la configuración de la colección
print(f"\n📊 Nombre: {collection.name}")
print(f"📊 Total documentos: {collection.count()}")

# Obtener un embedding de ejemplo para verificar
result = collection.get(ids=["DOCTOS_PV_DET"], include=['embeddings'])
if result and result['embeddings']:
    embedding = result['embeddings'][0]
    print(f"\n🧮 Embedding de DOCTOS_PV_DET:")
    print(f"   Dimensiones: {len(embedding)}")
    print(f"   Primeros 5 valores: {embedding[:5]}")
    print(f"   Últimos 5 valores: {embedding[-5:]}")

    # Verificar si están normalizados
    import numpy as np
    norm = np.linalg.norm(embedding)
    print(f"   Norma L2: {norm:.4f}")
    print(f"   ¿Normalizado?: {'SÍ' if abs(norm - 1.0) < 0.01 else 'NO'}")
