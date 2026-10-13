# run_check.ps1 — R4V background check, called by Windows Task Scheduler
# Runs every 4 hours: discover new videos, fetch transcripts, generate metadata.
# On Sundays: also runs weekly personality refresh (mines transcripts for fresh JT phrases).
# review.pyw will show a popup on next open if anything is new.
#
# To run manually:  powershell -ExecutionPolicy Bypass -File run_check.ps1
# To register task: python setup_task.py

Set-Location -Path "W:\r4v"

# Pull latest from remote
& git pull --ff-only 2>&1 | Out-Null

# Weekly personality refresh: once on Sunday, or on any day if the last run is 7+ days old
# (the PC slept through Sunday). Gated by the flag's timestamp so the 4-hourly task fires it
# at most once per Sunday.
$flagPath = "W:\r4v\data\personality_refresh_flag.json"
$lastRefresh = $null
if (Test-Path $flagPath) {
    try { $lastRefresh = ([DateTime](Get-Content $flagPath -Raw | ConvertFrom-Json).refreshed_at).ToLocalTime() } catch {}
}
$now = Get-Date
$ranToday = $lastRefresh -and $lastRefresh.Date -eq $now.Date
$overdue  = (-not $lastRefresh) -or (($now - $lastRefresh).TotalDays -ge 7)
if ((($now.DayOfWeek -eq 'Sunday') -and -not $ranToday) -or $overdue) {
    Write-Host "[run_check] Weekly personality refresh..."
    & "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\refresh_personalities.py"
}

# Run the normal background check
& "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\cli.py" check
