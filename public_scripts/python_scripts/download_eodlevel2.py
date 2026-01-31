"""
DNFileVault: Download only EOD Level 2 files (Simple Python Script)
"""

import os
import requests
from pathlib import Path

# --- CONFIGURATION ---
BASE_URL = "https://api.dnfilevault.com"
EMAIL = os.environ.get("DNFV_EMAIL", "you@example.com")
PASSWORD = os.environ.get("DNFV_PASSWORD", "your_password_here")
OUT_DIR = Path(os.environ.get("DNFV_OUT_DIR", "./downloads-eodlevel2"))
GROUP_NAME = "eodLevel2"


def main():
    if not EMAIL or EMAIL == "you@example.com":
        print("Please set DNFV_EMAIL environment variable.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "DNFileVaultSimpleDownloader/1.0"})

    # Login
    print(f"Logging in as {EMAIL}...")
    resp = session.post(f"{BASE_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    token = resp.json()["token"]
    session.headers.update({"Authorization": f"Bearer {token}"})

    # Find Group
    print(f"Finding group: {GROUP_NAME}...")
    groups = session.get(f"{BASE_URL}/groups").json()["groups"]
    group = next((g for g in groups if g["name"].lower() == GROUP_NAME.lower()), None)
    
    if not group:
        print(f"Group {GROUP_NAME} not found.")
        return

    group_id = group["id"]
    
    # List Files
    print("Fetching file list...")
    files = session.get(f"{BASE_URL}/groups/{group_id}/files").json()["files"]
    
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    for f in files:
        display_name = f["display_name"]
        uuid = f["uuid_filename"]
        cloud_url = f.get("cloud_share_link")
        out_path = OUT_DIR / display_name
        
        if out_path.exists():
            print(f"  Skip: {display_name} (exists)")
            continue
            
        # Try R2 first
        if cloud_url:
            print(f"  Downloading (R2): {display_name}...")
            try:
                with session.get(cloud_url, stream=True, headers={"Authorization": None}) as r:
                    if r.status_code == 200:
                        with open(out_path, "wb") as fd:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                fd.write(chunk)
                        continue # Done with this file
            except Exception:
                print("    R2 failed, trying API fallback...")

        # Fallback to API
        print(f"  Downloading (API): {display_name}...")
        with session.get(f"{BASE_URL}/download/{uuid}", stream=True) as r:
            r.raise_for_status()
            with open(out_path, "wb") as fd:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    fd.write(chunk)
                    
    print("Done.")

if __name__ == "__main__":
    main()
