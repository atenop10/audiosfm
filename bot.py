#!/usr/bin/env python3
"""AUDIOS FM Telegram bot.

Reads the PUBLIC pages of your website (the same pages visitors see), so nothing has to be
changed on the website and no database access is needed. Uses long polling, so no domain,
HTTPS or web server is needed on the VPS.
"""
import html
import logging
import os
import re
import sqlite3
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import config
except ImportError:
    raise SystemExit("config.py not found. Run:  bash setup.sh")

log = logging.getLogger("audiosfm-bot")
API = f"https://api.telegram.org/bot{config.BOT_TOKEN}/"
SITE = config.SITE_URL.rstrip("/")
HEADERS = {"User-Agent": "AudiosFM-TelegramBot/1.0"}
PER_PAGE = 8
db = None  # set by init_db()


# ------------------------------------------------------------------ database
def init_db(path):
    global db
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY, first_name TEXT,
            new_series_alerts INTEGER NOT NULL DEFAULT 0,
            blocked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS subs (
            chat_id INTEGER NOT NULL, story_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, story_id));
        CREATE TABLE IF NOT EXISTS stories (
            story_id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT,
            poster TEXT, is_popular INTEGER NOT NULL DEFAULT 0,
            seen_count INTEGER NOT NULL DEFAULT 0,
            known_count INTEGER NOT NULL DEFAULT 0,
            changed_at REAL NOT NULL DEFAULT 0,
            is_new INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        """
    )
    db.commit()


def meta_get(k, default="0"):
    r = db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def meta_set(k, v):
    db.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
    db.commit()


# ------------------------------------------------------------------ telegram
def api(method, **params):
    for _ in range(2):
        try:
            r = requests.post(API + method, json=params, timeout=40)
            data = r.json()
        except Exception as e:  # network problem / bad reply
            log.warning("telegram %s failed: %s", method, e)
            return {"ok": False, "error_code": 0}
        if data.get("ok"):
            return data
        if data.get("error_code") == 429:
            time.sleep(min(30, data.get("parameters", {}).get("retry_after", 2)))
            continue
        return data
    return {"ok": False, "error_code": 429}


def esc(s):
    return html.escape(str(s or ""), quote=False)


def send(chat_id, text, **extra):
    r = api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
            disable_web_page_preview=True, **extra)
    if not r.get("ok") and r.get("error_code") in (400, 403):
        db.execute("UPDATE users SET blocked=1 WHERE chat_id=?", (chat_id,))
        db.commit()
    return bool(r.get("ok"))


def story_url(story_id):
    return f"{SITE}/index.php?story={story_id}"


# ------------------------------------------------------------------ website reading
def fetch(path):
    r = requests.get(SITE + path, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_home(page):
    """Return {story_id: {title, desc, poster, count, popular}} from the home page."""
    soup = BeautifulSoup(page, "html.parser")
    out = {}
    for card in soup.select("article.card"):
        a = card.select_one("a[href*='story=']")
        h3 = card.find("h3")
        if not a or not h3:
            continue
        m = re.search(r"story=(\d+)", a["href"])
        if not m:
            continue
        sid = int(m.group(1))
        p = card.find("p")
        meta = card.select_one(".meta")
        meta_text = meta.get_text(" ", strip=True) if meta else ""
        mc = re.search(r"([\d,]+)\s+episodes?", meta_text)
        img = card.select_one("a.cover img")
        rec = {
            "title": h3.get_text(strip=True),
            "desc": p.get_text(" ", strip=True) if p else "",
            "poster": urljoin(SITE + "/", img["src"]) if img and img.get("src") else "",
            "count": int(mc.group(1).replace(",", "")) if mc else 0,
            "popular": 1 if "Popular" in meta_text else 0,
        }
        if sid in out:  # popular stories appear twice on the page
            rec["popular"] = max(rec["popular"], out[sid]["popular"])
        out[sid] = rec
    return out


def latest_episodes(story_id, n=8):
    """Names of the newest episodes (newest first). The site clamps a huge page number to the last page."""
    soup = BeautifulSoup(fetch(f"/index.php?story={story_id}&page=999999"), "html.parser")
    names = []
    for el in soup.select(".episode-row-title"):
        for span in el.select("span"):
            span.extract()
        name = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", el.get_text(" ", strip=True))
        if name:
            names.append(name)
    return names[-n:][::-1]


# ------------------------------------------------------------------ alerts
def broadcast(chat_ids, text, story_id):
    markup = {"inline_keyboard": [[{"text": "▶ Listen now", "url": story_url(story_id)}]]}
    for cid in chat_ids:
        send(cid, text, reply_markup=markup)
        time.sleep(0.05)  # stay under Telegram's rate limit


def announce(story_id, title, is_new_series, added, total):
    followers = {r["chat_id"] for r in db.execute(
        "SELECT s.chat_id FROM subs s JOIN users u ON u.chat_id=s.chat_id "
        "WHERE s.story_id=? AND u.blocked=0", (story_id,))}
    if is_new_series:
        opted = {r["chat_id"] for r in db.execute(
            "SELECT chat_id FROM users WHERE new_series_alerts=1 AND blocked=0")}
        text = f"🆕 <b>New series:</b> {esc(title)}\n{total} episode{'s' if total != 1 else ''} available now"
        broadcast(sorted(followers | opted), text, story_id)
    else:
        text = f"🎧 <b>{esc(title)}</b>\n{added} new episode{'s' if added != 1 else ''} added ({total} total)"
        broadcast(sorted(followers), text, story_id)


def check_site():
    try:
        stories = parse_home(fetch("/index.php"))
    except Exception as e:
        log.warning("site check failed: %s", e)
        return
    if not stories:
        log.warning("no series found on the home page (site down or layout changed) - skipping")
        return

    now = time.time()
    first_run = db.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 0
    if first_run:
        log.info("first run: remembering %d series, no alerts for existing episodes", len(stories))

    for sid, s in stories.items():
        row = db.execute("SELECT * FROM stories WHERE story_id=?", (sid,)).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO stories (story_id,title,description,poster,is_popular,seen_count,"
                "known_count,changed_at,is_new) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, s["title"], s["desc"], s["poster"], s["popular"], s["count"],
                 s["count"] if first_run else 0, now, 0 if first_run else 1))
            db.commit()
            continue

        seen, known, changed = row["seen_count"], row["known_count"], row["changed_at"]
        if s["count"] != seen:
            seen, changed = s["count"], now
        if seen < known:  # episodes were deleted on the site
            known = seen
        db.execute(
            "UPDATE stories SET title=?,description=?,poster=?,is_popular=?,seen_count=?,"
            "known_count=?,changed_at=? WHERE story_id=?",
            (s["title"], s["desc"], s["poster"], s["popular"], seen, known, changed, sid))
        db.commit()

        if seen > known and now - changed >= config.BATCH_WAIT_SECONDS:
            try:
                announce(sid, s["title"], bool(row["is_new"]) and known == 0, seen - known, seen)
            except Exception:
                log.exception("announce failed for story %s", sid)
            db.execute("UPDATE stories SET known_count=?, is_new=0 WHERE story_id=?", (seen, sid))
            db.commit()


# ------------------------------------------------------------------ bot screens
def toggle_sub(chat_id, story_id):
    """Returns True if now following, False if unfollowed, None if the series doesn't exist."""
    if db.execute("SELECT 1 FROM subs WHERE chat_id=? AND story_id=?", (chat_id, story_id)).fetchone():
        db.execute("DELETE FROM subs WHERE chat_id=? AND story_id=?", (chat_id, story_id))
        db.commit()
        return False
    if not db.execute("SELECT 1 FROM stories WHERE story_id=?", (story_id,)).fetchone():
        return None
    db.execute("INSERT OR IGNORE INTO subs (chat_id, story_id) VALUES (?, ?)", (chat_id, story_id))
    db.commit()
    return True


def series_keyboard(chat_id, page):
    total = db.execute("SELECT COUNT(*) FROM stories WHERE seen_count>0").fetchone()[0]
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, page), pages)
    rows = db.execute(
        "SELECT st.story_id, st.title, "
        "(SELECT COUNT(*) FROM subs s WHERE s.chat_id=? AND s.story_id=st.story_id) AS sub "
        "FROM stories st WHERE st.seen_count>0 ORDER BY st.story_id DESC LIMIT ? OFFSET ?",
        (chat_id, PER_PAGE, (page - 1) * PER_PAGE)).fetchall()
    kb = [[{"text": ("✅ " if r["sub"] else "⬜ ") + r["title"][:40],
            "callback_data": f"t:{r['story_id']}:{page}"}] for r in rows]
    nav = []
    if page > 1:
        nav.append({"text": "⬅️ Prev", "callback_data": f"p:{page - 1}"})
    nav.append({"text": f"{page}/{pages}", "callback_data": "x"})
    if page < pages:
        nav.append({"text": "Next ➡️", "callback_data": f"p:{page + 1}"})
    kb.append(nav)
    u = db.execute("SELECT new_series_alerts FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    on = bool(u and u["new_series_alerts"])
    kb.append([{"text": f"🆕 New series alerts: {'ON' if on else 'OFF'}", "callback_data": f"n:{page}"}])
    kb.append([{"text": "✔️ Done", "callback_data": "d"}])
    return {"inline_keyboard": kb}


def show_series(chat_id):
    send(chat_id, "🎧 <b>Available series</b>\nTap the series you like. You'll get an alert whenever "
                  "new episodes are uploaded.", reply_markup=series_keyboard(chat_id, 1))


def my_subs_text(chat_id):
    rows = db.execute("SELECT st.title FROM subs s JOIN stories st ON st.story_id=s.story_id "
                      "WHERE s.chat_id=? ORDER BY st.title", (chat_id,)).fetchall()
    if not rows:
        return "You haven't selected any series yet. Send /series to choose."
    return "🔔 <b>You get alerts for:</b>\n• " + "\n• ".join(esc(r["title"]) for r in rows)


def card_keyboard(chat_id, story_id):
    sub = db.execute("SELECT 1 FROM subs WHERE chat_id=? AND story_id=?", (chat_id, story_id)).fetchone()
    return {"inline_keyboard": [
        [{"text": "▶ Listen on site", "url": story_url(story_id)}],
        [{"text": "🔕 Unfollow alerts" if sub else "🔔 Follow for new-episode alerts",
          "callback_data": f"f:{story_id}"}],
    ]}


def send_card(chat_id, story_id):
    s = db.execute("SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
    if not s:
        send(chat_id, "Series not found.")
        return
    try:
        labels = latest_episodes(story_id)
    except Exception as e:
        log.warning("could not read episodes for %s: %s", story_id, e)
        labels = []
    text = f"🎧 <b>{esc(s['title'])}</b>\n"
    if (s["description"] or "").strip():
        text += esc(s["description"].strip()[:300]) + "\n"
    n = s["seen_count"]
    text += f"\n📚 {n} episode{'s' if n != 1 else ''}"
    if labels:
        text += "\nLatest: " + esc(", ".join(labels))
    kb = card_keyboard(chat_id, story_id)
    if s["poster"]:
        r = api("sendPhoto", chat_id=chat_id, photo=s["poster"], caption=text,
                parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            return
    send(chat_id, text, reply_markup=kb)


def do_search(chat_id, q):
    q = q.strip()
    if not q:
        send(chat_id, "Type the series name, e.g. /search dragon")
        return
    ql = q.lower()
    rows = db.execute("SELECT story_id, title FROM stories WHERE seen_count>0 "
                      "ORDER BY is_popular DESC, story_id DESC").fetchall()
    hits = [r for r in rows if ql in r["title"].lower()][:8]
    if not hits:
        send(chat_id, f"No series found for \"{esc(q)}\". Try another name, or send /series to browse all.")
        return
    kb = [[{"text": r["title"][:50], "callback_data": f"s:{r['story_id']}"}] for r in hits]
    send(chat_id, f"🔎 Results for <b>{esc(q)}</b> – tap a series:", reply_markup={"inline_keyboard": kb})


# ------------------------------------------------------------------ updates
def handle_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    parts = (cq.get("data") or "").split(":")
    db.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
    db.commit()
    kind = parts[0]

    def ack(text=""):
        api("answerCallbackQuery", callback_query_id=cq["id"], text=text)

    def redraw(page):
        api("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
            reply_markup=series_keyboard(chat_id, page))

    if kind == "t":  # tick/untick a series in the list
        state = toggle_sub(chat_id, int(parts[1]))
        ack({True: "Added ✅", False: "Removed"}.get(state, ""))
        redraw(int(parts[2]))
    elif kind == "p":
        ack()
        redraw(int(parts[1]))
    elif kind == "n":
        db.execute("UPDATE users SET new_series_alerts = 1 - new_series_alerts WHERE chat_id=?", (chat_id,))
        db.commit()
        ack()
        redraw(int(parts[1]))
    elif kind == "s":  # open a series card from search results
        ack()
        send_card(chat_id, int(parts[1]))
    elif kind == "f":  # follow/unfollow from a series card
        sid = int(parts[1])
        state = toggle_sub(chat_id, sid)
        ack({True: "You'll get alerts ✅", False: "Alerts off"}.get(state, ""))
        api("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
            reply_markup=card_keyboard(chat_id, sid))
    elif kind == "d":
        ack()
        api("editMessageText", chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
            text=my_subs_text(chat_id) + "\n\nSend /series any time to change your list.")
    else:
        ack()


def handle_update(u):
    if "callback_query" in u:
        handle_callback(u["callback_query"])
        return
    msg = u.get("message")
    if not msg or msg["chat"].get("type") != "private" or not msg.get("text"):
        return
    chat_id = msg["chat"]["id"]
    db.execute("INSERT INTO users (chat_id, first_name) VALUES (?, ?) "
               "ON CONFLICT(chat_id) DO UPDATE SET first_name=excluded.first_name, blocked=0",
               (chat_id, msg.get("from", {}).get("first_name")))
    db.commit()

    text = msg["text"].strip()
    cmd = text.split()[0].split("@")[0].lower()
    arg = text[len(text.split()[0]):].strip()

    if cmd == "/start":
        send(chat_id, "👋 Welcome to <b>AUDIOS FM</b> alerts!\n\n"
                      "/search name – find a series (or just type its name)\n"
                      "/series – browse and follow series\n"
                      "/mysubs – see your list\n"
                      "/stop – stop all alerts")
        show_series(chat_id)
    elif cmd in ("/series", "/list"):
        show_series(chat_id)
    elif cmd == "/search":
        do_search(chat_id, arg)
    elif cmd == "/mysubs":
        send(chat_id, my_subs_text(chat_id))
    elif cmd == "/stop":
        db.execute("DELETE FROM subs WHERE chat_id=?", (chat_id,))
        db.execute("UPDATE users SET new_series_alerts=0 WHERE chat_id=?", (chat_id,))
        db.commit()
        send(chat_id, "All alerts stopped. Send /series to start again.")
    elif not text.startswith("/"):
        do_search(chat_id, text)  # plain text = search
    else:
        send(chat_id, "Send a series name to search, or /series to browse.")


# ------------------------------------------------------------------ main loop
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "PASTE_BOT_TOKEN" in config.BOT_TOKEN or "YOURDOMAIN" in config.SITE_URL:
        raise SystemExit("Open config.py and set BOT_TOKEN and SITE_URL first.")
    init_db(os.path.join(os.path.dirname(os.path.abspath(__file__)), config.DB_FILE))
    api("deleteWebhook")  # this bot uses polling, so make sure no webhook is set
    offset = int(meta_get("offset", "0"))
    last_check = 0.0
    log.info("Bot started")
    while True:
        if time.time() - last_check >= config.CHECK_EVERY_SECONDS:
            try:
                check_site()
            except Exception:
                log.exception("check_site crashed")
            last_check = time.time()
        res = api("getUpdates", offset=offset, timeout=25, allowed_updates=["message", "callback_query"])
        if not res.get("ok"):
            time.sleep(3)
            continue
        for u in res["result"]:
            offset = u["update_id"] + 1
            try:
                handle_update(u)
            except Exception:
                log.exception("update failed")
        if res["result"]:
            meta_set("offset", offset)


if __name__ == "__main__":
    main()
