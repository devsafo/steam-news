"""
Database module for storing posted Steam games to prevent duplicate posts.
Uses PostgreSQL for persistent storage across Render redeploys.
"""

import os
import logging
from datetime import datetime
from typing import Any
import psycopg2
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)

# Neon.tech or other PostgreSQL connection string
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    """Returns a PostgreSQL connection."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL topilmadi. .env faylini yoki server sozlamalarini tekshiring!")
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)


def init_db() -> None:
    """Initializes the database schema if it doesn't already exist."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
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
            logger.info("PostgreSQL bazasi muvaffaqiyatli ulandi va tekshirildi.")
    except Exception as e:
        logger.error(f"PostgreSQL bazasini yaratishda xatolik: {e}")


def is_game_posted(app_id: int) -> bool:
    """Checks if a game with the given app_id has already been posted."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM posted_games WHERE app_id = %s", (app_id,))
                return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"PostgreSQL o'qishda xatolik: {e}")
        return False


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
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO posted_games (
                        app_id, name, discount_percent, original_price,
                        final_price, currency, posted_at, expiration_timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(app_id) DO UPDATE SET
                        discount_percent = EXCLUDED.discount_percent,
                        original_price = EXCLUDED.original_price,
                        final_price = EXCLUDED.final_price,
                        currency = EXCLUDED.currency,
                        posted_at = EXCLUDED.posted_at,
                        expiration_timestamp = EXCLUDED.expiration_timestamp
                """, (
                    app_id, name, discount_percent, original_price,
                    final_price, currency, now_str, expiration_timestamp
                ))
            conn.commit()
    except Exception as e:
        logger.error(f"PostgreSQL ga yozishda xatolik: {e}")


def get_posted_count() -> int:
    """Returns the total number of posted games stored in the database."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM posted_games")
                row = cursor.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


def get_recent_posted(limit: int = 10) -> list[dict[str, Any]]:
    """Returns the most recently posted games."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT app_id, name, discount_percent, original_price, final_price, currency, posted_at
                    FROM posted_games
                    ORDER BY posted_at DESC
                    LIMIT %s
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


if DATABASE_URL:
    init_db()
