# PENDIENTE: Refinamiento Automático con 0 Resultados

## Problema Identificado

Actualmente, el sistema solo refina SQL cuando hay un **ERROR** (línea 1404 en ai_assistant.py):

```python
while query_result.error and retry_count < max_retries:
```

**NO refina cuando devuelve 0 resultados** (línea 916):
```python
if query_result.row_count == 0:
    return "No se encontraron resultados para esta consulta."
```

## Escenario Problema

1. Usuario: "dame la última venta"
2. Sistema genera SQL con filtros: `WHERE FECHA >= CURRENT_DATE - 90`
3. Query ejecuta SIN ERROR
4. Devuelve **0 resultados** (porque la BD tiene datos de hace 6 meses)
5. Sistema muestra: "No se encontraron resultados"
6. **NO intenta ampliar rango de fechas**

## Solución Propuesta

Implementar **refinamiento iterativo** cuando `row_count == 0`:

### Estrategia de Ampliación Progresiva

```python
# Después de línea 1448 en ai_assistant.py

# Si no hay error PERO tampoco hay resultados, intentar ampliar búsqueda
if not query_result.error and query_result.row_count == 0:
    logger.info("⚠️ [SQL_QUERY] Query exitosa pero 0 resultados. Intentando ampliar búsqueda...")

    # Detectar si usa filtro de fecha
    if 'CURRENT_DATE' in sql_query or 'DATE \'' in sql_query:
        max_date_expansion_retries = 3
        date_expansion_retry = 0

        # Estrategia de ampliación:
        # 1. 90 días → 180 días
        # 2. 180 días → 365 días
        # 3. 365 días → Sin filtro de fecha (solo para "última venta")

        while query_result.row_count == 0 and date_expansion_retry < max_date_expansion_retries:
            date_expansion_retry += 1
            logger.info(f"🔄 [ZERO_RESULTS] Intento {date_expansion_retry}: Ampliando rango de fecha...")

            # Llamar a un nuevo método: refine_sql_for_zero_results()
            expanded_sql, expansion_msg = self.sql_generator.refine_sql_for_zero_results(
                sql_query,
                user_query,
                date_expansion_retry
            )

            # Ejecutar con rango ampliado
            query_result = db.execute_query_limited(expanded_sql)

            if query_result.row_count > 0:
                sql_query = expanded_sql
                logger.info(f"✅ [ZERO_RESULTS] Encontrados {query_result.row_count} resultados ampliando búsqueda")
                # Agregar nota al usuario
                response_message += f"\n\n💡 **Nota**: {expansion_msg}"
                break
```

### Nuevo Método Necesario en SQLGenerator

```python
def refine_sql_for_zero_results(self, original_sql: str, user_query: str, retry_attempt: int) -> Tuple[str, str]:
    """
    Refinar SQL cuando devuelve 0 resultados ampliando progresivamente los filtros.

    Args:
        original_sql: SQL que devolvió 0 resultados
        user_query: Consulta original del usuario
        retry_attempt: Número de intento (1, 2, 3...)

    Returns:
        (sql_refinado, mensaje_para_usuario)
    """

    # Estrategias de ampliación según el intento
    if retry_attempt == 1:
        # Intento 1: Duplicar rango de fecha (90 → 180 días)
        expanded_sql = original_sql.replace('CURRENT_DATE - 90', 'CURRENT_DATE - 180')
        expanded_sql = expanded_sql.replace('- 90 FROM DOCTOS_PV', '- 180 FROM DOCTOS_PV')
        message = "Amplié la búsqueda a los últimos 6 meses"

    elif retry_attempt == 2:
        # Intento 2: Ampliar a 1 año
        expanded_sql = original_sql.replace('CURRENT_DATE - 90', 'CURRENT_DATE - 365')
        expanded_sql = expanded_sql.replace('CURRENT_DATE - 180', 'CURRENT_DATE - 365')
        expanded_sql = expanded_sql.replace('- 90 FROM DOCTOS_PV', '- 365 FROM DOCTOS_PV')
        expanded_sql = expanded_sql.replace('- 180 FROM DOCTOS_PV', '- 365 FROM DOCTOS_PV')
        message = "Amplié la búsqueda al último año completo"

    elif retry_attempt == 3:
        # Intento 3: Quitar filtro de fecha (solo si es consulta de "última venta")
        if 'FIRST 1' in original_sql and any(keyword in user_query.lower() for keyword in ['última', 'ultimo', 'reciente']):
            # Quitar líneas WHERE que contengan FECHA
            import re
            lines = original_sql.split('\n')
            filtered_lines = [line for line in lines if 'FECHA >=' not in line and 'MAX(FECHA)' not in line]
            expanded_sql = '\n'.join(filtered_lines)
            message = "Amplié la búsqueda a TODOS los registros históricos (sin filtro de fecha)"
        else:
            # Para otras consultas, mantener filtro de 1 año
            expanded_sql = original_sql
            message = "No se encontraron datos incluso en el último año"

    else:
        # No más intentos
        return original_sql, "No se encontraron resultados"

    return expanded_sql, message
```

## Archivos a Modificar

1. **ai_assistant.py** (línea ~1448)
   - Agregar lógica después de línea 1448 ("Consulta exitosa")
   - Detectar `if query_result.row_count == 0`
   - Intentar refinamiento con ampliación de fechas

2. **ai_assistant.py** - Clase SQLGenerator
   - Agregar método `refine_sql_for_zero_results()`
   - Implementar estrategia de ampliación progresiva

## Beneficios

✅ **Mejor experiencia de usuario**: No muestra "0 resultados" sin intentar buscar más
✅ **Adaptación automática**: Se adapta a BDs con datos antiguos
✅ **Transparencia**: Informa al usuario qué ampliación se hizo
✅ **Inteligente**: Mantiene filtros de artículos (VENTA GLOBAL), solo amplía fechas

## Consideraciones

⚠️ **No ampliar indefinidamente**: Máximo 3 intentos
⚠️ **Solo para queries simples**: No aplicar a agregaciones complejas con GROUP BY
⚠️ **Respetar intención del usuario**: Si pidió fecha específica, NO ampliar

## Ejemplo de Flujo

```
Usuario: "dame la última venta"

Intento 1: WHERE FECHA >= CURRENT_DATE - 90
→ 0 resultados

Intento 2: WHERE FECHA >= CURRENT_DATE - 180
→ 0 resultados

Intento 3: WHERE FECHA >= CURRENT_DATE - 365
→ 0 resultados

Intento 4: Sin filtro de fecha
→ ✅ 1 resultado (venta de hace 10 meses)

Usuario ve: "Encontré la última venta (amplié la búsqueda a todos los registros históricos)"
```

## Estado

❌ **NO IMPLEMENTADO** - Documentado para implementación futura

---

**Fecha**: 2025-10-15
**Prioridad**: ALTA
**Complejidad**: MEDIA
