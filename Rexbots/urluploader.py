# Generic URL Uploader
# Ported from Url-uploader-Bot-V4 (Plugin/echo.py + Plugin/dl_button.py), rewritten
# to fit this bot's plugin style and reuse Rexbots/direct_utils.py.
#
# Every other downloader plugin in this bot (catbox, gofile, pixeldrain, mediafire,
# streamtape, terabox, mega, gdrive, ytdl's yt-dlp fallback, etc.) already claims
# its own domains. This plugin is the LAST-RESORT fallback: any bare http(s) link
# that isn't one of those known hosts, and that yt-dlp itself doesn't recognise as
# a media site, gets treated as a plain direct-download link — downloaded as-is
# and uploaded to Telegram. This is the one capability the original bot didn't
# have (it could only pull from Telegram channels / specific hosts, not from an
# arbitrary raw file URL).

import os
import re
import shutil
from urllib.parse import urlparse
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from Rexbots.direct_utils import (
    make_output_folder, safe_filename, stream_download, upload_file,
    DEFAULT_HEADERS, E_CHECK, E_CROSS, E_INFO
)
from Rexbots.torrent import _aria2c_available
from Rexbots.terabox import TERABOX_DOMAINS

GENERIC_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)

# Anything already owned by another plugin (or that shouldn't be treated as a
# raw file, like t.me links which are handled by start.py's save handler).
# ftp(s):// links never match GENERIC_URL_PATTERN at all (it's http(s)-only)
# and are handled separately by Rexbots/aria2_dl.py — listed here too just
# so a stray "ftp://..." pasted alongside an http(s) link in the same
# message can't be picked up as a raw file by mistake.
_EXCLUDED_DOMAINS = (
    "t.me", "telegram.me",
    "youtube.com", "youtu.be", "instagram.com", "instagr.am",
    "pinterest.", "pin.it",
    "facebook.com", "fb.watch", "fb.com",
    "mega.nz", "drive.google.com", "gofile.io", "mediafire.com",
    "pixeldrain.com", "streamtape.", "stape.", "catbox.moe",
    *TERABOX_DOMAINS,
    "magnet:", ".torrent",
    "twitter.com", "x.com", "pixiv.net", "deviantart.com", "artstation.com",
    "flickr.com", "tumblr.com", "reddit.com", "imgur.com",
    "danbooru.donmai.us", "gelbooru.com", "konachan.com", "yande.re",
    "safebooru.org", "zerochan.net", "furaffinity.net", "bsky.app",
    "mxplayer.in", "mxplay.com",
    "fembed.com", "fembed-hd.com", "femax20.com", "vanfem.com", "suzihaza.com",
    "embedsito.com", "owodeuwu.xyz", "plusto.link", "watchse.icu", "feurl.com",
    "vk.com", "vk.ru", ".mpd", "ftp://", "ftps://",
)


def extract_url(text: str):
    m = GENERIC_URL_PATTERN.search(text)
    if not m:
        return None
    url = m.group(0)
    lower = url.lower()
    return None if any(d in lower for d in _EXCLUDED_DOMAINS) else url


async def _handle(client: Client, message: Message, url: str):
    status = await message.reply_text(
        f"<b>{E_INFO} Link detected, downloading...</b>", parse_mode=enums.ParseMode.HTML
    )
    filename = safe_filename(url.split("/")[-1].split("?")[0], "downloaded_file")

    # Prefer aria2c when it's installed — unlike the aiohttp streamer below,
    # it keeps a .aria2 control file next to the partial download, so if the
    # connection drops mid-transfer, retrying continues from where it left
    # off instead of starting the whole file over from byte 0.
    if _aria2c_available():
        from Rexbots.aria2_dl import aria2c_download
        # message.id is only unique WITHIN a single chat, not globally, so two
        # users whose messages happen to share an id would otherwise collide;
        # include chat.id to keep folders globally unique.
        folder = os.path.join("downloads", "urluploader", f"task_{message.chat.id}_{message.id}")
        try:
            path = await aria2c_download(url, folder, status, label="Downloading (resumable)",
                                          out_name=f"{message.id}_{filename}",
                                          user_id=message.from_user.id, queue_label="URL upload")
            await upload_file(
                client, message, path, status,
                f"<b>{E_CHECK} Uploaded</b>\n<code>{filename}</code>"
            )
        except Exception as e:
            await status.edit_text(f"<b>{E_CROSS} Error:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return

    # Fallback: aria2c not installed on this host — old aiohttp streamer,
    # no resume, but still works for a plain one-shot download.
    folder = make_output_folder("urluploader")
    dest = f"{folder}/{message.id}_{filename}"

    # Many direct-file hosts/CDNs use hotlink protection that checks the
    # Referer header — without one, they serve an HTML "access denied" or
    # redirect page instead of the actual file, which is what surfaces as
    # "Server returned 'text/html'..." even for otherwise-valid links.
    # A same-origin Referer satisfies most of these checks and is a no-op
    # for hosts that don't care about it.
    parsed = urlparse(url)
    headers = dict(DEFAULT_HEADERS)
    if parsed.scheme and parsed.netloc:
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"

    try:
        await stream_download(url, dest, status, "Downloading File", headers=headers, user_id=message.from_user.id, file_name=filename)
        await upload_file(
            client, message, dest, status,
            f"<b>{E_CHECK} Uploaded</b>\n<code>{filename}</code>"
        )
    except Exception as e:
        await status.edit_text(f"<b>{E_CROSS} Error:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(
    filters.text & filters.private & filters.regex(GENERIC_URL_PATTERN) & ~filters.regex(r"^/"),
    group=4,  # absolute last resort: after specific-host handlers (1), yt-dlp's generic
              # fallback (2), and gallery-dl's generic fallback (3)
)
async def generic_url_auto_detect(client: Client, message: Message):
    url = extract_url(message.text)
    if not url:
        return

    # If yt-dlp or gallery-dl already recognises this as a media page, their
    # own generic fallbacks (group=2 / group=3) already handled it — don't
    # double-handle it here as a raw file.
    try:
        from Rexbots.ytdl import has_quality_formats
        if await has_quality_formats(url):
            return
    except Exception:
        pass
    try:
        from Rexbots.gallery import _gallery_supports
        if await _gallery_supports(url):
            return
    except Exception:
        pass

    await _handle(client, message, url)


@Client.on_message(filters.command(["url", "direct"]) & filters.private)
async def url_upload_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/url &lt;direct download link&gt;</code>\n"
            f"<i>Downloads any direct link and uploads it to Telegram.</i>",
            parse_mode=enums.ParseMode.HTML
        )
    raw = message.text.split(None, 1)[1].strip()
    url = extract_url(raw) or raw
    await _handle(client, message, url)
