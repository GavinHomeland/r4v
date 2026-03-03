"""setup_task.py — Register the R4V YouTube background check as a Windows Scheduled Task.

Run once:
    python setup_task.py

What it creates:
    Task name:  R4V YouTube Check
    Schedule:   Every 4 hours (240 minutes), continuously
    Action:     run_check.ps1  →  python cli.py check
    Behaviour:  No console window. Silently skips if run < 3h since last check.

Useful schtasks commands after setup:
    Run now:   schtasks /Run /TN "R4V YouTube Check"
    Status:    schtasks /Query /TN "R4V YouTube Check" /V /FO LIST
    Remove:    schtasks /Delete /TN "R4V YouTube Check" /F
"""

import subprocess
import sys
from pathlib import Path

TASK_NAME        = "R4V YouTube Check"
INTERVAL_MINUTES = 240   # 4 hours — change to 360 for 6 hours
PS_SCRIPT        = Path(__file__).parent / "run_check.ps1"

action = (
    f'powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass '
    f'-File "{PS_SCRIPT}"'
)

cmd = [
    "schtasks", "/Create",
    "/TN",  TASK_NAME,
    "/TR",  action,
    "/SC",  "MINUTE",
    "/MO",  str(INTERVAL_MINUTES),
    "/F",                   # Overwrite if the task already exists
    "/RL",  "LIMITED",      # Run with current user's normal privileges
]

print(f"Registering Windows Scheduled Task")
print(f"  Name:     {TASK_NAME}")
print(f"  Script:   {PS_SCRIPT}")
print(f"  Interval: every {INTERVAL_MINUTES // 60} hours")
print()

try:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("✓ Task registered successfully.")
        print()
        print("Useful commands:")
        print(f'  Run now: schtasks /Run /TN "{TASK_NAME}"')
        print(f'  Status:  schtasks /Query /TN "{TASK_NAME}" /V /FO LIST')
        print(f'  Remove:  schtasks /Delete /TN "{TASK_NAME}" /F')
        print()
        print("review.pyw will show a popup on open whenever new videos or metadata are found.")
    else:
        print(f"✗ Failed:\n{result.stderr or result.stdout}")
        sys.exit(1)
except FileNotFoundError:
    print("✗ schtasks.exe not found. Are you running this on Windows?")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
