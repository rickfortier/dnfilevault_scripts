# DNFileVault Client Scripts

Official Python client scripts for downloading and syncing data from [dnfilevault.com](https://dnfilevault.com).

## 🚀 What This Does

These scripts automatically download and sync your purchased data files (EOD market data, options data, etc.) from DNFileVault to your local machine using a simple "Login → List → Download" pattern.

**Key Features:**
- ✅ Downloads from **Cloudflare R2 CDN** (fast, worldwide)
- ✅ Automatic fallback to API server if needed
- ✅ Skips files that already exist locally
- ✅ Validates file integrity with checksums
- ✅ Smart sync - only downloads new/changed files
- ✅ Works on Windows, Linux, and Mac

## 📋 Requirements

- **Python 3.8 or higher**
- **requests** library (`pip install requests`)
- Valid DNFileVault account credentials
- Internet connection

## ⚡ Quick Start

### 1. Download Scripts

**Windows:**
```bash
curl -o download_all_windows.py https://www.dropbox.com/scl/fi/i7hpjwrthv0r2y6nku1m4/download_all_windows_Jan31.py?rlkey=x2tfxioiszqrq7v84rxhfq2ep&dl=1
```

**Linux/Mac:**
```bash
wget -O download_all_linux.py https://www.dropbox.com/scl/fi/cz7omtygrmbw551jp3xhe/download_all_linux_Jan31.py?rlkey=38tqg7w3695r5rkpknoznfv4v&dl=1
```

Or download manually from the [Automation page](https://dnfilevault.com/automation).

### 2. Install Dependencies

```bash
pip install requests
```

### 3. Configure Credentials (Environment Variables)

**Windows (PowerShell):**
```powershell
$env:DNFV_EMAIL = "your-email@example.com"
$env:DNFV_PASSWORD = "your-password"
```

**Linux/Mac (Bash):**
```bash
export DNFV_EMAIL="your-email@example.com"
export DNFV_PASSWORD="your-password"
```

**Optional - Make it permanent:**

Windows: Add to your PowerShell profile  
Linux/Mac: Add to `~/.bashrc` or `~/.zshrc`

### 4. Run

**Windows:**
```bash
python download_all_windows.py
```

**Linux/Mac:**
```bash
python download_all_linux.py
```

## 📖 How It Works

### Two Download Methods

DNFileVault provides two ways to download files:

#### Method 1: Cloudflare R2 CDN (Primary - Fast 🚀)
- Downloads directly from Cloudflare's global CDN
- No authentication required (pre-signed URLs)
- Much faster than API downloads
- Best for bulk operations
- Works worldwide with edge servers

#### Method 2: API Server Route (Fallback)
- Routes through DNFileVault API server
- Requires JWT authentication
- Use this if behind corporate firewall
- Server logs all downloads

**Scripts automatically try R2 first, then fall back to API if needed.**

### The Download Process

```
1. Login         → Get JWT token
2. List Groups   → Get your data groups (eodLevel2, eodLevel3, etc.)
3. List Files    → Get files in each group with cloud_share_link
4. Download      → Download via R2 (fast) or API (fallback)
5. Verify        → Check file size/checksum
6. Skip          → Don't re-download existing files
```

## 🔧 Configuration Options

### Default Download Location

**Windows:** `C:\dnfilevault-downloads\`  
**Linux/Mac:** `~/dnfilevault-downloads/`

Files are organized by group:
```
dnfilevault-downloads/
├── eodLevel2/
│   ├── L2_20260131.zip
│   └── L2_20260130.zip
├── eodLevel3/
│   ├── L3_20260131.zip
│   └── L3_20260130.zip
└── Following_RF/
    └── following_RF_20260131.zip
```

### Customize Download Location

Edit the script and change the `DOWNLOAD_DIR` variable:

```python
# For Windows
DOWNLOAD_DIR = r"D:\my-data\dnfilevault"

# For Linux/Mac
DOWNLOAD_DIR = "/data/dnfilevault"
```

### Filter by Date Range

Only download files from the last N days:

```python
# In the script, uncomment and set:
DAYS_BACK = 7  # Only download files from last 7 days
```

## 📚 Documentation

### Complete API Guide
Download the comprehensive guide:  
[DNFILEVAULT_MASTER_GUIDE.md](https://www.dropbox.com/scl/fi/i78n4tbnv63101vexbi2f/DNFILEVAULT_MASTER_GUIDE.md?rlkey=lb25wxjsc0f70nd4s1sslnkmk&dl=1)

**Includes:**
- Two download methods explained
- Authentication patterns
- Code examples (Python, C#, Java)
- Troubleshooting guide
- Corporate firewall handling
- Daily sync strategies

### API Reference
Interactive API documentation:  
[api.dnfilevault.com/docs](https://api.dnfilevault.com/docs)

## 🏢 Corporate Firewall Users

If `vault.dnfilevault.com` is blocked by your corporate firewall:

1. Log into [dnfilevault.com](https://dnfilevault.com)
2. Go to Profile → Check "Behind Corporate Firewall"
3. Scripts will automatically use API server route instead of R2

Or manually force API downloads by editing the script:
```python
USE_R2_LINKS = False  # Force API downloads
```

## 🔐 Security Best Practices

### ✅ DO:
- Use environment variables for credentials
- Use a unique User-Agent header
- Keep your scripts updated
- Verify checksums

### ❌ DON'T:
- Hardcode credentials in scripts
- Commit credentials to git
- Use default/blank User-Agent
- Run scripts from untrusted sources

## 🐛 Troubleshooting

### "401 Unauthorized"
- Check your email/password environment variables
- Ensure no typos in credentials
- Try logging into website to verify credentials

### "Slow Downloads"
- Make sure you're using R2 links (not API fallback)
- Check your User-Agent is set properly
- Try increasing timeout values

### "Connection Timeout"
- Increase timeout in script (default: 300 seconds)
- Check your internet connection
- Try again later (server may be overloaded)

### "Files Not Downloading"
- Check you have access to the group
- Verify file permissions on download directory
- Check disk space

### Anti-Scanner Protection
DNFileVault intentionally slows requests that look bot-like. **Always set a custom User-Agent:**

```python
headers = {
    "User-Agent": "DNFileVaultClient/1.0 (+your-email@example.com)"
}
```

## 📞 Support

- **Website:** [dnfilevault.com](https://dnfilevault.com)
- **Automation Page:** [dnfilevault.com/automation](https://dnfilevault.com/automation)
- **Email:** support@deltaneutral.com
- **Issues:** Report bugs via email

## 🎯 Use Cases

### Daily Automated Sync
Set up a cron job (Linux) or Task Scheduler (Windows) to run daily:

**Linux cron example:**
```bash
# Download at 6 PM daily
0 18 * * * cd /home/user/scripts && /usr/bin/python3 download_all_linux.py >> /var/log/dnfilevault.log 2>&1
```

**Windows Task Scheduler:**
1. Open Task Scheduler
2. Create Basic Task
3. Trigger: Daily at 6:00 PM
4. Action: Start program → `python.exe`
5. Arguments: `C:\path\to\download_all_windows.py`

### Integration with Trading Systems
Replace FTP/API calls in your legacy code with simple file copy:

**Before (Old FTP method):**
```csharp
// Bad - embedded FTP in every project
FtpDownload("L2_20260131.zip", localPath);
```

**After (Simple file copy):**
```csharp
// Good - just copy from sync folder
string syncPath = @"C:\dnfilevault-downloads\eodLevel2\L2_20260131.zip";
if (File.Exists(syncPath)) {
    ProcessFile(syncPath);  // Instant!
}
```

Let the Python script handle downloads in the background.

## 🔄 Upgrade from Old Scripts

If you're using older scripts (pre-January 2026):

1. **Download new versions** (Jan 31 or later)
2. **Change:** Scripts now use R2 cloud links by default
3. **Faster:** 3-10x speed improvement on downloads
4. **Same usage:** Environment variables still work the same

## 📊 Advanced Features

### Parallel Downloads
For maximum speed with R2 links:

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=5) as executor:
    executor.map(download_file, files)
```

### Checksum Verification
Scripts automatically verify file integrity:

```python
if file_checksum != api_checksum:
    print("⚠ Warning: Checksum mismatch, re-downloading...")
```

### State Tracking
Track downloaded files to avoid re-downloading:

```python
# Script maintains .download_state.json
# Skips files that haven't changed
```

## 📄 License

MIT License - These scripts are provided as-is for DNFileVault users.

---

## 🆘 Quick Help

**Problem:** Can't login  
**Solution:** Check environment variables are set: `echo $DNFV_EMAIL`

**Problem:** Downloads are slow  
**Solution:** Ensure R2 links are being used (check script output)

**Problem:** Files not showing up  
**Solution:** Check you have access to that group on the website

**Problem:** Script crashes  
**Solution:** Update Python and requests library: `pip install --upgrade requests`

---

**Made with ❤️ for DNFileVault users**  
**Last Updated:** January 31, 2026
