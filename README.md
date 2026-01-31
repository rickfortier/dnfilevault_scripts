# DNFileVault Client Scripts

Official client scripts for downloading and syncing data from [dnfilevault.com](https://dnfilevault.com).

## What This Does

These scripts allow you to automatically download and sync your purchased data files from DNFileVault to your local machine.

## Requirements

- Python 3.8 or higher
- Internet connection
- Valid DNFileVault account credentials

## Quick Start

### 1. Install
```bash
git clone https://github.com/rickfortier/dnfilevault_scripts.git
cd dnfilevault_scripts
pip install -r requirements.txt
```

### 2. Configure
```bash
cp config.example.ini config.ini
# Edit config.ini with your credentials
```

### 3. Run
```bash
python sync_client.py
```

## Configuration

Edit `config.ini` with your DNFileVault credentials:
```ini
[server]
hostname = dnfilevault.com
port = 22

[auth]
username = your_username
api_key = your_api_key

[local]
sync_folder = /path/to/local/data
```

## Getting Your API Key

1. Log in to [dnfilevault.com](https://dnfilevault.com)
2. Go to Account Settings
3. Generate a new API key under "API Access"

## Support

- **Documentation:** [docs.dnfilevault.com](https://docs.dnfilevault.com)
- **Email:** support@dnfilevault.com
- **Issues:** [GitHub Issues](https://github.com/rickfortier/dnfilevault_scripts/issues)

## License

MIT License - see [LICENSE](LICENSE) file for details.
