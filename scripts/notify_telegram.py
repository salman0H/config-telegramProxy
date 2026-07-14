import os
import sys
import glob
import json
import time
import urllib.request
import urllib.error

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Multiple recipients: set TELEGRAM_CHAT_IDS="111,222,333" (comma-separated).
# Falls back to the single TELEGRAM_CHAT_ID if TELEGRAM_CHAT_IDS isn't set.
_raw_ids = os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [c.strip() for c in _raw_ids.split(",") if c.strip()]
if not TELEGRAM_CHAT_IDS:
    raise RuntimeError("No TELEGRAM_CHAT_ID or TELEGRAM_CHAT_IDS set in environment.")

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

TELEGRAM_MESSAGE_LIMIT = 4096
# If the raw list would need more than this many messages, send it as a file
# attachment instead, to avoid hammering Telegram's per-chat flood limits.
MAX_TEXT_CHUNKS = 5
SEND_DELAY_SECONDS = 1  # spacing between messages, per recipient


def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def chunk_lines(lines, limit):
    """Pack lines into chunks, each under `limit` chars, without splitting a line."""
    chunks = [""]
    for line in lines:
        candidate = chunks[-1] + line + "\n"
        if len(candidate) > limit and chunks[-1]:
            chunks.append(line + "\n")
        else:
            chunks[-1] = candidate
    return [c for c in chunks if c.strip()]


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

    chunks = chunk_lines(uris, TELEGRAM_MESSAGE_LIMIT)

    for chat_id in TELEGRAM_CHAT_IDS:
        if len(chunks) <= MAX_TEXT_CHUNKS:
            for chunk in chunks:
                send_message(chat_id, chunk)
                time.sleep(SEND_DELAY_SECONDS)
        else:
            send_message(chat_id, f"{kind} update — {len(uris)} entries — full list attached.")
            time.sleep(SEND_DELAY_SECONDS)
            send_document(chat_id, file_path, caption=os.path.basename(file_path))
            time.sleep(SEND_DELAY_SECONDS)

    print(f"[notify_telegram] sent {len(uris)} {suffix} entries from {file_path} to {len(TELEGRAM_CHAT_IDS)} recipient(s).")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    if target in ("config", "both"):
        notify("Config", "config", "config")
    if target in ("proxy", "both"):
        notify("Proxy", "proxy", "proxy")