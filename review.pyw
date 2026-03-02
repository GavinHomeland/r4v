"""
review.pyw — R4V Metadata Review & Approval GUI
Run with: C:\Python314\pythonw.exe review.pyw   (no console window)
     or:  double-click in Windows Explorer
"""
import ctypes
import json
import os
import subprocess
import sys
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

# ── Colours ───────────────────────────────────────────────────────────────────
CLR_BG = "#1e1e2e"
CLR_PANEL = "#2a2a3e"
CLR_BORDER = "#3a3a5c"
CLR_TEXT = "#cdd6f4"
CLR_MUTED = "#6c7086"
CLR_CURRENT = "#313244"
CLR_PROPOSED = "#1e3a2a"
CLR_LINK = "#89dceb"
CLR_APPROVE = "#a6e3a1"
CLR_SKIP = "#f38ba8"
CLR_BTN_BG = "#45475a"
CLR_HEADER = "#cba6f7"

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
        # Status label vars
        self._status_vars: dict[str, tk.StringVar] = {}

        self._build_ui()
        self._load_data()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = tk.Frame(self.root, bg=CLR_PANEL, pady=6)
        toolbar.pack(fill="x", side="top")

        tk.Label(
            toolbar,
            text="  R4V Metadata Review",
            bg=CLR_PANEL,
            fg=CLR_HEADER,
            font=(FONT_FAMILY, 14, "bold"),
        ).pack(side="left", padx=10)

        self._summary_var = tk.StringVar(value="Loading…")
        tk.Label(
            toolbar,
            textvariable=self._summary_var,
            bg=CLR_PANEL,
            fg=CLR_MUTED,
            font=(FONT_FAMILY, 10),
        ).pack(side="left", padx=20)

        # Right-side buttons
        btn_frame = tk.Frame(toolbar, bg=CLR_PANEL)
        btn_frame.pack(side="right", padx=10)

        self._make_btn(btn_frame, "Approve All", self._approve_all, CLR_APPROVE).pack(side="left", padx=4)
        self._make_btn(btn_frame, "Skip All", self._skip_all, CLR_SKIP).pack(side="left", padx=4)
        self._make_btn(btn_frame, "Push Approved → YouTube", self._push_approved, "#89b4fa").pack(side="left", padx=4)
        self._make_btn(btn_frame, "Reload", self._reload, CLR_BTN_BG).pack(side="left", padx=4)
        self._make_btn(btn_frame, "Exit", self.root.destroy, CLR_BTN_BG).pack(side="left", padx=4)

        # ── Scrollable body ───────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=CLR_BG)
        body.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(body, bg=CLR_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._scroll_frame = tk.Frame(self._canvas, bg=CLR_BG)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw"
        )

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _make_btn(self, parent, text, cmd, color):
        return tk.Button(
            parent,
            text=text,
            command=cmd,
            bg=color,
            fg="#000000",
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
        )

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_data(self):
        # Clear existing widgets
        for w in self._scroll_frame.winfo_children():
            w.destroy()
        self._widgets.clear()
        self._status_vars.clear()

        self._videos, self._metadata = load_all_data()

        # Build video_id → video lookup
        self._video_map = {v["id"]: v for v in self._videos}

        # Build cards for every video that has generated metadata
        video_ids_with_meta = list(self._metadata.keys())
        # Also add videos without metadata (show as "pending generation")
        for v in self._videos:
            if v["id"] not in self._metadata:
                video_ids_with_meta.append(v["id"])

        for vid in video_ids_with_meta:
            self._build_video_card(vid)

        self._update_summary()

    def _reload(self):
        self._load_data()

    # ── Video card ────────────────────────────────────────────────────────────

    def _build_video_card(self, video_id: str):
        video = self._video_map.get(video_id, {})
        meta = self._metadata.get(video_id)
        url = get_video_url(video_id)

        existing_title = video.get("title", "") or (meta.get("existing_title", "") if meta else "")
        existing_desc = video.get("description", "")
        existing_tags = tags_to_str(video.get("tags", []))

        has_meta = meta is not None
        approval = meta.get("approved") if meta else None  # None/True/False

        # ── Card frame ────────────────────────────────────────────────────────
        card = tk.Frame(self._scroll_frame, bg=CLR_PANEL, pady=8, padx=12)
        card.pack(fill="x", padx=8, pady=6)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = tk.Frame(card, bg=CLR_PANEL)
        hdr.pack(fill="x")

        status_var = tk.StringVar(value=self._approval_label(approval))
        self._status_vars[video_id] = status_var

        tk.Label(
            hdr,
            textvariable=status_var,
            bg=CLR_PANEL,
            fg=self._approval_color(approval),
            font=(FONT_FAMILY, 10, "bold"),
            width=12,
            anchor="w",
        ).pack(side="left")

        tk.Label(
            hdr,
            text=f"  {existing_title or video_id}",
            bg=CLR_PANEL,
            fg=CLR_TEXT,
            font=(FONT_FAMILY, 11, "bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Clickable link
        link = tk.Label(
            hdr,
            text="▶ Watch",
            bg=CLR_PANEL,
            fg=CLR_LINK,
            font=(FONT_FAMILY, 10, "underline"),
            cursor="hand2",
        )
        link.pack(side="left", padx=8)
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        # Approve / Skip buttons
        btn_row = tk.Frame(hdr, bg=CLR_PANEL)
        btn_row.pack(side="left")

        self._make_btn(
            btn_row, "✓ Approve",
            lambda vid=video_id: self._set_approval(vid, True),
            CLR_APPROVE,
        ).pack(side="left", padx=2)

        self._make_btn(
            btn_row, "✗ Skip",
            lambda vid=video_id: self._set_approval(vid, False),
            CLR_SKIP,
        ).pack(side="left", padx=2)

        if not has_meta:
            tk.Label(
                card,
                text="  (no generated metadata yet — run: python cli.py generate)",
                bg=CLR_PANEL,
                fg=CLR_MUTED,
                font=(FONT_FAMILY, 9, "italic"),
            ).pack(anchor="w", pady=4)
            return

        # ── Fields ────────────────────────────────────────────────────────────
        widgets = {}
        self._widgets[video_id] = widgets

        proposed_title = meta.get("title", "")
        proposed_desc = meta.get("description", "")
        proposed_tags = tags_to_str(meta.get("tags", []))
        proposed_hashtags = meta.get("hashtags", "")

        fields = [
            ("TITLE", existing_title, proposed_title, "single"),
            ("DESCRIPTION", existing_desc, proposed_desc, "multi"),
            ("TAGS", existing_tags, proposed_tags, "single"),
            ("HASHTAGS", "", proposed_hashtags, "single"),
        ]

        for label, current_val, proposed_val, kind in fields:
            row = tk.Frame(card, bg=CLR_PANEL, pady=3)
            row.pack(fill="x")

            tk.Label(
                row,
                text=f"  {label}",
                bg=CLR_PANEL,
                fg=CLR_MUTED,
                font=(FONT_MONO, 9, "bold"),
                width=12,
                anchor="w",
            ).pack(side="left", anchor="n")

            cols = tk.Frame(row, bg=CLR_PANEL)
            cols.pack(fill="x", expand=True)

            # Current (read-only)
            cur_frame = tk.LabelFrame(
                cols, text="Current", bg=CLR_CURRENT, fg=CLR_MUTED,
                font=(FONT_FAMILY, 8), padx=4, pady=2,
            )
            cur_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

            if kind == "multi":
                cur_w = tk.Text(
                    cur_frame, height=4, wrap="word",
                    bg=CLR_CURRENT, fg=CLR_MUTED,
                    font=(FONT_MONO, 9),
                    relief="flat", state="disabled",
                )
                cur_w.pack(fill="both", expand=True)
                cur_w.config(state="normal")
                cur_w.insert("1.0", current_val)
                cur_w.config(state="disabled")
            else:
                cur_w = tk.Entry(
                    cur_frame,
                    bg=CLR_CURRENT, fg=CLR_MUTED,
                    font=(FONT_MONO, 9),
                    relief="flat", state="readonly",
                    readonlybackground=CLR_CURRENT,
                )
                cur_w.pack(fill="x")
                cur_w.config(state="normal")
                cur_w.insert(0, current_val)
                cur_w.config(state="readonly")

            # Proposed (editable)
            prop_frame = tk.LabelFrame(
                cols, text="Proposed  (editable)", bg=CLR_PROPOSED, fg=CLR_APPROVE,
                font=(FONT_FAMILY, 8), padx=4, pady=2,
            )
            prop_frame.pack(side="left", fill="both", expand=True)

            if kind == "multi":
                prop_w = tk.Text(
                    prop_frame, height=6, wrap="word",
                    bg=CLR_PROPOSED, fg=CLR_TEXT,
                    font=(FONT_MONO, 9),
                    relief="flat", insertbackground=CLR_TEXT,
                )
                prop_w.pack(fill="both", expand=True)
                prop_w.insert("1.0", proposed_val)
            else:
                prop_w = tk.Entry(
                    prop_frame,
                    bg=CLR_PROPOSED, fg=CLR_TEXT,
                    font=(FONT_MONO, 9),
                    relief="flat", insertbackground=CLR_TEXT,
                )
                prop_w.pack(fill="x")
                prop_w.insert(0, proposed_val)

            widgets[label.lower()] = prop_w

        # Separator
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

        # Read current proposed values from widgets
        widgets = self._widgets.get(video_id, {})
        if widgets:
            for field, w in widgets.items():
                if isinstance(w, tk.Text):
                    meta[field] = w.get("1.0", "end-1c")
                elif isinstance(w, tk.Entry):
                    meta[field] = w.get()
            # Reconstruct description from 'description' widget
            if "description" in meta:
                pass  # already updated above
            # Re-parse tags back to list
            if "tags" in meta and isinstance(meta["tags"], str):
                meta["tags"] = str_to_tags(meta["tags"])

        meta["approved"] = approved
        path = GENERATED_DIR / f"{video_id}_metadata.json"
        save_json(path, meta)

        # Update status label
        if video_id in self._status_vars:
            self._status_vars[video_id].set(self._approval_label(approved))
            # Update label colour (re-build is too heavy; use tag or StringVar trick)

        self._update_summary()

    def _approve_all(self):
        for vid in self._metadata:
            if self._metadata[vid].get("approved") is None:
                self._set_approval(vid, True)
        self._update_summary()

    def _skip_all(self):
        for vid in self._metadata:
            if self._metadata[vid].get("approved") is None:
                self._set_approval(vid, False)
        self._update_summary()

    def _update_summary(self):
        total = len(self._metadata)
        approved = sum(1 for m in self._metadata.values() if m.get("approved") is True)
        skipped = sum(1 for m in self._metadata.values() if m.get("approved") is False)
        pending = total - approved - skipped
        all_videos = len(self._videos)
        self._summary_var.set(
            f"Videos: {all_videos}  |  With metadata: {total}  |  "
            f"Approved: {approved}  |  Skipped: {skipped}  |  Pending: {pending}"
        )

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

    def _find_python(self) -> str:
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return str(venv_python)
        # Fall back to the Python running this script
        return sys.executable


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()

    # Apply a base ttk theme that plays well with dark overrides
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    app = R4VReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
