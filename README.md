# High-Speed Asynchronous Proxy Tester

## Overview
This Python application evaluates V2Ray configurations (VLESS, Trojan) and Telegram MTProto proxies based on raw TCP latency. The script is highly optimized to test thousands of endpoints in under 15 seconds using asynchronous socket connections.

## Technical Mechanisms
- **Decoding:** Automatically detects and decodes Base64 payloads common in subscription links.
- **Extraction:** Parses target IP addresses and ports natively using Regex, bypassing the need for heavy proxy cores (like Xray/Sing-box).
- **Latency Testing:** Executes high-concurrency TCP handshakes (`asyncio.open_connection`). Tests network reachability and latency, ignoring cryptographic handshake overhead.
- **Geolocation:** Batches target IPs to `ip-api.com` for rapid location resolution of successful nodes.

## Requirements
- Python 3.9+
- Third-party modules: `pyperclip`, `tabulate`

### Installation
If running into PEP 668 `externally-managed-environment` errors on Debian/Ubuntu, utilize a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyperclip tabulate# config-telegramProxy
