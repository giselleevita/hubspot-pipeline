"""Create deterministic GTM demo records in a HubSpot test portal.

Requires crm.objects.{contacts,companies,deals}.write. Re-running is safe because
records are found by deterministic domain, email, or deal name before creation.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from extract.client import HubSpotClient


def find_one(client, object_type: str, property_name: str, value: str):
    page = client._request("POST", f"/crm/v3/objects/{object_type}/search", json={
        "filterGroups": [{"filters": [{"propertyName": property_name, "operator": "EQ", "value": value}]}],
        "properties": [property_name], "limit": 1,
    })
    results = page.get("results", [])
    return results[0] if results else None


def get_or_create(client, object_type: str, key: str, properties: dict[str, str]):
    existing = find_one(client, object_type, key, properties[key])
    if existing:
        return str(existing["id"]), False
    created = client._request("POST", f"/crm/v3/objects/{object_type}", json={"properties": properties})
    return str(created["id"]), True


def associate(client, from_type: str, from_id: str, to_type: str, to_id: str):
    client._request(
        "PUT", f"/crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}"
    )


def main():
    client = HubSpotClient(os.environ["HUBSPOT_ACCESS_TOKEN"])
    stages = ["appointmentscheduled", "qualifiedtobuy", "presentationscheduled", "closedwon"]
    counts = {"companies": 0, "contacts": 0, "deals": 0}
    companies: list[str] = []
    for i in range(1, 9):
        company_id, created = get_or_create(client, "companies", "domain", {
            "name": f"Famly Demo Nursery {i}", "domain": f"famly-demo-{i}.example",
            "industry": "EDUCATION_MANAGEMENT",
        })
        companies.append(company_id)
        counts["companies"] += int(created)

    contacts: list[str] = []
    for i in range(1, 25):
        company_id = companies[(i - 1) % len(companies)]
        contact_id, created = get_or_create(client, "contacts", "email", {
            "email": f"gtm-demo-{i}@famly-demo.example", "firstname": f"Demo{i}", "lastname": "Educator",
        })
        associate(client, "contacts", contact_id, "companies", company_id)
        contacts.append(contact_id)
        counts["contacts"] += int(created)

    for i in range(1, 17):
        company_id = companies[(i - 1) % len(companies)]
        contact_id = contacts[(i - 1) % len(contacts)]
        deal_id, created = get_or_create(client, "deals", "dealname", {
            "dealname": f"Famly GTM Demo Deal {i}", "amount": str(2500 + i * 375),
            "dealstage": stages[(i - 1) % len(stages)],
            "closedate": str(date.today() + timedelta(days=i * 3)),
        })
        associate(client, "deals", deal_id, "contacts", contact_id)
        associate(client, "deals", deal_id, "companies", company_id)
        counts["deals"] += int(created)
    print("Demo seed complete:", counts)


if __name__ == "__main__":
    main()
