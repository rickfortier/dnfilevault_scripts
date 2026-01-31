import os
import re
from datetime import datetime, timedelta, timezone

import requests


def safe_name(name: str) -> str:
    # Windows-safe filename
    return re.sub(r'[<>:"/\\|?*]', "_", (name or "")).strip() or "file"


def parse_created_at(value: str) -> datetime:
    """
    DNFileVault stores timestamps like: 'YYYY-MM-DD HH:MM:SS'

    Note: this is a naive timestamp in the DB. We treat it as UTC for filtering.
    """
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def download_stream(session: requests.Session, url: str, out_path: str) -> None:
    if os.path.exists(out_path):
        return

    tmp_path = out_path + ".part"
    with session.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(tmp_path, out_path)


def main() -> int:
    base_url = os.environ.get("DNFV_BASE_URL", "https://api.dnfilevault.com").rstrip("/")
    email = os.environ.get("DNFV_EMAIL")
    password = os.environ.get("DNFV_PASSWORD")
    group_name = os.environ.get("DNFV_GROUP_NAME", "eodLevel2")
    out_dir = os.environ.get("DNFV_OUT_DIR", r"C:\dnfilevault-downloads\eodLevel2-last7days")
    days = int(os.environ.get("DNFV_DAYS", "7"))

    if not email or not password:
        raise SystemExit("Set DNFV_EMAIL and DNFV_PASSWORD in your environment.")

    os.makedirs(out_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            # Recommended: the API intentionally slows requests that look like scanners.
            "User-Agent": "DNFileVaultEODLevel2Downloader/1.0",
        }
    )

    # Login
    login = session.post(
        f"{base_url}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    login.raise_for_status()
    token = login.json()["token"]
    session.headers.update({"Authorization": f"Bearer {token}"})

    # Find group
    groups_resp = session.get(f"{base_url}/groups", timeout=30)
    groups_resp.raise_for_status()
    groups = groups_resp.json().get("groups", [])

    group = next(
        (g for g in groups if str(g.get("name", "")).lower() == group_name.lower()),
        None,
    )
    if not group:
        names = ", ".join(sorted({str(g.get("name", "")) for g in groups if g.get("name")}))
        raise SystemExit(f"Group '{group_name}' not found. Available groups: {names}")

    group_id = group["id"]

    # List files in group
    files_resp = session.get(f"{base_url}/groups/{group_id}/files", timeout=30)
    files_resp.raise_for_status()
    files = files_resp.json().get("files", [])

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    recent = []
    for f in files:
        created_at = f.get("created_at")
        if not created_at:
            continue
        try:
            created_dt = parse_created_at(str(created_at))
        except Exception:
            # If we can’t parse, skip (keeps the script strict and predictable)
            continue
        if created_dt >= cutoff:
            recent.append((created_dt, f))

    recent.sort(key=lambda t: t[0])

    print(f"Group: {group.get('name')} (id={group_id})")
    print(f"Cutoff (UTC): {cutoff.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Downloading {len(recent)} file(s) to: {out_dir}")

    for created_dt, f in recent:
        display_name = safe_name(f.get("display_name") or f.get("uuid_filename"))
        uuid_filename = f["uuid_filename"]
        url = f"{base_url}/download/{uuid_filename}"
        out_path = os.path.join(out_dir, display_name)
        print(f"- {created_dt.strftime('%Y-%m-%d %H:%M:%S')}  {display_name}")
        download_stream(session, url, out_path)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
