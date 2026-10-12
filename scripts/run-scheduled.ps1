# Invoked by Windows Task Scheduler: collect -> detect -> render new deals, logged per day.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null
$log = Join-Path $root ("logs\run-{0:yyyy-MM-dd}.log" -f (Get-Date))
$env:PYTHONIOENCODING = "utf-8"
$env:ESCAPADINHA_HOME = $root

"==== $(Get-Date -Format o) ====" | Out-File -FilePath $log -Append -Encoding utf8
& uv run --project $root escapadinha run *>&1 | Out-File -FilePath $log -Append -Encoding utf8
exit $LASTEXITCODE
