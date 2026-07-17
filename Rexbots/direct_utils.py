"""
Shared helpers for direct-link downloader plugins (catbox, pixeldrain, gofile,
mediafire, streamtape, terabox, mega, gdrive, torrent, gallery).

Every plugin extracts a direct download URL (or list of files) on its own,
then calls into this module to actually stream the download to disk,
build a thumbnail/metadata for videos, and upload the result to Telegram.
"""

import os
import re
import time
import random
import asyncio
import contextlib
import subprocess
import aiohttp
import requests
from pyrogram import enums

E_CHECK  = '<emoji id=5206607081334906820>✔️</emoji>'
E_CROSS  = '<emoji id=5210952531676504517>❌</emoji>'
E_ROCKET = '<emoji id=5456140674028019486>🚀</emoji>'
E_INFO   = '<emoji id=5334544901428229844>ℹ️</emoji>'
E_BOLT   = '⚡️'
E_SIZE   = '💯'
E_CLOCK  = '⌛'
E_ETA    = '💡'

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

def fmt_bytes(n):
    if not n:
        return "0B"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def fmt_duration(seconds):
    if seconds is None:
        return "0s"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def draw_bar(percent, length=12, filled="▓", empty="░"):
    percent = max(0, min(100, percent or 0))
    filled_n = round(length * percent / 100)
    return filled * filled_n + empty * (length - filled_n)


def fmt_hms(seconds):
    """MM:SS, or H:MM:SS once it runs past an hour. Used for the boxed
    progress card's Duration/ETA rows instead of fmt_duration()'s '1m 2s'
    style, since the box wants fixed-width clock formatting."""
    if seconds is None:
        return "--:--"
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _render_progress_box(header, rows):
    lines = [header, "", "╭━━━━❰ Progress ❱━━━━╮"]
    lines += [f"┣⪼ {row}" for row in rows]
    lines.append("╰━━━━━━━━━━━━━━━━╯")
    return "\n".join(lines)


def make_upload_progress(status, label="Uploading to Telegram", task_id=None,
                          file_name=None, duration=None, quality=None):
    """Returns an async progress callback for pyrogram's send_video/send_audio/
    send_document/send_photo (they accept `progress=`). Pyrogram awaits it
    directly since it's a coroutine function, calling it with (current, total)
    throughout the upload. Throttled by time + whole-percent change so it
    doesn't hit Telegram's edit rate limit on fast/local uploads.

    duration can be given as seconds (int/float) or an already-formatted
    'HH:MM:SS' string.
    """
    state = {"last_edit": 0.0, "last_pct": -1, "last_bytes": 0, "last_time": time.time()}

    async def _progress(current, total):
        now = time.time()
        pct = (current * 100 / total) if total else 0
        finished = total and current >= total
        if not finished and (now - state["last_edit"] < 2.5 or int(pct) == state["last_pct"]):
            return
        state["last_edit"] = now
        state["last_pct"] = int(pct)

        interval = now - state["last_time"]
        speed_bps = ((current - state["last_bytes"]) / interval) if interval > 0 else 0
        state["last_bytes"] = current
        state["last_time"] = now
        eta_secs = ((total - current) / speed_bps) if speed_bps > 0 else None

        bar = draw_bar(pct, length=10, filled="⬢", empty="⬡")
        header = f"<b>📤 {label}</b>"
        if task_id:
            header += f"  •  <code>{task_id}</code>"

        rows = []
        if file_name:
            rows.append(f"🎬 <b>File:</b> {file_name}")
        if duration:
            rows.append(f"⏱ <b>Duration:</b> {duration if isinstance(duration, str) else fmt_hms(duration)}")
        if quality:
            rows.append(f"🎞 <b>Quality:</b> {quality}")
        rows.append(f"📦 <b>Uploaded:</b> {fmt_bytes(current)} / {fmt_bytes(total)}")
        rows.append(f"[{bar}] {pct:.1f}%")
        rows.append(f"🚀 <b>Speed:</b> {fmt_bytes(speed_bps)}/s")
        rows.append(f"⏱️ <b>ETA:</b> {fmt_hms(eta_secs)}")

        await _status_edit(status, _render_progress_box(header, rows))

    return _progress


def format_progress(percent, speed_bps=None, done_bytes=None, total_bytes=None,
                     elapsed_secs=None, eta_secs=None, title="Downloading Video",
                     file_name=None, duration=None, quality=None) -> str:
    """Renders the standard boxed progress card used across every downloader:

    📥 Downloading Video

    ╭━━━━❰ Progress ❱━━━━╮
    ┣⪼ 🎬 File: ...
    ┣⪼ ⏱ Duration: 01:14:09
    ┣⪼ 🎞 Quality: 1080p
    ┣⪼ [⬢⬢⬢⬢⬢⬢⬢⬡⬡⬡] 76.6%
    ┣⪼ 🚀 Speed: 11.16 MB/s
    ┣⪼ ⏱️ ETA: 00:34
    ╰━━━━━━━━━━━━━━━━╯

    file_name/duration/quality rows are only shown when the caller passes
    them; existing callers that don't know these yet keep working unchanged.
    duration can be seconds (int/float) or an already-formatted string.
    """
    pct = percent if percent is not None else 0.0
    bar = draw_bar(pct, length=10, filled="⬢", empty="⬡")
    speed = f"{fmt_bytes(speed_bps)}/s" if speed_bps else "0B/s"

    header = f"<b>📥 {title}</b>"
    rows = []
    if file_name:
        rows.append(f"🎬 <b>File:</b> {file_name}")
    if duration:
        rows.append(f"⏱ <b>Duration:</b> {duration if isinstance(duration, str) else fmt_hms(duration)}")
    if quality:
        rows.append(f"🎞 <b>Quality:</b> {quality}")
    if done_bytes is not None or total_bytes is not None:
        rows.append(f"📦 <b>Size:</b> {fmt_bytes(done_bytes) if done_bytes is not None else '?'} / "
                    f"{fmt_bytes(total_bytes) if total_bytes else '?'}")
    rows.append(f"[{bar}] {pct:.1f}%")
    rows.append(f"🚀 <b>Speed:</b> {speed}")
    rows.append(f"⏱️ <b>ETA:</b> {fmt_hms(eta_secs)}")

    return _render_progress_box(header, rows)
def fmt_count(n):
    if n is None:
        return None
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return None


def fmt_upload_date(date_str):
    if not date_str or len(date_str) != 8:
        return None
    return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"


def format_forward_caption(msg, credit: str = None) -> str:
    """Builds the same style of rich metadata caption as format_media_caption(),
    but sourced from a Pyrogram Message (used for the restricted-content /save
    flow, which forwards real Telegram posts rather than yt-dlp results).

    📹 <first line of original caption, if any>
    👤 <source chat/channel name>
    ⏱ <duration>          (video/audio only)
    👁 <channel post views>  (only present on channel posts)
    📅 <post date>

    Downloaded by @<credit>
    """
    lines = []

    title = (msg.caption or "").strip().split("\n")[0][:100] if msg.caption else None
    if title:
        lines.append(f"📹 <b>{title}</b>")

    uploader = None
    if getattr(msg, "forward_from_chat", None):
        uploader = msg.forward_from_chat.title
    elif getattr(msg, "chat", None):
        uploader = msg.chat.title or msg.chat.username
    if uploader:
        lines.append(f"👤 {uploader}")

    duration = None
    if getattr(msg, "video", None):
        duration = msg.video.duration
    elif getattr(msg, "audio", None):
        duration = msg.audio.duration
    if duration:
        lines.append(f"⏱ {fmt_duration(duration)}")

    views = fmt_count(getattr(msg, "views", None))
    if views:
        lines.append(f"👁 {views}")

    post_date = getattr(msg, "forward_date", None) or getattr(msg, "date", None)
    if post_date:
        try:
            lines.append(f"📅 {post_date.strftime('%Y-%m-%d')}")
        except Exception:
            pass

    caption = "\n".join(lines) if lines else ""
    if credit:
        caption = (caption + "\n\n" if caption else "") + f"Downloaded by @{credit}"
    return caption


def format_media_caption(info: dict, credit: str = None) -> str:
    """Builds the rich metadata caption (title/channel/views/etc.) from a
    yt-dlp info dict. Only fields that are actually present are shown, since
    not every site (or every video) exposes all of them.

    📹 <title>
    👤 <uploader> @<handle>
    👥 <follower count>
    ⏱ <duration>
    👁 <views> | 👍 <likes> | 💬 <comments>
    🏷 <category>
    📅 <upload date>

    Downloaded by @<credit>
    """
    if not info:
        info = {}
    lines = []

    # Different extractors populate different fields — Instagram/Facebook
    # often leave "title" empty and put the caption text in "description"
    # instead, so fall through several fields rather than showing nothing.
    title = (
        info.get("title")
        or info.get("fulltitle")
        or (info.get("description") or "").strip().split("\n")[0][:100]
        or None
    )
    if title:
        lines.append(f"📹 <b>{title}</b>")

    uploader = (
        info.get("uploader") or info.get("channel") or info.get("uploader_id")
    )
    handle = info.get("uploader_id") or info.get("channel_id") or info.get("channel_handle")
    if uploader or handle:
        who = uploader or ""
        if handle and str(handle) != str(uploader):
            handle_str = f"@{handle}" if not str(handle).startswith("@") else str(handle)
            who = f"{who} {handle_str}".strip()
        lines.append(f"👤 {who}")

    followers = fmt_count(info.get("channel_follower_count"))
    if followers:
        lines.append(f"👥 {followers}")

    duration = info.get("duration")
    if duration:
        lines.append(f"⏱ {fmt_duration(duration)}")

    views = fmt_count(info.get("view_count"))
    likes = fmt_count(info.get("like_count"))
    comments = fmt_count(info.get("comment_count"))
    stats = [f"👁 {v}" for v in [views] if v]
    if likes:
        stats.append(f"👍 {likes}")
    if comments:
        stats.append(f"💬 {comments}")
    if stats:
        lines.append(" | ".join(stats))

    categories = info.get("categories") or ([info["category"]] if info.get("category") else None)
    if categories:
        lines.append(f"🏷 {categories[0]}")

    date_str = fmt_upload_date(info.get("upload_date"))
    if date_str:
        lines.append(f"📅 {date_str}")

    caption = "\n".join(lines) if lines else f"<b>{E_CHECK} Downloaded via yt-dlp</b>"
    if credit:
        caption += f"\n\nDownloaded by @{credit}"
    return caption


VIDEO_EXTS = ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.3gp', '.flv', '.m4v')
AUDIO_EXTS = ('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus')
PHOTO_EXTS = ('.jpg', '.jpeg', '.png', '.webp')

# Telegram bot accounts can upload up to 2GB per file (the 4GB cap is only
# for Premium *user* accounts, not bots). Leave a safety margin below that
# so a part with metadata/rounding never tips over the real server limit.
SPLIT_SIZE = int(1.9 * 1024 * 1024 * 1024)  # 1.9GB


async def _status_edit(status, text, parse_mode=enums.ParseMode.HTML):
    """Edits a status message whether it's a text message or a photo
    message (in which case the caption has to be edited instead)."""
    if status is None:
        return
    try:
        if getattr(status, "photo", None):
            await status.edit_caption(text, parse_mode=parse_mode)
        else:
            await status.edit_text(text, parse_mode=parse_mode)
    except Exception:
        pass  # e.g. "message not modified" — safe to ignore


async def split_file(path: str, status=None, chunk_size: int = SPLIT_SIZE):
    """Splits `path` into <=chunk_size parts, returning a list of part paths
    (the original file is left untouched — caller is responsible for
    removing it once all parts are uploaded).

    Video files are split with ffmpeg's segment muxer using stream copy, so
    each part stays a valid, independently playable video (much nicer than a
    raw byte-split, which would corrupt every part except the first). Any
    other file type is split as raw bytes, since there's no container to
    keep valid — the parts just get concatenated back on the receiving end.
    """
    ext = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path)
    if size <= chunk_size:
        return [path]

    if ext in VIDEO_EXTS:
        parts = await asyncio.to_thread(_split_video_ffmpeg, path, chunk_size, ext)
        if parts:
            return parts
        # fall through to raw split if ffmpeg segmenting failed for some reason

    return await asyncio.to_thread(_split_raw_bytes, path, chunk_size)


def _split_video_ffmpeg(path: str, chunk_size: int, ext: str):
    """Uses ffmpeg's segment muxer (stream copy, no re-encode) to cut a video
    into roughly chunk_size-sized, independently playable parts. Segment
    duration is estimated from the average bitrate so parts land close to
    chunk_size rather than being wildly over/under."""
    size = os.path.getsize(path)
    duration, _, _ = get_video_metadata(path)
    if not duration:
        return None

    bitrate = size / duration  # bytes/sec
    segment_time = max(30, int(chunk_size / bitrate * 0.97))  # 3% safety margin

    base, _ = os.path.splitext(path)
    out_pattern = f"{base}.part%03d{ext}"
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
             "-c", "copy", "-map", "0", "-f", "segment",
             "-segment_time", str(segment_time), "-reset_timestamps", "1",
             "-y", out_pattern],
            timeout=1800, check=True
        )
    except Exception:
        return None

    parts = sorted(
        f for f in os.listdir(os.path.dirname(path) or ".")
        if os.path.basename(f).startswith(os.path.basename(base) + ".part")
    )
    parts = [os.path.join(os.path.dirname(path), p) for p in parts]
    parts = [p for p in parts if os.path.exists(p) and os.path.getsize(p) > 0]

    # Any single part still over the limit (e.g. one huge keyframe interval)
    # falls back to a raw byte split for just that part — better an oversized
    # container split than a failed upload.
    fixed = []
    for p in parts:
        if os.path.getsize(p) > chunk_size:
            fixed.extend(_split_raw_bytes(p, chunk_size))
            os.remove(p)
        else:
            fixed.append(p)
    return fixed or None


def _split_raw_bytes(path: str, chunk_size: int):
    parts = []
    base = path
    idx = 0
    with open(path, "rb") as src:
        while True:
            data = src.read(chunk_size)
            if not data:
                break
            idx += 1
            part_path = f"{base}.{idx:03d}"
            with open(part_path, "wb") as dst:
                dst.write(data)
            parts.append(part_path)
    return parts


def make_output_folder(service: str) -> str:
    folder = os.path.join("downloads", service)
    os.makedirs(folder, exist_ok=True)
    return folder


def safe_filename(name: str, fallback: str) -> str:
    name = (name or "").strip().strip("/\\")
    if not name:
        return fallback
    # strip characters that break filesystem paths
    return "".join(c for c in name if c not in '\\/:*?"<>|') or fallback


def make_ffmpeg_progress_parser(total_duration: float, title: str = "Processing..."):
    """Returns a parse_line(line, elapsed) function for run_subprocess_with_progress
    that reads ffmpeg's own stderr progress ('time=00:01:23.45 speed=1.2x ...')
    and renders it with format_progress(), using total_duration (seconds,
    from get_video_metadata()) to compute a percentage."""
    time_re = re.compile(r'time=(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)')
    speed_re = re.compile(r'speed=\s*([\d.]+)x')

    def parse_line(line, elapsed):
        m = time_re.search(line)
        if not m:
            return None
        h, mi, s = m.groups()
        done_secs = int(h) * 3600 + int(mi) * 60 + float(s)
        pct = max(0, min(100, (done_secs / total_duration * 100) if total_duration else 0))
        speed_m = speed_re.search(line)
        speed_x = float(speed_m.group(1)) if speed_m else None
        eta = ((total_duration - done_secs) / speed_x) if (speed_x and total_duration and speed_x > 0) else None
        bar = draw_bar(pct)
        text = (
            f"<b>{E_BOLT} {title}</b>\n\n"
            f"<b>Progress:</b> <code>{bar}</code> {pct:.1f}%\n"
            f"{E_CLOCK} <b>Processed:</b> {fmt_duration(done_secs)} of {fmt_duration(total_duration)}\n"
            f"{E_ROCKET} <b>Speed:</b> {speed_x or 0:.2f}x\n"
            f"{E_ETA} <b>ETA:</b> {fmt_duration(eta)}"
        )
        return text

    return parse_line


async def run_subprocess_with_progress(cmd, status, label, parse_line, interval: float = 3.0,
                                        user_id: int = None, queue_label: str = None):
    """Runs `cmd`, streaming its combined stdout live instead of buffering the
    whole output with communicate() (which is why mega/torrent/gallery had no
    progress before — communicate() only returns once the process exits).

    Tools like aria2c/megatools redraw their progress line in place using
    carriage returns ('\\r') rather than newlines, so we read raw bytes and
    split on both '\\r' and '\\n' to catch every update.

    parse_line(line: str, elapsed: float) -> str | None
        Given one output line and seconds elapsed since the process started,
        return an HTML status text to show (typically built with
        format_progress()), or None to ignore that line. Edits are throttled
        to `interval` seconds so we don't hit Telegram's rate limit.

    user_id / queue_label: if user_id is given, this call registers itself
    with task_manager (same as stream_download()) so it shows up in /queue
    and can be stopped via /cancel_all.

    If the awaiting asyncio.Task gets cancelled (e.g. via /cancel_all, or
    the bot shutting down) the child process is explicitly killed instead of
    being left running as an orphan in the background — cancelling the
    *coroutine* alone does not stop a subprocess it spawned.

    Returns (returncode, last_stderr_tail).
    """
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )

    task_id = None
    if user_id is not None:
        try:
            from Rexbots import task_manager
            task_id = task_manager.register(user_id, asyncio.current_task(), queue_label or label)
        except Exception:
            task_id = None

    buf = b""
    last_edit = 0.0
    tail = b""

    try:
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            tail = (tail + chunk)[-2000:]  # keep a tail in case we need it for an error message

            while True:
                cut = -1
                for sep in (b"\r", b"\n"):
                    idx = buf.find(sep)
                    if idx != -1 and (cut == -1 or idx < cut):
                        cut = idx
                if cut == -1:
                    break
                line, buf = buf[:cut], buf[cut + 1:]
                elapsed = time.monotonic() - start
                try:
                    text = parse_line(line.decode(errors="replace").strip(), elapsed)
                except Exception:
                    text = None
                if text:
                    now = time.monotonic()
                    if status is not None and now - last_edit >= interval:
                        last_edit = now
                        await _status_edit(status, text)

        await proc.wait()
        return proc.returncode, tail.decode(errors="replace").strip()
    except asyncio.CancelledError:
        # The task was cancelled (e.g. /cancel_all) — without this, aria2c/
        # the child process keeps running in the background forever since
        # cancelling our coroutine does nothing to the OS process it spawned.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    finally:
        if proc.returncode is None:
            # Any other unexpected exit from this function (e.g. status.edit
            # raising) — make sure we never leak a running child process.
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        if task_id is not None:
            from Rexbots import task_manager
            task_manager.unregister(user_id, task_id)


_HTML_SIGNATURES = ("<!doctype", "<html", "<head", "<body", "<?xml")


def _looks_like_html_error(first_bytes: bytes) -> bool:
    """Detects an HTML/error page masquerading as a downloaded file — the
    root cause of 'file saves as HTML' reports. A real direct-file host
    virtually never returns a payload starting with these tags."""
    head = first_bytes[:300].lstrip().lower()
    return any(head.startswith(sig.encode()) or sig.encode() in head[:150] for sig in _HTML_SIGNATURES)


async def stream_download(url: str, dest: str, status, label: str,
                           headers: dict = None, timeout: int = 300,
                           user_id: int = None, file_name: str = None) -> int:
    """Streams url -> dest with periodic status.edit_text progress updates.
    Returns total bytes downloaded. Raises ValueError on HTTP/network failure
    OR when the response is clearly an HTML/error page rather than the file
    that was requested (expired link, login wall, host down, wrong URL,
    rate-limited, etc.) — previously that page got saved as-is with the
    target filename, which is why downloads were coming out as HTML.

    If user_id is given, this registers the currently-running task with
    task_manager so it shows up in /queue and can be stopped via
    /cancel_all — callers just need to pass their message.from_user.id,
    no extra bookkeeping required.

    file_name is optional — pass it when already known (most callers parse
    it out before downloading) so the progress box shows a File row."""
    headers = headers or DEFAULT_HEADERS
    start = time.monotonic()
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    task_id = None
    if user_id is not None:
        try:
            from Rexbots import task_manager
            task_id = task_manager.register(user_id, asyncio.current_task(), label)
        except Exception:
            task_id = None

    try:
        return await _stream_download_inner(
            url, dest, status, label, headers, timeout_cfg, start, file_name
        )
    finally:
        if task_id is not None:
            from Rexbots import task_manager
            task_manager.unregister(user_id, task_id)


async def _stream_download_inner(url, dest, status, label, headers, timeout_cfg, start, file_name=None) -> int:
    downloaded = 0
    last_edit = 0.0
    first_chunk = None

    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status not in (200, 206):
                raise ValueError(f"HTTP {resp.status} while downloading")

            content_type = resp.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise ValueError(
                    f"Server returned '{content_type}' instead of a file — "
                    "the link is likely expired, private, or wrong."
                )

            total = int(resp.headers.get("Content-Length", 0))

            try:
                with open(dest, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        if not chunk:
                            continue
                        if first_chunk is None:
                            first_chunk = chunk
                            if _looks_like_html_error(first_chunk):
                                raise ValueError(
                                    "Downloaded content is an HTML/error page, not the actual "
                                    "file — the link is likely expired, private, or requires login."
                                )
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.monotonic()
                        if status is not None and now - last_edit >= 3:
                            last_edit = now
                            elapsed = now - start
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            pct = (downloaded / total * 100) if total else 0
                            eta = ((total - downloaded) / speed) if (total and speed > 0) else None
                            await _status_edit(
                                status,
                                format_progress(pct, speed_bps=speed, done_bytes=downloaded,
                                                 total_bytes=total or None, elapsed_secs=elapsed,
                                                 eta_secs=eta, title=label, file_name=file_name)
                            )
            except ValueError:
                try:
                    os.remove(dest)
                except Exception:
                    pass
                raise

    if downloaded == 0:
        try:
            os.remove(dest)
        except Exception:
            pass
        raise ValueError("Downloaded 0 bytes — server sent an empty response.")

    return downloaded


def download_official_thumbnail(info: dict, thumb_path: str) -> bool:
    """Downloads the actual thumbnail image the site provides (from yt-dlp's
    info dict) and converts/scales it to a Telegram-friendly JPEG, instead of
    grabbing a random frame out of the video with ffmpeg.

    Picks the highest-resolution thumbnail listed, since yt-dlp's "thumbnails"
    list is ordered from lowest to highest quality.
    """
    if not info:
        return False
    thumb_url = None
    thumbs = info.get("thumbnails") or []
    if thumbs:
        thumb_url = thumbs[-1].get("url")
    thumb_url = thumb_url or info.get("thumbnail")
    if not thumb_url:
        return False

    raw_path = thumb_path + ".src"
    try:
        resp = requests.get(thumb_url, timeout=20)
        resp.raise_for_status()
        with open(raw_path, "wb") as f:
            f.write(resp.content)
    except Exception:
        return False

    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", raw_path,
             "-vf", "scale=320:-1", "-y", thumb_path],
            timeout=30, check=True
        )
        return os.path.exists(thumb_path)
    except Exception:
        return False
    finally:
        try:
            os.remove(raw_path)
        except Exception:
            pass


def extract_thumbnail(video_path: str, thumb_path: str) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = float(probe.stdout.strip() or "10")
    except ValueError:
        duration = 10.0
    seek = random.uniform(duration * 0.1, duration * 0.8) if duration > 1 else 0
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(seek),
             "-i", video_path, "-vframes", "1", "-vf", "scale=320:-1", "-y", thumb_path],
            timeout=30, check=True
        )
        return os.path.exists(thumb_path)
    except Exception:
        return False


def get_video_metadata(video_path: str):
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = int(float(dur.stdout.strip() or "0"))
    except ValueError:
        duration = 0
    dim = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, timeout=30
    )
    try:
        w, h = dim.stdout.strip().split(",")
        width, height = int(w), int(h)
    except Exception:
        width, height = 1280, 720
    return duration, width, height


async def _send_one(client, message, path: str, caption: str, progress):
    """Sends a single file (one part, or the whole file if not split) as
    video/audio/photo/document based on its extension. Returns the thumb
    path it created (if any) so the caller can clean it up."""
    ext = os.path.splitext(path)[1].lower()
    thumb = None

    if ext in VIDEO_EXTS:
        thumb = path + ".jpg"
        has_thumb = await asyncio.to_thread(extract_thumbnail, path, thumb)
        duration, width, height = await asyncio.to_thread(get_video_metadata, path)
        await client.send_video(
            chat_id=message.chat.id, video=path,
            thumb=thumb if has_thumb else None,
            duration=duration, width=width, height=height,
            caption=caption, reply_to_message_id=message.id,
            supports_streaming=True, parse_mode=enums.ParseMode.HTML,
            progress=progress
        )
    elif ext in AUDIO_EXTS:
        await client.send_audio(
            chat_id=message.chat.id, audio=path,
            caption=caption, reply_to_message_id=message.id,
            parse_mode=enums.ParseMode.HTML,
            progress=progress
        )
    elif ext in PHOTO_EXTS:
        await client.send_photo(
            chat_id=message.chat.id, photo=path,
            caption=caption, reply_to_message_id=message.id,
            parse_mode=enums.ParseMode.HTML,
            progress=progress
        )
    else:
        await client.send_document(
            chat_id=message.chat.id, document=path,
            caption=caption, reply_to_message_id=message.id,
            parse_mode=enums.ParseMode.HTML,
            progress=progress
        )
    return thumb


async def upload_file(client, message, path: str, status, caption: str):
    """Sends a downloaded file to Telegram as video/audio/photo/document
    based on its extension, then cleans up the local copy. If the file is
    bigger than Telegram's bot upload limit, it's split into parts first
    (see split_file()) and each part is uploaded and cleaned up in turn."""
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0

    parts = [path]
    if size > SPLIT_SIZE:
        await _status_edit(status, f"<b>{E_BOLT} File is {fmt_bytes(size)} — splitting before upload...</b>")
        parts = await split_file(path, status=status)

    total_parts = len(parts)
    try:
        for i, part_path in enumerate(parts, start=1):
            thumb = None
            try:
                label = "Uploading..." if total_parts == 1 else f"Uploading part {i}/{total_parts}..."
                await _status_edit(status, f"<b>{E_ROCKET} {label}</b>")
                progress = make_upload_progress(status, label=label)
                part_caption = caption if total_parts == 1 else f"{caption}\n\n<b>Part {i}/{total_parts}</b>"

                thumb = await _send_one(client, message, part_path, part_caption, progress)

                try:
                    part_size = os.path.getsize(part_path)
                except OSError:
                    part_size = 0
                try:
                    from Rexbots.user_stats import record_usage
                    # Only count one success per original file, not per part.
                    await record_usage(message.from_user.id, uploaded_bytes=part_size,
                                        success_count=(1 if i == total_parts else 0))
                except Exception:
                    pass  # usage stats are best-effort and must never break an upload
            finally:
                # Remove the part (if it's not the original, unsplit file)
                # and its thumb right away, so we don't hold disk for every
                # part until the whole batch finishes.
                if part_path != path:
                    try:
                        os.remove(part_path)
                    except Exception:
                        pass
                if thumb:
                    try:
                        os.remove(thumb)
                    except Exception:
                        pass

        await status.delete()
    finally:
        # `path` itself: removed here once, whether it was uploaded directly
        # (single part == path) or split into separate part files (in which
        # case `path` was left untouched by split_file/the loop above).
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
