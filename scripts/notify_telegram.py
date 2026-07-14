import os
import sys
import glob
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Multiple recipients: set TELEGRAM_CHAT_IDS="111,222,333" (comma-separated).
# Falls back to the single TELEGRAM_CHAT_ID if TELEGRAM_CHAT_IDS isn't set.
_raw_ids = os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID", "")
# Strip stray quotes/whitespace — the #1 cause of "chat not found" is a secret
# value like "123456789" (with literal quote characters) instead of 123456789.
TELEGRAM_CHAT_IDS = [c.strip().strip('"').strip("'") for c in _raw_ids.split(",") if c.strip()]
if not TELEGRAM_CHAT_IDS:
    raise RuntimeError("No TELEGRAM_CHAT_ID or TELEGRAM_CHAT_IDS set in environment.")

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

TELEGRAM_MESSAGE_LIMIT = 4096
ITEMS_PER_MESSAGE = 10
# Leave headroom under the hard 4096 cap for the header + code-fence characters.
CHARS_BUDGET_FOR_ITEMS = 3600
SEND_DELAY_SECONDS = 2  # spacing between messages, per recipient
# If a result set would need more than this many code-block messages, send a
# short summary + the raw file as an attachment instead. Sending dozens of
# messages back-to-back reliably triggers Telegram's per-chat flood limit.
MAX_TEXT_MESSAGES = 15

HANDLE = "@sentencedIntoMusic"
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

# ---------------------------------------------------------------------------
# Edit this to change how each message looks. Placeholders available:
# {kind} {part} {total_parts} {total_count} {date} {time} {handle}
# The code-fenced list of URIs is appended automatically after this header.
# ---------------------------------------------------------------------------
HEADER_TEMPLATE = (
    "سلام 👋\n\n"
    "🗂 بروزرسانی {kind} — بخش {part}/{total_parts}\n"
    "🔢 تعداد کل: {total_count}\n"
    "📅 {date} | ⏰ {time}\n"
    "📣 {handle}\n"
)


def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def pack_groups(lines, max_items=ITEMS_PER_MESSAGE, max_chars=CHARS_BUDGET_FOR_ITEMS):
    """Group lines into chunks of at most `max_items`, breaking earlier if the
    running character count would blow the budget (long config URIs)."""
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


def send_message(chat_id, text):
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    return _post("sendMessage", payload, {"Content-Type": "application/json"}, 15)


def send_document(chat_id, file_path, caption):
    boundary = "----telegram-boundary"
    with open(file_path, "rb") as f:
        file_data = f.read()

    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{os.path.basename(file_path)}\"\r\nContent-Type: text/plain\r\n\r\n",
    ]
    prefix = "".join(parts).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = prefix + file_data + suffix

    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return _post("sendDocument", payload, headers, 30)


# <<< تغییر اول: اضافه شدن پارامتر limit برای محدود کردن تعداد خطوط
def notify(kind, folder, suffix, limit=None):
    file_path = latest_file(folder, suffix)
    if not file_path:
        print(f"[notify_telegram] no {suffix} file found in {folder}, skipping.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        uris = [line.strip() for line in f if line.strip()]

    # <<< تغییر دوم: جدا کردن تعداد مشخص (پنجاه تای اول)
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

    for chat_id in TELEGRAM_CHAT_IDS:
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
            body = "```\n" + "\n".join(group) + "\n```"
            send_message(chat_id, header + body)
            time.sleep(SEND_DELAY_SECONDS)

    print(f"[notify_telegram] sent {len(uris)} {suffix} entries ({total_parts} messages) from {file_path} to {len(TELEGRAM_CHAT_IDS)} recipient(s).")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    if target in ("config", "both"):
        # <<< تغییر سوم: مقدار limit=50 فقط برای کانفیگ‌ها ارسال می‌شود
        notify("Config", "config", "config", limit=50)
    if target in ("proxy", "both"):
        notify("Proxy", "proxy", "proxy")