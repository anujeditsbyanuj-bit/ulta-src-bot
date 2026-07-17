# ========================================================
# Rexbots
# Don't Remove Credit 🥺
# Telegram Channel @RexBots_Official
#
# Maintained & Updated by:
# Dhanpal Sharma
# GitHub: https://github.com/LastPerson07
# ========================================================

FROM python:3.10.13-slim-bullseye

# Prevent Python from creating .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure logs are shown instantly
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    aria2 \
    megatools \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright's pip package doesn't ship the actual browser - fetch chromium
# (+ its OS-level libraries) at build time so Rexbots/headless.py's
# JS-rendering fallback works out of the box, no manual step needed.
RUN playwright install --with-deps chromium

# Copy project files
COPY . .

# Start ONLY the bot
# Flask keep_alive server handles port binding
CMD ["python3", "bot.py"]

# ========================================================
# Rexbots
# Don't Remove Credit
# Telegram Channel @RexBots_Official
#
# Updated & Managed by:
# Dhanpal Sharma | https://github.com/LastPerson07
# ========================================================
