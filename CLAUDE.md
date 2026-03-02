# CLAUDE.md — R4V YouTube Automation

## Project Mission
Roll4Veterans (R4V) is a 4,463-mile cross-country bicycle journey from Key West, FL → Los Angeles, CA → Flagstaff, AZ (Feb 27 – Jun 21, 2026) supporting veterans through Team Red, White & Blue (Team RWB). Rider: Marcus Antonius.

- Channel: https://www.youtube.com/@roll4veterans/shorts
- Website: https://r4v.songseekers.org
- Social: @roll4veterans (FB/IG/TT/YT)

## Architecture
```
W:\r4v\
├── cli.py              # Main CLI: python cli.py <command>
├── review.pyw          # GUI review & approval tool (double-click or pythonw)
├── config/
│   ├── settings.py     # All config constants; loads .env
│   ├── client_secret.json  # OAuth2 (not committed)
│   └── token.json      # OAuth2 token (not committed)
├── r4v/
│   ├── auth.py         # OAuth2 flow for YouTube API
│   ├── channel.py      # Video discovery (yt-dlp)
│   ├── transcript.py   # Transcript fetching (youtube-transcript-api)
│   ├── content_gen.py  # Claude API metadata generation
│   ├── youtube_api.py  # YouTube Data API v3 read/write
│   ├── engagement.py   # Like + comment automation
│   ├── quota_tracker.py # Daily quota guard (10k units/day)
│   └── storage.py      # JSON file persistence
└── data/
    ├── videos.json     # Discovered video list (cache)
    ├── transcripts/    # {video_id}.json per video
    ├── generated/      # {video_id}_metadata.json (AI output)
    └── applied/        # {video_id}_applied.json (pushed)
```

## Workflow (normal operation)
1. `python cli.py pipeline` — discover + transcripts + generate
2. Open `review.pyw` — review/edit AI output, click Approve or Skip per video
3. Click "Push Approved → YouTube" in the GUI (or `python cli.py push`)
4. `python cli.py engage` — post likes + comments on approved videos

## CLI commands
| Command | What it does |
|---------|-------------|
| `python cli.py discover` | Find all channel videos via yt-dlp |
| `python cli.py transcripts` | Fetch transcripts for all videos |
| `python cli.py generate` | AI-generate metadata (Claude) |
| `python cli.py review` | Terminal diff of current vs proposed |
| `python cli.py push --dry-run` | Preview push without changing anything |
| `python cli.py push` | Apply approved metadata to YouTube |
| `python cli.py engage --dry-run` | Preview likes/comments |
| `python cli.py engage` | Post likes + comments |
| `python cli.py pipeline` | Discover → transcripts → generate |
| `python cli.py quota` | Show today's API quota usage |

## Voice & tone guidelines for content generation
- Authentic, grassroots, veteran-community-focused
- Never commercial, never preachy
- Action verbs. Short sentences. Real talk.
- Reference the route, Team RWB, Marcus Antonius, and specific locations when present in transcript
- Always include standard footer with social links (handled automatically by content_gen.py)

## Required video footer (auto-appended)
```
---
JOIN THE CONVERSATION
Have a story to share? Want to support veterans? Interested in the ride?
📱 FB/IG/TT/YT: @roll4veterans
🌐 Website: r4v.songseekers.org
[any URLs found in transcript]

[hashtags]
```

## Python environment
- Python 3.14: `C:\Python314\python.exe`
- Virtual env: `W:\r4v\.venv\`
- Activate: `.venv\Scripts\activate`
- Install deps: `pip install -r requirements.txt`

## API quotas
- YouTube Data API v3: 10,000 units/day (resets midnight PT)
- videos.update = 50 units, videos.list = 1 unit
- ~30 videos × 50 units = 1,500 units per full pass (15% of limit)
- Quota tracked in data/quota_log.json

## Key dependencies
- `anthropic` — Claude API (claude-sonnet-4-6)
- `google-api-python-client` / `google-auth-oauthlib` — YouTube Data API
- `youtube-transcript-api` — transcript reading (no API key needed)
- `yt-dlp` — channel video discovery (no API quota cost)
- `click` — CLI framework

## Known issues / gotchas
- Transcripts may not be available for very new videos (give YouTube 24h to generate)
- Auto-generated captions on Shorts can be low quality — verify critical content
- YouTube API won't let you update categoryId to an invalid value; default is 22 (People & Blogs)
- OAuth consent screen must include your Google account as a test user while app is in "Testing"
