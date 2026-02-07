<<<<<<< HEAD
# DNFileVault Scripts

A collection of client-side scripts to interact with the [DNFileVault API](https://api.dnfilevault.com). These scripts are designed to help users download their purchases and group files efficiently.

## Features
- **Auto-Discovery & Failover**: On startup, scripts fetch the current list of API servers from `config.dnfilevault.com/endpoints.json` and automatically connect to the first healthy one. If a server is down, the next is tried — no manual configuration needed. When servers are added or moved, only the central config is updated; existing scripts pick up the change on next run.
- **Auto-Fallback Downloading**: Tries direct Cloudflare R2 links first (fastest) and falls back to the API server if needed.
- **Progress Tracking**: Real-time display of download progress and speed in **MB/s**.
- **Cross-Platform**: Optimized versions for **Windows**, **Linux**, **macOS**, **R**, **VB.NET**, and **Java**.
- **Anti-Throttling**: Custom User-Agent and timeout management to ensure smooth downloads.

## Available Scripts

### Python
| Script | Platform | Notes |
|--------|----------|-------|
| `dnfilevault_downloader.py` | Windows | `input()` pauses so the window stays open |
| `dnfilevault_downloader_linux.py` | Linux | Timestamped logging, cron-friendly, `sys.exit()` codes |
| `dnfilevault_downloader_mac.py` | macOS | Native Notification Center alerts, launchd-ready |

**Setup:** `pip install requests`

### R
| Script | Notes |
|--------|-------|
| `dnfilevault_downloader.R` | Uses `httr` + `jsonlite`. Run via `source()` or `Rscript` |

**Setup:** `install.packages(c("httr", "jsonlite"))`

### VB.NET
| Script | Notes |
|--------|-------|
| `dnfilevault_downloader.vb` | .NET 6+, requires Newtonsoft.Json |

**Setup:** `dotnet add package Newtonsoft.Json`

### Java
| Script | Notes |
|--------|-------|
| `DNFileVaultDownloader.java` | Java 11+, zero external dependencies |

**Setup:** `javac DNFileVaultDownloader.java && java DNFileVaultDownloader`

## How to Use
1. **Install** your language runtime (Python 3, R, .NET 6+, or Java 11+).
2. **Install dependencies** if required (see table above).
3. **Configure** your `EMAIL` and `PASSWORD` in the script, or set environment variables:
```bash
   export DNFV_EMAIL="your_email@example.com"
   export DNFV_PASSWORD="your_password"
```
4. **Run** the script. It will automatically discover the best API server and begin downloading.

## Documentation
- [Developer Guide](markdowns/DNFileVault_Developer_Guide.md): Discovery, failover, download methods, and code templates.
- [API Reference](API_REFERENCE.html): Technical documentation for the API endpoints.

## License
MIT License - feel free to use and modify for your own needs.
=======

>>>>>>> e317b6690bfb4aa9c48cc0f66dafe79071e38164
