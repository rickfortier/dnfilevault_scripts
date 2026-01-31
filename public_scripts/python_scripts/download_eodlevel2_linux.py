#!/usr/bin/env python3
"""
# Linux + Python: Download 'eodLevel2' Group Files
# Scheduled: Monday through Friday @ 18:00

This script downloads files from the 'eodLevel2' group on DNFileVault.
It is designed to be run automatically via a cron job.

## Prerequisites

1.  **Python 3.9+**
2.  **requests** library:
    `pip3 install requests`

## Configuration (Environment Variables)

The script expects these environment variables. You can set them in your user profile
(.bashrc / .profile) or inline in the cron job.

- `DNFV_EMAIL`: Your login email.
- `DNFV_PASSWORD`: Your login password.
- `DNFV_OUT_DIR`: (Optional) Where to save files. Defaults to `~/dnfilevault-downloads/eodLevel2`.
- `DNFV_BASE_URL`: (Optional) API URL. Defaults to `https://api.dnfilevault.com`.

## Setup Cron Job (Mon-Fri @ 18:00)

1.  Open your crontab:
    `crontab -e`

2.  Add the following line (adjust paths and credentials as needed):

    # Run Mon-Fri at 18:00 (6 PM)
    0 18 * * 1-5 export DNFV_EMAIL="me@example.com" export DNFV_PASSWORD="my_password" && /usr/bin/python3 /path/to/download_eodlevel2_linux.py >> /tmp/dnfv_download.log 2>&1

    *Note: Ensure you use the full path to python3 and the script.*

================================================================================
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Try to import requests
try:
    import requests
except ImportError:
    print("ERROR: 'requests' library missing. Install with: pip3 install requests")
    sys.exit(1)


def safe_name(name: str) -> str:
    """Sanitize filename to prevent directory traversal or invalid chars."""
    return re.sub(r'[<>:"/\\|?*]', "_", (name or "")).strip() or "file"


def download_stream(session: requests.Session, url: str, out_path: Path) -> None:
    """Downloads a file if it doesn't already exist."""
    if out_path.exists():
        # Optional: Check file size or checksum here if you wanted to be more robust
        print(f"  [Skip] Exists: {out_path.name}")
        return

    print(f"  [Download] {out_path.name} ...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    try:
        with session.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        tmp_path.replace(out_path)
    except Exception as e:
        print(f"  [Error] Failed to download {out_path.name}: {e}")
        if tmp_path.exists():
            os.remove(tmp_path)


def main() -> int:
    # 1. Configuration
    base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
    email = os.environ.get("DNFV_EMAIL")
    password = os.environ.get("DNFV_PASSWORD")
    
    # Defaults specific to this request
    target_group_name = "eodlevel2"
    default_out = str(Path.home() / "dnfilevault-downloads" / "eodLevel2")
    out_dir = Path(os.environ.get("DNFV_OUT_DIR", default_out))

    if not email or not password:
        print("Error: DNFV_EMAIL and DNFV_PASSWORD must be set.", file=sys.stderr)
        return 1

    print(f"--- Starting Download [{datetime.now()}] ---")
    print(f"Target Group: {target_group_name}")
    print(f"Output Dir: {out_dir}")

    session = requests.Session()
    # Custom User-Agent as requested to avoid throttling
    session.headers.update({"User-Agent": "DNFileVaultEodLevel2Downloader/1.0"})

    # 2. Login
    try:
        print("Logging in...")
        login_resp = session.post(
            f"{base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30
        )
        login_resp.raise_for_status()
        token = login_resp.json()["token"]
        session.headers.update({"Authorization": f"Bearer {token}"})
    except Exception as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 1

    # 3. Find 'eodLevel2' Group
    try:
        print("Fetching groups...")
        groups_resp = session.get(f"{base_url}/groups", timeout=30)
        groups_resp.raise_for_status()
        groups = groups_resp.json().get("groups", [])
    except Exception as e:
        print(f"Failed to list groups: {e}", file=sys.stderr)
        return 1

    # Filter for just eodLevel2 (case-insensitive)
    target_group = next(
        (g for g in groups if str(g.get("name", "")).lower() == target_group_name.lower()), 
        None
    )

    if not target_group:
        print(f"Warning: Group '{target_group_name}' not found in your account.")
        print(f"Available groups: {', '.join(g.get('name','') for g in groups)}")
        return 0

    gid = target_group.get("id")
    gname = target_group.get("name")
    print(f"Found Group: {gname} (ID: {gid})")

    # 4. List Files
    try:
        files_resp = session.get(f"{base_url}/groups/{gid}/files", timeout=30)
        files_resp.raise_for_status()
        files = files_resp.json().get("files", [])
    except Exception as e:
        print(f"Failed to list files: {e}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} files.")

    # 5. Download Files
    # Note: No date filtering requested, downloading all keys if missing locally.
    out_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        uuid_filename = f.get("uuid_filename")
        if not uuid_filename:
            continue
        
        display_name = safe_name(f.get("display_name") or uuid_filename)
        download_url = f"{base_url}/download/{uuid_filename}"
        target_path = out_dir / display_name
        
        download_stream(session, download_url, target_path)

    print("--- Done ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
