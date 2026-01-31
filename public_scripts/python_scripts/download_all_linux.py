"""
DNFileVault All-in-One Downloader (Linux/Mac/Windows)

This script downloads:
1. All files from your 'Purchases'
2. All files from your 'Groups' (optional: filter specific groups)

It works on Linux, Mac, and Windows.

## Usage (Linux / Mac)

1. Set your environment variables:

    export DNFV_EMAIL="you@example.com"
    export DNFV_PASSWORD="your_password"

    # Optional:
    export DNFV_OUT_DIR="$HOME/dnfilevault-downloads"
    export DNFV_GROUPS="eodLevel2,eodLevel3"   # Only download these groups
    export DNFV_DAYS="7"                        # Only download new files from last 7 days

2. Run the script:

    python3 download_all_linux.py

## Troubleshooting Timeouts
DNFileVault has anti-scanner protection. If requests look "bot-like" 
(e.g., default python-requests/curl User-Agent), the API will 
intentionally slow down responses (throttling). 
We fix this by setting a custom User-Agent and using longer timeouts.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*]', "_", (name or "")).strip() or "file"


def parse_created_at_utc(value: str):
    # DB timestamps look like "YYYY-MM-DD HH:MM:SS" (no tz). Treat as UTC for filtering.
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def download_with_fallback(session: requests.Session, file_info: dict, out_path: Path) -> None:
    if out_path.exists():
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    
    display_name = file_info.get("display_name") or "file"
    uuid_filename = file_info.get("uuid_filename")
    cloud_url = file_info.get("cloud_share_link")
    
    # 1. PRIMARY: Try Cloudflare R2 (No auth needed, fastest)
    if cloud_url:
        print(f"Downloading {display_name} via R2 CDN...")
        try:
            with session.get(cloud_url, stream=True, timeout=300, headers={"Authorization": None}) as r:
                if r.status_code == 200:
                    stream_to_file(r, tmp)
                    tmp.replace(out_path)
                    print(f"  ✓ DONE (R2)")
                    return
                else:
                    print(f"  R2 failed (HTTP {r.status_code}), falling back...")
        except Exception as e:
            print(f"  R2 error: {e}, falling back...")

    # 2. FALLBACK: API Server
    if not uuid_filename:
        print(f"  Error: No download link for {display_name}")
        return

    base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
    api_url = f"{base_url}/download/{uuid_filename}"
    print(f"Downloading {display_name} via API Server...")
    try:
        with session.get(api_url, stream=True, timeout=300) as r:
            r.raise_for_status()
            stream_to_file(r, tmp)
        tmp.replace(out_path)
        print(f"  ✓ DONE (API)")
    except Exception as e:
        print(f"  Error downloading {display_name}: {e}")
        if tmp.exists():
            os.remove(tmp)


def stream_to_file(response: requests.Response, path: Path) -> None:
    with open(path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)


def main() -> int:
    base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
    email = os.environ.get("DNFV_EMAIL")
    password = os.environ.get("DNFV_PASSWORD")
    out_dir = Path(os.environ.get("DNFV_OUT_DIR", str(Path.home() / "dnfilevault-downloads")))

    groups_filter_raw = os.environ.get("DNFV_GROUPS", "").strip()
    groups_filter = {g.strip().lower() for g in groups_filter_raw.split(",") if g.strip()} if groups_filter_raw else None

    days_raw = os.environ.get("DNFV_DAYS", "").strip()
    days = int(days_raw) if days_raw else None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)) if days is not None else None

    if not email or not password:
        print("Error: Missing credentials.")
        print("Please set DNFV_EMAIL and DNFV_PASSWORD in your environment.")
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": "DNFileVaultClient/1.0 (+support@deltaneutral.com)"})

    print("Logging in...")
    # Login
    try:
        login = session.post(f"{base_url}/auth/login", json={"email": email, "password": password}, timeout=60)
        login.raise_for_status()
        token = login.json()["token"]
        session.headers.update({"Authorization": f"Bearer {token}"})
    except requests.exceptions.ConnectionError:
        print("Login failed: ERROR - No internet connection or DNS failure. (Could not reach api.dnfilevault.com)")
        return 1
    except requests.exceptions.Timeout:
        print("Login failed: ERROR - The request timed out. Your connection might be slow or the server is busy.")
        return 1
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("Login failed: ERROR - Incorrect email or password. Check your DNFV_EMAIL and DNFV_PASSWORD.")
        else:
            print(f"Login failed: ERROR - Server returned status {e.response.status_code}")
        return 1
    except Exception as e:
        print(f"Login failed: ERROR - An unexpected network problem occurred: {e}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out_dir}")

    # Purchases
    print("Checking purchases...")
    try:
        purchases = session.get(f"{base_url}/purchases", timeout=60).json().get("purchases", [])
    except Exception as e:
        print(f"Failed to list purchases: {e}")
        purchases = []

    for p in purchases:
        pdir = out_dir / "purchases" / safe_name(f"{p['id']} - {p.get('product_name','')}")
        pdir.mkdir(parents=True, exist_ok=True)
        try:
            files = session.get(f"{base_url}/purchases/{p['id']}/files", timeout=60).json().get("files", [])
        except Exception as e:
            print(f"Failed to list files for purchase {p.get('id')}: {e}")
            continue

        for f in files:
            if cutoff is not None and f.get("created_at"):
                try:
                    if parse_created_at_utc(str(f["created_at"])) < cutoff:
                        continue
                except Exception:
                    pass
            out_path = pdir / safe_name(f.get("display_name") or f["uuid_filename"])
            download_with_fallback(session, f, out_path)

    # Groups
    print("Checking groups...")
    try:
        groups = session.get(f"{base_url}/groups", timeout=60).json().get("groups", [])
    except Exception as e:
        print(f"Failed to list groups: {e}")
        groups = []

    if groups_filter is not None:
        groups = [g for g in groups if str(g.get("name","")).lower() in groups_filter]

    for g in groups:
        gid = g.get("id")
        if gid is None:
            continue
        gdir = out_dir / "groups" / safe_name(f"{gid} - {g.get('name','')}")
        gdir.mkdir(parents=True, exist_ok=True)
        
        try:
            files = session.get(f"{base_url}/groups/{gid}/files", timeout=60).json().get("files", [])
        except Exception as e:
            print(f"Failed to list files for group {gid}: {e}")
            continue

        for f in files:
            if cutoff is not None and f.get("created_at"):
                try:
                    if parse_created_at_utc(str(f["created_at"])) < cutoff:
                        continue
                except Exception:
                    pass
            out_path = gdir / safe_name(f.get("display_name") or f["uuid_filename"])
            download_with_fallback(session, f, out_path)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
