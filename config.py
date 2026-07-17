"""
Save Restricted Content Bot Configuration

Developed by: LastPerson07XRexBots
Telegram: @RexBots_Official X @THEUPDATEDGUYS

Please retain this credit if you use or modify this project.
"""

import os


def _require(name: str, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable/secret: {name}.")
    return value


# ==============================
# Telegram Bot Credentials
# ==============================

BOT_TOKEN = _require("BOT_TOKEN", "8751062794:AAEFwtYHi_Ml0R5gyEV9bawX6qDAILniBYw")
API_ID = int(_require("API_ID", "37476811"))
API_HASH = _require("API_HASH", "7aa60670b871050820086c6267371ee6")


# ==============================
# Admin Configuration
# ==============================

# Add admin user IDs separated by commas in environment variables.
# No hardcoded fallback here on purpose: /shell and /eval (devtools.py) are
# gated on ADMINS, so silently defaulting to a baked-in ID would give that
# ID admin access (including those dangerous commands) on any deployment
# that forgets to set ADMINS explicitly. Failing loudly is safer.
ADMINS = [int(admin) for admin in _require("ADMINS").split(",") if admin]


# ==============================
# Database Configuration
# ==============================

DB_URI = _require("DB_URI", "mongodb+srv://Anujedit:Anujedit@cluster0.7cs2nhd.mongodb.net/?appName=Cluster0")
DB_NAME = os.environ.get("DB_NAME", "SaveRestricted2")


# ==============================
# Logging Configuration
# ==============================

# Telegram channel ID the bot logs to (example: -1001234567890)
LOG_CHANNEL = int(_require("LOG_CHANNEL", "-1003824246703"))

# ==============================
# Error Handling
# ==============================

# Set to True to send error messages to users
ERROR_MESSAGE = os.environ.get("ERROR_MESSAGE", "True").lower() == "true"

# ==============================
# Batch Link Limits
# ==============================

# Hard safety caps on how many messages a single batch link can request
MAX_BATCH_IDS_FREE    = int(os.environ.get("MAX_BATCH_IDS_FREE", "50"))
MAX_BATCH_IDS_PREMIUM = int(os.environ.get("MAX_BATCH_IDS_PREMIUM", "200"))

# Selectable options shown in the Settings > Batch Limit menu
BATCH_LIMIT_OPTIONS_FREE    = [10, 25, 50]
BATCH_LIMIT_OPTIONS_PREMIUM = [50, 100, 150, 200]

# ==============================
# YouTube / Instagram Downloader
# ==============================

# Max direct-download file size the bot will accept (bytes). This used to be
# capped at 2GB (Telegram's bot-upload limit), but Rexbots/direct_utils.py
# now auto-splits anything over SPLIT_SIZE (1.9GB) into parts before
# uploading, so this can safely go higher — it's just guarding against
# absurdly large / abusive downloads, not the per-file Telegram limit anymore.
YTDL_MAX_FILESIZE = int(os.environ.get("YTDL_MAX_FILESIZE", str(4 * 1024 * 1024 * 1024)))  # 4GB
YT_COOKIES    = os.environ.get("YT_COOKIES", "youtube/yt_cookies.txt")       # Netscape-format cookies.txt

# Google Drive OAuth token (enables /gdrive folder + private-file support).
# Generated locally by gdrive_oauth_setup.py, then uploaded to the bot via
# /setgdrivetoken. If missing, /gdrive just uses the public-file-only
# fallback that already worked before — nothing breaks.
GDRIVE_TOKEN_PATH = os.environ.get("GDRIVE_TOKEN_PATH", "gdrive/token.pickle")
INSTA_COOKIES = os.environ.get("INSTA_COOKIES", "Instagram/insta_cookies.txt")
FB_COOKIES    = os.environ.get("FB_COOKIES", "facebook/fb_cookies.txt")
# VK.com — only needed for private/age-restricted videos; public videos and
# clips work with no cookies at all. See Rexbots/vk.py.
VK_COOKIES    = os.environ.get("VK_COOKIES", "vk/vk_cookies.txt")

# ==============================
# YouTube Search (/search)
# ==============================

YTDL_SEARCH_PAGE_SIZE = int(os.environ.get("YTDL_SEARCH_PAGE_SIZE", "10"))

# ==============================
# Free-Access Token Gate (optional, URL-shortener based)
# ==============================

# Leave WEBSITE_URL / AD_API empty to keep this feature fully disabled.
WEBSITE_URL = os.environ.get("WEBSITE_URL", "")
AD_API      = os.environ.get("AD_API", "")
TOKEN_VALID_HOURS = int(os.environ.get("TOKEN_VALID_HOURS", "3"))
TOKEN_BATCH_BONUS = int(os.environ.get("TOKEN_BATCH_BONUS", "20"))

# ==============================
# Developer Tools (owner-only /eval, /shell)
# ==============================

# Extremely powerful — only ADMINS can ever use these regardless of this flag.
DEV_TOOLS_ENABLED = os.environ.get("DEV_TOOLS_ENABLED", "True").lower() == "true"

# ==============================
# Telegram Stars Payment Plans (/pay)
# ==============================

# label, days, star price — edit freely
STAR_PLANS = {
    "d": {"label": "1 Day",   "days": 1,  "stars": int(os.environ.get("STAR_PRICE_DAY", "15"))},
    "w": {"label": "1 Week",  "days": 7,  "stars": int(os.environ.get("STAR_PRICE_WEEK", "75"))},
    "m": {"label": "1 Month", "days": 30, "stars": int(os.environ.get("STAR_PRICE_MONTH", "250"))},
}

# ==============================
# Bot Mode (Freemium / Paid)
# ==============================

DEFAULT_BOT_MODE = os.environ.get("DEFAULT_BOT_MODE", "paid")  # "paid" or "freemium"

# ==============================
# Referral Program
# ==============================

REFERRAL_REWARD_BUCKS = int(os.environ.get("REFERRAL_REWARD_BUCKS", "50"))   # earned per successful referral
REFERRAL_TRIAL_DAYS   = int(os.environ.get("REFERRAL_TRIAL_DAYS", "1"))      # trial premium given to the new joiner
BUCKS_PER_PREMIUM_DAY = int(os.environ.get("BUCKS_PER_PREMIUM_DAY", "100"))  # redemption rate

# ==============================
# Force Subscribe (optional)
# ==============================
# Set to a channel ID/username (the bot must be an admin there) to require
# users to join before using the bot. Leave empty to keep this disabled.
FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "")

# ==============================
# Movie Info / Poster / AutoPost (optional, TMDB-powered)
# ==============================
# Get a free API key at https://www.themoviedb.org/settings/api
# Leave TMDB_API_KEY empty to keep /movieinfo, /poster and autopost disabled.
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

# Channel where the daily autopost job publishes movie release updates.
# Leave empty to keep autopost disabled even if TMDB_API_KEY is set.
AUTOPOST_CHANNEL = os.environ.get("AUTOPOST_CHANNEL", "")

# Hour (UTC, 0-23) the daily autopost job runs at.
AUTOPOST_HOUR_UTC = int(os.environ.get("AUTOPOST_HOUR_UTC", "6"))
