@echo off
setlocal
cd /d "%~dp0"

echo [0/3] Syncing with remote...
git -C "%~dp0" checkout -- data data_bundle.js
git -C "%~dp0" pull --ff-only
if errorlevel 1 (
  echo Git pull failed. Continuing with local data.
)

echo [1/3] Pipeline running...
C:\Users\DanKim\anaconda3\python.exe .\scripts\run_pipeline.py
if errorlevel 1 (
  echo Pipeline failed.
  pause
  exit /b 1
)

echo [2/3] Pushing updated data to GitHub...
git -C "%~dp0" add data/watchlist.json data/videos.json data/digest.json data_bundle.js
git -C "%~dp0" diff --cached --quiet
if errorlevel 1 (
  git -C "%~dp0" commit -m "chore: local daily update"
  git -C "%~dp0" push
  if errorlevel 1 (
    echo Git push failed. Data saved locally only.
  )
) else (
  echo No data changes to push.
)

echo [3/3] Done.
pause
endlocal
