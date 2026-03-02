# PAPA.md — R4V Operator Task Tracker

## Current Status
> Last updated: 2026-03-02
> Pipeline last run: never
> Videos processed: 0

---

## Setup Checklist
- [ ] Python 3.14 confirmed at `C:\Python314\python.exe`
- [ ] `.venv` created: `C:\Python314\python.exe -m venv W:\r4v\.venv`
- [ ] Dependencies installed: `.venv\Scripts\activate && pip install -r requirements.txt`
- [ ] `.env` file filled in with real API keys
- [ ] Google Cloud project created (see README.md for full guide)
- [ ] YouTube Data API v3 enabled in Google Cloud Console
- [ ] OAuth 2.0 Desktop credentials downloaded → `config/client_secret.json`
- [ ] Google account added as test user in OAuth consent screen
- [ ] First-run OAuth: `python cli.py discover` (triggers browser login)
- [ ] `config/token.json` created automatically after OAuth

---

## TODO Items

### High Priority
- [ ] Complete Google Cloud Console setup (see README.md)
- [ ] Add ANTHROPIC_API_KEY and YOUTUBE_CHANNEL_ID to `.env`
- [ ] Run first pipeline: `python cli.py pipeline`
- [ ] Review AI output in `review.pyw`
- [ ] Push first batch of updated metadata

### Medium Priority
- [ ] Verify transcript quality for all videos (Shorts auto-captions can be rough)
- [ ] Review and tweak AI-generated titles for brand consistency
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
| (run `python cli.py discover` to populate) | | | | | | |

---

## Quota Usage Tracker

| Date | Used | Remaining | Notes |
|------|------|-----------|-------|
| (auto-tracked in data/quota_log.json) | | | |

Daily limit: 10,000 units. Safe ceiling: 9,500.
Estimated cost per full pass (~30 videos): 1,500 units.

---

## Daily Workflow (once set up)

**For new videos:**
```
.venv\Scripts\activate
python cli.py pipeline --new-only   # only process new videos
```
Then open `review.pyw`, approve, and push.

**Full refresh:**
```
python cli.py pipeline --force      # re-fetch and re-generate everything
```

**Push approved:**
```
python cli.py push --dry-run        # preview first
python cli.py push
```

**Engagement:**
```
python cli.py engage --dry-run
python cli.py engage
```

---

## Windows Task Scheduler Setup (optional automation)

Create `W:\r4v\run_pipeline.bat`:
```bat
@echo off
call W:\r4v\.venv\Scripts\activate
python W:\r4v\cli.py pipeline --new-only >> W:\r4v\data\pipeline.log 2>&1
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

## Troubleshooting

| Problem | Solution |
|---------|---------|
| `FileNotFoundError: client_secret.json` | Download OAuth credentials from Google Cloud Console → save to `config/client_secret.json` |
| `TranscriptsDisabled` error | Video has no auto-captions yet; wait 24h or add captions manually |
| `QuotaExceededError` | Hit 9,500 unit ceiling; wait until midnight PT for reset |
| `HttpError 403` | OAuth token expired or wrong scope; delete `config/token.json` and re-run |
| `json.JSONDecodeError` from Claude | Claude returned non-JSON; run `python cli.py generate --force --video-id=<id>` to retry |
| review.pyw won't open | Run `C:\Python314\pythonw.exe W:\r4v\review.pyw` from a terminal to see errors |
