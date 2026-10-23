#!/usr/bin/env bash
# Pull the latest code from GitHub and restart the bot.   Usage: bash update.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

git pull --ff-only
./venv/bin/pip install -q -r requirements.txt
$SUDO systemctl restart audiosfm-bot
sleep 3
$SUDO journalctl -u audiosfm-bot -n 5 --no-pager || true
echo "Updated and restarted."
