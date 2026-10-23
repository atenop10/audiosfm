#!/usr/bin/env bash
# Give yourself admin commands.  Usage: bash set_admin.sh 123456789   (several people: 111,222)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
IDS="${1:-}"
[[ "$IDS" =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo "Usage: bash set_admin.sh 123456789   (send /id to your bot to see your ID)"; exit 1; }
[ -f config.py ] || { echo "config.py not found. Run: bash setup.sh"; exit 1; }
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

grep -v '^ADMIN_IDS' config.py > config.tmp || true
echo "ADMIN_IDS = [${IDS}]" >> config.tmp
mv config.tmp config.py && chmod 600 config.py
$SUDO systemctl restart audiosfm-bot
echo "Done. Admin ID(s) set: ${IDS}. Send /help to your bot to see the admin commands."
