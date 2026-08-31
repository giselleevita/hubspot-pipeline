from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from extract.client import HubSpotClient, modified_property
from extract.state import ensure_metadata, get_watermark, set_watermark

OBJECTS = {
    "contacts": ["email", "firstname", "lastname", "createdate", "lastmodifieddate"],
    "companies": ["name", "domain", "industry", "country", "numberofemployees", "createdate", "hs_lastmodifieddate"],
    "deals": ["dealname", "amount", "dealstage", "createdate", "closedate", "hs_lastmodifieddate"],
}
ASSOCIATIONS = {"contacts": ["companies"], "deals": ["contacts", "companies"]}

# Search results are indexed with a short lag, and a record modified while an
# extract is running would otherwise fall between the read and the watermark.
# Re-reading a few minutes of overlap closes both gaps, and upserts make the
# repeated read free.
DEFAULT_LOOKBACK_MINUTES = 5


def lookback_minutes() -> int:
    raw = os.getenv("EXTRACT_LOOKBACK_MINUTES", "")
    if not raw:
        return DEFAULT_LOOKBACK_MINUTES
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"EXTRACT_LOOKBACK_MINUTES must be an integer, got {raw!r}") from exc


def full_refresh_requested() -> bool:
    return os.getenv("FULL_REFRESH", "").lower() in {"1", "true", "yes"}


def extract_from(conn, object_type: str) -> datetime | None:
    """Where this object's extract should start, lookback included."""
    if full_refresh_requested():
        return None
    watermark = get_watermark(conn, object_type)
    if watermark is None:
        return None
    return watermark - timedelta(minutes=lookback_minutes())


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


def load_associations(
    conn, client, from_type: str, object_ids: list[str], ingested_at: datetime
) -> int:
    loaded = 0
    for to_type in ASSOCIATIONS.get(from_type, []):
        table = ensure_association_table(conn, from_type, to_type)
        if not object_ids:
            continue
        by_object = client.read_associations(from_type, to_type, object_ids)
        with conn.cursor() as cur:
            for object_id, results in by_object.items():
                # The response is authoritative for every object we asked
                # about, including the ones that came back with nothing. A
                # link removed in HubSpot has no row to update, so the stale
                # edge only disappears if the object's rows are cleared first.
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
                            object_id,
                            str(result["toObjectId"]),
                            str(association.get("label") or association.get("typeId")),
                            json.dumps(result),
                            ingested_at,
                        ))
                        loaded += 1
    return loaded


def extract_object(conn, client: HubSpotClient, object_type: str, run_started: datetime) -> int:
    ensure_raw_table(conn, object_type)
    modified_after = extract_from(conn, object_type)
    rows = list(client.iter_objects(object_type, OBJECTS[object_type], modified_after))
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(f"""
                INSERT INTO raw.{object_type} (object_id, payload, ingested_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (object_id) DO UPDATE SET
                    payload = EXCLUDED.payload, ingested_at = EXCLUDED.ingested_at
            """, (str(row["id"]), json.dumps(row), run_started))
        load_associations(conn, client, object_type, [str(row["id"]) for row in rows], run_started)
        # Advancing only after all upserts prevents a partial load from losing
        # records. The value is the run start rather than the newest record, so
        # anything modified during the run is still eligible next time.
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
