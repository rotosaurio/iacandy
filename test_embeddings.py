"""Test script para verificar que los embeddings de OpenAI funcionan correctamente."""

import sys
sys.path.insert(0, r'C:\Users\USER\Desktop\iacandy')

from schema_manager import EmbeddingGenerator

print("=" * 60)
print("TEST: Generación de Embeddings con OpenAI")
print("=" * 60)

try:
    print("\n1. Inicializando EmbeddingGenerator...")
    eg = EmbeddingGenerator()
    print("   ✓ EmbeddingGenerator creado")

    print("\n2. Generando embedding de prueba para: 'tabla de ventas'...")
    emb = eg.generate_embedding('tabla de ventas')
    print(f"   ✓ Embedding generado: {len(emb)} dimensiones")
    print(f"   ✓ Primeros 5 valores: {emb[:5]}")

    print("\n3. Generando batch de embeddings...")
    batch_emb = eg.generate_batch_embeddings(['clientes', 'articulos', 'facturas'])
    print(f"   ✓ Batch generado: {len(batch_emb)} embeddings")
    print(f"   ✓ Dimensiones: {len(batch_emb[0])}")

    print("\n" + "=" * 60)
    print("✅ TODAS LAS PRUEBAS PASARON - OpenAI Embeddings funciona!")
    print("=" * 60)

except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
