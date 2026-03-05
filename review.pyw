"""
review.pyw — R4V Metadata Review & Approval GUI
Run with: C:\Python314\pythonw.exe review.pyw   (no console window)
     or:  double-click in Windows Explorer

On open: automatically runs discover → transcripts → generate in background,
then loads the review UI when the pipeline completes.
"""
import ctypes
import datetime
import json
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from ctypes.wintypes import RECT
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

# ── Resolve project root regardless of working directory ──────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Data paths (mirror config/settings.py without importing heavy deps yet) ───
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_DIR = DATA_DIR / "generated"
VIDEOS_JSON = DATA_DIR / "videos.json"
CHECK_STATE_JSON = DATA_DIR / "check_state.json"

# ── Colours ───────────────────────────────────────────────────────────────────
CLR_BG = "#0e0e1c"
CLR_PANEL = "#181828"
CLR_BORDER = "#44447a"
CLR_TEXT = "#ffffff"
CLR_MUTED = "#8a90b8"
CLR_CURRENT = "#1e1e38"
CLR_PROPOSED = "#092a18"
CLR_LINK = "#62ddff"
CLR_APPROVE = "#00e676"
CLR_SKIP = "#ff4466"
CLR_BTN_BG = "#30324e"
CLR_HEADER = "#cc88ff"

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_widest_monitor_width() -> int:
    """Return the pixel width of the widest connected monitor."""
    widths: list[int] = []

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.POINTER(RECT),
        ctypes.c_double,
    )

    def _cb(hMon, hDC, lpRect, dwData):
        r = lpRect.contents
        widths.append(r.right - r.left)
        return True

    try:
        ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(_cb), 0)
    except Exception:
        pass

    return max(widths) if widths else 1920


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_all_data() -> tuple[list[dict], dict[str, dict]]:
    """Return (videos_list, {video_id: metadata_dict})."""
    videos = load_json(VIDEOS_JSON) or []
    metadata: dict[str, dict] = {}
    if GENERATED_DIR.exists():
        for p in sorted(GENERATED_DIR.glob("*_metadata.json")):
            vid = p.stem.replace("_metadata", "")
            data = load_json(p)
            if data:
                metadata[vid] = data
    return videos, metadata


def get_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/shorts/{video_id}"


def tags_to_str(tags) -> str:
    if isinstance(tags, list):
        return ", ".join(tags)
    return str(tags or "")


def str_to_tags(s: str) -> list[str]:
    return [t.strip() for t in s.split(",") if t.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Tooltip
# ─────────────────────────────────────────────────────────────────────────────

class Tooltip:
    """Hover tooltip for any tkinter widget. Shows after DELAY ms, hides on leave."""
    DELAY = 550  # ms before appearing

    def __init__(self, widget, text: str):
        self._widget   = widget
        self._text     = text
        self._tip      = None
        self._after_id = None
        widget.bind("<Enter>",  self._schedule, add="+")
        widget.bind("<Leave>",  self._cancel,   add="+")
        widget.bind("<Button>", self._cancel,   add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after_id = self._widget.after(self.DELAY, self._show)

    def _cancel(self, _=None):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        if self._tip:
            return
        x = self._widget.winfo_rootx() + 6
        y = self._widget.winfo_rooty() - 34
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._tip, text=self._text,
            bg="#2a2a4a", fg="#ffcc44",
            font=(FONT_FAMILY, 9), relief="solid", borderwidth=1,
            padx=10, pady=5,
        ).pack()


# ─────────────────────────────────────────────────────────────────────────────
# WrapFrame — left-to-right layout that wraps children on resize
# ─────────────────────────────────────────────────────────────────────────────

class WrapFrame(tk.Frame):
    """Frame that arranges child widgets left-to-right, wrapping to the next
    row when the available width is exceeded.  Children are registered via
    add(); the frame manages its own height via place()."""

    def __init__(self, master, gap: int = 4, **kw):
        super().__init__(master, **kw)
        self.pack_propagate(False)   # height controlled by _reflow, not children
        self._gap = gap
        self._items: list[tuple[tk.Widget, int]] = []  # (widget, padx)
        self.bind("<Configure>", lambda e: self.after_idle(self._reflow))

    def add(self, widget: tk.Widget, padx: int = 3) -> tk.Widget:
        """Register a child widget for wrapping layout and return it."""
        self._items.append((widget, padx))
        return widget

    def _reflow(self):
        W = self.winfo_width()
        if W < 10:
            return
        x, y, row_h = self._gap, self._gap, 0
        for widget, padx in self._items:
            widget.update_idletasks()
            rw = max(widget.winfo_reqwidth(), 1) + padx * 2
            rh = max(widget.winfo_reqheight(), 4)
            if x + rw > W and x > self._gap:
                x = self._gap
                y += row_h + self._gap
                row_h = 0
            widget.place(x=x + padx, y=y)
            x += rw
            row_h = max(row_h, rh)
        self.configure(height=y + row_h + self._gap)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner (background thread)
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline_thread(progress_q: queue.Queue, stop_event: threading.Event) -> None:
    """Run discover → transcripts → generate in a background thread.
    Posts (step, message) tuples to progress_q; posts ('done', '') when finished,
    or ('error', traceback) on failure. Checks stop_event to bail early.
    """
    try:
        progress_q.put(("step", "Discovering videos…"))
        from r4v.channel import discover_videos
        from config.settings import CHANNEL_URL
        videos = discover_videos(CHANNEL_URL, force=False)
        progress_q.put(("info", f"Found {len(videos)} videos"))
        if stop_event.is_set():
            progress_q.put(("done", ""))
            return

        # Only load cached transcripts — never attempt live fetches on startup
        progress_q.put(("step", "Loading cached transcripts…"))
        from r4v.storage import load_json as _load_transcript_json
        transcripts_map = {}
        for v in videos:
            if stop_event.is_set():
                progress_q.put(("done", ""))
                return
            cache_path = DATA_DIR / "transcripts" / f"{v['id']}.json"
            if cache_path.exists():
                t = _load_transcript_json(cache_path)
                if t:
                    transcripts_map[v["id"]] = t

        ok = len(transcripts_map)
        total = len(videos)
        progress_q.put(("info", f"Cached transcripts: {ok}/{total} (use Transcripts button to fetch more)"))
        if stop_event.is_set():
            progress_q.put(("done", ""))
            return

        progress_q.put(("step", "Generating AI metadata…"))
        from r4v.content_gen import generate_metadata
        generated = 0
        for i, v in enumerate(videos, 1):
            if stop_event.is_set():
                progress_q.put(("done", ""))
                return
            t = transcripts_map.get(v["id"])
            if not t:
                continue
            progress_q.put(("progress", f"Generating {i}/{total}: {v['id']}"))
            generate_metadata(
                video_id=v["id"],
                transcript_text=t["text"],
                existing_title=v.get("title", ""),
                transcript_urls=t.get("urls", []),
                force=False,
            )
            generated += 1

        progress_q.put(("info", f"Generated metadata for {generated} videos"))
        progress_q.put(("done", ""))

    except Exception as e:
        import traceback
        progress_q.put(("error", traceback.format_exc()))


# ─────────────────────────────────────────────────────────────────────────────
# Startup splash / progress window
# ─────────────────────────────────────────────────────────────────────────────

class PipelineSplash:
    """Modal-ish progress window shown while the pipeline runs on startup."""

    def __init__(self, root: tk.Tk, on_done, on_error):
        self.root = root
        self.on_done = on_done
        self.on_error = on_error
        self._q: queue.Queue = queue.Queue()

        self.win = tk.Toplevel(root)
        self.win.title("R4V — Running Pipeline")
        self.win.configure(bg=CLR_BG)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)  # block close

        # Centre on screen
        self.win.geometry("540x280")
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - 540) // 2
        y = (sh - 280) // 2
        self.win.geometry(f"540x280+{x}+{y}")

        tk.Label(
            self.win, text="R4V Metadata Pipeline",
            bg=CLR_BG, fg=CLR_HEADER,
            font=(FONT_FAMILY, 14, "bold"),
        ).pack(pady=(20, 4))

        tk.Label(
            self.win,
            text="Discovering videos · fetching transcripts · generating AI metadata",
            bg=CLR_BG, fg=CLR_MUTED,
            font=(FONT_FAMILY, 9),
        ).pack()

        self._step_var = tk.StringVar(value="Starting…")
        tk.Label(
            self.win, textvariable=self._step_var,
            bg=CLR_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 11, "bold"),
        ).pack(pady=(16, 4))

        self._prog = ttk.Progressbar(self.win, mode="indeterminate", length=460)
        self._prog.pack(pady=4)
        self._prog.start(12)

        self._detail_var = tk.StringVar(value="")
        tk.Label(
            self.win, textvariable=self._detail_var,
            bg=CLR_BG, fg=CLR_MUTED,
            font=(FONT_MONO, 8),
            wraplength=500,
        ).pack(pady=4)

        self._info_var = tk.StringVar(value="")
        tk.Label(
            self.win, textvariable=self._info_var,
            bg=CLR_BG, fg=CLR_APPROVE,
            font=(FONT_FAMILY, 9),
        ).pack()

        tk.Button(
            self.win, text="Skip → Load cached data",
            command=self._skip,
            bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 9), relief="flat",
            padx=12, pady=4, cursor="hand2",
        ).pack(pady=(12, 0))

        # Start background thread
        self._stop_event = threading.Event()
        t = threading.Thread(target=run_pipeline_thread, args=(self._q, self._stop_event), daemon=True)
        t.start()
        self.win.after(100, self._poll)

    def _skip(self):
        self._stop_event.set()
        self._prog.stop()
        self.win.destroy()
        self.on_done()

    def _poll(self):
        try:
            while True:
                kind, msg = self._q.get_nowait()
                if kind == "step":
                    self._step_var.set(msg)
                    self._detail_var.set("")
                elif kind == "progress":
                    self._detail_var.set(msg)
                elif kind == "info":
                    self._info_var.set(msg)
                elif kind == "done":
                    self._prog.stop()
                    self.win.destroy()
                    self.on_done()
                    return
                elif kind == "error":
                    self._prog.stop()
                    self.win.destroy()
                    self.on_error(msg)
                    return
        except queue.Empty:
            pass
        self.win.after(100, self._poll)


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────

class R4VReviewApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("R4V Metadata Review")
        self.root.configure(bg=CLR_BG)

        self._max_width = get_widest_monitor_width()
        self.root.geometry(f"{self._max_width}x900+0+0")

        # Per-video widget references: {video_id: {field: widget}}
        self._widgets: dict[str, dict] = {}
        self._status_vars: dict[str, tk.StringVar] = {}

        # Data
        self._videos: list[dict] = []
        self._metadata: dict[str, dict] = {}
        self._video_map: dict[str, dict] = {}

        # Navigation state
        self._filtered_ids: list[str] = []
        self._current_index: int = 0

        # Process buttons registry (populated in _build_ui; used for disable-all-during-run)
        self._proc_buttons: dict = {}

        self.root.minsize(880, 600)
        self._build_ui()
        self._load_data()
        self.root.after(600, self._check_new_activity)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Row 1: nav toolbar ────────────────────────────────────────────────
        toolbar = tk.Frame(self.root, bg=CLR_PANEL, pady=5)
        toolbar.pack(fill="x", side="top")

        tk.Label(
            toolbar, text="  R4V Metadata Review",
            bg=CLR_PANEL, fg=CLR_HEADER,
            font=(FONT_FAMILY, 13, "bold"),
        ).pack(side="left", padx=10)

        # Filter dropdown
        tk.Label(toolbar, text="Filter:", bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 10)).pack(side="left", padx=(12, 4))

        self._filter_var = tk.StringVar(value="Has Metadata")
        filter_menu = ttk.Combobox(
            toolbar, textvariable=self._filter_var,
            values=["All", "Pending", "Approved", "Skipped", "Has Metadata", "No Metadata", "Needs JT"],
            state="readonly", width=14, font=(FONT_FAMILY, 10),
        )
        filter_menu.pack(side="left")
        self._filter_var.trace_add("write", lambda *_: self._load_data())

        # Nav controls
        nav_frame = tk.Frame(toolbar, bg=CLR_PANEL)
        nav_frame.pack(side="left", padx=16)

        self._btn_prev = tk.Button(
            nav_frame, text="◀", command=lambda: self._nav(-1),
            bg=CLR_BTN_BG, fg=CLR_MUTED, state="disabled", cursor="arrow",
            font=(FONT_FAMILY, 9, "bold"), relief="flat", padx=8, pady=3,
        )
        self._btn_prev.pack(side="left", padx=2)
        Tooltip(self._btn_prev, "Previous video  (← arrow key)")

        self._nav_var = tk.StringVar(value="0 / 0")
        tk.Label(
            nav_frame, textvariable=self._nav_var,
            bg=CLR_PANEL, fg=CLR_TEXT,
            font=(FONT_FAMILY, 10, "bold"), width=8, anchor="center",
        ).pack(side="left", padx=4)

        self._btn_next = tk.Button(
            nav_frame, text="▶", command=lambda: self._nav(1),
            bg=CLR_BTN_BG, fg=CLR_MUTED, state="disabled", cursor="arrow",
            font=(FONT_FAMILY, 9, "bold"), relief="flat", padx=8, pady=3,
        )
        self._btn_next.pack(side="left", padx=2)
        Tooltip(self._btn_next, "Next video  (→ arrow key)")

        # Title jump dropdown
        self._jump_var = tk.StringVar()
        self._jump_combo = ttk.Combobox(
            nav_frame, textvariable=self._jump_var,
            state="readonly", width=50, font=(FONT_FAMILY, 9),
        )
        self._jump_combo.pack(side="left", padx=8)
        self._jump_combo.bind("<<ComboboxSelected>>", self._on_jump_select)

        # More ▼ pulldown menu (right side)
        self._more_menu = tk.Menu(
            self.root, tearoff=0,
            bg=CLR_PANEL, fg=CLR_TEXT,
            font=(FONT_FAMILY, 9),
            activebackground=CLR_BTN_BG, activeforeground=CLR_TEXT,
        )
        self._more_menu.add_command(
            label="Push Dry-Run",
            command=lambda: self._run_cli("Push Dry-Run", ["cli.py", "push", "--dry-run"], None, False),
        )
        self._more_menu.add_command(
            label="Engage Dry-Run",
            command=lambda: self._run_cli("Engage Dry-Run", ["cli.py", "engage", "--dry-run"], None, False),
        )
        self._more_menu.add_separator()
        self._more_menu.add_command(
            label="Check Quota",
            command=lambda: self._run_cli("Check Quota", ["cli.py", "quota"], None, False),
        )
        self._more_menu.add_separator()
        self._more_menu.add_command(label="Reload data", command=self._load_data)
        self._more_menu.add_command(label="↺ Reset process", command=self._reset_proc)

        more_btn = tk.Button(
            toolbar, text="More ▼",
            bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 9), relief="flat",
            padx=10, pady=4, cursor="hand2",
        )
        more_btn.config(command=lambda b=more_btn: self._more_menu.tk_popup(
            b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
        more_btn.pack(side="right", padx=(0, 10))
        Tooltip(more_btn, "Push Dry-Run · Engage Dry-Run · Check Quota · Reload · Reset")

        # ── Row 2: action bar (wraps on resize) ───────────────────────────────
        self._action_bar = WrapFrame(self.root, gap=5, bg=CLR_PANEL)
        self._action_bar.pack(fill="x", side="top", pady=(0, 2))

        def _sep() -> tk.Frame:
            return tk.Frame(self._action_bar, bg=CLR_BORDER, width=2, height=28)

        def _abtn(text: str, cmd, color: str, tip: str, key: str = None) -> tk.Button:
            fg = "#1e1e2e" if color in (CLR_APPROVE, CLR_SKIP, "#89b4fa") else CLR_TEXT
            b = tk.Button(
                self._action_bar, text=text, command=cmd,
                bg=color, fg=fg,
                font=(FONT_FAMILY, 9, "bold"), relief="flat",
                padx=10, pady=5, cursor="hand2",
            )
            Tooltip(b, tip)
            if key:
                self._proc_buttons[key] = b
            return b

        # Group 1: pipeline ops
        b_pipe = _abtn(
            "Pipeline ▸", self._open_pipeline_window, "#89b4fa",
            "Run discover → transcripts (cached) → generate AI for new videos only\n"
            "Opens a live progress window — click Skip to load cached data instead",
            "Pipeline ▸",
        )
        self._action_bar.add(b_pipe, padx=5)

        b_desc = _abtn(
            "Fetch Descs",
            lambda: self._run_cli("Fetch Descs", ["cli.py", "descriptions"],
                                  self._proc_buttons["Fetch Descs"], True),
            CLR_BTN_BG,
            "Download current descriptions from YouTube\n(fills the Current pane in each card)",
            "Fetch Descs",
        )
        self._action_bar.add(b_desc, padx=2)

        b_trans = _abtn(
            "Transcripts",
            lambda: self._run_cli("Transcripts", ["cli.py", "transcripts"],
                                  self._proc_buttons["Transcripts"], False),
            CLR_BTN_BG,
            "Fetch auto-generated captions for any video without them yet\n"
            "(may wait 2-4 h if YouTube rate-limits the IP — check back later)",
            "Transcripts",
        )
        self._action_bar.add(b_trans, padx=2)

        self._action_bar.add(_sep(), padx=8)

        # Group 2: push / engage
        b_push = _abtn(
            "Push Approved → YouTube", self._push_approved, "#89b4fa",
            "Apply all Approved metadata to YouTube via the Data API\n"
            "Requires OAuth — opens cli.py push in a new terminal",
            "Push Approved",
        )
        self._action_bar.add(b_push, padx=5)

        b_engage = _abtn(
            "Engage",
            lambda: self._run_cli("Engage", ["cli.py", "engage"],
                                  self._proc_buttons["Engage"], False),
            CLR_SKIP,
            "Like all Approved videos and post their channel comments as @roll4veterans\n"
            "Skips videos flagged 'JT Required'",
            "Engage",
        )
        self._action_bar.add(b_engage, padx=2)

        self._action_bar.add(_sep(), padx=8)

        # Group 3: personality
        b_pers = _abtn(
            "🎭 Personality", self._edit_personalities, CLR_BTN_BG,
            "Edit JT's voice profile and sample phrases\n"
            "(config/personalities.json) — changes take effect on next ⚡",
        )
        self._action_bar.add(b_pers, padx=5)

        self._action_bar.add(_sep(), padx=8)

        # Group 4: help / exit
        b_help = _abtn("? Help", self._show_help, "#f9e2af",
                        "Show workflow guide and keyboard shortcuts")
        self._action_bar.add(b_help, padx=5)

        b_exit = _abtn("Exit", self.root.destroy, CLR_BTN_BG, "Close the review tool")
        self._action_bar.add(b_exit, padx=2)

        # ── Process + status bars (pack before card so they anchor to bottom) ──
        self._build_bottom_bar()

        # ── Single-card area ──────────────────────────────────────────────────
        self._card_frame = tk.Frame(self.root, bg=CLR_BG)
        self._card_frame.pack(fill="both", expand=True)

        # Keyboard navigation (skip when focus is inside a text-editing widget)
        self.root.bind("<Left>",  self._on_left_key)
        self.root.bind("<Right>", self._on_right_key)

    def _on_left_key(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        self._nav(-1)

    def _on_right_key(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        self._nav(1)

    def _make_btn(self, parent, text, cmd, color):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=color, fg="#000000",
            font=(FONT_FAMILY, 9, "bold"), relief="flat",
            padx=10, pady=4, cursor="hand2",
        )

    # ── Data loading ──────────────────────────────────────────────────────────

    def _should_show(self, video_id: str) -> bool:
        f = self._filter_var.get()
        if f == "All":
            return True
        meta = self._metadata.get(video_id)
        if f == "Has Metadata":
            return meta is not None
        if f == "No Metadata":
            return meta is None
        if f == "Pending":
            return meta is not None and meta.get("approved") is None
        if f == "Approved":
            return meta is not None and meta.get("approved") is True
        if f == "Skipped":
            return meta is not None and meta.get("approved") is False
        if f == "Needs JT":
            return meta is not None and meta.get("needs_jt_comment", False)
        return True

    def _load_data(self, *_):
        self._autosave_current()
        self._videos, self._metadata = load_all_data()
        self._video_map = {v["id"]: v for v in self._videos}

        # Build ordered list: metadata videos first, then the rest
        seen: set[str] = set()
        video_ids_all: list[str] = []
        for vid in self._metadata:
            video_ids_all.append(vid)
            seen.add(vid)
        for v in self._videos:
            if v["id"] not in seen:
                video_ids_all.append(v["id"])

        self._filtered_ids = [vid for vid in video_ids_all if self._should_show(vid)]

        # Clamp index to valid range
        if self._filtered_ids:
            self._current_index = min(self._current_index, len(self._filtered_ids) - 1)
        else:
            self._current_index = 0

        # Populate jump dropdown
        jump_titles = []
        for i, vid in enumerate(self._filtered_ids):
            v = self._video_map.get(vid, {})
            meta = self._metadata.get(vid, {})
            title = (v.get("title") or meta.get("existing_title") or vid)[:60]
            jump_titles.append(f"#{i + 1:>3}  {title}")
        self._jump_combo["values"] = jump_titles

        self._update_summary()
        self._show_card(self._current_index)

    # ── Background-check notification ─────────────────────────────────────────

    def _check_new_activity(self):
        """Show a popup if the scheduled background check found new activity."""
        state = load_json(CHECK_STATE_JSON)
        if not state:
            return

        last_check = state.get("last_check_iso", "")
        last_notified = state.get("last_notified_iso") or ""

        # Only show if there's a check run we haven't notified about yet
        if not last_check or last_check <= last_notified:
            return

        new_vids  = state.get("new_video_ids", [])
        newly_gen = state.get("newly_generated", [])
        needs_t   = state.get("needs_transcript", [])
        pending   = state.get("total_pending_review", 0)

        # Mark as notified immediately (covers all close paths incl. title-bar X)
        state["last_notified_iso"] = datetime.datetime.now().isoformat(timespec="seconds")
        save_json(CHECK_STATE_JSON, state)

        # Nothing worth showing
        if not new_vids and not newly_gen and not pending:
            return

        # Format "last check X ago (H:MM AM/PM)"
        try:
            check_dt = datetime.datetime.fromisoformat(last_check)
            age_min  = int((datetime.datetime.now() - check_dt).total_seconds() / 60)
            if age_min < 2:
                age_str = "just now"
            elif age_min < 60:
                age_str = f"{age_min}m ago"
            else:
                h, m = divmod(age_min, 60)
                age_str = f"{h}h {m}m ago" if m else f"{h}h ago"
            hour   = check_dt.hour % 12 or 12
            ampm   = "AM" if check_dt.hour < 12 else "PM"
            time_str = f"{age_str}  ({hour}:{check_dt.minute:02d} {ampm})"
        except Exception:
            time_str = last_check

        # ── Build popup ───────────────────────────────────────────────────────
        win = tk.Toplevel(self.root)
        win.title("New Activity")
        win.configure(bg=CLR_BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        rows   = sum([bool(new_vids), bool(newly_gen), bool(pending), bool(needs_t)])
        win_h  = 200 + rows * 30
        self.root.update_idletasks()
        cx = self.root.winfo_x() + self.root.winfo_width()  // 2 - 280
        cy = self.root.winfo_y() + 160
        win.geometry(f"560x{win_h}+{max(0, cx)}+{max(0, cy)}")

        tk.Label(
            win, text="New Activity Found", bg=CLR_BG,
            fg=CLR_APPROVE, font=(FONT_FAMILY, 14, "bold"),
        ).pack(anchor="w", padx=28, pady=(16, 2))
        tk.Label(
            win, text=f"Last check: {time_str}", bg=CLR_BG,
            fg=CLR_MUTED, font=(FONT_FAMILY, 9),
        ).pack(anchor="w", padx=28, pady=(0, 10))

        def _row(icon, text, colour):
            tk.Label(
                win, text=f"  {icon}  {text}", bg=CLR_BG,
                fg=colour, font=(FONT_FAMILY, 11), anchor="w",
            ).pack(fill="x", padx=20, pady=2)

        if new_vids:
            _row("●", f"{len(new_vids)} new video{'s' if len(new_vids) != 1 else ''} discovered", CLR_APPROVE)
        if newly_gen:
            _row("●", f"{len(newly_gen)} video{'s' if len(newly_gen) != 1 else ''} ready for review (AI generated)", CLR_LINK)
        if pending:
            _row("●", f"{pending} total pending your review", CLR_TEXT)
        if needs_t:
            _row("○", f"{len(needs_t)} still waiting for transcripts (may be IP-blocked)", CLR_MUTED)

        tk.Frame(win, bg=CLR_BORDER, height=1).pack(fill="x", padx=20, pady=12)

        btn_row = tk.Frame(win, bg=CLR_BG)
        btn_row.pack(pady=(0, 16))

        def _jump():
            win.destroy()
            self._filter_var.set("Pending")

        def _dismiss():
            win.destroy()

        tk.Button(
            btn_row, text="Jump to Review", bg="#89b4fa", fg="#0e0e1c",
            font=(FONT_FAMILY, 11, "bold"), relief="flat",
            padx=18, pady=6, cursor="hand2", command=_jump,
        ).pack(side="left", padx=8)
        tk.Button(
            btn_row, text="Dismiss", bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 11), relief="flat",
            padx=18, pady=6, cursor="hand2", command=_dismiss,
        ).pack(side="left", padx=8)

        win.protocol("WM_DELETE_WINDOW", _dismiss)

    # ── Footer helper ─────────────────────────────────────────────────────────

    def _apply_footer(self, prop_w: tk.Text, video_id: str):
        """Apply the canonical footer to the description.

        - Strips any existing footer boilerplate (JOIN THE CONVERSATION block).
        - Preserves any extra 🔗 link lines that were already in the footer
          (e.g. URLs extracted from the transcript at generation time).
        - Pulls the current hashtags from the Hashtags field widget.
        - Safe to call multiple times — idempotent.
        """
        from config.settings import FOOTER_TEMPLATE

        FOOTER_MARKER = "\nJOIN THE CONVERSATION"

        # Pull hashtags from the sibling Hashtags widget
        ht_w = self._widgets.get(video_id, {}).get("hashtags")
        hashtags = ht_w.get().strip() if ht_w else ""

        # Get current description text
        text = prop_w.get("1.0", "end-1c")

        # Preserve any 🔗 extra-link lines already present in the footer
        extra_links = ""
        if FOOTER_MARKER in text:
            existing_footer = text[text.index(FOOTER_MARKER):]
            link_lines = [ln for ln in existing_footer.split("\n") if ln.startswith("🔗")]
            if link_lines:
                extra_links = "\n" + "\n".join(link_lines)
            text = text[:text.index(FOOTER_MARKER)]

        text = text.rstrip()

        footer = FOOTER_TEMPLATE.format(extra_links=extra_links, hashtags=hashtags)
        prop_w.delete("1.0", "end")
        prop_w.insert("1.0", text + footer)

    # ── Single-card navigation ─────────────────────────────────────────────────

    def _show_card(self, idx: int):
        """Clear card frame and render the card at idx."""
        for w in self._card_frame.winfo_children():
            w.destroy()
        self._widgets.clear()
        self._status_vars.clear()

        total = len(self._filtered_ids)
        if not total:
            tk.Label(
                self._card_frame,
                text="No videos match the current filter.",
                bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 12),
            ).pack(expand=True)
            self._nav_var.set("0 / 0")
            self._update_nav_buttons()
            return

        idx = max(0, min(idx, total - 1))
        self._current_index = idx
        self._nav_var.set(f"{idx + 1} / {total}")
        self._update_nav_buttons()
        try:
            self._jump_combo.current(idx)
        except Exception:
            pass

        self._build_video_card(self._filtered_ids[idx], idx, total)

    def _nav(self, delta: int):
        """Move forward/backward through the filtered list."""
        self._autosave_current()
        if not self._filtered_ids:
            return
        new_idx = max(0, min(len(self._filtered_ids) - 1, self._current_index + delta))
        if new_idx != self._current_index:
            self._current_index = new_idx
            self._show_card(self._current_index)

    def _update_nav_buttons(self):
        """Enable/disable ◀ ▶ and set state+cursor at list boundaries."""
        total = len(self._filtered_ids)
        at_start = (total == 0 or self._current_index <= 0)
        at_end   = (total == 0 or self._current_index >= total - 1)
        if at_start:
            self._btn_prev.config(state="disabled", fg=CLR_MUTED, cursor="arrow")
        else:
            self._btn_prev.config(state="normal",   fg=CLR_TEXT,  cursor="hand2")
        if at_end:
            self._btn_next.config(state="disabled", fg=CLR_MUTED, cursor="arrow")
        else:
            self._btn_next.config(state="normal",   fg=CLR_TEXT,  cursor="hand2")

    def _open_pipeline_window(self):
        """Open a dedicated progress window and run cli.py pipeline --new-only."""
        if self._proc_running:
            messagebox.showwarning("Busy", "Another process is already running.\nUse ↺ Reset (More ▼) if it is stuck.")
            return

        # Mark busy and disable all registered proc buttons
        self._proc_running = True
        for b in (v for v in self._proc_buttons.values() if v is not None):
            b.config(state="disabled")
        self._proc_progbar.start(12)
        self._proc_status_var.set("Pipeline: new videos only…")

        # Build progress window
        win = tk.Toplevel(self.root)
        win.title("R4V — Pipeline (new videos only)")
        win.configure(bg=CLR_BG)
        win.geometry("620x440")
        win.update_idletasks()
        cx = (win.winfo_screenwidth() - 620) // 2
        cy = (win.winfo_screenheight() - 440) // 2
        win.geometry(f"620x440+{cx}+{cy}")
        win.lift()

        tk.Label(win, text="R4V Pipeline — New Videos Only",
                 bg=CLR_BG, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 13, "bold")).pack(pady=(16, 2))
        tk.Label(win, text="discover  ·  transcripts (cached)  ·  generate AI metadata",
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 9)).pack()

        log_frame = tk.Frame(win, bg=CLR_BG)
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)

        log_txt = tk.Text(log_frame, bg="#111128", fg=CLR_TEXT,
                          font=(FONT_MONO, 9), relief="flat", wrap="word",
                          state="disabled", height=14)
        sb = ttk.Scrollbar(log_frame, command=log_txt.yview)
        log_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        log_txt.pack(fill="both", expand=True)

        status_var = tk.StringVar(value="Starting…")
        tk.Label(win, textvariable=status_var,
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_MONO, 8),
                 anchor="w", wraplength=580).pack(fill="x", padx=12)

        close_btn = tk.Button(win, text="Close when done",
                               bg=CLR_BTN_BG, fg=CLR_TEXT,
                               font=(FONT_FAMILY, 9), relief="flat",
                               padx=12, pady=4, cursor="hand2",
                               state="disabled", command=win.destroy)
        close_btn.pack(pady=(4, 14))

        def _append(text: str):
            log_txt.config(state="normal")
            log_txt.insert("end", text + "\n")
            log_txt.see("end")
            log_txt.config(state="disabled")

        _q: queue.Queue = queue.Queue()

        def _worker():
            python = self._find_python()
            cmd = [python, "-u", str(PROJECT_ROOT / "cli.py"), "pipeline", "--new-only"]
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        _q.put(("line", line))
                proc.wait()
                _q.put(("done", proc.returncode))
            except Exception as e:
                _q.put(("error", str(e)))

        def _finish(success: bool, msg: str):
            self._proc_running = False
            self._proc_progbar.stop()
            for b in (v for v in self._proc_buttons.values() if v is not None):
                b.config(state="normal")
            self._proc_status_var.set(msg)
            if success:
                self._load_data()
            try:
                close_btn.config(state="normal", text="Close")
                win.protocol("WM_DELETE_WINDOW", win.destroy)
            except Exception:
                pass

        def _poll():
            try:
                while True:
                    kind, val = _q.get_nowait()
                    if kind == "line":
                        _append(val)
                        status_var.set(val[:100])
                    elif kind == "done":
                        rc = val
                        msg = "✓ Pipeline complete" if rc == 0 else f"⚠ Pipeline exited {rc}"
                        _append(f"\n{msg}")
                        status_var.set(msg)
                        _finish(rc == 0, msg)
                        return
                    elif kind == "error":
                        msg = f"⚠ Error: {val}"
                        _append(f"\n{msg}")
                        status_var.set(msg[:100])
                        _finish(False, msg[:120])
                        return
            except queue.Empty:
                pass
            try:
                win.after(100, _poll)
            except Exception:
                pass  # window destroyed early

        threading.Thread(target=_worker, daemon=True).start()
        win.after(100, _poll)
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # blocked while running

    def _on_jump_select(self, event):
        self._autosave_current()
        idx = self._jump_combo.current()
        if idx >= 0:
            self._current_index = idx
            self._show_card(idx)

    def _autosave_current(self):
        """Persist edits in the current card's proposed fields without changing approval."""
        if not self._filtered_ids:
            return
        try:
            video_id = self._filtered_ids[self._current_index]
        except IndexError:
            return
        meta = self._metadata.get(video_id)
        widgets = self._widgets.get(video_id, {})
        if not meta or not widgets:
            return
        for field, w in widgets.items():
            if isinstance(w, tk.Text):
                meta[field] = w.get("1.0", "end-1c")
            elif isinstance(w, tk.Entry):
                meta[field] = w.get()
        if "tags" in meta and isinstance(meta["tags"], str):
            meta["tags"] = str_to_tags(meta["tags"])
        save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)

    # ── Video card ────────────────────────────────────────────────────────────

    def _build_video_card(self, video_id: str, idx: int, total: int):
        video = self._video_map.get(video_id, {})
        meta = self._metadata.get(video_id)
        url = get_video_url(video_id)

        existing_title = video.get("title", "") or (meta.get("existing_title", "") if meta else "")
        existing_desc  = (video.get("description", "")
                          or "(not cached — view current description in YouTube Studio)")
        existing_tags  = tags_to_str(video.get("tags", []))

        has_meta = meta is not None
        approval = meta.get("approved") if meta else None
        is_locked = (approval is True)

        # ── Card frame fills the remaining window area ─────────────────────────
        card = tk.Frame(self._card_frame, bg=CLR_PANEL, pady=8, padx=12)
        card.pack(fill="both", expand=True, padx=8, pady=6)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = tk.Frame(card, bg=CLR_PANEL)
        hdr.pack(fill="x")

        status_var = tk.StringVar(value=self._approval_label(approval))
        self._status_vars[video_id] = status_var

        tk.Label(
            hdr, textvariable=status_var,
            bg=CLR_PANEL, fg=self._approval_color(approval),
            font=(FONT_FAMILY, 10, "bold"), width=12, anchor="w",
        ).pack(side="left")

        # Video ID badge
        tk.Label(
            hdr, text=f"#{idx + 1}  {video_id}",
            bg=CLR_PANEL, fg=CLR_MUTED, font=(FONT_MONO, 9),
        ).pack(side="left", padx=(0, 12))

        tk.Label(
            hdr, text=existing_title or video_id,
            bg=CLR_PANEL, fg=CLR_TEXT,
            font=(FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Clickable link
        link = tk.Label(hdr, text="▶ Watch", bg=CLR_PANEL, fg=CLR_LINK,
                        font=(FONT_FAMILY, 10, "underline"), cursor="hand2")
        link.pack(side="left", padx=8)
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        # Action buttons
        btn_row = tk.Frame(hdr, bg=CLR_PANEL)
        btn_row.pack(side="left")

        if is_locked:
            _approve_btn = self._make_btn(btn_row, "↩ Unapprove",
                           lambda vid=video_id: self._unapprove(vid), CLR_MUTED)
            Tooltip(_approve_btn, "Remove Approved status — unlocks all fields for editing")
        else:
            _approve_btn = self._make_btn(btn_row, "✓ Approve",
                           lambda vid=video_id: self._set_approval(vid, True), CLR_APPROVE)
            Tooltip(_approve_btn, "Mark as Approved — saves edits and queues for Push to YouTube\nAuto-advances to the next card")
        _approve_btn.pack(side="left", padx=2)

        _gen_btn = self._make_btn(btn_row, "↻ Gen All",
                       lambda vid=video_id: self._generate_this(vid), "#a8a8c8")
        _gen_btn.pack(side="left", padx=(6, 2))
        if is_locked:
            _gen_btn.config(state="disabled")
        Tooltip(_gen_btn, "Re-run Gemini AI for ALL fields of this video\nReloads the card when done  (disabled while Approved)")

        # JT flag — marks that this video needs JT's personal comment
        needs_jt = (meta or {}).get("needs_jt_comment", False)
        jt_btn = tk.Button(
            btn_row,
            text="📌 JT Required" if needs_jt else "⚑ Needs JT?",
            bg="#f9e2af" if needs_jt else CLR_BTN_BG,
            fg="#000000",
            font=(FONT_FAMILY, 9, "bold"), relief="flat",
            padx=10, pady=4, cursor="hand2",
        )
        jt_btn.pack(side="left", padx=(4, 2))
        jt_btn.config(command=lambda vid=video_id, b=jt_btn: self._toggle_jt(vid, b))
        Tooltip(jt_btn, "Toggle: flag this video so JT writes the comment himself\nFlagged videos are skipped by  cli.py engage")

        if not has_meta:
            tk.Label(
                card,
                text="  (no generated metadata yet — click  ↻ Gen This  or run Generate AI)",
                bg=CLR_PANEL, fg=CLR_MUTED, font=(FONT_FAMILY, 9, "italic"),
            ).pack(anchor="w", pady=4)
            return

        # ── Fields ────────────────────────────────────────────────────────────
        widgets: dict = {}
        self._widgets[video_id] = widgets

        if is_locked:
            tk.Label(
                card,
                text="  \U0001f512  APPROVED — all fields locked.   Click  \u21a9 Unapprove  to edit.",
                bg="#061a06", fg=CLR_APPROVE, font=(FONT_FAMILY, 9, "italic"),
            ).pack(fill="x", pady=(0, 4))

        proposed_title    = meta.get("title", "")
        proposed_desc     = meta.get("description", "")
        proposed_tags     = tags_to_str(meta.get("tags", []))
        proposed_hashtags = meta.get("hashtags", "")

        # TITLE "Current" box shows the video number + ID (title already in header).
        # copy_source is what actually gets copied into the proposed box — for TITLE
        # that's the real YouTube title, not the video-ID badge shown in the box.
        title_id_str = f"#{idx + 1} of {total}   {video_id}"

        # Extract hashtags from the existing description (they sit at the bottom after the footer)
        existing_hashtags = " ".join(re.findall(r"#\w+", existing_desc)) if existing_desc else ""

        # (label, display_in_current, proposed_val, kind, expands, copyable, copy_source)
        fields = [
            ("TITLE",       title_id_str,      proposed_title,     "single", False, True, existing_title),
            ("DESCRIPTION", existing_desc,     proposed_desc,      "multi",  True,  True, existing_desc),
            ("TAGS",        existing_tags,     proposed_tags,       "single", False, True, existing_tags),
            ("HASHTAGS",    existing_hashtags, proposed_hashtags,  "single", False, True, existing_hashtags),
        ]

        for label, current_val, proposed_val, kind, expands, copyable, copy_source in fields:
            row = tk.Frame(card, bg=CLR_PANEL, pady=3)
            row.pack(fill="both" if expands else "x", expand=expands)

            tk.Label(
                row, text=f"  {label}",
                bg=CLR_PANEL, fg=CLR_MUTED,
                font=(FONT_MONO, 9, "bold"), width=12, anchor="w",
            ).pack(side="left", anchor="n")

            cols = tk.Frame(row, bg=CLR_PANEL)
            cols.pack(fill="both" if expands else "x", expand=expands)

            # Current (read-only)
            cur_frame = tk.LabelFrame(
                cols, text="Current", bg=CLR_CURRENT, fg=CLR_TEXT,
                font=(FONT_FAMILY, 8), padx=4, pady=2,
            )
            cur_frame.pack(side="left", fill="both", expand=True)

            if kind == "multi":
                cur_w = tk.Text(
                    cur_frame, height=2, wrap="word",
                    bg=CLR_CURRENT, fg=CLR_TEXT,
                    font=(FONT_MONO, 9), relief="flat", state="disabled",
                )
                cur_w.pack(fill="both", expand=True)
                cur_w.config(state="normal")
                cur_w.insert("1.0", current_val)
                cur_w.config(state="disabled")
            else:
                cur_w = tk.Entry(
                    cur_frame,
                    bg=CLR_CURRENT, fg=CLR_TEXT,
                    font=(FONT_MONO, 9), relief="flat",
                    state="readonly", readonlybackground=CLR_CURRENT,
                )
                cur_w.pack(fill="x")
                cur_w.config(state="normal")
                cur_w.insert(0, current_val)
                cur_w.config(state="readonly")

            # Copy-arrow column (sits on the border between Current and Proposed)
            if copyable:
                copy_col = tk.Frame(cols, bg=CLR_PANEL, width=34)
                copy_col.pack(side="left", fill="y")
                copy_col.pack_propagate(False)

            # Proposed (editable — or locked while Approved)
            prop_lbl = "Proposed  (editable)" if not is_locked else "Proposed  (locked)"
            prop_frame = tk.LabelFrame(
                cols, text=prop_lbl,
                bg=CLR_PROPOSED, fg=CLR_APPROVE if not is_locked else CLR_MUTED,
                font=(FONT_FAMILY, 8), padx=4, pady=2,
            )
            prop_frame.pack(side="left", fill="both", expand=True)

            # ⚡ per-field AI gen button — packed first so it anchors top-right
            field_key = label.lower()
            gen_field_btn = tk.Button(
                prop_frame, text="\u26a1",
                bg=CLR_PROPOSED, fg="#ffcc44",
                font=(FONT_MONO, 8), relief="flat",
                cursor="hand2", padx=3, pady=0,
                state="disabled" if is_locked else "normal",
            )
            if is_locked:
                gen_field_btn.config(fg=CLR_MUTED)
            gen_field_btn.pack(side="right", anchor="n")
            Tooltip(gen_field_btn,
                    f"Regenerate just {label.title()} using AI\n"
                    "(other field edits are preserved)\n"
                    "Disabled while card is Approved")

            # 🔗 Footer button — only on DESCRIPTION field
            _footer_btn = None
            if label == "DESCRIPTION":
                _footer_btn = tk.Button(
                    prop_frame, text="\U0001f517",
                    bg=CLR_PROPOSED, fg=CLR_LINK,
                    font=(FONT_MONO, 8), relief="flat",
                    cursor="hand2", padx=3, pady=0,
                    state="disabled" if is_locked else "normal",
                )
                if is_locked:
                    _footer_btn.config(fg=CLR_MUTED)
                _footer_btn.pack(side="right", anchor="n")
                Tooltip(_footer_btn,
                        "Apply the canonical footer (links + hashtags)\n"
                        "Preserves any extra 🔗 links already in the field.\n"
                        "Pulls hashtags from the Hashtags field.\n"
                        "Disabled while card is Approved")

            if kind == "multi":
                prop_w = tk.Text(
                    prop_frame, height=4, wrap="word",
                    bg=CLR_PROPOSED, fg=CLR_TEXT,
                    font=(FONT_MONO, 9), relief="flat", insertbackground=CLR_TEXT,
                )
                prop_w.pack(fill="both", expand=True)
                prop_w.insert("1.0", proposed_val)
                if is_locked:
                    prop_w.config(state="disabled")
            else:
                prop_w = tk.Entry(
                    prop_frame,
                    bg=CLR_PROPOSED, fg=CLR_TEXT,
                    font=(FONT_MONO, 9), relief="flat", insertbackground=CLR_TEXT,
                )
                prop_w.pack(fill="x")
                prop_w.insert(0, proposed_val)
                if is_locked:
                    prop_w.config(state="readonly", readonlybackground=CLR_PROPOSED)

            # Wire ⚡ button now that prop_w exists
            if not is_locked:
                gen_field_btn.config(
                    command=lambda vid=video_id, fk=field_key, pw=prop_w, k=kind, b=gen_field_btn:
                            self._generate_field(vid, fk, pw, k, b)
                )

            # Wire 🔗 footer button
            if _footer_btn is not None and not is_locked:
                _footer_btn.config(
                    command=lambda pw=prop_w, vid=video_id: self._apply_footer(pw, vid)
                )

            # >> copy button between the boxes
            if copyable:
                def _make_copy(cs=copy_source, pw=prop_w, k=kind):
                    if k == "multi":
                        pw.delete("1.0", "end")
                        pw.insert("1.0", cs)
                    else:
                        pw.delete(0, "end")
                        pw.insert(0, cs)
                _copy_btn = tk.Button(
                    copy_col, text="\u00bb",
                    bg=CLR_BTN_BG, fg="#ffcc44",
                    font=(FONT_MONO, 11, "bold"), relief="flat",
                    cursor="hand2", command=_make_copy,
                    padx=0, pady=0,
                )
                _copy_btn.pack(expand=True)
                tip_src = "existing YouTube title" if label == "TITLE" else f"current YouTube {label.lower()}"
                Tooltip(_copy_btn, f"Copy {tip_src} into the Proposed field\n(overwrites AI-generated text)")
                if is_locked:
                    _copy_btn.config(state="disabled")

            widgets[label.lower()] = prop_w

        # ── Comment row (full-width, no Current pane) ─────────────────────────
        comment_row = tk.Frame(card, bg=CLR_PANEL, pady=3)
        comment_row.pack(fill="x")

        tk.Label(
            comment_row, text="  COMMENT",
            bg=CLR_PANEL, fg=CLR_MUTED,
            font=(FONT_MONO, 9, "bold"), width=12, anchor="w",
        ).pack(side="left")

        comment_lbl = "Channel comment to post (editable)" if not is_locked else "Channel comment (locked)"
        comment_frame = tk.LabelFrame(
            comment_row, text=comment_lbl,
            bg="#0d1f30", fg="#62ddff",
            font=(FONT_FAMILY, 8), padx=4, pady=2,
        )
        comment_frame.pack(side="left", fill="x", expand=True)

        comment_w = tk.Entry(
            comment_frame,
            bg="#0d1f30", fg=CLR_TEXT,
            font=(FONT_MONO, 9), relief="flat", insertbackground=CLR_TEXT,
        )
        comment_w.pack(fill="x")
        comment_w.insert(0, meta.get("comment", ""))
        if is_locked:
            comment_w.config(state="readonly", readonlybackground="#0d1f30")
        widgets["comment"] = comment_w

        tk.Frame(card, bg=CLR_BORDER, height=1).pack(fill="x", pady=(8, 0))

    # ── Approval logic ────────────────────────────────────────────────────────

    def _approval_label(self, val) -> str:
        if val is True:
            return "✓ APPROVED"
        if val is False:
            return "✗ SKIPPED"
        return "  PENDING"

    def _approval_color(self, val) -> str:
        if val is True:
            return CLR_APPROVE
        if val is False:
            return CLR_SKIP
        return CLR_MUTED

    def _set_approval(self, video_id: str, approved: bool):
        meta = self._metadata.get(video_id)
        if not meta:
            return

        widgets = self._widgets.get(video_id, {})
        if widgets:
            for field, w in widgets.items():
                if isinstance(w, tk.Text):
                    meta[field] = w.get("1.0", "end-1c")
                elif isinstance(w, tk.Entry):
                    meta[field] = w.get()
            if "tags" in meta and isinstance(meta["tags"], str):
                meta["tags"] = str_to_tags(meta["tags"])

        meta["approved"] = approved
        save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)

        if video_id in self._status_vars:
            self._status_vars[video_id].set(self._approval_label(approved))

        self._update_summary()

        # Auto-advance to the next card
        if self._current_index < len(self._filtered_ids) - 1:
            self._current_index += 1
            self._show_card(self._current_index)

    def _update_summary(self):
        total    = len(self._metadata)
        approved = sum(1 for m in self._metadata.values() if m.get("approved") is True)
        skipped  = sum(1 for m in self._metadata.values() if m.get("approved") is False)
        pending  = total - approved - skipped
        jt_count = sum(1 for m in self._metadata.values() if m.get("needs_jt_comment"))
        jt_str   = f"  |  📌 JT: {jt_count}" if jt_count else ""
        self._status_bar_var.set(
            f"Videos: {len(self._videos)}  |  With metadata: {total}  |  "
            f"Approved: {approved}  |  Skipped: {skipped}  |  Pending: {pending}{jt_str}"
        )

    def _toggle_jt(self, video_id: str, btn: tk.Button):
        """Toggle the 'needs JT personal comment' flag on a video."""
        meta = self._metadata.get(video_id)
        if not meta:
            return
        meta["needs_jt_comment"] = not meta.get("needs_jt_comment", False)
        save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)
        if meta["needs_jt_comment"]:
            btn.config(text="📌 JT Required", bg="#f9e2af")
        else:
            btn.config(text="⚑ Needs JT?", bg=CLR_BTN_BG)
        self._update_summary()

    def _unapprove(self, video_id: str):
        """Remove Approved status and rebuild the card as fully editable."""
        meta = self._metadata.get(video_id)
        if not meta:
            return
        meta["approved"] = None
        save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)
        self._update_summary()
        self._show_card(self._current_index)

    # ── Single-video AI generation ─────────────────────────────────────────────

    def _generate_this(self, video_id: str):
        """Run  cli.py generate --video-id {id} --force  for just this one card."""
        if self._proc_running:
            return
        btn = self._proc_buttons.get("Generate AI")
        self._run_cli(
            f"Gen: {video_id[:14]}",
            ["cli.py", "generate", "--video-id", video_id, "--force"],
            btn,
            auto_reload=True,
        )

    def _generate_field(self, video_id: str, field: str, prop_w, kind: str, btn: tk.Button):
        """Build the generation prompt and open the prompt editor popup."""
        if self._proc_running:
            self._proc_status_var.set("⚠ Another process is running — click ↺ Reset if it's stuck")
            return

        from r4v.storage import load_json as _lj
        t_path = DATA_DIR / "transcripts" / f"{video_id}.json"
        t_data = _lj(t_path)
        if not t_data:
            messagebox.showwarning(
                "No transcript",
                f"No transcript cached for {video_id}.\n\nRun 'Fetch Transcripts' first.",
            )
            return

        try:
            from r4v.content_gen import build_prompt
            video = self._video_map.get(video_id, {})
            prompt = build_prompt(
                transcript_text=t_data["text"],
                existing_title=video.get("title", ""),
                existing_description=video.get("description", ""),
            )
        except Exception as e:
            messagebox.showerror("Prompt build error", str(e))
            return

        self._show_prompt_editor(video_id, field, prop_w, kind, btn, prompt, t_data)

    def _show_prompt_editor(self, video_id: str, field: str, prop_w, kind: str,
                             btn: tk.Button, prompt: str, t_data: dict):
        """Open an editable prompt popup. On Send → call Gemini in a background thread."""
        win = tk.Toplevel(self.root)
        win.title(f"Prompt Editor — {field.upper()} | {video_id}")
        win.configure(bg=CLR_BG)
        win.geometry("920x660")
        win.update_idletasks()
        cx = (win.winfo_screenwidth() - 920) // 2
        cy = (win.winfo_screenheight() - 660) // 2
        win.geometry(f"920x660+{cx}+{cy}")
        win.lift()
        win.focus_force()

        hdr = tk.Frame(win, bg=CLR_PANEL, pady=6)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"  Prompt for: {field.upper()}  |  {video_id}",
                 bg=CLR_PANEL, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 10, "bold")).pack(side="left")
        tk.Label(hdr, text="System prompt → 🎭 Personality button  ",
                 bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 8)).pack(side="right")

        txt_frame = tk.Frame(win, bg=CLR_BG)
        txt_frame.pack(fill="both", expand=True, padx=8, pady=4)

        prompt_txt = tk.Text(
            txt_frame, bg="#111128", fg=CLR_TEXT,
            font=(FONT_MONO, 9), wrap="word",
            insertbackground=CLR_TEXT, relief="flat",
        )
        sb = ttk.Scrollbar(txt_frame, command=prompt_txt.yview)
        prompt_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        prompt_txt.pack(fill="both", expand=True)
        prompt_txt.insert("1.0", prompt)
        prompt_txt.focus_set()

        footer = tk.Frame(win, bg=CLR_PANEL, pady=6)
        footer.pack(fill="x", padx=8)
        status_lbl = tk.Label(footer, text="Edit if needed, then click Send to Gemini.",
                               bg=CLR_PANEL, fg=CLR_MUTED,
                               font=(FONT_MONO, 8), anchor="w")
        status_lbl.pack(side="left", fill="x", expand=True)

        cancel_btn = tk.Button(footer, text="Cancel",
                               bg=CLR_BTN_BG, fg=CLR_TEXT,
                               font=(FONT_FAMILY, 9), relief="flat",
                               padx=12, pady=4, cursor="hand2",
                               command=win.destroy)
        cancel_btn.pack(side="right", padx=(4, 0))

        send_btn = tk.Button(footer, text="⚡  Send to Gemini",
                              bg=CLR_APPROVE, fg="#000000",
                              font=(FONT_FAMILY, 9, "bold"), relief="flat",
                              padx=12, pady=4, cursor="hand2")
        send_btn.pack(side="right", padx=(4, 0))
        Tooltip(send_btn, "Send the (edited) prompt to Gemini and update the field")

        def _send():
            edited = prompt_txt.get("1.0", "end-1c")
            send_btn.config(state="disabled", text="Sending…")
            cancel_btn.config(state="disabled")
            prompt_txt.config(state="disabled")
            status_lbl.config(text="Calling Gemini… (5–15 seconds)")
            self._proc_running = True
            btn.config(state="disabled", text="…")
            for b in (v for v in self._proc_buttons.values() if v is not None):
                b.config(state="disabled")
            self._proc_progbar.start(12)
            self._proc_status_var.set(f"Generating {field} for {video_id[:14]}…")

            def _worker():
                try:
                    from r4v.content_gen import generate_metadata
                    video = self._video_map.get(video_id, {})
                    result = generate_metadata(
                        video_id=video_id,
                        transcript_text=t_data["text"],
                        existing_title=video.get("title", ""),
                        existing_description=video.get("description", ""),
                        transcript_urls=t_data.get("urls", []),
                        force=True,
                        prompt_override=edited,
                    )
                    new_val = result.get(field, "")
                    if field == "tags" and isinstance(new_val, list):
                        new_val = tags_to_str(new_val)
                    self._proc_q.put(("field_done", (btn, "\u26a1", prop_w, kind, new_val, None, win)))
                except Exception as e:
                    self._proc_q.put(("field_done", (btn, "\u26a1", None, None, None, str(e), win)))

            threading.Thread(target=_worker, daemon=True).start()

        send_btn.config(command=_send)

    def _edit_personalities(self):
        """Open config/personalities.json in an editable popup."""
        prof_path = PROJECT_ROOT / "config" / "personalities.json"
        try:
            content = prof_path.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", f"Could not read personalities.json:\n{e}")
            return

        win = tk.Toplevel(self.root)
        win.title("Personality Profile — config/personalities.json")
        win.configure(bg=CLR_BG)
        win.geometry("880x700")
        win.update_idletasks()
        cx = (win.winfo_screenwidth() - 880) // 2
        cy = (win.winfo_screenheight() - 700) // 2
        win.geometry(f"880x700+{cx}+{cy}")
        win.lift()
        win.focus_force()

        tk.Label(win, text="  config/personalities.json  —  JT voice profile & sample phrases",
                 bg=CLR_PANEL, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 10, "bold"), pady=8).pack(fill="x")
        tk.Label(win, text="  Changes take effect on the next ⚡ generation — no restart needed",
                 bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 8), pady=2).pack(fill="x")

        txt_frame = tk.Frame(win, bg=CLR_BG)
        txt_frame.pack(fill="both", expand=True, padx=8, pady=4)

        editor = tk.Text(txt_frame, bg="#111128", fg=CLR_TEXT,
                          font=(FONT_MONO, 9), wrap="none",
                          insertbackground=CLR_TEXT, relief="flat", tabs="    ")
        sb_y = ttk.Scrollbar(txt_frame, command=editor.yview)
        sb_x = ttk.Scrollbar(txt_frame, orient="horizontal", command=editor.xview)
        editor.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side="right", fill="y")
        sb_x.pack(side="bottom", fill="x")
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", content)
        editor.focus_set()

        footer = tk.Frame(win, bg=CLR_PANEL, pady=6)
        footer.pack(fill="x", padx=8)
        status_lbl = tk.Label(footer, text="", bg=CLR_PANEL, fg=CLR_MUTED,
                               font=(FONT_MONO, 8), anchor="w")
        status_lbl.pack(side="left", fill="x", expand=True)

        def _save():
            text = editor.get("1.0", "end-1c")
            try:
                json.loads(text)
            except json.JSONDecodeError as e:
                status_lbl.config(text=f"⚠ Invalid JSON: {e}", fg=CLR_SKIP)
                return
            try:
                prof_path.write_text(text, encoding="utf-8")
                status_lbl.config(text="✓ Saved — takes effect on next ⚡", fg=CLR_APPROVE)
            except Exception as e:
                status_lbl.config(text=f"⚠ Save error: {e}", fg=CLR_SKIP)

        tk.Button(footer, text="Close", command=win.destroy,
                  bg=CLR_BTN_BG, fg=CLR_TEXT,
                  font=(FONT_FAMILY, 9), relief="flat", padx=12, pady=4,
                  cursor="hand2").pack(side="right", padx=(4, 0))
        tk.Button(footer, text="💾  Save",
                  bg=CLR_APPROVE, fg="#000000",
                  font=(FONT_FAMILY, 9, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=_save).pack(side="right", padx=(4, 0))

    def _reset_proc(self):
        """Force-reset the process-running flag — use when ⚡ or a button does nothing."""
        self._proc_progbar.stop()
        self._proc_running = False
        for b in (v for v in self._proc_buttons.values() if v is not None):
            b.config(state="normal")
        if self._proc_current_btn:
            try:
                self._proc_current_btn.config(text=self._proc_current_label)
            except Exception:
                pass
            self._proc_current_btn = None
        self._proc_status_var.set("↺ Reset — ready")

    # ── Push to YouTube ───────────────────────────────────────────────────────

    def _push_approved(self):
        approved = [
            vid for vid, m in self._metadata.items() if m.get("approved") is True
        ]
        if not approved:
            messagebox.showinfo("Nothing to push", "No videos are marked Approved yet.")
            return

        confirm = messagebox.askyesno(
            "Push to YouTube?",
            f"Push metadata updates for {len(approved)} approved video(s) to YouTube?\n\n"
            "This will call  python cli.py push  in a terminal window.",
        )
        if not confirm:
            return

        cli = PROJECT_ROOT / "cli.py"
        python = self._find_python()
        cmd = [python, str(cli), "push"]
        try:
            subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            messagebox.showinfo(
                "Push started",
                "cli.py push is running in a new terminal window.\n"
                "Check that window for progress.",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch cli.py push:\n{e}")

    def _show_help(self):
        win = tk.Toplevel(self.root)
        win.title("R4V Review — Help")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("660x600")
        win.update_idletasks()
        x = (win.winfo_screenwidth() - 660) // 2
        y = (win.winfo_screenheight() - 600) // 2
        win.geometry(f"660x600+{x}+{y}")

        tk.Label(win, text="How to use R4V Review", bg=CLR_BG, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 14, "bold"), pady=12).pack()

        help_text = (
            "WORKFLOW\n"
            "1. Each card is one YouTube Short.\n"
            "2. Click  ▶ Watch  to open the video on YouTube.\n"
            "3. Left column (dark) = Current data cached from YouTube.\n"
            "   Run  Fetch Descs  to populate descriptions in the left pane.\n"
            "4. Right column (green) = AI-proposed metadata. Edit freely before approving.\n"
            "5. Click  ✓ Approve  to queue a video. Auto-advances to the next card.\n"
            "6. Click  ✗ Skip  to leave that video unchanged on YouTube.\n"
            "7. When ready, click  Push Approved → YouTube  in the action bar.\n"
            "\n"
            "ACTION BAR (second row)\n"
            "  Pipeline ▸      Discover + generate AI for new videos — live progress window.\n"
            "  Fetch Descs     Download current descriptions from YouTube into left pane.\n"
            "  Transcripts     Fetch auto-captions (may be IP-blocked; retry in 2-4 h).\n"
            "  Push Approved   Send all Approved metadata to YouTube Data API.\n"
            "  Engage          Like + comment on Approved videos as @roll4veterans.\n"
            "  🎭 Personality  Edit JT's voice profile (personalities.json).\n"
            "\n"
            "MORE ▼ MENU\n"
            "  Push Dry-Run / Engage Dry-Run — preview changes with no API calls.\n"
            "  Check Quota — show today's YouTube API quota usage (10k units/day).\n"
            "  Reload data — re-read all JSON files from disk.\n"
            "  ↺ Reset process — unstick a frozen process button or ⚡ button.\n"
            "\n"
            "FIELD BUTTONS\n"
            "  ⚡  Regenerate just that field via Gemini AI (opens prompt editor).\n"
            "  🔗  Apply the canonical footer links + hashtags to the description.\n"
            "  »   Copy the current YouTube value into the Proposed field.\n"
            "\n"
            "KEYBOARD\n"
            "  ← / →  Navigate between videos (when focus is not in a text field).\n"
            "\n"
            "PUSHING\n"
            "  Push requires YouTube OAuth with etracyjob@gmail.com.\n"
            "  Run  python cli.py push  once manually to trigger the OAuth browser flow\n"
            "  if token.json is missing — afterwards pushes are automatic."
        )

        txt = tk.Text(win, bg=CLR_PANEL, fg=CLR_TEXT, font=(FONT_FAMILY, 10),
                      padx=16, pady=12, relief="flat", wrap="word")
        txt.insert("1.0", help_text)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        tk.Button(win, text="Close", command=win.destroy,
                  bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 10),
                  relief="flat", padx=20, pady=6, cursor="hand2").pack(pady=8)

    def _find_python(self) -> str:
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    # ── Bottom process bar ────────────────────────────────────────────────────

    def _build_bottom_bar(self):
        self._proc_q: queue.Queue = queue.Queue()
        self._proc_running = False
        # _proc_buttons is already initialised in __init__; populated by _build_ui
        self._proc_current_btn = None
        self._proc_current_label = ""
        self._proc_auto_reload = False

        # ── Status bar — very bottom ──────────────────────────────────────────
        status_bar = tk.Frame(self.root, bg=CLR_PANEL)
        status_bar.pack(fill="x", side="bottom")
        tk.Frame(status_bar, bg=CLR_BORDER, height=1).pack(fill="x")
        self._status_bar_var = tk.StringVar(value="Loading…")
        tk.Label(
            status_bar, textvariable=self._status_bar_var,
            bg=CLR_PANEL, fg=CLR_MUTED,
            font=(FONT_FAMILY, 9), anchor="w", padx=12, pady=2,
        ).pack(fill="x")

        # ── Process bar — above status bar ───────────────────────────────────
        proc_bar = tk.Frame(self.root, bg=CLR_PANEL)
        proc_bar.pack(fill="x", side="bottom")
        tk.Frame(proc_bar, bg=CLR_BORDER, height=1).pack(fill="x")

        proc_row = tk.Frame(proc_bar, bg=CLR_PANEL, pady=3)
        proc_row.pack(fill="x", padx=10)

        self._proc_progbar = ttk.Progressbar(proc_row, mode="indeterminate", length=180)
        self._proc_progbar.pack(side="left", padx=(0, 10))

        self._proc_status_var = tk.StringVar(value="Ready")
        tk.Label(
            proc_row, textvariable=self._proc_status_var,
            bg=CLR_PANEL, fg=CLR_MUTED,
            font=(FONT_MONO, 8), anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.root.after(100, self._poll_proc_q)

    def _run_cli(self, label: str, args: list, btn, auto_reload: bool = False):
        if self._proc_running:
            return

        self._proc_running = True
        self._proc_auto_reload = auto_reload
        self._proc_current_btn = btn
        self._proc_current_label = label

        for b in (v for v in self._proc_buttons.values() if v is not None):
            b.config(state="disabled")
        if btn is not None:
            btn.config(text=f"{label}…")
        self._proc_progbar.start(12)
        self._proc_status_var.set(f"Starting: {label}")

        python = self._find_python()
        cmd = [python, "-u", str(PROJECT_ROOT / args[0])] + args[1:]

        def _worker():
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(PROJECT_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        self._proc_q.put(("line", line))
                proc.wait()
                self._proc_q.put(("done", proc.returncode))
            except Exception as e:
                self._proc_q.put(("error", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_proc_q(self):
        try:
            while True:
                item = self._proc_q.get_nowait()
                kind = item[0]
                if kind == "line":
                    self._proc_status_var.set(item[1][:180])
                elif kind == "field_done":
                    _tup = item[1]
                    _btn, _lbl, _pw, _fkind, _val, _err = _tup[:6]
                    _popup = _tup[6] if len(_tup) > 6 else None
                    self._proc_progbar.stop()
                    self._proc_running = False
                    for b in (v for v in self._proc_buttons.values() if v is not None):
                        b.config(state="normal")
                    _btn.config(state="normal", text=_lbl)
                    if _popup:
                        try:
                            _popup.destroy()
                        except Exception:
                            pass
                    if _err:
                        self._proc_status_var.set(f"⚠ Field gen error: {_err[:120]}")
                        messagebox.showerror("Generation Error",
                                             f"Field generation failed:\n\n{_err[:500]}")
                    elif _pw is not None and _val is not None:
                        if _fkind == "multi":
                            _pw.delete("1.0", "end")
                            _pw.insert("1.0", _val)
                        else:
                            _pw.delete(0, "end")
                            _pw.insert(0, _val)
                        self._proc_status_var.set("✓ Field regenerated")
                elif kind in ("done", "error"):
                    self._proc_progbar.stop()
                    self._proc_running = False
                    for b in (v for v in self._proc_buttons.values() if v is not None):
                        b.config(state="normal")
                    if self._proc_current_btn:
                        self._proc_current_btn.config(text=self._proc_current_label)
                    if kind == "done":
                        rc = item[1]
                        suffix = f" (exit {rc})" if rc != 0 else " — done"
                        self._proc_status_var.set(f"{self._proc_current_label}{suffix}")
                        if self._proc_auto_reload and rc == 0:
                            self._load_data()
                    else:
                        self._proc_status_var.set(f"Error: {item[1][:160]}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_proc_q)


# ─────────────────────────────────────────────────────────────────────────────
# Desktop shortcut helper
# ─────────────────────────────────────────────────────────────────────────────

def _create_desktop_shortcut():
    """Create a desktop shortcut for review.pyw (Windows only, runs once)."""
    import os
    desktop = Path(os.environ.get("USERPROFILE", "~")) / "Desktop" / "R4V Review.lnk"
    if desktop.exists():
        return
    pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        return
    review = PROJECT_ROOT / "review.pyw"
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{desktop}'); "
        f"$sc.TargetPath = '{pythonw}'; "
        f"$sc.Arguments = '\"{review}\"'; "
        f"$sc.WorkingDirectory = '{PROJECT_ROOT}'; "
        f"$sc.Description = 'R4V Metadata Review'; "
        f"$sc.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    _create_desktop_shortcut()
    root = tk.Tk()

    # Apply a base ttk theme that plays well with dark overrides
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Dark-theme Combobox styling
    style.configure(
        "TCombobox",
        fieldbackground=CLR_CURRENT,
        background=CLR_BTN_BG,
        foreground=CLR_TEXT,
        selectbackground=CLR_BTN_BG,
        selectforeground=CLR_TEXT,
        arrowcolor=CLR_TEXT,
        bordercolor=CLR_BORDER,
    )
    style.map("TCombobox", fieldbackground=[("readonly", CLR_CURRENT)])
    # Style the dropdown list
    root.option_add("*TCombobox*Listbox.background", CLR_CURRENT)
    root.option_add("*TCombobox*Listbox.foreground", CLR_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", CLR_BTN_BG)
    root.option_add("*TCombobox*Listbox.selectForeground", CLR_TEXT)

    # Hide main window while pipeline runs
    root.withdraw()

    app_container = {}

    def on_pipeline_done():
        root.deiconify()
        app_container["app"] = R4VReviewApp(root)

    def on_pipeline_error(tb: str):
        root.deiconify()
        messagebox.showerror(
            "Pipeline Error",
            f"The pipeline encountered an error:\n\n{tb[:800]}\n\n"
            "The review UI will open with whatever data is available.",
        )
        app_container["app"] = R4VReviewApp(root)

    PipelineSplash(root, on_done=on_pipeline_done, on_error=on_pipeline_error)
    root.mainloop()


if __name__ == "__main__":
    main()
