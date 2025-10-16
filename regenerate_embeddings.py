"""
Script para regenerar embeddings con descripciones mejoradas.
Esto actualizará el sistema RAG con:
- COLUMN_SEMANTICS mejorado (160+ columnas documentadas)
- FK y PK explícitas en descripciones
- Patrones de consulta SQL comunes
- Términos de búsqueda expandidos
"""

import sys
import time
from schema_manager import schema_manager

def main():
    print("=" * 70)
    print("REGENERACIÓN DE EMBEDDINGS CON SISTEMA RAG MEJORADO")
    print("=" * 70)
    print()
    print("Mejoras incluidas:")
    print("  ✓ COLUMN_SEMANTICS con 160+ columnas documentadas")
    print("  ✓ FK y PK explícitas en descripciones")
    print("  ✓ Patrones de consulta SQL comunes por tabla")
    print("  ✓ Términos de búsqueda expandidos (25 por tabla)")
    print("  ✓ Contexto semántico enriquecido")
    print()
    print("=" * 70)
    print()

    input("Presiona ENTER para continuar (tomará 3-4 minutos)...")
    print()

    start_time = time.time()

    try:
        print("🔄 Iniciando regeneración de embeddings...")
        print()

        # Forzar recarga completa del esquema
        schema_manager.load_and_process_schema(
            force_refresh=True,
            skip_embeddings=False
        )

        elapsed = time.time() - start_time
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)

        print()
        print("=" * 70)
        print(f"✅ REGENERACIÓN COMPLETADA EXITOSAMENTE en {minutes}m {seconds}s")
        print("=" * 70)
        print()
        print("Próximos pasos:")
        print("  1. Reinicia app.py o main.py")
        print("  2. Prueba con: 'cuantos articulos hay activos?'")
        print("  3. Deberías ver similitud > 0.7 (antes era 0.45)")
        print()

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️ Proceso interrumpido por el usuario")
        return 1

    except Exception as e:
        print(f"\n\n❌ ERROR durante regeneración: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
