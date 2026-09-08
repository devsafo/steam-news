"""
Database module for storing posted Steam games to prevent duplicate posts.
Uses SQLite for persistent, lightweight storage.
"""

import sqlite3
from datetime import datetime
from typing import Any
from config import DATABASE_PATH


def get_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initializes the database schema if it doesn't already exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posted_games (
                app_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                discount_percent INTEGER NOT NULL,
                original_price REAL,
                final_price REAL,
                currency TEXT,
                posted_at TEXT NOT NULL,
                expiration_timestamp INTEGER
            )
        """)
        conn.commit()


def is_game_posted(app_id: int) -> bool:
    """Checks if a game with the given app_id has already been posted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM posted_games WHERE app_id = ?", (app_id,))
        return cursor.fetchone() is not None


def mark_game_posted(
    app_id: int,
    name: str,
    discount_percent: int,
    original_price: float,
    final_price: float,
    currency: str,
    expiration_timestamp: int | None = None
) -> None:
    """Records a game as posted in the database."""
    now_str = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO posted_games (
                app_id, name, discount_percent, original_price,
                final_price, currency, posted_at, expiration_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(app_id) DO UPDATE SET
                discount_percent = excluded.discount_percent,
                original_price = excluded.original_price,
                final_price = excluded.final_price,
                currency = excluded.currency,
                posted_at = excluded.posted_at,
                expiration_timestamp = excluded.expiration_timestamp
        """, (
            app_id, name, discount_percent, original_price,
            final_price, currency, now_str, expiration_timestamp
        ))
        conn.commit()


def get_posted_count() -> int:
    """Returns the total number of posted games stored in the database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM posted_games")
        row = cursor.fetchone()
        return row[0] if row else 0


def get_recent_posted(limit: int = 10) -> list[dict[str, Any]]:
    """Returns the most recently posted games."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT app_id, name, discount_percent, original_price, final_price, currency, posted_at
            FROM posted_games
            ORDER BY posted_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


# Automatically initialize DB on import
init_db()
