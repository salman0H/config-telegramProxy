import os
import sys
import glob
import json
import time
import random
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

HANDLE = "@sentencedIntoMusic"
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

HEADER_TEMPLATE = (
    "سلام 👋\n\n"
    "🗂 بروزرسانی {kind} — بخش {part}/{total_parts}\n"
    "🔢 تعداد کل: {total_count}\n"
    "📅 {date} | ⏰ {time}\n"
    "📣 {handle}\n"
)


def load_subscribers():
    """Load dynamically registered chat IDs from subscriber JSON file."""
    subscribers = set(TELEGRAM_CHAT_IDS)
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    subscribers.update(str(cid) for cid in data)
        except Exception as e:
            print(f"[subscribers] Error loading subscriber file: {e}")
    return list(subscribers)


def add_subscriber(chat_id):
    """Add a new chat ID to the subscribers list if not already present."""
    chat_id_str = str(chat_id)
    current_subs = set()
    if os.path.exists(SUBSCRIBERS_FILE):
        try:
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                current_subs = set(str(c) for c in json.load(f))
        except Exception:
            current_subs = set()

    if chat_id_str not in current_subs:
        current_subs.add(chat_id_str)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(current_subs), f, ensure_ascii=False, indent=2)
        return True
    return False


def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def pack_groups(lines, max_items=ITEMS_PER_MESSAGE, max_chars=CHARS_BUDGET_FOR_ITEMS):
    """Group lines into chunks of at most max_items, breaking earlier if character budget is exceeded."""
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


def send_message(chat_id, text, parse_mode="Markdown"):
    """Send a text message with specified parse mode."""
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }).encode("utf-8")
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

    recipients = load_subscribers()
    if not recipients:
        print("[notify_telegram] No recipients found in environment or subscriber list.")
        return

    for chat_id in recipients:
        print(f"[notify_telegram] sending to chat_id={chat_id!r}")

        if total_parts > MAX_TEXT_MESSAGES:
            summary = HEADER_TEMPLATE.format(
                kind=kind,
                part=1,
                total_parts=1,
                total_count=len(uris),
                date=date_str,
                time=time_str,
                handle=HANDLE,
            ) + f"\n({total_parts} message-blocks worth — sending as a file instead.)"
            send_message(chat_id, summary)
            time.sleep(SEND_DELAY_SECONDS)
            send_document(chat_id, file_path, caption=os.path.basename(file_path))
            time.sleep(SEND_DELAY_SECONDS)
            continue

        for i, group in enumerate(groups, 1):
            header = HEADER_TEMPLATE.format(
                kind=kind,
                part=i,
                total_parts=total_parts,
                total_count=len(uris),
                date=date_str,
                time=time_str,
                handle=HANDLE,
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
    """Log incoming user updates into a JSON file."""
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "username": username,
        "request": request_text
    }
    with open("bot_requests_log.json", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data) + "\n")


def reply_with_status(chat_id, text):
    """Reply to user with standard execution status block appended."""
    status_footer = "\n\nExecution Status: Bot is running and operational."
    send_message(chat_id, text + status_footer, parse_mode="HTML")


def fetch_and_process_updates(offset=None):
    """Poll updates from Telegram API and handle incoming commands."""
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
        update_id = update.get("update_id")
        next_offset = update_id + 1

        msg = update.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        user_id = msg.get("from", {}).get("id")
        username = msg.get("from", {}).get("username", "N/A")
        text = msg.get("text", "")

        if chat_id and text:
            append_request_log(user_id, username, text)

            if text.startswith("/start"):
                reply_with_status(chat_id, "Welcome. System ready.")
            elif text.startswith("/getConfigs") or text.startswith("/configs"):
                # 1. Immediate acknowledgment message
                send_message(chat_id, "صبر کن ایدیتو بردارم بعد برات میفرستوم", parse_mode="HTML")
                
                # 2. Save ID to subscribers list
                add_subscriber(chat_id)
                
                # 3. Fun status delay simulation
                time.sleep(1)
                send_message(chat_id, "کارگران مشغول کارند... 👷🏻‍♂️", parse_mode="HTML")
                
                # Random delay between 2 to 5 seconds
                random_wait = random.randint(2, 5)
                time.sleep(random_wait)
                
                # 4. Final completion message and status
                send_message(chat_id, "کار کارگرا تموم شد! 👷🏻‍♂️✅", parse_mode="HTML")
                reply_with_status(chat_id, "آیدی شما در لیست دریافت خودکار ثبت شد و کانفیگ‌ها ارسال خواهند شد.")
            else:
                reply_with_status(chat_id, "Unknown command logged.")

    return next_offset


def run_bot_daemon():
    """Start polling loop for live incoming message handling."""
    print("[bot_polling] Starting daemon...")
    offset = None
    while True:
        offset = fetch_and_process_updates(offset)
        time.sleep(1)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"

    if target == "daemon":
        run_bot_daemon()
    else:
        if target in ("config", "both"):
            notify("Config", "config", "config", limit=50)
        if target in ("proxy", "both"):
            notify("Proxy", "proxy", "proxy")