"""
DNFileVault: Download ALL purchase + group files (beginner-friendly / lots of prints)

What this script does:
- Logs in with your email + password (POST /auth/login) to get a JWT token
- Lists your purchases (GET /purchases) and downloads each purchase's files
- Lists your groups (GET /groups) and downloads each group's files
- Creates all folders it needs
- Skips files that already exist (so you can re-run it safely)

Before running:
1) Install Python 3.10+ (3.11+ recommended).
2) Install the 'requests' library:
     pip install requests

Then run:
  python download_all_python.py

Tip (optional):
You can set environment variables instead of editing the file:
  DNFV_EMAIL
  DNFV_PASSWORD
  DNFV_OUT_DIR
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple

try:
    import requests
except Exception as e:
    print("ERROR: This script needs the 'requests' library but it is not installed.")
    print("What happened:", repr(e))
    print("")
    print("Fix:")
    print("  1) Open a terminal / PowerShell")
    print("  2) Run: pip install requests")
    print("")
    sys.exit(1)


# ----------------------------
# EDIT THESE (or use env vars)
# ----------------------------

BASE_URL = "https://api.dnfilevault.com"
USER_AGENT = "DNFileVaultBulkDownloader/1.0"

# It is recommended to set these in your terminal environments instead of hardcoding:
# Windows: $env:DNFV_EMAIL = "me@example.com"
# Linux:   export DNFV_EMAIL="me@example.com"
EMAIL = os.environ.get("DNFV_EMAIL", "you@example.com")
PASSWORD = os.environ.get("DNFV_PASSWORD", "your_password_here")
OUT_DIR = os.environ.get("DNFV_OUT_DIR", "C:\\dnfilevault-downloads")

# Download behavior
CHUNK_SIZE_BYTES = 1024 * 1024  # 1 MB
REQUEST_TIMEOUT_SECONDS = 60
SLEEP_BETWEEN_DOWNLOADS_SECONDS = 0.10  # small pause to be polite to the API


def print_banner() -> None:
    print("============================================================")
    print("DNFileVault Bulk Downloader (Python)")
    print("============================================================")
    print("Base URL:", BASE_URL)
    print("Output folder:", OUT_DIR)
    print("User-Agent:", USER_AGENT)
    print("------------------------------------------------------------")
    print("Important:")
    print("- If downloads are slow, that's normal if requests look like scanners.")
    print("- This script sets a custom User-Agent to reduce slow-downs.")
    print("- You can safely re-run: it skips files already on disk.")
    print("============================================================")
    print("")


def sanitize_file_or_folder_name(name: str) -> str:
    """
    Windows-safe filename: replace invalid characters with underscores.
    """
    if name is None:
        return "unnamed"

    name = str(name).strip()
    if not name:
        return "unnamed"

    # Replace invalid characters for Windows filenames: < > : " / \ | ? *
    name = re.sub(r'[<>:"/\\\\|?*]', "_", name)
    name = name.rstrip(" .")

    if not name:
        return "unnamed"

    if len(name) > 150:
        name = name[:150].rstrip(" .")

    return name


def ensure_dir(path: str) -> None:
    if not path:
        raise ValueError("ensure_dir: path is empty")
    if os.path.isdir(path):
        return
    print("Creating folder:", path)
    os.makedirs(path, exist_ok=True)


def pretty_http_error(response: requests.Response) -> str:
    status = response.status_code
    text_preview = ""
    try:
        data = response.json()
        text_preview = str(data)
    except Exception:
        try:
            t = response.text or ""
            t = t.strip()
            if len(t) > 500:
                t = t[:500] + " ... (truncated)"
            text_preview = t
        except Exception:
            text_preview = "<could not read response body>"

    hint = ""
    if status == 401:
        hint = "Hint: 401 usually means bad email/password OR missing/expired token."
    elif status == 403:
        hint = "Hint: 403 means you do not have access to that file."
    elif status == 404:
        hint = "Hint: 404 means the file record exists but the server can't find it on disk."
    elif status == 429:
        hint = "Hint: 429 means rate-limited. Try running again later."

    msg = f"HTTP {status}"
    if hint:
        msg += f" | {hint}"
    if text_preview:
        msg += f" | Response: {text_preview}"
    return msg


def api_get_json(session: requests.Session, url: str) -> Dict[str, Any]:
    print("GET:", url)
    resp = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise RuntimeError(pretty_http_error(resp))
    try:
        return resp.json()
    except Exception as e:
        raise RuntimeError(f"Server returned non-JSON data for {url}. Error: {repr(e)}")


def login_and_get_session() -> Tuple[requests.Session, str]:
    print("Step 1: Logging in to get a token...")
    print("  Email:", EMAIL)

    if not EMAIL or EMAIL == "you@example.com":
        print("")
        print("STOP: Please set DNFV_EMAIL environment variable to your real email.")
        sys.exit(1)

    if not PASSWORD or PASSWORD == "your_password_here":
        print("")
        print("STOP: Please set DNFV_PASSWORD environment variable to your real password.")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        }
    )

    login_url = f"{BASE_URL}/auth/login"
    payload = {"email": EMAIL, "password": PASSWORD}
    print("POST:", login_url)
    print("  Sending login request...")

    resp = session.post(login_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        print("")
        print("Login failed.")
        raise RuntimeError(pretty_http_error(resp))

    data = resp.json()
    token = data.get("token")
    if not token:
        raise RuntimeError("Login succeeded but response did not contain a 'token'.")

    print("  Login OK. Token received.")
    session.headers.update({"Authorization": f"Bearer {token}"})
    print("Step 1 complete.")
    print("")
    return session, token


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while True:
        candidate = f"{base} ({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def download_file_with_fallback(session: requests.Session, file_info: Dict[str, Any], out_path: str) -> None:
    ensure_dir(os.path.dirname(out_path))

    if os.path.exists(out_path):
        print("  SKIP (already exists):", out_path)
        return

    display_name = file_info.get("display_name") or "unnamed"
    uuid_filename = file_info.get("uuid_filename")
    cloud_url = file_info.get("cloud_share_link")

    # PRIMARY: Try Cloudflare R2 direct link (FAST)
    if cloud_url:
        print(f"  Attempting Direct R2 Download: {cloud_url}")
        try:
            # Note: R2 links do not need the Authorization header or custom User-Agent,
            # but we use the session anyway for consistency/timeouts. 
            # We clear the Authorization header for this specific request if it's a direct cloud link.
            with session.get(cloud_url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS, headers={"Authorization": None}) as resp:
                if resp.status_code == 200:
                    save_stream_to_file(resp, out_path)
                    print(f"  ✓ DONE via R2: {out_path}")
                    return
                else:
                    print(f"  R2 returned HTTP {resp.status_code}. Falling back to API server.")
        except Exception as e:
            print(f"  R2 download failed: {repr(e)}. Falling back to API server.")

    # FALLBACK: Use API server route
    if not uuid_filename:
        print("  ERROR: No UUID or Cloud Link available for this file.")
        return

    api_url = f"{BASE_URL}/download/{uuid_filename}"
    print(f"  Attempting API Download: {api_url}")
    try:
        # For API download, we must have the Authorization header (which is already in the session)
        with session.get(api_url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            if resp.status_code == 200:
                save_stream_to_file(resp, out_path)
                print(f"  ✓ DONE via API: {out_path}")
            else:
                raise RuntimeError(pretty_http_error(resp))
    finally:
        time.sleep(SLEEP_BETWEEN_DOWNLOADS_SECONDS)


def save_stream_to_file(resp: requests.Response, out_path: str) -> None:
    total = resp.headers.get("Content-Length")
    if total:
        print("    Size (bytes):", total)
    else:
        print("    Size (bytes): unknown")

    temp_path = out_path + ".part"
    bytes_written = 0
    start_time = time.time()

    with open(temp_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE_BYTES):
            if not chunk:
                continue
            f.write(chunk)
            bytes_written += len(chunk)
            if bytes_written % (10 * CHUNK_SIZE_BYTES) < CHUNK_SIZE_BYTES:
                elapsed = max(time.time() - start_time, 0.0001)
                mb = bytes_written / (1024 * 1024)
                rate = mb / elapsed
                print(f"      Downloaded: {mb:.1f} MB ({rate:.1f} MB/s)")

    final_out_path = unique_path(out_path) if os.path.exists(out_path) else out_path
    os.replace(temp_path, final_out_path)


def download_all_purchases(session: requests.Session) -> None:
    print("Step 2: Downloading PURCHASE files...")
    purchases_root = os.path.join(OUT_DIR, "purchases")
    ensure_dir(purchases_root)

    purchases_url = f"{BASE_URL}/purchases"
    data = api_get_json(session, purchases_url)
    purchases = data.get("purchases", [])

    if not purchases:
        print("No purchases found.")
        print("Step 2 complete.")
        print("")
        return

    print("Purchases found:", len(purchases))

    for idx, p in enumerate(purchases, start=1):
        purchase_id = p.get("id")
        product_name = p.get("product_name", "")
        print("------------------------------------------------------------")
        print(f"Purchase {idx}/{len(purchases)}")
        print("  id          :", purchase_id)
        print("  product_name:", product_name)

        if not purchase_id:
            continue

        folder_name = sanitize_file_or_folder_name(f"{purchase_id} - {product_name}")
        purchase_dir = os.path.join(purchases_root, folder_name)
        ensure_dir(purchase_dir)

        files_url = f"{BASE_URL}/purchases/{purchase_id}/files"
        files_data = api_get_json(session, files_url)
        files = files_data.get("files", [])

        print("  Files found:", len(files))
        for f in files:
            display_name = f.get("display_name") or "unnamed"
            uuid_filename = f.get("uuid_filename")
            if not uuid_filename:
                continue

            safe_name = sanitize_file_or_folder_name(display_name)
            out_path = os.path.join(purchase_dir, safe_name)
            print("")
            print("  File:", display_name)
            download_file_with_fallback(session, f, out_path)

    print("")
    print("Step 2 complete.")
    print("")


def download_all_groups(session: requests.Session) -> None:
    print("Step 3: Downloading GROUP files...")
    groups_root = os.path.join(OUT_DIR, "groups")
    ensure_dir(groups_root)

    groups_url = f"{BASE_URL}/groups"
    data = api_get_json(session, groups_url)
    groups = data.get("groups", [])

    if not groups:
        print("No groups found.")
        print("Step 3 complete.")
        print("")
        return

    print("Groups found:", len(groups))

    for idx, g in enumerate(groups, start=1):
        group_id = g.get("id")
        group_name = g.get("name", "")
        print("------------------------------------------------------------")
        print(f"Group {idx}/{len(groups)}")
        print("  id  :", group_id)
        print("  name:", group_name)

        if not group_id:
            continue

        folder_name = sanitize_file_or_folder_name(f"{group_id} - {group_name}")
        group_dir = os.path.join(groups_root, folder_name)
        ensure_dir(group_dir)

        files_url = f"{BASE_URL}/groups/{group_id}/files"
        files_data = api_get_json(session, files_url)
        files = files_data.get("files", [])

        print("  Files found:", len(files))
        for f in files:
            display_name = f.get("display_name") or "unnamed"
            uuid_filename = f.get("uuid_filename")
            if not uuid_filename:
                continue

            safe_name = sanitize_file_or_folder_name(display_name)
            out_path = os.path.join(group_dir, safe_name)
            print("")
            print("  File:", display_name)
            download_file_with_fallback(session, f, out_path)

    print("")
    print("Step 3 complete.")
    print("")


def main() -> None:
    print_banner()
    ensure_dir(OUT_DIR)

    try:
        session, _token = login_and_get_session()
        download_all_purchases(session)
        download_all_groups(session)
    except KeyboardInterrupt:
        print("\nStopping safely.")
        sys.exit(2)
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        sys.exit(1)

    print("All done.")


if __name__ == "__main__":
    main()
