"""R4V Launcher — quick-access button panel for all pipeline commands."""
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path

ROOT = Path(__file__).parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
PYTHONW = str(ROOT / ".venv" / "Scripts" / "pythonw.exe")

COMMANDS = [
    ("Discover Videos",         [PYTHON, "cli.py", "discover"]),
    ("Fetch Transcripts",       [PYTHON, "cli.py", "transcripts"]),
    ("Generate AI Metadata",    [PYTHON, "cli.py", "generate"]),
    ("Open Review GUI",         [PYTHONW, "review.pyw"]),
    ("Push Dry-Run",            [PYTHON, "cli.py", "push", "--dry-run"]),
    ("Push to YouTube",         [PYTHON, "cli.py", "push"]),
    ("Engage Dry-Run",          [PYTHON, "cli.py", "engage", "--dry-run"]),
    ("Engage",                  [PYTHON, "cli.py", "engage"]),
    ("Pipeline (new only)",     [PYTHON, "cli.py", "pipeline", "--new-only"]),
    ("Check Quota",             [PYTHON, "cli.py", "quota"]),
]

BG        = "#1e1e2e"
BG_CARD   = "#2a2a3e"
FG        = "#cdd6f4"
ACCENT    = "#89b4fa"
BTN_BG    = "#313244"
BTN_HOV   = "#45475a"
BTN_RUN   = "#a6e3a1"
BTN_RUN_FG= "#1e1e2e"


def run_cmd(cmd, btn):
    btn.config(state="disabled", text=f"Running…")
    def _go():
        try:
            subprocess.Popen(cmd, cwd=str(ROOT), creationflags=subprocess.CREATE_NEW_CONSOLE)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        finally:
            btn.after(1500, lambda: btn.config(state="normal", text=btn._label))
    btn.after(10, _go)


root = tk.Tk()
root.title("R4V Launcher")
root.configure(bg=BG)
root.resizable(False, False)

title = tk.Label(root, text="Roll4Veterans Pipeline", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 13, "bold"), pady=10)
title.pack()

frame = tk.Frame(root, bg=BG, padx=16, pady=8)
frame.pack()

for label, cmd in COMMANDS:
    is_push = "Push to YouTube" == label or "Engage" == label and "Dry" not in label
    bg_c  = "#f38ba8" if is_push else BTN_BG
    fg_c  = BTN_RUN_FG if is_push else FG
    hov_c = "#eba0ac" if is_push else BTN_HOV

    btn = tk.Button(
        frame, text=label, width=26,
        bg=bg_c, fg=fg_c, activebackground=hov_c, activeforeground=fg_c,
        font=("Segoe UI", 10), relief="flat", cursor="hand2",
        pady=6, bd=0, highlightthickness=0,
    )
    btn._label = label
    btn.config(command=lambda c=cmd, b=btn: run_cmd(c, b))
    btn.pack(pady=3)

    def _on_enter(e, b=btn, h=hov_c): b.config(bg=h)
    def _on_leave(e, b=btn, n=bg_c):  b.config(bg=n)
    btn.bind("<Enter>", _on_enter)
    btn.bind("<Leave>", _on_leave)

footer = tk.Label(root, text="Terminal commands open in a new window",
                  bg=BG, fg="#6c7086", font=("Segoe UI", 8), pady=8)
footer.pack()

root.mainloop()
