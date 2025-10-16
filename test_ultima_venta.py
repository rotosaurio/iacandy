"""Script para diagnosticar por qué no se encuentran ventas."""
import sys
from database import FirebirdDB
from datetime import datetime

def main():
    print("=" * 70)
    print("DIAGNOSTICO: ULTIMA VENTA REGISTRADA")
    print("=" * 70)

    db = FirebirdDB()

    # Test 1: ¿Hay alguna venta?
    print("\n1. Verificando si existen ventas en DOCTOS_PV...")
    query1 = "SELECT FIRST 1 DOCTO_PV_ID, FECHA FROM DOCTOS_PV ORDER BY FECHA DESC"
    result1 = db.execute_query_limited(query1)

    if result1 and result1.data:
        print(f"   ✓ SÍ hay ventas. Última venta:")
        print(f"     - DOCTO_PV_ID: {result1.data[0][0]}")
        print(f"     - FECHA: {result1.data[0][1]}")
        ultimo_id = result1.data[0][0]
    else:
        print("   ✗ NO hay ventas en DOCTOS_PV")
        return 1

    # Test 2: ¿Esa venta tiene detalles?
    print(f"\n2. Verificando detalles de la venta {ultimo_id}...")
    query2 = f"""
    SELECT COUNT(*)
    FROM DOCTOS_PV_DET
    WHERE DOCTO_PV_ID = {ultimo_id}
    """
    result2 = db.execute_query_limited(query2)

    if result2 and result2.data:
        count = result2.data[0][0]
        print(f"   ✓ La venta tiene {count} líneas de detalle")
    else:
        print("   ✗ No se pudo contar detalles")

    # Test 3: ¿Cuántos detalles tienen UNIDADES > 0?
    print(f"\n3. Verificando detalles con UNIDADES > 0...")
    query3 = f"""
    SELECT COUNT(*)
    FROM DOCTOS_PV_DET
    WHERE DOCTO_PV_ID = {ultimo_id}
      AND UNIDADES > 0
    """
    result3 = db.execute_query_limited(query3)

    if result3 and result3.data:
        count = result3.data[0][0]
        print(f"   → {count} líneas con UNIDADES > 0")

    # Test 4: ¿Cuántos tienen PRECIO_TOTAL_NETO > 0?
    print(f"\n4. Verificando detalles con PRECIO_TOTAL_NETO > 0...")
    query4 = f"""
    SELECT COUNT(*)
    FROM DOCTOS_PV_DET
    WHERE DOCTO_PV_ID = {ultimo_id}
      AND PRECIO_TOTAL_NETO > 0
    """
    result4 = db.execute_query_limited(query4)

    if result4 and result4.data:
        count = result4.data[0][0]
        print(f"   → {count} líneas con PRECIO_TOTAL_NETO > 0")

    # Test 5: ¿Cuántos tienen artículo válido?
    print(f"\n5. Verificando artículos válidos (sin filtros de nombre)...")
    query5 = f"""
    SELECT COUNT(*)
    FROM DOCTOS_PV_DET pvd
    LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
    WHERE pvd.DOCTO_PV_ID = {ultimo_id}
    """
    result5 = db.execute_query_limited(query5)

    if result5 and result5.data:
        count = result5.data[0][0]
        print(f"   → {count} líneas con artículos (con LEFT JOIN)")

    # Test 6: ¿Qué pasa si aplicamos todos los filtros?
    print(f"\n6. Aplicando TODOS los filtros de la consulta original...")
    query6 = f"""
    SELECT COUNT(*)
    FROM DOCTOS_PV_DET pvd
    LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
    WHERE pvd.DOCTO_PV_ID = {ultimo_id}
      AND pvd.UNIDADES > 0
      AND pvd.PRECIO_TOTAL_NETO > 0
      AND (
            a.NOMBRE IS NULL OR (
                a.NOMBRE NOT LIKE '%GLOBAL%'
            AND a.NOMBRE NOT LIKE '%CORTE%'
            AND a.NOMBRE NOT LIKE '%SISTEMA%'
            )
          )
    """
    result6 = db.execute_query_limited(query6)

    if result6 and result6.data:
        count = result6.data[0][0]
        print(f"   → {count} líneas después de TODOS los filtros")
        if count == 0:
            print("\n   ⚠️ PROBLEMA ENCONTRADO: Los filtros eliminan todas las líneas")

    # Test 7: Mostrar los artículos reales de esa venta
    print(f"\n7. Mostrando artículos REALES de la venta (sin filtros)...")
    query7 = f"""
    SELECT FIRST 5
        pvd.POSICION,
        pvd.ARTICULO_ID,
        a.NOMBRE AS ARTICULO,
        pvd.UNIDADES,
        pvd.PRECIO_TOTAL_NETO
    FROM DOCTOS_PV_DET pvd
    LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
    WHERE pvd.DOCTO_PV_ID = {ultimo_id}
    ORDER BY pvd.POSICION
    """
    result7 = db.execute_query_limited(query7)

    if result7 and result7.data:
        print(f"   Primeras 5 líneas:")
        for row in result7.data:
            pos, art_id, nombre, unidades, precio = row
            print(f"     {pos}. Art {art_id}: '{nombre}' - {unidades} unid. - ${precio}")

    # Test 8: ¿Qué nombres de artículos están siendo filtrados?
    print(f"\n8. Verificando si hay artículos con nombres problemáticos...")
    query8 = f"""
    SELECT FIRST 5
        a.NOMBRE
    FROM DOCTOS_PV_DET pvd
    LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
    WHERE pvd.DOCTO_PV_ID = {ultimo_id}
      AND (
            a.NOMBRE LIKE '%GLOBAL%' OR
            a.NOMBRE LIKE '%CORTE%' OR
            a.NOMBRE LIKE '%SISTEMA%'
          )
    """
    result8 = db.execute_query_limited(query8)

    if result8 and result8.data and len(result8.data) > 0:
        print(f"   → SÍ hay artículos siendo filtrados:")
        for row in result8.data:
            print(f"     - '{row[0]}'")
    else:
        print(f"   → NO hay artículos con esos nombres")

    print("\n" + "=" * 70)
    print("RECOMENDACION:")
    print("=" * 70)
    print("La consulta original tiene filtros demasiado restrictivos.")
    print("Debería simplificarse para mostrar TODAS las líneas de la venta.")
    print("=" * 70)

    db.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
