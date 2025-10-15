# Firebird AI Assistant - Script de Inicio
# ===========================================

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  FIREBIRD AI ASSISTANT - INTERFAZ WEB" -ForegroundColor Yellow
Write-Host "  Version 1.0.0 - Python 3.11" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si existe el ambiente virtual
if (!(Test-Path ".\venv")) {
    Write-Host "⚠️ No se encontr\u00f3 el ambiente virtual" -ForegroundColor Red
    Write-Host "Creando ambiente virtual con Python 3.11..." -ForegroundColor Yellow
    py -3.11 -m venv venv
    Write-Host "✅ Ambiente virtual creado" -ForegroundColor Green
}

# Activar ambiente virtual
Write-Host "🔧 Activando ambiente virtual..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# Verificar Python version
$pythonVersion = python --version 2>&1
Write-Host "📦 $pythonVersion" -ForegroundColor Cyan

# Verificar dependencias
Write-Host "🔍 Verificando dependencias..." -ForegroundColor Yellow
$deps = pip list 2>&1 | Select-String "flask|firebird-driver|openai"
if ($deps.Count -lt 3) {
    Write-Host "⚠️ Faltan dependencias. Instalando..." -ForegroundColor Yellow
    pip install -r requirements.txt
    Write-Host "✅ Dependencias instaladas" -ForegroundColor Green
} else {
    Write-Host "✅ Todas las dependencias est\u00e1n instaladas" -ForegroundColor Green
}

Write-Host ""
Write-Host "🚀 Iniciando servidor web..." -ForegroundColor Green
Write-Host "🌐 URL: http://localhost:8050" -ForegroundColor Cyan
Write-Host "📁 Base de datos: C:\Microsip Datos\CANDY MART CONCENTRADORA.FDB" -ForegroundColor Cyan
Write-Host ""
Write-Host "Presiona Ctrl+C para detener el servidor" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Iniciar aplicaci\u00f3n
python app.py

# Al terminar
Write-Host ""
Write-Host "👋 Servidor detenido" -ForegroundColor Yellow
Write-Host "Presiona cualquier tecla para salir..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")