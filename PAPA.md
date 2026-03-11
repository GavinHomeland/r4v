# PAPA.md — R4V Operator Task Tracker

> **Tip:** Run any command via `Ctrl+Shift+P` → "Tasks: Run Task" → pick an **R4V:** task.

## Current Status
> Last updated: 2026-03-10
> Pipeline: fully operational — discover (yt-dlp + API), transcripts (proxy rotation), AI generate (Gemini), push + publish + playlist, engage (like + comment)
> New video workflow: set new uploads to **Unlisted** in Studio → pipeline auto-discovers and populates → Approve → Push publishes + adds to playlist
> Draft/"Uploaded" videos must be added manually via **Add Video** button (paste Studio URL)

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
- [x] Google Cloud project created
- [x] YouTube Data API v3 enabled in Google Cloud Console
- [x] OAuth credentials downloaded → `config/client_secret.json`
- [x] First-run OAuth browser login done (re-auth as etracyjob@gmail.com if comments fail)

---

## TODO Items

### Right Now
- [ ] Add remaining "Uploaded" (draft) videos via **Add Video** button (paste Studio URL): March 9 2026, Leaving NC, Other warehouse 2, Dinky wipers, Nash — Musings already added
- [ ] Run Pipeline in review.pyw to fetch transcripts + generate AI metadata for those videos
- [ ] Approve the generated metadata cards → Push to YouTube (publishes + adds to playlist)
- [ ] Run Engage on newly pushed videos (like + comment as @roll4veterans)

### Before You Can Push to YouTube
- [x] Google Cloud Console OAuth setup done — `config/client_secret.json` saved
- [x] OAuth with etracyjob@gmail.com (JT's account) — token.json saved, push works
- [x] Sunset thoughts pushed successfully; push popup now confirms success/failure

### Medium Priority
- [ ] Verify transcript quality for all videos (Shorts auto-captions can be rough)
- [ ] Review and tweak AI-generated titles for brand consistency
- [ ] Regenerate Gemini API key (exposed in chat session 2026-03-02)
- [x] Set up Windows Task Scheduler for daily new-video processing (see Scheduling section)

### Low Priority / Future
- [ ] Add thumbnail automation (YouTube API supports thumbnail upload)
- [ ] Cross-post captions to TikTok/Instagram (reuse transcript pipeline)
- [ ] Create YouTube Shorts playlist via API
- [ ] Build Community tab posting automation

---

## Video Processing Status <== is this section supposed to do something, Claude?>

| Video ID | Title (short) | Transcript | Generated | Approved | Pushed | Engaged |
|----------|---------------|-----------|-----------|----------|--------|---------|
| (run [▶ discover](command:workbench.action.terminal.sendSequence?%7B%22text%22%3A%22cd%20/w/r4v%20%26%26%20.venv/Scripts/python.exe%20cli.py%20discover%5Cn%22%7D) to populate) | | | | | | |

---

## Quota Usage Tracker <== and this one? Seems like this is available in the review app.>

| Date | Used | Remaining | Notes |
|------|------|-----------|-------|
| (auto-tracked in data/quota_log.json) | | | |

Daily limit: 10,000 units. Safe ceiling: 9,500.
Estimated cost per full pass (~30 videos): 1,500 units.
Check current usage: `R4V: Check quota` (via Ctrl+Shift+P → Tasks: Run Task)

---

## Daily Workflow (once set up)

**Normal session — process new videos:**
1. Open `review.pyw` (double-click or `R4V: Open review GUI`) — startup pipeline runs automatically
2. If new videos were found, click **Pipeline ▸** to fetch transcripts + generate AI metadata
3. **Review each card** — edit if needed, then click ✓ Approve, ✗ Skip, or 🏷 Done in Studio
4. Click **Push Approved → YouTube** — publishes + adds to R4V playlist
5. Click **Engage** — like + comment on newly pushed videos

**First-time / full refresh (no scheduled task):**
1. `R4V: Fetch transcripts` (may need multiple runs if IP-blocked)
2. `R4V: Generate metadata (AI)` or use **Pipeline ▸** button
3. Open `review.pyw` → review → approve
4. Click **Push Approved → YouTube**

---

## Adding New Videos to the System

### Recommended workflow for new uploads
1. Upload video to YouTube Studio
2. **Set visibility to Unlisted** (not "Uploaded"/draft) before closing Studio
3. Next pipeline run (or every-4h scheduled check) will auto-discover it, fetch transcript, generate AI metadata
4. **⏸ Human review** — open review.pyw, inspect each card:
   - ✓ **Approve** — ready to push
   - ✗ **Skip** — not ready, revisit later
   - 🏷 **Done in Studio** — you edited it manually; exclude from automation
5. Click **Push Approved → YouTube** — publishes to Public + adds to R4V playlist
6. Click **Engage** — posts like + comment as @roll4veterans

### Why "Uploaded" (draft) videos don't auto-discover
YouTube's API has no endpoint to list draft videos. The uploads playlist API only returns Published videos (public or unlisted). **Draft = invisible to all discovery methods.** Setting to Unlisted takes one click and makes everything automatic.

### Adding a draft video manually (one-time workaround)
If a video is already stuck as "Uploaded/draft":
1. Open **review.pyw** → More ▼ → **Add Video** (or click the Add Video button in the action bar)
2. Paste the Studio URL: `https://studio.youtube.com/video/VIDEO_ID/edit`
3. Click **Add** — the app fetches metadata and adds it to the list
4. Run **Pipeline ▸** to fetch transcript and generate AI metadata

Or via CLI: `python cli.py add-video VIDEO_ID`

---

## Windows Task Scheduler (automated background check)

Already set up via `setup_task.py`. Runs every 4 hours:
- Discovers new videos, fetches missing transcripts, generates AI metadata
- Writes `data/check_state.json` — review.pyw shows a popup on next open if there's new activity

**Manage the task:**
```
Run now:  schtasks /Run /TN "R4V YouTube Check"
Status:   schtasks /Query /TN "R4V YouTube Check" /V /FO LIST
Remove:   schtasks /Delete /TN "R4V YouTube Check" /F
Re-setup: python setup_task.py
```

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
| YouTube IP block on transcripts | Proxies handle this automatically; if all 10 proxies fail, wait ~2h and retry |
| `json.JSONDecodeError` from Gemini | Gemini returned non-JSON; run generate with `--force --video-id=<id>` to retry |
| review.pyw won't open | Run `.venv\Scripts\python.exe W:\r4v\review.pyw` from a terminal to see errors |
| Gemini 404 model error | Check `config/settings.py` — model must be `gemini-2.5-flash-lite` |
| New video not discovered by pipeline | If it shows "Uploaded" (not "Unlisted") in Studio, use Add Video button to add by ID |
| review.pyw already running warning | Only one instance allowed; check taskbar/system tray for the existing window |
| Push succeeded but video still shows old metadata | YouTube may take a few minutes to reflect changes; check Studio directly |
 
 ## Notes:
 In 2026, YouTube’s algorithm has shifted away from simply counting "vanity metrics" (like likes and subscribes) toward a deeper focus on **viewer satisfaction** and **AI-driven intent matching**.

While likes, shares, and subscribes still play a role, they are now secondary to how well your video actually serves the person watching it. Here is the hierarchy of what increases visibility today:

### 1. The "Big Two": Satisfaction & Retention

The algorithm no longer just asks, "Did they click?" It asks, "Was it worth their time?"

* **Average View Duration (AVD):** This is the single strongest signal. If people stay for 70% of your video, YouTube will push it to thousands more. If they leave in 10 seconds, the video "dies."
* **Viewer Satisfaction Surveys:** YouTube now regularly serves "Was this video a good use of your time?" surveys. High satisfaction scores can make a video go viral even if it has fewer likes than others.
* **"Hype" Feature:** For channels under 500k subscribers, the new **Hype** button allows fans to physically boost a video’s visibility on regional leaderboards, giving smaller creators a significant organic lift.

### 2. Click-Through Rate (CTR) vs. Substance

While your thumbnail and title must be "clickable," the AI now analyzes your video frame-by-frame.

* **AI Contextual Awareness:** YouTube's AI "watches" your video to see if the content actually matches the title. If you use clickbait that doesn't deliver, the algorithm will detect the "disconnect" and stop recommending you, regardless of your CTR.
* **Thumbnail A/B Testing:** You can now upload up to three thumbnails in YouTube Studio. The system automatically picks the winner based on which one generates the most **watch time**, not just the most clicks.

### 3. Engagement Velocity (Likes, Comments, Shares)

These are considered "Engagement Velocity" signals—basically, how much noise a video makes in its first 48 hours.

* **Likes & Comments:** These act as "social proof." They tell the algorithm the content is sparking a reaction. **Replying to comments** within the first 24 hours is a massive signal that your channel is an active community, which increases your "Trust Score."
* **Shares:** Sharing to private groups (WhatsApp, Discord) or other social platforms is a high-value signal because it brings "External Sessions" to YouTube, which the platform loves.

### 4. Format Synergy: Shorts as a "Funnel"

In 2026, visibility is often a "multi-format" game:

* **The Shorts Hook:** Using vertical Shorts to "tease" your long-form content is the most effective way to reach new audiences.
* **Binge-Watching (Session Time):** If your video leads a viewer to watch a *second* video (even someone else's), YouTube rewards you. Using **Playlists** and **End Screens** is essential for this.

### Summary Table: What to Prioritize

| Priority | Metric | Why it matters in 2026 |
| --- | --- | --- |
| **Highest** | **Retention / AVD** | Proves the content is actually good. |
| **High** | **Satisfaction Surveys** | AI uses these to determine if you are "serving" the user. |
| **Medium** | **CTR** | Gets people in the door (but must match the content). |
| **Moderate** | **Likes / Shares** | Signals "velocity" and community health. |
| **Low** | **Subscribers** | Follower count is now less important than individual video performance. |

---

**Would you like me to analyze your "10BitWorks" video description to see how we can optimize it for these specific 2026 keywords and "Search Everywhere Optimization"?**
---

## Q&A

### Tags vs Hashtags — what's the difference?

**They are completely different fields that serve different purposes.**

**Tags** (the `TAGS` field in the review dashboard) are YouTube's internal keyword list. Viewers never see them. They affect how YouTube's search and recommendation algorithm understands what your video is about. YouTube uses tags as hints — "this video is about cycling, veterans, Team RWB, Florida." Good tags are a mix of broad terms (cycling, veterans) and specific content terms (Team RWB, Roll4Veterans, Key West). We generate 15–20 per video.

**Hashtags** (the `HASHTAGS` field, displayed below TAGS in the dashboard) are `#words` embedded in the video description. YouTube extracts them and displays them as clickable blue links above the video title in the player. When a viewer clicks `#TeamRWB`, they go to a feed of all videos using that hashtag. They DO affect discoverability — especially on Shorts. We generate 12–16 per video following the rules in `config/personalities.json`.

**In short:** Tags are invisible search signals. Hashtags are visible, clickable links above the video title.

---

### Video Processing Status table

This table was designed for manual tracking. With 106+ videos it's not practical to maintain by hand. **Use the review.pyw dashboard instead** — it shows real-time counts in the status bar at the bottom (Videos, With metadata, Approved, Skipped, Pending). For a full list, use the Filter dropdown or Jump combo in the GUI.

---

### Quota Usage Tracker table

Same situation — the table here is a manual placeholder. **Use `R4V: Check quota` from the VSCode task menu** (or More ▼ → Check Quota in review.pyw) to see live quota usage from `data/quota_log.json`.

