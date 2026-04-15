# CLAUDE.md — R4V YouTube Automation

## Account & Identity Reference (NEVER mix these up)
| Person | YouTube handle | Google account | Token file | Role |
|--------|---------------|----------------|------------|------|
| JT (Jordan Tracy) | @roll4veterans | JT's personal (not used directly) | token_jt.json | Rider, channel owner |
| Gavin Grey (given name: Eric Tracy) | @erictracy5584 | etracyjob@gmail.com | token_gavin.json | JT's brother, channel manager |

**Who is Gavin?** Eric Tracy is his legal/given name — hence etracyjob@gmail.com and @erictracy5584.
He now goes by Gavin Grey. JT = Jordan Tracy. They are brothers (both Tracys).

**Important:** etracyjob@gmail.com is GAVIN's account. It has owner/manager access to @roll4veterans,
so token_jt.json is authenticated via Gavin's account to manage @roll4veterans on JT's behalf.

- **JT** opens video descriptions with "Hello friend!" (he's addressing everyone). In comments he uses openers like "Hey, brother —", "Hey, friend —", "Man, I tell you what —" etc.
- **Gavin** (JT's brother) addresses JT directly — opener varies: "Hi, Brother", "Hi, Bro", "Hey, Bro", "JT!" — always different, never the same phrasing twice; may refer to JT by name mid-comment
- comment_jt → posted from @roll4veterans (JT's account) — general video comment or reply to a viewer
- comment_gavin → posted from @erictracy5584 (Gavin's account) — always a reply to JT's comment thread

## Project Mission
Roll4Veterans (R4V) is a 4,463-mile cross-country bicycle journey from Key West, FL → Los Angeles, CA → Flagstaff, AZ (Feb 27 – Jun 21, 2026) supporting veterans through Team Red, White & Blue (Team RWB).

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
3. Click **Push → YouTube** in the action bar (or `python cli.py push`)
4. Engage (like + comment) runs automatically 4 seconds after a successful push — no extra click needed

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
**Row 1 (toolbar):** Title · Filter ▼ · ◀ N/Total ▶ · Jump combo · Search [×] · More ▼
**Row 2 (action bar, right-justified):** `[+ Add Video]` `[Pipeline ▸]` `[Push → YouTube]` `[? Help]` `[Exit]`
**More ▼ menu:** Pull All ▸ · Engage · Personalities (JT & Gavin) · Conversation Refresh · Mark All Done · Fetch Descriptions · Transcripts · Find Unlisted · Generate AI · Check Quota · Transcript Log · Reload · ↺ Reset
**Push → Engage:** Engage does NOT run automatically after Push. Use More ▼ › Engage manually when ready, or trigger via Conversation Refresh.
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
- "Uploaded"/draft videos are invisible to all discovery APIs — user must add by ID via Add Video dialog or `cli.py add-video`. YouTube auto-sets new uploads to Unlisted once processing finishes, so this only matters for videos stuck mid-process.

## Push / Engage patterns (hard-won lessons)
- **NEVER pre-mark approved→"external" before the push subprocess runs.** `list_approved_updates()` only returns `approved is True`. Pre-marking empties the queue before the subprocess can read it — push silently processes 0 videos and exits rc=0.
- **Pass video IDs explicitly** (`--video-id ID` repeatable) from GUI to CLI. This decouples the GUI state from the CLI's queue scan.
- **Mark "external" only on success**, in the `_on_push_done` callback, after confirming the `applied/` file was written.
- **Engagement double-posting prevention**: `applied/engagement.json` stores `{video_id: {liked, commented}}`. `run_engagement()` skips any video with both flags True. Never call engage without checking this log first.
- `--video-id` on both `push` and `engage` CLI commands accepts `multiple=True` (repeat flag). GUI passes all IDs this way.

##
##
## Claude to-do items - Move to completed when done. Ask questions if unclear. Leave this heading even if empty.
- [DONE] Multi-account engagement comment system:
    - Gemini extracts 0-3 locations from transcript; Google Maps search URLs built in comment_location
    - Comment sequence: location pin (@roll4veterans) → JT voice comment (@roll4veterans) → Gavin reply to JT's thread (@erictracy5584)
    - Likes from both @roll4veterans and @erictracy5584 (Gavin steps skip gracefully if token_gavin.json not set up)
    - Card shows LOCATION / JT / GAVIN editable comment fields
    - Personalities editor updated: title now "JT & Gavin"; both profiles visible and editable
    - Conversation Refresh: day%3==0 popup on app open + More menu item any time;
      selects random half of videos pushed in last 15 days, fetches last 3 comments,
      generates continuation via Gemini (JT or Gavin depending on last commenter),
      presents one at a time for edit/[skip], posts all approved at once

- [DONE] Add a button by the Approve button that pulls up the raw YouTube transcript (cached, probably) (read only in a pop up window. All windows should remember last position and sizing.) so I can read it.
- [DONE] add any folder with secrets to .gitignore — added token_jt.json, token_gavin.json, cookies.txt







## Completed / Answered items (archived from To do from Papa)
- [ANSWERED] Inline hyperlinks like [10BitWorks](url) in descriptions: YouTube does NOT render markdown or HTML hyperlinks. Plain URLs auto-become clickable. No implementation possible.
- [DONE] Links section in footer with clickable links: FOOTER_TEMPLATE in settings.py has a full links section (social, website, GoFundMe, Zeffy, Strava) with plain URLs — what YouTube supports.
- [DONE] Items under Join the Conversation are links: footer uses plain URLs which YouTube auto-links. Named hyperlinks are not supported by YouTube.
- Answer these questions in papa.md
    -- [ANSWERED] Tags = YouTube's internal invisible search keywords; Hashtags = #words in description that appear as clickable blue links above video title. Both generated per video. Full explanation in PAPA.md Q&A section.
    -- [ANSWERED] How can I programmatically push Thumbs Up? videos.rate(rating="like") is already in cli.py engage. Calling it again on an already-liked video does NOT unlike it — YouTube's API ignores duplicate likes.
    -- [ANSWERED] Do I need a new Google Cloud cred file after adding JT's email? No. Just delete config/token.json and re-auth as etracyjob@gmail.com.
- [WAIT] Comment didn't post — waiting to retest after JT's email (etracyjob@gmail.com) was added as OAuth tester. Procedure is in papa.md.
- [DONE] IP ban workaround: 10 Webshare proxies now active in transcript.py (GenericProxyConfig, random rotation per fetch).
    -- w:\r4v\Webshare 10 proxies.txt
    -- https://proxy.webshare.io/api/v2/proxy/list/download/qyzcfmfyeowzdhqmtutihqifoiebhihebayhdifb/-/any/username/direct/-/?plan_id=12908472
- [ANSWERED] cookies.txt in /config: No longer functional — youtube-transcript-api v1.2.4 removed cookie support upstream. Proxies are the replacement.
- [DONE] Prioritize UNLISTED videos — unlisted sort to top of list in review.pyw + availability field added to channel.py
- [DONE] Tooltips on per-card icons (lightning bolt ⚡, link 🔗, copy »). Everything needs a tooltip.
- [DONE] Filter videos by YouTube Visibility = "Unlisted" in the review UI (new "Unlisted" filter option)
- [DONE] Search by current YouTube title — search box in toolbar next to jump dropdown
- [DONE] Mark a video as "already done in YouTube Studio" (skip without overwriting) — for videos edited manually during the IP block.
- [DONE] STOP button in proc bar — terminates running subprocess, resets state
- [DONE] Update PAPA.md to reflect current state (task scheduler done, OAuth steps completed, etc.).