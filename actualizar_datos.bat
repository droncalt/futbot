@echo off
rem Descarga resultados y cuotas nuevas, re-ajusta los modelos y liquida las boletas registradas.
cd /d "%~dp0"
python -P bot.py actualizar
pause
