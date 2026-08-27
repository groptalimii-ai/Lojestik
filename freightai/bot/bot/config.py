import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

# Shared with the backend ONLY (same value as backend's BOT_SERVICE_SECRET
# in .env). Used to sign the /auth/telegram handshake -- this is what
# proves a login request genuinely came from this bot process and not
# from someone hitting the API directly. Never sent to or shown to users.
BOT_SERVICE_SECRET = os.environ.get("BOT_SERVICE_SECRET", "")

if not TELEGRAM_BOT_TOKEN:
    # Do not crash import-time in dev, but warn loudly.
    print("WARNING: TELEGRAM_BOT_TOKEN is not set. Set it in your .env file.")

if not BOT_SERVICE_SECRET:
    print("WARNING: BOT_SERVICE_SECRET is not set. /auth/telegram calls will fail.")
