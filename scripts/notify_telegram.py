import os
import sys
import glob
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

_raw_ids = os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [c.strip().strip('"').strip("'") for c in _raw_ids.split(",") if c.strip()]

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

TELEGRAM_MESSAGE_LIMIT = 4096
ITEMS_PER_MESSAGE = 10
CHARS_BUDGET_FOR_ITEMS = 3600
SEND_DELAY_SECONDS = 2
MAX_TEXT_MESSAGES = 15
SUBSCRIBERS_FILE = "subscribers.json"
OFFSET_FILE = "scripts/telegram_offset.json"

HANDLE = "@sentencedIntoMusic"
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

HEADER_TEMPLATE = (
    "سلام 👋\n\n"
    "🗂 بروزرسانی {kind} — بخش {part}/{total_parts}\n"
    "🔢 تعداد کل: {total_count}\n"
    "📅 {date} | ⏰ {time}\n"
    "📣 {handle}\n"
)


# subscribers.json format: {"<chat_id>": "<username or 'N/A'>", ...}
# (kept as a dict now, instead of a flat list, specifically so we know WHO
# each chat_id belongs to when broadcasting.)

def _load_subscribers_dict():
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):  # migrate old flat-list format
                    return {str(c): "N/A" for c in data}
        except Exception as e:
            print(f"[subscribers] Error loading subscriber file: {e}")
    return {}


def load_subscribers():
    """Return {chat_id: username} for everyone who should receive broadcasts
    (static TELEGRAM_CHAT_IDS + dynamically subscribed users)."""
    subs = _load_subscribers_dict()
    for cid in TELEGRAM_CHAT_IDS:
        subs.setdefault(cid, "N/A")
    return subs


def add_subscriber(chat_id, username="N/A"):
    """Add/refresh a chat ID (and its username) in the subscribers file."""
    subs = _load_subscribers_dict()
    chat_id_str = str(chat_id)
    is_new = chat_id_str not in subs
    subs[chat_id_str] = username or "N/A"
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)
    return is_new


def remove_subscriber(chat_id):
    subs = _load_subscribers_dict()
    chat_id_str = str(chat_id)
    if chat_id_str in subs:
        del subs[chat_id_str]
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(subs, f, ensure_ascii=False, indent=2)
        return True
    return False


def load_offset():
    if os.path.exists(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("offset")
        except Exception:
            return None
    return None


def save_offset(offset):
    if offset is None:
        return
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        json.dump({"offset": offset}, f)


def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def pack_groups(lines, max_items=ITEMS_PER_MESSAGE, max_chars=CHARS_BUDGET_FOR_ITEMS):
    groups = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and (len(current) >= max_items or current_len + line_len > max_chars):
            groups.append(current)
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        groups.append(current)
    return groups


def _post(method, data, headers, timeout, max_retries=4):
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(f"{API_BASE}/{method}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 429:
                try:
                    retry_after = json.loads(body).get("parameters", {}).get("retry_after", 5)
                except Exception:
                    retry_after = 5
                print(f"[notify_telegram] rate limited, waiting {retry_after}s before retry ({attempt}/{max_retries})...")
                time.sleep(retry_after + 1)
                continue
            print(f"[notify_telegram] Telegram API error {e.code}: {body}")
            raise
    raise RuntimeError(f"Gave up on {method} after {max_retries} retries — Telegram kept rate-limiting.")


def send_message(chat_id, text, parse_mode=None):
    payload_dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload_dict["parse_mode"] = parse_mode
    payload = json.dumps(payload_dict).encode("utf-8")
    return _post("sendMessage", payload, {"Content-Type": "application/json"}, 15)


def send_document(chat_id, file_path, caption):
    boundary = "----telegram-boundary"
    with open(file_path, "rb") as f:
        file_data = f.read()

    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{os.path.basename(file_path)}"\r\nContent-Type: text/plain\r\n\r\n',
    ]
    prefix = "".join(parts).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = prefix + file_data + suffix

    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return _post("sendDocument", payload, headers, 30)


def notify(kind, folder, suffix, limit=None):
    file_path = latest_file(folder, suffix)
    if not file_path:
        print(f"[notify_telegram] no {suffix} file found in {folder}, skipping.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        uris = [line.strip() for line in f if line.strip()]

    if limit is not None:
        uris = uris[:limit]

    if not uris:
        print(f"[notify_telegram] {file_path} is empty, skipping.")
        return

    groups = pack_groups(uris)
    total_parts = len(groups)
    now = datetime.now(TEHRAN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    recipients = load_subscribers()  # {chat_id: username}
    if not recipients:
        print("[notify_telegram] No recipients found in environment or subscriber list.")
        return

    for chat_id, username in recipients.items():
        print(f"[notify_telegram] sending {kind} to chat_id={chat_id!r} username={username!r}")

        if total_parts > MAX_TEXT_MESSAGES:
            summary = HEADER_TEMPLATE.format(
                kind=kind, part=1, total_parts=1, total_count=len(uris),
                date=date_str, time=time_str, handle=HANDLE,
            ) + f"\n({total_parts} message-blocks worth — sending as a file instead.)"
            send_message(chat_id, summary)
            time.sleep(SEND_DELAY_SECONDS)
            send_document(chat_id, file_path, caption=os.path.basename(file_path))
            time.sleep(SEND_DELAY_SECONDS)
            continue

        for i, group in enumerate(groups, 1):
            header = HEADER_TEMPLATE.format(
                kind=kind, part=i, total_parts=total_parts, total_count=len(uris),
                date=date_str, time=time_str, handle=HANDLE,
            )
            if kind == "Proxy":
                body = "\n".join(f"<blockquote>{line}</blockquote>" for line in group)
                parse_mode = "HTML"
            else:
                body = "```\n" + "\n".join(group) + "\n```"
                parse_mode = "Markdown"

            send_message(chat_id, header + body, parse_mode=parse_mode)
            time.sleep(SEND_DELAY_SECONDS)

    print(f"[notify_telegram] sent {len(uris)} {suffix} entries ({total_parts} messages) from {file_path} to {len(recipients)} recipient(s).")


def append_request_log(user_id, username, request_text):
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "username": username,
        "request": request_text
    }
    with open("bot_requests_log.json", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data) + "\n")


def handle_update(update):
    """Process a single update: save subscriber (with username) silently,
    log interaction silently, send NO interactive responses."""
    update_id = update.get("update_id")
    next_offset = update_id + 1

    msg = update.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    user_id = msg.get("from", {}).get("id")
    username = msg.get("from", {}).get("username", "N/A")
    text = msg.get("text", "")

    if chat_id and text:
        append_request_log(user_id, username, text)

        if text.startswith("/start") or text.startswith("/getConfigs") or text.startswith("/configs"):
            add_subscriber(chat_id, username)
        elif text.startswith("/end") or text.startswith("/stop"):
            remove_subscriber(chat_id)

    return next_offset


def fetch_and_process_updates(offset=None):
    url = f"{API_BASE}/getUpdates?timeout=10"
    if offset:
        url += f"&offset={offset}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            updates = json.loads(resp.read().decode("utf-8")).get("result", [])
    except Exception as e:
        print(f"[bot_polling] Error: {e}")
        return offset

    next_offset = offset
    for update in updates:
        next_offset = handle_update(update)
    return next_offset


def run_bot_daemon():
    print("[bot_polling] Starting daemon...")
    offset = None
    while True:
        offset = fetch_and_process_updates(offset)
        time.sleep(1)


def poll_once():
    offset = load_offset()
    received_count = 0

    url = f"{API_BASE}/getUpdates?timeout=5"
    if offset:
        url += f"&offset={offset}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            updates = json.loads(resp.read().decode("utf-8")).get("result", [])
    except Exception as e:
        print(f"[bot_polling] Error fetching updates: {e}")
        return

    for update in updates:
        offset = handle_update(update)
        received_count += 1

    save_offset(offset)
    print(f"[bot_polling] processed {received_count} message(s) since last run silently.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"

    if target == "daemon":
        run_bot_daemon()
    elif target == "poll":
        poll_once()
    else:
        if target in ("config", "both"):
            notify("Config", "config", "config", limit=50)
        if target in ("proxy", "both"):
            notify("Proxy", "proxy", "proxy")