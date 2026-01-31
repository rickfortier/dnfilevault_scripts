
import os
import sys
import zipfile
import requests
import pandas as pd
from datetime import datetime, timezone

# Assuming these are custom modules in your environment
try:
    import utils
    import sstore
except ImportError:
    # Mocks for standalone testing/linting if modules are missing
    class MockUtils:
        def getPrevDate(self):
            return datetime.now() - pd.Timedelta(days=1)
    
    class MockSStore:
        def setStatus(self, msg):
            print(f"[STATUS] {msg}")

    utils = MockUtils()
    sstore = MockSStore()

def get_dn_session(email, password, base_url="https://api.dnfilevault.com"):
    """
    Authenticates with DNFileVault and returns a session with the auth token.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": "DNFileVaultFetcher/1.0"})
    
    try:
        resp = session.post(
            f"{base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30
        )
        resp.raise_for_status()
        token = resp.json()["token"]
        session.headers.update({"Authorization": f"Bearer {token}"})
        return session
    except Exception as e:
        raise Exception(f"DNFileVault Login Failed: {e}")

def find_group_id(session, base_url, group_name_filter="eodLevel2"):
    """
    Finds the Group ID for a given group name (case-insensitive).
    """
    resp = session.get(f"{base_url}/groups", timeout=30)
    resp.raise_for_status()
    groups = resp.json().get("groups", [])
    
    for g in groups:
        if str(g.get("name", "")).strip().lower() == group_name_filter.lower():
            return g["id"]
    return None

def download_file_api(session, base_url, uuid_filename, target_path):
    """
    Downloads a file using the DNFileVault API.
    """
    download_url = f"{base_url}/download/{uuid_filename}"
    
    # Download to .part file
    tmp_path = target_path + ".part"
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    with session.get(download_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
    
    # Rename to final
    if os.path.exists(target_path):
        os.remove(target_path)
    os.rename(tmp_path, target_path)

def processDf(df, savefilename):
    """
    Placeholder for the actual processing logic used in your system.
    """
    print(f"Processing DataFrame from {savefilename} with shape {df.shape}")
    # Your original logic here...

def fetchRecentData():
    """
    Improved version of fetchRecentData using DNFileVault API instead of FTP.
    """
    try:
        # 1. Setup Configuration
        email = os.environ.get("DNFV_EMAIL")
        password = os.environ.get("DNFV_PASSWORD")
        base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
        # Default destination from original script
        target_dir = os.environ.get("DNFV_TARGET_DIR", "/var/www/optiondata/Recent")
        
        if not email or not password:
            raise ValueError("Environment variables DNFV_EMAIL and DNFV_PASSWORD must be set.")

        # 2. Determine target file
        datadate = utils.getPrevDate()
        dt_str = datadate.strftime("%Y%m%d")
        filename = f"L2_{dt_str}.zip"
        targetfilepath = os.path.join(target_dir, filename)

        sstore.setStatus(f"Starting fetch for {filename}...")

        # 3. Connect to API
        session = get_dn_session(email, password, base_url)
        
        # 4. Find the Group (e.g., eodLevel2) containing the file
        # Note: You might need to adjust 'eodLevel2' if your files are in a different group.
        group_id = find_group_id(session, base_url, "eodLevel2")
        if not group_id:
            sstore.setStatus("Group 'eodLevel2' not found via API.")
            return False

        # 5. List files in the group and find the target file
        files_resp = session.get(f"{base_url}/groups/{group_id}/files", timeout=30)
        files_resp.raise_for_status()
        files = files_resp.json().get("files", [])
        
        target_file_obj = None
        for f in files:
            # Check display_name first, then uuid_filename
            dname = f.get("display_name")
            if dname and dname == filename:
                target_file_obj = f
                break
            
            # Fallback check if filename is inside display name (if looser matching needed)
            # or check uuid if needed (unlikely for specific date files)

        if not target_file_obj:
            sstore.setStatus(f"File {filename} not found in group.")
            return False

        # 6. Download if needed
        if not os.path.exists(targetfilepath):
            sstore.setStatus(f"Downloading {filename}...")
            download_file_api(session, base_url, target_file_obj["uuid_filename"], targetfilepath)
        else:
            sstore.setStatus(f"File {filename} already exists locally.")

        # 7. Process the Zip
        sstore.setStatus(f"Processing {filename}...")
        with zipfile.ZipFile(targetfilepath) as zf:
            csvList = zf.namelist()
            for csvfile in csvList:
                if csvfile.endswith(".csv") and "options_" in csvfile:
                    # Using pyarrow engine as in your original commented code, or default
                    # df = pd.read_csv(zf.open(csvfile), engine='pyarrow', dtype_backend='pyarrow')
                    df = pd.read_csv(zf.open(csvfile))
                    
                    savefilename = csvfile
                    if "L2_" not in savefilename:
                        savefilename = "L2_" + savefilename
                    
                    processDf(df, savefilename)

        sstore.setStatus("complete fetch recent data")
        return True

    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        error_msg = f"{e} ({exc_type}, {fname}, {exc_tb.tb_lineno})"
        print(error_msg)
        sstore.setStatus(error_msg)
        return False

if __name__ == "__main__":
    # Example usage
    # Ensure env vars are set before running
    if not os.environ.get("DNFV_EMAIL"):
        print("Please set DNFV_EMAIL and DNFV_PASSWORD")
    else:
        success = fetchRecentData()
        print(f"Fetch success: {success}")
