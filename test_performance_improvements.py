#!/usr/bin/env python3
"""
Script para probar las mejoras de rendimiento implementadas.
"""

import time
import sys
import os

# Agregar el directorio raíz al path para importar módulos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import FirebirdDB
from config import config

def test_performance_improvements():
    """Probar las mejoras de rendimiento implementadas."""
    print("🔧 Probando mejoras de rendimiento...")

    try:
        # Inicializar conexión
        db = FirebirdDB()
        if not db.connect():
            print("❌ Error conectando a la base de datos")
            return False

        # Query de prueba que debería beneficiarse de las mejoras
        test_query = """
        SELECT
            pv.DOCTO_PV_ID,
            pv.FECHA,
            al.NOMBRE AS ALMACEN,
            pvd.ARTICULO_ID,
            pvd.CLAVE_ARTICULO,
            a.NOMBRE AS ARTICULO,
            pvd.UNIDADES,
            pvd.PRECIO_TOTAL_NETO
        FROM DOCTOS_PV pv
        INNER JOIN DOCTOS_PV_DET pvd ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
        LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
        LEFT JOIN ALMACENES al ON al.ALMACEN_ID = pv.ALMACEN_ID
        WHERE pv.FECHA >= DATE '2025-01-01'
        ORDER BY pv.FECHA DESC
        """

        print(f"📊 Ejecutando query limitada a {config.ui.preview_row_limit} filas...")

        # Probar tiempo de ejecución
        start_time = time.time()
        result = db.execute_query_limited(test_query)
        execution_time = time.time() - start_time

        print("✅ Query ejecutada exitosamente:")
        print(f"   Tiempo: {execution_time:.2f} segundos")
        print(f"   Filas obtenidas: {result.row_count}")
        print(f"   Tiene más datos: {'Sí' if result.has_more_data else 'No'}")
        print(f"   Error: {'Sí' if result.error else 'No'}")

        if result.error:
            print(f"   ❌ Error: {result.error}")

        # Verificar que se aplicó la optimización
        if "SELECT FIRST" in result.sql.upper():
            print("✅ Optimización aplicada: SELECT FIRST agregado correctamente")
        else:
            print("⚠️ Optimización no aplicada correctamente")

        print("\n🎯 Prueba completada exitosamente!")
        return True

    except Exception as e:
        print(f"❌ Error durante la prueba: {e}")
        return False

if __name__ == "__main__":
    success = test_performance_improvements()
    sys.exit(0 if success else 1)
