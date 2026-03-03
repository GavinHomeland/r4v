# PAPA.md — R4V Operator Task Tracker

> **Tip:** Run any command via `Ctrl+Shift+P` → "Tasks: Run Task" → pick an **R4V:** task.

## Current Status
> Last updated: 2026-03-03
> Pipeline last run: in progress — transcripts partially fetched (37/92)
> Videos discovered: 92

---

## Quick Commands

Run via `Ctrl+Shift+P` → **Tasks: Run Task** — all R4V tasks are listed there.

| Action | Task Name |
|--------|-----------|
| Discover new videos | `R4V: Discover videos` |
| Fetch transcripts | `R4V: Fetch transcripts` |
| Generate AI metadata | `R4V: Generate metadata (AI)` |
| Open review GUI | `R4V: Open review GUI` |
| Push approved → YouTube (dry run) | `R4V: Push dry-run` |
| Push approved → YouTube | `R4V: Push to YouTube` |
| Engage (like + comment, dry run) | `R4V: Engage (dry-run)` |
| Engage (like + comment) | `R4V: Engage` |
| Full pipeline (new videos only) | `R4V: Full pipeline (new only)` |
| Check quota usage | `R4V: Check quota` |

---

## Setup Checklist
- [x] Python 3.14 confirmed at `C:\Python314\python.exe`
- [x] `.venv` created: `C:\Python314\python.exe -m venv W:\r4v\.venv`
- [x] Dependencies installed: `.venv\Scripts\activate && pip install -r requirements.txt`
- [x] `.env` file filled in — `GEMINI_API_KEY` and `YOUTUBE_CHANNEL_ID`
- [x] GitHub repo created: https://github.com/GavinHomeland/r4v
- [ ] **[Needed for push/engage only]** Google Cloud project created (see README.md Step 3)
- [ ] **[Needed for push/engage only]** YouTube Data API v3 enabled in Google Cloud Console
- [ ] **[Needed for push/engage only]** OAuth credentials downloaded → `config/client_secret.json`
- [ ] **[Needed for push/engage only]** First-run OAuth browser login → creates `config/token.json`

---

## TODO Items

### Right Now (no extra setup needed)
- [ ] Wait for IP ban to lift (2-4 hrs), then run `R4V: Fetch transcripts` — 37/92 cached, 55 remaining
- [ ] Run `R4V: Generate metadata (AI)` — can run now on the 37 already fetched
- [ ] Open `R4V: Open review GUI` — approve / edit AI output

### Before You Can Push to YouTube
- [x] Google Cloud Console OAuth setup done — `config/client_secret.json` saved
- [x] First-run OAuth browser login done — `config/token.json` saved (hellochauncy account)
- [ ] **Re-do OAuth with etracyjob@gmail.com** — current token uses wrong account (no channel edit rights)
- [ ] Run `R4V: Push to YouTube` first batch of approved metadata

### Medium Priority
- [ ] Verify transcript quality for all videos (Shorts auto-captions can be rough)
- [ ] Review and tweak AI-generated titles for brand consistency
- [ ] Regenerate Gemini API key (exposed in chat session 2026-03-02)
- [ ] Set up Windows Task Scheduler for daily new-video processing (see Scheduling section)

### Low Priority / Future
- [ ] Add thumbnail automation (YouTube API supports thumbnail upload)
- [ ] Cross-post captions to TikTok/Instagram (reuse transcript pipeline)
- [ ] Create YouTube Shorts playlist via API
- [ ] Build Community tab posting automation

---

## Video Processing Status

| Video ID | Title (short) | Transcript | Generated | Approved | Pushed | Engaged |
|----------|---------------|-----------|-----------|----------|--------|---------|
| (run [▶ discover](command:workbench.action.terminal.sendSequence?%7B%22text%22%3A%22cd%20/w/r4v%20%26%26%20.venv/Scripts/python.exe%20cli.py%20discover%5Cn%22%7D) to populate) | | | | | | |

---

## Quota Usage Tracker

| Date | Used | Remaining | Notes |
|------|------|-----------|-------|
| (auto-tracked in data/quota_log.json) | | | |

Daily limit: 10,000 units. Safe ceiling: 9,500.
Estimated cost per full pass (~30 videos): 1,500 units.
Check current usage: `R4V: Check quota` (via Ctrl+Shift+P → Tasks: Run Task)

---

## Daily Workflow (once set up)

**Normal session — process new videos:**
1. `R4V: Full pipeline (new only)`
2. `R4V: Open review GUI` — approve / edit in GUI
3. `R4V: Push to YouTube`

**First-time / full refresh:**
1. `R4V: Fetch transcripts`
2. `R4V: Generate metadata (AI)`
3. `R4V: Open review GUI`
4. `R4V: Push dry-run` then `R4V: Push to YouTube`

---

## Windows Task Scheduler Setup (optional automation)

Create `W:\r4v\run_pipeline.bat`:
```bat
@echo off
W:\r4v\.venv\Scripts\python.exe W:\r4v\cli.py pipeline --new-only >> W:\r4v\data\pipeline.log 2>&1
```

In Task Scheduler:
- Create Basic Task → "R4V Daily Pipeline"
- Trigger: Daily, 6:00 AM
- Action: Start a program → `W:\r4v\run_pipeline.bat`
- Run whether logged in or not

Note: Push still requires manual review/approval in `review.pyw` — never automate push without human review.

---

## SEO & Visibility Strategy

1. **Publish timing**: Update metadata within 24h of upload for best algorithmic boost
2. **Title testing**: Use YouTube Studio to monitor CTR per video; swap titles if <5% CTR after 48h
3. **Playlists**: Create "Roll4Veterans Shorts" playlist manually in YouTube Studio
4. **Community tab**: Post weekly ride updates linking to recent Shorts (manual)
5. **End screens**: Add manually in YouTube Studio — not available via API for Shorts
6. **Pinned comment**: The `engage` command posts a mission-aligned comment that pins to top (boosts early engagement signal)
7. **Cross-posting**: Copy AI-generated descriptions to TikTok/Instagram; same transcript, different character limits

---

## Posting Comments as JT (Channel Identity)

### How It Works

When `cli.py engage` posts a comment, it posts **as the authenticated Google account**. If you authenticate with `etracyjob@gmail.com` (JT's account, which owns `@roll4veterans`), the comment appears as the channel — exactly as if JT posted it himself.

**We have full permission to post in JT's voice.** The AI-generated comments in `review.pyw` are written in his voice already (mission-aligned, authentic, invites engagement). Gavin edits and approves them before they go live.

### Re-authenticating as JT's Account

The current `config/token.json` was created with a different Google account. To switch:

1. Delete `config/token.json`:
   ```
   del W:\r4v\config\token.json
   ```
2. Run any CLI command that needs auth (e.g., `R4V: Push dry-run`)
3. A browser window opens — **sign in as `etracyjob@gmail.com`**
4. Grant the requested YouTube permissions
5. `config/token.json` is saved automatically — all future comments post as JT / `@roll4veterans`

### The "📌 JT Required" Flag in review.pyw

Some videos may benefit from a comment that's more personal than the AI can generate — an inside joke, a specific memory from that day, something only JT would know. Mark those with **⚑ Needs JT?** in the review GUI.

Flagged videos are **skipped by `cli.py engage`** — so Gavin won't accidentally post an off-target comment. JT can write those himself directly in YouTube Studio when he has a few minutes.

For everything else: Gavin reviews + edits the AI comment in the COMMENT field, approves the card, and `engage` posts it as `@roll4veterans`. JT's voice, automated.

### Summary

| Scenario | Who posts | How |
|----------|-----------|-----|
| Standard comment | Gavin (via `engage`) | AI draft → Gavin edits → auto-post as `@roll4veterans` |
| Personal/JT-only comment | JT directly | Flagged in GUI → JT logs into YouTube Studio → posts manually |

---

## Troubleshooting

| Problem | Solution |
|---------|---------|
| `FileNotFoundError: client_secret.json` | Download OAuth credentials from Google Cloud Console → save to `config/client_secret.json` |
| `TranscriptsDisabled` error | Video has no auto-captions yet; wait 24h or add captions manually |
| `QuotaExceededError` | Hit 9,500 unit ceiling; wait until midnight PT for reset |
| `HttpError 403` | OAuth token expired or wrong scope; delete `config/token.json` and re-run |
| YouTube IP block on transcripts | Wait 45 min, then re-run [▶ transcripts](command:workbench.action.terminal.sendSequence?%7B%22text%22%3A%22cd%20/w/r4v%20%26%26%20.venv/Scripts/python.exe%20cli.py%20transcripts%5Cn%22%7D) — rate limiting is built in |
| `json.JSONDecodeError` from Gemini | Gemini returned non-JSON; run generate with `--force --video-id=<id>` to retry |
| review.pyw won't open | Run `.venv\Scripts\python.exe W:\r4v\review.pyw` from a terminal to see errors |
| Gemini 404 model error | Check `config/settings.py` — model must be `gemini-2.5-flash-lite` |
