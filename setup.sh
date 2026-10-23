#!/usr/bin/env bash
# One-command setup for the AUDIOS FM Telegram bot (Ubuntu/Debian VPS).
# Usage:  bash setup.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
[ -f bot.py ] || { echo "Error: bot.py not found. Run this script from the bot folder."; exit 1; }

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "=== AUDIOS FM bot setup ==="
read -rp "Bot token from @BotFather: " TOKEN
read -rp "Your website address (example: https://mysite.com): " SITE
TOKEN="$(echo "$TOKEN" | tr -d '[:space:]')"
SITE="$(echo "$SITE" | tr -d '[:space:]')"; SITE="${SITE%/}"

[[ "$TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] || { echo "That doesn't look like a bot token. Copy it again from @BotFather."; exit 1; }
[[ "$SITE" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || { echo "Website must look like https://mysite.com (no extra path)."; exit 1; }

echo "-> Installing Python (may ask for your password)..."
$SUDO apt-get update -y -qq
$SUDO apt-get install -y -qq python3 python3-venv curl

echo "-> Checking the bot token..."
curl -fsS "https://api.telegram.org/bot${TOKEN}/getMe" | grep -q '"ok":true' \
  || { echo "Telegram rejected this token. Check it and run the script again."; exit 1; }

echo "-> Checking your website is reachable..."
if ! curl -fsS -o /dev/null -m 20 "${SITE}/index.php"; then
  echo "WARNING: could not open ${SITE}/index.php from this server. The bot will still start, but check the address."
fi

echo "-> Writing config.py..."
cat > config.py <<CONF
BOT_TOKEN = "${TOKEN}"
SITE_URL = "${SITE}"

CHECK_EVERY_SECONDS = 120
BATCH_WAIT_SECONDS = 180
DB_FILE = "bot.db"
CONF
chmod 600 config.py

echo "-> Installing bot libraries..."
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

echo "-> Creating the always-on service..."
$SUDO tee /etc/systemd/system/audiosfm-bot.service >/dev/null <<SERVICE
[Unit]
Description=AUDIOS FM Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=${DIR}
ExecStart=${DIR}/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now audiosfm-bot
$SUDO systemctl restart audiosfm-bot

sleep 4
echo
if $SUDO systemctl is-active --quiet audiosfm-bot; then
  echo "DONE. The bot is running. Open Telegram and send /start to your bot."
else
  echo "The bot did not start. Last log lines:"
fi
$SUDO journalctl -u audiosfm-bot -n 8 --no-pager || true
echo
echo "Live logs:  sudo journalctl -u audiosfm-bot -f"
echo "Restart:    sudo systemctl restart audiosfm-bot"
echo "Stop:       sudo systemctl stop audiosfm-bot"
