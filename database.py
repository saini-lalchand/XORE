"""
database.py — XORE Pure Android SQLite persistence layer.

EXISTING FEATURES (unchanged):
  C1 — _write_lock serialises all INSERT/DDL operations.
  C2 — WAL journal mode + PRAGMA synchronous=NORMAL at startup.
  C3 — _db() context-manager owns the full connection lifecycle.
  C4 — Row factory → list[dict] instead of raw tuples.
  C5 — OrderRecord TypedDict replaces 13-positional-arg signature.

NEW IN THIS VERSION:
  D1 — Added optional `ram_gb` INTEGER column to the orders table.
       Stores the validated even-integer RAM value (or NULL if not provided).
  D2 — Added `partners` table for shop node registration.
  D3 — Added PartnerRecord TypedDict and save_partner() function.
"""

import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator, Optional
from typing_extensions import TypedDict


DB_PATH = "xore_data.db"

# C1 — one lock for the whole module; only write paths acquire it.
_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# OrderRecord — typed dict that replaces 13 positional args
# ---------------------------------------------------------------------------
class OrderRecord(TypedDict):
    order_id:        str
    user_id:         str
    device_id:       str
    client_name:     str
    mobile:          str
    address:         str
    device_model:    str
    android_version: Optional[str]
    ram_gb:          Optional[int]      # D1 — even integer or NULL
    imei:            Optional[str]      # 15-digit string or NULL
    payment_method:  str
    base_fee:        float
    xore_share:      float
    partner_shop_id: Optional[str]
    partner_share:   Optional[float]


# ---------------------------------------------------------------------------
# PartnerRecord — typed dict for partner shop nodes (NEW)
# ---------------------------------------------------------------------------
class PartnerRecord(TypedDict):
    partner_id:    str
    shop_name:     str
    owner_name:    str
    mobile:        str
    address:       str
    status:        str  # 'active' or 'pending'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    """
    Open a per-call SQLite connection.

    check_same_thread=False — required because FastAPI dispatches handlers
    on worker threads that differ from the thread that called connect().
    Safe here because every caller opens, uses, and closes its own connection
    inside a single function call; no connection object is shared across calls.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row          # C4
    return conn


@contextmanager
def _db(write: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """
    C3 — Context manager that owns the full connection lifecycle.
    Acquires _write_lock for write operations; rolls back on any exception.
    """
    if write:
        _write_lock.acquire()
    conn = _connect()
    try:
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()
        if write:
            _write_lock.release()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def init_db() -> None:
    """
    Called once at app startup.
    Creates the orders and partners tables, enables WAL mode.
    """
    with _db(write=True) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        # Orders table (existing)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id         TEXT UNIQUE NOT NULL,
                user_id          TEXT NOT NULL,
                device_id        TEXT NOT NULL,
                client_name      TEXT NOT NULL,
                mobile           TEXT NOT NULL,
                address          TEXT NOT NULL,
                device_model     TEXT NOT NULL,
                android_version  TEXT,
                ram_gb           INTEGER,          -- D1: even integer GB
                imei             TEXT,             -- D1: 15-digit string
                payment_method   TEXT NOT NULL,
                base_fee         REAL NOT NULL,
                partner_shop_id  TEXT,
                partner_share    REAL,
                xore_share       REAL NOT NULL,
                status           TEXT DEFAULT 'pending',
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ---- USERS TABLE (NEW) ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          TEXT UNIQUE NOT NULL,
                password_hash    TEXT NOT NULL,
                role             TEXT NOT NULL,   -- 'user', 'partner', or 'admin'
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Partners table (NEW)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS partners (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id       TEXT UNIQUE NOT NULL,
                shop_name        TEXT NOT NULL,
                owner_name       TEXT NOT NULL,
                mobile           TEXT NOT NULL,
                address          TEXT NOT NULL,
                status           TEXT DEFAULT 'pending',
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_partners_status ON partners(status);")


    print("✅ Database initialised (orders + partners tables created, WAL mode enabled).")


def save_order(record: OrderRecord) -> None:
    """
    C5 — Insert a new order row from a typed OrderRecord dict.
    Raises ValueError on duplicate order_id or any SQLite error.
    """
    try:
        with _db(write=True) as conn:
            conn.execute("""
                INSERT INTO orders (
                    order_id, user_id, device_id,
                    client_name, mobile, address,
                    device_model, android_version,
                    ram_gb, imei,
                    payment_method, base_fee,
                    partner_shop_id, partner_share, xore_share
                ) VALUES (
                    :order_id, :user_id, :device_id,
                    :client_name, :mobile, :address,
                    :device_model, :android_version,
                    :ram_gb, :imei,
                    :payment_method, :base_fee,
                    :partner_shop_id, :partner_share, :xore_share
                )
            """, record)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Duplicate order_id: {record['order_id']}") from e
    except sqlite3.Error as e:
        raise ValueError(f"Database error: {e}") from e


def save_partner(record: PartnerRecord) -> None:
    """
    Insert a new partner (shop node) record.
    Raises ValueError on duplicate partner_id or any SQLite error.
    """
    try:
        with _db(write=True) as conn:
            conn.execute("""
                INSERT INTO partners (
                    partner_id, shop_name, owner_name,
                    mobile, address, status
                ) VALUES (
                    :partner_id, :shop_name, :owner_name,
                    :mobile, :address, :status
                )
            """, record)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Duplicate partner_id: {record['partner_id']}") from e
    except sqlite3.Error as e:
        raise ValueError(f"Database error: {e}") from e


def get_all_orders() -> list[dict]:
    """
    Fetch all orders newest-first.
    Returns list[dict] (column name → value) instead of raw tuples (C4).
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]

def get_partner(partner_id: str) -> Optional[dict]:
    """Fetch a partner by partner_id."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM partners WHERE partner_id = ?", (partner_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_partners() -> list[dict]:
    """
    Fetch all partners (shop nodes) newest-first.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM partners ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_order(order_id: str) -> Optional[dict]:
    """Fetch a single order by its ID."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else None

def update_order_status(order_id: str, new_status: str) -> None:
    """Update the status of an order."""
    allowed = {"pending", "completed", "cancelled"}
    if new_status not in allowed:
        raise ValueError(f"Status must be one of: {allowed}")
    try:
        with _db(write=True) as conn:
            conn.execute("""
                UPDATE orders
                SET status = ?
                WHERE order_id = ?
            """, (new_status, order_id))
    except sqlite3.Error as e:
        raise ValueError(f"Database error: {e}") from e

def update_partner_status(partner_id: str, new_status: str) -> None:
    """Update the status of a partner."""
    allowed = {"active", "inactive"}
    if new_status not in allowed:
        raise ValueError(f"Status must be one of: {allowed}")
    try:
        with _db(write=True) as conn:
            conn.execute("""
                UPDATE partners
                SET status = ?
                WHERE partner_id = ?
            """, (new_status, partner_id))
    except sqlite3.Error as e:
        raise ValueError(f"Database error: {e}") from e
    

def save_user(user_id: str, password_hash: str, role: str) -> None:
    """Save a new user/partner login credentials."""
    try:
        with _db(write=True) as conn:
            conn.execute("""
                INSERT INTO users (user_id, password_hash, role)
                VALUES (?, ?, ?)
            """, (user_id, password_hash, role))
    except sqlite3.IntegrityError as e:
        raise ValueError(f"User ID '{user_id}' already exists") from e
    except sqlite3.Error as e:
        raise ValueError(f"Database error: {e}") from e

def get_user(user_id: str) -> Optional[dict]:
    """Fetch a user by user_id."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


if __name__ == "__main__":
    init_db()
    print("Database 'xore_data.db' initialised successfully!")