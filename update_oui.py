#!/usr/bin/env python3
"""
update_oui.py
Downloads the official IEEE OUI registry and stores it as a SQLite table.
Run this once to populate, and again periodically to refresh.
"""

import sqlite3
import os
import sys
import urllib.request

OUI_URL = "https://standards-oui.ieee.org/oui/oui.txt"
# Keep in sync with server/database.py DATA_DIR.
DB_PATH = os.environ.get("NODESENTRY_DATA_DIR") or os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_PATH, "nodesentry.db")


def download_oui(url: str) -> str:
    print(f"[*] Downloading OUI registry from {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NodeSentry/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8", errors="replace")
        print(f"[+] Downloaded {len(data):,} bytes")
        return data
    except Exception as e:
        print(f"[!] Failed to download OUI file: {e}")
        sys.exit(1)


def parse_oui(raw: str) -> list[tuple[str, str]]:
    """
    Parse lines like:
      A0-B1-C2   (hex)    Apple, Inc.
    Returns list of (prefix, vendor) e.g. ("A0:B1:C2", "Apple, Inc.")
    """
    entries = []
    for line in raw.splitlines():
        if "(hex)" not in line:
            continue
        parts = line.split("(hex)")
        if len(parts) != 2:
            continue
        prefix = parts[0].strip().replace("-", ":").upper()
        vendor = parts[1].strip()
        if prefix and vendor:
            entries.append((prefix, vendor))
    return entries


def store_oui(entries: list[tuple[str, str]], db_path: str):
    print(f"[*] Storing {len(entries):,} entries to {db_path} ...")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oui (
            prefix  TEXT PRIMARY KEY,
            vendor  TEXT NOT NULL
        )
    """)
    conn.execute("DELETE FROM oui")
    conn.executemany("INSERT OR REPLACE INTO oui (prefix, vendor) VALUES (?, ?)", entries)
    conn.commit()
    conn.close()
    print(f"[+] Done. {len(entries):,} OUI entries stored.")


def lookup(mac: str, db_path: str) -> str | None:
    prefix = mac.upper()[:8]
    conn   = sqlite3.connect(db_path)
    row    = conn.execute("SELECT vendor FROM oui WHERE prefix = ?", (prefix,)).fetchone()
    conn.close()
    return row[0] if row else None


if __name__ == "__main__":
    raw     = download_oui(OUI_URL)
    entries = parse_oui(raw)
    print(f"[+] Parsed {len(entries):,} entries")
    store_oui(entries, DB_PATH)

    # Quick sanity check
    test_macs = [
        ("AC:BC:32:00:00:00", "should be Apple"),
        ("24:0A:C4:00:00:00", "should be Espressif"),
        ("B8:27:EB:00:00:00", "should be Raspberry Pi"),
    ]
    print("\n[*] Sanity check:")
    for mac, hint in test_macs:
        vendor = lookup(mac, DB_PATH)
        print(f"    {mac} -> {vendor or 'NOT FOUND'} ({hint})")