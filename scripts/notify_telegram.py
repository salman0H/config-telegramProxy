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
SEND_DELAY_SECONDS = 1.2  # spacing between messages, per recipient

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


def _post(method, data, headers, timeout):
    req = urllib.request.Request(f"{API_BASE}/{method}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[notify_telegram] Telegram API error {e.code}: {body}")
        raise


def send_message(chat_id, text):
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    return _post("sendMessage", payload, {"Content-Type": "application/json"}, 15)


def notify(kind, folder, suffix):
    file_path = latest_file(folder, suffix)
    if not file_path:
        print(f"[notify_telegram] no {suffix} file found in {folder}, skipping.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        uris = [line.strip() for line in f if line.strip()]

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
        notify("Config", "config", "config")
    if target in ("proxy", "both"):
        notify("Proxy", "proxy", "proxy")