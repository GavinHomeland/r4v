# Roll4Veterans YouTube Automation

Automates metadata, SEO, and engagement for the [@roll4veterans](https://www.youtube.com/@roll4veterans/shorts) YouTube channel.

**Project:** 4,463-mile bike ride from Key West → LA → Flagstaff (Feb 27 – Jun 21, 2026) supporting veterans through Team RWB.

---

## Quick Start

```
.venv\Scripts\activate
python cli.py pipeline          # discover → transcripts → AI generate
# Then open review.pyw to approve
python cli.py push              # push approved metadata to YouTube
```

---

## First-Time Setup

### 1. Python environment

```
C:\Python314\python.exe -m venv W:\r4v\.venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API Keys — create `.env` in project root

```
ANTHROPIC_API_KEY=sk-ant-...
YOUTUBE_CHANNEL_ID=UCxxxxxxxxxxxxxxxxxxxxxx
```

Get your Channel ID from YouTube Studio → Settings → Channel → Advanced.

### 3. Google Cloud Console — YouTube Data API

1. Go to https://console.cloud.google.com
2. **Create project**: Click dropdown → "New Project" → name it `r4v-youtube`
3. **Enable API**: APIs & Services → Enable APIs → search **YouTube Data API v3** → Enable
4. **Create OAuth credentials**:
   - APIs & Services → Credentials → Create Credentials → **OAuth 2.0 Client ID**
   - Application type: **Desktop app**
   - Name: `r4v-desktop`
   - Download the JSON file
   - Rename it `client_secret.json`
   - Move it to `W:\r4v\config\client_secret.json`
5. **Configure consent screen**:
   - APIs & Services → OAuth consent screen
   - User type: **External** → Create
   - App name: `R4V Automation` | Support email: your email
   - Scopes: click "Add or Remove Scopes" → add `youtube.force-ssl`
   - Test users: add your YouTube channel's Google account email
   - Save and continue
6. **First OAuth run**: `python cli.py discover` → browser opens → sign in → grant permission
   - Token saved to `config/token.json` automatically
   - Subsequent runs use the saved token (auto-refreshed)

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `python cli.py discover` | Find all channel videos (yt-dlp, no quota) |
| `python cli.py transcripts` | Fetch transcripts (no API key needed) |
| `python cli.py generate` | AI-generate metadata via Claude |
| `python cli.py review` | Terminal diff: current vs proposed |
| `python cli.py push --dry-run` | Preview changes (no API writes) |
| `python cli.py push` | Apply approved metadata to YouTube |
| `python cli.py engage --dry-run` | Preview likes + comments |
| `python cli.py engage` | Post likes + comments |
| `python cli.py pipeline` | Discover → transcripts → generate |
| `python cli.py pipeline --new-only` | Only process new videos |
| `python cli.py quota` | Today's API quota status |

All commands accept `--video-id <id>` to target a single video.

---

## Review GUI

Open `review.pyw` (double-click or `C:\Python314\pythonw.exe review.pyw`) to:
- See each video with a clickable YouTube link
- Compare current vs AI-proposed metadata side by side
- Edit proposed text before approving
- Approve ✓ or Skip ✗ per video
- Push all approved videos directly from the GUI

---

## Data Files

| Path | Contents |
|------|---------|
| `data/videos.json` | Discovered video list |
| `data/transcripts/{id}.json` | Raw + joined transcript text |
| `data/generated/{id}_metadata.json` | AI-generated metadata (edit here) |
| `data/applied/{id}_applied.json` | Record of pushed updates |
| `data/applied/engagement.json` | Like/comment tracking |
| `data/quota_log.json` | Daily API quota usage |

---

## Standard Video Footer

Every description gets this footer appended automatically:

```
---
JOIN THE CONVERSATION
Have a story to share? Want to support veterans? Interested in the ride?
📱 FB/IG/TT/YT: @roll4veterans
🌐 Website: r4v.songseekers.org

#RollForVeterans #R4V ...
```

---

## Quota Budget

YouTube Data API: 10,000 units/day (resets midnight PT)

| Operation | Cost | 30-video pass |
|-----------|------|---------------|
| `videos.list` | 1 unit | 30 units |
| `videos.update` | 50 units | 1,500 units |
| `commentThreads.insert` | 50 units | 1,500 units |
| `videos.rate` | 50 units | 1,500 units |
| **Full pass (update + engage)** | | **~4,530 units (45%)** |

---

## Project Files

- `CLAUDE.md` — AI assistant context (auto-maintained)
- `PAPA.md` — Human operator tasks and tracker
- `README.md` — This file
