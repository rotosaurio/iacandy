@echo off
echo ============================================
echo   FIREBIRD AI ASSISTANT - INTERFAZ WEB
echo ============================================
echo.
echo Activando entorno virtual Python 3.11...
call venv\Scripts\activate.bat
echo.
echo Iniciando servidor web en puerto 8050...
echo.
python app.py
pause