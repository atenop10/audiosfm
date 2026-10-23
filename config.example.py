# Example only. setup.sh creates the real config.py for you on the server (it is NOT stored in GitHub).
# ---- Edit these two lines ----
BOT_TOKEN = "PASTE_BOT_TOKEN_HERE"      # from @BotFather
SITE_URL = "https://YOURDOMAIN.com"     # your website, no slash at the end

# ---- Optional settings ----
CHECK_EVERY_SECONDS = 120   # how often the bot looks at your website
BATCH_WAIT_SECONDS = 180    # wait this long after the last upload, so 12 uploads = 1 alert
DB_FILE = "bot.db"          # the bot's own small database (created automatically)

# Telegram IDs allowed to use admin commands (/stats, /broadcast, /checknow).
# Send /id to your bot to see your ID. Example: ADMIN_IDS = [123456789]
ADMIN_IDS = []
