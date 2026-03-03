# run_check.ps1 — R4V background check, called by Windows Task Scheduler
# Runs every 4 hours: discover new videos, fetch transcripts, generate metadata.
# review.pyw will show a popup on next open if anything is new.
#
# To run manually:  powershell -ExecutionPolicy Bypass -File run_check.ps1
# To register task: python setup_task.py

Set-Location -Path "W:\r4v"
& "W:\r4v\.venv\Scripts\python.exe" "W:\r4v\cli.py" check
