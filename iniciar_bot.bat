@echo off
rem Abre FutBot en el navegador (http://localhost:8501). Cierra esta ventana para apagarlo.
rem --server.address 0.0.0.0 permite abrirlo desde el celular en la misma WiFi (pide PIN fuera de esta PC).
cd /d "%~dp0"
start "" /b "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" >nul 2>&1
python -m streamlit run futbot.py --server.address 0.0.0.0 --server.port 8501 --browser.serverAddress localhost --browser.gatherUsageStats false
pause
