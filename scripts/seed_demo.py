"""Seed a HubSpot test portal with the demo dataset.

Needs crm.objects.{contacts,companies,deals}.write on the private app, which
the pipeline itself does not use. Add the scopes, seed, then remove them: the
extractor only ever reads.

    python -m scripts.seed_demo --dry-run   # show what would be created
    python -m scripts.seed_demo

Re-running is safe. Existing records are matched on a deterministic key
(company domain, contact email, deal name) and skipped, and associations are
idempotent on HubSpot's side.
"""
from __future__ import annotations

import argparse
import os

from extract.client import HubSpotClient
from scripts.demo_data import generate, summary

BATCH_SIZE = 100

KEY_PROPERTY = {"companies": "domain", "contacts": "email", "deals": "dealname"}

# HubSpot's default association type ids.
ASSOCIATION_TYPE = {
    ("contacts", "companies"): 1,
    ("deals", "contacts"): 3,
    ("deals", "companies"): 5,
}


def existing_by_key(client: HubSpotClient, object_type: str) -> dict[str, str]:
    """Every record already in the portal, keyed by the property we seed on."""
    key = KEY_PROPERTY[object_type]
    found: dict[str, str] = {}
    for record in client.iter_objects(object_type, [key], None):
        value = record.get("properties", {}).get(key)
        if value:
            found[value] = str(record["id"])
    return found


def create_batch(client: HubSpotClient, object_type: str, records: list[dict]) -> dict[str, str]:
    created: dict[str, str] = {}
    key = KEY_PROPERTY[object_type]
    for start in range(0, len(records), BATCH_SIZE):
        chunk = records[start : start + BATCH_SIZE]
        payload = {"inputs": [{"properties": _writable(record["properties"])} for record in chunk]}
        response = client._request("POST", f"/crm/v3/objects/{object_type}/batch/create", json=payload)
        for result in response.get("results", []):
            created[result["properties"][key]] = str(result["id"])
    return created


def _writable(properties: dict) -> dict:
    """Drop read-only fields. HubSpot sets creation and modification times itself."""
    skip = {"createdate", "hs_lastmodifieddate", "lastmodifieddate"}
    return {k: v for k, v in properties.items() if v is not None and k not in skip}


def associate_batch(client: HubSpotClient, from_type: str, to_type: str, pairs: list[tuple[str, str]]) -> int:
    type_id = ASSOCIATION_TYPE[(from_type, to_type)]
    for start in range(0, len(pairs), BATCH_SIZE):
        chunk = pairs[start : start + BATCH_SIZE]
        client._request(
            "POST",
            f"/crm/v4/associations/{from_type}/{to_type}/batch/create",
            json={"inputs": [
                {
                    "_from": {"id": from_id},
                    "to": {"id": to_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": type_id}],
                }
                for from_id, to_id in chunk
            ]},
        )
    return len(pairs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a HubSpot test portal with demo GTM records.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be created and exit.")
    args = parser.parse_args()

    dataset = generate()
    if args.dry_run:
        print("Would seed:")
        for key, value in summary(dataset).items():
            print(f"  {key}: {value}")
        return

    client = HubSpotClient(os.environ["HUBSPOT_ACCESS_TOKEN"])
    ids: dict[str, dict[str, str]] = {}
    for object_type in ("companies", "contacts", "deals"):
        present = existing_by_key(client, object_type)
        missing = [record for record in dataset[object_type] if record["key"] not in present]
        present.update(create_batch(client, object_type, missing))
        ids[object_type] = present
        print(f"{object_type}: {len(missing)} created, {len(dataset[object_type]) - len(missing)} already present")

    company_ids = [ids["companies"][c["key"]] for c in dataset["companies"]]
    contact_ids = [ids["contacts"][c["key"]] for c in dataset["contacts"]]
    deal_ids = [ids["deals"][d["key"]] for d in dataset["deals"]]

    contact_company = [
        (contact_ids[index], company_ids[contact["company_index"] - 1])
        for index, contact in enumerate(dataset["contacts"])
        if contact["company_index"]
    ]
    deal_contact = [
        (deal_ids[index], contact_ids[contact_index - 1])
        for index, deal in enumerate(dataset["deals"])
        for contact_index in deal["contact_indexes"]
    ]
    deal_company = [
        (deal_ids[index], company_ids[company_index - 1])
        for index, deal in enumerate(dataset["deals"])
        for company_index in deal["company_indexes"]
    ]

    print("associations:",
          associate_batch(client, "contacts", "companies", contact_company),
          associate_batch(client, "deals", "contacts", deal_contact),
          associate_batch(client, "deals", "companies", deal_company))


if __name__ == "__main__":
    main()
