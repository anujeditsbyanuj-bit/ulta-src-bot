import io
import sys
import traceback
import subprocess
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from config import ADMINS, DEV_TOOLS_ENABLED

E_CHECK = '<emoji id=5206607081334906820>✔️</emoji>'
E_CROSS = '<emoji id=5210952531676504517>❌</emoji>'
E_GEAR  = '<emoji id=5341715473882955310>⚙️</emoji>'


def _enabled():
    return DEV_TOOLS_ENABLED


async def _aexec(code: str, client: Client, message: Message):
    exec_globals = {"client": client, "message": message, "app": client}
    body = "\n".join(f"    {line}" for line in code.split("\n"))
    exec(f"async def __ex(client, message):\n{body}", exec_globals)
    return await exec_globals["__ex"](client, message)


# =========================================================
# /eval - Owner-only Python code execution (debug console)
# =========================================================

@Client.on_message(filters.command(["eval"]) & filters.user(ADMINS))
async def eval_command(client: Client, message: Message):
    if not _enabled():
        return await message.reply_text(f"<b>{E_CROSS} Dev tools are disabled.</b>", parse_mode=enums.ParseMode.HTML)
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_GEAR} Usage:</b> <code>/eval &lt;python code&gt;</code>", parse_mode=enums.ParseMode.HTML
        )

    code = message.text.split(None, 1)[1]
    old_stdout = sys.stdout
    sys.stdout = redirected = io.StringIO()
    try:
        result = await _aexec(code, client, message)
        output = redirected.getvalue()
        if result is not None:
            output += repr(result)
        if not output.strip():
            output = "(no output)"
    except Exception:
        output = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    if len(output) > 3500:
        output = output[:3500] + "\n... (truncated)"
    await message.reply_text(f"<pre>{output}</pre>", parse_mode=enums.ParseMode.HTML)


# =========================================================
# /shell - Owner-only host shell command execution
# =========================================================

@Client.on_message(filters.command(["shell", "sh"]) & filters.user(ADMINS))
async def shell_command(client: Client, message: Message):
    if not _enabled():
        return await message.reply_text(f"<b>{E_CROSS} Dev tools are disabled.</b>", parse_mode=enums.ParseMode.HTML)
    if len(message.command) < 2:
        return await message.reply_text(
            f"<b>{E_GEAR} Usage:</b> <code>/shell &lt;command&gt;</code>", parse_mode=enums.ParseMode.HTML
        )

    cmd = message.text.split(None, 1)[1]
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        output = (proc.stdout or "") + (proc.stderr or "")
        if not output.strip():
            output = f"(exit code {proc.returncode}, no output)"
    except subprocess.TimeoutExpired:
        output = "Command timed out after 60s."
    except Exception as e:
        output = f"Error: {e}"

    if len(output) > 3500:
        output = output[:3500] + "\n... (truncated)"
    await message.reply_text(f"<pre>{output}</pre>", parse_mode=enums.ParseMode.HTML)
