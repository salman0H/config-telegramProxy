import asyncio
import base64
import json
import os
import re
import time
import urllib.request
from datetime import datetime

import pyperclip
from tabulate import tabulate

CONFIG_URL = "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_base64_Sub.txt"
PROXY_URL = "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"
TIMEOUT_SECONDS = 3.0
CONCURRENCY_LIMIT = 500

def fetch_data(source_type, input_val):
    raw_data = ""
    if source_type == "1":
        with open(input_val, "r", encoding="utf-8") as f:
            raw_data = f.read()
    elif source_type == "2":
        raw_data = pyperclip.paste()
    elif source_type == "3":
        req = urllib.request.Request(input_val, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            raw_data = response.read().decode('utf-8')

    try:
        if not any(proto in raw_data[:50] for proto in ["vless://", "trojan://", "vmess://", "https://"]):
            decoded_data = base64.b64decode(raw_data).decode('utf-8')
            return [line.strip() for line in decoded_data.splitlines() if line.strip()]
    except Exception:
        pass

    return [line.strip() for line in raw_data.splitlines() if line.strip()]

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

def fetch_locations(hosts):
    locations = {}
    unique_hosts = list(set(hosts))
    
    batches = [unique_hosts[i:i + 100] for i in range(0, len(unique_hosts), 100)]
    
    for batch in batches:
        try:
            payload = json.dumps([{"query": h} for h in batch]).encode('utf-8')
            req = urllib.request.Request("http://ip-api.com/batch?fields=query,country", data=payload)
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                for item in data:
                    locations[item.get('query')] = item.get('country', 'Unknown')
        except Exception:
            for h in batch:
                locations[h] = "Unknown"
    return locations

async def main():
    mode = input("Select mode: 1 for Configs, 2 for MTProto: ").strip()
    if mode not in ["1", "2"]:
        print("Invalid mode.")
        return

    src = input("Select source: 1 for File, 2 for Clipboard, 3 for Repo: ").strip()
    if src not in ["1", "2", "3"]:
        print("Invalid source.")
        return

    url = CONFIG_URL if mode == "1" else PROXY_URL
    input_val = input("Enter path/url (Press Enter for default Repo): ").strip() if src != "2" else url
    if src == "3" and not input_val:
        input_val = url

    print("Fetching data...")
    lines = fetch_data(src, input_val)
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

    results = await asyncio.gather(*tasks)
    
    valid_configs = []
    
    for uri, host, latency in results:
        if latency is not None and latency < limit:
            valid_configs.append({"uri": uri, "host": host, "ping": latency})

    valid_count = len(valid_configs)
    
    if valid_count > 100:
        print(f"\nFound {valid_count} working configurations.")
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

    hosts_to_resolve = []
    for item in valid_configs:
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", item["host"]):
            hosts_to_resolve.append(item["host"])

    print("\nResolving IP locations...")
    locations = fetch_locations(hosts_to_resolve)

    table_data = []
    output_uris = []
    
    for item in valid_configs:
        loc = locations.get(item["host"], item["host"])
        table_data.append([item["uri"][:30] + "...", round(item["ping"], 2), loc])
        output_uris.append(item["uri"])

    folder = "config" if mode == "1" else "proxy"
    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/{datetime.now().strftime('%Y-%m-%d')}_{folder}.txt"
    
    output_text = "\n".join(output_uris)
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(output_text)
    pyperclip.copy(output_text)
    
    print(f"\nSaved {len(output_uris)} working configs to {filename} and copied to clipboard.")
    print(tabulate(table_data, headers=["Config/Proxy (Truncated)", "Ping (ms)", "Location"], tablefmt="grid"))

if __name__ == "__main__":
    asyncio.run(main())