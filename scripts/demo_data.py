"""Deterministic demo dataset, shaped exactly like HubSpot API responses.

One generator feeds both paths: `seed_demo.py` pushes these records into a test
portal, and `load_fixture.py` writes the same records straight into the raw
tables for anyone reviewing the project without a HubSpot token. Sharing the
generator is what stops the two from drifting into different shapes.

The distribution is deliberate rather than uniform. It contains the cases the
data model claims to handle: deals attached to more than one company, deals with
several contacts, contacts with no company at all, deals with no amount, and a
spread of modification times so an incremental run has a boundary to land on.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

COMPANY_COUNT = 60
CONTACT_COUNT = 240
DEAL_COUNT = 120

STAGES = [
    ("appointmentscheduled", 0.30),
    ("qualifiedtobuy", 0.22),
    ("presentationscheduled", 0.18),
    ("decisionmakerboughtin", 0.10),
    ("closedwon", 0.12),
    ("closedlost", 0.08),
]

COUNTRIES = ["Denmark", "United Kingdom", "Germany", "Norway", "Sweden"]
INDUSTRIES = ["EDUCATION_MANAGEMENT", "PRIMARY_SECONDARY_EDUCATION", "NON_PROFIT_ORGANIZATION_MANAGEMENT"]
FIRST_NAMES = ["Anna", "Mikkel", "Sofia", "Jonas", "Freja", "Lucas", "Emma", "Noah", "Clara", "Elias"]
LAST_NAMES = ["Jensen", "Nielsen", "Hansen", "Pedersen", "Andersen", "Schmidt", "Müller", "Berg", "Lund", "Holm"]

# Everything is generated relative to this instant, then frozen by the seed.
HORIZON_DAYS = 540


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _weighted_stage(rng: random.Random) -> str:
    roll, running = rng.random(), 0.0
    for stage, weight in STAGES:
        running += weight
        if roll <= running:
            return stage
    return STAGES[-1][0]


def generate(now: datetime | None = None, seed: int = 20260831) -> dict:
    """Companies, contacts, deals and association edges, as plain dicts."""
    rng = random.Random(seed)
    now = now or datetime.now(UTC)

    companies = []
    for index in range(1, COMPANY_COUNT + 1):
        created = now - timedelta(days=rng.randint(30, HORIZON_DAYS), minutes=rng.randint(0, 1440))
        modified = created + timedelta(days=rng.randint(0, 60))
        companies.append({
            "key": f"famly-demo-{index}.example",
            "properties": {
                "name": f"Demo Nursery {index}",
                "domain": f"famly-demo-{index}.example",
                "industry": rng.choice(INDUSTRIES),
                "country": rng.choice(COUNTRIES),
                "numberofemployees": str(rng.choice([4, 8, 12, 20, 35, 60, 120])),
                "createdate": _stamp(created),
                "hs_lastmodifieddate": _stamp(min(modified, now)),
            },
        })

    contacts = []
    for index in range(1, CONTACT_COUNT + 1):
        created = now - timedelta(days=rng.randint(1, HORIZON_DAYS), minutes=rng.randint(0, 1440))
        modified = created + timedelta(days=rng.randint(0, 45))
        contacts.append({
            "key": f"gtm-demo-{index}@famly-demo.example",
            # One in twelve contacts has no company. A dimension that assumed
            # otherwise would drop them.
            "company_index": None if index % 12 == 0 else (index % COMPANY_COUNT),
            "properties": {
                "email": f"gtm-demo-{index}@famly-demo.example",
                "firstname": rng.choice(FIRST_NAMES),
                "lastname": rng.choice(LAST_NAMES),
                # Contacts carry lastmodifieddate, not hs_lastmodifieddate.
                "createdate": _stamp(created),
                "lastmodifieddate": _stamp(min(modified, now)),
            },
        })

    deals = []
    for index in range(1, DEAL_COUNT + 1):
        created = now - timedelta(days=rng.randint(1, 400), minutes=rng.randint(0, 1440))
        modified = min(created + timedelta(days=rng.randint(0, 90)), now)
        stage = _weighted_stage(rng)
        # One deal in twenty has no amount filled in, which is what SAFE casts
        # and not_null tests are for.
        amount = None if index % 20 == 0 else str(rng.randrange(1500, 48000, 250))
        deals.append({
            "key": f"Demo Deal {index}",
            # One deal in nine has nobody attached, which is what the left
            # join in the coverage query is looking for.
            "contact_indexes": [] if index % 9 == 0 else [
                ((index * 3 + offset) % CONTACT_COUNT) + 1 for offset in range(1 + (index % 3))
            ],
            # One deal in fifteen belongs to two companies. This is the case the
            # bridge table exists for.
            "company_indexes": [((index * 7) % COMPANY_COUNT) + 1] + (
                [((index * 7 + 13) % COMPANY_COUNT) + 1] if index % 15 == 0 else []
            ),
            "properties": {
                "dealname": f"Demo Deal {index}",
                "amount": amount,
                "dealstage": stage,
                "pipeline": "default",
                "createdate": _stamp(created),
                "closedate": _stamp(created + timedelta(days=rng.randint(14, 120))),
                "hs_lastmodifieddate": _stamp(modified),
            },
        })

    return {"companies": companies, "contacts": contacts, "deals": deals}


def summary(dataset: dict) -> dict[str, int]:
    deals = dataset["deals"]
    return {
        "companies": len(dataset["companies"]),
        "contacts": len(dataset["contacts"]),
        "deals": len(deals),
        "contacts_without_company": sum(1 for c in dataset["contacts"] if c["company_index"] is None),
        "deals_with_two_companies": sum(1 for d in deals if len(d["company_indexes"]) > 1),
        "deals_without_amount": sum(1 for d in deals if d["properties"]["amount"] is None),
        "deal_contact_edges": sum(len(d["contact_indexes"]) for d in deals),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(summary(generate()), indent=2))
