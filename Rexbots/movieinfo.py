# Rexbots
# Movie Info / Poster (TMDB) — ported from Url-uploader-Bot-V4
# (Plugin/movieinfo.py + Plugin/poster.py), merged and rewritten with aiohttp
# to match the rest of Rexbots' async style.
# Don't Remove Credit
# Telegram Channel @RexBots_Official

import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from config import TMDB_API_KEY, ADMINS

E_CROSS = '<emoji id=5210952531676504517>❌</emoji>'

BASE_URL = "https://api.themoviedb.org/3"

LANG_MAP = {
    "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "ml": "Malayalam", "kn": "Kannada",
    "en": "English", "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati",
    "pa": "Punjabi", "or": "Odia", "as": "Assamese", "ur": "Urdu",
}


def _is_configured():
    return bool(TMDB_API_KEY)


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        return await resp.json()


def _parse_name_year(command: list):
    if len(command) > 2 and command[-1].isdigit() and len(command[-1]) == 4:
        return " ".join(command[1:-1]), command[-1]
    return " ".join(command[1:]), None


async def _search_movie(session, name, year):
    url = f"{BASE_URL}/search/movie?api_key={TMDB_API_KEY}&query={name}"
    if year:
        url += f"&year={year}"
    resp = await _get_json(session, url)
    results = resp.get("results", [])
    return results[0] if results else None


async def get_poster_url(session, movie_id):
    url = f"{BASE_URL}/movie/{movie_id}/images?api_key={TMDB_API_KEY}&include_image_language=hi,en,null"
    try:
        resp = await _get_json(session, url)
    except Exception:
        return None
    backdrops = resp.get("backdrops", [])
    posters = resp.get("posters", [])

    for b in backdrops:
        if b.get("iso_639_1") == "hi":
            return f"https://media.themoviedb.org/t/p/w1000_and_h563_face{b['file_path']}"
    for b in backdrops:
        if b.get("iso_639_1") == "en":
            return f"https://media.themoviedb.org/t/p/w1000_and_h563_face{b['file_path']}"
    if posters:
        return f"https://image.tmdb.org/t/p/original{posters[0]['file_path']}"
    if backdrops:
        return f"https://media.themoviedb.org/t/p/w1000_and_h563_face{backdrops[0]['file_path']}"
    return None


def format_caption(details, directors, top_actors, languages):
    title = details.get("title")
    release_date = details.get("release_date", "N/A")
    year = release_date.split("-")[0] if release_date else "N/A"
    overview = details.get("overview", "No description available.")
    genres = ", ".join(g["name"] for g in details.get("genres", [])) or "N/A"
    runtime = details.get("runtime", "N/A")

    return (
        f"🎬 <b>{title}</b> ({year})\n\n"
        f"<b>🗓 Release Date:</b> <code>{release_date}</code>\n"
        f"<b>⏱ Runtime:</b> <code>{runtime} min</code>\n"
        f"<b>🌐 Languages:</b> <code>{languages}</code>\n"
        f"<b>🎭 Genres:</b> <code>{genres}</code>\n"
        f"<b>🎬 Director:</b> <code>{directors}</code>\n"
        f"<b>⭐ Cast:</b> <code>{top_actors}</code>\n\n"
        f"📝 <code>{overview}</code>"
    )


@Client.on_message(filters.command("movieinfo") & filters.user(ADMINS))
async def movieinfo_command(client: Client, message: Message):
    if not _is_configured():
        return await message.reply_text(
            f"<b>{E_CROSS} TMDB_API_KEY is not set.</b> Add it in Secrets to enable this command.",
            parse_mode=enums.ParseMode.HTML
        )
    if len(message.command) < 2:
        return await message.reply_text("❌ Usage: <code>/movieinfo movie name [year]</code>", parse_mode=enums.ParseMode.HTML)

    name, year = _parse_name_year(message.command)
    status = await message.reply_text(f"🔎 Searching for <b>{name}</b>...", parse_mode=enums.ParseMode.HTML)

    try:
        async with aiohttp.ClientSession() as session:
            movie = await _search_movie(session, name, year)
            if not movie:
                return await status.edit_text(f"❌ No results found for {name} ({year or ''}).")

            movie_id = movie["id"]
            details = await _get_json(session, f"{BASE_URL}/movie/{movie_id}?api_key={TMDB_API_KEY}&language=en-US")
            credits = await _get_json(session, f"{BASE_URL}/movie/{movie_id}/credits?api_key={TMDB_API_KEY}&language=en-US")

            cast = credits.get("cast", [])
            crew = credits.get("crew", [])
            top_actors = ", ".join(a["name"] for a in cast[:10]) or "N/A"
            directors = [m["name"] for m in crew if m.get("job") == "Director"]
            director_names = ", ".join(directors) if directors else "N/A"

            spoken_langs = details.get("spoken_languages", [])
            langs = [LANG_MAP.get(l["iso_639_1"], l.get("english_name", "?")) for l in spoken_langs]
            languages = ", ".join(langs) if langs else "N/A"

            poster_url = await get_poster_url(session, movie_id)
            caption = format_caption(details, director_names, top_actors, languages)

        await status.delete()
        if poster_url:
            await message.reply_photo(poster_url, caption=caption, parse_mode=enums.ParseMode.HTML)
        else:
            await message.reply_text(caption, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        await status.edit_text(f"❌ Error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("poster") & filters.user(ADMINS))
async def poster_command(client: Client, message: Message):
    if not _is_configured():
        return await message.reply_text(
            f"<b>{E_CROSS} TMDB_API_KEY is not set.</b> Add it in Secrets to enable this command.",
            parse_mode=enums.ParseMode.HTML
        )
    if len(message.command) < 2:
        return await message.reply_text("❌ Usage: <code>/poster movie name [year]</code>", parse_mode=enums.ParseMode.HTML)

    name, year = _parse_name_year(message.command)
    status = await message.reply_text(f"🔎 Searching posters for <b>{name}</b>...", parse_mode=enums.ParseMode.HTML)

    try:
        async with aiohttp.ClientSession() as session:
            movie = await _search_movie(session, name, year)
            if not movie:
                return await status.edit_text(f"❌ Movie '{name}' not found.")
            poster_url = await get_poster_url(session, movie["id"])

        await status.delete()
        title = movie.get("title", name)
        if poster_url:
            await message.reply_photo(poster_url, caption=f"🎬 <b>{title}</b>", parse_mode=enums.ParseMode.HTML)
        else:
            await message.reply_text(f"❌ No poster found for {title}.")
    except Exception as e:
        await status.edit_text(f"❌ Error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML)
