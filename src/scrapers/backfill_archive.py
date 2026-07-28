import requests
import json
import os
import yaml
import time
from datetime import datetime

# Load Config for Project Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"

def fetch_wayback_snapshots(url, start_date='20240101', end_date=None):
    """Query CDX API for snapshots."""
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")
        
    params = {
        'url': url,
        'from': start_date,
        'to': end_date,
        'output': 'json',
        'fl': 'timestamp,original',
        'collapse': 'digest', # Filter duplicates
        'filter': 'statuscode:200'
    }
    
    queries_to_try = [
        url,
        url.replace("https://", "").replace("http://", ""),
        url + "*"
    ]
    
    for q in queries_to_try:
        print(f"Querying Wayback CDX for {q}...")
        params['url'] = q
        try:
            response = requests.get(WAYBACK_CDX_API, params=params)
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 1: # Header + at least one result
                    print(f"Found {len(data)-1} snapshots with query: {q}")
                    return data[1:]
        except Exception as e:
            print(f"CDX Error for {q}: {e}")
            
    return []

def download_snapshot(original_url, timestamp, source_name):
    """Downloads a specific snapshot."""
    archive_url = f"https://web.archive.org/web/{timestamp}/{original_url}"
    
    # Path: data/bronze/{source}/YYYY-MM-DD/
    # Parse timestamp: YYYYMMDDHHMMSS
    try:
        dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
    except:
        dt = datetime.now()
        
    date_str = dt.strftime("%Y-%m-%d")
    save_dir = os.path.join(CONFIG['storage']['bronze_path'], source_name, date_str)
    os.makedirs(save_dir, exist_ok=True)
    
    # Filename with embedded unix timestamp to help parser
    unix_ts = int(dt.timestamp())
    filename = f"daily_schedule_{unix_ts}.html"
    filepath = os.path.join(save_dir, filename)
    
    if os.path.exists(filepath):
        print(f"Skipping existing: {date_str}")
        return

    print(f"Downloading snapshot {timestamp} -> {filepath}...")
    try:
        # User Agent is important for Archive.org sometimes
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'} 
        resp = requests.get(archive_url, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            with open(filepath, "w", encoding='utf-8') as f:
                f.write(resp.text)
            time.sleep(1.0) # Polite delay
        else:
            print(f"Failed: {resp.status_code}")
    except Exception as e:
        print(f"Download Error: {e}")

def run_backfill(source_key="webtoon_global", limit=24, override_url=None):
    """
    Main Orchestrator. 
    limit: Max snapshots to download (e.g., 12 = 1 per month for a year)
    """
    target = CONFIG['scraping']['targets'].get(source_key)
    if not target:
        print(f"Target {source_key} not found in config.")
        return

    url = override_url if override_url else target['daily_schedule_url']
    snapshots = fetch_wayback_snapshots(url)
    print(f"Found {len(snapshots)} total snapshots.")
    
    # Sampling: Prefer mid-month snapshots (e.g., 15th) to reduce volume
    # Or just take one every N
    step = max(1, len(snapshots) // limit) if limit else 1
    selected = snapshots[::step]
    
    print(f"Downloading {len(selected)} selected snapshots...")
    for item in selected:
        ts = item[0]
        download_snapshot(url, ts, source_key)

if __name__ == "__main__":
    # Force Homepage Backfill for robustness
    run_backfill("webtoon_global", limit=5, override_url="https://www.webtoons.com/en")
