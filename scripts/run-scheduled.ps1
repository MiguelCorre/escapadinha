# Invoked by Windows Task Scheduler: collect -> detect -> render new deals, logged per day.
# Native stderr (uv progress lines) must not be treated as a PowerShell error, so the
# command runs through cmd.exe with plain redirection instead of PowerShell's *>&1.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null
$log = Join-Path $root ("logs\run-{0:yyyy-MM-dd}.log" -f (Get-Date))
$env:PYTHONIOENCODING = "utf-8"
$env:ESCAPADINHA_HOME = $root
$env:COLUMNS = "120"   # rich tables: no wrapping in the log file

"==== $(Get-Date -Format o) ====" | Out-File -FilePath $log -Append -Encoding utf8
try {
    $uv = (Get-Command uv -ErrorAction Stop).Source
} catch {
    "uv not found on PATH: $PATH" | Out-File -FilePath $log -Append -Encoding utf8
    exit 127
}
cmd.exe /d /c "`"$uv`" run --project `"$root`" escapadinha run >> `"$log`" 2>&1"
$code = $LASTEXITCODE
"---- exit $code ----" | Out-File -FilePath $log -Append -Encoding utf8
exit $code
