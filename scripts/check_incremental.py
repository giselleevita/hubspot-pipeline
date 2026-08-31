"""Fail if warehouse keys duplicate; summarize the latest two pipeline runs."""
import json
import os

import psycopg


with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
    cur.execute("""
        select status, object_counts, started_at from pipeline_runs
        order by started_at desc limit 2
    """)
    runs = cur.fetchall()
    for object_type in ("contacts", "companies", "deals"):
        cur.execute(f"select count(*), count(distinct object_id) from raw.{object_type}")
        total, distinct_total = cur.fetchone()
        if total != distinct_total:
            raise SystemExit(f"duplicate natural keys in raw.{object_type}")
    print(json.dumps([{"status": row[0], "counts": row[1], "started_at": row[2].isoformat()} for row in runs], indent=2))
