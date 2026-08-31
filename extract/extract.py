from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import psycopg

from extract.client import HubSpotClient
from extract.state import ensure_metadata, get_watermark, set_watermark

OBJECTS = {
    "contacts": ["email", "firstname", "lastname", "createdate", "hs_lastmodifieddate"],
    "companies": ["name", "domain", "industry", "createdate", "hs_lastmodifieddate"],
    "deals": ["dealname", "amount", "dealstage", "createdate", "closedate", "hs_lastmodifieddate"],
}
ASSOCIATIONS = {"contacts": ["companies"], "deals": ["contacts", "companies"]}


def ensure_raw_table(conn, object_type: str) -> None:
    if object_type not in OBJECTS:
        raise ValueError(f"unsupported object type: {object_type}")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS raw.{object_type} (
                object_id text PRIMARY KEY, payload jsonb NOT NULL,
                ingested_at timestamptz NOT NULL
            )
        """)


def ensure_association_table(conn, from_type: str, to_type: str) -> str:
    table = f"{from_type}_{to_type}"
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS raw.{table} (
                from_object_id text NOT NULL,
                to_object_id text NOT NULL,
                association_type text NOT NULL,
                payload jsonb NOT NULL,
                ingested_at timestamptz NOT NULL,
                PRIMARY KEY (from_object_id, to_object_id, association_type)
            )
        """)
    return table


def load_associations(conn, client, from_type: str, object_ids: list[str], ingested_at: datetime) -> int:
    loaded = 0
    for to_type in ASSOCIATIONS.get(from_type, []):
        table = ensure_association_table(conn, from_type, to_type)
        for object_id in object_ids:
            results = list(client.iter_associations(from_type, object_id, to_type))
            with conn.cursor() as cur:
                # The API response is authoritative for the processed object, including removals.
                cur.execute(f"DELETE FROM raw.{table} WHERE from_object_id = %s", (object_id,))
                for result in results:
                    for association in result.get("associationTypes", []):
                        cur.execute(f"""
                            INSERT INTO raw.{table}
                                (from_object_id, to_object_id, association_type, payload, ingested_at)
                            VALUES (%s, %s, %s, %s::jsonb, %s)
                            ON CONFLICT (from_object_id, to_object_id, association_type)
                            DO UPDATE SET payload=EXCLUDED.payload, ingested_at=EXCLUDED.ingested_at
                        """, (
                            object_id, str(result["toObjectId"]), association.get("label") or association.get("typeId"),
                            json.dumps(result), ingested_at,
                        ))
                        loaded += 1
    return loaded


def extract_object(conn, client: HubSpotClient, object_type: str, run_started: datetime) -> int:
    ensure_raw_table(conn, object_type)
    watermark = None if os.getenv("FULL_REFRESH", "").lower() in {"1", "true", "yes"} else get_watermark(conn, object_type)
    rows = list(client.iter_objects(object_type, OBJECTS[object_type], watermark))
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(f"""
                INSERT INTO raw.{object_type} (object_id, payload, ingested_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (object_id) DO UPDATE SET
                    payload = EXCLUDED.payload, ingested_at = EXCLUDED.ingested_at
            """, (str(row["id"]), json.dumps(row), run_started))
        load_associations(conn, client, object_type, [str(row["id"]) for row in rows], run_started)
        # Advancing only after all upserts prevents a partial load from losing records.
        set_watermark(conn, object_type, run_started)
    conn.commit()
    return len(rows)


def run() -> uuid.UUID:
    token = os.environ["HUBSPOT_ACCESS_TOKEN"]
    database_url = os.environ["DATABASE_URL"]
    run_id, started = uuid.uuid4(), datetime.now(timezone.utc)
    client = HubSpotClient(token)
    with psycopg.connect(database_url) as conn:
        ensure_metadata(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO pipeline_runs (run_id, started_at, status) VALUES (%s, %s, 'running')", (run_id, started))
        conn.commit()
        counts: dict[str, int] = {}
        try:
            for object_type in OBJECTS:
                counts[object_type] = extract_object(conn, client, object_type, started)
            with conn.cursor() as cur:
                cur.execute("UPDATE pipeline_runs SET status='transforming', object_counts=%s::jsonb WHERE run_id=%s", (json.dumps(counts), run_id))
            conn.commit()
            return run_id
        except Exception as exc:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("UPDATE pipeline_runs SET ended_at=now(), status='failed', object_counts=%s::jsonb, error_message=%s WHERE run_id=%s", (json.dumps(counts), str(exc)[:2000], run_id))
            conn.commit()
            raise


if __name__ == "__main__":
    run()
