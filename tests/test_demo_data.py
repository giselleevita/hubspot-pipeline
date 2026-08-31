"""The demo dataset has to contain the cases the data model claims to handle.

Without these assertions the fixtures drifted into a set where every deal had
exactly one company, which made the bridge table look unnecessary in a review.
"""
from scripts.demo_data import generate, summary

DATASET = generate()
SUMMARY = summary(DATASET)


def test_volume_is_enough_for_an_incremental_run_to_be_interesting():
    assert SUMMARY["companies"] == 60
    assert SUMMARY["contacts"] == 240
    assert SUMMARY["deals"] == 120


def test_some_deals_belong_to_two_distinct_companies():
    shared = [d for d in DATASET["deals"] if len(set(d["company_indexes"])) > 1]
    assert len(shared) >= 5, "the bridge table needs multi-company deals to justify itself"


def test_some_deals_have_no_contact_attached():
    assert any(not d["contact_indexes"] for d in DATASET["deals"])


def test_some_contacts_have_no_company():
    assert SUMMARY["contacts_without_company"] > 0


def test_some_deals_have_no_amount():
    assert SUMMARY["deals_without_amount"] > 0


def test_contacts_carry_lastmodifieddate_and_others_carry_hs_lastmodifieddate():
    assert "lastmodifieddate" in DATASET["contacts"][0]["properties"]
    assert "hs_lastmodifieddate" not in DATASET["contacts"][0]["properties"]
    assert "hs_lastmodifieddate" in DATASET["deals"][0]["properties"]
    assert "hs_lastmodifieddate" in DATASET["companies"][0]["properties"]


def test_generation_is_deterministic():
    assert summary(generate()) == SUMMARY


def test_modification_times_never_precede_creation():
    for deal in DATASET["deals"]:
        assert deal["properties"]["hs_lastmodifieddate"] >= deal["properties"]["createdate"]
