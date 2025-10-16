# Cómo Configurar el API Key de OpenAI

## 🚨 Problema Actual

El sistema **NO puede generar consultas SQL correctamente** porque falta el API Key de OpenAI.

Cuando no hay API Key configurado:
- ❌ Los embeddings son vectores de ceros (no reales)
- ❌ El sistema RAG no puede identificar tablas relevantes
- ❌ Las consultas SQL pueden ser incorrectas o demasiado restrictivas
- ❌ Aparecen errores como: "No pude identificar tablas relevantes"

## ✅ Solución: Configurar API Key

Tienes **dos opciones** para configurar tu API Key de OpenAI:

---

## Opción 1: Variable de Entorno (Recomendado)

### Windows PowerShell:
```powershell
$env:OPENAI_API_KEY = "sk-tu-api-key-aqui"
```

### Windows CMD:
```cmd
set OPENAI_API_KEY=sk-tu-api-key-aqui
```

### Linux/Mac:
```bash
export OPENAI_API_KEY="sk-tu-api-key-aqui"
```

### Para hacerlo permanente:

**Windows:**
1. Busca "Variables de entorno" en el menú Inicio
2. Click en "Variables de entorno del sistema"
3. En "Variables de usuario", click "Nueva"
4. Nombre: `OPENAI_API_KEY`
5. Valor: `sk-tu-api-key-aqui`
6. Click OK y reinicia tu terminal

**Linux/Mac:**
Agrega al archivo `~/.bashrc` o `~/.zshrc`:
```bash
export OPENAI_API_KEY="sk-tu-api-key-aqui"
```

---

## Opción 2: Modificar config.py

Edita el archivo [config.py](config.py):

```python
@dataclass
class AIConfig:
    """Configuración de IA."""
    api_key: str = "sk-tu-api-key-aqui"  # ← Pega tu API key aquí
    model: str = "gpt-5"
    temperature: float = 0.1
    max_tokens: int = 3000
```

⚠️ **Advertencia:** NO subas este archivo a GitHub con tu API Key.

---

## 🔑 Obtener un API Key de OpenAI

Si no tienes un API Key:

1. Ve a https://platform.openai.com/
2. Crea una cuenta o inicia sesión
3. Ve a **API Keys** en el menú lateral
4. Click en **"Create new secret key"**
5. Copia el key (empieza con `sk-...`)
6. **Guárdalo en un lugar seguro** (no lo podrás ver de nuevo)

---

## 🧪 Verificar que Funciona

Después de configurar el API Key, ejecuta este comando:

```bash
python -c "from config import config; print('API Key configurado:', 'SI' if len(config.ai.api_key) > 10 else 'NO'); print('Primeros 15 caracteres:', config.ai.api_key[:15])"
```

Deberías ver:
```
API Key configurado: SI
Primeros 15 caracteres: sk-proj-abc1234...
```

---

## 🚀 Reiniciar el Sistema

Una vez configurado el API Key:

1. **Detén la aplicación** si está corriendo (Ctrl+C)
2. **Borra la base de datos vectorial anterior:**
   ```bash
   rm -rf ./data/chroma_db_large
   rm -rf ./data/chroma_db_openai
   ```
   O en Windows PowerShell:
   ```powershell
   Remove-Item -Recurse -Force ./data/chroma_db_large
   Remove-Item -Recurse -Force ./data/chroma_db_openai
   ```

3. **Reinicia la aplicación:**
   ```bash
   python main.py
   # o
   python app.py
   ```

4. **El sistema regenerará automáticamente los embeddings** con el nuevo modelo y API Key

---

## 📊 Verificar que los Embeddings se Generan Correctamente

Cuando inicies la aplicación, deberías ver en los logs:

```
Inicializando cliente OpenAI para embeddings (text-embedding-3-large)
Cliente OpenAI inicializado correctamente
Procesando TODAS las tablas para embeddings (545 tablas)...
```

**NO deberías ver:**
```
Error generando embedding: Error code: 401 - You didn't provide an API key
```

---

## ⚡ Mejora Aplicada

Con la modificación reciente en [ai_assistant.py](ai_assistant.py), ahora el sistema:

✅ **Busca la última venta QUE TENGA artículos reales** (no "VENTA GLOBAL")
✅ **Filtra PRIMERO y ordena DESPUÉS** (estrategia correcta)
✅ **Mantiene los filtros** para excluir artículos de sistema

Pero **necesitas el API Key configurado** para que funcione correctamente.

---

## 🆘 Soporte

Si tienes problemas:

1. Verifica que el API Key es válido
2. Verifica que tienes créditos en tu cuenta de OpenAI
3. Revisa los logs en `logs/firebird_ai_assistant.log`
4. Busca líneas con "Error generando embedding" o "401"

---

**Fecha:** 2025-10-15
**Autor:** Sistema de IA Firebird Assistant
