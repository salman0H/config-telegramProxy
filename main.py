import argparse
import asyncio
import base64
import json
import os
import binascii
from http.client import HTTPException
import logging
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

import pyperclip
from tabulate import tabulate

CONFIG_URL = "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt"
PROXY_URL = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"
TIMEOUT_SECONDS = 3.0
CONCURRENCY_LIMIT = 100
HTTP_TIMEOUT = 15
HTTP_RETRIES = 3
HTTP_RETRY_DELAY = 2
logger = logging.getLogger(__name__)
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

def fetch_url(url):
    last_error = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                return response.read().decode('utf-8-sig')
        except (urllib.error.URLError, OSError, TimeoutError, HTTPException) as e:
            last_error = e
            logger.warning("Source fetch failed attempt=%d/%d error=%s", attempt, HTTP_RETRIES, type(e).__name__)
            if isinstance(e, urllib.error.HTTPError):
                e.close()
            if isinstance(e, urllib.error.HTTPError) and e.code not in (408, 429) and e.code < 500:
                break
            if attempt < HTTP_RETRIES:
                time.sleep(HTTP_RETRY_DELAY * 2 ** (attempt - 1))
    raise last_error

def fetch_data(source_type, input_val):
    raw_data = ""
    if source_type == "1":
        with open(input_val, "r", encoding="utf-8") as f:
            raw_data = f.read()
    elif source_type == "2":
        raw_data = pyperclip.paste()
    elif source_type == "3":
        raw_data = fetch_url(input_val)

    return parse_subscription(raw_data)


def decode_base64(value):
    value = "".join(value.split())
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True).decode("utf-8")


def parse_subscription(raw_data):
    text = raw_data.lstrip("\ufeff").strip()
    if "://" not in text:
        try:
            text = decode_base64(text)
        except (ValueError, UnicodeError, binascii.Error):
            pass
    # Retain the first copy; fragment labels do not change connection settings.
    unique = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "://" in line:
            unique.setdefault(line.split("#", 1)[0], line)
    return list(unique.values())


def extract_target(uri, mode):
    try:
        parsed = urlsplit(uri)
        if mode == "2":
            if not ((parsed.scheme == "tg" and parsed.netloc == "proxy") or
                    (parsed.scheme == "https" and parsed.hostname in ("t.me", "telegram.me") and parsed.path == "/proxy")):
                return None, None
            params = parse_qs(parsed.query)
            host = params.get("server", [""])[0].strip("[]")
            port = int(params.get("port", ["0"])[0])
        elif mode == "1":
            if parsed.scheme == "vmess":
                data = json.loads(decode_base64(uri[len("vmess://"):].split("#", 1)[0]))
                host, port = data.get("add"), int(data.get("port", 0))
            elif parsed.scheme in ("vless", "trojan", "ss", "ssr"):
                if parsed.scheme == "ssr":
                    payload = decode_base64(uri[len("ssr://"):]).split("/?", 1)[0]
                    host, port, *_ = payload.rsplit(":", 5)
                    host, port = host.strip("[]"), int(port)
                else:
                    if parsed.scheme == "ss" and "@" not in parsed.netloc:
                        payload = decode_base64(unquote(parsed.netloc))
                        parsed = urlsplit("ss://" + payload)
                    host, port = parsed.hostname, parsed.port
            else:
                # Hysteria/TUIC use UDP and cannot be evaluated with a TCP probe.
                return None, None
        else:
            return None, None
        if isinstance(host, str) and host and not any(c.isspace() for c in host) and port and 1 <= port <= 65535:
            return host.lower(), port
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, AttributeError):
        pass
    return None, None


async def tcp_ping(uri, host, port, semaphore):
    async with semaphore:
        start_time = time.perf_counter()
        writer = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=TIMEOUT_SECONDS
            )
            latency = (time.perf_counter() - start_time) * 1000
            return uri, host, latency
        except (OSError, TimeoutError, ValueError):
            return uri, host, None
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1)
                except (OSError, TimeoutError):
                    pass


async def test_targets(lines, mode):
    endpoints = {}
    for uri in lines:
        host, port = extract_target(uri, mode)
        if host:
            endpoints.setdefault((host, port), []).append(uri)
    logger.info("Probe input=%d endpoints=%d concurrency=%d", len(lines), len(endpoints), CONCURRENCY_LIMIT)
    # Bound tasks as well as sockets, even with very large subscriptions.
    items = iter(endpoints)
    results = []
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def worker():
        for host, port in items:
            _, _, latency = await tcp_ping("", host, port, semaphore)
            results.extend((uri, host, latency) for uri in endpoints[(host, port)])

    await asyncio.gather(*(worker() for _ in range(min(CONCURRENCY_LIMIT, len(endpoints)))))
    return results

def fetch_location_fallback(host):
    # HTTPS single-host fallback for networks that block/reset plain-HTTP ip-api.com
    try:
        req = urllib.request.Request(
            f"https://ipwho.is/{host}?fields=success,country",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('success'):
                return data.get('country', 'Unknown')
    except Exception as e:
        logger.debug("Location fallback failed error=%s", type(e).__name__)
    return "Unknown"

def fetch_locations(hosts):
    locations = {}
    unique_hosts = list(set(hosts))

    batches = [unique_hosts[i:i + 100] for i in range(0, len(unique_hosts), 100)]
    primary_failed_hosts = []

    for i, batch in enumerate(batches):
        try:
            payload = json.dumps([{"query": h} for h in batch]).encode('utf-8')
            req = urllib.request.Request("http://ip-api.com/batch?fields=query,country,status", data=payload)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))
                for item in data:
                    query = item.get('query')
                    if item.get('status') == 'success':
                        locations[query] = item.get('country', 'Unknown')
                    else:
                        locations[query] = 'Unknown'
                        primary_failed_hosts.append(query)
        except Exception as e:
            logger.warning("Location batch failed hosts=%d error=%s", len(batch), type(e).__name__)
            primary_failed_hosts.extend(batch)
        if i < len(batches) - 1:
            time.sleep(4)

    if primary_failed_hosts:
        logger.info("Location fallback hosts=%d", len(primary_failed_hosts))
        for host in primary_failed_hosts:
            locations[host] = fetch_location_fallback(host)

    return locations

def safe_clipboard_copy(text):
    try:
        pyperclip.copy(text)
    except Exception as e:
        logger.debug("Clipboard unavailable error=%s", type(e).__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Config/proxy latency tester")
    parser.add_argument("--mode", choices=["1", "2"], help="1=Configs, 2=MTProto")
    parser.add_argument("--source", choices=["1", "2", "3"], help="1=File, 2=Clipboard, 3=Repo")
    parser.add_argument("--input", default="", help="Path or URL (used with --source 1 or 3)")
    parser.add_argument("--locations", action="store_true", help="Look up countries (optional network calls)")
    parser.add_argument("--export", default="", help="Number of results to export, or 'all'")
    return parser.parse_args()

async def main():
    args = parse_args()
    headless = args.mode is not None and args.source is not None

    mode = args.mode if args.mode else input("Select mode: 1 for Configs, 2 for MTProto: ").strip()
    if mode not in ["1", "2"]:
        print("Invalid mode.")
        return

    src = args.source if args.source else input("Select source: 1 for File, 2 for Clipboard, 3 for Repo: ").strip()
    if src not in ["1", "2", "3"]:
        print("Invalid source.")
        return

    url = CONFIG_URL if mode == "1" else PROXY_URL
    if headless:
        input_val = args.input.strip() if args.input else url
    else:
        input_val = input("Enter path/url (Press Enter for default Repo): ").strip() if src != "2" else url
        if src == "3" and not input_val:
            input_val = url

    started = time.perf_counter()
    logger.info("Fetching subscription mode=%s source=%s", mode, src)
    try:
        lines = fetch_data(src, input_val)
    except Exception as e:
        logger.error("Source fetch failed error=%s; previous output preserved", type(e).__name__)
        return 1

    if not lines:
        logger.warning("Subscription empty; previous output preserved")
        return 1

    logger.info("Subscription loaded items=%d timeout_seconds=%.1f", len(lines), TIMEOUT_SECONDS)

    limit = 300 if mode == "1" else 200
    results = await test_targets(lines, mode)
    if not results:
        logger.warning("No supported config/proxy URIs; previous output preserved")
        return 1

    valid_configs = []

    for uri, host, latency in results:
        if latency is not None and latency < limit:
            valid_configs.append({"uri": uri, "host": host, "ping": latency})

    valid_count = len(valid_configs)
    valid_configs.sort(key=lambda item: item["ping"])

    if valid_count > 0 and (headless or valid_count > 100):
        logger.info("TCP candidates selected=%d", valid_count)
        if headless:
            export_arg = args.export.strip()
            if export_arg.isdigit():
                export_limit = int(export_arg)
                if 1 <= export_limit <= valid_count:
                    valid_configs = valid_configs[:export_limit]
                else:
                    logger.warning("--export out of bounds. Exporting all.")
            else:
                logger.info("Exporting all selected candidates")
        else:
            user_input = input(f"How many do you want to export? (Enter a number up to {valid_count}, or press Enter for all): ").strip()
            if user_input.isdigit():
                export_limit = int(user_input)
                if 1 <= export_limit <= valid_count:
                    valid_configs = valid_configs[:export_limit]
                else:
                    print("Out of bounds. Exporting all.")
            else:
                print("Invalid input or empty. Exporting all.")

    if not valid_configs:
        logger.warning("No endpoints met latency threshold_ms=%d; previous output preserved", limit)
        return 1

    hosts_to_resolve = [item["host"] for item in valid_configs]

    locations = await asyncio.to_thread(fetch_locations, hosts_to_resolve) if args.locations else {}

    table_data = []
    output_uris = []

    for item in valid_configs:
        loc = locations.get(item["host"], "Unknown")
        table_data.append([item["host"], round(item["ping"], 2), loc])
        output_uris.append(item["uri"])

    folder = "config" if mode == "1" else "proxy"

    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/{datetime.now(TEHRAN_TZ).strftime('%Y-%m-%d')}_{folder}.txt"
    readme_filename = f"{folder}/README.md"
    output_text = "\n".join(output_uris) + "\n"
    # Replace each file atomically; never remove a directory before saving results.
    atomic_write(filename, output_text)
    markdown_table = tabulate(table_data, headers=["Host", "TCP latency (ms)", "Location"], tablefmt="github")
    atomic_write(readme_filename, f"# TCP Benchmark - {datetime.now(TEHRAN_TZ).isoformat(timespec='seconds')}\n\nTCP reachability only; protocol authentication is not verified.\n\n{markdown_table}\n")
    if not headless:
        safe_clipboard_copy(output_text)
        print(markdown_table)
    logger.info("Probe completed tested=%d selected=%d elapsed_seconds=%.2f output=%s",
                len(results), len(output_uris), time.perf_counter() - started, filename)
    return 0


def atomic_write(filename, text):
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=Path(filename).parent, delete=False) as f:
            temp_path = f.name
            f.write(text)
        os.replace(temp_path, filename)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


if __name__ == "__main__":
    from scripts.logging_utils import configure_logging
    configure_logging()
    try:
        sys.exit(asyncio.run(main()))
    except (OSError, ValueError):
        logger.error("Cannot process input or save output")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(130)