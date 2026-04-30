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

# Sunday: refresh JT catchphrases/quotes from recent transcripts
if ((Get-Date).DayOfWeek -eq 'Sunday') {
    Write-Host "[run_check] Sunday — running personality refresh..."
    & "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\refresh_personalities.py"
}

# Run the normal background check
& "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\cli.py" check
