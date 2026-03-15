@echo off
setlocal
cd /d "%~dp0"

start "YT Dashboard Server" cmd /k "C:\Users\DanKim\anaconda3\python.exe .\scripts\serve_dashboard.py"
timeout /t 3 /nobreak >nul
explorer.exe "http://127.0.0.1:8000"

endlocal
