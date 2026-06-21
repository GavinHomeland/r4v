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

# TEMPORARY: run the personality refresh once per DAY (was Sunday-only) until we confirm
# it works in the scheduled context. Revert to the Sunday check once verified.
# Gated by the flag's date so the 4-hourly task fires it at most once per calendar day (UTC).
$flagPath = "W:\r4v\data\personality_refresh_flag.json"
$lastRefreshDate = $null
if (Test-Path $flagPath) {
    try { $lastRefreshDate = ([DateTime](Get-Content $flagPath -Raw | ConvertFrom-Json).refreshed_at).ToUniversalTime().Date } catch {}
}
if ($lastRefreshDate -ne (Get-Date).ToUniversalTime().Date) {
    Write-Host "[run_check] Daily personality refresh..."
    & "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\refresh_personalities.py"
}

# Run the normal background check
& "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\cli.py" check
