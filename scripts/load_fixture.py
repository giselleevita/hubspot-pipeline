"""Load the demo dataset straight into a separate raw layer, no HubSpot needed.

Anyone reviewing this project without a private-app token can still build every
model and query the marts. The data is generated, and it goes into its own
database (`hubspot_demo` by default) so that it can never be mistaken for, or
mixed with, records extracted from a real portal.

    python -m scripts.load_fixture
    dbt build --project-dir dbt --profiles-dir dbt --target demo
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import psycopg

from extract.extract import ensure_association_table, ensure_raw_table
from extract.state import ensure_metadata
from scripts.demo_data import generate, summary

DEFAULT_DEMO_DB = "hubspot_demo"

# Ids are synthetic and far outside HubSpot's range for this portal, so a demo
# row can never collide with a real object id.
COMPANY_ID_BASE = 900_000_000_000
CONTACT_ID_BASE = 910_000_000_000
DEAL_ID_BASE = 920_000_000_000


def admin_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://pipeline:pipeline@localhost:5432/hubspot")


def demo_url() -> str:
    if os.getenv("DEMO_DATABASE_URL"):
        return os.environ["DEMO_DATABASE_URL"]
    base = admin_url().rsplit("/", 1)[0]
    return f"{base}/{os.getenv('DEMO_DBNAME', DEFAULT_DEMO_DB)}"


def ensure_database(name: str) -> None:
    with psycopg.connect(admin_url(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{name}"')


def api_record(object_id: int, properties: dict) -> dict:
    """The envelope the CRM API returns, so staging parses fixtures and live rows identically."""
    return {
        "id": str(object_id),
        "properties": {k: v for k, v in properties.items()},
        "createdAt": properties.get("createdate"),
        "updatedAt": properties.get("hs_lastmodifieddate") or properties.get("lastmodifieddate"),
        "archived": False,
    }


def load(conn, dataset: dict, ingested_at: datetime) -> dict[str, int]:
    for object_type in ("contacts", "companies", "deals"):
        ensure_raw_table(conn, object_type)
    tables = {
        ("contacts", "companies"): ensure_association_table(conn, "contacts", "companies"),
        ("deals", "contacts"): ensure_association_table(conn, "deals", "contacts"),
        ("deals", "companies"): ensure_association_table(conn, "deals", "companies"),
    }

    with conn.cursor() as cur:
        for table in ("contacts", "companies", "deals"):
            cur.execute(f"TRUNCATE raw.{table}")
        for table in tables.values():
            cur.execute(f"TRUNCATE raw.{table}")

        for index, company in enumerate(dataset["companies"], start=1):
            _insert_object(cur, "companies", COMPANY_ID_BASE + index, company["properties"], ingested_at)
        for index, contact in enumerate(dataset["contacts"], start=1):
            _insert_object(cur, "contacts", CONTACT_ID_BASE + index, contact["properties"], ingested_at)
            if contact["company_index"]:
                _insert_edge(cur, tables[("contacts", "companies")], CONTACT_ID_BASE + index,
                             COMPANY_ID_BASE + contact["company_index"], ingested_at)
        for index, deal in enumerate(dataset["deals"], start=1):
            _insert_object(cur, "deals", DEAL_ID_BASE + index, deal["properties"], ingested_at)
            for contact_index in deal["contact_indexes"]:
                _insert_edge(cur, tables[("deals", "contacts")], DEAL_ID_BASE + index,
                             CONTACT_ID_BASE + contact_index, ingested_at)
            for company_index in deal["company_indexes"]:
                _insert_edge(cur, tables[("deals", "companies")], DEAL_ID_BASE + index,
                             COMPANY_ID_BASE + company_index, ingested_at)
    conn.commit()
    return summary(dataset)


def _insert_object(cur, table: str, object_id: int, properties: dict, ingested_at: datetime) -> None:
    cur.execute(
        f"""INSERT INTO raw.{table} (object_id, payload, ingested_at) VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (object_id) DO UPDATE SET payload = EXCLUDED.payload, ingested_at = EXCLUDED.ingested_at""",
        (str(object_id), json.dumps(api_record(object_id, properties)), ingested_at),
    )


def _insert_edge(cur, table: str, from_id: int, to_id: int, ingested_at: datetime) -> None:
    payload = {"toObjectId": to_id, "associationTypes": [{"category": "HUBSPOT_DEFINED", "typeId": 1, "label": "Primary"}]}
    cur.execute(
        f"""INSERT INTO raw.{table} (from_object_id, to_object_id, association_type, payload, ingested_at)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (from_object_id, to_object_id, association_type)
            DO UPDATE SET payload = EXCLUDED.payload, ingested_at = EXCLUDED.ingested_at""",
        (str(from_id), str(to_id), "Primary", json.dumps(payload), ingested_at),
    )


def main() -> None:
    database = os.getenv("DEMO_DBNAME", DEFAULT_DEMO_DB)
    ensure_database(database)
    with psycopg.connect(demo_url()) as conn:
        ensure_metadata(conn)
        counts = load(conn, generate(), datetime.now(UTC))
    print(f"Loaded demo fixtures into {database}:")
    for key, value in counts.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
