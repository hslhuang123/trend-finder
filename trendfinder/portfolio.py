"""SQLite-backed paper portfolio: cash, positions, transactions, and daily snapshots.

All cash and P&L amounts are kept in a single base currency (USD). Each position
records its native currency and the FX rate at entry/exit so mixed US/CAD
portfolios stay correct.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config


@contextmanager
def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with _conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value REAL)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                entry_price REAL NOT NULL,
                shares REAL NOT NULL,
                entry_date TEXT NOT NULL,
                stop_loss_pct REAL,
                take_profit_pct REAL,
                trailing_stop_pct REAL,
                peak_price REAL,
                status TEXT NOT NULL DEFAULT 'open',
                exit_price REAL,
                exit_date TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER,
                type TEXT NOT NULL,
                ticker TEXT NOT NULL,
                price REAL NOT NULL,
                shares REAL NOT NULL,
                total REAL NOT NULL,
                timestamp TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS snapshots (
                date TEXT PRIMARY KEY,
                cash REAL NOT NULL,
                market_value REAL NOT NULL,
                total_value REAL NOT NULL,
                unrealized REAL,
                realized REAL
            )"""
        )
        # FX migration: older DBs lack these columns.
        _ensure_columns(conn, "positions", {
            "currency": "currency TEXT",
            "entry_fx": "entry_fx REAL",
            "exit_fx": "exit_fx REAL",
        })
        conn.execute("UPDATE positions SET currency='USD' WHERE currency IS NULL")
        conn.execute("UPDATE positions SET entry_fx=1.0 WHERE entry_fx IS NULL")

        if conn.execute("SELECT value FROM meta WHERE key='cash'").fetchone() is None:
            conn.execute("INSERT INTO meta (key, value) VALUES ('cash', ?)", (config.INITIAL_CASH,))


def _set_cash(conn, amount: float) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('cash', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (amount,),
    )


def get_cash() -> float:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='cash'").fetchone()
    return float(row["value"]) if row else config.INITIAL_CASH


def buy(ticker: str, price: float, shares: float,
        currency: str = "USD", entry_fx: float = 1.0,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        trailing_stop_pct: float | None = None) -> int:
    """Open a long position. `price` is in the position's native currency;
    cash is debited in the base currency (USD) using `entry_fx`."""
    ticker = ticker.upper().strip()
    currency = (currency or "USD").upper()
    entry_fx = float(entry_fx or 1.0)

    if shares <= 0:
        raise ValueError("shares must be positive")
    if price <= 0:
        raise ValueError("price must be positive")

    cost_base = price * shares * entry_fx
    now = datetime.now().isoformat(timespec="seconds")

    with _conn() as conn:
        cash = float(conn.execute("SELECT value FROM meta WHERE key='cash'").fetchone()["value"])
        if cost_base > cash + 1e-9:
            raise ValueError(f"Not enough cash (need ${cost_base:,.2f}, have ${cash:,.2f})")

        cur = conn.execute(
            "INSERT INTO positions (ticker, entry_price, shares, entry_date, stop_loss_pct, "
            "take_profit_pct, trailing_stop_pct, peak_price, status, currency, entry_fx) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (ticker, price, shares, now, stop_loss_pct, take_profit_pct,
             trailing_stop_pct, price, currency, entry_fx),
        )
        position_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO transactions (position_id, type, ticker, price, shares, total, timestamp) "
            "VALUES (?, 'buy', ?, ?, ?, ?, ?)",
            (position_id, ticker, price, shares, cost_base, now),
        )
        _set_cash(conn, cash - cost_base)
    return position_id


def sell(position_id: int, price: float, exit_fx: float = 1.0) -> float:
    """Close a position. Returns proceeds in the base currency (USD)."""
    exit_fx = float(exit_fx or 1.0)
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='open'", (position_id,)
        ).fetchone()
        if row is None:
            raise ValueError("position not found or already closed")

        shares = float(row["shares"])
        proceeds_base = price * shares * exit_fx
        conn.execute(
            "UPDATE positions SET status='closed', exit_price=?, exit_fx=?, exit_date=? WHERE id=?",
            (price, exit_fx, now, position_id),
        )
        conn.execute(
            "INSERT INTO transactions (position_id, type, ticker, price, shares, total, timestamp) "
            "VALUES (?, 'sell', ?, ?, ?, ?, ?)",
            (position_id, row["ticker"], price, shares, proceeds_base, now),
        )
        cash = float(conn.execute("SELECT value FROM meta WHERE key='cash'").fetchone()["value"])
        _set_cash(conn, cash + proceeds_base)
    return proceeds_base


def update_peak(position_id: int, price: float) -> None:
    """Raise the stored native peak price for trailing-stop tracking."""
    with _conn() as conn:
        row = conn.execute("SELECT peak_price FROM positions WHERE id=?", (position_id,)).fetchone()
        if row is None:
            return
        peak = row["peak_price"] or price
        if price > peak:
            conn.execute("UPDATE positions SET peak_price=? WHERE id=?", (price, position_id))


def get_position(position_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    return dict(row) if row else None


def get_open_positions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='open' ORDER BY entry_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_closed_positions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status='closed' ORDER BY exit_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_snapshot(day: str, cash: float, market_value: float, total_value: float,
                    unrealized: float, realized: float) -> None:
    """Record (or overwrite) the portfolio value for a given day."""
    with _conn() as conn:
        conn.execute(
            """INSERT INTO snapshots (date, cash, market_value, total_value, unrealized, realized)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 cash=excluded.cash, market_value=excluded.market_value,
                 total_value=excluded.total_value, unrealized=excluded.unrealized,
                 realized=excluded.realized""",
            (day, cash, market_value, total_value, unrealized, realized),
        )


def get_snapshots() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM snapshots ORDER BY date").fetchall()
    return [dict(r) for r in rows]


def reset() -> None:
    """Wipe the paper account back to its starting cash."""
    with _conn() as conn:
        conn.execute("DELETE FROM positions")
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM snapshots")
        _set_cash(conn, config.INITIAL_CASH)
