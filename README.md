# High-Speed Asynchronous Proxy Tester & Telegram Bot Notifier

## Overview
This repository contains a high-performance Python application designed to evaluate V2Ray configurations (VLESS, Trojan) and Telegram MTProto proxies based on raw TCP latency. High concurrency (`asyncio`) allows thousands of endpoints to be evaluated in under 15 seconds.

Additionally, the suite includes an automated **Telegram Notification & Interactive Bot System** that continuously delivers fresh, benchmarked proxies/configs to subscribed users and Telegram channels.

---

## Key Features

- **Fast Latency Testing:** Concurrent TCP handshakes (`asyncio.open_connection`) test network reachability with minimal latency overhead.
- **Decoding & Extraction:** Automatically decodes Base64 payloads and uses regex parsing to bypass heavy proxy client dependencies.
- **Geolocation Resolution:** Batches target IP addresses to `ip-api.com` to resolve country locations.
- **Automated GitHub Actions:** Scheduled workflows run every 12 hours to test endpoints, update repository files, and dispatch updates to Telegram.
- **Telegram Broadcasting & Bot Daemon:**
  - Sends chunked markdown/HTML messages or full log files based on Telegram API limits.
  - Interactive **Daemon Mode** to process incoming Telegram bot commands (`/getConfigs`, `/start`, etc.).
  - **Dynamic Subscribers:** Automatically logs user Chat IDs (`subscribers.json`) for automatic distribution upon command triggers.
  - **Request Logging:** Audits user commands and incoming requests (`bot_requests_log.json`).

---

## Technical Mechanisms

1. **Benchmarking Core (`main.py`)**
   - Fetches configuration & proxy lists from remote sources.
   - Parses endpoints, benchmarks TCP connections, and resolves node locations.
   - Outputs markdown summary tables (`README.md`) and raw URI text files inside `config/` and `proxy/` directories.

2. **Telegram Delivery & Bot Daemon (`scripts/notify_telegram.py`)**
   - **Broadcast Mode:** Dispatches parsed configurations and proxy lines directly to registered Telegram chats/channels.
   - **Daemon Mode:** Polls Telegram API (`getUpdates`) for incoming user interactions, registers new user IDs, and provides interactive responses.

---

## Bot Commands Reference

| Command | Description |
| :--- | :--- |
| `/start` | Check bot status and verify system readiness. |
| `/getConfigs` | Subscribe your Chat ID to the automatic update list and receive latest configs. |
| `/configs` | Trigger manually to receive current configurations and MTProto proxies. |
| `/status` | View real-time operational status of the bot daemon. |
| `/help` | Display command guide and usages. |

---

## Requirements & Installation

- Python 3.9+
- Dependencies: `pyperclip`, `tabulate`

### Local Setup

```bash
# Clone repository
git clone [https://github.com/your-username/config-telegramProxy.git](https://github.com/your-username/config-telegramProxy.git)
cd config-telegramProxy

# Set up virtual environment (Debian/Ubuntu PEP 668 compliance)
python3 -m venv .venv
source .venv/bin/activate

# Install required packages
pip install pyperclip tabulate
