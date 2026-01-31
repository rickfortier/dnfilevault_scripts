"""
# Linux + Python: Download Group files (DNFileVault)

This script downloads files from your DNFileVault groups to your local machine.
It is designed for Linux users but should work on macOS/Windows too.

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
    export DNFV_OUT_DIR="$HOME/dnfilevault-downloads/groups" # Defaults to this folder
    export DNFV_GROUPS="eodLevel2,eodLevel3"  # Comma-separated list of groups to download. If omitted, downloads ALL.
    export DNFV_DAYS="7"  # Download only files created in the last 7 days. If omitted, downloads ALL.

## How to Run

1.  Open your terminal.
2.  Navigate to the folder containing this script.
3.  Set your environment variables (see above).
4.  Run the command:
    `python3 download_groups_linux.py`

## Troubleshooting

- If you see "ModuleNotFoundError: No module named 'requests'", run `pip install requests`.
- If you see "401 Client Error: Unauthorized", check your email and password.
- If you see "No groups found", check if you are assigned to any groups in the system.

================================================================================
"""

import os
import re
import sys
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
    Replaces characters like < > : " / \ | ? * with underscores.
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
    print("--- Starting DNFileVault Group Downloader ---")

    # 1. Load Configuration
    base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
    email = os.environ.get("DNFV_EMAIL")
    password = os.environ.get("DNFV_PASSWORD")
    
    # Default output dir: ~/dnfilevault-downloads/groups
    default_out = str(Path.home() / "dnfilevault-downloads" / "groups")
    out_dir_str = os.environ.get("DNFV_OUT_DIR", default_out)
    out_dir = Path(out_dir_str)

    # Parse Filters
    groups_filter_raw = os.environ.get("DNFV_GROUPS", "").strip()
    if groups_filter_raw:
        groups_filter = {g.strip().lower() for g in groups_filter_raw.split(",") if g.strip()}
        print(f"Filtering for groups: {groups_filter_raw}")
    else:
        groups_filter = None
        print("No group filter set (downloading ALL groups).")

    days_raw = os.environ.get("DNFV_DAYS", "").strip()
    cutoff = None
    if days_raw:
        try:
            days = int(days_raw)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            print(f"Date filter active: Downloading files from the last {days} days.")
            print(f"Cutoff date (UTC): {cutoff.strftime('%Y-%m-%d %H:%M:%S')}")
        except ValueError:
            print(f"Warning: Invalid DNFV_DAYS value '{days_raw}'. Ignoring date filter.")

    # 2. Validate Credentials
    if not email or not password:
        print("\nCRITICAL ERROR: Credentials missing.")
        print("Please set DNFV_EMAIL and DNFV_PASSWORD environment variables.")
        print("Example: export DNFV_EMAIL='me@test.com'")
        return 1

    print(f"\nTarget Output Directory: {out_dir}")
    print(f"API URL: {base_url}")
    print(f"User: {email}")

    # 3. Setup Session
    session = requests.Session()
    session.headers.update({
        "User-Agent": "DNFileVaultGroupDownloader/1.0",
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
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Login Failed: Incorrect email or password.")
        else:
            print(f"Login Failed: {e}")
        return 1
    except Exception as e:
        print(f"Login Error: {e}")
        return 1

    # 5. List Groups
    print("\nStep 2: Fetching list of groups...")
    try:
        groups_resp = session.get(f"{base_url}/groups", timeout=30)
        groups_resp.raise_for_status()
        all_groups = groups_resp.json().get("groups", [])
    except Exception as e:
        print(f"Failed to list groups: {e}")
        return 1

    # Filter groups
    groups_to_process = []
    if groups_filter:
        for g in all_groups:
            if str(g.get("name", "")).lower() in groups_filter:
                groups_to_process.append(g)
    else:
        groups_to_process = all_groups

    if not groups_to_process:
        print("No matching groups found to process.")
        return 0

    print(f"Found {len(groups_to_process)} groups to process.")

    # 6. Create Output Directory
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating output directory '{out_dir}': {e}")
        return 1

    # 7. Process Each Group
    for i, g in enumerate(groups_to_process, 1):
        gid = g.get("id")
        gname = str(g.get("name") or gid)
        
        print(f"\n--- Processing Group [{i}/{len(groups_to_process)}]: {gname} (ID: {gid}) ---")
        
        if gid is None:
            print("Skipping group with no ID.")
            continue

        # Prepare group folder
        group_dir = out_dir / safe_name(gname)
        group_dir.mkdir(parents=True, exist_ok=True)

        # List files in group
        try:
            files_resp = session.get(f"{base_url}/groups/{gid}/files", timeout=30)
            files_resp.raise_for_status()
            files = files_resp.json().get("files", [])
        except Exception as e:
            print(f"Error listing files for group '{gname}': {e}")
            continue

        print(f"Total files in group: {len(files)}")

        # Filter files by date (if configured)
        files_to_download = []
        if cutoff:
            for f in files:
                ca_str = f.get("created_at")
                if not ca_str:
                    continue
                ca_date = parse_created_at(str(ca_str))
                if ca_date and ca_date >= cutoff:
                    files_to_download.append(f)
            print(f"Files after date filtering: {len(files_to_download)}")
        else:
            files_to_download = files

        if not files_to_download:
            print("No files to download for this group.")
            continue

        # Download files
        for f in files_to_download:
            uuid_filename = f.get("uuid_filename")
            if not uuid_filename:
                continue
            
            # Construct display name and paths
            display_name = safe_name(f.get("display_name") or uuid_filename)
            download_url = f"{base_url}/download/{uuid_filename}"
            target_path = group_dir / display_name
            
            download_stream(session, download_url, target_path)

    print("\n--- All Done. Script Finished. ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
