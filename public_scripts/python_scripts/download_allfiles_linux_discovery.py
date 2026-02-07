#!/usr/bin/env python3
"""
DNFileVault Downloader for Linux
------------------------------------------------------------------
This script downloads ALL files from your DNFileVault account:
1. All Purchases
2. All Groups

It automatically discovers available API servers and fails over
to the next one if the primary is down.

Designed for Linux servers and cron jobs.

BEFORE YOU RUN THIS:
1. You need Python 3.6+ installed.
2. You need the 'requests' library:
       pip3 install requests

HOW TO CONFIGURE:
Set environment variables or edit the CONFIGURATION section below.

CRON EXAMPLE (daily at 6am):
    0 6 * * * /usr/bin/python3 /home/rick/dnfilevault_downloader_linux.py >> /var/log/dnfilevault.log 2>&1

ENVIRONMENT VARIABLES (recommended for cron):
    export DNFV_EMAIL="your_email@example.com"
    export DNFV_PASSWORD="your_password"
    export DNFV_OUT_DIR="/data/dnfilevault-downloads"
"""

import os
import re
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("ERROR: The 'requests' library is not installed.")
    print("Run: pip3 install requests")
    sys.exit(1)


# ==============================================================================
# CONFIGURATION
# ==============================================================================

EMAIL = os.environ.get("DNFV_EMAIL", "your_email@example.com")
PASSWORD = os.environ.get("DNFV_PASSWORD", "your_password")

# Default download location - override with DNFV_OUT_DIR env variable
OUTPUT_FOLDER = os.environ.get("DNFV_OUT_DIR", os.path.expanduser("~/dnfilevault-downloads"))

# Set to a number (e.g., 1) to only download the newest N files per group.
# Set to None to download EVERYTHING.
DAYS_TO_CHECK = None

# ==============================================================================


# API Discovery
DISCOVERY_URL = "https://config.dnfilevault.com/endpoints.json"

FALLBACK_ENDPOINTS = [
    "https://api.dnfilevault.com",
    "https://api-redmint.dnfilevault.com",
]

USER_AGENT = "DNFileVaultClient/1.0 (+support@deltaneutral.com)"


def log(msg):
    """Print with timestamp for cron/log readability."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def get_api_endpoints(session):
    """Fetch current API endpoint list from Cloudflare R2."""
    log("Discovering API endpoints...")
    try:
        r = session.get(DISCOVERY_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            endpoints = sorted(data.get("endpoints", []), key=lambda x: x.get("priority", 99))
            urls = [e["url"] for e in endpoints]
            log(f"  Found {len(urls)} endpoints (config v{data.get('version', '?')}, updated {data.get('updated', '?')})")
            for e in endpoints:
                log(f"    {e.get('priority', '?')}. {e['url']} ({e.get('label', '')})")
            return urls
        else:
            log(f"  Discovery returned status {r.status_code}, using fallback list.")
    except Exception as e:
        log(f"  Discovery unavailable ({e}), using fallback list.")
    
    log(f"  Using {len(FALLBACK_ENDPOINTS)} fallback endpoints.")
    return FALLBACK_ENDPOINTS


def find_working_api(session, endpoints):
    """Test each endpoint and return the first healthy one."""
    log("Finding a healthy API server...")
    for url in endpoints:
        try:
            r = session.get(f"{url}/health", timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "healthy":
                    log(f"  ✓ {url} - healthy")
                    return url
                else:
                    log(f"  ✗ {url} - responded but status: {data.get('status', 'unknown')}")
            else:
                log(f"  ✗ {url} - returned {r.status_code}")
        except requests.exceptions.Timeout:
            log(f"  ✗ {url} - timed out")
        except requests.exceptions.ConnectionError:
            log(f"  ✗ {url} - connection failed")
        except Exception as e:
            log(f"  ✗ {url} - error: {e}")
    
    return None


def sanitize_filename(name):
    """Clean up a filename for Linux filesystem."""
    if not name:
        return "unnamed_file"
    clean = re.sub(r'[<>:"/\\|?*]', "_", str(name))
    return clean.strip() or "unnamed_file"


def ensure_folder_exists(folder_path):
    """Create folder if it doesn't exist."""
    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
            log(f"Created folder: {folder_path}")
        except OSError as e:
            log(f"Error creating folder {folder_path}: {e}")


def login_to_api(session, base_url):
    """Login and return JWT token."""
    log(f"Logging in as {EMAIL}...")
    
    try:
        response = session.post(
            f"{base_url}/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=60
        )
        
        if response.status_code == 200:
            token = response.json().get("token")
            log("Login successful!")
            return token
        elif response.status_code == 401:
            log("Login failed: Incorrect email or password.")
        else:
            log(f"Login failed: Server returned {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        log(f"Login failed: Could not reach {base_url}")
    except requests.exceptions.Timeout:
        log("Login failed: Request timed out.")
    except requests.exceptions.RequestException as e:
        log(f"Login failed: {e}")
        
    return None


def download_file(session, token, file_info, save_directory, base_url):
    """Download a file via R2 (primary) or API server (fallback)."""
    uuid_filename = file_info.get("uuid_filename")
    cloud_url = file_info.get("cloud_share_link")
    display_name = file_info.get("display_name") or uuid_filename
    
    safe_name = sanitize_filename(display_name)
    full_save_path = os.path.join(save_directory, safe_name)
    
    # Skip if already downloaded
    if os.path.exists(full_save_path):
        return

    # Method 1: R2 Direct Link (PRIMARY)
    if cloud_url:
        log(f"  Downloading: {safe_name} via R2...")
        try:
            with requests.get(cloud_url, stream=True, timeout=30) as r:
                if r.status_code == 200:
                    save_content(r, full_save_path)
                    log(f"  ✓ Complete (R2)")
                    return
                else:
                    log(f"  R2 returned {r.status_code}, trying fallback...")
        except Exception as e:
            log(f"  R2 failed: {e}, trying fallback...")

    # Method 2: API Server (FALLBACK)
    if not uuid_filename:
        log(f"  ✗ No download ID for {safe_name}")
        return

    log(f"  Downloading: {safe_name} via API...")
    try:
        with session.get(f"{base_url}/download/{uuid_filename}", stream=True, timeout=300) as r:
            if r.status_code == 200:
                save_content(r, full_save_path)
                log(f"  ✓ Complete (API)")
            else:
                log(f"  ✗ Failed: {safe_name} - Status {r.status_code}")
    except Exception as e:
        log(f"  ✗ Error: {safe_name} - {e}")


def save_content(response, full_save_path):
    """Stream response to disk with progress."""
    temp_path = full_save_path + ".tmp"
    total_downloaded = 0
    start_time = time.time()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with open(temp_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)
                total_downloaded += len(chunk)
                
                elapsed = time.time() - start_time
                if elapsed > 0 and sys.stdout.isatty():
                    speed_mbps = (total_downloaded / (1024 * 1024)) / elapsed
                    if total_size > 0:
                        percent = (total_downloaded / total_size) * 100
                        sys.stdout.write(f"\r    Progress: {percent:6.1f}% | Speed: {speed_mbps:6.2f} MB/s")
                    else:
                        sys.stdout.write(f"\r    Downloaded: {total_downloaded / (1024*1024):7.1f} MB | Speed: {speed_mbps:6.2f} MB/s")
                    sys.stdout.flush()
    
    if sys.stdout.isatty():
        print("")
    
    if os.path.exists(full_save_path):
        os.remove(full_save_path)
    os.rename(temp_path, full_save_path)


def main():
    log("=" * 50)
    log("DNFileVault Downloader v2.0 (Linux)")
    log("=" * 50)
    log(f"Output: {OUTPUT_FOLDER}")
    
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    
    # Discover API endpoints
    endpoints = get_api_endpoints(session)
    
    # Find healthy server
    base_url = find_working_api(session, endpoints)
    if not base_url:
        log("ERROR: All API servers are unreachable!")
        log("Contact support@deltaneutral.com if this persists.")
        sys.exit(1)
    
    log(f"Using API: {base_url}")
    
    # Login
    token = login_to_api(session, base_url)
    if not token:
        log("Exiting due to login failure.")
        sys.exit(1)

    session.headers.update({"Authorization": f"Bearer {token}"})
    ensure_folder_exists(OUTPUT_FOLDER)

    # Download Purchases
    log("--- Checking Purchases ---")
    try:
        resp = session.get(f"{base_url}/purchases", timeout=60)
        purchases = resp.json().get("purchases", [])
    except Exception as e:
        log(f"Error checking purchases: {e}")
        purchases = []
        
    if not purchases:
        log("No purchases found.")

    for p in purchases:
        folder_name = f"{p['id']} - {p.get('product_name', 'Unknown')}"
        product_path = os.path.join(OUTPUT_FOLDER, "Purchases", sanitize_filename(folder_name))
        ensure_folder_exists(product_path)
        
        try:
            files = session.get(f"{base_url}/purchases/{p['id']}/files", timeout=60).json().get("files", [])
            files_to_download = files[:DAYS_TO_CHECK] if DAYS_TO_CHECK is not None else files
            for f in files_to_download:
                download_file(session, token, f, product_path, base_url)
        except Exception as e:
            log(f"Error getting files for purchase {p['id']}: {e}")

    # Download Groups
    log("--- Checking Groups ---")
    try:
        resp = session.get(f"{base_url}/groups", timeout=60)
        groups = resp.json().get("groups", [])
    except Exception as e:
        log(f"Error checking groups: {e}")
        groups = []

    if not groups:
        log("No groups found.")

    for g in groups:
        folder_name = f"{g['id']} - {g.get('name', 'Unknown')}"
        group_path = os.path.join(OUTPUT_FOLDER, "Groups", sanitize_filename(folder_name))
        ensure_folder_exists(group_path)
        
        try:
            files = session.get(f"{base_url}/groups/{g['id']}/files", timeout=60).json().get("files", [])
            files_to_download = files[:DAYS_TO_CHECK] if DAYS_TO_CHECK is not None else files
            for f in files_to_download:
                download_file(session, token, f, group_path, base_url)
        except Exception as e:
            log(f"Error getting files for group {g['id']}: {e}")

    log("All done!")
    log(f"Files saved to: {OUTPUT_FOLDER}")


if __name__ == "__main__":
    main()