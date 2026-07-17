import os
import re
import aiohttp
from urllib.parse import quote, unquote, urlparse
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from Rexbots.direct_utils import (
    make_output_folder, safe_filename, stream_download, upload_file,
    E_CHECK, E_CROSS, E_INFO
)

# Reuses the same headless-Chromium setup as Rexbots/headless.py (no new
# browser/driver dependency) to render teradownloader.com, which — like the
# JS-rendered players headless.py handles — only builds its real download
# link client-side; the raw HTML is just a "Loading..." placeholder.
try:
    from playwright.async_api import async_playwright
    from Rexbots.headless import _ensure_chromium
except ImportError:
    async_playwright = None
    _ensure_chromium = None

# Single source of truth for every TeraBox / mirror domain this plugin
# handles. Rexbots/urluploader.py (the generic last-resort uploader) imports
# this tuple to build its own exclusion list, so the two plugins can never
# drift out of sync again — previously urluploader.py hard-coded only the
# original 6 domains and re-processed every link on this longer list a
# second time as a "raw file" after terabox.py had already delivered it.
TERABOX_DOMAINS = (
    "terabox.com", "1024terabox.com", "teraboxapp.com", "freeterabox.com",
    "nephobox.com", "4funbox.com", "4funbox.co", "4funbox.in", "terabox.app", "terabox.fun",
    "1024tera.com", "1024tera.co", "1024-terabox.com", "tera1024box.com",
    "mirrobox.com", "momerybox.com", "tibibox.com",
    "dubox.com", "terafileshare.com", "terasharelink.com", "teraboxlink.com",
    "terabox.link", "teraboxurl.com", "teraboxshare.com", "teraboxfree.com",
    "teraboxsharefile.com", "terabox.club", "terabox.click",
    "terasharefile.com", "terashareus.com", "gibibox.com", "pebibox.com",
    "fancybox.in", "bestclouddrive.com",
)

PATTERN = re.compile(
    r"(https?://)?(www\.)?("
    + "|".join(re.escape(d) for d in TERABOX_DOMAINS)
    + r")/\S+",
    re.IGNORECASE
)

# NOTE: savetube.me (the previous extraction API) has been permanently
# retired; teradownloader.com (rendered via headless Chromium below) is now
# the only extraction method.

_TERADOWNLOADER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def extract_url(text: str):
    m = PATTERN.search(text)
    return m.group(0) if m else None


async def _filename_from_headers(url: str) -> str | None:
    """Best-effort filename lookup via a HEAD request — teradownloader's
    scraped CDN links don't come with a filename attached the way the
    savetube API response does, but the CDN itself usually reveals one
    through Content-Disposition (or, failing that, the URL path)."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.head(url, allow_redirects=True) as resp:
                cd = resp.headers.get("Content-Disposition", "")
                m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
                if m:
                    return safe_filename(unquote(m.group(1)), "terabox_file")
                base = os.path.basename(urlparse(str(resp.url)).path)
                if base:
                    return safe_filename(base, "terabox_file")
    except Exception:
        pass
    return None


# Known TeraBox CDN domains — used to tell the real file link apart from
# teradownloader.com's own nav/preview/ad links when the primary selector
# below doesn't match cleanly.
_CDN_DOMAIN_HINTS = (
    "1024tera", "freeterabox", "terabox.app", "terabox.com",
    "4funbox", "nephobox", "terabox.link",
)


async def _collect_candidate_hrefs(page):
    """Gathers every plausible download link on the rendered page, along with
    a best-effort display name for each (used for folder links, where the
    page renders one row per file — a single-file link just ends up as a
    list of one). Tries the specific selector the site currently uses
    first, then falls back to scanning every anchor if that selector
    doesn't match (site markup may have shifted slightly) — better to
    over-collect here and filter/verify below than to miss a real link
    because of one narrow selector.

    Returns a list of (href, display_name_or_None) tuples, in document
    order, with hrefs de-duplicated (first name seen wins)."""
    items = []
    seen = set()

    def _add(href, name):
        if href and href.startswith("http") and href not in seen:
            seen.add(href)
            items.append((href, name or None))

    try:
        # Folder pages render one block per file; grabbing the block's own
        # text alongside its link lets us recover a filename per row instead
        # of just one link for the whole page.
        rows = await page.query_selector_all("div.p-5")
        for row in rows:
            anchors = await row.query_selector_all("a")
            if not anchors:
                continue
            row_text = None
            try:
                row_text = (await row.inner_text() or "").strip() or None
            except Exception:
                pass
            for a in anchors:
                href = await a.get_attribute("href")
                # Prefer the anchor's own visible text as the name; fall
                # back to the row's text if the anchor itself has none.
                a_text = None
                try:
                    a_text = (await a.inner_text() or "").strip() or None
                except Exception:
                    pass
                _add(href, a_text or row_text)
    except Exception:
        pass

    if not items:
        try:
            anchors = await page.query_selector_all("a")
            for a in anchors:
                href = await a.get_attribute("href")
                if href and "teradownloader.com" not in href:
                    a_text = None
                    try:
                        a_text = (await a.inner_text() or "").strip() or None
                    except Exception:
                        pass
                    _add(href, a_text)
        except Exception:
            pass

    return items


def _rank_candidates(items):
    """Puts items whose href matches a known TeraBox CDN domain first (most
    likely to be real files), keeping the rest as a lower-priority
    fallback. Operates on (href, name) tuples and preserves order within
    each group."""
    preferred = [it for it in items if any(hint in it[0] for hint in _CDN_DOMAIN_HINTS)]
    rest = [it for it in items if it not in preferred]
    return preferred + rest


async def _head_ok(url: str) -> bool:
    """Confirms a candidate link actually resolves to a downloadable
    response before we commit to it and start streaming it to the user."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.head(url, allow_redirects=True) as resp:
                return resp.status in (200, 206)
    except Exception:
        return False


async def _render_and_collect(page_url: str, timeout: int):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            context = await browser.new_context(user_agent=_TERADOWNLOADER_UA)
            page = await context.new_page()
            await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                await page.wait_for_selector("div.p-5 a", timeout=timeout * 1000)
            except Exception:
                pass  # fall through to the broader any-anchor scan below regardless
            # The link is sometimes populated a beat after the selector
            # first appears (async JS finishing up) — give it a moment.
            await page.wait_for_timeout(1500)
            return await _collect_candidate_hrefs(page)
        finally:
            await browser.close()


def _name_to_filename(name: str) -> str | None:
    """Turns a row's visible text (which may include size/date noise
    alongside the actual filename) into a clean filename, if the text
    looks like it contains one."""
    if not name:
        return None
    # The filename is usually the first "word group" on the row; take the
    # longest whitespace-delimited chunk that contains a dot-extension,
    # since surrounding text (file size, date, "Download" button label) is
    # what's most likely to lack one.
    candidates = re.findall(r"[^\s]+\.[A-Za-z0-9]{2,5}", name)
    if candidates:
        return safe_filename(max(candidates, key=len), None)
    return None


async def _fetch_all_via_teradownloader(link: str, timeout: int = 25):
    """Extracts direct TeraBox CDN download link(s) via teradownloader.com.

    teradownloader.com resolves the actual TeraBox CDN link(s) entirely in
    client-side JS, so this renders the page in headless Chromium via
    Playwright rather than scraping static HTML (which only ever shows a
    "Loading..." placeholder). For a single-file share link this yields one
    file; for a folder share link the same rendered page lists one row per
    file, so every verified candidate is returned rather than just the
    first — this is what gives us folder support.

    Every candidate link found is verified with a HEAD request before being
    accepted, and the whole render is retried once if the first attempt
    turns up nothing valid (the site is occasionally slow to populate
    links). Raises ValueError if nothing usable is found after that, so the
    caller can report the failure.

    Returns a list of (url, filename) tuples — one entry for a single file,
    multiple for a folder.
    """
    if async_playwright is None:
        raise ValueError("Playwright not installed — teradownloader unavailable.")

    if _ensure_chromium is not None:
        await _ensure_chromium()

    page_url = f"https://teradownloader.com/download?l={quote(link, safe='')}"

    last_error = None
    for attempt in range(2):  # one retry if the page was just slow
        try:
            items = await _render_and_collect(page_url, timeout)
        except Exception as e:
            last_error = str(e)
            continue

        results = []
        for href, name in _rank_candidates(items):
            if await _head_ok(href):
                filename = _name_to_filename(name) or await _filename_from_headers(href) or safe_filename(None, "terabox_file")
                results.append((href, filename))

        if results:
            return results

        last_error = "page rendered but no candidate link responded to a HEAD request"

    raise ValueError(
        f"teradownloader: no working download link found after 2 attempts "
        f"(site markup may have changed, or the link is invalid/private). Last issue: {last_error}"
    )


async def _handle(client: Client, message: Message, url: str):
    status = await message.reply_text(f"<b>{E_INFO} TeraBox link detected — extracting...</b>", parse_mode=enums.ParseMode.HTML)
    try:
        files = await _fetch_all_via_teradownloader(url)
    except Exception as e:
        return await status.edit_text(f"<b>{E_CROSS} Error:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)

    folder = make_output_folder("terabox")
    total = len(files)
    is_folder = total > 1
    ok_count = 0

    for idx, (direct_url, filename) in enumerate(files, start=1):
        prefix = f"[{idx}/{total}] " if is_folder else ""
        try:
            # message.id is only unique WITHIN a single chat, not globally,
            # so two users whose messages happen to share an id would
            # otherwise collide on the same filename in this shared
            # folder; include chat.id, and the file index for folders, to
            # keep every destination path globally unique.
            dest = f"{folder}/{message.chat.id}_{message.id}_{idx}_{filename}"
            await stream_download(
                direct_url, dest, status, f"{prefix}Downloading from TeraBox",
                user_id=message.from_user.id, file_name=filename
            )
            caption = f"<b>{E_CHECK} TeraBox File</b>\n<code>{filename}</code>"
            if is_folder:
                caption += f"\n<i>{idx}/{total}</i>"
            await upload_file(client, message, dest, status, caption)
            ok_count += 1
        except Exception as e:
            # One bad file in a folder shouldn't stop the rest from being
            # fetched — report it and continue to the next.
            await message.reply_text(
                f"<b>{E_CROSS} Failed:</b> <code>{filename}</code>\n<code>{e}</code>",
                parse_mode=enums.ParseMode.HTML
            )

    if is_folder:
        await status.edit_text(
            f"<b>{E_CHECK} TeraBox folder done:</b> {ok_count}/{total} file(s) delivered.",
            parse_mode=enums.ParseMode.HTML
        )


@Client.on_message(filters.text & filters.private & filters.regex(PATTERN), group=1)
async def terabox_auto_detect(client: Client, message: Message):
    url = extract_url(message.text)
    if url:
        await _handle(client, message, url)


@Client.on_message(filters.command("terabox") & filters.private)
async def terabox_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/terabox &lt;terabox URL&gt;</code>",
            parse_mode=enums.ParseMode.HTML
        )
    url = extract_url(message.command[1]) or message.command[1]
    await _handle(client, message, url)
