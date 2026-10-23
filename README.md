# AUDIOS FM Telegram Bot (Python)

Runs on your VPS. It reads your website's public pages, so **nothing changes on your website**
and no database access is needed. No domain, HTTPS or web server needed on the VPS either.

## What it does
- `/search name` (or just type a name) -> matching series -> poster, description, episode count, latest episodes
- `/series` -> tick the series you like (multi-select)
- Follow / unfollow button on every series card
- Alerts when new episodes appear (12 uploads in a row = 1 message), optional "new series" alerts
- `/mysubs` shows your list, `/stop` removes all alerts

## Setup with GitHub (recommended)

Your bot token is never stored in GitHub: `setup.sh` creates `config.py` on the server only.

**A. Put the code on GitHub (once)**
1. github.com -> New repository -> name it e.g. `audiosfm-bot` -> choose **Private** -> Create.
2. Unzip this package on your computer. In the new repo click **Add file -> Upload files**, drag in
   `bot.py`, `config.example.py`, `requirements.txt`, `setup.sh`, `update.sh`, `set_admin.sh`,
   `README.md` (and `.gitignore` if your computer shows hidden files) -> **Commit changes**.

**B. Install on the VPS**
```
sudo apt update && sudo apt install -y git
git clone https://github.com/YOUR_USERNAME/audiosfm-bot.git
cd audiosfm-bot && bash setup.sh
```
- Public repo: no login needed.
- Private repo: when git asks, Username = your GitHub username, Password = a **Personal Access Token**
  (GitHub -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens ->
  only this repository -> Repository permissions -> Contents: **Read-only**).
  To make the server remember it, run this BEFORE `git clone`: `git config --global credential.helper store`

`setup.sh` asks for your bot token (from @BotFather) and website address, installs everything and starts the bot.

**C. Update later (after you change a file on GitHub)**
```
cd ~/audiosfm-bot && bash update.sh
```

**Command-line alternative for step A** (if you use git on your computer):
```
cd audiosfm-bot
git init && git add . && git commit -m "bot" && git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/audiosfm-bot.git
git push -u origin main
```

## Commands

Everyone:
- `/start` welcome + series list, `/help` all commands
- `/search name` (or just type a name), `/series` browse and tick series, `/mysubs`, `/stop`
- `/id` shows your Telegram ID

Admin only (set `ADMIN_IDS` in `config.py`):
- `/stats` users, follows, most-followed series, last website check
- `/broadcast your message` shows a preview with Send/Cancel buttons before anything is sent
- `/checknow` reads the website immediately and reports whether it worked

**Become admin:** start the bot, send `/id` to it, then on the VPS run
`bash set_admin.sh YOUR_ID` (or enter the ID when `setup.sh` asks). Several admins: `bash set_admin.sh 111,222`.
The "/" command menu in Telegram is filled in automatically (admins see the extra commands).

## Manual setup (copy and paste on your VPS, Ubuntu/Debian)

1. Create the bot: Telegram -> @BotFather -> `/newbot` -> copy the token.

2. Put these files in a folder called `audiosfm-bot` in your home folder
   (`bot.py`, `config.example.py`, `requirements.txt`), copy `config.example.py` to `config.py`, then open it and set
   `BOT_TOKEN` and `SITE_URL`.

3. Install and test:
   ```
   sudo apt update && sudo apt install -y python3 python3-venv
   cd ~/audiosfm-bot
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ./venv/bin/python bot.py
   ```
   You should see "Bot started". Send `/start` to your bot. Press Ctrl+C to stop.

4. Keep it running forever (also after reboot):
   ```
   sudo tee /etc/systemd/system/audiosfm-bot.service >/dev/null <<SERVICE
   [Unit]
   Description=AUDIOS FM Telegram bot
   After=network-online.target
   Wants=network-online.target

   [Service]
   User=$USER
   WorkingDirectory=$HOME/audiosfm-bot
   ExecStart=$HOME/audiosfm-bot/venv/bin/python bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   SERVICE
   sudo systemctl daemon-reload
   sudo systemctl enable --now audiosfm-bot
   ```

Useful commands:
- See logs: `sudo journalctl -u audiosfm-bot -f`
- Restart after editing config: `sudo systemctl restart audiosfm-bot`
- Stop: `sudo systemctl stop audiosfm-bot`

## Good to know
- First start: the bot remembers all current series/episodes and does NOT alert for them.
  Alerts begin with anything uploaded after that.
- Alerts arrive about 3-5 minutes after the upload (check every 2 min + 3 min batch wait).
  Change `CHECK_EVERY_SECONDS` / `BATCH_WAIT_SECONDS` in `config.py`.
- It visits your home page every 2 minutes. If your site counts visitors, these visits may show up.
- If your website changes its layout (class names `card`, `meta`, `episode-row-title`), the bot logs
  "no series found" and keeps running; ask for an update.
- If the site sits behind Cloudflare "under attack" mode or blocks bots, the bot can't read it.
- Users, follows and series memory are saved in `bot.db` next to `bot.py`. Back it up if you move servers.
- The bot sends links to your site, never the audio files.
