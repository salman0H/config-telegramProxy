import os
import json
import urllib.request
from datetime import datetime, timedelta, timezone

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID") or "@sentencedIntoMusic"
SUBSCRIBERS_FILE = "subscribers.json"
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

def is_user_member(user_id):
    if str(user_id) == "748378868":
        return True
    if not TELEGRAM_CHANNEL_ID:
        return True
    url = f"{API_BASE}/getChatMember?chat_id={TELEGRAM_CHANNEL_ID}&user_id={user_id}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("result", {}).get("status")
            return status in ["member", "administrator", "creator"]
    except Exception:
        return False

def run_dry_run():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        return

    try:
        with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
            recipients = json.load(f)
    except Exception:
        recipients = {}

    if str(TELEGRAM_ADMIN_CHAT_ID) not in recipients:
        recipients[str(TELEGRAM_ADMIN_CHAT_ID)] = "Admin"

    active_users = []
    for chat_id, username in recipients.items():
        if str(chat_id) != str(TELEGRAM_ADMIN_CHAT_ID) and not is_user_member(chat_id):
            continue
        active_users.append(f"{username} ({chat_id})")

    now = datetime.now(TEHRAN_TZ)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    report = (
        "👨‍💻 گزارش سیستم - شبیه‌سازی ارسال (Dry Run)\n\n"
        f"🗂 نوع: Check\n"
        f"👥 تعداد گیرندگان مجاز: {len(active_users)}\n"
        f"📅 {date_str} | ⏰ {time_str}\n\n"
        "لیست کاربران:\n" + "\n".join(active_users)
    )

    payload = json.dumps({"chat_id": TELEGRAM_ADMIN_CHAT_ID, "text": report}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/sendMessage", 
        data=payload, 
        headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Failed to send report: {e}")

if __name__ == "__main__":
    run_dry_run()
