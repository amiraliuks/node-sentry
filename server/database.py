import sqlite3
import json
import os
from contextlib import contextmanager
from threading import local

DB_PATH = os.path.join(os.path.dirname(__file__), "nodesentry.db")

# Thread-local connection pool
_local = local()

def _get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA cache_size=1000")
    return _local.conn

@contextmanager
def get_conn():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# Init
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
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                node           TEXT NOT NULL,
                uptime         INTEGER,
                packets_seen   INTEGER,
                alerts_sent    INTEGER,
                free_heap      INTEGER,
                rssi_to_broker INTEGER,
                timestamp      INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_type      ON alerts(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_node      ON alerts(node)")
    print("[DB] Database initialized.")


# Validation
VALID_TYPES = {"deauth", "probe", "evil_twin", "karma"}
MAX_LIMIT   = 500

def _validate_limit(limit: int) -> int:
    if not isinstance(limit, int) or limit < 1:
        return 50
    return min(limit, MAX_LIMIT)

def _validate_type(alert_type: str | None) -> str | None:
    if alert_type and alert_type not in VALID_TYPES:
        return None
    return alert_type

def _validate_node(node: str | None) -> str | None:
    if node and (len(node) > 32 or not node.replace("-", "").replace("_", "").isalnum()):
        return None
    return node


# Writes
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


# Reads
def get_alerts(limit=50, page=1, alert_type=None, node=None):
    limit      = _validate_limit(limit)
    page       = max(1, page)
    alert_type = _validate_type(alert_type)
    node       = _validate_node(node)
    offset     = (page - 1) * limit

    query   = "SELECT * FROM alerts"
    count_q = "SELECT COUNT(*) FROM alerts"
    filters = []
    params  = []

    if alert_type:
        filters.append("type = ?")
        params.append(alert_type)
    if node:
        filters.append("node = ?")
        params.append(node)
    if filters:
        where   = " WHERE " + " AND ".join(filters)
        query   += where
        count_q += where

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"

    with get_conn() as conn:
        total = conn.execute(count_q, params).fetchone()[0]
        rows  = conn.execute(query, params + [limit, offset]).fetchall()

    return {
        "page":       page,
        "limit":      limit,
        "total":      total,
        "total_pages": max(1, -(-total // limit)),  # ceiling division
        "alerts":     [dict(r) for r in rows],
    }

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


# OUI Lookup
def get_vendor(mac: str) -> str | None:
    """Look up MAC vendor from the OUI table. Returns None if not found."""
    if not mac or len(mac) < 8:
        return None
    prefix = mac.upper()[:8]
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT vendor FROM oui WHERE prefix = ?", (prefix,)
            ).fetchone()
        return row["vendor"] if row else None
    except Exception:
        return None