# Headless-browser video URL discovery — last-resort fallback for JS-rendered
# players.
#
# yt-dlp's generic extractor only scans the raw HTML/JS it downloads; it
# never executes JavaScript. Most video sites without a dedicated yt-dlp
# extractor build the real video/manifest URL at runtime (signed tokens,
# player.js calling an API, etc.), so that URL simply never appears in the
# page source yt-dlp sees — no amount of smarter regex/parsing on our side
# can find a URL that isn't there.
#
# The only real fix is to actually render the page like a browser would and
# watch what it requests. This module does exactly that with Playwright:
# launch headless Chromium, load the page, nudge the player to start (many
# only fire the real media request after a play click), and collect any
# response that looks like a video file or streaming manifest.
#
# Requires: `pip install playwright` AND a one-time `playwright install
# chromium` (or `playwright install --with-deps chromium` to also grab the
# OS-level libraries) on the HOST — the pip package alone does not ship the
# browser binary. If that step hasn't been run, everything here degrades
# to returning None so callers just fall through to the next fallback.

import os
import re
import glob
import asyncio

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

_MEDIA_EXT_RE = re.compile(r"\.(m3u8|mpd|mp4|webm|m4s)(\?|$)", re.IGNORECASE)
_MEDIA_CT_RE = re.compile(r"(mpegurl|dash\+xml|video/mp4|video/webm)", re.IGNORECASE)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_PLAY_SELECTORS = (
    "video",
    ".vjs-big-play-button",
    ".jw-icon-playback",
    "[class*='play-button']",
    "button[aria-label*='play' i]",
)

# The Dockerfile runs `playwright install --with-deps chromium` at build
# time, so on a Docker deploy the browser is already there. Hosts that skip
# the Dockerfile (Procfile/buildpack-based Render/Railway deploys) never
# run that step, so as a safety net we self-install on first use here -
# once per process, cached after that either way.
_chromium_ensure_lock = asyncio.Lock()
_chromium_ensured = False


async def _ensure_chromium():
    global _chromium_ensured
    if _chromium_ensured:
        return
    async with _chromium_ensure_lock:
        if _chromium_ensured:
            return
        cache_dir = os.path.expanduser("~/.cache/ms-playwright")
        if glob.glob(os.path.join(cache_dir, "chromium-*")):
            _chromium_ensured = True
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "playwright", "install", "chromium",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=300)
        except Exception:
            pass  # best-effort - find_media_url below will just fail gracefully if this didn't work
        _chromium_ensured = True


def available() -> bool:
    return async_playwright is not None


async def find_media_url(page_url: str, timeout: int = 25) -> str | None:
    """Render page_url in headless Chromium and return the best-looking
    media URL seen in network traffic, or None if nothing was found (or
    Playwright/its browser isn't installed on this host)."""
    if async_playwright is None:
        return None

    await _ensure_chromium()

    candidates: list[str] = []

    def on_response(response):
        try:
            url = response.url
            ctype = response.headers.get("content-type", "")
            if _MEDIA_EXT_RE.search(url) or _MEDIA_CT_RE.search(ctype):
                candidates.append(url)
        except Exception:
            pass

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            try:
                context = await browser.new_context(user_agent=_UA)
                page = await context.new_page()
                page.on("response", on_response)

                try:
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                except Exception:
                    pass  # a slow/hanging page may still have fired useful requests already

                # Many players only issue the real media request after a
                # play click - try the obvious candidates, first one wins.
                for selector in _PLAY_SELECTORS:
                    try:
                        el = await page.query_selector(selector)
                        if el:
                            await el.click(timeout=2000)
                            break
                    except Exception:
                        continue

                await page.wait_for_timeout(6000)  # let the player start streaming
            finally:
                await browser.close()
    except Exception:
        return None

    if not candidates:
        return None

    # A master HLS/DASH manifest is more useful than a raw segment file -
    # prefer those if we saw one.
    for c in candidates:
        if ".m3u8" in c or ".mpd" in c:
            return c
    return candidates[0]
