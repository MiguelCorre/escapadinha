# Registers a per-user scheduled task running scripts/run-scheduled.ps1 at the given times.
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Times 07:30,19:30
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister
param(
    [string[]]$Times = @("08:00", "14:00", "20:00"),
    [string]$TaskName = "Escapadinha collect",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task '$TaskName'."
    return
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not on PATH; install it first (https://docs.astral.sh/uv/)."
}

$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $PSScriptRoot "run-scheduled.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $root
$triggers = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
    -Description "Escapadinha: collect flight prices, detect deals, render slides" -Force | Out-Null
Write-Output "Registered '$TaskName' at $($Times -join ', '). Logs: $root\logs\"
