import re
import aiohttp
from pyrogram import Client, filters, enums
from pyrogram.types import Message

from Rexbots.direct_utils import (
    make_output_folder, safe_filename, stream_download, upload_file,
    E_CHECK, E_CROSS, E_INFO
)

PATTERN = re.compile(r"(https?://)?(www\.)?gofile\.io/d/\S+", re.IGNORECASE)
GOFILE_API = "https://api.gofile.io"


def extract_url(text: str):
    m = PATTERN.search(text)
    return m.group(0) if m else None


async def _api_get(endpoint: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{GOFILE_API}{endpoint}") as resp:
            resp.raise_for_status()
            return await resp.json()


async def _handle(client: Client, message: Message, url: str):
    status = await message.reply_text(f"<b>{E_INFO} GoFile link detected...</b>", parse_mode=enums.ParseMode.HTML)
    content_id = url.split("/d/")[-1].split("?")[0].strip("/")

    try:
        data = await _api_get(f"/contents/{content_id}")
        if data.get("status") != "ok":
            raise ValueError(f"GoFile API error: {data.get('status', 'unknown')}")

        files = data["data"].get("files", {})
        if not files:
            raise ValueError("No files found in this GoFile link.")

        file_list = list(files.values())
        total = len(file_list)
        folder = make_output_folder("gofile")

        for idx, info in enumerate(file_list, 1):
            filename = safe_filename(info.get("name"), f"gofile_{idx}")
            direct_url = info.get("link") or info.get("directLink")
            if not direct_url:
                continue
            dest = f"{folder}/{message.id}_{idx}_{filename}"
            label = f"Downloading from GoFile ({idx}/{total})"
            headers = {"Cookie": f"accountToken={info.get('accountToken', '')}"} if info.get("accountToken") else None
            await stream_download(direct_url, dest, status, label, headers=headers, user_id=message.from_user.id, file_name=filename)
            await upload_file(client, message, dest, status, f"<b>{E_CHECK} GoFile</b>\n<code>{filename}</code>")
            if idx < total:
                status = await message.reply_text(f"<b>{E_INFO} Downloading next file...</b>", parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        await status.edit_text(f"<b>{E_CROSS} Error:</b>\n<code>{e}</code>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.text & filters.private & filters.regex(PATTERN), group=1)
async def gofile_auto_detect(client: Client, message: Message):
    url = extract_url(message.text)
    if url:
        await _handle(client, message, url)


@Client.on_message(filters.command("gofile") & filters.private)
async def gofile_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_INFO} Usage:</b> <code>/gofile &lt;gofile.io URL&gt;</code>",
            parse_mode=enums.ParseMode.HTML
        )
    url = extract_url(message.command[1]) or message.command[1]
    await _handle(client, message, url)
