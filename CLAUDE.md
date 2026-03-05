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
1. Open `review.pyw` → click **Pipeline ▸** (action bar) — discover + generate for new videos
2. Review/edit AI output, click Approve or Skip per video
3. Click **Push Approved → YouTube** in the action bar (or `python cli.py push`)
4. Click **Engage** in the action bar — post likes + comments on approved videos

## Scheduled background check
- `setup_task.py` registers a Windows Task Scheduler job (every 4 h) that runs `cli.py check`
- `check` discovers new videos, fetches missing transcripts, generates metadata for newly transcribed
- On next `review.pyw` open, a popup appears if new activity was found
- run_check.ps1 → called by the task scheduler

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

## review.pyw UI layout
**Row 1 (toolbar):** Title · Filter ▼ · ◀ N/Total ▶ · Jump combo · More ▼
**Row 2 (action bar, wraps on resize):**
`[Pipeline ▸]` `[Fetch Descs]` `[Transcripts]` | `[Push Approved→YouTube]` `[Engage]` | `[🎭 Personality]` | `[? Help]` `[Exit]`
**More ▼ menu:** Push Dry-Run · Engage Dry-Run · Check Quota · Reload · ↺ Reset
**Card area:** one video at a time; ◀/▶ navigate (disabled + non-clickable at boundaries)
**Proc bar:** progress bar + status text (above bottom)
**Status bar (very bottom):** Videos: N | With metadata: N | Approved: N | …

## Per-card field buttons
- `⚡` — regenerate just that field via Gemini AI (opens prompt editor)
- `🔗` — apply canonical description footer (settings.py FOOTER_TEMPLATE) preserving existing extra links
- `»` — copy current YouTube value into Proposed field

## Key dependencies
- `google-generativeai` (google-genai SDK) — Gemini AI content generation
- `google-api-python-client` / `google-auth-oauthlib` — YouTube Data API
- `youtube-transcript-api` — transcript reading (no API key needed)
- `yt-dlp` — channel video discovery (no API quota cost)
- `click` — CLI framework

## Known issues / gotchas
- Transcripts may not be available for very new videos (give YouTube 24h to generate)
- Auto-generated captions on Shorts can be low quality — verify critical content
- YouTube API won't let you update categoryId to an invalid value; default is 22 (People & Blogs)
- OAuth consent screen must include your Google account as a test user while app is in "Testing"
- IP rate-limit from YouTube on transcript fetching: wait 2-4 h, then use Transcripts button or scheduled check

## To do from Papa. Verify if unclear. 
- In the descriptions, a reference to an entity like 10BitWorks should be an inline hyperlink, if possible (if YouTube accepts hyperlinks like that... I think it does.). - Also, put a links section in the footer with clickable links.
- Put a button on the dash to bring up personalities.json for edit.
- Items under Join the Conversation are links.
- Answer these questions in papa.md
    -- Is there a difference between "Tags" (on the dashboard) and "Hashtags"? 
    -- How can I programmatically push Thumbs Up on all the videos?
    -- How can I queue all videos to play (watch all the way thru for metrics) in the bg? How do I make and maintain (add new videos) to a playlist?
    -- Do I need a new Google Cloud cred file after adding JT's email address?
- The comment didn't post (under any id) in the video that I approved and pushed. The description and all did update, so that's good. I've added JT's email address as a tester in the Google Cloud dashboard thingie. I still need to try the procedure outlined in papa.md, but the engage button should do something.
Review this information and implement concepts that make sense for us, including getting around the IP bans. https://github.com/jdepoix/youtube-transcript-api?tab=readme-ov-file#working-around-ip-bans-requestblocked-or-ipblocked-exception
    -- w:\r4v\Webshare 10 proxies.txt
    -- https://proxy.webshare.io/api/v2/proxy/list/download/qyzcfmfyeowzdhqmtutihqifoiebhihebayhdifb/-/any/username/direct/-/?plan_id=12908472
- The most important ones to be worked on are in UNLISTED status. How can that be prioritized?
- I added cookies.txt to /config. Is it working correctly?
- Put a tooltip on the little icons in the boxes (lightning bolt). Everything should have a tooltip telling what it does. 
- Videos shown on the YouTube Visibility field as "unlsted" are the highest priority. I'd like to filter those.
- I'd like to be able to do a search for the current title of a video.