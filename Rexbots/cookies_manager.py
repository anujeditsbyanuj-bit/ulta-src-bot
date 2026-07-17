# Generic per-domain cookies store.
#
# config.py only ever wired up cookies for three hardcoded sites (YouTube,
# Instagram, Facebook). A lot of "quality options are missing" / "site wants
# a login" problems on OTHER sites are simply because yt-dlp is fetching
# the page logged-out, and the page serves a smaller/lower-quality format
# list (or an entirely different, JS-stub page) to anonymous visitors.
#
# This lets an admin upload a Netscape-format cookies.txt for ANY domain,
# which ytdl.py's _cookies_for() then picks up automatically for every
# link from that domain (and its subdomains) - no code change needed per
# site.
#
# Usage:
#   /setcookies example.com                — then send the cookies.txt file
#   /setcookies example.com  (as a document caption, file attached directly)
#   /listcookies                            — see which domains have cookies set
#   /delcookies example.com                 — remove them

import os
import re
from urllib.parse import urlparse
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from config import ADMINS

E_CHECK = '<emoji id=5206607081334906820>✔️</emoji>'
E_CROSS = '<emoji id=5210952531676504517>❌</emoji>'
E_INFO  = '<emoji id=5334544901428229844>ℹ️</emoji>'

COOKIES_DIR = "cookies/custom"
os.makedirs(COOKIES_DIR, exist_ok=True)

# user_id -> domain, set by /setcookies while waiting for the file to follow
# as the user's next message.
_pending_setcookies: dict[int, str] = {}


def _sanitize_domain(raw: str) -> str:
    raw = raw.strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.split("/")[0].split(":")[0]
    if raw.startswith("www."):
        raw = raw[4:]
    return re.sub(r"[^a-z0-9.\-]", "", raw)


def _cookie_path(domain: str) -> str:
    return os.path.join(COOKIES_DIR, f"{domain}.txt")


def get_cookies_for_url(url: str) -> str | None:
    """Used by ytdl.py: does this URL's domain (or a parent of it) have a
    custom cookies.txt an admin uploaded via /setcookies? Checks most
    specific to least specific (sub.example.com, then example.com)."""
    try:
        netloc = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    except Exception:
        return None
    parts = netloc.split(".")
    for i in range(len(parts) - 1):  # never falls all the way to a bare TLD
        candidate = ".".join(parts[i:])
        path = _cookie_path(candidate)
        if os.path.exists(path):
            return path
    return None


async def _save_cookie_file(message: Message, domain: str):
    dest = _cookie_path(domain)
    try:
        await message.download(file_name=dest)
    except Exception as e:
        return await message.reply_text(
            f"<b>{E_CROSS} Failed to save cookies:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML
        )
    await message.reply_text(
        f"<b>{E_CHECK} Cookies saved for <code>{domain}</code></b>\n"
        f"<i>Links from this domain (and its subdomains) will now use these cookies automatically.</i>",
        parse_mode=enums.ParseMode.HTML
    )


@Client.on_message(filters.command("setcookies") & filters.private & filters.user(ADMINS))
async def setcookies_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/setcookies example.com</code>\n"
            f"<i>Then send the Netscape-format cookies.txt file as your next message "
            f"(or attach it directly to this command).</i>",
            parse_mode=enums.ParseMode.HTML
        )
    domain = _sanitize_domain(message.command[1])
    if not domain or "." not in domain:
        return await message.reply_text(f"<b>{E_CROSS} Invalid domain.</b>", parse_mode=enums.ParseMode.HTML)

    if message.document:
        return await _save_cookie_file(message, domain)

    _pending_setcookies[message.from_user.id] = domain
    await message.reply_text(
        f"<b>{E_INFO} Got it.</b> Now send the cookies.txt file for <code>{domain}</code>.",
        parse_mode=enums.ParseMode.HTML
    )


# group=-1 so this is checked BEFORE rename.py's group=0 catch-all document
# handler. It only ever acts (and only ever calls stop_propagation) when a
# /setcookies is actually pending for this user - any other document upload
# passes straight through untouched, exactly as before.
@Client.on_message(filters.private & filters.document, group=-1)
async def setcookies_file_receive(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        return
    domain = _pending_setcookies.pop(user_id, None)
    if not domain:
        return
    await _save_cookie_file(message, domain)
    message.stop_propagation()


@Client.on_message(filters.command("listcookies") & filters.private & filters.user(ADMINS))
async def listcookies_command(client: Client, message: Message):
    files = sorted(f[:-4] for f in os.listdir(COOKIES_DIR) if f.endswith(".txt"))
    if not files:
        return await message.reply_text(f"<b>{E_INFO} No custom cookies set.</b>", parse_mode=enums.ParseMode.HTML)
    text = f"<b>{E_INFO} Custom cookies set for:</b>\n" + "\n".join(f"• <code>{d}</code>" for d in files)
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command(["delcookies", "clearcookies"]) & filters.private & filters.user(ADMINS))
async def delcookies_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(f"<b>{E_INFO} Usage:</b> <code>/delcookies example.com</code>", parse_mode=enums.ParseMode.HTML)
    domain = _sanitize_domain(message.command[1])
    path = _cookie_path(domain)
    if os.path.exists(path):
        os.remove(path)
        await message.reply_text(f"<b>{E_CHECK} Removed cookies for <code>{domain}</code></b>", parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text(f"<b>{E_CROSS} No cookies found for <code>{domain}</code></b>", parse_mode=enums.ParseMode.HTML)
