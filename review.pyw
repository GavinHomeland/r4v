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
TRANSCRIPTS_DIR  = DATA_DIR / "transcripts"
GENERATED_DIR = DATA_DIR / "generated"
APPLIED_DIR = DATA_DIR / "applied"
VIDEOS_JSON = DATA_DIR / "videos.json"
CHECK_STATE_JSON = DATA_DIR / "check_state.json"
UI_PREFS_JSON        = DATA_DIR / "ui_prefs.json"
GLOBAL_AI_NOTES_JSON = DATA_DIR / "global_ai_notes.json"

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

    # Correct stale availability: if a video was pushed through our system it's public,
    # regardless of what videos.json says.  Saves back if anything changed.
    dirty = False
    for v in videos:
        if v.get("availability") in ("unlisted", "private"):
            if (APPLIED_DIR / f"{v['id']}_applied.json").exists():
                v["availability"] = "public"
                dirty = True
    if dirty:
        save_json(VIDEOS_JSON, videos)

    metadata: dict[str, dict] = {}
    if GENERATED_DIR.exists():
        for p in sorted(GENERATED_DIR.glob("*_metadata.json")):
            vid = p.stem.replace("_metadata", "")
            try:
                data = load_json(p)
            except Exception:
                print(f"[data] Skipping malformed metadata file: {p.name}")
                continue
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
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry("+9999+9999")  # render off-screen first to measure
        tk.Label(
            self._tip, text=self._text,
            bg="#2a2a4a", fg="#ffcc44",
            font=(FONT_FAMILY, 11), relief="solid", borderwidth=1,
            padx=10, pady=5, justify="left",
        ).pack()
        self._tip.update_idletasks()
        tw = self._tip.winfo_width()
        th = self._tip.winfo_height()
        sw = self._widget.winfo_screenwidth()
        sh = self._widget.winfo_screenheight()
        wx = self._widget.winfo_rootx()
        wy = self._widget.winfo_rooty()
        wh = self._widget.winfo_height()
        # Prefer below the widget; fall back to above if near bottom
        x = wx + 6
        y = wy + wh + 4
        if y + th > sh - 10:
            y = wy - th - 4
        # Clamp to screen bounds
        if x + tw > sw - 6:
            x = sw - tw - 6
        x = max(x, 0)
        y = max(y, 0)
        self._tip.wm_geometry(f"+{x}+{y}")


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
        videos = discover_videos(CHANNEL_URL, force=True)
        # Merge in unlisted videos via YouTube API (yt-dlp only sees the public channel page)
        try:
            from r4v.auth import get_youtube_service
            from r4v.channel import discover_unlisted_via_api
            videos = discover_unlisted_via_api(get_youtube_service())
            unlisted = sum(1 for v in videos if v.get("availability") == "unlisted")
            progress_q.put(("info", f"Found {len(videos)} videos ({unlisted} unlisted)"))
        except Exception as _e:
            progress_q.put(("info", f"Found {len(videos)} videos (unlisted discovery skipped: {_e})"))
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
        from r4v.storage import load_json as _load_meta_json
        # Skip videos already marked Done in Studio or Approved
        done_ids = set()
        for p in GENERATED_DIR.glob("*_metadata.json"):
            try:
                m = _load_meta_json(p)
                if m and m.get("approved") in (True, "external"):
                    done_ids.add(p.stem.replace("_metadata", ""))
            except Exception:
                pass
        active_videos = [v for v in videos if v["id"] not in done_ids]
        generated = 0
        for i, v in enumerate(active_videos, 1):
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

        skipped_done = len(videos) - len(active_videos)
        if skipped_done:
            progress_q.put(("info", f"Skipped {skipped_done} already-done videos"))
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
            font=(FONT_FAMILY, 16, "bold"),
        ).pack(pady=(20, 4))

        tk.Label(
            self.win,
            text="Discovering videos · fetching transcripts · generating AI metadata",
            bg=CLR_BG, fg=CLR_MUTED,
            font=(FONT_FAMILY, 11),
        ).pack()

        self._step_var = tk.StringVar(value="Starting…")
        tk.Label(
            self.win, textvariable=self._step_var,
            bg=CLR_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 13, "bold"),
        ).pack(pady=(16, 4))

        self._prog = ttk.Progressbar(self.win, mode="indeterminate", length=460)
        self._prog.pack(pady=4)
        self._prog.start(12)

        self._detail_var = tk.StringVar(value="")
        tk.Label(
            self.win, textvariable=self._detail_var,
            bg=CLR_BG, fg=CLR_MUTED,
            font=(FONT_MONO, 10),
            wraplength=500,
        ).pack(pady=4)

        self._info_var = tk.StringVar(value="")
        tk.Label(
            self.win, textvariable=self._info_var,
            bg=CLR_BG, fg=CLR_APPROVE,
            font=(FONT_FAMILY, 11),
        ).pack()

        tk.Button(
            self.win, text="Skip → Load cached data",
            command=self._skip,
            bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 11), relief="flat",
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

        # Remembered geometry for persistent windows
        self._transcript_win_geo: str = ""
        self._gen_this_btn = None  # current card's ↻ Gen All button (set in _build_video_card)

        # Sash position memory — loaded from disk before anything else runs
        self._sash_prefs: dict = (load_json(UI_PREFS_JSON) or {}).get("sashes", {})
        # Bootstrap log (can't use _sash_log yet — method not bound — so write directly)
        try:
            import datetime as _dt2
            _log = DATA_DIR / "sash_debug.log"
            with open(_log, "a", encoding="utf-8") as _f:
                _f.write(f"\n{'='*60}\n{_dt2.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  APP OPEN\n")
                _f.write(f"LOAD from disk: {self._sash_prefs}\n")
        except Exception:
            pass
        self._vpane = None
        self._col_panes: list = []

        self.root.minsize(880, 600)
        self._build_ui()
        self.root.state("zoomed")
        self.root.update_idletasks()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._load_data()
        self.root.after(600, self._check_new_activity)
        self.root.after(1200, self._check_conversation_refresh)
        self.root.after(1800, self._check_personality_refresh)
        self.root.after(3000, self._startup_queue_check)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Row 1: nav toolbar ────────────────────────────────────────────────
        toolbar = tk.Frame(self.root, bg=CLR_PANEL, pady=5)
        toolbar.pack(fill="x", side="top")

        tk.Label(
            toolbar, text="  R4V Metadata Review",
            bg=CLR_PANEL, fg=CLR_HEADER,
            font=(FONT_FAMILY, 15, "bold"),
        ).pack(side="left", padx=10)

        # Filter dropdown
        tk.Label(toolbar, text="Filter:", bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 12)).pack(side="left", padx=(12, 4))

        self._filter_var = tk.StringVar(value="Unlisted")
        filter_menu = ttk.Combobox(
            toolbar, textvariable=self._filter_var,
            values=["All", "Pending", "Approved", "Skipped", "External", "Has Metadata", "No Metadata", "Unlisted", "Private"],
            state="readonly", width=16, font=(FONT_FAMILY, 12),
        )
        filter_menu.pack(side="left")
        Tooltip(filter_menu,
                "Filter the video list:\n"
                "• Unlisted — new videos awaiting push (starts here)\n"
                "• Pending — generated metadata not yet approved\n"
                "• Approved — approved, waiting to be pushed\n"
                "• Skipped — marked skip, excluded from pipeline\n"
                "• External — Done in Studio or already pushed\n"
                "• All — every video on the channel")
        self._filter_var.trace_add("write", lambda *_: self._load_data())

        # Nav controls
        nav_frame = tk.Frame(toolbar, bg=CLR_PANEL)
        nav_frame.pack(side="left", padx=16)

        self._btn_prev = tk.Button(
            nav_frame, text="◀", command=lambda: self._nav(-1),
            bg=CLR_BTN_BG, fg=CLR_MUTED, state="disabled", cursor="arrow",
            font=(FONT_FAMILY, 11, "bold"), relief="flat", padx=8, pady=3,
        )
        self._btn_prev.pack(side="left", padx=2)
        Tooltip(self._btn_prev, "Previous video  (← arrow key)")

        self._nav_var = tk.StringVar(value="0 / 0")
        tk.Label(
            nav_frame, textvariable=self._nav_var,
            bg=CLR_PANEL, fg=CLR_TEXT,
            font=(FONT_FAMILY, 12, "bold"), width=8, anchor="center",
        ).pack(side="left", padx=4)

        self._btn_next = tk.Button(
            nav_frame, text="▶", command=lambda: self._nav(1),
            bg=CLR_BTN_BG, fg=CLR_MUTED, state="disabled", cursor="arrow",
            font=(FONT_FAMILY, 11, "bold"), relief="flat", padx=8, pady=3,
        )
        self._btn_next.pack(side="left", padx=2)
        Tooltip(self._btn_next, "Next video  (→ arrow key)")

        # Title jump dropdown
        self._jump_var = tk.StringVar()
        self._jump_combo = ttk.Combobox(
            nav_frame, textvariable=self._jump_var,
            state="readonly", width=50, font=(FONT_FAMILY, 11),
        )
        self._jump_combo.pack(side="left", padx=8)
        self._jump_combo.bind("<<ComboboxSelected>>", self._on_jump_select)
        Tooltip(self._jump_combo, "Jump directly to any video by title")

        # Title search box
        self._search_var = tk.StringVar()
        tk.Label(nav_frame, text="Search:", bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 11)).pack(side="left", padx=(12, 2))
        _search_entry = tk.Entry(
            nav_frame, textvariable=self._search_var,
            width=22, font=(FONT_FAMILY, 11),
            bg=CLR_BTN_BG, fg=CLR_TEXT, insertbackground=CLR_TEXT,
            relief="flat",
        )
        _search_entry.pack(side="left", padx=(0, 2))
        Tooltip(_search_entry, "Filter list by title — type to narrow, clear to reset")
        _clear_btn = tk.Button(
            nav_frame, text="×", command=lambda: self._search_var.set(""),
            bg=CLR_BTN_BG, fg=CLR_MUTED, relief="flat", padx=4, pady=2, font=(FONT_FAMILY, 11),
        )
        _clear_btn.pack(side="left")
        Tooltip(_clear_btn, "Clear search")
        self._search_var.trace_add("write", lambda *_: self._load_data())

        # More ▼ pulldown menu — sits in nav_frame, right of search bar
        self._more_menu = tk.Menu(
            self.root, tearoff=0,
            bg=CLR_PANEL, fg=CLR_TEXT,
            font=(FONT_FAMILY, 11),
            activebackground=CLR_BTN_BG, activeforeground=CLR_TEXT,
        )
        # Action items moved from action bar
        self._more_menu.add_command(
            label="Pull All \u25b8  \u2014 re-process every video",
            command=lambda: messagebox.askyesno(
                "Pull All — Are you sure?",
                "This re-runs the full pipeline on EVERY video, including ones already approved.\n\n"
                "It will overwrite generated metadata and could take several minutes.\n\n"
                "Are you sure?",
                icon="warning",
            ) and self._open_pipeline_window(pull_all=True),
        )
        self._more_menu.add_command(
            label="Engage (like + comment)",
            command=lambda: self._run_cli("Engage", ["cli.py", "engage"], None, True),
        )
        self._more_menu.add_command(
            label="\U0001f3ad Personalities \u2014 edit JT & Gavin voice profiles",
            command=self._edit_personalities,
        )
        self._more_menu.add_command(
            label="\U0001f310 Global AI Notes \u2014 persistent instructions for every generation",
            command=self._edit_global_ai_notes,
        )
        self._more_menu.add_command(
            label="\U0001f3f7 Tags & Hashtags \u2014 edit for this video",
            command=self._edit_tags_hashtags_dialog,
        )
        self._more_menu.add_command(
            label="\U0001f4dd Notes for AI \u2014 corrections for this video",
            command=self._edit_ai_notes_dialog,
        )
        self._more_menu.add_command(
            label="\U0001f4ac Conversation Refresh",
            command=self._conversation_refresh,
        )
        self._more_menu.add_command(
            label="\u2713 Mark All Done",
            command=self._mark_all_done,
        )
        self._more_menu.add_separator()
        # Pipeline sub-tools
        self._more_menu.add_command(
            label="Fetch Descriptions",
            command=lambda: self._run_cli("Fetch Descs", ["cli.py", "descriptions"],
                                         None, True),
        )
        self._more_menu.add_command(
            label="Transcripts (fetch missing captions)",
            command=lambda: self._run_cli("Transcripts", ["cli.py", "transcripts"],
                                         None, True),
        )
        self._more_menu.add_command(
            label="Find Unlisted (API scan)",
            command=lambda: self._run_cli("Find Unlisted", ["cli.py", "discover-unlisted"],
                                         None, True),
        )
        self._more_menu.add_command(
            label="Generate AI (without full pipeline)",
            command=lambda: self._run_cli("Generate AI", ["cli.py", "generate"],
                                         None, True),
        )
        self._more_menu.add_separator()
        self._more_menu.add_command(
            label="Check Quota",
            command=lambda: self._run_cli("Check Quota", ["cli.py", "quota"], None, False),
        )
        self._more_menu.add_command(
            label="Transcript Log (last 100)",
            command=lambda: self._run_cli("Transcript Log", ["cli.py", "transcript-log", "--tail", "100"], None, False),
        )
        self._more_menu.add_command(
            label="Transcript Log (errors only)",
            command=lambda: self._run_cli("Transcript Log (errors)", ["cli.py", "transcript-log", "--errors"], None, False),
        )
        self._more_menu.add_separator()
        self._more_menu.add_command(label="Reload data", command=self._load_data)
        self._more_menu.add_command(label="\u21ba Reset process bar", command=self._reset_proc)

        more_btn = tk.Button(
            nav_frame, text="More \u25bc",
            bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 11), relief="flat",
            padx=10, pady=4, cursor="hand2",
        )
        more_btn.config(command=lambda b=more_btn: self._more_menu.tk_popup(
            b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
        more_btn.pack(side="left", padx=(8, 2))
        Tooltip(more_btn,
                "Additional operations:\n"
                "• Pull All \u25b8 \u2014 full pipeline for all videos (including completed)\n"
                "• Engage \u2014 like + comment on pushed videos\n"
                "• Personalities \u2014 edit JT & Gavin voice profiles\n"
                "• Conversation Refresh \u2014 generate follow-up comments on recent videos\n"
                "• Mark All Done \u2014 baseline all pending as External\n"
                "• Fetch Descriptions \u2014 download current YouTube description text\n"
                "• Transcripts \u2014 fetch missing captions (may be rate-limited)\n"
                "• Find Unlisted \u2014 API scan for unlisted/private videos\n"
                "• Generate AI \u2014 run AI generation without the full pipeline\n"
                "• Check Quota \u2014 show today's YouTube API quota usage\n"
                "• Transcript Log \u2014 recent transcript fetch history\n"
                "• Reload data \u2014 refresh the video list from disk\n"
                "• Reset process bar \u2014 unstick a frozen button (no files changed)")

        # ── Row 2: action bar — proc+status left, buttons right ───────────────
        self._action_bar = tk.Frame(self.root, bg=CLR_PANEL, pady=2)
        self._action_bar.pack(fill="x", side="top")

        # Left: proc status (progbar + text + stop) over video counts
        _left = tk.Frame(self._action_bar, bg=CLR_PANEL)
        _left.pack(side="left", padx=(10, 20), fill="y", pady=1)

        _proc_row = tk.Frame(_left, bg=CLR_PANEL)
        _proc_row.pack(side="top", anchor="w")
        self._stop_btn = tk.Button(
            _proc_row, text="■ Stop", bg=CLR_SKIP, fg="#000000",
            font=(FONT_FAMILY, 10, "bold"), relief="flat",
            padx=8, pady=1, cursor="hand2",
            command=self._stop_proc, state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._stop_btn, "Stop the currently running task")
        self._proc_progbar = ttk.Progressbar(_proc_row, mode="indeterminate", length=140)
        self._proc_progbar.pack(side="left", padx=(0, 8))
        self._proc_status_var = tk.StringVar(value="Ready")
        tk.Label(_proc_row, textvariable=self._proc_status_var, bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_MONO, 10), anchor="w").pack(side="left")

        _stats_row = tk.Frame(_left, bg=CLR_PANEL)
        _stats_row.pack(side="top", anchor="w")
        self._status_bar_var = tk.StringVar(value="Loading…")
        tk.Label(_stats_row, textvariable=self._status_bar_var, bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 10), anchor="w").pack(side="left")

        def _abtn(text: str, cmd, color: str, tip: str, key: str = None) -> tk.Button:
            fg = "#1e1e2e" if color in (CLR_APPROVE, CLR_SKIP, "#89b4fa", "#f9e2af") else CLR_TEXT
            b = tk.Button(
                self._action_bar, text=text, command=cmd,
                bg=color, fg=fg,
                font=(FONT_FAMILY, 11, "bold"), relief="flat",
                padx=10, pady=5, cursor="hand2",
            )
            Tooltip(b, tip)
            if key:
                self._proc_buttons[key] = b
            return b

        # Pack right-to-left so display order is: + Add Video | Pipeline ▸ | Push → YouTube | ? Help | Exit
        b_exit = _abtn("Exit", self._on_close, CLR_BTN_BG, "Close the review tool")
        b_exit.pack(side="right", padx=(2, 10))

        b_help = _abtn("? Help", self._show_help, "#f9e2af",
                       "Show workflow guide and keyboard shortcuts")
        b_help.pack(side="right", padx=2)

        b_push = _abtn(
            "Push \u2192 YouTube", self._push_approved, "#89b4fa",
            "Push all Approved cards to YouTube: updates title, description, tags,\n"
            "sets visibility to Public, and adds to the R4V playlist.\n"
            "To post likes and comments, use More \u25be \u203a Engage after pushing.",
            "Push Approved",
        )
        b_push.pack(side="right", padx=2)

        b_pipe = _abtn(
            "Pipeline \u25b8", self._open_pipeline_window, "#89b4fa",
            "Run discover \u2192 descriptions \u2192 transcripts \u2192 generate AI\n"
            "Skips videos already Approved or Done in Studio \u2014 new/pending only.\n"
            "Opens a live progress window.",
            "Pipeline \u25b8",
        )
        b_pipe.pack(side="right", padx=2)

        b_addvid = _abtn(
            "+ Add Video",
            self._add_video_dialog,
            CLR_BTN_BG,
            "Paste a YouTube or Studio URL (or bare video ID) to add a draft/unlisted video\n"
            "that wasn't auto-discovered. Fetches metadata from YouTube API.",
        )
        b_addvid.pack(side="right", padx=(10, 2))

        # ── Process + status bars (pack before card so they anchor to bottom) ──
        self._build_bottom_bar()

        # ── Single-card area ──────────────────────────────────────────────────
        self._card_frame = tk.Frame(self.root, bg=CLR_BG)
        self._card_frame.pack(fill="both", expand=True)

        # Keyboard navigation (skip when focus is inside a text-editing widget)
        self.root.bind("<Left>",  self._on_left_key)
        self.root.bind("<Right>", self._on_right_key)


    def _on_close(self):
        """Save sash positions then exit."""
        self._save_sash_prefs()
        self.root.destroy()

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
            font=(FONT_FAMILY, 11, "bold"), relief="flat",
            padx=10, pady=4, cursor="hand2",
        )

    # ── Data loading ──────────────────────────────────────────────────────────

    def _should_show(self, video_id: str) -> bool:
        f = self._filter_var.get()
        meta = self._metadata.get(video_id)
        video = self._video_map.get(video_id, {})

        # Search filter — applied on top of the active filter
        q = self._search_var.get().strip().lower() if hasattr(self, "_search_var") else ""
        if q:
            title = (video.get("title") or (meta.get("existing_title", "") if meta else "") or video_id).lower()
            if q not in title:
                return False

        if f == "All":
            return True
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
        if f == "External":
            return meta is not None and meta.get("approved") == "external"
        if f == "Unlisted":
            return video.get("availability", "") == "unlisted"
        if f == "Private":
            return video.get("availability", "") == "private"
        return True

    def _load_data(self, *_, skip_autosave: bool = False):
        if not skip_autosave:
            self._autosave_current()
        self._videos, self._metadata = load_all_data()
        self._video_map = {v["id"]: v for v in self._videos}

        # Build ordered list: unlisted/private first, then metadata videos, then the rest
        seen: set[str] = set()
        video_ids_all: list[str] = []
        # Unlisted + private first (highest priority — manually added, need attention)
        for v in self._videos:
            if v.get("availability", "") in ("unlisted", "private"):
                video_ids_all.append(v["id"])
                seen.add(v["id"])
        # Then videos with metadata
        for vid in self._metadata:
            if vid not in seen:
                video_ids_all.append(vid)
                seen.add(vid)
        # Then remaining
        for v in self._videos:
            if v["id"] not in seen:
                video_ids_all.append(v["id"])

        self._filtered_ids = [vid for vid in video_ids_all if self._should_show(vid)]

        # Clamp index to valid range
        if self._filtered_ids:
            self._current_index = min(self._current_index, len(self._filtered_ids) - 1)
        else:
            self._current_index = 0

        # Populate jump dropdown (with status icon prefix for at-a-glance color coding)
        jump_titles = []
        for i, vid in enumerate(self._filtered_ids):
            v = self._video_map.get(vid, {})
            meta = self._metadata.get(vid, {})
            title = (v.get("title") or meta.get("existing_title") or vid)[:55]
            icon = self._status_icon(vid)
            jump_titles.append(f"#{i + 1:>3} {icon}{title}")
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
        win.resizable(True, True)
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
            fg=CLR_APPROVE, font=(FONT_FAMILY, 16, "bold"),
        ).pack(anchor="w", padx=28, pady=(16, 2))
        tk.Label(
            win, text=f"Last check: {time_str}", bg=CLR_BG,
            fg=CLR_MUTED, font=(FONT_FAMILY, 11),
        ).pack(anchor="w", padx=28, pady=(0, 10))

        def _row(icon, text, colour):
            tk.Label(
                win, text=f"  {icon}  {text}", bg=CLR_BG,
                fg=colour, font=(FONT_FAMILY, 13), anchor="w",
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
            font=(FONT_FAMILY, 13, "bold"), relief="flat",
            padx=18, pady=6, cursor="hand2", command=_jump,
        ).pack(side="left", padx=8)
        tk.Button(
            btn_row, text="Dismiss", bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 13), relief="flat",
            padx=18, pady=6, cursor="hand2", command=_dismiss,
        ).pack(side="left", padx=8)

        win.protocol("WM_DELETE_WINDOW", _dismiss)

    # ── Personality Refresh notification ─────────────────────────────────────

    def _check_personality_refresh(self):
        """Show a notification if the weekly remote agent updated personalities.json."""
        flag_path  = DATA_DIR / "personality_refresh_flag.json"
        seen_path  = DATA_DIR / "personality_refresh_seen.json"
        if not flag_path.exists():
            return
        flag = load_json(flag_path) or {}
        seen = load_json(seen_path) or {}
        if flag.get("refreshed_at") == seen.get("refreshed_at"):
            return  # already acknowledged

        # Mark seen immediately
        save_json(seen_path, {"refreshed_at": flag.get("refreshed_at", "")})

        win = tk.Toplevel(self.root)
        win.title("Personalities Updated")
        win.configure(bg=CLR_BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self.root.update_idletasks()
        cx = self.root.winfo_x() + self.root.winfo_width()  // 2 - 220
        cy = self.root.winfo_y() + 160
        win.geometry(f"440x180+{max(0,cx)}+{max(0,cy)}")

        tk.Label(win, text="Personality Profiles Updated",
                 bg=CLR_BG, fg=CLR_APPROVE,
                 font=(FONT_FAMILY, 14, "bold")).pack(anchor="w", padx=24, pady=(18, 2))
        tk.Label(win,
                 text="The weekly agent refreshed JT's catchphrases and quotes.\n"
                      "Reload now to use the new profiles for generation.",
                 bg=CLR_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 11),
                 justify="left").pack(anchor="w", padx=24, pady=(4, 12))

        btn_row = tk.Frame(win, bg=CLR_BG)
        btn_row.pack(pady=(0, 16))

        def _reload():
            win.destroy()
            self._load_data()

        tk.Button(btn_row, text="Reload Now", bg=CLR_APPROVE, fg="#000000",
                  font=(FONT_FAMILY, 12, "bold"), relief="flat",
                  padx=16, pady=5, cursor="hand2", command=_reload).pack(side="left", padx=8)
        tk.Button(btn_row, text="Later", bg=CLR_BTN_BG, fg=CLR_TEXT,
                  font=(FONT_FAMILY, 12), relief="flat",
                  padx=16, pady=5, cursor="hand2", command=win.destroy).pack(side="left", padx=8)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    # ── Conversation Refresh ──────────────────────────────────────────────────

    def _check_conversation_refresh(self):
        """On app open, suggest conversation refresh once per day on refresh days (day % 3 == 0)."""
        import datetime as _dt
        from r4v.conversation_refresh import should_suggest_refresh, get_recently_pushed_video_ids
        if not should_suggest_refresh():
            return
        today = _dt.date.today().isoformat()
        prefs = load_json(UI_PREFS_JSON) or {}
        if prefs.get("refresh_suggested_date") == today:
            return
        recent = get_recently_pushed_video_ids(days=15)
        if not recent:
            return
        prefs["refresh_suggested_date"] = today
        save_json(UI_PREFS_JSON, prefs)
        win = tk.Toplevel(self.root)
        win.title("Conversation Refresh")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("420x160")
        win.update_idletasks()
        win.geometry(f"420x160+{(win.winfo_screenwidth()-420)//2}+{(win.winfo_screenheight()-160)//2}")
        win.grab_set()
        tk.Label(win, text="\U0001f4ac  Conversation Refresh", bg=CLR_BG, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 14, "bold")).pack(pady=(16, 4))
        tk.Label(win, text=f"Today is a refresh day. {len(recent)} video(s) posted in the last 15 days.\n"
                           "Generate follow-up comments for a random half?",
                 bg=CLR_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 12), justify="center").pack(pady=(0, 12))
        btn_frame = tk.Frame(win, bg=CLR_BG)
        btn_frame.pack()
        tk.Button(btn_frame, text="Run Refresh", bg="#89b4fa", fg="#1e1e2e",
                  font=(FONT_FAMILY, 12, "bold"), padx=12, relief="flat",
                  command=lambda: [win.destroy(), self._conversation_refresh()]).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Not now", bg=CLR_BTN_BG, fg=CLR_TEXT,
                  font=(FONT_FAMILY, 12), padx=12, relief="flat",
                  command=win.destroy).pack(side="left", padx=6)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def _conversation_refresh(self):
        """Open the conversation refresh workflow dialog."""
        from r4v.conversation_refresh import (
            get_recently_pushed_video_ids, select_refresh_candidates,
            prepare_refresh_batch, post_refresh_comment,
        )
        from r4v.auth import get_youtube_service_jt, get_youtube_service_gavin
        from config.settings import TOKEN_FILE_GAVIN

        recent = get_recently_pushed_video_ids(days=15)
        if not recent:
            messagebox.showinfo("Conversation Refresh", "No videos pushed in the last 15 days.")
            return

        candidates = select_refresh_candidates(recent)
        if not candidates:
            messagebox.showinfo("Conversation Refresh", "No candidates selected.")
            return

        # Show working dialog while fetching/generating
        work_win = tk.Toplevel(self.root)
        work_win.title("Conversation Refresh — Preparing")
        work_win.configure(bg=CLR_BG)
        work_win.geometry("420x120")
        work_win.update_idletasks()
        work_win.geometry(f"420x120+{(work_win.winfo_screenwidth()-420)//2}+{(work_win.winfo_screenheight()-120)//2}")
        work_win.grab_set()
        status_var = tk.StringVar(value=f"Fetching comments for {len(candidates)} video(s)...")
        tk.Label(work_win, textvariable=status_var, bg=CLR_BG, fg=CLR_TEXT,
                 font=(FONT_FAMILY, 12), wraplength=380).pack(pady=(24, 8), padx=12)
        prog = ttk.Progressbar(work_win, mode="indeterminate", length=300)
        prog.pack()
        prog.start(12)
        work_win.update()

        batch = []
        service_jt = None
        service_gavin = None
        error_msg = ""

        try:
            service_jt = get_youtube_service_jt()
            if TOKEN_FILE_GAVIN.exists():
                try:
                    service_gavin = get_youtube_service_gavin()
                except Exception:
                    pass
            def _refresh_progress(cur, tot, text):
                status_var.set(text)
                self._proc_status_var.set(f"Refresh: {text}")
                work_win.update()

            status_var.set(f"Starting — {len(candidates)} video(s)...")
            work_win.update()
            batch = prepare_refresh_batch(service_jt, candidates,
                                          progress_callback=_refresh_progress)
        except Exception as e:
            error_msg = str(e)
        finally:
            prog.stop()
            work_win.destroy()
            self._proc_status_var.set("")

        if error_msg:
            messagebox.showerror("Conversation Refresh", f"Error: {error_msg}")
            return
        if not batch:
            messagebox.showinfo("Conversation Refresh",
                                "No follow-up comments generated\n(all videos may have comments disabled).")
            return

        # Present each video for review one at a time
        self._show_refresh_review(batch, service_jt, service_gavin)

    def _show_refresh_review(self, batch: list, service_jt, service_gavin):
        """Present refresh comments one at a time for edit/approve/skip, then post all at once."""
        approved_items = []
        idx_var = [0]
        total = len(batch)

        win = tk.Toplevel(self.root)
        win.title(f"Conversation Refresh — Review (0/{total})")
        win.configure(bg=CLR_BG)
        win.geometry("640x560")
        win.update_idletasks()
        win.geometry(f"640x560+{(win.winfo_screenwidth()-640)//2}+{(win.winfo_screenheight()-560)//2}")
        win.grab_set()

        # Header
        hdr_var = tk.StringVar()
        tk.Label(win, textvariable=hdr_var, bg=CLR_BG, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 13, "bold")).pack(pady=(12, 0), padx=12, anchor="w")

        responder_var = tk.StringVar()
        progress_var = tk.StringVar(value="")

        # Bottom section — pack before existing_txt so it anchors to the bottom
        btn_frame = tk.Frame(win, bg=CLR_BG)
        btn_frame.pack(side="bottom", pady=12)

        _info_row = tk.Frame(win, bg=CLR_BG)
        _info_row.pack(side="bottom", fill="x", padx=12, pady=(0, 4))
        responder_lbl = tk.Label(_info_row, textvariable=responder_var, bg=CLR_BG, fg=CLR_MUTED,
                                 font=(FONT_FAMILY, 11))
        responder_lbl.pack(side="left")
        tk.Label(_info_row, textvariable=progress_var, bg=CLR_BG, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 10)).pack(side="left", padx=(16, 0))

        proposed_txt = tk.Text(win, bg="#0d1f30", fg=CLR_TEXT, height=10,
                               font=(FONT_MONO, 11), relief="flat", wrap="word",
                               insertbackground=CLR_TEXT)
        proposed_txt.pack(side="bottom", fill="x", padx=12)

        tk.Label(win, text="Generated follow-up (edit before approving):",
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 11, "bold")).pack(
                     side="bottom", pady=(8, 2), padx=12, anchor="w")

        # Existing comments — fills all remaining space
        tk.Label(win, text="Recent comments:", bg=CLR_BG, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 11, "bold")).pack(pady=(8, 2), padx=12, anchor="w")
        existing_txt = tk.Text(win, bg="#111128", fg="#aaa",
                               font=(FONT_MONO, 11), relief="flat", wrap="word", state="disabled")
        existing_txt.pack(fill="both", expand=True, padx=12)
        existing_txt.tag_config("gavin",   foreground="#a6e3a1")
        existing_txt.tag_config("jt",      foreground="#62ddff")
        existing_txt.tag_config("janelle", foreground="#cba6f7")
        existing_txt.tag_config("rstracy", foreground="#fab387")
        existing_txt.tag_config("target",  foreground="#ffffff", background="#2a1f00")

        def _load_item(i: int):
            item = batch[i]
            win.title(f"Conversation Refresh — Review ({i+1}/{total})")
            hdr_var.set(f"{i+1}/{total}  \u2014  {item['title'][:60]}")
            is_gavin = item["responder"] == "gavin"
            responder_var.set(
                f"Replying as: {'@erictracy5584 (Gavin)' if is_gavin else '@roll4veterans (JT)'}"
            )
            responder_lbl.config(fg="#a6e3a1" if is_gavin else "#62ddff")
            existing_txt.config(state="normal")
            existing_txt.delete("1.0", "end")
            target_tid = item.get("reply_to_thread_id")
            for c in reversed(item["existing_comments"]):
                author = c["author"]
                is_target = c.get("thread_id") == target_tid
                tag = ("target" if is_target
                       else "gavin"   if "erictracy" in author.lower()
                       else "jt"      if "roll4veterans" in author.lower()
                       else "janelle" if "janellerhea" in author.lower()
                       else "rstracy" if "rstracy" in author.lower()
                       else None)
                display_author = "Gavin" if "erictracy" in author.lower() else author
                prefix = "↳ replying to → " if is_target else ""
                line = f"{prefix}{display_author}:\n  {c['text']}\n\n"
                existing_txt.insert("end", line, tag or "")
            existing_txt.config(state="disabled")
            proposed_txt.delete("1.0", "end")
            proposed_txt.insert("1.0", item["generated_comment"])
            approved_count = len(approved_items)
            progress_var.set(f"{approved_count} approved so far")

        def _approve():
            item = batch[idx_var[0]]
            text = proposed_txt.get("1.0", "end-1c").strip()
            if text:
                approved_items.append({**item, "final_comment": text})
            _advance()

        def _skip():
            _advance()

        def _advance():
            idx_var[0] += 1
            if idx_var[0] >= total:
                win.destroy()
                _post_all()
            else:
                _load_item(idx_var[0])

        tk.Button(btn_frame, text="\u2713 Approve & Next",
                  bg=CLR_APPROVE, fg="#1e1e2e",
                  font=(FONT_FAMILY, 12, "bold"), padx=14, relief="flat",
                  command=_approve).pack(side="left", padx=6)
        tk.Button(btn_frame, text="[skip]",
                  bg=CLR_BTN_BG, fg=CLR_MUTED,
                  font=(FONT_FAMILY, 12), padx=10, relief="flat",
                  command=_skip).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel all",
                  bg=CLR_BTN_BG, fg=CLR_SKIP,
                  font=(FONT_FAMILY, 12), padx=10, relief="flat",
                  command=win.destroy).pack(side="left", padx=6)

        _load_item(0)

        def _post_all():
            if not approved_items:
                messagebox.showinfo("Conversation Refresh", "No comments were approved — nothing posted.")
                return
            confirm = messagebox.askyesno(
                "Post refresh comments?",
                f"Post {len(approved_items)} follow-up comment(s) to YouTube now?",
            )
            if not confirm:
                return
            posted = 0
            # thread_id from a just-posted JT comment, keyed by video_id,
            # so a pending Gavin reply can be chained to it
            pending_threads: dict = {}
            for item in approved_items:
                tid = item.get("reply_to_thread_id", "")
                if item.get("reply_to_jt_pending"):
                    tid = pending_threads.get(item["video_id"], "")
                result = post_refresh_comment(
                    service_jt, service_gavin,
                    item["video_id"], item["final_comment"],
                    item["responder"],
                    reply_to_thread_id=tid,
                    dry_run=False,
                )
                if result is not None:
                    posted += 1
                    if item.get("pair_with_next"):
                        pending_threads[item["video_id"]] = result
            messagebox.showinfo("Conversation Refresh", f"Posted {posted}/{len(approved_items)} comment(s).")

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

        # Pull hashtags from meta (Tags & Hashtags dialog saves there directly)
        hashtags = (self._metadata.get(video_id) or {}).get("hashtags", "")

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
                bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 14),
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

    def _open_pipeline_window(self, pull_all: bool = False, skip_discover: bool = False, video_ids: list[str] | None = None):
        """Open a dedicated progress window and run cli.py pipeline [--all]."""
        if self._proc_running:
            messagebox.showwarning("Busy", "Another process is already running.\nUse ↺ Reset (More ▼) if it is stuck.")
            return

        # Mark busy and disable all registered proc buttons
        self._proc_running = True
        for b in (v for v in self._proc_buttons.values() if v is not None):
            b.config(state="disabled")
        self._proc_progbar.start(12)
        if video_ids:
            label = f"{len(video_ids)} video(s)"
        elif pull_all:
            label = "ALL videos"
        else:
            label = "new/pending only"
        self._proc_status_var.set(f"Pipeline: {label}…")

        # Build progress window
        win = tk.Toplevel(self.root)
        win.title(f"R4V — Pipeline ({label})")
        win.configure(bg=CLR_BG)
        win.geometry("620x440")
        win.update_idletasks()
        cx = (win.winfo_screenwidth() - 620) // 2
        cy = (win.winfo_screenheight() - 440) // 2
        win.geometry(f"620x440+{cx}+{cy}")
        win.lift()

        tk.Label(win, text=f"R4V Pipeline — {label.title()}",
                 bg=CLR_BG, fg=CLR_HEADER,
                 font=(FONT_FAMILY, 15, "bold")).pack(pady=(16, 2))
        steps_text = ("transcripts  ·  generate AI metadata" if (skip_discover or video_ids)
                      else "discover  ·  transcripts (cached)  ·  generate AI metadata")
        tk.Label(win, text=steps_text,
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 11)).pack()

        log_frame = tk.Frame(win, bg=CLR_BG)
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)

        log_txt = tk.Text(log_frame, bg="#111128", fg=CLR_TEXT,
                          font=(FONT_MONO, 11), relief="flat", wrap="word",
                          state="disabled", height=14)
        sb = ttk.Scrollbar(log_frame, command=log_txt.yview)
        log_txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        log_txt.pack(fill="both", expand=True)

        status_var = tk.StringVar(value="Starting…")
        tk.Label(win, textvariable=status_var,
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_MONO, 10),
                 anchor="w", wraplength=580).pack(fill="x", padx=12)

        close_btn = tk.Button(win, text="Close when done",
                               bg=CLR_BTN_BG, fg=CLR_TEXT,
                               font=(FONT_FAMILY, 11), relief="flat",
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
            cmd = [python, "-u", str(PROJECT_ROOT / "cli.py"), "pipeline"]
            if pull_all:
                cmd.append("--all")
            if skip_discover and not video_ids:
                cmd.append("--skip-discover")
            for vid in (video_ids or []):
                cmd += ["--video-id", vid]
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
            self._clean_pending_queue()
            self._schedule_auto_check()  # start 30-min retry if videos still pending
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
            if field == "_cur_description":
                # Editable current description — save back to videos.json
                video = self._video_map.get(video_id, {})
                video["description"] = w.get("1.0", "end-1c")
                continue
            if isinstance(w, tk.Text):
                meta[field] = w.get("1.0", "end-1c")
            elif isinstance(w, tk.Entry):
                meta[field] = w.get()
        if "tags" in meta and isinstance(meta["tags"], str):
            meta["tags"] = str_to_tags(meta["tags"])
        # Keep comment_jt in sync with comment (backward compat alias)
        if "comment" in meta:
            meta["comment_jt"] = meta["comment"]
        save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)
        # If the editable current description changed, persist to videos.json too
        if "_cur_description" in widgets:
            save_json(VIDEOS_JSON, self._videos)

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
        is_locked = (approval is True or approval == "external")

        # ── Card frame fills the remaining window area ─────────────────────────
        card = tk.Frame(self._card_frame, bg=CLR_PANEL, pady=8, padx=12)
        card.pack(fill="both", expand=True, padx=8, pady=6)

        # Colored status stripe at top of card
        stripe_clr = self._status_stripe_color(has_meta, approval)
        tk.Frame(card, bg=stripe_clr, height=4).pack(fill="x", pady=(0, 6))

        # ── Header row ────────────────────────────────────────────────────────
        hdr = tk.Frame(card, bg=CLR_PANEL)
        hdr.pack(fill="x")

        status_var = tk.StringVar(value=self._approval_label(approval))
        self._status_vars[video_id] = status_var

        tk.Label(
            hdr, textvariable=status_var,
            bg=CLR_PANEL, fg=self._approval_color(approval),
            font=(FONT_FAMILY, 12, "bold"), width=12, anchor="w",
        ).pack(side="left")

        # Video ID badge
        tk.Label(
            hdr, text=f"#{idx + 1}  {video_id}",
            bg=CLR_PANEL, fg=CLR_MUTED, font=(FONT_MONO, 11),
        ).pack(side="left", padx=(0, 12))

        has_notes = bool(meta and meta.get("ai_notes", "").strip())
        if has_notes:
            dot = tk.Label(hdr, text="●", bg=CLR_PANEL, fg="#cc4444",
                           font=(FONT_FAMILY, 11), cursor="hand2")
            dot.pack(side="left", padx=(0, 4))
            Tooltip(dot, "AI Notes active — click to edit")
            dot.bind("<Button-1>", lambda e: self._edit_ai_notes_dialog())

        tk.Label(
            hdr, text=existing_title or video_id,
            bg=CLR_PANEL, fg=CLR_TEXT,
            font=(FONT_FAMILY, 13, "bold"), anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Clickable link
        link = tk.Label(hdr, text="▶ Watch", bg=CLR_PANEL, fg=CLR_LINK,
                        font=(FONT_FAMILY, 12, "underline"), cursor="hand2")
        link.pack(side="left", padx=8)
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        # Action buttons
        btn_row = tk.Frame(hdr, bg=CLR_PANEL)
        btn_row.pack(side="left")

        if approval is True:
            _approve_btn = self._make_btn(btn_row, "↩ Unapprove",
                           lambda vid=video_id: self._unapprove(vid), CLR_MUTED)
            Tooltip(_approve_btn, "Remove Approved status — unlocks all fields for editing")
        elif approval == "external":
            _approve_btn = self._make_btn(btn_row, "↩ Back to Pending",
                           lambda vid=video_id: self._unapprove(vid), CLR_MUTED)
            Tooltip(_approve_btn, "Clear \'Done in Studio\' mark — returns card to Pending for editing")
        else:
            _approve_btn = self._make_btn(btn_row, "✓ Approve",
                           lambda vid=video_id: self._set_approval(vid, True), CLR_APPROVE)
            Tooltip(_approve_btn, "Mark as Approved — saves edits and queues for Push to YouTube\nAuto-advances to the next card")
        _approve_btn.pack(side="left", padx=2)

        if not is_locked:
            _ext_btn = self._make_btn(btn_row, "⚙ Done in Studio",
                           lambda vid=video_id: self._set_approval(vid, "external"), "#5577aa")
            _ext_btn.pack(side="left", padx=(4, 2))
            Tooltip(_ext_btn, "Mark as already edited in YouTube Studio — hides from Pending,\nskipped by Push (won\'t overwrite your manual edits)")

        _gen_btn = self._make_btn(btn_row, "↻ Gen All",
                       lambda vid=video_id: self._generate_this(vid), "#a8a8c8")
        _gen_btn.pack(side="left", padx=(6, 2))
        if is_locked:
            _gen_btn.config(state="disabled")
        self._gen_this_btn = _gen_btn  # kept current so _generate_this can disable it
        Tooltip(_gen_btn, "Re-run Gemini AI for ALL fields of this video\nReloads the card when done  (disabled while Approved/External)")

        _txn_btn = self._make_btn(btn_row, "📄 Transcript",
                       lambda vid=video_id: self._show_transcript(vid), "#7a7a9a")
        _txn_btn.pack(side="left", padx=(6, 2))
        Tooltip(_txn_btn, "View the raw cached transcript for this video (read-only)")

        if not has_meta:
            tk.Label(
                card,
                text="  (no generated metadata yet — fetch transcript first, then click  Generate AI  or  ↻ Gen This)",
                bg=CLR_PANEL, fg=CLR_MUTED, font=(FONT_FAMILY, 11, "italic"),
            ).pack(anchor="w", pady=4)
            return

        # ── Fields ────────────────────────────────────────────────────────────
        widgets: dict = {}
        self._widgets[video_id] = widgets

        proposed_title    = meta.get("title", "")
        proposed_desc     = meta.get("description", "")
        proposed_tags     = tags_to_str(meta.get("tags", []))
        proposed_hashtags = meta.get("hashtags", "")

        # TITLE "Current" box shows the video number + ID (title already in header).
        # copy_source is what actually gets copied into the proposed box — for TITLE
        # that's the real YouTube title, not the video-ID badge shown in the box.
        title_id_str = f"#{idx + 1} of {total}   {video_id}"

        # (label, display_in_current, proposed_val, kind, expands, copyable, copy_source)
        fields = [
            ("TITLE",       title_id_str,  proposed_title, "single", False, True, existing_title),
            ("DESCRIPTION", existing_desc, proposed_desc,  "multi",  True,  True, existing_desc),
        ]

        vpane = tk.PanedWindow(card, orient=tk.VERTICAL, sashwidth=5,
                               sashrelief="flat", bg=CLR_BORDER, bd=0)
        vpane.pack(fill="both", expand=True)
        self._vpane = vpane
        self._col_panes = []

        for label, current_val, proposed_val, kind, expands, copyable, copy_source in fields:
            row = tk.Frame(vpane, bg=CLR_PANEL, pady=3)
            vpane.add(row, stretch="always" if expands else "never",
                      minsize=120 if kind == "multi" else 32)

            tk.Label(
                row, text=f"  {label}",
                bg=CLR_PANEL, fg=CLR_MUTED,
                font=(FONT_MONO, 11, "bold"), width=12, anchor="w",
            ).pack(side="left", anchor="n")

            cols = tk.PanedWindow(row, orient=tk.HORIZONTAL, sashwidth=5,
                                  sashrelief="flat", bg=CLR_BORDER, bd=0)
            cols.pack(fill="both" if expands else "x", expand=expands)
            self._col_panes.append(cols)
            left_pane = tk.Frame(cols, bg=CLR_PANEL)
            cols.add(left_pane, stretch="always", minsize=100)

            # Current (read-only)
            cur_frame = tk.LabelFrame(
                left_pane, text="Current", bg=CLR_CURRENT, fg=CLR_TEXT,
                font=(FONT_FAMILY, 10), padx=4, pady=2,
            )
            cur_frame.pack(side="left", fill="both", expand=True)

            if kind == "multi":
                cur_w = tk.Text(
                    cur_frame, height=2, wrap="word",
                    bg=CLR_CURRENT, fg=CLR_TEXT,
                    font=(FONT_MONO, 11), relief="flat",
                )
                cur_w.pack(fill="both", expand=True)
                cur_w.insert("1.0", current_val)
                if label == "DESCRIPTION":
                    widgets["_cur_description"] = cur_w
            else:
                cur_w = tk.Entry(
                    cur_frame,
                    bg=CLR_CURRENT, fg=CLR_TEXT,
                    font=(FONT_MONO, 11), relief="flat",
                    state="readonly", readonlybackground=CLR_CURRENT,
                )
                cur_w.pack(fill="x")
                cur_w.config(state="normal")
                cur_w.insert(0, current_val)
                cur_w.config(state="readonly")

            # Copy-arrow column (sits on the border between Current and Proposed)
            if copyable:
                copy_col = tk.Frame(left_pane, bg=CLR_PANEL, width=34)
                copy_col.pack(side="left", fill="y")
                copy_col.pack_propagate(False)

            # Proposed (editable — or locked while Approved)
            prop_lbl = "Proposed  (editable)" if not is_locked else "Proposed  (locked)"
            prop_frame = tk.LabelFrame(
                cols, text=prop_lbl,
                bg=CLR_PROPOSED, fg=CLR_APPROVE if not is_locked else CLR_MUTED,
                font=(FONT_FAMILY, 10), padx=4, pady=2,
            )
            cols.add(prop_frame, stretch="always", minsize=100)

            # ⚡ per-field AI gen button — packed first so it anchors top-right
            field_key = label.lower()
            gen_field_btn = tk.Button(
                prop_frame, text="\u26a1",
                bg=CLR_PROPOSED, fg="#ffcc44",
                font=(FONT_MONO, 10), relief="flat",
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
                    font=(FONT_MONO, 10), relief="flat",
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
                    font=(FONT_MONO, 11), relief="flat", insertbackground=CLR_TEXT,
                )
                prop_w.pack(fill="both", expand=True)
                prop_w.insert("1.0", proposed_val)
                if is_locked:
                    prop_w.config(state="disabled")
            else:
                prop_w = tk.Entry(
                    prop_frame,
                    bg=CLR_PROPOSED, fg=CLR_TEXT,
                    font=(FONT_MONO, 11), relief="flat", insertbackground=CLR_TEXT,
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
                    font=(FONT_MONO, 13, "bold"), relief="flat",
                    cursor="hand2", command=_make_copy,
                    padx=0, pady=0,
                )
                _copy_btn.pack(expand=True)
                tip_src = "existing YouTube title" if label == "TITLE" else f"current YouTube {label.lower()}"
                Tooltip(_copy_btn, f"Copy {tip_src} into the Proposed field\n(overwrites AI-generated text)")
                if is_locked:
                    _copy_btn.config(state="disabled")

            widgets[label.lower()] = prop_w

        # Restore sash positions — two passes: 50ms for layout to settle, 150ms to confirm
        vpane.after(50, self._restore_sash_prefs)
        vpane.after(150, self._restore_sash_prefs)

        # ── Comment rows (full-width, no Current pane) ───────────────────────
        def _comment_row(parent, label_text, meta_key, fg_color, field_key, tooltip_text):
            row = tk.Frame(parent, bg=CLR_PANEL, pady=2)
            row.pack(fill="x")
            tk.Label(
                row, text=f"  {label_text}",
                bg=CLR_PANEL, fg=fg_color,
                font=(FONT_MONO, 11, "bold"), width=12, anchor="w",
            ).pack(side="left")
            lbl_txt = f"{tooltip_text} (editable)" if not is_locked else f"{tooltip_text} (locked)"
            frame = tk.LabelFrame(row, text=lbl_txt, bg="#0d1f30", fg=fg_color,
                                  font=(FONT_FAMILY, 10), padx=4, pady=2)
            frame.pack(side="left", fill="x", expand=True)
            w = tk.Text(frame, bg="#0d1f30", fg=CLR_TEXT,
                        font=(FONT_MONO, 11), relief="flat", insertbackground=CLR_TEXT,
                        height=4, wrap="word")
            w.pack(fill="x")
            value = meta.get(meta_key) or meta.get("comment", "") if meta_key in ("comment_jt", "comment") else meta.get(meta_key, "")
            w.insert("1.0", value)
            if is_locked:
                w.config(state="disabled")
            widgets[field_key] = w
            return w

        _comment_row(card, "LOCATION",   "comment_location", "#89dceb",
                     "comment_location", "\U0001f4cd Maps links (auto-generated from transcript)")
        _comment_row(card, "JT",         "comment_jt",       "#62ddff",
                     "comment",          "@roll4veterans comment in JT's voice")
        _comment_row(card, "GAVIN",      "comment_gavin",    "#a6e3a1",
                     "comment_gavin",    "@erictracy5584 reply to JT's comment (Gavin)")

        tk.Frame(card, bg=CLR_BORDER, height=1).pack(fill="x", pady=(8, 0))

    # ── Approval logic ────────────────────────────────────────────────────────

    def _approval_label(self, val) -> str:
        if val is True:
            return "✓ APPROVED"
        if val is False:
            return "✗ SKIPPED"
        if val == "external":
            return "⚙ EXTERNAL"
        return "  PENDING"

    def _approval_color(self, val) -> str:
        if val is True:
            return CLR_APPROVE
        if val is False:
            return CLR_SKIP
        if val == "external":
            return "#5599cc"
        return CLR_MUTED

    def _status_icon(self, video_id: str) -> str:
        """Short text badge for the jump-combo dropdown (1–2 chars + space)."""
        meta = self._metadata.get(video_id)
        if meta is None:
            return "○ "
        val = meta.get("approved")
        if val is True:
            return "✓ "
        if val is False:
            return "✗ "
        if val == "external":
            return "⚙ "
        return "· "

    def _status_stripe_color(self, has_meta: bool, approval) -> str:
        """3-px card stripe colour keyed to approval state."""
        if not has_meta:
            return "#333346"
        if approval is True:
            return CLR_APPROVE
        if approval is False:
            return CLR_SKIP
        if approval == "external":
            return "#5599cc"
        return "#555577"   # pending

    def _set_approval(self, video_id: str, approved):
        meta = self._metadata.get(video_id)
        if not meta:
            if approved != "external":
                return
            # No generated metadata yet — create a minimal record so the
            # "Done in Studio" mark can be saved and the card can advance.
            meta = {"video_id": video_id}
            self._metadata[video_id] = meta

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
        # If the video will remain visible in the current filter after this change
        # (e.g. filter = "All"), pre-advance the index so _load_data lands on the
        # next card.  If it drops out of the filter (e.g. "Pending" → now approved),
        # the natural clamp already moves to the next item — no nudge needed.
        if self._should_show(video_id):
            self._current_index = min(
                self._current_index + 1,
                max(0, len(self._filtered_ids) - 1),
            )
        self._load_data(skip_autosave=True)

    def _update_summary(self):
        total    = len(self._metadata)
        approved = sum(1 for m in self._metadata.values() if m.get("approved") is True)
        skipped  = sum(1 for m in self._metadata.values() if m.get("approved") is False)
        external = sum(1 for m in self._metadata.values() if m.get("approved") == "external")
        pending  = total - approved - skipped - external
        ext_str  = f"  |  ⚙ External: {external}" if external else ""
        self._status_bar_var.set(
            f"Videos: {len(self._videos)}  |  With metadata: {total}  |  "
            f"Approved: {approved}  |  Skipped: {skipped}  |  Pending: {pending}{ext_str}"
        )

    def _unapprove(self, video_id: str):
        """Remove Approved status and rebuild the card as fully editable."""
        meta = self._metadata.get(video_id)
        if not meta:
            return
        meta["approved"] = None
        save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)
        self._load_data()

    def _show_transcript(self, video_id: str):
        """Open a read-only popup showing the cached transcript text for the given video."""
        t_path = DATA_DIR / "transcripts" / f"{video_id}.json"
        t_data = load_json(t_path) if t_path.exists() else None
        text = (t_data or {}).get("text", "").strip()

        win = tk.Toplevel(self.root)
        video = self._video_map.get(video_id, {})
        title_str = video.get("title", video_id)[:60]
        win.title(f"{title_str} — Transcript")
        win.configure(bg=CLR_BG)
        win.minsize(600, 400)

        # Restore previous geometry if we have one
        if self._transcript_win_geo:
            try:
                win.geometry(self._transcript_win_geo)
            except Exception:
                win.geometry("820x560")
        else:
            win.geometry("820x560")

        def _on_close():
            self._transcript_win_geo = win.geometry()
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)

        if not text:
            tk.Label(
                win, text="No transcript cached for this video.\nRun Transcripts from the More menu to fetch it.",
                bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 13), justify="center",
            ).pack(expand=True)
            return

        frame = tk.Frame(win, bg=CLR_BG)
        frame.pack(fill="both", expand=True, padx=12, pady=(10, 6))

        txt = tk.Text(
            frame, wrap="word", font=(FONT_FAMILY, 12),
            bg=CLR_PANEL, fg=CLR_TEXT, relief="flat",
            padx=10, pady=8, spacing1=3,
        )
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        txt.insert("1.0", text)
        txt.config(state="disabled")

        btn_row = tk.Frame(win, bg=CLR_BG)
        btn_row.pack(pady=(0, 8))
        tk.Button(
            btn_row, text="Close", bg=CLR_BTN_BG, fg=CLR_TEXT,
            font=(FONT_FAMILY, 12), relief="flat", padx=16, pady=4,
            cursor="hand2", command=_on_close,
        ).pack()

    def _mark_all_done(self):
        """Mark every video as 'Done in Studio' (approved='external') regardless of current status.

        This includes Approved, Pending, Skipped, and videos without metadata yet.
        Nothing will be pushed to YouTube after this runs.
        """
        # All known video IDs from both the video list and existing metadata
        all_ids = {v["id"] for v in self._videos} | set(self._metadata.keys())
        not_done = [
            vid for vid in all_ids
            if self._metadata.get(vid, {}).get("approved") != "external"
        ]
        if not not_done:
            messagebox.showinfo("Mark All Done", "All videos are already marked Done — nothing to do.")
            return

        if not messagebox.askyesno(
            "Mark All Done",
            f"Mark ALL {len(not_done)} video{'s' if len(not_done) != 1 else ''} as Done?\n\n"
            "This includes Approved, Pending, and any without metadata.\n"
            "Nothing will be pushed to YouTube. New videos discovered later\n"
            "will still be picked up by the pipeline.",
            icon="warning",
        ):
            return

        for vid in not_done:
            meta = self._metadata.get(vid) or {"video_id": vid}
            meta["approved"] = "external"
            save_json(GENERATED_DIR / f"{vid}_metadata.json", meta)

        self._load_data()
        self._proc_status_var.set(f"Marked {len(not_done)} videos as Done in Studio")

    # ── Single-video AI generation ─────────────────────────────────────────────

    def _generate_this(self, video_id: str):
        """Run  cli.py generate --video-id {id} --force  for just this one card."""
        if self._proc_running:
            return
        btn = getattr(self, "_gen_this_btn", None)
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
            from r4v.content_gen import build_prompt, _pick_gavin_hack, _build_local_color_hint
            video = self._video_map.get(video_id, {})
            meta = self._metadata.get(video_id, {})
            t_text = t_data["text"]
            prompt = build_prompt(
                transcript_text=t_text,
                existing_title=video.get("title", ""),
                existing_description=video.get("description", ""),
                ai_notes=meta.get("ai_notes", ""),
                gavin_hack=_pick_gavin_hack(),
                local_color=_build_local_color_hint(
                    existing_title=video.get("title", ""),
                    existing_description=video.get("description", ""),
                    transcript_text=t_text,
                ),
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
                 font=(FONT_FAMILY, 12, "bold")).pack(side="left")
        tk.Label(hdr, text="System prompt → 🎭 Personality button  ",
                 bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 10)).pack(side="right")

        txt_frame = tk.Frame(win, bg=CLR_BG)
        txt_frame.pack(fill="both", expand=True, padx=8, pady=4)

        prompt_txt = tk.Text(
            txt_frame, bg="#111128", fg=CLR_TEXT,
            font=(FONT_MONO, 11), wrap="word",
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
                               font=(FONT_MONO, 10), anchor="w")
        status_lbl.pack(side="left", fill="x", expand=True)

        cancel_btn = tk.Button(footer, text="Cancel",
                               bg=CLR_BTN_BG, fg=CLR_TEXT,
                               font=(FONT_FAMILY, 11), relief="flat",
                               padx=12, pady=4, cursor="hand2",
                               command=win.destroy)
        cancel_btn.pack(side="right", padx=(4, 0))

        send_btn = tk.Button(footer, text="⚡  Send to Gemini",
                              bg=CLR_APPROVE, fg="#000000",
                              font=(FONT_FAMILY, 11, "bold"), relief="flat",
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

    def _edit_ai_notes_dialog(self):
        """Popup to edit AI notes (>> instructions) for the current video."""
        if not self._filtered_ids:
            return
        video_id = self._filtered_ids[self._current_index]
        meta = self._metadata.get(video_id)
        if meta is None:
            messagebox.showinfo("No metadata", "Generate metadata for this video first.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Notes for AI — {video_id}")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("620x340")
        win.minsize(400, 280)
        win.transient(self.root)

        tk.Label(win, text="Corrections / context for Gemini on next regen:",
                 bg=CLR_BG, fg="#a08060", font=(FONT_FAMILY, 11)).pack(
                     anchor="w", padx=12, pady=(10, 2))
        tk.Label(win, text='Each line becomes a [[ instruction.  Example: "The tour guide is a man, not a woman"',
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 10, "italic")).pack(
                     anchor="w", padx=12, pady=(0, 6))

        def _save(close=True):
            notes = txt.get("1.0", "end-1c").strip()
            meta["ai_notes"] = notes
            save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)
            if close:
                win.destroy()

        btn_frame = tk.Frame(win, bg=CLR_BG)
        btn_frame.pack(side="bottom", pady=(0, 10))
        tk.Button(btn_frame, text="Save & Close", command=lambda: _save(True),
                  bg=CLR_APPROVE, fg="#000000", font=(FONT_FAMILY, 11, "bold"),
                  padx=10).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", command=win.destroy,
                  bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 11),
                  padx=10).pack(side="left", padx=6)
        txt = tk.Text(win, bg="#1a1408", fg=CLR_TEXT, font=(FONT_MONO, 11),
                      relief="flat", insertbackground=CLR_TEXT, wrap="word")
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        txt.insert("1.0", meta.get("ai_notes", ""))
        txt.focus_set()

        win.bind("<Escape>", lambda _: win.destroy())
        win.bind("<Control-Return>", lambda _: _save(True))
        win.grab_set()

    def _edit_global_ai_notes(self):
        """Popup to edit persistent global AI notes — applied to every generation."""
        win = tk.Toplevel(self.root)
        win.title("Global AI Notes")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("640x360")
        win.minsize(400, 280)
        win.transient(self.root)

        tk.Label(win, text="Persistent instructions for Gemini — applied to every generation:",
                 bg=CLR_BG, fg="#a08060", font=(FONT_FAMILY, 11)).pack(
                     anchor="w", padx=12, pady=(10, 2))
        tk.Label(win,
                 text='One instruction per line. Stays active until you clear it.  '
                      'Example: "Sean\'s name is spelled Sean, not Shawn"',
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_FAMILY, 10, "italic"), wraplength=610).pack(
                     anchor="w", padx=12, pady=(0, 6))

        current_data = load_json(GLOBAL_AI_NOTES_JSON) or {}
        current_notes = (current_data.get("notes") or "").strip()

        def _save(close=True):
            notes = txt.get("1.0", "end-1c").strip()
            save_json(GLOBAL_AI_NOTES_JSON, {"notes": notes})
            if notes:
                self._proc_status_var.set(f"Global AI notes saved ({len(notes.splitlines())} line(s))")
            else:
                self._proc_status_var.set("Global AI notes cleared.")
            if close:
                win.destroy()

        def _clear():
            txt.delete("1.0", "end")
            _save(close=True)

        btn_frame = tk.Frame(win, bg=CLR_BG)
        btn_frame.pack(side="bottom", pady=(0, 10))
        tk.Button(btn_frame, text="Save & Close", command=lambda: _save(True),
                  bg=CLR_APPROVE, fg="#000000", font=(FONT_FAMILY, 11, "bold"),
                  padx=10).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Clear All", command=_clear,
                  bg=CLR_SKIP, fg="#000000", font=(FONT_FAMILY, 11),
                  padx=10).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", command=win.destroy,
                  bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 11),
                  padx=10).pack(side="left", padx=6)

        txt = tk.Text(win, bg="#1a1408", fg=CLR_TEXT, font=(FONT_MONO, 11),
                      relief="flat", insertbackground=CLR_TEXT, wrap="word")
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        txt.insert("1.0", current_notes)
        txt.focus_set()

        win.bind("<Escape>", lambda _: win.destroy())
        win.bind("<Control-Return>", lambda _: _save(True))
        win.grab_set()

    def _edit_tags_hashtags_dialog(self):
        """Popup to edit Tags and Hashtags for the current video."""
        if not self._filtered_ids:
            return
        video_id = self._filtered_ids[self._current_index]
        meta = self._metadata.get(video_id)
        if meta is None:
            messagebox.showinfo("No metadata", "Generate metadata for this video first.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Tags & Hashtags — {video_id}")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("700x320")
        win.transient(self.root)

        # Tags
        tk.Label(win, text="TAGS  (comma-separated, invisible search keywords)",
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_MONO, 11, "bold")).pack(
                     anchor="w", padx=12, pady=(12, 2))
        tags_entry = tk.Entry(win, bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_MONO, 11),
                              insertbackground=CLR_TEXT, relief="flat")
        tags_entry.insert(0, tags_to_str(meta.get("tags", [])))
        tags_entry.pack(fill="x", padx=12, pady=(0, 10))

        # Hashtags
        tk.Label(win, text="HASHTAGS  (#words that appear as clickable links in description)",
                 bg=CLR_BG, fg=CLR_MUTED, font=(FONT_MONO, 11, "bold")).pack(
                     anchor="w", padx=12, pady=(0, 2))
        ht_txt = tk.Text(win, bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_MONO, 11),
                         relief="flat", insertbackground=CLR_TEXT, height=5, wrap="word")
        ht_txt.insert("1.0", meta.get("hashtags", ""))
        ht_txt.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        tags_entry.focus_set()

        def _save():
            self._autosave_current()  # flush description edits first
            meta["tags"] = str_to_tags(tags_entry.get())
            meta["hashtags"] = ht_txt.get("1.0", "end-1c").strip()
            save_json(GENERATED_DIR / f"{video_id}_metadata.json", meta)
            win.destroy()

        btn_frame = tk.Frame(win, bg=CLR_BG)
        btn_frame.pack(pady=(0, 10))
        tk.Button(btn_frame, text="Save & Close", command=_save,
                  bg=CLR_APPROVE, fg="#000000", font=(FONT_FAMILY, 11, "bold"),
                  padx=10).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", command=win.destroy,
                  bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 11),
                  padx=10).pack(side="left", padx=6)
        win.bind("<Escape>", lambda _: win.destroy())

    def _edit_personalities(self):
        """Open config/personalities.json in an editable popup."""
        prof_path = PROJECT_ROOT / "config" / "personalities.json"
        try:
            content = prof_path.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", f"Could not read personalities.json:\n{e}")
            return

        win = tk.Toplevel(self.root)
        win.title("Voice Profiles — JT & Gavin (config/personalities.json)")
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
                 font=(FONT_FAMILY, 12, "bold"), pady=8).pack(fill="x")
        tk.Label(win, text="  Changes take effect on the next ⚡ generation — no restart needed",
                 bg=CLR_PANEL, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 10), pady=2).pack(fill="x")

        txt_frame = tk.Frame(win, bg=CLR_BG)
        txt_frame.pack(fill="both", expand=True, padx=8, pady=4)

        editor = tk.Text(txt_frame, bg="#111128", fg=CLR_TEXT,
                          font=(FONT_MONO, 11), wrap="none",
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
                               font=(FONT_MONO, 10), anchor="w")
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
                  font=(FONT_FAMILY, 11), relief="flat", padx=12, pady=4,
                  cursor="hand2").pack(side="right", padx=(4, 0))
        tk.Button(footer, text="💾  Save",
                  bg=CLR_APPROVE, fg="#000000",
                  font=(FONT_FAMILY, 11, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=_save).pack(side="right", padx=(4, 0))

    def _stop_proc(self):
        """Terminate the currently running subprocess and reset the process state."""
        if self._proc_subprocess:
            try:
                self._proc_subprocess.terminate()
            except Exception:
                pass
            self._proc_subprocess = None
        self._reset_proc()
        self._proc_status_var.set("■ Stopped")

    # ── Sash position memory ──────────────────────────────────────────────────

    def _sash_log(self, msg: str):
        try:
            import datetime as _dt
            log = DATA_DIR / "sash_debug.log"
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"{_dt.datetime.now().strftime('%H:%M:%S')}  {msg}\n")
        except Exception:
            pass

    def _save_sash_prefs(self):
        """Read live sash positions from widgets and save to ui_prefs.json."""
        try:
            if self._vpane and self._vpane.winfo_exists():
                vsashes = []
                for i in range(4):
                    try:
                        vsashes.append(self._vpane.sash_coord(i)[1])
                    except Exception:
                        break
                if vsashes:
                    self._sash_prefs["vpane"] = vsashes
                self._sash_log(f"SAVE vpane sash_coord → {vsashes}")
            else:
                self._sash_log("SAVE vpane: no widget")
            hsashes = []
            for idx, pane in enumerate(self._col_panes):
                try:
                    x = pane.sash_coord(0)[0] if pane.winfo_exists() else None
                    hsashes.append(x)
                    self._sash_log(f"SAVE hpane[{idx}] sash_coord → {x}  (pane width={pane.winfo_width()})")
                except Exception as e:
                    hsashes.append(None)
                    self._sash_log(f"SAVE hpane[{idx}] ERROR: {e}")
            if any(x is not None for x in hsashes):
                self._sash_prefs["hpane"] = hsashes
            if self._sash_prefs:
                prefs = load_json(UI_PREFS_JSON) or {}
                prefs["sashes"] = self._sash_prefs
                save_json(UI_PREFS_JSON, prefs)
                self._sash_log(f"SAVE written to disk: {self._sash_prefs}")
            else:
                self._sash_log("SAVE skipped — _sash_prefs empty")
        except Exception as e:
            self._sash_log(f"SAVE exception: {e}")

    def _restore_sash_prefs(self):
        """Apply _sash_prefs to the current card's paned windows."""
        self._sash_log(f"RESTORE called  prefs={self._sash_prefs}")
        try:
            for i, y in enumerate(self._sash_prefs.get("vpane", [])):
                try:
                    self._vpane.sash_place(i, 0, int(y))
                    self._sash_log(f"RESTORE vpane sash {i} → y={y}")
                except Exception as e:
                    self._sash_log(f"RESTORE vpane sash {i} ERROR: {e}")
            saved_h = self._sash_prefs.get("hpane", [])
            for idx, pane in enumerate(self._col_panes):
                try:
                    if idx < len(saved_h) and saved_h[idx] is not None:
                        x = int(saved_h[idx])
                    else:
                        # Default 40:60 split
                        x = int(pane.winfo_width() * 0.40)
                    pane.sash_place(0, x, 0)
                    after_x = pane.sash_coord(0)[0]
                    self._sash_log(f"RESTORE hpane[{idx}] → x={x}  verify after={after_x}  pane_w={pane.winfo_width()}")
                except Exception as e:
                    self._sash_log(f"RESTORE hpane[{idx}] ERROR: {e}")
        except Exception as e:
            self._sash_log(f"RESTORE exception: {e}")

    def _reset_proc(self):
        """Force-reset the process-running flag — use when ⚡ or a button does nothing."""
        if hasattr(self, "_stop_btn"):
            self._stop_btn.config(state="disabled")
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
        approved_unordered = [
            vid for vid, m in self._metadata.items() if m.get("approved") is True
        ]
        if not approved_unordered:
            messagebox.showinfo("Nothing to push", "No videos are marked Approved yet.")
            return

        # Sort by upload_date ascending (oldest content scheduled first)
        def _sort_key(vid):
            return self._video_map.get(vid, {}).get("upload_date", "") or ""
        approved = sorted(approved_unordered, key=_sort_key)

        schedule_map = self._push_schedule_dialog(approved)
        if schedule_map is None:
            return  # cancelled

        is_scheduled = bool(schedule_map)

        # Write publish_at timestamps into metadata files before launching CLI
        if is_scheduled:
            for vid, ts in schedule_map.items():
                meta = self._metadata.get(vid)
                if meta:
                    meta["publish_at"] = ts
                    save_json(GENERATED_DIR / f"{vid}_metadata.json", meta)

        pushed_ids = list(approved)

        def _on_push_done(rc):
            if rc == 0:
                newly_applied = [
                    vid for vid in pushed_ids
                    if (APPLIED_DIR / f"{vid}_applied.json").exists()
                ]
                for vid in newly_applied:
                    meta = load_json(GENERATED_DIR / f"{vid}_metadata.json")
                    if meta:
                        meta["approved"] = "external"
                        meta.pop("publish_at", None)  # consumed — clean up
                        save_json(GENERATED_DIR / f"{vid}_metadata.json", meta)

                # Update videos.json so the filter reflects current YouTube state
                _vids = load_json(VIDEOS_JSON) or []
                _vid_set = set(newly_applied)
                for _v in _vids:
                    if _v.get("id") in _vid_set:
                        _v["availability"] = "public"
                if _vid_set:
                    save_json(VIDEOS_JSON, _vids)
                    self._videos = _vids  # keep in-memory copy in sync

                # Remove pushed IDs from the pending Add Video list
                _p = load_json(UI_PREFS_JSON) or {}
                _pending = _p.get("pending_video_ids", [])
                if _pending:
                    _p["pending_video_ids"] = [v for v in _pending if v not in _vid_set]
                    save_json(UI_PREFS_JSON, _p)

                self._load_data()
                count = len(newly_applied)

                if is_scheduled:
                    first_ts = schedule_map.get(pushed_ids[0], "")[:16].replace("T", " ") if pushed_ids else ""
                    self._proc_status_var.set(
                        f"\u2713 Scheduled {count}/{len(pushed_ids)} video(s) — "
                        f"first releases {first_ts} UTC"
                    )
                    return  # no auto-engage for scheduled releases

                self._proc_status_var.set(
                    f"\u2713 Pushed {count}/{len(pushed_ids)} video(s) \u2014 use More \u25be \u203a Engage to post comments."
                )

                # Auto-engage disabled — re-enable by uncommenting below
                # self._proc_status_var.set(
                #     f"\u2713 Pushed {count}/{len(pushed_ids)} video(s) \u2014 Engage starts in 4 seconds..."
                # )
                # def _auto_engage():
                #     from r4v.storage import load_json as _le
                #     eng_log = _le(APPLIED_DIR / "engagement.json") or {}
                #     unengaged = [
                #         vid for vid in newly_applied
                #         if not (eng_log.get(vid, {}).get("liked")
                #                 and eng_log.get(vid, {}).get("commented"))
                #     ]
                #     if unengaged:
                #         engage_args = ["cli.py", "engage"]
                #         for vid in unengaged:
                #             engage_args += ["--video-id", vid]
                #         self._run_cli("Engage", engage_args, None, auto_reload=False)
                #     else:
                #         self._proc_status_var.set(
                #             f"\u2713 Pushed {count}/{len(pushed_ids)} \u2014 all videos already engaged."
                #         )
                # self.root.after(4000, _auto_engage)
            else:
                messagebox.showerror(
                    "Push failed",
                    f"The push command exited with error code {rc}.\n"
                    "Check the progress log for details.",
                )

        push_args = ["cli.py", "push"]
        for vid in pushed_ids:
            push_args += ["--video-id", vid]
        self._run_cli(
            "Push → YouTube",
            push_args,
            self._proc_buttons.get("Push Approved"),
            auto_reload=False,
            on_done=_on_push_done,
        )

    def _push_schedule_dialog(self, approved_ids: list[str]):
        """Modal dialog: push now or schedule with 4h between releases.

        Returns {} for push-now, {video_id: RFC3339_utc_str, ...} for schedule,
        or None if cancelled.
        """
        from datetime import datetime, timezone, timedelta

        n = len(approved_ids)
        result_holder = [None]

        win = tk.Toplevel(self.root)
        win.title(f"Push {n} video(s) to YouTube")
        win.configure(bg=CLR_BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        # ── Mode selector ────────────────────────────────────────────────────
        mode_var = tk.StringVar(value="now")

        hdr = tk.Frame(win, bg=CLR_BG)
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(hdr, text=f"Push {n} approved video(s) to YouTube",
                 bg=CLR_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 13, "bold")).pack(anchor="w")

        # ── Schedule options (shown/hidden) ──────────────────────────────────
        sched_frame = tk.Frame(win, bg=CLR_BG)

        modes = tk.Frame(win, bg=CLR_BG)
        modes.pack(fill="x", padx=16, pady=4)

        # Default start: next round hour in local time
        _now = datetime.now()
        _default_start = (_now.replace(minute=0, second=0, microsecond=0)
                          + timedelta(hours=1))
        start_var = tk.StringVar(value=_default_start.strftime("%Y-%m-%d %H:%M"))

        _saved_iv = str((load_json(UI_PREFS_JSON) or {}).get("push_interval_hours", 4))
        interval_var = tk.StringVar(value=_saved_iv)

        sf_top = tk.Frame(sched_frame, bg=CLR_BG)
        sf_top.pack(fill="x", pady=(6, 2))
        tk.Label(sf_top, text="Start (local time):", bg=CLR_BG, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 11)).pack(side="left")
        start_entry = tk.Entry(sf_top, textvariable=start_var, width=18,
                               bg=CLR_PANEL, fg=CLR_TEXT, insertbackground=CLR_TEXT,
                               font=(FONT_MONO, 11), relief="flat")
        start_entry.pack(side="left", padx=(6, 0))
        tk.Label(sf_top, text="  Interval (hours):", bg=CLR_BG, fg=CLR_MUTED,
                 font=(FONT_FAMILY, 11)).pack(side="left")
        interval_entry = tk.Entry(sf_top, textvariable=interval_var, width=5,
                                  bg=CLR_PANEL, fg=CLR_TEXT, insertbackground=CLR_TEXT,
                                  font=(FONT_MONO, 11), relief="flat")
        interval_entry.pack(side="left", padx=(6, 0))
        interval_lbl = tk.Label(sf_top, text="", bg=CLR_BG, fg=CLR_MUTED,
                                font=(FONT_FAMILY, 10, "italic"))
        interval_lbl.pack(side="left", padx=(12, 0))

        preview_txt = tk.Text(sched_frame, height=min(n, 8), width=58,
                              bg=CLR_PANEL, fg=CLR_TEXT, font=(FONT_MONO, 10),
                              relief="flat", state="disabled")
        preview_txt.pack(fill="x", pady=(4, 0))

        def _update_preview(*_):
            try:
                local_tz = datetime.now().astimezone().tzinfo
                local_dt = (datetime.strptime(start_var.get().strip(), "%Y-%m-%d %H:%M")
                            .replace(tzinfo=local_tz))
            except ValueError:
                interval_lbl.config(text="(invalid date/interval)")
                preview_txt.config(state="normal")
                preview_txt.delete("1.0", "end")
                preview_txt.config(state="disabled")
                return

            try:
                iv_hours = float(interval_var.get().strip())
                if iv_hours < 0:
                    raise ValueError
            except ValueError:
                interval_lbl.config(text="(invalid interval)")
                preview_txt.config(state="normal")
                preview_txt.delete("1.0", "end")
                preview_txt.config(state="disabled")
                return

            interval = timedelta(hours=iv_hours) if n > 1 else timedelta(0)
            total_mins = int(interval.total_seconds() / 60)
            if total_mins >= 60:
                h, m = divmod(total_mins, 60)
                iv_str = f"every {h}h" + (f" {m}m" if m else "")
            else:
                iv_str = f"every {total_mins}m"
            interval_lbl.config(text=f"— {iv_str}")

            preview_txt.config(state="normal")
            preview_txt.delete("1.0", "end")
            for i, vid in enumerate(approved_ids):
                slot = local_dt + interval * i
                title = (self._video_map.get(vid, {}).get("title")
                         or self._metadata.get(vid, {}).get("existing_title", vid))[:38]
                preview_txt.insert("end",
                    f"{i+1:2}. {slot.strftime('%b %d %I:%M %p')}  {title}\n")
            preview_txt.config(state="disabled")

        start_var.trace_add("write", _update_preview)
        interval_var.trace_add("write", _update_preview)

        def _toggle():
            if mode_var.get() == "schedule":
                sched_frame.pack(fill="x", padx=16, pady=(0, 6))
                _update_preview()
            else:
                sched_frame.pack_forget()
            win.update_idletasks()

        for val, lbl in [("now",      "Push now — make all Public immediately"),
                          ("schedule", "Schedule — stagger releases")]:
            tk.Radiobutton(modes, text=lbl, variable=mode_var, value=val,
                           bg=CLR_BG, fg=CLR_TEXT, selectcolor=CLR_BG,
                           activebackground=CLR_BG, activeforeground=CLR_TEXT,
                           font=(FONT_FAMILY, 11), command=_toggle).pack(anchor="w", pady=1)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = tk.Frame(win, bg=CLR_BG)
        btn_row.pack(pady=(8, 14))

        def _cancel():
            result_holder[0] = None
            win.destroy()

        def _confirm():
            if mode_var.get() == "now":
                result_holder[0] = {}
                win.destroy()
                return
            # Build schedule map
            try:
                local_tz = datetime.now().astimezone().tzinfo
                local_dt = (datetime.strptime(start_var.get().strip(), "%Y-%m-%d %H:%M")
                            .replace(tzinfo=local_tz))
            except ValueError:
                messagebox.showerror("Invalid date",
                                     "Enter start time as YYYY-MM-DD HH:MM", parent=win)
                return
            try:
                iv_hours = float(interval_var.get().strip())
                if iv_hours < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid interval",
                                     "Enter a positive number of hours (e.g. 2 or 1.5)", parent=win)
                return
            prefs = load_json(UI_PREFS_JSON) or {}
            prefs["push_interval_hours"] = iv_hours
            save_json(UI_PREFS_JSON, prefs)
            utc_start = local_dt.astimezone(timezone.utc)
            interval = timedelta(hours=iv_hours) if n > 1 else timedelta(0)
            smap = {}
            for i, vid in enumerate(approved_ids):
                slot = utc_start + interval * i
                smap[vid] = slot.strftime("%Y-%m-%dT%H:%M:%SZ")
            result_holder[0] = smap
            win.destroy()

        tk.Button(btn_row, text="Cancel", command=_cancel,
                  bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 11),
                  padx=10, relief="flat").pack(side="left", padx=6)
        tk.Button(btn_row, text="Confirm", command=_confirm,
                  bg=CLR_APPROVE, fg="#000000", font=(FONT_FAMILY, 11, "bold"),
                  padx=14, relief="flat").pack(side="left", padx=6)

        win.bind("<Escape>", lambda _: _cancel())
        win.bind("<Return>", lambda _: _confirm())
        win.update_idletasks()
        cx = (win.winfo_screenwidth()  - win.winfo_width())  // 2
        cy = (win.winfo_screenheight() - win.winfo_height()) // 2
        win.geometry(f"+{cx}+{cy}")
        win.wait_window()
        return result_holder[0]

    def _add_video_dialog(self):
        """Open a dialog to add videos by pasting URLs or IDs — one per line."""
        import re as _re
        win = tk.Toplevel(self.root)
        win.title("Add Video(s) by URL")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("560x375")
        win.update_idletasks()
        x = (win.winfo_screenwidth() - 560) // 2
        y = (win.winfo_screenheight() - 375) // 2
        win.geometry(f"560x375+{x}+{y}")
        win.grab_set()

        tk.Label(win, text="Paste YouTube URLs or video IDs — one per line:",
                 bg=CLR_BG, fg=CLR_TEXT, font=("Segoe UI", 12)).pack(pady=(14, 4), padx=16, anchor="w")

        txt = tk.Text(win, bg=CLR_BTN_BG, fg=CLR_TEXT, insertbackground=CLR_TEXT,
                      font=("Segoe UI", 11), height=10, relief="flat", wrap="word")
        txt.pack(padx=16, fill="both", expand=True)

        # Restore pending URLs saved from the last session
        _prefs = load_json(UI_PREFS_JSON) or {}
        _pending_ids = _prefs.get("pending_video_ids", [])
        if _pending_ids:
            _restored = "\n".join(f"https://www.youtube.com/shorts/{vid}" for vid in _pending_ids)
            txt.insert("1.0", _restored + "\n" + "\n" * max(0, 9 - len(_pending_ids)))
        else:
            txt.insert("1.0", "\n" * 9)  # pre-fill with blank lines — paste URLs without pressing Enter
        txt.mark_set("insert", "1.0")
        txt.focus_set()

        status_var = tk.StringVar()
        status_lbl = tk.Label(win, textvariable=status_var, bg=CLR_BG, fg=CLR_MUTED,
                              font=("Segoe UI", 10, "italic"), anchor="w")
        status_lbl.pack(pady=(4, 0), padx=16, fill="x")

        def _extract_ids(raw: str) -> list[str]:
            seen, ids = set(), []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = (_re.search(r"studio\.youtube\.com/video/([A-Za-z0-9_-]{11})", line)
                     or _re.search(r"(?:v=|shorts/|youtu\.be/)([A-Za-z0-9_-]{11})", line))
                vid = m.group(1) if m else (line if _re.fullmatch(r"[A-Za-z0-9_-]{11}", line) else None)
                if vid and vid not in seen:
                    seen.add(vid)
                    ids.append(vid)
            return ids

        def _do_add():
            raw = txt.get("1.0", "end-1c")
            ids = _extract_ids(raw)
            if not ids:
                status_var.set("No valid video IDs found — check your URLs.")
                status_lbl.config(fg=CLR_SKIP)
                return

            status_var.set(f"Fetching {len(ids)} video(s)...")
            status_lbl.config(fg=CLR_MUTED)
            win.update_idletasks()

            try:
                from r4v.auth import get_youtube_service
                status_var.set(f"Parsed {len(ids)} ID(s): {', '.join(ids)}")
                status_lbl.config(fg=CLR_MUTED)
                win.update_idletasks()

                service = get_youtube_service()
                status_var.set("Auth OK — calling API...")
                win.update_idletasks()

                # Fetch all in one API call (up to 50)
                resp = service.videos().list(
                    part="snippet,status", id=",".join(ids)
                ).execute()
                api_items = {item["id"]: item for item in resp.get("items", [])}
                status_var.set(f"API returned {len(api_items)} item(s) — saving...")
                win.update_idletasks()

                videos = load_json(VIDEOS_JSON) or []
                existing_map = {v["id"]: v for v in videos}
                added, updated, missing = [], [], []

                for vid in ids:
                    if vid not in api_items:
                        missing.append(vid)
                        continue
                    item = api_items[vid]
                    snippet = item.get("snippet", {})
                    privacy = item.get("status", {}).get("privacyStatus", "public")
                    video = {
                        "id": vid,
                        "title": snippet.get("title", ""),
                        "url": f"https://www.youtube.com/shorts/{vid}",
                        "upload_date": snippet.get("publishedAt", "")[:10].replace("-", ""),
                        "description": snippet.get("description", ""),
                        "tags": snippet.get("tags", []),
                        "duration": None,
                        "view_count": None,
                        "availability": privacy,
                    }
                    if vid in existing_map:
                        existing_map[vid].update(video)
                        updated.append(vid)
                    else:
                        videos.append(video)
                        existing_map[vid] = video
                        added.append(vid)

                save_json(VIDEOS_JSON, videos)
                self._load_data(skip_autosave=True)

                # Persist pending IDs to ui_prefs — cleared only when pushed
                _all_processed = added + updated
                if _all_processed:
                    _p = load_json(UI_PREFS_JSON) or {}
                    _existing_pending = _p.get("pending_video_ids", [])
                    _merged = list(dict.fromkeys(_existing_pending + _all_processed))
                    _p["pending_video_ids"] = _merged
                    save_json(UI_PREFS_JSON, _p)

                parts = []
                if added:
                    parts.append(f"{len(added)} added")
                if updated:
                    parts.append(f"{len(updated)} updated")
                if missing:
                    parts.append(f"{len(missing)} not found: {missing}")
                summary = " · ".join(parts)
                self._proc_status_var.set(f"Add Video: {summary}")
                if not missing:
                    win.destroy()
                    self._open_pipeline_window(video_ids=added or updated)
                else:
                    status_var.set(f"✓ {summary}")
                    status_lbl.config(fg=CLR_MUTED)
                    txt.delete("1.0", "end")
                    txt.insert("1.0", "\n" * 9)
            except Exception as exc:
                msg = str(exc)
                if "invalid_grant" in msg or "Token has been expired" in msg:
                    msg = "OAuth token expired — close and re-authenticate."
                status_var.set(f"Error: {msg}")
                status_lbl.config(fg=CLR_SKIP)

        btn_frame = tk.Frame(win, bg=CLR_BG)
        btn_frame.pack(pady=(8, 10))
        tk.Button(btn_frame, text="Add", command=_do_add, bg="#89b4fa", fg="#1e1e2e",
                  font=("Segoe UI", 12, "bold"), padx=12).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Close", command=win.destroy, bg=CLR_BTN_BG, fg=CLR_TEXT,
                  font=("Segoe UI", 12), padx=12).pack(side="left", padx=6)
        win.bind("<Escape>", lambda _: win.destroy())

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
                 font=(FONT_FAMILY, 16, "bold"), pady=12).pack()

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
            "  Find Unlisted   Query YouTube API (auth required) to discover unlisted videos.\n"
            "  Generate AI     Generate AI metadata for all videos that have a transcript.\n"
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

        txt = tk.Text(win, bg=CLR_PANEL, fg=CLR_TEXT, font=(FONT_FAMILY, 12),
                      padx=16, pady=12, relief="flat", wrap="word")
        txt.insert("1.0", help_text)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        tk.Button(win, text="Close", command=win.destroy,
                  bg=CLR_BTN_BG, fg=CLR_TEXT, font=(FONT_FAMILY, 12),
                  relief="flat", padx=20, pady=6, cursor="hand2").pack(pady=8)

    def _find_python(self) -> str:
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    # ── Bottom process bar ────────────────────────────────────────────────────

    def _build_bottom_bar(self):
        """Initialise process-runner state. UI widgets live in the action bar (built in _build_ui)."""
        self._proc_q: queue.Queue = queue.Queue()
        self._proc_running = False
        self._proc_subprocess = None
        self._proc_current_btn = None
        self._proc_current_label = ""
        self._proc_auto_reload = False
        self._proc_on_done = None
        self._auto_check_after_id = None
        self._auto_check_fire_ms: int = 0  # epoch ms when next check fires
        self.root.after(100, self._poll_proc_q)

    # ── Auto-check pending queue ──────────────────────────────────────────────

    _AUTO_CHECK_INTERVAL_MS = 30 * 60 * 1000  # 30 minutes

    def _get_unprocessed_pending(self) -> list[str]:
        """Return pending video IDs that still need transcript or metadata."""
        prefs = load_json(UI_PREFS_JSON) or {}
        pending = prefs.get("pending_video_ids", [])
        return [v for v in pending
                if not (TRANSCRIPTS_DIR / f"{v}.json").exists()
                or not (GENERATED_DIR / f"{v}_metadata.json").exists()]

    def _startup_queue_check(self):
        """On startup: clean stale pending IDs, then schedule auto-check if needed."""
        self._clean_pending_queue()
        self._schedule_auto_check()

    def _clean_pending_queue(self):
        """Remove from pending_video_ids any video that is fully processed, pushed, or private.

        Runs on startup and after every pipeline/push so IDs don't get stuck.
        """
        prefs = load_json(UI_PREFS_JSON) or {}
        pending = prefs.get("pending_video_ids", [])
        if not pending:
            return

        # Build a quick lookup of video availability from videos.json
        all_videos = load_json(VIDEOS_JSON) or []
        availability = {v["id"]: v.get("availability", "public") for v in all_videos if "id" in v}

        kept = []
        for vid in pending:
            # Drop if private — transcripts will never be available
            if availability.get(vid) == "private":
                continue
            meta_path = GENERATED_DIR / f"{vid}_metadata.json"
            meta = load_json(meta_path) if meta_path.exists() else None
            # Drop if pushed (applied file exists) or fully processed with approved state
            if (APPLIED_DIR / f"{vid}_applied.json").exists():
                continue
            if meta and meta.get("approved") == "external":
                continue
            kept.append(vid)
        if kept != pending:
            prefs["pending_video_ids"] = kept
            save_json(UI_PREFS_JSON, prefs)

    def _schedule_auto_check(self):
        """Schedule next auto-check if there are still unprocessed pending videos."""
        import time as _time
        if self._auto_check_after_id:
            return  # already scheduled
        if not self._get_unprocessed_pending():
            return
        self._auto_check_fire_ms = int(_time.time() * 1000) + self._AUTO_CHECK_INTERVAL_MS
        self._auto_check_after_id = self.root.after(
            self._AUTO_CHECK_INTERVAL_MS, self._auto_check_pending
        )
        self._auto_check_countdown_tick()

    def _auto_check_countdown_tick(self):
        """Update status bar with countdown every 60 s while waiting."""
        import time as _time
        if not self._auto_check_after_id or self._proc_running:
            return
        remaining_ms = self._auto_check_fire_ms - int(_time.time() * 1000)
        if remaining_ms <= 0:
            return
        remaining_min = max(1, round(remaining_ms / 60000))
        self._proc_status_var.set(
            f"Auto-check: next transcript retry in {remaining_min} min "
            f"({len(self._get_unprocessed_pending())} video(s) pending)"
        )
        self.root.after(60_000, self._auto_check_countdown_tick)

    def _auto_check_pending(self):
        """Fire: run pipeline for any unprocessed pending videos, then reschedule if needed."""
        self._auto_check_after_id = None
        self._clean_pending_queue()
        unprocessed = self._get_unprocessed_pending()
        if not unprocessed:
            return
        if self._proc_running:
            # Something else is running — back off and try again in 30 min
            self._schedule_auto_check()
            return
        pipeline_args = ["cli.py", "pipeline", "--skip-discover"]
        for vid in unprocessed:
            pipeline_args += ["--video-id", vid]

        attempted = set(unprocessed)
        _MAX_TRANSCRIPT_FAILURES = 3

        def _on_done(rc):
            self._load_data()
            self._clean_pending_queue()

            # Work out what changed
            now_unprocessed = set(self._get_unprocessed_pending())
            newly_done = attempted - now_unprocessed
            still_pending = attempted & now_unprocessed

            # Increment failure counters for videos that still have no transcript
            prefs = load_json(UI_PREFS_JSON) or {}
            failures = prefs.get("transcript_failures", {})
            gave_up = []
            for vid in still_pending:
                failures[vid] = failures.get(vid, 0) + 1
                if failures[vid] >= _MAX_TRANSCRIPT_FAILURES:
                    gave_up.append(vid)
            # Drop give-up videos from pending and clear their counter
            if gave_up:
                pending = prefs.get("pending_video_ids", [])
                prefs["pending_video_ids"] = [v for v in pending if v not in gave_up]
                for vid in gave_up:
                    failures.pop(vid, None)
            # Clear counters for newly-done videos
            for vid in newly_done:
                failures.pop(vid, None)
            prefs["transcript_failures"] = failures
            save_json(UI_PREFS_JSON, prefs)

            import datetime as _dt
            ts = _dt.datetime.now().strftime("%H:%M")
            lines = [f"Auto-check completed at {ts}", ""]
            vids_list = self._videos if hasattr(self, "_videos") else []
            title_map = {v["id"]: v.get("title", v["id"])[:50] for v in vids_list}
            if newly_done:
                lines.append(f"✓ Processed ({len(newly_done)}):")
                for vid in sorted(newly_done):
                    lines.append(f"   {title_map.get(vid, vid)}")
            retrying = still_pending - set(gave_up)
            if retrying:
                lines.append(f"⏳ Still waiting for captions ({len(retrying)}):")
                for vid in sorted(retrying):
                    lines.append(f"   {title_map.get(vid, vid)}  (attempt {failures.get(vid,0)}/{_MAX_TRANSCRIPT_FAILURES})")
                lines.append("")
                lines.append("Will retry in 30 minutes.")
            if gave_up:
                lines.append(f"✗ Gave up after {_MAX_TRANSCRIPT_FAILURES} failures — removed from queue:")
                for vid in sorted(gave_up):
                    lines.append(f"   {title_map.get(vid, vid)}")
            if not newly_done and not retrying and not gave_up:
                lines.append("Nothing changed.")

            self._show_auto_check_result("\n".join(lines))
            self._schedule_auto_check()  # reschedule only if still needed

        self._run_cli(
            "Auto-check (transcripts)", pipeline_args, None,
            auto_reload=False, on_done=_on_done,
        )

    def _show_auto_check_result(self, message: str):
        """Non-modal result window that stays until the user dismisses it."""
        # Close any previous result window
        prev = getattr(self, "_auto_check_result_win", None)
        if prev:
            try:
                prev.destroy()
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        win.title("Auto-check Result")
        win.configure(bg=CLR_BG)
        win.resizable(True, True)
        win.geometry("420x260")
        win.update_idletasks()
        # Position bottom-right of main window
        mx = self.root.winfo_x() + self.root.winfo_width() - 440
        my = self.root.winfo_y() + self.root.winfo_height() - 300
        win.geometry(f"420x260+{max(0,mx)}+{max(0,my)}")
        win.lift()
        win.attributes("-topmost", True)
        self._auto_check_result_win = win

        txt = tk.Text(win, bg=CLR_PANEL, fg=CLR_TEXT, font=(FONT_MONO, 11),
                      relief="flat", wrap="word", padx=12, pady=10, state="normal")
        txt.insert("1.0", message)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        tk.Button(win, text="OK", command=win.destroy,
                  bg=CLR_APPROVE, fg="#000000",
                  font=(FONT_FAMILY, 11, "bold"), padx=20, pady=4,
                  cursor="hand2").pack(pady=(0, 10))
        win.bind("<Return>", lambda _: win.destroy())
        win.bind("<Escape>", lambda _: win.destroy())

    def _run_cli(self, label: str, args: list, btn, auto_reload: bool = False, on_done=None):
        if self._proc_running:
            return

        self._proc_running = True
        self._proc_auto_reload = auto_reload
        self._proc_on_done = on_done
        self._proc_current_btn = btn
        self._proc_current_label = label

        for b in (v for v in self._proc_buttons.values() if v is not None):
            b.config(state="disabled")
        if btn is not None:
            btn.config(text=f"{label}…")
        self._proc_progbar.start(12)
        self._proc_status_var.set(f"Starting: {label}")
        if hasattr(self, "_stop_btn"):
            self._stop_btn.config(state="normal")

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
                self._proc_subprocess = proc
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        self._proc_q.put(("line", line))
                proc.wait()
                self._proc_subprocess = None
                self._proc_q.put(("done", proc.returncode))
            except Exception as e:
                self._proc_subprocess = None
                self._proc_q.put(("error", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_proc_q(self):
        try:
            while True:
                item = self._proc_q.get_nowait()
                kind = item[0]
                if kind == "line":
                    line = item[1]
                    # Detect OAuth token expiry in any subprocess output
                    if any(s in line for s in ("invalid_grant", "Token has been expired",
                                               "token has been expired", "oauth2", "re-authenticate")):
                        self._proc_status_var.set(
                            "⚠ OAuth token expired — run: python cli.py push  to re-authenticate"
                        )
                        messagebox.showwarning(
                            "OAuth Token Expired",
                            "A YouTube OAuth token has expired.\n\n"
                            "To fix:\n"
                            "  1. Open a terminal in W:\\r4v\n"
                            "  2. Run:  python cli.py push\n"
                            "  3. Complete the browser sign-in\n\n"
                            "If it's Gavin's token (engage/comments), run:\n"
                            "  python cli.py engage"
                        )
                    else:
                        self._proc_status_var.set(line[:180])
                elif kind == "field_done":
                    _tup = item[1]
                    _btn, _lbl, _pw, _fkind, _val, _err = _tup[:6]
                    _popup = _tup[6] if len(_tup) > 6 else None
                    self._proc_progbar.stop()
                    self._proc_running = False
                    if hasattr(self, "_stop_btn"):
                        self._stop_btn.config(state="disabled")
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
                    self._proc_subprocess = None
                    if hasattr(self, "_stop_btn"):
                        self._stop_btn.config(state="disabled")
                    for b in (v for v in self._proc_buttons.values() if v is not None):
                        b.config(state="normal")
                    if self._proc_current_btn:
                        self._proc_current_btn.config(text=self._proc_current_label)
                    if kind == "done":
                        rc = item[1]
                        suffix = f" (exit {rc})" if rc != 0 else " — done"
                        self._proc_status_var.set(f"{self._proc_current_label}{suffix}")
                        if self._proc_auto_reload and rc == 0:
                            self._load_data(skip_autosave=True)
                        if self._proc_on_done:
                            self._proc_on_done(rc)
                            self._proc_on_done = None
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
        app = R4VReviewApp(root)
        app_container["app"] = app
        # Auto-run a background check after UI loads: fetches missing descriptions,
        # transcripts, and generates metadata for anything new — reloads when done.
        root.after(1200, lambda: app._run_cli(
            "Auto-check", ["cli.py", "check", "--force"], None, True
        ))

    def on_pipeline_error(tb: str):
        root.deiconify()
        messagebox.showerror(
            "Pipeline Error",
            f"The pipeline encountered an error:\n\n{tb[:800]}\n\n"
            "The review UI will open with whatever data is available.",
        )
        app = R4VReviewApp(root)
        app_container["app"] = app
        root.after(1200, lambda: app._run_cli(
            "Auto-check", ["cli.py", "check", "--force"], None, True
        ))

    PipelineSplash(root, on_done=on_pipeline_done, on_error=on_pipeline_error)
    root.mainloop()


if __name__ == "__main__":
    # Single-instance guard: create a named Windows mutex.
    # If it already exists ERROR_ALREADY_EXISTS (183) is returned, meaning
    # another copy of review.pyw is already running.
    _MUTEX_NAME = "Global\\R4VReviewApp_SingleInstance"
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        import tkinter as _tk
        import tkinter.messagebox as _mb
        _r = _tk.Tk()
        _r.withdraw()
        _mb.showwarning(
            "Already Running",
            "R4V Review is already open.\n\nCheck your taskbar or system tray.",
        )
        _r.destroy()
        sys.exit(0)
    main()
