$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\DanKim\anaconda3\python.exe'
$script = Join-Path $root 'scripts\run_pipeline.py'

Write-Host "[0/3] Syncing with remote..."
git -C $root checkout -- data data_bundle.js 2>$null
git -C $root pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "Git pull failed. Continuing with local data."
}

Write-Host "[1/3] Pipeline running..."
& $python $script
if ($LASTEXITCODE -ne 0) {
    Write-Host "Pipeline failed."
    exit $LASTEXITCODE
}

Write-Host "[2/3] Pushing updated data to GitHub..."
git -C $root add data/watchlist.json data/videos.json data/digest.json data_bundle.js
git -C $root diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git -C $root commit -m "chore: local daily update"
    git -C $root push
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Git push failed (may need to pull first). Data saved locally."
    }
} else {
    Write-Host "No data changes to push."
}

Write-Host "[3/3] Done."
