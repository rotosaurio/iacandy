"""Script para investigar qué es una VENTA GLOBAL."""
from database import FirebirdDB
import pandas as pd

def main():
    db = FirebirdDB()

    print("=" * 80)
    print("INVESTIGACION: QUE ES UNA VENTA GLOBAL")
    print("=" * 80)

    # 1. Buscar el artículo VENTA GLOBAL
    print("\n1. Buscando artículo 'VENTA GLOBAL'...")
    sql1 = """
    SELECT ARTICULO_ID, NOMBRE, CLAVE_ARTICULO, TIPO, STATUS
    FROM ARTICULOS
    WHERE NOMBRE LIKE '%GLOBAL%'
    """
    r1 = db.execute_query_limited(sql1, 10)

    if r1.preview_data:
        print(f"   Encontrados {len(r1.preview_data)} artículos con 'GLOBAL':")
        for row in r1.preview_data[:5]:
            print(f"     - ID: {row[0]}, Nombre: '{row[1]}', Clave: '{row[2]}', Tipo: '{row[3]}', Status: '{row[4]}'")
    else:
        print("   No se encontraron artículos con 'GLOBAL'")

    # 2. Verificar diferencia entre DOCTOS_PV y DOCTOS_VE
    print("\n2. Investigando diferencia entre DOCTOS_PV y DOCTOS_VE...")

    # Contar registros en cada tabla
    sql2a = "SELECT COUNT(*) FROM DOCTOS_PV"
    r2a = db.execute_query_limited(sql2a, 1)
    count_pv = r2a.preview_data[0][0] if r2a.preview_data else 0

    sql2b = "SELECT COUNT(*) FROM DOCTOS_VE"
    r2b = db.execute_query_limited(sql2b, 1)
    count_ve = r2b.preview_data[0][0] if r2b.preview_data else 0

    print(f"   DOCTOS_PV: {count_pv:,} registros (Punto de Venta)")
    print(f"   DOCTOS_VE: {count_ve:,} registros (Ventas/Facturas)")

    # 3. Buscar ventas recientes en DOCTOS_VE (facturas reales)
    print("\n3. Buscando últimas ventas en DOCTOS_VE (facturas)...")
    sql3 = """
    SELECT FIRST 5
        ve.DOCTO_VE_ID,
        ve.FECHA,
        ve.TIPO_DOCTO,
        ve.STATUS,
        c.NOMBRE AS CLIENTE,
        ve.IMPORTE_NETO,
        ve.IMPORTE_TOTAL
    FROM DOCTOS_VE ve
    LEFT JOIN CLIENTES c ON c.CLIENTE_ID = ve.CLIENTE_ID
    ORDER BY ve.FECHA DESC
    """
    r3 = db.execute_query_limited(sql3, 5)

    if r3.preview_data:
        df3 = pd.DataFrame(r3.preview_data, columns=r3.columns)
        print("\n   Últimas 5 facturas (DOCTOS_VE):")
        print(df3.to_string(index=False))
    else:
        print("   No se encontraron facturas en DOCTOS_VE")

    # 4. Ver detalles de una factura real
    if r3.preview_data and len(r3.preview_data) > 0:
        ultimo_docto_ve = r3.preview_data[0][0]
        print(f"\n4. Detalle de la última factura (ID: {ultimo_docto_ve})...")

        sql4 = f"""
        SELECT FIRST 10
            ved.POSICION,
            a.NOMBRE AS ARTICULO,
            ved.CLAVE_ARTICULO,
            ved.UNIDADES,
            ved.PRECIO_UNITARIO,
            ved.PRECIO_TOTAL_NETO
        FROM DOCTOS_VE_DET ved
        LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = ved.ARTICULO_ID
        WHERE ved.DOCTO_VE_ID = {ultimo_docto_ve}
        ORDER BY ved.POSICION
        """
        r4 = db.execute_query_limited(sql4, 10)

        if r4.preview_data:
            df4 = pd.DataFrame(r4.preview_data, columns=r4.columns)
            print(f"\n   Artículos vendidos en factura {ultimo_docto_ve}:")
            print(df4.to_string(index=False))
        else:
            print(f"   No se encontraron detalles para factura {ultimo_docto_ve}")

    # 5. Verificar si hay ventas en DOCTOS_PV que NO sean VENTA GLOBAL
    print("\n5. Buscando ventas en DOCTOS_PV con artículos reales (no GLOBAL)...")
    sql5 = """
    SELECT FIRST 5
        pv.DOCTO_PV_ID,
        pv.FECHA,
        a.NOMBRE AS ARTICULO,
        pvd.UNIDADES,
        pvd.PRECIO_TOTAL_NETO
    FROM DOCTOS_PV pv
    INNER JOIN DOCTOS_PV_DET pvd ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
    LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
    WHERE a.NOMBRE NOT LIKE '%GLOBAL%'
      AND a.NOMBRE NOT LIKE '%CORTE%'
      AND pvd.UNIDADES > 0
    ORDER BY pv.FECHA DESC
    """
    r5 = db.execute_query_limited(sql5, 5)

    if r5.preview_data:
        df5 = pd.DataFrame(r5.preview_data, columns=r5.columns)
        print("\n   Últimas ventas PV con artículos reales:")
        print(df5.to_string(index=False))
    else:
        print("   No se encontraron ventas PV con artículos reales")

    # 6. Entender la relación entre PV y VE
    print("\n6. Análisis de la última VENTA GLOBAL (DOCTO_PV_ID: 79592878)...")
    sql6 = """
    SELECT
        pv.DOCTO_PV_ID,
        pv.FECHA,
        pv.FOLIO_FISCAL,
        pv.STATUS,
        pv.IMPORTE_NETO,
        pv.IMPORTE_TOTAL,
        al.NOMBRE AS ALMACEN
    FROM DOCTOS_PV pv
    LEFT JOIN ALMACENES al ON al.ALMACEN_ID = pv.ALMACEN_ID
    WHERE pv.DOCTO_PV_ID = 79592878
    """
    r6 = db.execute_query_limited(sql6, 1)

    if r6.preview_data:
        print("\n   Detalle del documento:")
        for i, col in enumerate(r6.columns):
            print(f"     {col}: {r6.preview_data[0][i]}")

    print("\n" + "=" * 80)
    print("CONCLUSIONES:")
    print("=" * 80)
    print("- DOCTOS_PV: Documentos de punto de venta (tickets, ventas rápidas)")
    print("- DOCTOS_VE: Documentos de venta (facturas, notas de venta formales)")
    print("- 'VENTA GLOBAL': Posiblemente un artículo comodín o venta sin desglose")
    print("\nPara consultas de ventas reales con artículos, usa DOCTOS_VE en vez de DOCTOS_PV")
    print("=" * 80)

    db.close()

if __name__ == "__main__":
    main()
