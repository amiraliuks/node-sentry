#!/usr/bin/env python3
"""
backfill_devices.py
Populates the devices table from existing alerts in the database.
Run once after upgrading to a version that includes device tracking.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))

from database import init_db, init_devices_table, upsert_device, get_conn

def backfill():
    init_db()
    init_devices_table()

    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM alerts ORDER BY timestamp ASC").fetchall()

    total = len(rows)
    print(f"[*] Found {total} alerts to backfill...")

    for i, row in enumerate(rows):
        alert = dict(row)
        upsert_device(alert)
        if (i + 1) % 100 == 0 or (i + 1) == total:
            print(f"[*] Processed {i + 1}/{total}")

    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]

    print(f"[+] Done. {count} unique devices tracked.")

if __name__ == "__main__":
    backfill()