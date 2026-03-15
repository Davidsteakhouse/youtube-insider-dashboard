@echo off
setlocal
cd /d "%~dp0"

echo [1/2] Pipeline running...
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py
if errorlevel 1 (
  echo Pipeline failed.
  pause
  exit /b 1
)

echo [2/2] Sending Telegram digest...
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py --notify-telegram
if errorlevel 1 (
  echo Telegram delivery failed.
  pause
  exit /b 1
)

echo Done.
pause
endlocal
