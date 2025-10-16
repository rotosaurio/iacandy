"""
Asistente de IA conversacional para consultas de base de datos.

Este módulo implementa el motor conversacional que utiliza OpenAI para
generar consultas SQL y analizar resultados de forma inteligente.
"""

import json
import time
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import dataclass

import openai
from openai import OpenAI

from config import config, StatusMessages
from database import db, QueryResult
from schema_manager import schema_manager
from utils import logger, timing_decorator, cache_manager, DataFormatter, SQLValidator
from query_complexity_analyzer import model_selector, QueryComplexity
from stored_procedures_manager import procedures_manager


def is_reasoning_model(model_name: str) -> bool:
    """
    Detecta si el modelo es un modelo de razonamiento que NO soporta temperature.
    Modelos de razonamiento: gpt-5, o1, o3, etc.
    """
    reasoning_models = ['gpt-5', 'o1', 'o3', 'o1-mini', 'o1-preview', 'o3-mini']
    return any(reasoning_model in model_name.lower() for reasoning_model in reasoning_models)


def build_api_params(model: str, messages: list, max_tokens: int, 
                     temperature: float = None, response_format: dict = None) -> dict:
    """
    Construye los parámetros para la API de OpenAI según el modelo.
    Modelos de razonamiento (GPT-5, o1, o3) NO soportan temperature ni response_format.
    """
    params = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens
    }
    
    # Solo agregar temperature si NO es modelo de razonamiento
    if not is_reasoning_model(model) and temperature is not None:
        params["temperature"] = temperature
    
    # Solo agregar response_format si NO es modelo de razonamiento
    # Los modelos de razonamiento no soportan response_format
    if response_format is not None and not is_reasoning_model(model):
        params["response_format"] = response_format
    
    return params


@dataclass
class ConversationMessage:
    """Mensaje en una conversación."""
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class AIResponse:
    """Respuesta del asistente de IA."""
    message: str
    sql_generated: Optional[str] = None
    needs_execution: bool = False
    suggested_actions: List[str] = None
    confidence_score: float = 1.0
    reasoning: Optional[str] = None
    error: Optional[str] = None
    has_data: bool = False
    data: Optional[List[Dict[str, Any]]] = None

    def __post_init__(self):
        if self.suggested_actions is None:
            self.suggested_actions = []
        if self.data is None:
            self.data = []


class SQLGenerator:
    """Generador de consultas SQL usando OpenAI."""
    
    def __init__(self):
        # Cliente OpenAI SIN timeout (espera indefinidamente)
        self.client = OpenAI(
            api_key=config.ai.api_key,
            timeout=None  # Sin timeout
        )
        self.conversation_history = []
    
    @timing_decorator("SQL Generation")
    def generate_sql(self, user_query: str, relevant_tables: List[Dict[str, Any]]) -> Tuple[str, float, str]:
        """Generar SQL a partir de una consulta de usuario."""
        try:
            logger.info("🔍 [SQL_GENERATION] Iniciando generación de SQL")
            logger.info(f"📝 [SQL_GENERATION] Consulta del usuario: {user_query}")
            logger.info(f"📋 [SQL_GENERATION] Tablas relevantes encontradas: {len(relevant_tables)}")

            # 🚀 NUEVO: Selección inteligente de modelo basada en complejidad
            logger.info("🤖 [SQL_GENERATION] Seleccionando modelo basado en complejidad...")
            selected_model, complexity_analysis = model_selector.select_model_for_query(
                user_query,
                relevant_tables
            )
            logger.info(f"🤖 [SQL_GENERATION] Modelo seleccionado: {selected_model} | Complejidad: {complexity_analysis.level.value}")

            # Preparar contexto de tablas
            logger.info("📊 [SQL_GENERATION] Construyendo contexto de tablas...")
            table_context = self._build_table_context(relevant_tables)
            logger.info(f"✅ [SQL_GENERATION] Contexto de tablas construido: {len(table_context)} caracteres")

            # 🚀 NUEVO: Buscar procedimientos almacenados relevantes
            logger.info("🔍 [SQL_GENERATION] Buscando procedimientos almacenados relevantes...")
            relevant_procedures = procedures_manager.find_relevant_procedures(user_query)
            procedures_context = procedures_manager.get_procedures_context(relevant_procedures)
            logger.info(f"✅ [SQL_GENERATION] Procedimientos encontrados: {len(relevant_procedures)}")

            # Construir prompt del sistema (mejorado para GPT-5)
            logger.info("📝 [SQL_GENERATION] Construyendo prompt del sistema...")
            system_prompt = self._build_sql_system_prompt(
                table_context,
                procedures_context,
                complexity_analysis
            )
            logger.info(f"✅ [SQL_GENERATION] Prompt del sistema construido: {len(system_prompt)} caracteres")

            # Preparar mensajes
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Genera una consulta SQL para: {user_query}"}
            ]
            logger.info("📤 [SQL_GENERATION] Mensajes preparados para envío a OpenAI")

            # Llamar a OpenAI con el modelo seleccionado
            logger.info(f"🚀 [SQL_GENERATION] Llamando a OpenAI con modelo: {selected_model}")
            api_params = build_api_params(
                model=selected_model,
                messages=messages,
                max_tokens=config.ai.max_tokens,
                temperature=config.ai.temperature,
                response_format={"type": "json_object"}
            )
            logger.info("🔧 [SQL_GENERATION] Parámetros API preparados, iniciando llamada...")
            response = self.client.chat.completions.create(**api_params)
            logger.info("✅ [SQL_GENERATION] Respuesta recibida de OpenAI")
            
            # Procesar respuesta
            response_content = response.choices[0].message.content
            
            # 🔍 DEBUG: Ver qué devuelve GPT-5
            if not response_content or not response_content.strip():
                logger.error(f"❌ GPT-5 devolvió respuesta vacía. Response completo: {response}")
                raise ValueError("GPT-5 devolvió una respuesta vacía. Intenta reformular tu pregunta.")
            
            logger.debug(f"📝 Respuesta de GPT-5 (primeros 500 chars): {response_content[:500]}")
            
            # Limpiar markdown si viene en la respuesta
            cleaned_content = response_content.strip()
            
            # Remover bloques de código markdown si existen
            if cleaned_content.startswith('```'):
                # Remover ```json o ``` al inicio y ``` al final
                cleaned_content = re.sub(r'^```(?:json)?\s*', '', cleaned_content)
                cleaned_content = re.sub(r'\s*```$', '', cleaned_content)
                cleaned_content = cleaned_content.strip()
            
            # Intentar parsear JSON
            try:
                response_data = json.loads(cleaned_content)
            except json.JSONDecodeError as e:
                # Intentar extraer JSON si está dentro de la respuesta
                logger.warning(f"⚠️ Respuesta no es JSON puro. Intentando extraer JSON...")
                json_match = re.search(r'\{[\s\S]*\}', cleaned_content)
                if json_match:
                    try:
                        response_data = json.loads(json_match.group(0))
                        logger.info("✅ JSON extraído exitosamente de la respuesta")
                    except Exception as parse_error:
                        logger.error(f"❌ No se pudo parsear JSON extraído. Error: {parse_error}. Contenido: {response_content[:1000]}")
                        raise ValueError(f"GPT-5 no devolvió JSON válido: {str(e)}\nContenido: {response_content[:500]}")
                else:
                    logger.error(f"❌ No se encontró JSON en la respuesta. Contenido: {response_content[:1000]}")
                    raise ValueError(f"GPT-5 no devolvió JSON: {response_content[:500]}")
            
            sql_query = response_data.get('sql', '')
            confidence = response_data.get('confidence', 0.5)
            reasoning = response_data.get('reasoning', '')
            needs_aggregation = response_data.get('needs_aggregation', False)
            expected_rows = response_data.get('expected_rows', 0)
            
            # Validar SQL generado
            is_valid, validation_error = SQLValidator.is_safe_query(sql_query)
            if not is_valid:
                raise ValueError(f"SQL generado no es válido: {validation_error}")
            
            # Log del SQL completo (sin truncar)
            logger.info(f"SQL generado para '{user_query}':\n{sql_query}")
            
            return sql_query, confidence, reasoning
            
        except Exception as e:
            logger.error(f"Error generando SQL para '{user_query}'", e)
            raise
    
    def _get_sample_data(self, table_name: str, columns: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        """Obtener datos de ejemplo de una tabla (con caché de 2 horas)."""
        try:
            # Construir clave de caché
            cache_key = f"sample_{table_name}_{limit}"

            # Intentar obtener del caché
            cached = cache_manager.get(cache_key)
            if cached is not None:
                return cached

            # Primeras 20 columnas para dar contexto amplio
            cols_to_select = columns[:20]
            col_list = ', '.join(cols_to_select)

            # Query simple y rápida
            query = f"SELECT FIRST {limit} {col_list} FROM {table_name}"

            result = db.execute_query_limited(query)

            if result.error or not result.preview_data:
                return []

            # Convertir a lista de diccionarios
            sample_rows = []
            for row in result.preview_data:
                row_dict = {}
                for i, col in enumerate(result.columns):
                    if i < len(row):
                        val = row[i]
                        # Formatear valores para ser compactos
                        if val is None:
                            row_dict[col] = "NULL"
                        elif isinstance(val, str) and len(val) > 50:
                            row_dict[col] = val[:47] + "..."
                        else:
                            row_dict[col] = val
                sample_rows.append(row_dict)

            # Guardar en caché por 2 horas (más tiempo para reducir queries)
            cache_manager.set(cache_key, sample_rows, ttl=7200)

            return sample_rows

        except Exception as e:
            logger.debug(f"No se pudo obtener datos de ejemplo de {table_name}: {e}")
            return []
    
    def _build_table_context(self, relevant_tables: List[Dict[str, Any]]) -> str:
        """Construir contexto AMPLIO con datos de ejemplo para base de datos compleja (545 tablas)."""
        if not relevant_tables:
            return "No se encontraron tablas relevantes."
        
        context_parts = []
        
        for table in relevant_tables:
            table_name = table['name']
            row_count = table.get('row_count', 0)
            
            # Encabezado con indicador de tamaño
            size_flag = "🔴" if row_count > 1000000 else ("🟡" if row_count > 100000 else "🟢")
            context_parts.append(f"\n{size_flag} **{table_name}** ({DataFormatter.format_number(row_count)} rows)")

            # CRÍTICO: Mostrar TODAS las columnas para tablas principales, limitado para relacionadas
            # Esto es ESENCIAL para que el modelo no use columnas inexistentes
            is_related = table.get('is_related', False)
            max_cols = 30 if is_related else 999  # Sin límite para tablas principales

            columns = table.get('columns', [])[:max_cols]

            if columns:
                # Mostrar columnas CON tipos (ayuda al modelo a entender mejor)
                col_with_types = [f"{col['name']} ({col.get('type', 'UNKNOWN')})" for col in columns]
                context_parts.append(f"   Columnas: {', '.join(col_with_types)}")

                # Si hay más columnas que no se mostraron
                if len(table.get('columns', [])) > len(columns):
                    remaining = len(table.get('columns', [])) - len(columns)
                    context_parts.append(f"   ... y {remaining} columnas más (tabla relacionada)")

                # 🚀 AMPLIADO: 5 filas de ejemplo con 10 columnas cada una
                col_names = [col['name'] for col in columns]
                sample_data = self._get_sample_data(table_name, col_names, limit=5)

                if sample_data:
                    context_parts.append("   📊 Datos de ejemplo:")
                    for i, row in enumerate(sample_data, 1):
                        # Mostrar primeras 10 columnas del ejemplo (balance info/tokens)
                        sample_cols = list(row.items())[:10]
                        sample_str = ", ".join([f"{k}={v}" for k, v in sample_cols])
                        context_parts.append(f"      [{i}] {sample_str}")

            # PRIMARY KEYS
            primary_keys = table.get('primary_keys', [])
            if primary_keys:
                context_parts.append(f"   🔑 PK: {', '.join(primary_keys)}")

            # AMPLIADO: Hasta 8 FOREIGN KEYS (crítico para JOINs complejos)
            foreign_keys = table.get('foreign_keys', [])
            if foreign_keys:
                fk_list = [f"{fk.get('column', '')}→{fk.get('referenced_table', '')}" for fk in foreign_keys[:8]]
                context_parts.append(f"   🔗 FK: {', '.join(fk_list)}")
        
        return "\n".join(context_parts)
    
    def _build_sql_system_prompt(self, table_context: str, procedures_context: str = "", complexity_analysis = None) -> str:
        """Construir prompt del sistema para generación de SQL (optimizado para GPT-5)."""

        # Determinar nivel de instrucciones basado en complejidad
        complexity_guidance = ""
        if complexity_analysis:
            if complexity_analysis.level == QueryComplexity.VERY_COMPLEX:
                complexity_guidance = """
🎯 **QUERY MUY COMPLEJA DETECTADA**
- Usa CTEs (WITH) SOLO para consultar tablas reales, NO para constantes
- Implementa WINDOW FUNCTIONS para análisis temporal
- Considera MÚLTIPLES niveles de agregación
- Optimiza con índices apropiados
- ⚠️ NO uses CTEs vacíos como WITH rango AS (SELECT valor)
"""
            elif complexity_analysis.level == QueryComplexity.COMPLEX:
                complexity_guidance = """
🎯 **QUERY COMPLEJA DETECTADA**
- Usa múltiples JOINs eficientemente
- Implementa subconsultas cuando sea necesario
- Agrega cálculos y métricas avanzadas
- ⚠️ Usa DATE '2025-02-01' para fechas, no CTEs con constantes
"""

        return f"""Eres un experto ÉLITE en bases de datos Firebird 3.0 y análisis de datos complejos usando GPT-5.
Generas consultas SQL AVANZADAS, ULTRA-OPTIMIZADAS y con CAPACIDAD MULTI-TABLA EXCEPCIONAL.

🎯 **PRIORIDAD ABSOLUTA: SIMPLICIDAD Y EFICIENCIA**

📌 **REGLAS DE ORO PARA QUERIES RÁPIDAS**:

1. **SIMPLICIDAD PRIMERO** - Usa la query MÁS SIMPLE que responda la pregunta
   - ✅ Una sola tabla si es suficiente
   - ✅ SELECT directo mejor que subqueries
   - ✅ Filtros simples mejor que JOINs innecesarios
   - ❌ NO compliques sin necesidad

2. **TABLA MÁS ESPECÍFICA** - Elige la tabla que más directamente contiene los datos
   - ✅ Para "último artículo vendido" → usa DOCTOS_PV_DET con ORDER BY + FIRST 1
   - ✅ Para "stock actual" → usa EXISTENCIAS directamente
   - ❌ NO hagas JOINs si la info está en una tabla

3. **FILTRA ANTES DE TODO** - En tablas grandes, SIEMPRE filtra primero
   - ✅ WHERE FECHA >= CURRENT_DATE - 30 (filtra primero)
   - ✅ WHERE ARTICULO_ID = 123 (usa índices)
   - ❌ NO hagas COUNT(*) sin WHERE en tablas grandes
   - ❌ NO hagas SUM() de toda la tabla sin filtros

4. **ÍNDICES SON TUS AMIGOS** - Usa columnas indexadas en WHERE y JOINs
   - 🔑 Columnas indexadas: *_ID (IDs), FECHA, ARTICULO_ID, CLIENTE_ID, FOLIO
   - ✅ WHERE ARTICULO_ID = 500 (rápido - usa índice)
   - ❌ WHERE UPPER(NOMBRE) LIKE '%ABC%' (lento - no usa índice)

5. **ORDENA AL FINAL** - ORDER BY SOLO cuando sea necesario
   - ✅ ORDER BY cuando el usuario pide "los mejores", "mayor", "último"
   - ❌ NO ordenes si solo necesitas contar o sumar

6. **LÍMITES SIEMPRE** - Usa FIRST n para queries exploratorias
   - ✅ SELECT FIRST 1 para "el último", "el más reciente"
   - ✅ SELECT FIRST 10 para "los mejores", "top productos"
   - ✅ SELECT FIRST 100 para vistas generales

⚡ **EJEMPLOS DE QUERIES SIMPLES Y RÁPIDAS**:

**Último artículo vendido (ÓPTIMO - 1 tabla, filtro por fecha, orden inverso, límite)**:
```sql
SELECT FIRST 1
    pvd.ARTICULO_ID,
    pvd.DESCRIPCION1,
    pv.FECHA,
    pvd.UNIDADES
FROM DOCTOS_PV_DET pvd
INNER JOIN DOCTOS_PV pv ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
WHERE pv.FECHA >= CURRENT_DATE - 90  -- Filtrar últimos 3 meses (más rápido)
ORDER BY pv.FECHA DESC, pv.DOCTO_PV_ID DESC
```

**Stock actual de un artículo (ÓPTIMO - 1 tabla, filtro por ID)**:
```sql
SELECT
    e.ARTICULO_ID,
    SUM(e.EXISTENCIA) AS STOCK_TOTAL
FROM EXISTENCIAS e
WHERE e.ARTICULO_ID = 500
GROUP BY e.ARTICULO_ID
```

**Ventas del mes (ÓPTIMO - filtro por fecha en tabla indexada)**:
```sql
SELECT
    COUNT(*) AS TOTAL_FACTURAS,
    SUM(pvd.IMPORTE) AS TOTAL_VENTA
FROM DOCTOS_PV pv
INNER JOIN DOCTOS_PV_DET pvd ON pv.DOCTO_PV_ID = pvd.DOCTO_PV_ID
WHERE pv.FECHA >= DATE '2025-10-01'
  AND pv.FECHA < DATE '2025-11-01'
```

❌ **ANTIPATRONES - EVITA ESTAS QUERIES LENTAS**:

**MAL - Sin filtro de fecha en tabla grande**:
```sql
SELECT FIRST 1 * FROM DOCTOS_PV_DET
ORDER BY DOCTO_PV_DET_ID DESC  -- Escanea TODA la tabla (millones)
```

**BIEN - Con filtro de fecha**:
```sql
SELECT FIRST 1 * FROM DOCTOS_PV_DET pvd
INNER JOIN DOCTOS_PV pv ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
WHERE pv.FECHA >= CURRENT_DATE - 90  -- Solo últimos 3 meses
ORDER BY pv.FECHA DESC
```

**MAL - JOINs innecesarios**:
```sql
SELECT a.NOMBRE, p.NOMBRE AS PROVEEDOR
FROM ARTICULOS a
LEFT JOIN PROVEEDORES p ON a.PROVEEDOR_ID = p.PROVEEDOR_ID
WHERE a.ARTICULO_ID = 500  -- Solo necesitas ARTICULOS
```

**BIEN - Query simple**:
```sql
SELECT NOMBRE FROM ARTICULOS WHERE ARTICULO_ID = 500
```

{complexity_guidance}

🚫 **EXCLUSIONES AUTOMÁTICAS DE ARTÍCULOS/REGISTROS**:

⚠️ **MUY IMPORTANTE - ESTRATEGIA DE FILTRADO PARA "ÚLTIMA VENTA":**

Cuando el usuario pide la "ÚLTIMA venta", "venta más reciente", o similar:
- ❌ **MAL**: Buscar el DOCTO_PV_ID más alto y luego filtrar artículos
  - Problema: Si la última venta solo tiene "VENTA GLOBAL", no habrá resultados
- ✅ **BIEN**: Buscar la última venta QUE TENGA artículos reales

**PATRÓN CORRECTO para "última venta con artículos" (QUERY SIMPLE Y RÁPIDA):**

⚠️ **FILTROS DE FECHA - REGLA CRÍTICA:**
- Si el usuario especifica fechas (ej: "febrero 2025", "último mes", "esta semana"):
  → Usa SOLO las fechas que el usuario pidió
- Si el usuario NO especifica fechas (solo dice "última venta"):
  → ESTRATEGIA INTELIGENTE para bases de datos potencialmente desactualizadas:

  **Opción A (PREFERIDA)**: Usar subconsulta para encontrar la fecha más reciente
  ```sql
  WHERE pv.FECHA >= (SELECT FIRST 1 MAX(FECHA) - 90 FROM DOCTOS_PV)
  ```

  **Opción B**: Si no sabes si la BD está actualizada, usa rango amplio
  ```sql
  WHERE pv.FECHA >= CURRENT_DATE - 365  -- Último año (más seguro)
  ```

  **Opción C**: Si estás seguro que la BD está al día
  ```sql
  WHERE pv.FECHA >= CURRENT_DATE - 90  -- Últimos 3 meses (más rápido)
  ```

  → La Opción A es MEJOR porque se adapta automáticamente a BDs desactualizadas

**Ejemplo 1: Usuario NO especifica fecha ("última venta registrada") - ÓPTIMO**
```sql
-- ✅ CORRECTO: Usa subconsulta para adaptarse a BDs desactualizadas
SELECT FIRST 1
    pv.DOCTO_PV_ID,
    pv.FECHA,
    al.NOMBRE AS ALMACEN,
    a.NOMBRE AS ARTICULO,
    pvd.UNIDADES,
    pvd.PRECIO_TOTAL_NETO
FROM DOCTOS_PV pv
INNER JOIN DOCTOS_PV_DET pvd ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
LEFT JOIN ALMACENES al ON al.ALMACEN_ID = pv.ALMACEN_ID
WHERE pv.FECHA >= (SELECT MAX(FECHA) - 90 FROM DOCTOS_PV)  -- ⚡ Se adapta a BDs antiguas
  AND pvd.UNIDADES > 0
  AND pvd.PRECIO_TOTAL_NETO > 0
  AND (a.NOMBRE IS NULL OR (
      a.NOMBRE NOT LIKE '%VENTA GLOBAL%'
      AND a.NOMBRE NOT LIKE '%CORTE%'
      AND a.NOMBRE NOT LIKE '%SISTEMA%'
  ))
ORDER BY pv.FECHA DESC, pv.DOCTO_PV_ID DESC
```
**Nota**: Esto funciona aunque la BD tenga datos de hace 1 año, porque busca "90 días antes de la fecha MÁS RECIENTE en la tabla", no 90 días antes de HOY.

**Ejemplo 2: Usuario SÍ especifica fecha ("última venta de febrero 2025")**
```sql
-- ✅ CORRECTO: Usar las fechas del usuario
SELECT FIRST 1
    pv.DOCTO_PV_ID,
    pv.FECHA,
    al.NOMBRE AS ALMACEN,
    a.NOMBRE AS ARTICULO,
    pvd.UNIDADES,
    pvd.PRECIO_TOTAL_NETO
FROM DOCTOS_PV pv
INNER JOIN DOCTOS_PV_DET pvd ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
LEFT JOIN ARTICULOS a ON a.ARTICULO_ID = pvd.ARTICULO_ID
LEFT JOIN ALMACENES al ON al.ALMACEN_ID = pv.ALMACEN_ID
WHERE pv.FECHA >= DATE '2025-02-01'      -- Fechas del usuario
  AND pv.FECHA < DATE '2025-03-01'       -- Fechas del usuario
  AND pvd.UNIDADES > 0
  AND pvd.PRECIO_TOTAL_NETO > 0
  AND (a.NOMBRE IS NULL OR (
      a.NOMBRE NOT LIKE '%VENTA GLOBAL%'
      AND a.NOMBRE NOT LIKE '%CORTE%'
      AND a.NOMBRE NOT LIKE '%SISTEMA%'
  ))
ORDER BY pv.FECHA DESC, pv.DOCTO_PV_ID DESC
```

❌ **INCORRECTO - QUERY LENTA (NO USES ESTE PATRÓN):**
```sql
-- ❌ MAL: Subconsulta con EXISTS escanea MILLONES de registros
-- Esta query puede tardar 10+ minutos
SELECT pv.* FROM DOCTOS_PV pv
WHERE EXISTS (
    SELECT 1 FROM DOCTOS_PV_DET pvd
    WHERE pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
      AND pvd.UNIDADES > 0
)
ORDER BY pv.FECHA DESC
```

**Nota:**
- ⚡ **SIEMPRE incluye filtro de fecha** en tablas grandes (DOCTOS_PV tiene 3.9 millones de registros)
- ✅ El ORDER BY va al FINAL después de filtrar
- ✅ FIRST 1 toma solo el primer resultado después de ordenar
- ❌ NUNCA uses EXISTS o subconsultas correlacionadas para "última venta"

**Para análisis de ventas y productos más vendidos:**

1. **EXCLUIR artículos de sistema/control**:
   - WHERE pvd.DESCRIPCION1 NOT LIKE '%VENTA GLOBAL%'
   - WHERE pvd.DESCRIPCION1 NOT LIKE '%CORTE%'
   - WHERE pvd.DESCRIPCION1 NOT LIKE '%SISTEMA%'
   - WHERE a.NOMBRE NOT LIKE '%GLOBAL%'

2. **EXCLUIR artículos con CVE_ART de control**:
   - WHERE ca.CODIGO NOT IN ('GLOBAL', 'CORTE', 'SISTEMA')

3. **FILTRAR por artículos reales con ventas significativas**:
   - WHERE pvd.UNIDADES > 0 (excluir transacciones vacías)
   - WHERE pvd.IMPORTE > 0 (excluir registros sin valor)

4. **Clientes especiales**:
   - Excluir 'CLIENTE MOSTRADOR' o 'PUBLICO GENERAL' en análisis de clientes específicos

**EJEMPLO - Artículo más vendido (con exclusiones)**:
```sql
SELECT FIRST 1
    pvd.ARTICULO_ID,
    pvd.DESCRIPCION1 AS ARTICULO,
    SUM(pvd.UNIDADES) AS TOTAL_VENDIDO,
    SUM(pvd.IMPORTE) AS TOTAL_IMPORTE
FROM DOCTOS_PV_DET pvd
INNER JOIN DOCTOS_PV pv ON pvd.DOCTO_PV_ID = pv.DOCTO_PV_ID
WHERE pv.FECHA >= DATE '2025-02-01'
  AND pv.FECHA < DATE '2025-03-01'
  AND pvd.UNIDADES > 0
  AND pvd.DESCRIPCION1 NOT LIKE '%VENTA GLOBAL%'
  AND pvd.DESCRIPCION1 NOT LIKE '%CORTE%'
  AND pvd.DESCRIPCION1 NOT LIKE '%SISTEMA%'
GROUP BY pvd.ARTICULO_ID, pvd.DESCRIPCION1
ORDER BY TOTAL_VENDIDO DESC
```

CONTEXTO DE TABLAS DISPONIBLES:
{table_context}

🎯 CAPACIDADES AVANZADAS REQUERIDAS:
1. **JOINS MÚLTIPLES**: Combinar 3-5+ tablas cuando sea necesario
2. **ANÁLISIS CRUZADO**: Relacionar ventas, inventario, clientes, proveedores
3. **AGREGACIONES COMPLEJAS**: SUM, COUNT, AVG con múltiples GROUP BY
4. **SUBQUERIES**: Para cálculos avanzados y filtros dinámicos
5. **WINDOW FUNCTIONS**: RANK, ROW_NUMBER cuando sea útil (Firebird 3.0+)
6. **CÁLCULOS**: Porcentajes, diferencias, ratios, tendencias

⚡ OPTIMIZACIÓN CRÍTICA - TABLAS GRANDES:
- DOCTOS_PV_DET, DOCTOS_CC_DET, DOCTOS_PV, DOCTOS_CC: Millones de registros
- EXISTENCIAS, MOVIMIENTOS_ALMACEN: Grandes volúmenes
- **REGLA DE ORO**: SIEMPRE filtrar por FECHA primero en tablas de transacciones
- Usar índices: ARTICULO_ID, CLIENTE_ID, PROVEEDOR_ID, ALMACEN_ID, FECHA

⚠️ **ADVERTENCIA CRÍTICA - VERIFICAR COLUMNAS**:
Antes de usar una columna, VERIFICA que existe en el esquema proporcionado.
- ❌ DOCTOS_PV NO tiene SERIE
- ❌ DOCTOS_VE NO tiene SERIE  
- ❌ DOCTOS_CC NO tiene SERIE
- ✅ Usan: TIPO_DOCTO + FOLIO (no SERIE)

🔗 RELACIONES COMUNES EN MicroSIP:
- ARTICULOS ↔ CLAVES_ARTICULOS (códigos alternativos)
- ARTICULOS ↔ EXISTENCIAS (inventario por almacén)
- ARTICULOS ↔ PRECIOS_ARTICULOS (listas de precios)
- ARTICULOS ↔ LINEAS_ARTICULOS (categorías)
- DOCTOS_PV ↔ DOCTOS_PV_DET (maestro-detalle ventas)
- DOCTOS_CC ↔ DOCTOS_CC_DET (maestro-detalle compras)
- DOCTOS_PV ↔ CLIENTES (ventas por cliente)
- DOCTOS_CC ↔ PROVEEDORES (compras por proveedor)
- EXISTENCIAS ↔ ALMACENES (ubicación física)

REGLAS DE FIREBIRD 3.0:
1. Sintaxis: FIRST n (no LIMIT), SKIP n (para paginación)
2. Funciones fecha: CURRENT_DATE, CURRENT_TIMESTAMP, EXTRACT(MONTH FROM fecha)
3. Concatenación: || (pipe doble)
4. NULL handling: COALESCE(campo, valor_default)
5. CAST: CAST(campo AS VARCHAR(50)), CAST(campo AS INTEGER)
6. Strings: UPPER(), LOWER(), TRIM(), SUBSTRING()

💡 QUERIES COMPLEJAS - EJEMPLOS:

**Ventas por cliente con total y cantidad:**
```sql
SELECT 
    c.CLIENTE_ID,
    c.NOMBRE AS CLIENTE,
    COUNT(DISTINCT pv.DOCTO_PV_ID) AS TOTAL_FACTURAS,
    SUM(pvd.UNIDADES) AS UNIDADES_VENDIDAS,
    SUM(pvd.IMPORTE) AS IMPORTE_TOTAL
FROM DOCTOS_PV pv
INNER JOIN DOCTOS_PV_DET pvd ON pv.DOCTO_PV_ID = pvd.DOCTO_PV_ID
INNER JOIN CLIENTES c ON pv.CLIENTE_ID = c.CLIENTE_ID
WHERE pv.FECHA >= DATE '2025-01-01'
GROUP BY c.CLIENTE_ID, c.NOMBRE
ORDER BY IMPORTE_TOTAL DESC
```

**Artículos con stock bajo y su proveedor:**
```sql
SELECT 
    a.ARTICULO_ID,
    a.NOMBRE AS ARTICULO,
    ca.CODIGO AS CODIGO_ALTERNO,
    SUM(e.EXISTENCIA) AS STOCK_TOTAL,
    a.MINIMO,
    p.NOMBRE AS PROVEEDOR
FROM ARTICULOS a
LEFT JOIN CLAVES_ARTICULOS ca ON a.ARTICULO_ID = ca.ARTICULO_ID
LEFT JOIN EXISTENCIAS e ON a.ARTICULO_ID = e.ARTICULO_ID
LEFT JOIN PROVEEDORES p ON a.PROVEEDOR_ID = p.PROVEEDOR_ID
WHERE a.ACTIVO = 1
GROUP BY a.ARTICULO_ID, a.NOMBRE, ca.CODIGO, a.MINIMO, p.NOMBRE
HAVING SUM(COALESCE(e.EXISTENCIA, 0)) < a.MINIMO
ORDER BY STOCK_TOTAL
```

**Top productos más rentables (precio vs costo):**
```sql
SELECT FIRST 10
    a.ARTICULO_ID,
    a.NOMBRE,
    pa.PRECIO,
    a.COSTO,
    (pa.PRECIO - a.COSTO) AS UTILIDAD,
    ((pa.PRECIO - a.COSTO) / NULLIF(a.COSTO, 0) * 100) AS MARGEN_PCT
FROM ARTICULOS a
INNER JOIN PRECIOS_ARTICULOS pa ON a.ARTICULO_ID = pa.ARTICULO_ID
WHERE a.ACTIVO = 1 AND a.COSTO > 0
ORDER BY MARGEN_PCT DESC
```

**Análisis de ventas por mes con crecimiento:**
```sql
WITH ventas_mes AS (
    SELECT 
        EXTRACT(YEAR FROM pv.FECHA) AS ANIO,
        EXTRACT(MONTH FROM pv.FECHA) AS MES,
        SUM(pvd.IMPORTE) AS TOTAL_VENTA
    FROM DOCTOS_PV pv
    INNER JOIN DOCTOS_PV_DET pvd ON pv.DOCTO_PV_ID = pvd.DOCTO_PV_ID
    WHERE pv.FECHA >= DATE '2024-01-01'
    GROUP BY 1, 2
)
SELECT 
    ANIO,
    MES,
    TOTAL_VENTA,
    LAG(TOTAL_VENTA) OVER (ORDER BY ANIO, MES) AS VENTA_MES_ANTERIOR
FROM ventas_mes
ORDER BY ANIO, MES
```

🎯 INSTRUCCIONES PARA QUERIES COMPLEJAS:
1. **USA MÚLTIPLES TABLAS** cuando la pregunta lo requiera
2. **RELACIONA DATOS**: Combina ventas con inventario, clientes con productos, etc.
3. **AGREGA CONTEXTO**: No solo números, incluye nombres descriptivos
4. **CALCULA MÉTRICAS**: Porcentajes, promedios, totales, diferencias
5. **FILTRA INTELIGENTEMENTE**: Usa fechas, estados activos, rangos relevantes
6. **ORDENA RESULTADOS**: Los más importantes primero

⚠️ EVITA QUERIES LENTAS:
- ❌ MAL:  SELECT * FROM DOCTOS_PV_DET (sin filtro ni límite)
- ✅ BIEN: SELECT FIRST 100 * FROM DOCTOS_PV_DET WHERE FECHA >= '2025-01-01'
- ❌ MAL:  SUM sin WHERE en tablas grandes
- ✅ BIEN: SUM con filtro de fecha y JOINs apropiados

{procedures_context}

💡 **CAPACIDADES GPT-5 AVANZADAS**:
- Análisis multi-dimensional de hasta 10+ tablas simultáneamente
- Generación de CTEs complejas con múltiples niveles
- Optimización automática de queries basada en volumen de datos
- Window Functions avanzadas para análisis temporal y ranking
- Subconsultas correlacionadas cuando sea necesario
- Cálculos financieros y estadísticos complejos

📋 **FORMATO DE RESPUESTA OBLIGATORIO** (DEBE SER JSON VÁLIDO):
```json
{{
    "sql": "consulta SQL completa y optimizada",
    "confidence": 0.9,
    "reasoning": "explicación breve de la query y tablas usadas",
    "needs_aggregation": true,
    "expected_rows": 50
}}
```

⚠️ **MUY IMPORTANTE**: 
- Tu respuesta DEBE ser ÚNICAMENTE el objeto JSON de arriba
- NO incluyas texto adicional antes o después del JSON
- NO uses markdown, NO uses comillas triples
- SOLO el JSON puro y válido

Genera consultas COMPLEJAS, COMPLETAS y EFICIENTES que respondan exactamente lo que el usuario necesita.
Aprovecha al máximo las capacidades de GPT-5 para crear queries óptimas y sofisticadas."""

    def refine_sql(self, original_sql: str, error_message: str, user_feedback: str = None) -> Tuple[str, str]:
        """Refinar SQL basado en errores o feedback usando múltiples modelos automáticamente."""
        models_to_try = [
            config.ai.model_complex,  # GPT-5 primero
            config.ai.model_fallback,  # Luego GPT-4o
            config.ai.model_simple     # Finalmente modelo simple
        ]

        last_error = None

        for model_idx, model_name in enumerate(models_to_try):
            try:
                logger.info(f"🔄 Intentando refinamiento con modelo: {model_name}")

                # 🚀 OBTENER CONTEXTO RAG DE LAS TABLAS INVOLUCRADAS
                # Extraer nombres de tablas del SQL
                table_pattern = r'\b(?:FROM|JOIN)\s+(\w+)'
                tables_in_sql = list(set(re.findall(table_pattern, original_sql.upper())))

                # Obtener información detallada de las tablas usando el método correcto
                schema_context = ""
                if tables_in_sql:
                    schema_context = "\n\n📊 **ESQUEMA DE TABLAS INVOLUCRADAS**:\n"
                    schema_context += schema_manager.get_table_context(tables_in_sql[:5])

                messages = [
                    {
                        "role": "system",
                        "content": f"""Eres un experto en debugging de SQL para Firebird 3.0 y MicroSIP.

⚠️ ERRORES COMUNES EN MICROSIP:
- La tabla DOCTOS_PV usa FECHA (NO FECHA_DOCUMENTO)
- La tabla DOCTOS_VE usa FECHA (NO FECHA_DOCUMENTO)
- DOCTOS_PV NO tiene columna SERIE (solo tiene FOLIO, TIPO_DOCTO)
- DOCTOS_VE NO tiene columna SERIE (solo tiene FOLIO, TIPO_DOCTO)
- DOCTOS_CC NO tiene columna SERIE (solo tiene FOLIO, TIPO_DOCTO)
- Las series están en otras tablas de configuración, no en los documentos
- Si necesitas serie+folio, usa TIPO_DOCTO y FOLIO
- Las columnas de fecha suelen ser FECHA, FECHA_HORA_CREACION, etc.

⚠️ ERRORES COMUNES DE FIREBIRD 3.0:
- CTEs vacíos (WITH sin FROM): Firebird necesita un FROM real o usar CAST directamente
- Si el error es "Token unknown" en un CTE, reemplaza el CTE por valores directos
- Ejemplo INCORRECTO: WITH rango AS (SELECT CAST('2025-02-01' AS DATE) AS f_ini)
- Ejemplo CORRECTO: Usa DATE '2025-02-01' directamente en el WHERE
- Los CTEs solo deben usarse cuando realmente consultan tablas, no para constantes

🔧 SINTAXIS FIREBIRD:
- Fechas literales: DATE '2025-02-01' (NO CAST('2025-02-01' AS DATE))
- Para rangos de fecha, usa directamente en WHERE: WHERE FECHA >= DATE '2025-02-01' AND FECHA < DATE '2025-03-01'
- CAST solo cuando sea absolutamente necesario

{schema_context}

Corrige errores de sintaxis, nombres de columnas incorrectos y optimiza la consulta."""
                    },
                    {
                        "role": "user",
                        "content": f"""
SQL original que falló:
{original_sql}

Error recibido:
{error_message}

{f'Feedback adicional del usuario: {user_feedback}' if user_feedback else ''}

Por favor, corrige el SQL y explica los cambios realizados.

⚠️ **RESPONDE ÚNICAMENTE CON ESTE JSON** (sin texto adicional, sin markdown):
{{
    "corrected_sql": "SQL corregido",
    "changes_made": "explicación de los cambios"
}}
"""
                    }
                ]

                # Usar modelo actual para refinamiento
                api_params = build_api_params(
                    model=model_name,
                    messages=messages,
                    max_tokens=config.ai.max_tokens,
                    temperature=config.ai.temperature,
                    response_format={"type": "json_object"}
                )
                response = self.client.chat.completions.create(**api_params)

                # Limpiar respuesta igual que en generate_sql
                response_content = response.choices[0].message.content

                if not response_content or not response_content.strip():
                    logger.error(f"❌ Refinamiento: {model_name} devolvió respuesta vacía")
                    last_error = f"Modelo {model_name} devolvió respuesta vacía"
                    continue

                logger.debug(f"📝 Respuesta refinamiento con {model_name} (primeros 500 chars): {response_content[:500]}")

                # Limpiar markdown
                cleaned_content = response_content.strip()
                if cleaned_content.startswith('```'):
                    cleaned_content = re.sub(r'^```(?:json)?\s*', '', cleaned_content)
                    cleaned_content = re.sub(r'\s*```$', '', cleaned_content)
                    cleaned_content = cleaned_content.strip()

                # Parsear JSON
                try:
                    response_data = json.loads(cleaned_content)
                except json.JSONDecodeError:
                    # Intentar extraer JSON
                    json_match = re.search(r'\{[\s\S]*\}', cleaned_content)
                    if json_match:
                        try:
                            response_data = json.loads(json_match.group(0))
                        except Exception as parse_error:
                            logger.error(f"❌ Refinamiento: No se pudo parsear JSON de {model_name}. Error: {parse_error}")
                            last_error = f"No se pudo parsear JSON de {model_name}"
                            continue
                    else:
                        logger.error(f"❌ Refinamiento: No se encontró JSON en {model_name}")
                        last_error = f"No se encontró JSON en {model_name}"
                        continue

                corrected_sql = response_data.get('corrected_sql', original_sql)
                changes_explanation = response_data.get('changes_made', 'Sin cambios específicos')

                # Validar SQL corregido
                is_valid, validation_error = SQLValidator.is_safe_query(corrected_sql)
                if not is_valid:
                    logger.warning(f"⚠️ SQL corregido por {model_name} no es válido: {validation_error}")
                    last_error = f"SQL corregido no es válido: {validation_error}"
                    continue

                logger.info(f"✅ SQL refinado exitosamente con modelo {model_name}")
                return corrected_sql, changes_explanation

            except Exception as e:
                logger.error(f"❌ Error refinando SQL con modelo {model_name}: {e}")
                last_error = f"Error con {model_name}: {str(e)}"
                continue

        # Si todos los modelos fallaron
        logger.error(f"❌ No se pudo refinar el SQL después de intentar con todos los modelos disponibles. Último error: {last_error}")
        return original_sql, f"No se pudo refinar el SQL después de intentar con múltiples modelos. Último error: {last_error}"

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
        logger.info(f"🔄 [ZERO_RESULTS] Refinando SQL para intento {retry_attempt} de ampliación de búsqueda")

        # Estrategias de ampliación según el intento
        if retry_attempt == 1:
            # Intento 1: Duplicar rango de fecha (90 → 180 días)
            expanded_sql = original_sql.replace('CURRENT_DATE - 90', 'CURRENT_DATE - 180')
            expanded_sql = expanded_sql.replace('- 90 FROM DOCTOS_PV', '- 180 FROM DOCTOS_PV')
            expanded_sql = expanded_sql.replace('DATE - 90', 'DATE - 180')
            message = "Amplié la búsqueda a los últimos 6 meses"

        elif retry_attempt == 2:
            # Intento 2: Ampliar a 1 año
            expanded_sql = original_sql.replace('CURRENT_DATE - 90', 'CURRENT_DATE - 365')
            expanded_sql = expanded_sql.replace('CURRENT_DATE - 180', 'CURRENT_DATE - 365')
            expanded_sql = expanded_sql.replace('- 90 FROM DOCTOS_PV', '- 365 FROM DOCTOS_PV')
            expanded_sql = expanded_sql.replace('- 180 FROM DOCTOS_PV', '- 365 FROM DOCTOS_PV')
            expanded_sql = expanded_sql.replace('DATE - 90', 'DATE - 365')
            expanded_sql = expanded_sql.replace('DATE - 180', 'DATE - 365')
            message = "Amplié la búsqueda al último año completo"

        elif retry_attempt == 3:
            # Intento 3: Quitar filtro de fecha (solo si es consulta de "última venta")
            if 'FIRST 1' in original_sql.upper() and any(keyword in user_query.lower() for keyword in ['última', 'ultimo', 'reciente', 'latest', 'last']):
                # Quitar líneas WHERE que contengan FECHA
                import re
                lines = original_sql.split('\n')
                filtered_lines = []
                for line in lines:
                    # Quitar líneas WHERE que contengan filtros de fecha
                    if 'WHERE' in line.upper() and ('FECHA >=' in line.upper() or 'FECHA >= CURRENT_DATE' in line.upper() or 'MAX(FECHA)' in line.upper()):
                        continue
                    filtered_lines.append(line)
                expanded_sql = '\n'.join(filtered_lines)
                message = "Amplié la búsqueda a TODOS los registros históricos (sin filtro de fecha)"
            else:
                # Para otras consultas, mantener filtro de 1 año
                expanded_sql = original_sql
                message = "No se encontraron datos incluso en el último año"

        else:
            # No más intentos
            logger.warning(f"⚠️ [ZERO_RESULTS] Máximo de intentos alcanzado ({retry_attempt})")
            return original_sql, "No se encontraron resultados después de múltiples intentos de ampliación"

        logger.info(f"✅ [ZERO_RESULTS] SQL ampliado exitosamente. Cambio: {message}")
        logger.debug(f"📋 [ZERO_RESULTS] SQL original: {original_sql[:200]}...")
        logger.debug(f"📋 [ZERO_RESULTS] SQL ampliado: {expanded_sql[:200]}...")

        return expanded_sql, message


class ResultAnalyzer:
    """Analizador de resultados de consultas SQL."""
    
    def __init__(self):
        # Cliente OpenAI SIN timeout (espera indefinidamente)
        self.client = OpenAI(
            api_key=config.ai.api_key,
            timeout=None  # Sin timeout
        )
    
    @timing_decorator("Result Analysis")
    def analyze_results(self, query_result: QueryResult, user_question: str) -> str:
        """Analizar resultados y generar insights en lenguaje natural."""
        try:
            if query_result.error:
                return f"La consulta tuvo un error: {query_result.error}"
            
            if query_result.row_count == 0:
                return "No se encontraron resultados para esta consulta, incluso después de intentar ampliar los filtros de búsqueda."
            
            # Preparar resumen de datos
            data_summary = self._prepare_data_summary(query_result)
            
            # Generar análisis con IA
            analysis = self._generate_ai_analysis(query_result.sql, data_summary, user_question)
            
            return analysis
            
        except Exception as e:
            logger.error("Error analizando resultados", e)
            return "No se pudo analizar los resultados de la consulta."
    
    def _prepare_data_summary(self, query_result: QueryResult) -> str:
        """Preparar resumen de datos para análisis."""
        summary_parts = [
            f"Consulta ejecutada: {query_result.sql}",
            f"Registros encontrados: {DataFormatter.format_number(query_result.row_count)}",
            f"Tiempo de ejecución: {DataFormatter.format_duration(query_result.execution_time)}",
            f"Columnas: {', '.join(query_result.columns)}"
        ]
        
        # Agregar muestra de datos si está disponible
        if query_result.preview_data and len(query_result.preview_data) > 0:
            summary_parts.append("\nMuestra de datos:")
            
            # Mostrar máximo 5 filas como muestra
            sample_rows = query_result.preview_data[:5]
            
            for i, row in enumerate(sample_rows, 1):
                row_data = []
                for j, value in enumerate(row):
                    if j < len(query_result.columns):
                        col_name = query_result.columns[j]
                        formatted_value = self._format_value_for_summary(value)
                        row_data.append(f"{col_name}: {formatted_value}")
                
                summary_parts.append(f"  Fila {i}: {', '.join(row_data[:4])}...")  # Máximo 4 campos por fila
        
        return "\n".join(summary_parts)
    
    def _format_value_for_summary(self, value) -> str:
        """Formatear valor para el resumen."""
        if value is None:
            return "NULL"
        elif isinstance(value, (int, float)):
            return DataFormatter.format_number(value)
        elif isinstance(value, str):
            return DataFormatter.truncate_text(value, 50)
        else:
            return DataFormatter.truncate_text(str(value), 50)
    
    def _generate_ai_analysis(self, sql: str, data_summary: str, user_question: str) -> str:
        """Generar análisis usando IA."""
        try:
            system_prompt = """Eres un analista de datos ÉLITE potenciado por GPT-5. Tu trabajo es analizar resultados de consultas SQL y generar insights profundos y accionables en español.

🎯 CAPACIDADES GPT-5 PARA ANÁLISIS:
1. **Análisis Multi-dimensional**: Identifica patrones complejos y correlaciones ocultas
2. **Insights Predictivos**: Sugiere tendencias futuras basadas en los datos
3. **Contexto de Negocio**: Traduce métricas técnicas a impacto empresarial
4. **Recomendaciones Accionables**: Proporciona pasos concretos a seguir
5. **Detección de Anomalías**: Identifica valores atípicos o datos sospechosos
6. **Análisis Comparativo**: Compara con períodos anteriores o benchmarks

INSTRUCCIONES:
1. Responde en español, de forma clara pero profunda
2. Genera insights que vayan más allá de lo obvio
3. Menciona patrones, tendencias, anomalías y oportunidades
4. Explica en términos de negocio y valor empresarial
5. Si hay muchos registros, destaca los más importantes y el por qué
6. Sugiere análisis complementarios que aporten valor adicional
7. Usa emojis apropiados para destacar puntos clave (📊 📈 📉 💰 ⚠️ 💡)"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"""
Pregunta del usuario: {user_question}

Resumen de resultados:
{data_summary}

Por favor, analiza estos resultados y proporciona insights útiles."""}
            ]
            
            # Usar modelo principal para análisis de resultados
            api_params = build_api_params(
                model=config.ai.model,
                messages=messages,
                max_tokens=1200,
                temperature=0.3
            )
            response = self.client.chat.completions.create(**api_params)
            
            analysis = response.choices[0].message.content.strip()
            
            return analysis
            
        except Exception as e:
            logger.error("Error generando análisis con IA", e)
            return "Se obtuvieron los datos solicitados, pero no se pudo generar un análisis detallado."


class ConversationManager:
    """Gestor de conversaciones con el usuario."""
    
    def __init__(self):
        self.conversations = {}
        self.current_session_id = None
    
    def start_new_conversation(self, session_id: str = None) -> str:
        """Iniciar nueva conversación."""
        if session_id is None:
            session_id = f"session_{int(time.time())}"
        
        self.conversations[session_id] = []
        self.current_session_id = session_id
        
        # Mensaje de bienvenida
        welcome_message = ConversationMessage(
            role="assistant",
            content="¡Hola! Soy tu asistente de IA para consultas de base de datos. Puedes preguntarme sobre tus datos usando lenguaje natural.",
            timestamp=datetime.now(),
            metadata={"type": "welcome"}
        )
        
        self.conversations[session_id].append(welcome_message)
        
        logger.info(f"Nueva conversación iniciada: {session_id}")
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str, metadata: Dict[str, Any] = None) -> None:
        """Agregar mensaje a la conversación."""
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
        
        self.conversations[session_id].append(message)
    
    def get_conversation_context(self, session_id: str, last_n_messages: int = 10) -> List[Dict[str, str]]:
        """Obtener contexto de conversación para IA."""
        if session_id not in self.conversations:
            return []
        
        recent_messages = self.conversations[session_id][-last_n_messages:]
        
        context = []
        for msg in recent_messages:
            if msg.role in ['user', 'assistant']:
                context.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        return context
    
    def get_conversation_summary(self, session_id: str) -> Dict[str, Any]:
        """Obtener resumen de la conversación."""
        if session_id not in self.conversations:
            return {}
        
        messages = self.conversations[session_id]
        
        return {
            "session_id": session_id,
            "message_count": len(messages),
            "start_time": messages[0].timestamp.isoformat() if messages else None,
            "last_activity": messages[-1].timestamp.isoformat() if messages else None,
            "user_queries": len([m for m in messages if m.role == "user"]),
            "sql_generated": len([m for m in messages if m.metadata.get("sql_query")])
        }


class AIAssistant:
    """Asistente principal de IA."""
    
    def __init__(self):
        self.sql_generator = SQLGenerator()
        self.result_analyzer = ResultAnalyzer()
        self.conversation_manager = ConversationManager()
        self.current_session = None
    
    def start_session(self) -> str:
        """Iniciar nueva sesión de conversación."""
        session_id = self.conversation_manager.start_new_conversation()
        self.current_session = session_id
        return session_id
    
    @timing_decorator("AI Chat Processing")
    def chat(self, message: str, session_id: str = None) -> AIResponse:
        """Procesar mensaje de chat del usuario."""
        try:
            if session_id is None:
                session_id = self.current_session or self.start_session()
            
            # Agregar mensaje del usuario
            self.conversation_manager.add_message(session_id, "user", message)
            
            # Determinar si necesita generar SQL
            needs_sql = self._needs_sql_generation(message)
            
            if needs_sql:
                return self._handle_sql_query(message, session_id)
            else:
                return self._handle_general_chat(message, session_id)
        
        except Exception as e:
            logger.error(f"Error procesando chat: {message}", e)
            return AIResponse(
                message="Lo siento, ocurrió un error procesando tu mensaje. ¿Puedes intentar reformularlo?",
                error=str(e)
            )
    
    def _needs_sql_generation(self, message: str) -> bool:
        """Determinar si el mensaje requiere generar SQL."""
        sql_indicators = [
            # ============= VERBOS DE CONSULTA =============
            'dame', 'dime', 'muestra', 'muestrame', 'muéstrame', 'enseña', 'enseñame',
            'consulta', 'busca', 'encuentra', 'obten', 'obtén', 'obtener',
            'lista', 'listar', 'enlista', 'ver', 'visualiza', 'visualizar',
            'mostrar', 'traer', 'trae', 'saca', 'sacar', 'extraer', 'extrae',
            'buscar', 'necesito', 'quiero', 'requiero', 'selecciona', 'filtrar',
            'recuperar', 'recupera', 'consigue', 'conseguir', 'proporciona',
            'devolverme', 'devolver', 'presentar', 'presenta', 'exhibir',
            
            # ============= PREGUNTAS (con y sin acentos) =============
            'cuanto', 'cuánto', 'cuantos', 'cuántos', 'cuanta', 'cuánta', 'cuantas', 'cuántas',
            'cuando', 'cuándo', 'cual', 'cuál', 'cuales', 'cuáles',
            'que', 'qué', 'quien', 'quién', 'quienes', 'quiénes',
            'donde', 'dónde', 'adonde', 'adónde', 'como', 'cómo',
            'por que', 'por qué', 'porque', 'para que', 'para qué',
            
            # ============= INTERROGATIVOS Y EXISTENCIA =============
            'hay', 'existe', 'existen', 'tienen', 'tengo', 'tiene', 'tenemos',
            'contiene', 'incluye', 'posee', 'cuenta con', 'dispone', 'disponible',
            'se encuentra', 'encuentra', 'esta', 'está', 'estan', 'están',
            
            # ============= AGREGACIONES Y CÁLCULOS =============
            'total', 'totales', 'suma', 'sumar', 'sumatorio',
            'promedio', 'media', 'average', 'maximo', 'máximo', 'max',
            'minimo', 'mínimo', 'min', 'ultimo', 'último', 'primero',
            'cantidad', 'cantidades', 'conteo', 'contar', 'count', 'numero', 'número',
            'porcentaje', 'porciento', 'ratio', 'proporcion', 'proporción',
            'acumulado', 'agregado', 'consolidado', 'sumatoria',
            
            # ============= ANÁLISIS Y COMPARACIÓN =============
            'mayor', 'mayores', 'menor', 'menores', 'mas', 'más',
            'menos', 'mejor', 'mejores', 'peor', 'peores',
            'igual', 'diferente', 'distinto', 'similar', 'parecido',
            'comparar', 'comparación', 'comparativo', 'versus', 'vs',
            'entre', 'rango', 'desde', 'hasta', 'durante',
            'antes', 'despues', 'después', 'anterior', 'posterior',
            
            # ============= TIEMPO Y FECHAS =============
            'hoy', 'ayer', 'mañana', 'semana', 'mes', 'año', 'dia', 'día',
            'actual', 'actualmente', 'ahora', 'reciente', 'recientes',
            'historico', 'histórico', 'anterior', 'pasado', 'futuro',
            'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
            'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
            'trimestre', 'bimestre', 'semestre', 'quincenal', 'mensual', 'anual',
            
            # ============= ESTADOS Y CONDICIONES =============
            'activo', 'activos', 'activa', 'activas', 'vigente', 'vigentes',
            'inactivo', 'inactivos', 'inactiva', 'inactivas',
            'pendiente', 'pendientes', 'procesado', 'procesados',
            'cancelado', 'cancelados', 'eliminado', 'eliminados',
            'completo', 'completos', 'incompleto', 'incompletos',
            'abierto', 'abiertos', 'cerrado', 'cerrados',
            'pagado', 'pagados', 'cobrado', 'cobrados', 'sin pagar', 'por cobrar',
            'disponible', 'disponibles', 'agotado', 'agotados',
            'nuevo', 'nuevos', 'usado', 'usados',
            
            # ============= TÉRMINOS DE NEGOCIO - MicroSIP =============
            # Ventas
            'venta', 'ventas', 'vender', 'vendido', 'vendidos',
            'factura', 'facturas', 'facturado', 'facturacion', 'facturación',
            'pedido', 'pedidos', 'orden', 'ordenes', 'órdenes',
            'cotizacion', 'cotizaciones', 'cotización', 'cotizar',
            'remision', 'remisiones', 'remisión',
            'devolucion', 'devoluciones', 'devolución', 'devolver',
            'nota', 'notas', 'credito', 'crédito', 'debito', 'débito',
            
            # Clientes
            'cliente', 'clientes', 'comprador', 'compradores',
            'consumidor', 'consumidores', 'cuenta', 'cuentas',
            'contacto', 'contactos', 'direccion', 'dirección',
            'zona', 'zonas', 'ruta', 'rutas', 'vendedor', 'vendedores',
            
            # Productos/Artículos
            'producto', 'productos', 'articulo', 'articulos', 'artículo', 'artículos',
            'item', 'items', 'mercancia', 'mercancía', 'sku',
            'inventario', 'existencia', 'existencias', 'stock',
            'almacen', 'almacenes', 'almacén', 'bodega', 'bodegas',
            'codigo', 'códigos', 'código', 'clave', 'claves',
            'linea', 'lineas', 'línea', 'líneas', 'categoria', 'categoría',
            'familia', 'familias', 'grupo', 'grupos', 'marca', 'marcas',
            'unidad', 'unidades', 'presentacion', 'presentación',
            
            # Precios y Costos
            'precio', 'precios', 'costo', 'costos', 'importe', 'importes',
            'monto', 'montos', 'valor', 'valores', 'subtotal',
            'iva', 'impuesto', 'impuestos', 'descuento', 'descuentos',
            'cargo', 'cargos', 'comision', 'comisión', 'ganancia', 'utilidad',
            'margen', 'margenes', 'márgenes',
            
            # Compras y Proveedores
            'compra', 'compras', 'comprar', 'adquisicion', 'adquisición',
            'proveedor', 'proveedores', 'supplier', 'entrada', 'entradas',
            'recepcion', 'recepción', 'orden compra', 'requisicion', 'requisición',
            
            # Finanzas
            'pago', 'pagos', 'cobro', 'cobros', 'cobranza',
            'saldo', 'saldos', 'balance', 'abono', 'abonos',
            'cheque', 'cheques', 'transferencia', 'transferencias',
            'efectivo', 'tarjeta', 'banco', 'bancos', 'bancario',
            'poliza', 'póliza', 'polizas', 'pólizas', 'movimiento', 'movimientos',
            'ingreso', 'ingresos', 'egreso', 'egresos', 'gasto', 'gastos',
            
            # Documentos y Reportes
            'reporte', 'reportes', 'informe', 'informes',
            'documento', 'documentos', 'folio', 'folios',
            'serie', 'series', 'numero', 'número', 'registro', 'registros',
            'listado', 'listados', 'relacion', 'relación', 'catalogo', 'catálogo',
            
            # Producción e Inventario
            'movimiento', 'movimientos', 'traspaso', 'traspasos',
            'entrada', 'entradas', 'salida', 'salidas',
            'ajuste', 'ajustes', 'inventario fisico', 'conteo',
            'lote', 'lotes', 'serial', 'serie', 'caducidad',
            
            # Empleados y RH
            'empleado', 'empleados', 'trabajador', 'trabajadores',
            'nomina', 'nómina', 'sueldo', 'sueldos', 'salario', 'salarios',
            'departamento', 'departamentos', 'puesto', 'puestos',
            
            # Configuración
            'usuario', 'usuarios', 'permiso', 'permisos',
            'parametro', 'parámetro', 'parametros', 'parámetros',
            'configuracion', 'configuración', 'sucursal', 'sucursales',
            'empresa', 'empresas',
            
            # ============= TÉRMINOS DE ANÁLISIS =============
            'analisis', 'análisis', 'estadistica', 'estadística',
            'tendencia', 'comportamiento', 'historico', 'histórico',
            'proyeccion', 'proyección', 'forecast', 'prediccion', 'predicción',
            'dashboard', 'kpi', 'indicador', 'indicadores', 'metrica', 'métrica',
            'top', 'ranking', 'clasificacion', 'clasificación',
            
            # ============= ACCIONES Y VERBOS GENERALES =============
            'listar', 'enumerar', 'detallar', 'especificar',
            'revisar', 'verificar', 'validar', 'comprobar', 'checar',
            'identificar', 'localizar', 'ubicar', 'detectar',
            'calcular', 'computar', 'determinar', 'evaluar',
            'analizar', 'examinar', 'investigar', 'explorar',
            'generar', 'crear', 'producir', 'elaborar',
            'exportar', 'descargar', 'imprimir',
        ]
        
        message_lower = message.lower()
        return any(indicator in message_lower for indicator in sql_indicators)
    
    def _filter_edge_cases(self, query_result: QueryResult, query_context: str) -> QueryResult:
        """Filtrar registros sospechosos (edge cases) de los resultados."""
        if not query_result.data or not query_result.columns:
            return query_result

        filtered_data = []
        excluded_count = 0

        for row in query_result.data:
            should_include = True

            # Buscar columnas de texto (DESCRIPCION, NOMBRE, ARTICULO, etc.)
            for col_idx, col_name in enumerate(query_result.columns):
                if col_idx >= len(row):
                    continue

                value = str(row[col_idx]).upper() if row[col_idx] else ""

                # Detectar patrones de sistema en nombres/descripciones
                if any(keyword in col_name.upper() for keyword in ['DESCRIPCION', 'NOMBRE', 'ARTICULO', 'CLIENTE']):
                    excluded_patterns = config.edge_case.excluded_article_patterns[:]
                    excluded_patterns.extend(['INTERNO', 'AJUSTE'])

                    for pattern in excluded_patterns:
                        if pattern.startswith('%') and pattern.endswith('%'):
                            # Pattern like '%VENTA GLOBAL%'
                            inner_pattern = pattern[1:-1]
                            if inner_pattern in value:
                                should_include = False
                                excluded_count += 1
                                break
                        elif pattern in value:
                            should_include = False
                            excluded_count += 1
                            break

                if not should_include:
                    break

            if should_include:
                filtered_data.append(row)

        # Log if exclusions were applied
        if excluded_count > 0:
            logger.info(f"🔍 Filtro de edge cases aplicado: {excluded_count} registros excluidos de {len(query_result.data)} totales")

        # Actualizar resultado
        filtered_result = QueryResult(
            columns=query_result.columns,
            data=filtered_data,
            row_count=len(filtered_data),
            execution_time=query_result.execution_time,
            error=query_result.error,
            has_more_data=query_result.has_more_data,
            preview_data=filtered_data[:query_result.row_count] if query_result.preview_data else filtered_data
        )

        return filtered_result

    def _handle_sql_query(self, user_query: str, session_id: str) -> AIResponse:
        """Manejar consulta que requiere SQL."""
        try:
            logger.info("🔍 [SQL_QUERY] Iniciando procesamiento de consulta SQL")
            logger.info(f"📝 [SQL_QUERY] Consulta del usuario: {user_query}")

            # Buscar tablas relevantes usando RAG
            logger.info("🔍 [SQL_QUERY] Buscando tablas relevantes usando RAG...")
            relevant_tables = schema_manager.find_relevant_tables(user_query)
            logger.info(f"✅ [SQL_QUERY] Tablas relevantes encontradas: {len(relevant_tables)} tablas")

            if not relevant_tables:
                logger.warning("❌ [SQL_QUERY] No se encontraron tablas relevantes")
                return AIResponse(
                    message="No pude identificar tablas relevantes para tu consulta. ¿Puedes ser más específico sobre qué datos necesitas?",
                    suggested_actions=[
                        "Menciona términos específicos como 'ventas', 'clientes', 'productos'",
                        "Especifica el período de tiempo que te interesa",
                        "Indica qué tipo de análisis necesitas"
                    ]
                )

            # Generar SQL
            logger.info("🤖 [SQL_QUERY] Generando SQL con IA...")
            try:
                sql_query, confidence, reasoning = self.sql_generator.generate_sql(user_query, relevant_tables)
                logger.info("✅ [SQL_QUERY] SQL generado exitosamente")
                logger.info(f"📊 [SQL_QUERY] Confianza: {confidence}")
                logger.info(f"💭 [SQL_QUERY] Razonamiento: {reasoning}")
                logger.info(f"📋 [SQL_QUERY] SQL generado: {sql_query}")
            except Exception as e:
                logger.error(f"❌ [SQL_QUERY] Error generando SQL: {e}")
                return AIResponse(
                    message=f"Tuve problemas generando la consulta SQL: {str(e)}. ¿Puedes reformular tu pregunta?",
                    error=str(e)
                )
            
            # Ejecutar consulta con advertencia si tarda mucho
            import time
            logger.info("🗃️ [SQL_QUERY] Ejecutando consulta en base de datos...")
            start_time = time.time()
            query_result = db.execute_query_limited(sql_query)
            execution_time = time.time() - start_time
            logger.info(f"✅ [SQL_QUERY] Consulta ejecutada en {execution_time:.2f} segundos")
            logger.info(f"📈 [SQL_QUERY] Resultado: {query_result.row_count} filas, error: {'Sí' if query_result.error else 'No'}")

            # Aplicar filtros de edge cases si está habilitado (solo si NO hay error)
            if config.edge_case.enable_post_sql_filtering and not query_result.error and hasattr(query_result, 'data') and query_result.data:
                logger.info("🔍 [SQL_QUERY] Aplicando filtros de casos especiales...")
                query_result = self._filter_edge_cases(query_result, user_query)
                logger.info("✅ [SQL_QUERY] Filtros aplicados")

            # Log si la query tardó mucho
            if execution_time > 10:
                logger.warning(f"⚠️ Query lenta detectada ({execution_time:.2f}s): {sql_query[:200]}")

            # 🔄 Si hay error, intentar refinamiento hasta 5 veces
            max_retries = 5
            retry_count = 0

            while query_result.error and retry_count < max_retries:
                retry_count += 1
                logger.info(f"🔄 [SQL_QUERY] Intento {retry_count}/{max_retries} de refinamiento SQL...")
                logger.info(f"❌ [SQL_QUERY] Error actual: {query_result.error}")

                try:
                    logger.info("🔧 [SQL_QUERY] Iniciando refinamiento de SQL...")
                    refined_sql, changes = self.sql_generator.refine_sql(sql_query, query_result.error)
                    logger.info(f"💡 [SQL_QUERY] Cambios aplicados (intento {retry_count}): {changes}")
                    logger.info(f"📋 [SQL_QUERY] SQL refinado: {refined_sql}")

                    # Ejecutar SQL refinado
                    logger.info("🗃️ [SQL_QUERY] Ejecutando SQL refinado...")
                    query_result = db.execute_query_limited(refined_sql)

                    if not query_result.error:
                        # ✅ Éxito!
                        sql_query = refined_sql
                        logger.info(f"✅ [SQL_QUERY] SQL refinado exitosamente después de {retry_count} intento(s)")
                        break
                    else:
                        # Actualizar SQL para el próximo intento
                        sql_query = refined_sql
                        logger.warning(f"⚠️ [SQL_QUERY] Intento {retry_count} falló. Error: {query_result.error[:100]}")

                except Exception as e:
                    logger.error(f"❌ [SQL_QUERY] Error en intento {retry_count} de refinamiento: {e}")
                    # Continuar al siguiente intento
                    continue
            
            # Si después de todos los intentos sigue con error
            if query_result.error:
                logger.error(f"❌ [SQL_QUERY] Todos los intentos de refinamiento fallaron después de {retry_count} intentos")
                logger.error(f"❌ [SQL_QUERY] Error final: {query_result.error}")
                logger.error(f"❌ [SQL_QUERY] SQL final que falló: {sql_query}")
                error_msg = f"No pude ejecutar la consulta después de {retry_count} intentos de corrección.\n\n❌ **Último error:** {query_result.error}\n\n🔍 **Último SQL intentado:**\n```sql\n{sql_query}\n```\n\n💡 **Sugerencia:** Intenta reformular tu pregunta con más detalles o de forma más simple."
                return AIResponse(
                    message=error_msg,
                    sql_generated=sql_query,
                    error=query_result.error
                )

            # ✅ Consulta exitosa - continuar con análisis
            logger.info("✅ [SQL_QUERY] Consulta ejecutada exitosamente, iniciando análisis de resultados...")
            logger.info(f"📊 [SQL_QUERY] Datos obtenidos: {query_result.row_count} filas")

            # 🔄 Si no hay resultados, intentar refinamiento hasta 3 veces
            max_date_expansion_retries = 3
            date_expansion_retry = 0
            original_user_query = user_query  # Guardar consulta original para refinamiento

            while not query_result.error and query_result.row_count == 0 and date_expansion_retry < max_date_expansion_retries:
                date_expansion_retry += 1
                logger.info(f"🔄 [ZERO_RESULTS] Intento {date_expansion_retry}/{max_date_expansion_retries} de ampliación de búsqueda...")

                try:
                    # Llamar al método de refinamiento para cero resultados
                    expanded_sql, expansion_msg = self.sql_generator.refine_sql_for_zero_results(
                        sql_query,
                        original_user_query,
                        date_expansion_retry
                    )

                    if expanded_sql != sql_query:
                        logger.info(f"📋 [ZERO_RESULTS] SQL ampliado: {expanded_sql}")
                        logger.info("🗃️ [ZERO_RESULTS] Ejecutando SQL ampliado...")

                        # Ejecutar con rango ampliado
                        expanded_query_result = db.execute_query_limited(expanded_sql)

                        if expanded_query_result.row_count > 0:
                            # ✅ Éxito! Usar resultados ampliados
                            query_result = expanded_query_result
                            sql_query = expanded_sql
                            logger.info(f"✅ [ZERO_RESULTS] Encontrados {query_result.row_count} resultados ampliando búsqueda (intento {date_expansion_retry})")
                            # Agregar nota al usuario sobre la ampliación realizada
                            expansion_note = f"\n\n💡 **Nota**: {expansion_msg}"
                            break
                        else:
                            logger.warning(f"⚠️ [ZERO_RESULTS] Intento {date_expansion_retry} no encontró resultados")
                    else:
                        logger.info(f"ℹ️ [ZERO_RESULTS] No se pudo ampliar más la búsqueda en intento {date_expansion_retry}")
                        break

                except Exception as e:
                    logger.error(f"❌ [ZERO_RESULTS] Error en intento {date_expansion_retry} de ampliación: {e}")
                    break

            # Analizar resultados
            logger.info("🧠 [SQL_QUERY] Analizando resultados con IA...")
            analysis = self.result_analyzer.analyze_results(query_result, user_query)
            logger.info("✅ [SQL_QUERY] Análisis completado")

            # Preparar respuesta
            response_message = analysis
            logger.info("📝 [SQL_QUERY] Preparando respuesta final...")

            # Agregar nota de expansión si se realizó
            if 'expansion_note' in locals():
                response_message += expansion_note

            # Advertencia si la query tardó mucho
            if execution_time > 10:
                response_message += f"\n\n⚠️ **Advertencia**: Esta consulta tardó {execution_time:.1f} segundos. "
                response_message += "Considera agregar filtros de fecha más específicos para mejorar el rendimiento."
            elif execution_time > 5:
                response_message += f"\n\n⏱️ Tiempo de ejecución: {execution_time:.1f}s"
            
            # Agregar SQL generado al final del mensaje para que el usuario pueda verlo y probarlo
            response_message += f"\n\n🔍 **Consulta SQL generada:**\n```sql\n{sql_query}\n```"

            if query_result.has_more_data:
                logger.info(f"📋 [SQL_QUERY] Hay más datos disponibles: {query_result.has_more_data}")
                response_message += f"\n\n📊 Mostrando {query_result.row_count:,} de más registros. "
                response_message += "¿Te gustaría exportar todos los resultados a Excel?"

            # Agregar sugerencias inteligentes
            logger.info("💡 [SQL_QUERY] Generando sugerencias de seguimiento...")
            suggested_actions = self._generate_follow_up_suggestions(user_query, query_result, relevant_tables)
            logger.info(f"✅ [SQL_QUERY] Sugerencias generadas: {len(suggested_actions)} sugerencias")

            # Guardar en conversación
            logger.info("💾 [SQL_QUERY] Guardando conversación...")
            self.conversation_manager.add_message(
                session_id,
                "assistant",
                response_message,
                metadata={
                    "sql_query": sql_query,
                    "row_count": query_result.row_count,
                    "execution_time": query_result.execution_time,
                    "tables_used": [t['name'] for t in relevant_tables]
                }
            )
            logger.info("✅ [SQL_QUERY] Respuesta completa preparada")

            # Convertir resultados a formato dict
            data_rows = []
            if query_result.preview_data and len(query_result.preview_data) > 0:
                for row in query_result.preview_data:
                    row_dict = {}
                    for i, col_name in enumerate(query_result.columns):
                        if i < len(row):
                            row_dict[col_name] = row[i]
                    data_rows.append(row_dict)

            return AIResponse(
                message=response_message,
                sql_generated=sql_query,
                needs_execution=False,  # Ya ejecutado
                suggested_actions=suggested_actions,
                confidence_score=confidence,
                reasoning=reasoning,
                has_data=query_result.row_count > 0,
                data=data_rows
            )

        except Exception as e:
            logger.error(f"Error manejando consulta SQL: {user_query}", e)
            return AIResponse(
                message="Ocurrió un error procesando tu consulta. ¿Puedes intentar con una pregunta más específica?",
                error=str(e)
            )

    def _handle_general_chat(self, message: str, session_id: str) -> AIResponse:
        """Manejar chat general (sin SQL)."""
        try:
            # Obtener contexto de conversación
            context = self.conversation_manager.get_conversation_context(session_id)

            # Responder usando IA
            client = OpenAI(
                api_key=config.ai.api_key,
                timeout=None  # Sin timeout
            )

            system_prompt = """Eres un asistente especializado en bases de datos y análisis de datos. 
Ayudas a usuarios a entender y consultar sus datos empresariales.
Responde de forma amigable y profesional en español.
Si el usuario pregunta sobre capacidades, explica que puedes ayudar con consultas de datos usando lenguaje natural."""

            messages = [
                {"role": "system", "content": system_prompt}
            ] + context + [
                {"role": "user", "content": message}
            ]

            api_params = build_api_params(
                model=config.ai.model,
                messages=messages,
                max_tokens=500,
                temperature=0.7
            )
            response = client.chat.completions.create(**api_params)

            ai_response = response.choices[0].message.content.strip()

            # Agregar sugerencias útiles
            suggestions = [
                "Pregúntame sobre ventas, clientes o productos específicos",
                "Puedo generar reportes y análisis de tus datos",
                "Intenta preguntas como: 'Dame las ventas del último mes'"
            ]

            self.conversation_manager.add_message(session_id, "assistant", ai_response)

            return AIResponse(
                message=ai_response,
                suggested_actions=suggestions,
                confidence_score=0.8
            )

        except Exception as e:
            logger.error(f"Error en chat general: {message}", e)
            return AIResponse(
                message="Estoy aquí para ayudarte con consultas sobre tus datos. ¿Qué te gustaría saber?",
                error=str(e)
            )

    def _generate_follow_up_suggestions(self, original_query: str, query_result: QueryResult, 
                                      relevant_tables: List[Dict[str, Any]]) -> List[str]:
        """Generar sugerencias de seguimiento inteligentes."""
        suggestions = []

        # Sugerencias basadas en los resultados
        if query_result.row_count > 1000:
            suggestions.append("¿Quieres que filtre por un período específico?")
            suggestions.append("¿Te interesa un resumen agrupado de estos datos?")

        if query_result.row_count == 0:
            suggestions.append("¿Quieres ampliar el rango de búsqueda?")
            suggestions.append("¿Te interesa verificar datos relacionados?")

        # Sugerencias basadas en tablas relacionadas
        for table in relevant_tables[:2]:  # Solo primeras 2 tablas
            relationships = table.get('relationships', {})

            for related_table in relationships.get('references', [])[:2]:
                suggestions.append(f"También puedo analizar datos de {related_table}")

        # Sugerencias estándar de análisis
        if 'venta' in original_query.lower():
            suggestions.extend([
                "¿Quieres ver el análisis por cliente o producto?",
                "¿Te interesa la comparación con períodos anteriores?"
            ])

        elif 'cliente' in original_query.lower():
            suggestions.extend([
                "¿Quieres ver el historial de compras?",
                "¿Te interesa el análisis de comportamiento?"
            ])

        # Máximo 3 sugerencias
        return suggestions[:3]

    def get_session_summary(self, session_id: str = None) -> Dict[str, Any]:
        """Obtener resumen de la sesión actual."""
        if session_id is None:
            session_id = self.current_session

        if session_id is None:
            return {"error": "No hay sesión activa"}

        return self.conversation_manager.get_conversation_summary(session_id)


# Instancia global del asistente
ai_assistant = AIAssistant()
