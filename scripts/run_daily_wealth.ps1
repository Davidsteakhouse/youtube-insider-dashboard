$python = 'C:\Users\DanKim\anaconda3\python.exe'
$script = 'C:\Users\DanKim\Desktop\Wealth\ai project\0. youtube benchmark dashboard\scripts\run_pipeline.py'

& $python $script --notify-telegram
exit $LASTEXITCODE
