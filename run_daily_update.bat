@echo off
setlocal
cd /d "%~dp0"

echo [0/1] Syncing with remote...
git -C "%~dp0" pull --ff-only
if errorlevel 1 (
  echo Git pull failed. Continuing with local data.
)

echo [1/1] Pipeline running...
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py
if errorlevel 1 (
  echo Pipeline failed.
  pause
  exit /b 1
)

echo Done.
pause
endlocal
