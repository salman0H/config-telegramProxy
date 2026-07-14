import os
import sys
import glob
import json
import urllib.request

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

TELEGRAM_MESSAGE_LIMIT = 4096

# ---------------------------------------------------------------------------
# Customize this. {index}, {uri}, {ping}, {location} are available.
# ping/location come from README.md's markdown table; if a URI isn't found
# there, ping/location fall back to "?".
# ---------------------------------------------------------------------------
ENTRY_FORMAT = "{index}. `{uri}`\n   ping: {ping}ms | {location}\n"
HEADER_FORMAT = "*{kind} update* — {count} entries\n\n"


def latest_file(folder, suffix):
    pattern = os.path.join(folder, f"*_{suffix}.txt")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def parse_readme_table(readme_path):
    """Map truncated-uri-prefix -> (ping, location) from README.md's github table."""
    mapping = []
    if not os.path.exists(readme_path):
        return mapping
    with open(readme_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or "Ping" in line or set(line) <= set("|-"):
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) != 3:
                continue
            prefix, ping, location = cols
            prefix = prefix.rstrip(".")  # strip trailing "..."
            mapping.append((prefix, ping, location))
    return mapping


def lookup(uri, table):
    for prefix, ping, location in table:
        if uri.startswith(prefix):
            return ping, location
    return "?", "?"


def build_messages(kind, uris, table):
    header = HEADER_FORMAT.format(kind=kind, count=len(uris))
    chunks = [header]
    for i, uri in enumerate(uris, 1):
        ping, location = lookup(uri, table)
        entry = ENTRY_FORMAT.format(index=i, uri=uri, ping=ping, location=location)
        if len(chunks[-1]) + len(entry) > TELEGRAM_MESSAGE_LIMIT:
            chunks.append("")
        chunks[-1] += entry
    return chunks


def send_message(text):
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}/sendMessage", data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_document(file_path, caption):
    boundary = "----telegram-boundary"
    with open(file_path, "rb") as f:
        file_data = f.read()

    body = []
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{TELEGRAM_CHAT_ID}\r\n")
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n")
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{os.path.basename(file_path)}\"\r\nContent-Type: text/plain\r\n\r\n")
    prefix = "".join(body).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = prefix + file_data + suffix

    req = urllib.request.Request(f"{API_BASE}/sendDocument", data=payload,
                                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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

    table = parse_readme_table(os.path.join(folder, "README.md"))

    # Small result set: send as formatted text. Large: send as file + short summary.
    if len(uris) <= 15:
        for chunk in build_messages(kind, uris, table):
            send_message(chunk)
    else:
        send_message(HEADER_FORMAT.format(kind=kind, count=len(uris)) + "full list attached.")
        send_document(file_path, caption=os.path.basename(file_path))

    print(f"[notify_telegram] sent {len(uris)} {suffix} entries from {file_path}.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    if target in ("config", "both"):
        notify("Config", "config", "config")
    if target in ("proxy", "both"):
        notify("Proxy", "proxy", "proxy")