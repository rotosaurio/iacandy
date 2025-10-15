# 🚀 Guía de Ejecución Paso a Paso

## Orden Correcto para Implementar las Mejoras de Embeddings

Sigue estos pasos **en orden** para que todo funcione correctamente.

---

## 📋 PASO 1: Verificar el Código

Asegúrate de que los cambios en `schema_manager.py` están correctos:

```bash
# Verificar sintaxis
python -c "import schema_manager; print('✓ schema_manager.py OK')"
```

**Resultado esperado:**
```
✓ schema_manager.py OK
```

**Si hay errores:** Revisa que todas las ediciones se aplicaron correctamente.

---

## 📋 PASO 2: Enriquecer Metadatos de MicroSIP (RECOMENDADO PERO OPCIONAL)

Este paso mejora los archivos JSON de metadatos con análisis real de la base de datos.

### 2.1. Ejecutar Script de Enriquecimiento

```bash
python enrich_microsip_metadata.py
```

### 2.2. Salida Esperada

```
================================================================================
ENRIQUECEDOR DE METADATOS MICROSIP
================================================================================

🚀 Iniciando enriquecimiento de metadatos MicroSIP...
📖 Cargando metadatos existentes...
  ✓ Diccionario cargado: 549 tablas
  ✓ Relaciones cargadas: 304 tablas

🔍 Analizando base de datos real...
  Procesadas 50/549 tablas...
  Procesadas 100/549 tablas...
  Procesadas 150/549 tablas...
  ...
  Procesadas 549/549 tablas...
✅ Análisis completado: 549 tablas enriquecidas

🔗 Combinando metadatos existentes con análisis de BD...
✅ Enriquecimiento completado
  - Tablas: 549
  - Categorías: 12
  - Keywords: 549
  - Relaciones: 304

💾 Guardando metadatos enriquecidos...
  ✓ Backup creado: microsip_dictionary_backup.json
  ✓ Backup creado: microsip_relationships_backup.json
  ✓ Guardado: microsip_dictionary.json
  ✓ Guardado: microsip_relationships.json

📄 Reporte guardado: enriquecimiento_reporte.txt
🎉 Enriquecimiento completado exitosamente
```

### 2.3. Verificar Resultados

```bash
# Verificar que se crearon los backups
dir microsip*backup*.json

# Verificar que se creó el reporte
type enriquecimiento_reporte.txt
```

**Archivos generados:**
- ✅ `microsip_dictionary_backup.json` (backup original)
- ✅ `microsip_relationships_backup.json` (backup original)
- ✅ `microsip_dictionary.json` (versión enriquecida)
- ✅ `microsip_relationships.json` (versión enriquecida)
- ✅ `enriquecimiento_reporte.txt` (reporte de cambios)

### 2.4. ¿Qué pasa si hay errores?

**Error común: "No se puede conectar a la BD"**
```bash
# Solución: Verificar config.py tiene la ruta correcta
python -c "from config import config; print(config.database.database_path)"
```

**Error: "Tabla no encontrada"**
- No te preocupes, el script continúa con las demás tablas
- Revisa el log para ver qué tablas fallaron

**Si el script falla completamente:**
- Los archivos originales NO se modifican hasta que el análisis termine
- Puedes ejecutarlo varias veces sin problemas

---

## 📋 PASO 3: Limpiar Caché de Embeddings Antiguos

Es **CRÍTICO** limpiar los embeddings viejos para que se regeneren con las nuevas descripciones.

### 3.1. Eliminar Caché de ChromaDB

```bash
# Windows (PowerShell)
Remove-Item -Recurse -Force data\chroma_db\*

# Windows (CMD)
rmdir /s /q data\chroma_db
mkdir data\chroma_db

# O manualmente: eliminar todo dentro de data/chroma_db/
```

### 3.2. Eliminar Caché de Schema (Opcional)

```bash
# Si existe archivo de caché
del data\schema_cache.json
```

**¿Por qué es necesario?**
- Los embeddings viejos usan las descripciones antiguas (pobres en semántica)
- Al limpiar, se regeneran con las nuevas descripciones enriquecidas
- Sin este paso, **NO verás ninguna mejora**

---

## 📋 PASO 4: Regenerar Embeddings con Nuevas Descripciones

Ahora regenera el esquema con las descripciones mejoradas.

### Opción A: Desde la Interfaz de Escritorio (RECOMENDADO)

```bash
# 1. Iniciar aplicación
python main.py

# 2. Esperar a que cargue la interfaz

# 3. En la interfaz:
#    - Ir al menú "Herramientas" (o presionar Ctrl+Shift+R)
#    - Seleccionar "Recargar Schema"
#    - O presionar el botón "Forzar Recarga de Schema"
```

**Progreso que verás:**
```
🔄 Cargando esquema completo de la base de datos...
🧠 Procesando TODAS las tablas para embeddings (549 tablas)...
📊 Iniciando generación de embeddings para 549 tablas...

🔄 [1/549] Procesando: ACCIONES_CONTACTOS_CLIENTES
  ✓ Obtenida muestra de 3 registros
✓ [1/549] ACCIONES_CONTACTOS_CLIENTES completada (0.2%)

🔄 [2/549] Procesando: ACCIONES_USUARIOS
  ✓ Obtenida muestra de 10 registros
✓ [2/549] ACCIONES_USUARIOS completada (0.4%)

...

✓ [549/549] ZONAS completada (100.0%)
✅ Procesadas 549/549 tablas para embeddings

💾 Guardando embeddings en ChromaDB...
✅ ChromaDB actualizado
✅ Esquema procesado completamente: 549 tablas totales, 345 activas, 549 con embeddings
```

**Tiempo estimado:** 3-5 minutos (depende del tamaño de tu BD)

### Opción B: Desde Script de Python

```bash
# Crear script temporal: test_regenerate.py
python -c "
from schema_manager import schema_manager
print('Regenerando embeddings...')
result = schema_manager.load_and_process_schema(force_refresh=True)
print(f'✅ Completado: {result[\"stats\"][\"total_tables\"]} tablas procesadas')
"
```

### Opción C: Desde la Web App

```bash
# 1. Iniciar app web
python app.py

# 2. Abrir http://localhost:8050

# 3. Esperar a que se complete la carga inicial
#    (La app regenera automáticamente en background)

# Ver en consola:
# "Esquema cargado y procesado completamente"
```

---

## 📋 PASO 5: Verificar que las Mejoras Funcionan

### 5.1. Revisar Logs

```bash
# Ver últimas líneas del log
tail -50 logs/firebird_ai_assistant.log

# O en Windows
Get-Content logs/firebird_ai_assistant.log -Tail 50

# O abrir directamente el archivo
notepad logs/firebird_ai_assistant.log
```

**Busca estas líneas clave:**
```
✅ Esquema procesado completamente: 549 tablas totales, 345 activas, 549 con embeddings
💾 Guardando embeddings en ChromaDB...
✅ ChromaDB actualizado
```

### 5.2. Probar Consultas de Prueba

Ejecuta desde la interfaz (desktop o web):

```
# Test 1: Consulta básica de ventas
"Dame las ventas del último mes"

# Test 2: Consulta con sinónimos
"Muestra los productos más vendidos"
"Muestra los artículos más vendidos"
"Muestra los ítems más vendidos"

# Test 3: Consulta de inventario
"¿Cuántos productos tengo en stock?"
"¿Cuántos artículos hay en existencia?"

# Test 4: Consulta de clientes
"¿Quiénes son mis mejores clientes?"
"¿Cuáles son los compradores más importantes?"
```

### 5.3. Verificar Selección de Tablas

En los logs, busca líneas como estas:

```
🔍 Buscando tablas relevantes para: "Dame las ventas del último mes"
Encontradas 3 tablas principales para: 'Dame las ventas del último mes'
Expandidas 3 tablas a 8 (incluyendo 5 relacionadas)

Tablas seleccionadas:
  1. DOCTOS_PV_DET (score: 0.89) ← ¡Score alto!
  2. DOCTOS_PV (score: 0.87)
  3. VENTAS (score: 0.82)
  4. ARTICULOS (relacionada, score: 0.67)
  5. CLIENTES (relacionada, score: 0.65)
```

**Buenas señales:**
- ✅ Scores de similaridad > 0.75 para tablas principales
- ✅ Tablas relacionadas relevantes incluidas
- ✅ No aparecen tablas de configuración/sistema sin sentido

**Malas señales:**
- ❌ Scores < 0.5 (threshold demasiado bajo)
- ❌ Tablas irrelevantes (TEMP, CONFIG, LOG, etc.)
- ❌ No encuentra ninguna tabla

### 5.4. Comparar Descripciones

```bash
# Ver descripción de una tabla específica
python -c "
from schema_manager import schema_manager
schema_manager.load_and_process_schema()
emb = schema_manager.schema_cache['table_embeddings']['DOCTOS_PV_DET']
print('Descripción:')
print(emb['description'])
"
```

**Deberías ver algo como:**
```
Descripción:
Registra transacciones de venta. Detalle de productos vendidos en cada operación |
Identificadores: ID_DOCTO, CVE_ART | Valores monetarios: IMPORTE, PRECIO |
Cantidades: UNIDADES | Fechas: FECHA |
Ejemplos: TIPO_DOCTO: "F, T" | UNIDADES: rango 1.00 a 500.00 |
Características: datos operacionales actuales | registros secuenciales |
Relaciones: vinculada a productos (ARTICULOS) |
Términos: vender, vendido, transacción, ticket, factura
```

---

## 📋 PASO 6: Ajustes Finos (OPCIONAL)

Si las mejoras no son suficientes, prueba estos ajustes:

### 6.1. Bajar Threshold de Similaridad

Edita `config.py`:

```python
# Encontrar esta línea (aprox. línea 120)
similarity_threshold: float = 0.7  # Valor por defecto

# Cambiar a:
similarity_threshold: float = 0.6  # Más permisivo
```

**Reiniciar app** después de cambiar config.

### 6.2. Aumentar Top-K de Tablas

Edita `config.py`:

```python
# Encontrar esta línea
top_k_tables: int = 5  # Valor por defecto

# Cambiar a:
top_k_tables: int = 8  # Más tablas principales
```

### 6.3. Extender Caché TTL

Si regenerar es muy lento:

```python
# config.py
cache_ttl_minutes: int = 30  # Por defecto

# Cambiar a:
cache_ttl_minutes: int = 120  # 2 horas de caché
```

---

## 📋 PASO 7: Monitoreo Continuo

### 7.1. Revisar Estadísticas

```python
# Obtener estadísticas del esquema
from schema_manager import schema_manager
stats = schema_manager.get_schema_summary()

print(f"Total tablas: {stats['total_tables']}")
print(f"Tablas activas: {stats['active_tables']}")
print(f"ChromaDB embeddings: {stats['total_tables']}")
print(f"Caché válido: {stats['cache_valid']}")
```

### 7.2. Ver Tablas Activas

```python
from schema_manager import schema_manager
schema_manager.load_and_process_schema()

activas = schema_manager.active_tables_cache[:20]
print("Top 20 tablas activas:")
for i, tabla in enumerate(activas, 1):
    print(f"  {i}. {tabla}")
```

---

## ⚠️ Troubleshooting

### Problema 1: "No se encuentran tablas para ninguna consulta"

**Solución:**
```bash
# 1. Verificar que ChromaDB tiene datos
python -c "
from schema_manager import schema_manager
stats = schema_manager.vector_store.get_collection_stats()
print(f'Total embeddings: {stats.get(\"total_tables\", 0)}')
"

# 2. Si retorna 0, regenerar:
# - Limpiar data/chroma_db/*
# - Ejecutar Paso 4 nuevamente
```

### Problema 2: "Embeddings muy lentos de generar"

**Solución:**
```python
# Limitar a solo tablas prioritarias temporalmente
# Editar schema_manager.py línea 1335:

if processed < 200 and table_info.row_count != 0:  # Solo 200 tablas
```

### Problema 3: "Scores de similaridad muy bajos"

**Solución:**
```bash
# 1. Verificar modelo de embeddings
python -c "
from schema_manager import EmbeddingGenerator
gen = EmbeddingGenerator()
gen._load_model()
print(f'Modelo: {gen.model}')
"

# 2. Verificar descripciones no están vacías
python -c "
from schema_manager import schema_manager
schema_manager.load_and_process_schema()
emb = schema_manager.schema_cache['table_embeddings']
vacias = [t for t, e in emb.items() if len(e['description']) < 50]
print(f'Tablas con descripción pobre: {len(vacias)}')
if vacias:
    print('Ejemplos:', vacias[:5])
"
```

### Problema 4: "Error al enriquecer metadatos"

**Solución:**
```bash
# Restaurar backups
copy microsip_dictionary_backup.json microsip_dictionary.json
copy microsip_relationships_backup.json microsip_relationships.json

# Reintentar con solo primeras 100 tablas para debug
# Editar enrich_microsip_metadata.py línea 65:
# for table_name, table_info in list(schema.items())[:100]:
```

---

## 🎯 Checklist Final

Marca cada paso cuando lo completes:

- [ ] **Paso 1:** Código verificado sin errores de sintaxis
- [ ] **Paso 2:** Metadatos enriquecidos (opcional pero recomendado)
  - [ ] Backups creados
  - [ ] Reporte generado
- [ ] **Paso 3:** Caché de ChromaDB limpiado
- [ ] **Paso 4:** Embeddings regenerados
  - [ ] 549 tablas procesadas
  - [ ] ChromaDB actualizado
- [ ] **Paso 5:** Verificación exitosa
  - [ ] Logs muestran éxito
  - [ ] Consultas de prueba funcionan
  - [ ] Scores > 0.7
  - [ ] Descripciones enriquecidas visibles
- [ ] **Paso 6:** Ajustes finos aplicados (si es necesario)
- [ ] **Paso 7:** Monitoreo configurado

---

## 📞 Siguiente Paso si Todo Funciona

Si completaste todos los pasos exitosamente:

1. **Prueba con consultas reales** de tu negocio
2. **Compara resultados** con el sistema anterior
3. **Ajusta thresholds** según necesites
4. **Documenta consultas problemáticas** para mejorar sinónimos

---

## 🎉 ¡Éxito!

Si ves esto en los logs:

```
✅ Esquema procesado completamente: 549 tablas totales, 345 activas, 549 con embeddings
ChromaDB retornó 5 resultados candidatos
Encontradas 5 de 5 tablas que superan threshold 0.7
✓ Tabla DOCTOS_PV_DET incluida (similaridad: 0.89)
✓ Tabla DOCTOS_PV incluida (similaridad: 0.87)
```

**¡Todo está funcionando correctamente!** 🎊

---

## 📚 Archivos de Referencia

- **Documentación completa:** `MEJORAS_EMBEDDINGS.md`
- **Script de enriquecimiento:** `enrich_microsip_metadata.py`
- **Código modificado:** `schema_manager.py`
- **Configuración:** `config.py`
- **Logs:** `logs/firebird_ai_assistant.log`
