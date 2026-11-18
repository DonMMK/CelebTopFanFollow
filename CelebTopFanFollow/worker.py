#!/usr/bin/env python3
"""Poll public profiles and deliver new-post alerts through Telegram."""
import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from threading import Thread
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

LOG = logging.getLogger("celebtopfanfollow")
STREAMS = {"instagram_feed": "instagram", "tiktok_feed": "tiktok"}
PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok"}
HANDLE = re.compile(r"[a-z0-9._]{1,30}", re.ASCII)
SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    stream TEXT, handle TEXT, added_at REAL NOT NULL,
    PRIMARY KEY (stream, handle)
);
CREATE TABLE IF NOT EXISTS source_checks (
    stream TEXT, handle TEXT, attempted_at REAL NOT NULL, succeeded INTEGER NOT NULL,
    PRIMARY KEY (stream, handle)
);
CREATE TABLE IF NOT EXISTS alerts (
    stream TEXT, post_id TEXT, handle TEXT NOT NULL, published_at REAL NOT NULL,
    message TEXT NOT NULL, sent_at REAL,
    PRIMARY KEY (stream, post_id)
);
"""


class ServiceError(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def request(label, url, payload=None, token=None, *, html=False):
    headers = {"Accept": "text/html" if html else "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=25) as response:
            maximum = 5 * 1024 * 1024
            body = response.read(maximum + 1)
            if len(body) > maximum:
                raise ServiceError(f"{label} response exceeded the size limit")
            return body.decode("utf-8") if html else json.loads(body)
    except HTTPError as exc:
        with exc:
            retry_after = 900 if exc.code == 429 else 0
            if label == "TikTok" and exc.code == 403:
                retry_after = 900
            details = ""
            if label in ("Telegram", "Meta"):
                try:
                    error = json.loads(exc.read(32768))
                    if label == "Telegram" and exc.code == 429:
                        retry_after = int(error.get("parameters", {}).get("retry_after", 30))
                    if label == "Meta":
                        code = int(error.get("error", {}).get("code", 0))
                        details = f" (Graph error {code})" if code else ""
                        if code in (4, 17, 32, 613):
                            retry_after = 900
                except (ValueError, AttributeError, TypeError, OSError):
                    pass
        raise ServiceError(f"{label} returned HTTP {exc.code}{details}", retry_after) from None
    except (URLError, OSError, ValueError):
        # Exception details can contain Telegram's token-bearing URL.
        raise ServiceError(f"{label} connection or response failed") from None


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ServiceError(f"Set {name} in the service environment")
    return value


def telegram(method, payload):
    token = required("TELEGRAM_BOT_TOKEN")
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ServiceError("Invalid Telegram bot token format")
    result = request("Telegram", f"https://api.telegram.org/bot{token}/{method}", payload)
    if not result.get("ok"):
        raise ServiceError("Telegram did not accept the request")
    return result["result"]


def chat_id():
    value = required("TELEGRAM_CHAT_ID")
    if not re.fullmatch(r"-?[0-9]+", value):
        raise ServiceError("TELEGRAM_CHAT_ID must be numeric")
    return int(value)


def send(message, thread_id=None):
    payload = {
        "chat_id": chat_id(),
        "text": message,
        "link_preview_options": {"is_disabled": True},
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    telegram("sendMessage", payload)


def read_config(path):
    try:
        raw = json.loads(path.read_text())
        watchlist = {}
        for platform in PLATFORM_NAMES:
            values = raw.get(platform, [])
            if not isinstance(values, list):
                raise ValueError(f"{platform} must be an array")
            handles = sorted({value.strip().lstrip("@").lower() for value in values})
            if len(handles) > 50 or any(not HANDLE.fullmatch(handle) for handle in handles):
                raise ValueError(f"{platform} accepts up to 50 valid usernames")
            watchlist[platform] = handles

        maximum = raw.get("feed_results_per_profile", 10)
        if type(maximum) is not int or not 1 <= maximum <= 50:
            raise ValueError("feed_results_per_profile must be an integer from 1 to 50")
        minutes = {}
        for stream in STREAMS:
            interval = raw["poll_minutes"].get(stream, 0)
            if type(interval) is not int or (interval != 0 and interval < 15):
                raise ValueError(f"{stream} interval must be 0 or at least 15 minutes")
            minutes[stream] = interval
        return watchlist, minutes, maximum
    except (KeyError, AttributeError, OSError, TypeError, ValueError) as exc:
        raise ServiceError(f"Invalid watchlist file {path}: {exc}") from None


def instagram_rows(handle, limit):
    token = required("META_ACCESS_TOKEN")
    account_id = required("META_IG_USER_ID")
    version = os.environ.get("META_GRAPH_VERSION", "v27.0")
    if not re.fullmatch(r"[0-9]+", account_id) or not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
        raise ServiceError("Invalid META_IG_USER_ID or META_GRAPH_VERSION")
    media_fields = "id,shortcode,caption,media_type,media_product_type,permalink,timestamp"
    fields = f"business_discovery.username({handle}){{username,media.limit({limit}){{{media_fields}}}}}"
    url = f"https://graph.facebook.com/{version}/{account_id}?" + urlencode({"fields": fields})
    result = request("Meta", url, token=token)
    try:
        account = result["business_discovery"]
        rows = account["media"]["data"]
        if account["username"].lower() != handle or not isinstance(rows, list):
            raise ValueError()
    except (TypeError, KeyError, AttributeError, ValueError):
        raise ServiceError("Meta did not return this professional account's media") from None
    return rows


class CreatorEmbed(HTMLParser):
    """Find the JSON state in TikTok's ordinary public creator embed."""

    def __init__(self):
        super().__init__()
        self.reading = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__FRONTITY_CONNECT_STATE__":
            self.reading = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.reading = False

    def handle_data(self, data):
        if self.reading:
            self.parts.append(data)


def tiktok_rows(handle, limit):
    path = f"/embed/@{handle}"
    html = request("TikTok", f"https://www.tiktok.com{path}", html=True)
    parser = CreatorEmbed()
    parser.feed(html)
    try:
        state = json.loads("".join(parser.parts))
        account = state["source"]["data"][path]
        user = account["userInfo"]
        rows = account["videoList"]
        if user.get("privateAccount") or user["uniqueId"].lower() != handle or not isinstance(rows, list):
            raise ValueError()
    except (TypeError, KeyError, AttributeError, ValueError):
        raise ServiceError("TikTok did not expose this public creator feed", retry_after=900) from None
    return rows[:limit]


def published_time(value):
    try:
        if isinstance(value, (int, float)):
            return float(value) if 0 < value < 4_000_000_000 else None
        if value.isascii() and value.isdigit():
            return published_time(int(value))
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None


def allowed_link(url, platform):
    if isinstance(url, str):
        try:
            parts = urlsplit(url)
            host = parts.hostname or ""
            domain = f"{platform}.com"
            if parts.scheme == "https" and (host == domain or host.endswith("." + domain)):
                if parts.username is None and parts.password is None and parts.path not in ("", "/"):
                    return parts._replace(query="", fragment="").geturl()
        except ValueError:
            pass
    return None


@dataclass(frozen=True)
class Post:
    handle: str
    post_id: str
    title: str
    published_at: float
    url: str
    caption: str


def parse_post(stream, handle, row):
    platform = STREAMS[stream]
    if platform == "instagram":
        link = allowed_link(row.get("permalink"), platform)
        shortcode = re.fullmatch(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)/?", urlsplit(link).path) if link else None
        post_id = row.get("shortcode") or (shortcode[1] if shortcode else row.get("id"))
        media = row.get("media_type")
        is_reel = row.get("media_product_type") == "REELS" or "/reel/" in (link or "")
        title = "Reel" if is_reel else {
            "IMAGE": "Photo", "CAROUSEL_ALBUM": "Carousel", "VIDEO": "Video",
        }.get(str(media), "Post")
        when, caption = row.get("timestamp"), row.get("caption")
        link = link or f"https://www.instagram.com/{handle}/"
    else:
        post_id = str(row.get("id", ""))
        author = row.get("authorUniqueId")
        if not re.fullmatch(r"[0-9]{15,20}", post_id) or (author and str(author).lower() != handle):
            return None
        # The public embed can omit the time. TikTok's numeric IDs encode it
        # in their upper bits, as used by the RSSHub creator-embed route.
        when = row.get("createTime") or (int(post_id) >> 32)
        caption = row.get("desc")
        photo = bool(row.get("imagePost") or row.get("imagePostInfo"))
        kind = "photo" if photo else "video"
        link = f"https://www.tiktok.com/@{handle}/{kind}/{post_id}"
        title = "Photo slideshow" if photo else "Video"
    timestamp = published_time(when)
    if not post_id or timestamp is None or not 1_450_000_000 <= timestamp <= time.time() + 300:
        return None
    preview = " ".join(caption.split())[:240] if isinstance(caption, str) else ""
    return Post(handle, str(post_id), title, timestamp, link, preview)


def checked_posts(stream, handle, limit):
    fetch = instagram_rows if stream == "instagram_feed" else tiktok_rows
    rows = fetch(handle, limit)
    posts = [post for row in rows if isinstance(row, dict) and (post := parse_post(stream, handle, row))]
    if rows and not posts:
        raise ServiceError("Feed returned rows without usable post metadata")
    return posts


def sync_watches(db, watchlist, minutes):
    now = time.time()
    desired = {(stream, handle) for stream, platform in STREAMS.items() if minutes[stream]
               for handle in watchlist[platform]}
    current = set(db.execute("SELECT stream, handle FROM watches"))
    removed = current - desired
    with db:
        db.executemany("DELETE FROM watches WHERE stream=? AND handle=?", removed)
        db.executemany("DELETE FROM source_checks WHERE stream=? AND handle=?", removed)
        db.executemany("DELETE FROM alerts WHERE stream=? AND handle=? AND sent_at IS NULL", removed)
        db.executemany("INSERT INTO watches VALUES (?, ?, ?)",
                       ((stream, handle, now) for stream, handle in desired - current))


def watchlist_text(db, watchlist, minutes):
    checks = {(stream, handle): (attempted_at, succeeded)
              for stream, handle, attempted_at, succeeded in db.execute("SELECT * FROM source_checks")}
    lines = ["CelebTopFanFollow watchlist"]
    for stream, platform in STREAMS.items():
        handles, interval = watchlist[platform], minutes[stream]
        mode = f"every {interval} min" if interval else "paused"
        lines.extend(("", f"{PLATFORM_NAMES[platform]} ({len(handles)}) · {mode}"))
        if not handles:
            lines.append("No accounts configured")
        for handle in handles:
            attempted, succeeded = checks.get((stream, handle), (None, None))
            status = "paused" if not interval else "awaiting check"
            if interval and attempted is not None:
                stale = time.time() - attempted > max(1800, 2 * interval * 60)
                status = "check overdue" if stale else ("OK" if succeeded else "check failed")
            lines.append(f"@{handle} · {status}")
    # Each platform is capped at 50 accounts, but long handles plus status
    # can exceed Telegram's one-message limit.
    messages, chunk = [], ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3900:
            messages.append(chunk.rstrip())
            chunk = ""
        chunk += line + "\n"
    return messages + [chunk.rstrip()]


def watchlist_command(update, authorized_chat, username):
    message = update.get("message") or {}
    if (message.get("chat") or {}).get("id") != authorized_chat:
        return None
    token = str(message.get("text") or "").split(maxsplit=1)
    if not token:
        return None
    command, _, target = token[0].lower().partition("@")
    if target and target != username.lower():
        return None
    if command in ("/watchlist", "/start"):
        return message
    return None


def command_loop(db_path, watchlist, minutes):
    authorized_chat = chat_id()
    username = None
    offset = 0
    menu_set = False
    while True:
        try:
            if not username:
                username = telegram("getMe", {})["username"]
            if not menu_set:
                try:
                    telegram("setMyCommands", {
                        "scope": {"type": "chat", "chat_id": authorized_chat},
                        "commands": [{"command": "watchlist", "description": "Show monitored accounts by platform"}],
                    })
                except ServiceError as exc:
                    LOG.warning("Could not register /watchlist in the Telegram menu: %s", exc)
                menu_set = True
            updates = telegram("getUpdates", {
                "offset": offset,
                "timeout": 15,
                "allowed_updates": ["message"],
            })
            if not updates:
                offset = 0
            for update in updates:
                offset = update["update_id"] + 1
                message = watchlist_command(update, authorized_chat, username)
                if message is None:
                    continue
                with closing(sqlite3.connect(db_path)) as db:
                    messages = watchlist_text(db, watchlist, minutes)
                thread = message.get("message_thread_id") if message.get("is_topic_message") else None
                for reply in messages:
                    send(reply, thread)
        except (ServiceError, sqlite3.Error) as exc:
            LOG.warning("Telegram commands: %s", exc)
            time.sleep(max(20, getattr(exc, "retry_after", 0)))


def record(db, stream, posts, watches):
    name = PLATFORM_NAMES[STREAMS[stream]]
    with db:
        for post in posts:
            if post.published_at <= watches[post.handle]:
                continue
            date = datetime.fromtimestamp(post.published_at, timezone.utc).strftime("%d %b %Y, %H:%M UTC")
            parts = [f"{name} · {post.title}", f"@{post.handle} · {date}", post.caption, post.url]
            db.execute("""INSERT OR IGNORE INTO alerts
                        (stream, post_id, handle, published_at, message) VALUES (?, ?, ?, ?, ?)""",
                       (stream, post.post_id, post.handle, post.published_at, "\n".join(filter(None, parts))))


def flush(db):
    rows = db.execute("""SELECT stream, post_id, message FROM alerts
                       WHERE sent_at IS NULL ORDER BY published_at LIMIT 25""").fetchall()
    for stream, post_id, message in rows:
        send(message)
        with db:
            db.execute("UPDATE alerts SET sent_at=? WHERE stream=? AND post_id=?",
                       (time.time(), stream, post_id))
        LOG.info("Telegram alert sent for %s (%s)", stream, post_id)


def run(db, db_path, watchlist, minutes, limit):
    sync_watches(db, watchlist, minutes)
    Thread(target=command_loop, args=(db_path, watchlist, minutes), daemon=True).start()
    next_delivery = 0
    cooldown = {stream: 0 for stream in STREAMS}

    while True:
        if time.monotonic() >= next_delivery:
            try:
                flush(db)
            except ServiceError as exc:
                LOG.warning("%s; queued alerts will be retried", exc)
                next_delivery = time.monotonic() + max(300, exc.retry_after)

        due = db.execute("""
            SELECT w.stream, w.handle, w.added_at, c.attempted_at
            FROM watches w LEFT JOIN source_checks c
            ON c.stream=w.stream AND c.handle=w.handle
            ORDER BY c.attempted_at, w.stream, w.handle
        """).fetchall()
        for stream, handle, added_at, last_attempt in due:
            if time.monotonic() < cooldown[stream]:
                continue
            if last_attempt and time.time() < last_attempt + minutes[stream] * 60:
                continue
            attempted_at = time.time()
            try:
                posts = checked_posts(stream, handle, limit)
            except ServiceError as exc:
                LOG.warning("%s @%s: %s", stream, handle, exc)
                if exc.retry_after:
                    cooldown[stream] = time.monotonic() + exc.retry_after
                succeeded = False
            else:
                record(db, stream, posts, {handle: added_at})
                LOG.info("%s @%s returned %s items", stream, handle, len(posts))
                succeeded = True
            with db:
                db.execute("INSERT OR REPLACE INTO source_checks VALUES (?, ?, ?, ?)",
                           (stream, handle, attempted_at, succeeded))
            break
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/celebtopfanfollow/watchlist.json"))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--test-telegram", action="store_true")
    action.add_argument("--chat-id", action="store_true", help="List chat IDs in pending updates")
    action.add_argument("--clear-telegram-webhook", action="store_true",
                        help="Remove the old webhook for this bot and keep pending updates")
    action.add_argument("--preview", choices=STREAMS, help="Run one free feed check per configured handle without sending alerts")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.test_telegram:
            send("CelebTopFanFollow is connected. This is a test alert.")
            print("Test alert sent")
        elif args.clear_telegram_webhook:
            telegram("deleteWebhook", {"drop_pending_updates": False})
            print("Telegram webhook removed")
        elif args.chat_id:
            chats = set()
            for update in telegram("getUpdates", {"limit": 100, "timeout": 0}):
                message = update.get("message") or update.get("channel_post") or {}
                if "chat" in message:
                    chats.add((message["chat"]["id"], message["chat"]["type"]))
            for identifier, kind in sorted(chats):
                print(identifier, kind)
            if not chats:
                print("No pending chat messages. Open the bot in Telegram and send /start.")
        else:
            watchlist, minutes, limit = read_config(args.config)
            if args.preview:
                handles = watchlist[STREAMS[args.preview]]
                if not handles:
                    raise ServiceError("Add at least one username for this platform")
                for handle in handles:
                    posts = checked_posts(args.preview, handle, limit)
                    if not posts:
                        print(f"@{handle} | No items in the current public feed")
                    for post in posts:
                        print(f"@{post.handle} | {post.title} | {post.url}")
                return
            required("TELEGRAM_BOT_TOKEN")
            chat_id()
            state = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/celebtopfanfollow"))
            with (state / "worker.lock").open("w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ServiceError("A worker is already using this state directory") from None
                db_path = state / "alerts.sqlite3"
                with closing(sqlite3.connect(db_path)) as db:
                    db.executescript(SCHEMA)
                    run(db, db_path, watchlist, minutes, limit)
    except ServiceError as exc:
        LOG.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
