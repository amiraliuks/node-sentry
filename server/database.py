import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "nodesentry.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                node      TEXT NOT NULL,
                type      TEXT NOT NULL,
                mac       TEXT,
                ssid      TEXT,
                rssi      INTEGER,
                extra     TEXT,
                timestamp INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                node            TEXT NOT NULL,
                uptime          INTEGER,
                packets_seen    INTEGER,
                alerts_sent     INTEGER,
                free_heap       INTEGER,
                rssi_to_broker  INTEGER,
                timestamp       INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type      ON alerts(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_node      ON alerts(node)")
        conn.commit()
    print("[DB] Database initialized.")


def insert_alert(payload: dict):
    known = {"node", "type", "mac", "ssid", "rssi", "timestamp"}
    extra = {k: v for k, v in payload.items() if k not in known}
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO alerts (node, type, mac, ssid, rssi, extra, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.get("node"),
            payload.get("type"),
            payload.get("mac"),
            payload.get("ssid"),
            payload.get("rssi"),
            json.dumps(extra) if extra else None,
            payload.get("timestamp"),
        ))
        conn.commit()


def insert_stats(payload: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO stats (node, uptime, packets_seen, alerts_sent, free_heap, rssi_to_broker, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.get("node"),
            payload.get("uptime"),
            payload.get("packets_seen"),
            payload.get("alerts_sent"),
            payload.get("free_heap"),
            payload.get("rssi_to_broker"),
            payload.get("timestamp", 0),
        ))
        conn.commit()


def get_alerts(limit=200, alert_type=None, node=None):
    query = "SELECT * FROM alerts"
    filters = []
    params = []
    if alert_type:
        filters.append("type = ?")
        params.append(alert_type)
    if node:
        filters.append("node = ?")
        params.append(node)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_counts():
    with get_conn() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        by_type = conn.execute(
            "SELECT type, COUNT(*) as count FROM alerts GROUP BY type"
        ).fetchall()
    counts = {"total": total}
    for row in by_type:
        counts[row["type"]] = row["count"]
    return counts


def get_nodes():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.*
            FROM stats s
            INNER JOIN (
                SELECT node, MAX(timestamp) as latest
                FROM stats
                GROUP BY node
            ) latest ON s.node = latest.node AND s.timestamp = latest.latest
        """).fetchall()
    return [dict(r) for r in rows]