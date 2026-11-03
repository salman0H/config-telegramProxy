import os
import sys
import glob
import json
import time
import base64
import html
from http.client import HTTPException
import logging
import tempfile
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

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
                if not isinstance(data, (dict, list) if filepath == SUBSCRIBERS_FILE else dict):
                    raise ValueError("Invalid state structure")
                return data
        except Exception as e:
            logger.error("Cannot load state file=%s error=%s", filepath, type(e).__name__)
            raise ValueError(f"Invalid state file: {filepath}") from None
    return default

def load_subscribers():
    data = _load_json(SUBSCRIBERS_FILE, {})
    if isinstance(data, list):
        return {str(c): "N/A" for c in data}
    return {str(chat_id): username for chat_id, username in data.items()}

def save_json(filepath, data):
    directory = os.path.dirname(filepath) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as f:
            temporary = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temporary, filepath)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_subscribers(subs):
    save_json(SUBSCRIBERS_FILE, subs)


def load_offset():
    state = _load_json(OFFSET_FILE, {})
    offset = state.get("offset")
    if offset is not None and (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0):
        raise ValueError("Invalid polling offset")
    return offset


def save_offset(offset):
    if offset is not None:
        save_json(OFFSET_FILE, {"offset": offset})


def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    logger.debug("Output files folder=%s count=%d", folder, len(files))
    return files[-1] if files else None

def pack_groups(lines, max_items=ITEMS_PER_MESSAGE, max_chars=CHARS_BUDGET_FOR_ITEMS):
    groups = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line.encode("utf-16-le")) // 2 + 1
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
        retry_delay = min(2 ** attempt, 30)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("Invalid API response")
                return result
        except urllib.error.HTTPError as e:
            code = e.code
            if code == 429:
                try:
                    retry_delay = min(max(float(json.loads(e.read()).get("parameters", {}).get("retry_after", 5)), 1), 120) + 1
                except (ValueError, TypeError, AttributeError):
                    retry_delay = 6
            elif code < 500:
                logger.warning("Telegram request rejected method=%s status=%d", method, code)
                e.close()
                return {"ok": False, "error_code": code}
            logger.warning("Telegram retry method=%s status=%d attempt=%d/%d", method, code, attempt, max_retries)
            e.close()
        except (OSError, ValueError, HTTPException) as e:
            logger.warning("Telegram retry method=%s error=%s attempt=%d/%d", method, type(e).__name__, attempt, max_retries)
        if attempt < max_retries:
            time.sleep(retry_delay)
    logger.error("Telegram request exhausted method=%s attempts=%d", method, max_retries)
    return {"ok": False, "description": "Max retries reached"}


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

def send_document(chat_id, file_path, caption, content=None):
    boundary = "----telegram-boundary"
    if content is None:
        with open(file_path, "rb") as f:
            file_data = f.read()
    else:
        file_data = content.encode("utf-8")
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
    if TELEGRAM_ADMIN_CHAT_ID and str(user_id) == str(TELEGRAM_ADMIN_CHAT_ID):
        return True
    payload = json.dumps({"chat_id": TELEGRAM_CHANNEL_ID, "user_id": user_id}).encode("utf-8")
    data = _post("getChatMember", payload, {"Content-Type": "application/json"}, 10)
    result = data.get("result", {})
    if not data.get("ok"):
        logger.warning("Membership verification unavailable")
        return False
    return result.get("status") in ("member", "administrator", "creator") or (
        result.get("status") == "restricted" and result.get("is_member") is True
    )

def apply_custom_label(uri, label):
    if uri.startswith("vmess://"):
        try:
            b64 = uri[len("vmess://"):].split("#", 1)[0]
            padded = b64 + "=" * (-len(b64) % 4)
            data = json.loads(base64.b64decode(padded, altchars=b"-_").decode("utf-8"))
            data["ps"] = label
            new_b64 = base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")
            return "vmess://" + new_b64
        except Exception:
            return uri
    base = uri.split("#")[0]
    return f"{base}#{urllib.parse.quote(label, safe='@')}"

def poll_updates():
    logger.info("[Polling] Fetching Telegram updates...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("[Error] TELEGRAM_BOT_TOKEN is missing.")
        return

    offset = load_offset()
    payload = {"timeout": 5, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    response = _post("getUpdates", json.dumps(payload).encode("utf-8"), {"Content-Type": "application/json"}, 15)
    if not response.get("ok"):
        logger.error("Polling failed; offset preserved")
        return
    updates = response.get("result", [])
    if not isinstance(updates, list):
        logger.error("Invalid polling response; offset preserved")
        return

    if not updates:
        logger.info("[Polling] No new messages found.")
        return

    logger.info(f"[Polling] Found {len(updates)} new update(s).")
    subs = load_subscribers()
    next_offset = offset

    subscribed = denied = unsubscribed = 0
    for update in updates:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            continue
        next_offset = max(next_offset or 0, update_id + 1)
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        user_id = msg.get("from", {}).get("id")
        username = msg.get("from", {}).get("username", "N/A")
        text = msg.get("text", "")

        if not chat_id or not isinstance(text, str) or not text.strip():
            continue

        command = text.split()[0].split("@", 1)[0]
        if command in ("/start", "/getConfigs"):
            if is_user_member(user_id):
                subs[chat_id] = username
                send_message(chat_id, "✅ اشتراک شما فعال شد. پروکسی‌ها به محض آپدیت به صورت خودکار برای شما ارسال می‌شوند.")
                subscribed += 1
            else:
                send_message(chat_id, f"سلام 👋\nبرای دریافت پروکسی‌ها ابتدا در کانال {TELEGRAM_CHANNEL_ID} عضو شوید، سپس مجدداً دستور /start را ارسال کنید.")
                denied += 1
        
        elif command == "/stop":
            if chat_id in subs:
                del subs[chat_id]
                send_message(chat_id, "❌ اشتراک شما لغو شد.")
                unsubscribed += 1

    save_subscribers(subs)
    save_offset(next_offset)
    logger.info("Polling completed updates=%d subscribed=%d denied=%d unsubscribed=%d", len(updates), subscribed, denied, unsubscribed)
    if TELEGRAM_ADMIN_CHAT_ID and (subscribed or denied or unsubscribed):
        send_message(TELEGRAM_ADMIN_CHAT_ID, f"گزارش عضویت\nفعال: {subscribed}\nردشده/تأییدنشده: {denied}\nلغو: {unsubscribed}")

def split_report(text, max_units=3500):
    """Split plain text without cutting Unicode characters or dropping content."""
    chunks = []
    current = []
    units = 0
    for line in text.splitlines(keepends=True):
        line_units = len(line.encode("utf-16-le")) // 2
        if current and units + line_units > max_units:
            chunks.append("".join(current))
            current, units = [], 0
        for character in line:
            size = 2 if ord(character) > 0xFFFF else 1
            if units + size > max_units:
                chunks.append("".join(current))
                current, units = [], 0
            current.append(character)
            units += size
    if current:
        chunks.append("".join(current))
    return chunks


def send_admin_report(summary, recipients, list_title="گیرندگان موفق"):
    """Send the complete recipient list only to the configured administrator."""
    if not TELEGRAM_ADMIN_CHAT_ID:
        logger.warning("Admin report skipped: TELEGRAM_ADMIN_CHAT_ID is not configured")
        return False
    entries = []
    for index, (chat_id, username) in enumerate(recipients.items(), 1):
        name = " ".join(str(username or "").split())
        if not name or name == "N/A":
            name = "بدون نام کاربری"
        elif name != "Admin":
            name = "@" + name.lstrip("@")
        entries.append(f"{index}. {name} | ID: {chat_id}")
    report = summary + f"\n\n👥 {list_title}:\n" + ("\n".join(entries) or "هیچ‌کس")
    chunks = split_report(report)
    delivered = True
    for index, chunk in enumerate(chunks, 1):
        text = f"📋 گزارش ادمین — بخش {index}/{len(chunks)}\n\n" + chunk
        result = send_message(TELEGRAM_ADMIN_CHAT_ID, text)
        if not result or not result.get("ok"):
            delivered = False
            logger.error("Admin report part failed part=%d total=%d", index, len(chunks))
        if index < len(chunks):
            time.sleep(SEND_DELAY_SECONDS)
    if delivered:
        logger.info("Complete admin report delivered recipients=%d parts=%d", len(recipients), len(chunks))
    return delivered


def notify(kind, folder, suffix, limit=None):
    logger.info(f"[Notify] Starting broadcast for {kind}...")
    if not TELEGRAM_BOT_TOKEN:
        logger.error("[Error] TELEGRAM_BOT_TOKEN is missing!")
        return
    if not TELEGRAM_CHANNEL_ID:
        logger.error("[Error] TELEGRAM_CHANNEL_ID is missing!")
        return

    logger.info(f"[Notify] Using Channel ID: {TELEGRAM_CHANNEL_ID}")
    file_path = latest_file(folder, suffix)
    if not file_path:
        logger.info(f"[Notify] Aborted: No file found in '{folder}' matching '*_{suffix}.txt'")
        return

    logger.info(f"[Notify] Target file found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        raw_uris = [line.strip() for line in f if line.strip()]
    
    if limit is not None:
        raw_uris = raw_uris[:limit]
        
    if not raw_uris:
        logger.info(f"[Notify] Aborted: File {file_path} is empty.")
        return

    if kind == "Config":
        uris = [apply_custom_label(uri, TELEGRAM_CHANNEL_ID) for uri in raw_uris]
    else:
        uris = raw_uris

    groups = pack_groups(uris)
    total_parts = len(groups)
    
    now = datetime.now(TEHRAN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    
    recipients = load_subscribers()
    logger.info(f"[Notify] Loaded {len(recipients)} subscriber(s) from database.")
    
    if TELEGRAM_ADMIN_CHAT_ID and str(TELEGRAM_ADMIN_CHAT_ID) not in recipients:
        recipients[str(TELEGRAM_ADMIN_CHAT_ID)] = "Admin"

    active_users = {}
    failed = skipped = 0
    started = time.perf_counter()

    if not recipients:
        logger.info("[Notify] Aborted: No recipients found.")
        return

    use_document = total_parts > MAX_TEXT_MESSAGES or any(
        len(line.encode("utf-16-le")) // 2 > CHARS_BUDGET_FOR_ITEMS for line in uris
    )
    for chat_id in recipients:
        if str(chat_id) != str(TELEGRAM_ADMIN_CHAT_ID) and not is_user_member(chat_id):
            skipped += 1
            logger.debug("Recipient skipped: membership not verified")
            continue
            
        logger.debug("Sending broadcast to recipient")
        success = True

        if use_document:
            summary = HEADER_TEMPLATE.format(
                kind=kind, part=1, total_parts=1, total_count=len(uris),
                date=date_str, time=time_str, handle=TELEGRAM_CHANNEL_ID,
            ) + "\n(فایل کانفیگ‌ها به دلیل حجم بالا پیوست شد)"
            res = send_message(chat_id, summary)
            if res and res.get("ok"):
                time.sleep(SEND_DELAY_SECONDS)
                document_result = send_document(chat_id, file_path, caption=os.path.basename(file_path), content="\n".join(uris) + "\n")
                success = bool(document_result and document_result.get("ok"))
            else:
                success = False
        else:
            for i, group in enumerate(groups, 1):
                header = HEADER_TEMPLATE.format(
                    kind=kind, part=i, total_parts=total_parts, total_count=len(uris),
                    date=date_str, time=time_str, handle=TELEGRAM_CHANNEL_ID,
                )
                if kind == "Proxy":
                    body = "\n".join(f"<blockquote>{html.escape(line)}</blockquote>" for line in group)
                    parse_mode = "HTML"
                else:
                    body = "<pre>" + html.escape("\n".join(group)) + "</pre>"
                    parse_mode = "HTML"
                
                res = send_message(chat_id, html.escape(header) + body, parse_mode=parse_mode)
                if not res or not res.get("ok"):
                    logger.warning("Broadcast message failed kind=%s part=%d", kind, i)
                    success = False
                    break
                time.sleep(SEND_DELAY_SECONDS)
                
        if success:
            active_users[chat_id] = recipients[chat_id]
        else:
            failed += 1

    logger.info("Broadcast completed kind=%s recipients=%d delivered=%d failed=%d skipped=%d elapsed_seconds=%.2f",
                kind, len(recipients), len(active_users), failed, skipped, time.perf_counter() - started)
    if TELEGRAM_ADMIN_CHAT_ID:
        report = (
            "👨‍💻 گزارش ارسال\n\n"
            f"🗂 نوع: {kind}\n"
            f"📄 فایل: {os.path.basename(file_path)}\n"
            f"🔢 تعداد آیتم: {len(uris)}\n"
            f"✅ موفق: {len(active_users)} | ❌ ناموفق: {failed} | ⏭ تأییدنشده: {skipped}\n"
            f"📅 {date_str} | ⏰ {time_str}"
        )
        send_admin_report(report, active_users)

if __name__ == "__main__":
    from logging_utils import configure_logging
    configure_logging()
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    
    if target not in ("poll", "config", "proxy", "both") or not TELEGRAM_BOT_TOKEN:
        logger.error("Valid target and TELEGRAM_BOT_TOKEN are required")
        sys.exit(1)
    try:
        if target == "poll":
            poll_updates()
        else:
            if target in ("config", "both"):
                notify("Config", "config", "config", limit=50)
            if target in ("proxy", "both"):
                notify("Proxy", "proxy", "proxy")
    except (OSError, ValueError):
        logger.error("Bot stopped: cannot read or save state/output; inspect files before retrying")
        sys.exit(1)
