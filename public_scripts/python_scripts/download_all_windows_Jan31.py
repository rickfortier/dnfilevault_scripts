"""
DNFileVault Downloader for Windows (Python)
------------------------------------------------------------------
This script downloads ALL files from your DNFileVault account:
1. All Purchases
2. All Groups

It is designed for Windows users and includes explanations for each part.

BEFORE YOU RUN THIS:
1. You need Python installed.
2. You need the 'requests' library.
   Open Command Prompt (cmd.exe) or PowerShell and run:
       pip install requests

HOW TO CONFIGURE:
Scroll down to the "CONFIGURATION" section below and enter your
email, password, and where you want files to go.

TROUBLESHOOTING TIMEOUTS:
DNFileVault has anti-scanner protection. If requests look "bot-like" 
(e.g., default python-requests/curl User-Agent), the API will 
intentionally slow down responses (throttling). 
We fix this by setting a custom User-Agent and using longer timeouts.
"""

import os
import re
import sys
import time
from datetime import datetime

# We use the 'requests' library to talk to the internet (API).
try:
    import requests
except ImportError:
    print("ERROR: The 'requests' library is not installed.")
    print("Please open PowerShell or Command Prompt and run:")
    print("    pip install requests")
    print("")
    input("Press Enter to exit...")
    sys.exit(1)


# ==============================================================================
# CONFIGURATION
# ==============================================================================
# Enter your DNFileVault email and password here.
# NOTE: Keep the quotes "" around your text.

EMAIL = os.environ.get("DNFV_EMAIL", "your_email@example.com")
PASSWORD = os.environ.get("DNFV_PASSWORD", "your_password")

# Where should the files be saved?
# On Windows, you can use paths like r"C:\Downloads\DNFileVault"
# The 'r' before the quote tells Python to treat backslashes `\` normally.
OUTPUT_FOLDER = os.environ.get("DNFV_OUT_DIR", r"C:\dnfilevault-downloads")

# Filter settings (Optional)
# Set DAYS_TO_CHECK to a number (e.g., 1) to only download the newest files (top N).
# For example, set to 1 to only download the very latest file.
# Set to None to download EVERYTHING.
DAYS_TO_CHECK = None

# ==============================================================================


# Constants for the API
BASE_URL = "https://api.dnfilevault.com"
# A custom User-Agent identifies your script and prevents the API from throttling you.
USER_AGENT = "DNFileVaultClient/1.0 (+support@deltaneutral.com)"

def sanitize_filename(name):
    """
    Cleans up a filename so Windows is happy.
    Windows doesn't like certain characters
    """
    if not name:
        return "unnamed_file"
    # Replace bad characters with an underscore
    clean = re.sub(r'[<>:"/\\\\|?*]', "_", str(name))
    return clean.strip() or "unnamed_file"

def ensure_folder_exists(folder_path):
    """
    Checks if a folder exists. If not, it creates it.
    """
    if not os.path.exists(folder_path):
        try:
            os.makedirs(folder_path)
            print(f"Created folder: {folder_path}")
        except OSError as e:
            print(f"Error creating folder {folder_path}: {e}")

def login_to_api(session):
    """
    Logs in using the EMAIL and PASSWORD variables.
    Returns the 'token' needed for downloading files.
    """
    print(f"Step 1: Logging in as {EMAIL}...")
    
    login_url = f"{BASE_URL}/auth/login"
    payload = {
        "email": EMAIL,
        "password": PASSWORD
    }
    
    try:
        # Send a POST request to the login page (using 60s timeout for stability)
        response = session.post(login_url, json=payload, timeout=60)
        
        # Check if login worked (Status code 200 means OK)
        if response.status_code == 200:
            data = response.json()
            token = data.get("token")
            print("Login successful!")
            return token
        elif response.status_code == 401:
            print("Login failed: Incorrect email or password. Please check your EMAIL and PASSWORD settings.")
        else:
            print(f"Login failed: Server returned error {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("Login failed: ERROR - No internet connection or DNS failure. (Could not reach api.dnfilevault.com)")
    except requests.exceptions.Timeout:
        print("Login failed: ERROR - The request timed out. Your connection might be slow or the server is busy.")
    except requests.exceptions.RequestException as e:
        print(f"Login failed: ERROR - A network problem occurred: {e}")
        
    return None

def download_file(session, token, file_info, save_directory):
    """
    Downloads a single file using the 'Auto-Fallback' strategy:
    1. Method 1 (Primary): Direct Cloudflare R2 (Fastest, no auth)
    2. Method 2 (Fallback): API Server (Authenticated)
    """
    uuid_filename = file_info.get("uuid_filename")
    cloud_url = file_info.get("cloud_share_link")
    display_name = file_info.get("display_name") or uuid_filename
    
    # Clean the name for Windows
    safe_name = sanitize_filename(display_name)
    full_save_path = os.path.join(save_directory, safe_name)
    
    # Check if we already have it
    if os.path.exists(full_save_path):
        # Optional: verify size here if you want to be extra robust
        # print(f"  Skipping (already exists): {safe_name}")
        return

    # Method 1: Try R2 Direct Link (PRIMARY)
    if cloud_url:
        print(f"  Downloading: {safe_name} via Cloudflare R2 (Method 1)...")
        try:
            # Note: We use a fresh requests.get (no session headers) because 
            # R2 links are public/signed and don't need our JWT or custom User-Agent.
            with requests.get(cloud_url, stream=True, timeout=30) as r:
                if r.status_code == 200:
                    save_content(r, full_save_path)
                    print(f"  ✓ Complete (fast)")
                    return
                else:
                    print(f"  R2 returned {r.status_code}, trying fallback...")
        except Exception as e:
            print(f"  R2 attempt failed: {e}, trying fallback...")

    # Method 2: Fallback to API Server
    if not uuid_filename:
        print(f"  ✗ Error: No download ID available for {safe_name}")
        return

    print(f"  Downloading: {safe_name} via API Server (Method 2)...")
    download_url = f"{BASE_URL}/download/{uuid_filename}"
    
    try:
        # We reuse the 'session' here because it carries our JWT Token and custom User-Agent.
        with session.get(download_url, stream=True, timeout=300) as r:
            if r.status_code == 200:
                save_content(r, full_save_path)
                print(f"  ✓ Complete (fallback)")
            else:
                print(f"  ✗ Failed to download {safe_name}. Status: {r.status_code}")
    except Exception as e:
        print(f"  ✗ Error downloading {safe_name}: {e}")

def save_content(response, full_save_path):
    """Utility to write the response stream to disk safely with speed display."""
    temp_path = full_save_path + ".tmp"
    total_downloaded = 0
    start_time = time.time()
    
    # Try to get total size for progress
    total_size = int(response.headers.get('content-length', 0))
    
    with open(temp_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024*1024): # 1 MB chunks
            if chunk:
                f.write(chunk)
                total_downloaded += len(chunk)
                
                elapsed = time.time() - start_time
                if elapsed > 0:
                    speed_mbps = (total_downloaded / (1024 * 1024)) / elapsed
                    
                    if total_size > 0:
                        percent = (total_downloaded / total_size) * 100
                        # Use end='' and \r to stay on the same line for progress updates
                        sys.stdout.write(f"\r    Progress: {percent:6.1f}% | Speed: {speed_mbps:6.2f} MB/s")
                    else:
                        sys.stdout.write(f"\r    Downloaded: {total_downloaded / (1024*1024):7.1f} MB | Speed: {speed_mbps:6.2f} MB/s")
                    sys.stdout.flush()
    
    # End the progress line
    print("")
    
    if os.path.exists(full_save_path):
        os.remove(full_save_path)
    os.rename(temp_path, full_save_path)

def main():
    print("--- DNFileVault Windows Downloader ---")
    print(f"Saving files to: {OUTPUT_FOLDER}")
    
    # 1. Start a web session
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    
    # 2. Login
    token = login_to_api(session)
    if not token:
        # If no token, we can't continue
        print("Stopping script due to login failure.")
        input("Press Enter to exit...")
        return

    # Add the token to all future requests
    session.headers.update({"Authorization": f"Bearer {token}"})

    # Prepare the output folder
    ensure_folder_exists(OUTPUT_FOLDER)

    # 3. Download Purchases
    # --------------------------------------------------------------------------
    print("\n--- Checking Purchases ---")
    try:
        resp = session.get(f"{BASE_URL}/purchases", timeout=60)
        data = resp.json()
        purchases = data.get("purchases", [])
    except Exception as e:
        print(f"Error checking purchases: {e}")
        purchases = []
        
    if not purchases:
        print("No purchases found.")

    for p in purchases:
        # Create a folder for each product
        folder_name = f"{p['id']} - {p.get('product_name', 'Unknown')}"
        safe_folder_name = sanitize_filename(folder_name)
        product_path = os.path.join(OUTPUT_FOLDER, "Purchases", safe_folder_name)
        ensure_folder_exists(product_path)
        
        # Get files for this purchase
        try:
            files_resp = session.get(f"{BASE_URL}/purchases/{p['id']}/files", timeout=60)
            files = files_resp.json().get("files", [])
            
            # Determine which files to download
            files_to_download = files
            if DAYS_TO_CHECK is not None:
                # If we have a limit, take only the first N files
                # (Assumes the API returns them sorted newly created -> older)
                files_to_download = files[:DAYS_TO_CHECK]

            for f in files_to_download:
                download_file(session, token, f, product_path)
                
        except Exception as e:
            print(f"Error getting files for purchase {p['id']}: {e}")

    # 4. Download Groups
    # --------------------------------------------------------------------------
    print("\n--- Checking Groups ---")
    try:
        resp = session.get(f"{BASE_URL}/groups", timeout=60)
        data = resp.json()
        groups = data.get("groups", [])
    except Exception as e:
        print(f"Error checking groups: {e}")
        groups = []

    if not groups:
        print("No groups found.")

    for g in groups:
        # Create a folder for each group
        folder_name = f"{g['id']} - {g.get('name', 'Unknown')}"
        safe_folder_name = sanitize_filename(folder_name)
        group_path = os.path.join(OUTPUT_FOLDER, "Groups", safe_folder_name)
        ensure_folder_exists(group_path)
        
        # Get files for this group
        try:
            files_resp = session.get(f"{BASE_URL}/groups/{g['id']}/files", timeout=60)
            files = files_resp.json().get("files", [])
            
            # Determine which files to download
            files_to_download = files
            if DAYS_TO_CHECK is not None:
                # If we have a limit, take only the first N files
                files_to_download = files[:DAYS_TO_CHECK]

            for f in files_to_download:
                download_file(session, token, f, group_path)
                
        except Exception as e:
            print(f"Error getting files for group {g['id']}: {e}")

    print("\n------------------------------------------------------------------")
    print("All done!")
    print(f"Check your files in: {OUTPUT_FOLDER}")
    # Pause so the user can see the message if they double-clicked the script
    input("Press Enter to close this window...")

if __name__ == "__main__":
    main()
