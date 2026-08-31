from __future__ import annotations

from datetime import datetime, timezone


def ensure_metadata(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_state (
                object_type text PRIMARY KEY,
                watermark timestamptz NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id uuid PRIMARY KEY, started_at timestamptz NOT NULL,
                ended_at timestamptz, status text NOT NULL,
                object_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
                error_message text
            )
        """)
    conn.commit()


def get_watermark(conn, object_type: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT watermark FROM pipeline_state WHERE object_type = %s", (object_type,))
        row = cur.fetchone()
    return row[0] if row else None


def set_watermark(conn, object_type: str, watermark: datetime) -> None:
    if watermark.tzinfo is None:
        watermark = watermark.replace(tzinfo=timezone.utc)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO pipeline_state (object_type, watermark) VALUES (%s, %s)
            ON CONFLICT (object_type) DO UPDATE SET watermark = EXCLUDED.watermark
        """, (object_type, watermark))
