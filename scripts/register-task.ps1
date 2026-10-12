# Registers a per-user scheduled task running scripts/run-scheduled.ps1 every N hours, all day.
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1                 # every 2 h
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -EveryHours 1
#   powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister
param(
    [ValidateRange(1, 12)][int]$EveryHours = 2,
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
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $root

# Daily trigger at midnight, repeated every N hours for the whole day.
$trigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$repeat = New-ScheduledTaskTrigger -Once -At "00:00" `
    -RepetitionInterval (New-TimeSpan -Hours $EveryHours) -RepetitionDuration (New-TimeSpan -Days 1)
$trigger.Repetition = $repeat.Repetition

# StartWhenAvailable: a run missed while the PC was asleep/off starts as soon as it is back.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Escapadinha: collect flight prices, detect deals, render slides" -Force | Out-Null
Write-Output "Registered '$TaskName' every $EveryHours h. Logs: $root\logs\"
