# DNFileVault: The Comprehensive Developer & Implementation Guide

This guide provides everything you need to successfully integrate with the DNFileVault API, from core concepts and troubleshooting to production-ready code templates.

---

## 1. API Discovery & Failover

DNFileVault runs across multiple API servers for redundancy. Your script should **never hardcode a single API URL**. Instead, use the automatic discovery system to find the best available server.

### How It Works

1. **Discovery**: Your script fetches a central configuration file from Cloudflare R2
2. **Health Check**: It tests each endpoint in priority order
3. **Failover**: If the primary is down, it automatically uses the next healthy server
4. **Fallback**: If the discovery service itself is unreachable, hardcoded fallback URLs are used

### Discovery Endpoint

```
https://config.dnfilevault.com/endpoints.json
```

This returns a JSON object listing all available API servers (which may change over time):

```json
{
  "version": 1,
  "updated": "2026-02-07",
  "endpoints": [
    {"url": "https://api.dnfilevault.com", "label": "Yellow-Dev", "priority": 1},
    {"url": "https://api-redmint.dnfilevault.com", "label": "Red-Mint", "priority": 2},
    {"url": "https://api-va.dnfilevault.com", "label": "Hetzner-VA", "priority": 3},
    {"url": "https://api-west.dnfilevault.com", "label": "Hetzner-West", "priority": 4}
  ]
}
```

**Fields:**
- `version` — Incremented when endpoints change. Can be used for cache-busting.
- `updated` — Date of last configuration change.
- `endpoints` — Array of API servers sorted by `priority` (1 = preferred).

### Implementation: Discovery + Health Check

```python
DISCOVERY_URL = "https://config.dnfilevault.com/endpoints.json"

# Hardcoded fallback in case discovery itself is unreachable
FALLBACK_ENDPOINTS = [
    "https://api.dnfilevault.com",
    "https://api-redmint.dnfilevault.com",
]

def get_api_endpoints(session):
    """Fetch current API endpoint list from Cloudflare R2."""
    try:
        r = session.get(DISCOVERY_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            endpoints = sorted(data["endpoints"], key=lambda x: x.get("priority", 99))
            urls = [e["url"] for e in endpoints]
            print(f"Discovered {len(urls)} endpoints (v{data.get('version', '?')})")
            return urls
    except Exception as e:
        print(f"Discovery unavailable: {e}")
    return FALLBACK_ENDPOINTS

def find_working_api(session, endpoints):
    """Test each endpoint and return the first healthy one."""
    for url in endpoints:
        try:
            r = session.get(f"{url}/health", timeout=10)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                print(f"Using API: {url}")
                return url
        except:
            print(f"  {url} - unreachable, trying next...")
    return None
```

### Usage in Your Script

```python
session = requests.Session()
session.headers.update({"User-Agent": "DNFileVaultClient/1.0"})

# Step 1: Discover endpoints
endpoints = get_api_endpoints(session)

# Step 2: Find a healthy server
base_url = find_working_api(session, endpoints)
if not base_url:
    print("All API servers are down!")
    sys.exit(1)

# Step 3: Use base_url for all subsequent API calls
token = login(session, base_url)
# ...
```

### Why This Matters

- **Zero downtime for customers**: If one server goes down, the script automatically uses another.
- **No script updates needed**: When servers are added, moved, or retired, only the JSON on R2 is updated. Every customer's existing script picks up the change on next run.
- **Global reach**: Customers automatically connect to the geographically closest healthy server.

### Health Check Endpoints

Each API server provides health endpoints:

| Endpoint | What It Checks |
| :--- | :--- |
| `/health` | API server is running and responding |
| `/health/db` | API server AND database connectivity |

**`/health` response:**
```json
{"service": "DNFileVault API", "status": "healthy"}
```

**`/health/db` response:**
```json
{"service": "DNFileVault API", "status": "healthy", "database": "connected", "files": 5731, "users": 329}
```

For the discovery health check, use `/health` (faster, no DB round-trip). For deeper monitoring, use `/health/db` to confirm database connectivity.

---

## 2. Download Methods: Two Ways to Access Files

DNFileVault provides **TWO download methods**. Always use Method 1 (Cloud Link) as your primary approach.

### Method 1: Direct Cloudflare R2 Download (PRIMARY - RECOMMENDED ⭐)

**What it is:** `cloud_share_link` - A direct CDN link to your file hosted on Cloudflare R2.

**Why use this:**
- ✅ **Fastest**: Downloads directly from Cloudflare's global CDN edge servers
- ✅ **Worldwide**: Optimized delivery from data centers closest to you
- ✅ **Lower server load**: Doesn't go through DNFileVault API servers
- ✅ **Best for bulk downloads**: Parallel downloads without rate limiting

**How it works:**
1. Login to get JWT token
2. List files in a group
3. Each file includes a `cloud_share_link` field
4. Use that link directly - no authentication header needed!

**Example:**
```python
import requests

# After login and getting group files...
files = response.json()["files"]
for file in files:
    # Use cloud_share_link directly - FAST!
    download_url = file["cloud_share_link"]  # e.g., https://vault.dnfilevault.com/abc-123
    
    # No authentication needed for R2 links
    # Note: Use stream=True for large files
    with requests.get(download_url, stream=True) as r:
        r.raise_for_status()
        with open(file["display_name"], "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
```

**URL Format:**
```
https://vault.dnfilevault.com/{uuid_filename}
```

### Method 2: Server-Routed Download (FALLBACK)

**What it is:** Traditional API endpoint: `/download/{uuid_filename}`

**When to use this:**
- 🔥 **Behind corporate firewall**: Your firewall blocks `vault.dnfilevault.com`
- 🔥 **Need audit logging**: Server logs every download attempt
- 🔥 **Special security requirements**: Must route through authenticated API

**How it works:**
- Request goes through DNFileVault API server
- Requires JWT token in `Authorization` header
- Server validates access and streams file to you
- Slower (not CDN-optimized)

**Example:**
```python
# Fallback method - use when cloud_share_link doesn't work
download_url = f"{base_url}/download/{file['uuid_filename']}"
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(download_url, headers=headers, stream=True)
# ... save to file ...
```

**Note:** Use the dynamically discovered `base_url` (from Section 1), not a hardcoded URL.

### Recommended Implementation: Auto-Fallback

```python
def download_file(file_info, token, output_path, base_url):
    """Download with automatic fallback from R2 to API server."""
    
    # Try Method 1: Direct R2 link (PRIMARY)
    try:
        cloud_url = file_info.get("cloud_share_link")
        if cloud_url:
            print(f"Downloading {file_info['display_name']} via Cloudflare R2...")
            with requests.get(cloud_url, timeout=30, stream=True) as r:
                if r.status_code == 200:
                    with open(output_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                    print(f"✓ Complete (fast)")
                    return True
    except Exception as e:
        print(f"R2 download failed: {e}, trying fallback...")
    
    # Fallback to Method 2: API server route
    try:
        api_url = f"{base_url}/download/{file_info['uuid_filename']}"
        headers = {"Authorization": f"Bearer {token}"}
        print(f"Downloading {file_info['display_name']} via API Server...")
        with requests.get(api_url, headers=headers, timeout=60, stream=True) as r:
            if r.status_code == 200:
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        f.write(chunk)
                print(f"✓ Complete (fallback)")
                return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False
```

### Troubleshooting: Why Direct Download URLs Fail

If you are trying to download files by guessing folder structures (e.g., `/eodLevel2/L2_...zip`), **it will not work.**

**The Core Problem:**
The DNFileVault API is a **database-driven system**, not a flat file server. It does not have physical folders that you can browse directly via URL.

1.  **Wrong Endpoints**:
    *   ❌ **WRONG**: `https://api.dnfilevault.com/eodLevel2/filename.zip`
    *   ✅ **CORRECT**: Use the `cloud_share_link` from the API response
    *   ✅ **FALLBACK**: `https://{base_url}/download/{uuid_filename}`
    
2.  **Wrong Identifiers**:
    *   The API does not recognize filenames like `L2_20260116.zip` for direct access.
    *   You must first list files to get the `uuid_filename` or `cloud_share_link`.

### The Required Pattern: "Discover -> Login -> List -> Download"

You must follow these steps in order:
1.  **Discover**: Fetch `config.dnfilevault.com/endpoints.json` and find a healthy API server.
2.  **Login**: Call `POST /auth/login` to get a **JWT Token**.
3.  **List**: Call `GET /groups/{id}/files` to get file info including `cloud_share_link`.
4.  **Download**: Use `cloud_share_link` directly (no auth needed!) or fall back to UUID method.

---

## 3. API Reference & Core Concepts

### Base URLs

Do **not** hardcode a base URL. Use the discovery system (Section 1) to find the current best server. The available servers as of this writing are:

| Server | URL | Location |
| :--- | :--- | :--- |
| Yellow-Dev (Primary) | `https://api.dnfilevault.com` | Local |
| Red-Mint | `https://api-redmint.dnfilevault.com` | Local |
| Hetzner-VA | `https://api-va.dnfilevault.com` | Ashburn, VA |
| Hetzner-West | `https://api-west.dnfilevault.com` | Hillsboro, OR |

**Discovery URL:** `https://config.dnfilevault.com/endpoints.json`
**Website (Manual):** `https://dnfilevault.com`

### Authentication
Include your token in the `Authorization` header for all protected endpoints:
`Authorization: Bearer <your_jwt_token>`

### Important: User-Agent
The API intentionally slows requests from generic headers (like `python-requests`). **Always** set a custom User-Agent:
`User-Agent: DNFileVaultClient/1.0 (+support@deltaneutral.com)`

### Primary Endpoints
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | `GET` | Server health check (fast, no DB). |
| `/health/db` | `GET` | Server + database health check. |
| `/auth/login` | `POST` | Exchange email/password for a JWT Token. |
| `/purchases` | `GET` | List all products/purchases owned by the user. |
| `/groups` | `GET` | List all membership groups (e.g., eodLevel2, eodLevel3). |
| `/groups/{id}/files` | `GET` | List all files within a specific group. Returns `cloud_share_link` for each file. |
| `/download/{uuid}` | `GET` | **FALLBACK ONLY**: Download via API server (slower). Use `cloud_share_link` instead. |

### File Object Structure
When you call `/groups/{id}/files`, each file object includes:
```json
{
  "id": 12345,
  "uuid_filename": "f3119e86-44eb-4a31-8710-d07d3ba9adbc",
  "display_name": "L2_20260116.zip",
  "file_size": 52428800,
  "checksum": "abc123...",
  "created_at": "2026-01-16T10:30:00Z",
  "cloud_share_link": "https://vault.dnfilevault.com/f3119e86-44eb-4a31-8710-d07d3ba9adbc"
}
```

**KEY FIELD**: `cloud_share_link` - Use this for all downloads (fastest, global CDN).

---

## 4. Implementation Best Practices

### The "Short Circuit" Strategy
To optimize your C# applications, don't initiate a download if the file is already on your disk. Use a centralized Python script for the "heavy lifting" (automation) and have your C# code check the local folder first.

**C# Wrapper Example:**
```csharp
public void GetFile(string fileName, string groupName)
{
    string localPath = Path.Combine(@"C:\dnfilevault-downloads", groupName, fileName);
    
    if (File.Exists(localPath)) {
        // Instant access
        ProcessFile(localPath);
    } else {
        // Fallback to API/FTP download
        DownloadFile(fileName);
    }
}
```

### Buddy Coding (VS + Cursor)
For rapid implementation across many legacy projects:
1.  Open your project in **Visual Studio** and **Cursor** simultaneously.
2.  Use the AI chat in Cursor to find all FTP calls and automatically refactor them to include the "Short Circuit" logic.

---

## 5. Code Cookbook: Templates

### Environment Setup
Store your credentials in environment variables rather than hardcoding them.

### Python Template (Bulk Downloader with Discovery + R2)
```python
import os
import requests
from pathlib import Path

DISCOVERY_URL = "https://config.dnfilevault.com/endpoints.json"
FALLBACK_ENDPOINTS = [
    "https://api.dnfilevault.com",
    "https://api-redmint.dnfilevault.com",
]

def get_api_endpoints(session):
    try:
        r = session.get(DISCOVERY_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            endpoints = sorted(data["endpoints"], key=lambda x: x.get("priority", 99))
            return [e["url"] for e in endpoints]
    except:
        pass
    return FALLBACK_ENDPOINTS

def find_working_api(session, endpoints):
    for url in endpoints:
        try:
            r = session.get(f"{url}/health", timeout=10)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                return url
        except:
            continue
    return None

def main():
    email = os.environ.get("DNFV_EMAIL")
    password = os.environ.get("DNFV_PASSWORD")
    download_dir = Path("./downloads")
    download_dir.mkdir(exist_ok=True)
    
    session = requests.Session()
    session.headers.update({"User-Agent": "DNFileVaultClient/1.0"})

    # 1. Discover & select API server
    endpoints = get_api_endpoints(session)
    base_url = find_working_api(session, endpoints)
    if not base_url:
        print("All API servers are down!")
        return
    print(f"Using API: {base_url}")

    # 2. Login
    resp = session.post(f"{base_url}/auth/login", json={"email": email, "password": password})
    token = resp.json()["token"]
    session.headers["Authorization"] = f"Bearer {token}"

    # 3. List & Download Groups
    groups = session.get(f"{base_url}/groups").json()["groups"]
    for g in groups:
        group_dir = download_dir / g["name"]
        group_dir.mkdir(exist_ok=True)
        
        files = session.get(f"{base_url}/groups/{g['id']}/files").json()["files"]
        for f in files:
            output_path = group_dir / f["display_name"]
            
            # PRIMARY: Try cloud_share_link first (FAST!)
            try:
                if f.get("cloud_share_link"):
                    print(f"Downloading {f['display_name']} via R2...")
                    with requests.get(f["cloud_share_link"], timeout=30, stream=True) as r:
                        r.raise_for_status()
                        with open(output_path, "wb") as fd:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                fd.write(chunk)
                    print(f"  ✓ Complete (R2)")
                    continue
            except Exception as e:
                print(f"  R2 failed: {e}, trying API fallback...")
            
            # FALLBACK: Use API server route
            try:
                print(f"Downloading {f['display_name']} via API...")
                with session.get(f"{base_url}/download/{f['uuid_filename']}", timeout=60, stream=True) as r:
                    r.raise_for_status()
                    with open(output_path, "wb") as fd:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            fd.write(chunk)
                print(f"  ✓ Complete (API)")
            except Exception as e:
                print(f"  ✗ Failed: {e}")

if __name__ == "__main__":
    main()
```

### C# Template (.NET 6+ Sync)
Use this for robust daily automation. It tracks state to skip files that haven't changed.
1.  **Login** to get JWT.
2.  **Compare** API file list vs. local `.dnfv_state.json`.
3.  **Download** only if new, missing, or size/checksum changed.

---

## 6. Daily Sync Variants

### Last 7 Days (Python/C#)
If you only need recent data:
1.  Set `DNFV_DAYS = 7`.
2.  The script calculates a cutoff (`DateTime.Now - 7 days`).
3.  Filters the file list to only download items where `created_at >= cutoff`.

### Linux/Headless Servers
Use the `download_groups_linux.py` variant. It ignores personal "Purchases" and focuses solely on "Groups," making it ideal for cron jobs on data servers.

---

## Troubleshooting Summary

### Connection & Discovery Issues
*   **All API servers unreachable**: Check your internet connection. If `config.dnfilevault.com` loads but no APIs respond, all servers may be down — contact support.
*   **Discovery URL fails**: The script will fall back to hardcoded endpoints automatically. If this happens often, check if your firewall blocks `config.dnfilevault.com`.
*   **Wrong server selected**: Endpoints are tried in priority order. If you need a specific server, you can still hardcode `BASE_URL` temporarily for debugging.

### Download Issues
*   **Slow Downloads**: Make sure you're using `cloud_share_link` (R2), not `/download/{uuid}` (API server).
*   **R2 Link Blocked**: Your corporate firewall may block `vault.dnfilevault.com`. Use API fallback method.
*   **404 Not Found**: You likely used a Display Name instead of a UUID. List files first to get proper links.

### Authentication Issues
*   **401 Unauthorized**: Missing or expired Bearer Token. (Note: R2 links don't need auth!)
*   **403 Access Denied**: File is not in your authorized groups.

### Performance Issues
*   **Slow API**: Ensure you have set a custom User-Agent header.
*   **Want Maximum Speed?**: Use `cloud_share_link` for direct CDN downloads.

### Corporate Firewall Users
If `vault.dnfilevault.com` is blocked by your firewall:
1. Set a flag in your profile: "Behind Corporate Firewall"
2. Your code should check this and use `/download/{uuid}` method instead
3. This routes through the API server which is usually allowed