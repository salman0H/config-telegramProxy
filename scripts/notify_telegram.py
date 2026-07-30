import os
import sys
import glob
import json
import time
import base64
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID") or "@sentencedIntoMusic"

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
ITEMS_PER_MESSAGE = 10
CHARS_BUDGET_FOR_ITEMS = 3600
SEND_DELAY_SECONDS = 2
MAX_TEXT_MESSAGES = 15
SUBSCRIBERS_FILE = "subscribers.json"
OFFSET_FILE = "scripts/telegram_offset.json"
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

HEADER_TEMPLATE = (
    "سلام 👋\n\n"
    "🗂 بروزرسانی {kind} — بخش {part}/{total_parts}\n"
    "🔢 تعداد کل: {total_count}\n"
    "📅 {date} | ⏰ {time}\n"
    "📣 {handle}\n"
)

def _load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, type(default)) else default
        except Exception as e:
            print(f"[Error] Failed to load {filepath}: {e}")
    return default

def load_subscribers():
    data = _load_json(SUBSCRIBERS_FILE, {})
    if isinstance(data, list):
        return {str(c): "N/A" for c in data}
    return data

def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False, indent=2)

def load_offset():
    state = _load_json(OFFSET_FILE, {})
    return state.get("offset")

def save_offset(offset):
    if offset is None:
        return
    state = _load_json(OFFSET_FILE, {})
    state["offset"] = offset
    os.makedirs(os.path.dirname(OFFSET_FILE), exist_ok=True)
    with open(OFFSET_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    print(f"[Debug] Searching for pattern: {pattern} -> Found: {files}")
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
                time.sleep(retry_after + 1)
                continue
            print(f"[Error] API HTTPError {e.code}: {body}")
            raise RuntimeError(f"API HTTPError {e.code}: {body}")
    raise RuntimeError(f"API request failed after {max_retries} attempts.")

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

def is_user_member(user_id):
    if not TELEGRAM_CHANNEL_ID:
        return True
    url = f"{API_BASE}/getChatMember?chat_id={TELEGRAM_CHANNEL_ID}&user_id={user_id}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("result", {}).get("status")
            return status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"[Membership] Verification failed for {user_id}: {e}")
        return False

def apply_custom_label(uri, label):
    if uri.startswith("vmess://"):
        try:
            b64 = uri[len("vmess://"):]
            padded = b64 + "=" * (-len(b64) % 4)
            data = json.loads(base64.b64decode(padded).decode("utf-8"))
            data["ps"] = label
            new_b64 = base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")
            return "vmess://" + new_b64
        except Exception:
            return uri
    base = uri.split("#")[0]
    return f"{base}#{urllib.parse.quote(label, safe='@')}"

def poll_updates():
    print("[Polling] Fetching Telegram updates...")
    if not TELEGRAM_BOT_TOKEN:
        print("[Error] TELEGRAM_BOT_TOKEN is empty.")
        return

    offset = load_offset()
    url = f"{API_BASE}/getUpdates?timeout=5"
    if offset:
        url += f"&offset={offset}"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            updates = json.loads(resp.read().decode("utf-8")).get("result", [])
    except Exception as e:
        print(f"[Polling] Error fetching updates: {e}")
        return

    if not updates:
        print("[Polling] No new messages found.")
        return

    print(f"[Polling] Found {len(updates)} new update(s).")
    subs = load_subscribers()
    next_offset = offset

    for update in updates:
        next_offset = update.get("update_id") + 1
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        user_id = msg.get("from", {}).get("id")
        username = msg.get("from", {}).get("username", "N/A")
        text = msg.get("text", "")

        if not chat_id or not text:
            continue

        if text.startswith("/start") or text.startswith("/getConfigs"):
            if is_user_member(user_id):
                subs[chat_id] = username
                send_message(chat_id, "✅ اشتراک شما فعال شد. پروکسی‌ها به محض آپدیت به صورت خودکار برای شما ارسال می‌شوند.")
                if TELEGRAM_ADMIN_CHAT_ID:
                    send_message(TELEGRAM_ADMIN_CHAT_ID, f"🟢 [System Log]\nUser @{username} ({chat_id}) subscribed successfully.")
            else:
                send_message(chat_id, "سلام 👋\nبرای دریافت پروکسی‌ها ابتدا در کانال @sentencedIntoMusic عضو شوید، سپس مجدداً دستور /start را ارسال کنید.")
                if TELEGRAM_ADMIN_CHAT_ID:
                    send_message(TELEGRAM_ADMIN_CHAT_ID, f"🔴 [System Log]\nUser @{username} ({chat_id}) denied. Not in channel.")
        
        elif text.startswith("/stop"):
            if chat_id in subs:
                del subs[chat_id]
                send_message(chat_id, "❌ اشتراک شما لغو شد.")
                if TELEGRAM_ADMIN_CHAT_ID:
                    send_message(TELEGRAM_ADMIN_CHAT_ID, f"⚪️ [System Log]\nUser @{username} ({chat_id}) unsubscribed.")

    save_subscribers(subs)
    save_offset(next_offset)
    print("[Polling] Offset and subscribers saved.")

def notify(kind, folder, suffix, limit=None):
    print(f"[Notify] Starting broadcast for {kind}...")
    if not TELEGRAM_BOT_TOKEN:
        print("[Error] TELEGRAM_BOT_TOKEN is empty. Check GitHub Secrets.")
        return
    if not TELEGRAM_CHANNEL_ID:
        print("[Error] TELEGRAM_CHANNEL_ID is empty.")
        return

    file_path = latest_file(folder, suffix)
    if not file_path:
        print(f"[Notify] Aborted: No file found matching '{folder}/*_{suffix}.txt'")
        return

    print(f"[Notify] Target file found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        raw_uris = [line.strip() for line in f if line.strip()]
    
    if limit is not None:
        raw_uris = raw_uris[:limit]
        
    if not raw_uris:
        print(f"[Notify] Aborted: File {file_path} is empty.")
        return

    uris = [apply_custom_label(uri, TELEGRAM_CHANNEL_ID) for uri in raw_uris]
    groups = pack_groups(uris)
    total_parts = len(groups)
    
    now = datetime.now(TEHRAN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    
    recipients = load_subscribers()
    
    if TELEGRAM_ADMIN_CHAT_ID and str(TELEGRAM_ADMIN_CHAT_ID) not in recipients:
        recipients[str(TELEGRAM_ADMIN_CHAT_ID)] = "Admin"

    active_users = []

    if not recipients:
        print("[Notify] Aborted: No subscribers found in database.")
        return

    for chat_id, username in recipients.items():
        if str(chat_id) != str(TELEGRAM_ADMIN_CHAT_ID) and not is_user_member(chat_id):
            print(f"[Notify] Skipped {chat_id} (not a member).")
            continue
            
        active_users.append(f"{username} ({chat_id})")
        print(f"[Notify] Sending to {username} ({chat_id})...")

        if total_parts > MAX_TEXT_MESSAGES:
            summary = HEADER_TEMPLATE.format(
                kind=kind, part=1, total_parts=1, total_count=len(uris),
                date=date_str, time=time_str, handle=TELEGRAM_CHANNEL_ID,
            ) + f"\n(فایل کانفیگ‌ها به دلیل حجم بالا پیوست شد)"
            send_message(chat_id, summary)
            time.sleep(SEND_DELAY_SECONDS)
            send_document(chat_id, file_path, caption=os.path.basename(file_path))
        else:
            for i, group in enumerate(groups, 1):
                header = HEADER_TEMPLATE.format(
                    kind=kind, part=i, total_parts=total_parts, total_count=len(uris),
                    date=date_str, time=time_str, handle=TELEGRAM_CHANNEL_ID,
                )
                if kind == "Proxy":
                    body = "\n".join(f"<blockquote>{line}</blockquote>" for line in group)
                    parse_mode = "HTML"
                else:
                    body = "```\n" + "\n".join(group) + "\n```"
                    parse_mode = "Markdown"
                
                send_message(chat_id, header + body, parse_mode=parse_mode)
                time.sleep(SEND_DELAY_SECONDS)

    if TELEGRAM_ADMIN_CHAT_ID:
        report = (
            "👨‍💻 گزارش سیستم - ارسال موفق\n\n"
            f"🗂 نوع: {kind}\n"
            f"👥 تعداد گیرندگان: {len(active_users)}\n"
            f"📅 {date_str} | ⏰ {time_str}\n\n"
            "لیست کاربران:\n" + "\n".join(active_users)
        )
        send_message(TELEGRAM_ADMIN_CHAT_ID, report)
        print("[Notify] Admin report sent.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    
    if target == "poll":
        poll_updates()
    else:
        if target in ("config", "both"):
            notify("Config", "config", "config", limit=50)
        if target in ("proxy", "both"):
            notify("Proxy", "proxy", "proxy")