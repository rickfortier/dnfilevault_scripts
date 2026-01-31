#!/usr/bin/env python3
"""
# Linux/Mac + Python: Download All Purchases (Daily)

This script downloads files from ALL your DNFileVault groups to your local machine.
It is configured to download only files created in the last 24 hours (Daily check).

## Prerequisites

1.  **Python 3.9+** installed.
2.  **requests** library installed.
    - Install via terminal: `python3 -m pip install requests`

## Configuration (Environment Variables)

You must set the following environment variables before running the script.
You can set them in your terminal session like this:

    export DNFV_EMAIL="you@example.com"
    export DNFV_PASSWORD="your_password_here"
    
    # Optional settings:
    export DNFV_BASE_URL="https://api.dnfilevault.com"  # Defaults to this if not set
    export DNFV_OUT_DIR="$HOME/dnfilevault-downloads/daily" # Defaults to this folder
    # DNFV_DAYS defaults to 1 (Daily) in this script, but can be overridden.
    
## How to Run (Daily via Cron)

To run this daily, you can add it to your crontab:

    0 6 * * * /usr/bin/python3 /path/to/download_daily_purchases.py

"""

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Try to import requests; give a helpful error if missing.
try:
    import requests
except ImportError:
    print("ERROR: The 'requests' library is not installed.")
    print("Please run: python3 -m pip install requests")
    sys.exit(1)


def safe_name(name: str) -> str:
    """
    Sanitize a string to be safe for use as a filename.
    
    """
    return re.sub(r'[<>:"/\\|?*]', "_", (name or "")).strip() or "file"


def parse_created_at(value: str):
    """
    Parses timestamps from the API.
    DNFileVault stores timestamps like: 'YYYY-MM-DD HH:MM:SS' (no timezone in DB).
    We treat it as UTC for filtering purposes.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        # Fallback if format changes
        return None


def download_stream(session: requests.Session, url: str, out_path: Path) -> None:
    """
    Downloads a file from 'url' to 'out_path' in chunks.
    Skips download if the file already exists.
    """
    if out_path.exists():
        print(f"    [Skip] File already exists: {out_path.name}")
        return

    # Create directory if it doesn't exist
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Download to a temporary .part file first
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    print(f"    [Downloading] {out_path.name} ...")
    try:
        with session.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024): # 1MB chunks
                    if chunk:
                        f.write(chunk)
        
        # Rename .part file to actual filename on success
        tmp_path.replace(out_path)
        print(f"    [Success] Saved to: {out_path}")
        
    except Exception as e:
        print(f"    [Error] Failed to download {out_path.name}: {e}")
        if tmp_path.exists():
            os.remove(tmp_path)


def main() -> int:
    print("--- Starting DNFileVault Daily Downloader ---")
    print(f"Time: {datetime.now().isoformat()}")

    # 1. Load Configuration
    base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
    email = os.environ.get("DNFV_EMAIL")
    password = os.environ.get("DNFV_PASSWORD")
    
    # Default output dir: ~/dnfilevault-downloads/daily
    default_out = str(Path.home() / "dnfilevault-downloads" / "daily")
    out_dir_str = os.environ.get("DNFV_OUT_DIR", default_out)
    out_dir = Path(out_dir_str)

    # Filter: All Groups (No DNFV_GROUPS check or filtering logic implemented here intentionally to match 'All purchases')
    
    # Filter: Daily (Last 1 day)
    # Allow override, but default to 1
    days_raw = os.environ.get("DNFV_DAYS", "5").strip()
    try:
        days = int(days_raw)
    except ValueError:
        days = 1 # Fallback default
        
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"Date filter: Downloading files from the last {days} day(s).")
    print(f"Cutoff (UTC): {cutoff.strftime('%Y-%m-%d %H:%M:%S')}")

    # 2. Validate Credentials
    if not email or not password:
        print("\nCRITICAL ERROR: Credentials missing.")
        print("Please set DNFV_EMAIL and DNFV_PASSWORD environment variables.")
        print("Example: export DNFV_EMAIL='me@test.com'")
        return 1

    print(f"\nTarget Output Directory: {out_dir}")
    print(f"User: {email}")

    # 3. Setup Session
    session = requests.Session()
    session.headers.update({
        "User-Agent": "DNFileVaultDailyDownloader/1.0",
    })

    # 4. Login
    print("\nStep 1: Logging in...")
    try:
        login_resp = session.post(
            f"{base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        login_resp.raise_for_status()
        token = login_resp.json()["token"]
        # Add token to headers for future requests
        session.headers.update({"Authorization": f"Bearer {token}"})
        print("Login successful.")
    except Exception as e:
        print(f"Login Failed: {e}")
        return 1

    # 5. List Groups
    print("\nStep 2: Fetching list of all groups...")
    try:
        groups_resp = session.get(f"{base_url}/groups", timeout=30)
        groups_resp.raise_for_status()
        all_groups = groups_resp.json().get("groups", [])
    except Exception as e:
        print(f"Failed to list groups: {e}")
        return 1

    if not all_groups:
        print("No groups found for this user.")
        return 0

    print(f"Found {len(all_groups)} groups.")

    # 6. Create Output Directory
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating output directory '{out_dir}': {e}")
        return 1

    # 7. Process Each Group
    files_downloaded_count = 0
    
    for i, g in enumerate(all_groups, 1):
        gid = g.get("id")
        gname = str(g.get("name") or gid)
        
        # print(f"Checking Group [{i}/{len(all_groups)}]: {gname}")
        
        if gid is None:
            continue

        # Prepare group folder
        group_dir = out_dir / safe_name(gname)
        # We don't create the folder yet, only if we find files to download, 
        # OR we can create it anyway. Let's create it only if needed to avoid empty folders?
        # script 'download_groups_linux.py' created it always. Let's stick to creating it if we are checking.
        # Actually, let's keep it clean: check files first.

        # List files in group
        try:
            files_resp = session.get(f"{base_url}/groups/{gid}/files", timeout=30)
            files_resp.raise_for_status()
            files = files_resp.json().get("files", [])
        except Exception as e:
            print(f"Error listing files for group '{gname}': {e}")
            continue

        # Filter files by date
        files_to_download = []
        for f in files:
            print(f)
            ca_str = f.get("created_at")
            if not ca_str:
                continue
            ca_date = parse_created_at(str(ca_str))
            if ca_date and ca_date >= cutoff:
                files_to_download.append(f)

        if not files_to_download:
            continue

        print(f"\nGroup: {gname} - Found {len(files_to_download)} new file(s).")
        group_dir.mkdir(parents=True, exist_ok=True)

        # Download files
        for f in files_to_download:
            uuid_filename = f.get("uuid_filename")
            if not uuid_filename:
                continue
            
            display_name = safe_name(f.get("display_name") or uuid_filename)
            download_url = f"{base_url}/download/{uuid_filename}"
            target_path = group_dir / display_name
            
            download_stream(session, download_url, target_path)
            files_downloaded_count += 1

    print(f"\n--- All Done. Downloaded {files_downloaded_count} new files. ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
