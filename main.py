import argparse
import asyncio
import base64
import json
import os
import re
import shutil
import time
import urllib.request
import urllib.error
from datetime import datetime

import pyperclip
from tabulate import tabulate

CONFIG_URL = "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt"
PROXY_URL = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"
TIMEOUT_SECONDS = 3.0
CONCURRENCY_LIMIT = 500
HTTP_TIMEOUT = 15
HTTP_RETRIES = 3
HTTP_RETRY_DELAY = 2

def fetch_url(url):
    last_error = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                return response.read().decode('utf-8')
        except (urllib.error.URLError, ConnectionResetError, TimeoutError) as e:
            last_error = e
            if attempt < HTTP_RETRIES:
                time.sleep(HTTP_RETRY_DELAY)
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

    try:
        if not any(proto in raw_data[:50] for proto in ["vless://", "trojan://", "vmess://", "https://"]):
            decoded_data = base64.b64decode(raw_data).decode('utf-8')
            return [line.strip() for line in decoded_data.splitlines() if line.strip()]
    except Exception:
        pass

    return [line.strip() for line in raw_data.splitlines() if line.strip()]

import urllib.parse

CUSTOM_LABEL = "@sentencedIntoMusic"

def apply_custom_label(uri, label=CUSTOM_LABEL):
    """Rename config's display tag. vmess stores it in base64 JSON ('ps');
    vless/trojan/ss store it after '#'. MTProto t.me/proxy links have no
    name field, so this is only meaningful for mode 1 (Configs)."""
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
    return f"{base}#{urllib.parse.quote(label, safe='')}"

def extract_target(uri, mode):
    if mode == "1":
        match = re.search(r'@([^/:\?]+):(\d+)', uri)
        if match:
            return match.group(1), int(match.group(2))
    elif mode == "2":
        match = re.search(r'server=([^&]+)&port=(\d+)', uri)
        if match:
            return match.group(1), int(match.group(2))
    return None, None

async def tcp_ping(uri, host, port, semaphore):
    async with semaphore:
        start_time = time.time()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=TIMEOUT_SECONDS
            )
            writer.close()
            await writer.wait_closed()
            latency = (time.time() - start_time) * 1000
            return uri, host, latency
        except Exception:
            return uri, host, None

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
        print(f"  [location] fallback lookup failed for {host}: {e}")
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
            print(f"  [location] ip-api.com batch failed ({e}); will retry these {len(batch)} hosts via HTTPS fallback")
            primary_failed_hosts.extend(batch)
        if i < len(batches) - 1:
            time.sleep(4)

    if primary_failed_hosts:
        print(f"  [location] resolving {len(primary_failed_hosts)} hosts via HTTPS fallback (ipwho.is)...")
        for host in primary_failed_hosts:
            locations[host] = fetch_location_fallback(host)

    return locations

def safe_clipboard_copy(text):
    try:
        pyperclip.copy(text)
    except Exception as e:
        print(f"[clipboard] skipped (no clipboard available in this environment): {e}")

def parse_args():
    parser = argparse.ArgumentParser(description="Config/proxy latency tester")
    parser.add_argument("--mode", choices=["1", "2"], help="1=Configs, 2=MTProto")
    parser.add_argument("--source", choices=["1", "2", "3"], help="1=File, 2=Clipboard, 3=Repo")
    parser.add_argument("--input", default="", help="Path or URL (used with --source 1 or 3)")
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

    print("Fetching data...")
    try:
        lines = fetch_data(src, input_val)
    except Exception as e:
        print(f"Failed to fetch data: {e}")
        return

    if not lines:
        print("No valid configurations found.")
        return

    print(f"Loaded {len(lines)} items. Testing configurations (Timeout: {TIMEOUT_SECONDS}s)...")

    limit = 300 if mode == "1" else 200
    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
    tasks = []

    for uri in lines:
        host, port = extract_target(uri, mode)
        if host and port:
            tasks.append(tcp_ping(uri, host, port, semaphore))

    if not tasks:
        print("No parsable config/proxy URIs found in source data.")
        return

    results = await asyncio.gather(*tasks)

    valid_configs = []

    for uri, host, latency in results:
        if latency is not None and latency < limit:
            valid_configs.append({"uri": uri, "host": host, "ping": latency})

    valid_count = len(valid_configs)
    valid_configs.sort(key=lambda item: item["ping"])

    if valid_count > 100:
        print(f"\nFound {valid_count} working configurations.")
        if headless:
            export_arg = args.export.strip()
            if export_arg.isdigit():
                export_limit = int(export_arg)
                if 1 <= export_limit <= valid_count:
                    valid_configs = valid_configs[:export_limit]
                else:
                    print("--export out of bounds. Exporting all.")
            else:
                print("Exporting all (headless mode, no --export limit given).")
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
        print("No configurations met the latency criteria.")
        return

    hosts_to_resolve = [item["host"] for item in valid_configs]

    print("\nResolving IP locations...")
    locations = fetch_locations(hosts_to_resolve)

    table_data = []
    output_uris = []

    for item in valid_configs:
        loc = locations.get(item["host"], item["host"])
        table_data.append([item["uri"][:30] + "...", round(item["ping"], 2), loc])
        uri = apply_custom_label(item["uri"]) if mode == "1" else item["uri"]
        output_uris.append(uri)

    folder = "config" if mode == "1" else "proxy"

    # Empty directory prior to saving
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder, exist_ok=True)

    filename = f"{folder}/{datetime.now().strftime('%Y-%m-%d')}_{folder}.txt"
    readme_filename = f"{folder}/README.md"

    output_text = "\n".join(output_uris)

    # Save text output
    with open(filename, "w", encoding="utf-8") as f:
        f.write(output_text)
    safe_clipboard_copy(output_text)

    # Save README.md table output
    markdown_table = tabulate(table_data, headers=["Config/Proxy (Truncated)", "Ping (ms)", "Location"], tablefmt="github")
    with open(readme_filename, "w", encoding="utf-8") as f:
        f.write(f"# Benchmark Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{markdown_table}\n")

    print(f"\nSaved {len(output_uris)} working configs to {filename}, updated {readme_filename}, and copied to clipboard.")
    print(tabulate(table_data, headers=["Config/Proxy (Truncated)", "Ping (ms)", "Location"], tablefmt="grid"))

if __name__ == "__main__":
    asyncio.run(main())