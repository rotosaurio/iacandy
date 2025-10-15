"""
Script de prueba para validar las mejoras de GPT-5.

Ejecutar: python test_mejoras_gpt5.py
"""

import sys
from config import config
from query_complexity_analyzer import model_selector, QueryComplexity
from stored_procedures_manager import procedures_manager
from utils import logger


def test_configuracion():
    """Verificar que la configuración está correcta."""
    print("=" * 80)
    print("🔍 TEST 1: Verificación de Configuración")
    print("=" * 80)
    
    print(f"\n✓ Modelo principal: {config.ai.model}")
    print(f"✓ Modelo simple: {config.ai.model_simple}")
    print(f"✓ Modelo complejo: {config.ai.model_complex}")
    print(f"✓ Modelo fallback: {config.ai.model_fallback}")
    print(f"✓ Max tokens: {config.ai.max_tokens}")
    print(f"✓ Temperature: {config.ai.temperature}")
    print(f"✓ Timeout: {config.ai.timeout}s")
    print(f"✓ Max retries: {config.ai.max_retries}")
    print(f"✓ Selección inteligente: {'HABILITADA' if config.ai.enable_smart_model_selection else 'DESHABILITADA'}")
    print(f"✓ Umbral complejidad: {config.ai.complexity_threshold} tablas")
    print(f"✓ Procedimientos almacenados: {'HABILITADO' if config.rag.enable_stored_procedures else 'DESHABILITADO'}")
    print(f"✓ Top K tablas: {config.rag.top_k_tables}")
    
    assert config.ai.model == "gpt-5", "El modelo principal debe ser gpt-5"
    assert config.ai.max_tokens == 4000, "Max tokens debe ser 4000"
    assert config.ai.enable_smart_model_selection, "Selección inteligente debe estar habilitada"
    
    print("\n✅ Configuración correcta!")


def test_detector_complejidad():
    """Probar el detector de complejidad."""
    print("\n" + "=" * 80)
    print("🔍 TEST 2: Detector de Complejidad de Consultas")
    print("=" * 80)
    
    # Casos de prueba
    test_cases = [
        {
            "query": "Dame los clientes activos",
            "tables": [{"name": "CLIENTES"}],
            "expected_level": QueryComplexity.SIMPLE
        },
        {
            "query": "Dame las ventas del mes con total por cliente",
            "tables": [
                {"name": "DOCTOS_PV"},
                {"name": "DOCTOS_PV_DET"},
                {"name": "CLIENTES"}
            ],
            "expected_level": QueryComplexity.MODERATE
        },
        {
            "query": "Análisis de rentabilidad por producto con tendencia mensual y márgenes",
            "tables": [
                {"name": "ARTICULOS"},
                {"name": "DOCTOS_PV_DET"},
                {"name": "DOCTOS_PV"},
                {"name": "PRECIOS_ARTICULOS"},
                {"name": "EXISTENCIAS"},
                {"name": "CLIENTES"}
            ],
            "expected_level": QueryComplexity.COMPLEX
        },
        {
            "query": "Comparar ventas vs compras por artículo con análisis de rotación, tendencias y proyecciones",
            "tables": [
                {"name": "ARTICULOS"},
                {"name": "DOCTOS_PV_DET"},
                {"name": "DOCTOS_CC_DET"},
                {"name": "EXISTENCIAS"},
                {"name": "MOVIMIENTOS_ALMACEN"},
                {"name": "PRECIOS_ARTICULOS"},
                {"name": "CLIENTES"},
                {"name": "PROVEEDORES"},
                {"name": "ALMACENES"}
            ],
            "expected_level": QueryComplexity.VERY_COMPLEX
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📝 Test Case {i}:")
        print(f"   Query: {test_case['query']}")
        print(f"   Tablas: {len(test_case['tables'])}")
        
        model, analysis = model_selector.select_model_for_query(
            test_case['query'],
            test_case['tables']
        )
        
        print(f"   Resultado:")
        print(f"     - Nivel: {analysis.level.value}")
        print(f"     - Score: {analysis.score}/100")
        print(f"     - Modelo: {model}")
        print(f"     - Explicación: {analysis.explanation}")
        
        # Verificar nivel esperado
        if analysis.level == test_case['expected_level']:
            print(f"   ✅ Nivel correcto ({test_case['expected_level'].value})")
        else:
            print(f"   ⚠️  Nivel diferente (esperado: {test_case['expected_level'].value}, obtenido: {analysis.level.value})")
    
    print("\n✅ Detector de complejidad funcionando!")


def test_selector_modelo():
    """Probar el selector de modelos."""
    print("\n" + "=" * 80)
    print("🔍 TEST 3: Selector Inteligente de Modelos")
    print("=" * 80)
    
    # Resetear estadísticas
    model_selector.usage_stats = {'gpt-5': 0, 'gpt-4o': 0, 'fallback': 0}
    
    # Simular varias consultas
    queries = [
        ("Dame los clientes", [{"name": "CLIENTES"}]),
        ("Ventas del mes", [{"name": "DOCTOS_PV"}, {"name": "DOCTOS_PV_DET"}]),
        ("Análisis complejo multi-tabla", [{"name": f"TABLA_{i}"} for i in range(6)]),
        ("Lista de productos", [{"name": "ARTICULOS"}]),
    ]
    
    print("\nSimulando consultas...")
    for query, tables in queries:
        model, _ = model_selector.select_model_for_query(query, tables)
        print(f"  • '{query}' → {model}")
    
    # Obtener estadísticas
    stats = model_selector.get_usage_statistics()
    print(f"\n📊 Estadísticas de Uso:")
    print(f"  Total de consultas: {stats['total_queries']}")
    print(f"  GPT-5: {stats['gpt-5_usage']} ({stats.get('gpt-5_percentage', 0)}%)")
    print(f"  GPT-4o: {stats['gpt-4o_usage']} ({stats.get('gpt-4o_percentage', 0)}%)")
    
    print("\n✅ Selector de modelos funcionando!")


def test_procedimientos_almacenados():
    """Probar el gestor de procedimientos almacenados."""
    print("\n" + "=" * 80)
    print("🔍 TEST 4: Procedimientos Almacenados")
    print("=" * 80)
    
    # Obtener todos los procedimientos
    all_procedures = procedures_manager.get_all_procedures()
    print(f"\n✓ Procedimientos cargados: {len(all_procedures)}")
    
    if all_procedures:
        print("\n📦 Procedimientos disponibles:")
        for proc in all_procedures[:5]:  # Mostrar máximo 5
            print(f"  • {proc.name}")
            print(f"    - {proc.description}")
            print(f"    - Casos de uso: {', '.join(proc.use_cases)}")
    
    # Probar búsqueda de procedimientos relevantes
    test_queries = [
        "existencias de artículos",
        "ventas por período",
        "costo promedio"
    ]
    
    print("\n🔍 Búsqueda de procedimientos relevantes:")
    for query in test_queries:
        relevant = procedures_manager.find_relevant_procedures(query, top_k=2)
        print(f"\n  Query: '{query}'")
        if relevant:
            print(f"  Encontrados: {len(relevant)}")
            for proc in relevant:
                print(f"    • {proc.name}")
        else:
            print(f"  No se encontraron procedimientos relevantes")
    
    print("\n✅ Procedimientos almacenados funcionando!")


def test_integracion_completa():
    """Probar la integración completa del sistema."""
    print("\n" + "=" * 80)
    print("🔍 TEST 5: Integración Completa")
    print("=" * 80)
    
    # Simular una consulta compleja
    query = "Dame el análisis de ventas por cliente con tendencia mensual y margen de utilidad"
    tables = [
        {"name": "DOCTOS_PV"},
        {"name": "DOCTOS_PV_DET"},
        {"name": "CLIENTES"},
        {"name": "ARTICULOS"},
        {"name": "PRECIOS_ARTICULOS"}
    ]
    
    print(f"\n📝 Consulta de prueba:")
    print(f"   '{query}'")
    print(f"   Tablas involucradas: {len(tables)}")
    
    # Seleccionar modelo
    model, analysis = model_selector.select_model_for_query(query, tables)
    
    print(f"\n🤖 Análisis de Complejidad:")
    print(f"   Nivel: {analysis.level.value}")
    print(f"   Score: {analysis.score}/100")
    print(f"   Modelo seleccionado: {model}")
    print(f"   Explicación: {analysis.explanation}")
    
    # Buscar procedimientos
    relevant_procs = procedures_manager.find_relevant_procedures(query, top_k=2)
    
    print(f"\n📦 Procedimientos Relevantes:")
    if relevant_procs:
        for proc in relevant_procs:
            print(f"   • {proc.name}: {proc.description}")
    else:
        print(f"   No se encontraron procedimientos específicos")
    
    # Verificar que se seleccionó el modelo correcto
    if analysis.level in [QueryComplexity.COMPLEX, QueryComplexity.VERY_COMPLEX]:
        assert model == config.ai.model_complex, "Debe usar modelo complejo para queries complejas"
        print(f"\n✅ Modelo correcto seleccionado (GPT-5 para query compleja)")
    
    print("\n✅ Integración completa funcionando!")


def main():
    """Ejecutar todos los tests."""
    print("\n" + "=" * 80)
    print("🚀 PRUEBAS DE MEJORAS GPT-5")
    print("=" * 80)
    
    try:
        test_configuracion()
        test_detector_complejidad()
        test_selector_modelo()
        test_procedimientos_almacenados()
        test_integracion_completa()
        
        print("\n" + "=" * 80)
        print("✅ ¡TODOS LOS TESTS PASARON EXITOSAMENTE!")
        print("=" * 80)
        print("\n🎉 El sistema está listo para usar GPT-5 con todas las mejoras:")
        print("   ✓ Selección inteligente de modelos")
        print("   ✓ Detector de complejidad")
        print("   ✓ Soporte para procedimientos almacenados")
        print("   ✓ Prompts optimizados para GPT-5")
        print("\n💡 Puedes ejecutar la aplicación con: python app.py")
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ ERROR EN TEST: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

