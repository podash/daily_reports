import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from config import DB_CONFIG

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    """Context manager for PostgreSQL connection."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        yield conn
    except psycopg2.OperationalError as e:
        logger.error("DB connection failed: %s", e)
        raise
    finally:
        if conn is not None:
            conn.close()


def execute_query(sql, params=None):
    """Execute a read-only query and return rows as list of dicts."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def execute_scalar(sql, params=None):
    """Execute a query and return a single scalar value."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None
