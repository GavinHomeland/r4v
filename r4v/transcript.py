"""Transcript fetching and processing via youtube-transcript-api."""
import json
import re
import sys
import time
import random
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.proxies import GenericProxyConfig

from config.settings import TRANSCRIPTS_DIR, PROXIES_FILE, TRANSCRIPT_LOG_JSONL, WHISPER_PYTHON, WHISPER_MODEL, COOKIES_FILE
from r4v.storage import load_json, save_json


def _log(video_id: str, method: str, result: str, detail: str = "") -> None:
    """Append one line to data/transcript_log.jsonl.

    Fields:
      ts       — ISO-8601 UTC timestamp
      video_id — YouTube video ID
      method   — 'proxy_api' | 'ytdlp' | 'cache' | 'batch'
      result   — 'ok' | 'blocked' | 'unavailable' | 'error' | 'ok_ytdlp'
      detail   — error message, char count, proxy IP hint, etc.
    """
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "video_id": video_id,
        "method": method,
        "result": result,
        "detail": detail,
    }
    try:
        with TRANSCRIPT_LOG_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # never let logging crash the fetch

# Regex for URLs mentioned in transcript text
_URL_RE = re.compile(r"https?://[^\s\"'>)]+")

# Delay between live fetches (seconds)
_MIN_DELAY = 3.0
_MAX_DELAY = 7.0

# Per-video retry on IP block
_MAX_RETRIES = 3
_RETRY_WAIT = 15  # seconds between retries

# Fallback wait when all proxies seem blocked (no proxy configured)
_BAN_WAIT_MINUTES = 60
_MAX_BAN_WAITS = 3

# Sentinel returned by fetch_transcript when IP-blocked (distinct from None = no transcript)
_BLOCKED = object()


def _cookies_args() -> list[str]:
    """Return yt-dlp --cookies arg if cookies.txt exists, else empty list."""
    if COOKIES_FILE.exists():
        return ["--cookies", str(COOKIES_FILE)]
    return []

# Cached list of proxy URLs (populated once on first use)
_proxies: list[str] | None = None


def _load_proxies() -> list[str]:
    """Parse proxy file. Format: ip:port:user:pass per line.
    Returns list of proxy URLs: http://user:pass@host:port
    """
    if not PROXIES_FILE.exists():
        return []
    urls = []
    for line in PROXIES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            urls.append(f"http://{user}:{password}@{host}:{port}")
    return urls


def _get_proxies() -> list[str]:
    global _proxies
    if _proxies is None:
        _proxies = _load_proxies()
        if _proxies:
            print(f"[transcript] Loaded {len(_proxies)} proxies from {PROXIES_FILE.name}")
        else:
            print(f"[transcript] No proxy file found at {PROXIES_FILE.name}")
    return _proxies


def _make_api() -> YouTubeTranscriptApi:
    """Build a YouTubeTranscriptApi instance using a random proxy if available.

    Note: cookies support was removed in youtube-transcript-api v1.2.4 (temporarily
    disabled upstream due to YouTube changes). Only proxy_config is supported now.
    """
    proxies = _get_proxies()
    if proxies:
        url = random.choice(proxies)
        return YouTubeTranscriptApi(
            proxy_config=GenericProxyConfig(http_url=url, https_url=url)
        )
    return YouTubeTranscriptApi()


def _is_ip_block(exc: Exception) -> bool:
    msg = str(exc)
    return (
        "RequestBlocked" in msg
        or "IpBlocked" in msg
        or "blocked" in msg.lower()
        or "too many requests" in msg.lower()
    )


_VTT_TAG_RE = re.compile(r"<[^>]+>")
_VTT_TS_RE = re.compile(
    r"(\d+):(\d+):(\d+\.\d+)\s*-->\s*(\d+):(\d+):(\d+\.\d+)"
)


def _parse_vtt(vtt_text: str) -> list[dict]:
    """Parse YouTube auto-caption VTT into segment list.

    YouTube's VTT has 'commit' blocks (exactly 10 ms apart) that contain
    clean, non-duplicated caption text without inline word-timing tags.
    """
    def _ts_sec(h, m, s):
        return int(h) * 3600 + int(m) * 60 + float(s)

    def _decode(t):
        return (t.replace("&gt;", ">").replace("&lt;", "<")
                 .replace("&amp;", "&").replace("&nbsp;", " ")
                 .replace("&#39;", "'"))

    segments = []
    seen: set[str] = set()
    for block in re.split(r"\n{2,}", vtt_text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        ts_m = None
        ts_i = None
        for i, line in enumerate(lines):
            m = _VTT_TS_RE.match(line)
            if m:
                ts_m, ts_i = m, i
                break
        if ts_m is None:
            continue
        start = _ts_sec(ts_m.group(1), ts_m.group(2), ts_m.group(3))
        end   = _ts_sec(ts_m.group(4), ts_m.group(5), ts_m.group(6))
        # Only process 10 ms commit blocks (clean, non-duplicated phrases)
        if abs((end - start) - 0.01) > 0.002:
            continue
        for tl in lines[ts_i + 1:]:
            if not tl:
                continue
            clean = _decode(_VTT_TAG_RE.sub("", tl)).strip()
            if clean and clean not in seen:
                seen.add(clean)
                segments.append({"text": clean, "start": start, "duration": 0.01})
            break
    return segments


def _fetch_via_ytdlp(video_id: str) -> dict | None:
    """Fallback: fetch transcript using yt-dlp subtitle download.

    yt-dlp uses a different request path that YouTube does not block
    the same way it blocks youtube-transcript-api. No proxy needed.
    Returns the same dict format as fetch_transcript, or None on failure.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        out_tpl = str(Path(tmpdir) / "%(id)s")
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--skip-download",
            "--write-auto-subs",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--no-warnings",
            *_cookies_args(),
            "-o", out_tpl,
            url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            stderr = proc.stderr.decode(errors="replace").strip()
        except Exception as e:
            _log(video_id, "ytdlp", "error", str(e))
            print(f"[transcript] yt-dlp error for {video_id}: {e}")
            return None

        vtt_file = Path(tmpdir) / f"{video_id}.en.vtt"
        if not vtt_file.exists():
            detail = stderr[:200] if stderr else "no .en.vtt file produced"
            _log(video_id, "ytdlp", "unavailable", detail)
            print(f"[transcript] yt-dlp: no subtitles for {video_id} — trying Whisper")
            return _fetch_via_whisper(video_id)

        vtt_text = vtt_file.read_text(encoding="utf-8")

    segments = _parse_vtt(vtt_text)
    if not segments:
        _log(video_id, "ytdlp", "error", "VTT parsed but 0 commit segments")
        print(f"[transcript] yt-dlp: VTT parsed but no usable segments for {video_id}")
        return None

    full_text = re.sub(r"\s+", " ", " ".join(s["text"] for s in segments)).strip()
    _log(video_id, "ytdlp", "ok_ytdlp", f"{len(full_text)} chars, {len(segments)} segments")
    return {
        "video_id": video_id,
        "text": full_text,
        "segments": segments,
        "urls": extract_urls(full_text),
    }


# Inline script run inside the Whisper Python environment to transcribe one file.
# Tries CUDA first (faster), falls back to CPU if cuDNN is unavailable.
_WHISPER_SCRIPT = """\
import sys, json
from faster_whisper import WhisperModel
audio, model_name = sys.argv[1], sys.argv[2]
try:
    model = WhisperModel(model_name, device="cuda", compute_type="int8")
except Exception:
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
segs, _ = model.transcribe(audio, language="en", beam_size=5)
print(json.dumps([{"text": s.text.strip(), "start": s.start, "duration": s.end - s.start}
                  for s in segs if s.text.strip()]))
"""

# Directory containing cudnn_ops_infer64_8.dll — needed by ctranslate2 for CUDA.
# Found in Miniconda a1111 env's torch/lib directory.
_CUDNN_PATH = r"C:\Users\Rufous\Miniconda3\envs\a1111\Lib\site-packages\torch\lib"


def _fetch_via_whisper(video_id: str) -> dict | None:
    """Last-resort fallback: download audio with yt-dlp, transcribe with faster-whisper.

    Used when YouTube has no auto-captions and yt-dlp VTT fetch also fails.
    Requires WHISPER_PYTHON (E:/venvs/whisperx_env_v1) to be available.
    """
    if not WHISPER_PYTHON.exists():
        _log(video_id, "whisper", "error", f"WHISPER_PYTHON not found: {WHISPER_PYTHON}")
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Download best audio (no conversion needed — whisper handles webm/m4a/opus)
        dl_cmd = [
            sys.executable, "-m", "yt_dlp",
            "--format", "bestaudio",
            "--no-warnings",
            *_cookies_args(),
            "-o", str(tmp / f"{video_id}.%(ext)s"),
            url,
        ]
        try:
            subprocess.run(dl_cmd, capture_output=True, timeout=120)
        except Exception as e:
            _log(video_id, "whisper", "error", f"audio download failed: {e}")
            return None

        audio_files = list(tmp.glob(f"{video_id}.*"))
        if not audio_files:
            _log(video_id, "whisper", "unavailable", "yt-dlp produced no audio file")
            print(f"[transcript] whisper: no audio downloaded for {video_id}")
            return None
        audio_path = audio_files[0]

        # Write the transcription script to a temp file
        script_path = tmp / "_whisper_run.py"
        script_path.write_text(_WHISPER_SCRIPT, encoding="utf-8")

        # Inject cuDNN path so ctranslate2 can find cudnn_ops_infer64_8.dll for CUDA.
        import os as _os
        env = _os.environ.copy()
        if Path(_CUDNN_PATH).exists():
            env["PATH"] = _CUDNN_PATH + _os.pathsep + env.get("PATH", "")

        try:
            proc = subprocess.run(
                [str(WHISPER_PYTHON), str(script_path), str(audio_path), WHISPER_MODEL],
                capture_output=True, text=True, timeout=300, env=env,
            )
        except Exception as e:
            _log(video_id, "whisper", "error", f"whisper subprocess failed: {e}")
            return None

    if proc.returncode != 0:
        err = proc.stderr.strip()[:200]
        _log(video_id, "whisper", "error", f"rc={proc.returncode} {err}")
        print(f"[transcript] whisper failed for {video_id}: {err[:100]}")
        return None

    try:
        seg_list = json.loads(proc.stdout)
    except Exception:
        _log(video_id, "whisper", "error", "bad JSON from whisper script")
        return None

    if not seg_list:
        _log(video_id, "whisper", "unavailable", "whisper produced 0 segments (silent/music?)")
        print(f"[transcript] whisper: no speech detected in {video_id}")
        return None

    full_text = re.sub(r"\s+", " ", " ".join(s["text"] for s in seg_list)).strip()

    # Reject hallucination-only output: Whisper often produces "you", "thank you",
    # or music notes on silence/background noise. Require at least 8 distinct words.
    _HALLUCINATION_WORDS = {"you", "thank", "music", "applause", "", "the", "a", "i", "uh", "um"}
    unique_real_words = {w.lower().strip(".,!?") for w in full_text.split()} - _HALLUCINATION_WORDS
    if len(unique_real_words) < 8:
        _log(video_id, "whisper", "unavailable",
             f"hallucination filter: only {len(unique_real_words)} distinct words: {full_text[:80]}")
        print(f"[transcript] whisper: {video_id} output looks like hallucination ({full_text[:60]!r}) — skipping")
        return None

    _log(video_id, "whisper", "ok_whisper", f"{len(full_text)} chars, {len(seg_list)} segments, model={WHISPER_MODEL}")
    print(f"[transcript] whisper: {video_id} — {len(full_text)} chars")
    return {
        "video_id": video_id,
        "text": full_text,
        "segments": seg_list,
        "urls": extract_urls(full_text),
    }


def fetch_transcript(video_id: str, force: bool = False) -> dict | object | None:
    """Fetch and cache the transcript for one video.

    Returns:
        dict   — success; keys: video_id, text, segments, urls
        None   — no transcript available (disabled / not found)
        _BLOCKED sentinel — IP-blocked after all retries
    """
    cache_path = TRANSCRIPTS_DIR / f"{video_id}.json"
    if not force and cache_path.exists():
        return load_json(cache_path)

    proxies = _get_proxies()
    _proxy_used: str = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            if proxies:
                _proxy_used = random.choice(proxies)
                api = YouTubeTranscriptApi(
                    proxy_config=GenericProxyConfig(http_url=_proxy_used, https_url=_proxy_used)
                )
            else:
                _proxy_used = "direct"
                api = YouTubeTranscriptApi()
            segments = api.fetch(video_id)
            seg_list = [
                {"text": s.text, "start": s.start, "duration": s.duration}
                for s in segments
            ]
            break  # success
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            _log(video_id, "proxy_api", "unavailable",
                 f"{type(e).__name__} proxy={_proxy_used.split('@')[-1] if '@' in _proxy_used else _proxy_used}")
            print(f"[transcript] No transcript for {video_id}: subtitles unavailable")
            return None
        except Exception as e:
            err_short = str(e)[:200]
            proxy_hint = _proxy_used.split("@")[-1] if "@" in _proxy_used else _proxy_used
            if _is_ip_block(e):
                _log(video_id, "proxy_api", "blocked",
                     f"attempt={attempt} proxy={proxy_hint} err={err_short[:80]}")
                # Try yt-dlp immediately on first block — avoids wasting time on
                # more blocked proxy retries when all proxies share the same fate.
                print(f"[transcript] IP blocked on {video_id} — trying yt-dlp fallback")
                result = _fetch_via_ytdlp(video_id)
                if result is not None:
                    save_json(cache_path, result)
                    return result
                # yt-dlp also failed; keep retrying proxies if attempts remain
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_WAIT * attempt
                    print(
                        f"[transcript] yt-dlp failed — retrying proxy "
                        f"(attempt {attempt}/{_MAX_RETRIES}, wait {wait}s)"
                    )
                    time.sleep(wait)
                    continue
                _log(video_id, "proxy_api", "blocked", f"gave up after {attempt} attempts + ytdlp")
                return _BLOCKED
            # Private/unlisted videos need cookies — try yt-dlp with auth
            if "private" in err_short.lower() or "unplayable" in err_short.lower():
                _log(video_id, "proxy_api", "blocked", f"private video — trying yt-dlp with cookies")
                print(f"[transcript] Private video {video_id} — trying yt-dlp with cookies")
                result = _fetch_via_ytdlp(video_id)
                if result is not None:
                    save_json(cache_path, result)
                    return result
                return None
            _log(video_id, "proxy_api", "error", f"proxy={proxy_hint} err={err_short}")
            print(f"[transcript] Error fetching {video_id}: {e}")
            return None
    else:
        _log(video_id, "proxy_api", "blocked", "for-else: all attempts exhausted")
        return _BLOCKED

    full_text = " ".join(s["text"] for s in seg_list)
    full_text = re.sub(r"\s+", " ", full_text).strip()

    proxy_hint = _proxy_used.split("@")[-1] if "@" in _proxy_used else _proxy_used
    _log(video_id, "proxy_api", "ok", f"{len(full_text)} chars proxy={proxy_hint}")

    data = {
        "video_id": video_id,
        "text": full_text,
        "segments": seg_list,
        "urls": extract_urls(full_text),
    }
    save_json(cache_path, data)
    return data


def extract_text(transcript_data: dict) -> str:
    """Return the full joined transcript text."""
    return transcript_data.get("text", "")


def extract_urls(text: str) -> list[str]:
    """Return a deduplicated list of URLs found in transcript text."""
    found = _URL_RE.findall(text)
    seen: set[str] = set()
    out = []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_all_transcripts(video_ids: list[str], force: bool = False) -> dict[str, dict | None]:
    """Fetch transcripts for a list of video IDs with polite delays between requests.

    Returns {video_id: dict} for successfully fetched videos.
    Videos with no transcript or that remain blocked map to None.

    The _BLOCKED sentinel from fetch_transcript is handled internally:
    - consecutive blocks increment a counter that triggers a long wait (no-proxy fallback)
    - a plain None (TranscriptsDisabled/NoTranscriptFound) does NOT count as a block
    """
    proxies = _get_proxies()
    if proxies:
        print(f"[transcript] Using {len(proxies)} proxies for IP ban avoidance")
    else:
        print("[transcript] No proxies configured — fetching anonymously (may hit IP limits)")

    results: dict[str, dict | None] = {}
    total = len(video_ids)
    consecutive_blocks = 0
    ban_waits = 0

    _log("batch", "batch", "start", f"{total} videos, force={force}, proxies={len(proxies)}")

    for i, vid in enumerate(video_ids, 1):
        cache_path = TRANSCRIPTS_DIR / f"{vid}.json"
        if not force and cache_path.exists():
            results[vid] = load_json(cache_path)
            print(f"[transcript] {i}/{total} {vid} (cached)")
            continue

        print(f"[transcript] {i}/{total} {vid}")
        result = fetch_transcript(vid, force=force)

        if result is _BLOCKED:
            # Genuine IP block — count toward ban detection
            results[vid] = None
            if not proxies:
                # Only apply the long sleep when we have no proxies to rotate
                consecutive_blocks += 1
                if consecutive_blocks >= 2:
                    ban_waits += 1
                    if ban_waits > _MAX_BAN_WAITS:
                        print(f"[transcript] Reached max ban waits ({_MAX_BAN_WAITS}). Stopping.")
                        break
                    print(
                        f"[transcript] IP ban detected (ban {ban_waits}/{_MAX_BAN_WAITS}) — "
                        f"sleeping {_BAN_WAIT_MINUTES} min then resuming..."
                    )
                    time.sleep(_BAN_WAIT_MINUTES * 60)
                    consecutive_blocks = 0
        elif result is None:
            # No transcript available — not an IP block, reset block counter
            consecutive_blocks = 0
            results[vid] = None
        else:
            consecutive_blocks = 0
            results[vid] = result

        if i < total:
            delay = random.uniform(_MIN_DELAY, _MAX_DELAY)
            time.sleep(delay)

    ok = sum(1 for v in results.values() if v is not None)
    _log("batch", "batch", "done", f"{ok}/{total} fetched")
    return results
