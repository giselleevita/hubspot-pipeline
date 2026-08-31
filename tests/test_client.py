from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from extract import client as client_module
from extract.client import HubSpotClient, modified_property


def response(payload, status_code=200, headers=None):
    item = Mock(status_code=status_code, headers=headers or {})
    item.json.return_value = payload
    return item


def make_client(session):
    return HubSpotClient("token", session=session)


def test_contacts_filter_on_their_own_modified_property():
    """Contacts answer to lastmodifieddate. Filtering them on hs_lastmodifieddate
    returns zero rows without erroring, which is how a broken incremental run
    stays invisible."""
    assert modified_property("contacts") == "lastmodifieddate"
    assert modified_property("companies") == "hs_lastmodifieddate"
    assert modified_property("deals") == "hs_lastmodifieddate"


def test_unknown_object_type_is_rejected():
    with pytest.raises(ValueError, match="unsupported object type"):
        modified_property("tickets")


def test_cursor_pagination_on_full_refresh():
    session = Mock(headers={})
    session.request.side_effect = [
        response({"results": [{"id": "1"}], "paging": {"next": {"after": "abc"}}}),
        response({"results": [{"id": "2"}]}),
    ]
    rows = list(make_client(session).iter_objects("contacts", ["email"], None))
    assert [row["id"] for row in rows] == ["1", "2"]
    assert session.request.call_args_list[1].kwargs["params"]["after"] == "abc"


def test_incremental_search_sends_watermark_and_sorts_ascending():
    session = Mock(headers={})
    session.request.return_value = response({"results": []})
    watermark = datetime(2025, 1, 1, tzinfo=timezone.utc)

    list(make_client(session).iter_objects("deals", ["amount"], watermark))

    body = session.request.call_args.kwargs["json"]
    assert body["filterGroups"][0]["filters"][0] == {
        "propertyName": "hs_lastmodifieddate",
        "operator": "GTE",
        "value": str(int(watermark.timestamp() * 1000)),
    }
    assert body["sorts"] == [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]


def test_contact_search_uses_lastmodifieddate():
    session = Mock(headers={})
    session.request.return_value = response({"results": []})

    list(make_client(session).iter_objects("contacts", ["email"], datetime(2025, 1, 1, tzinfo=timezone.utc)))

    body = session.request.call_args.kwargs["json"]
    assert body["filterGroups"][0]["filters"][0]["propertyName"] == "lastmodifieddate"


def test_search_reanchors_at_the_result_cap(monkeypatch):
    """Past 10,000 results the endpoint stops paging, so the query restarts from
    the last record instead of losing the remainder."""
    monkeypatch.setattr(client_module, "SEARCH_RESULT_CAP", 2)
    monkeypatch.setattr(client_module, "PAGE_SIZE", 2)
    session = Mock(headers={})
    session.request.side_effect = [
        response({
            "results": [
                {"id": "1", "properties": {"hs_lastmodifieddate": "2026-01-01T00:00:00Z"}},
                {"id": "2", "properties": {"hs_lastmodifieddate": "2026-03-01T00:00:00Z"}},
            ],
            "paging": {"next": {"after": "200"}},
        }),
        response({"results": [{"id": "3", "properties": {"hs_lastmodifieddate": "2026-03-02T00:00:00Z"}}]}),
    ]

    rows = list(make_client(session).iter_objects("deals", ["amount"], datetime(2025, 1, 1, tzinfo=timezone.utc)))

    assert [row["id"] for row in rows] == ["1", "2", "3"]
    second_body = session.request.call_args_list[1].kwargs["json"]
    assert "after" not in second_body
    assert second_body["filterGroups"][0]["filters"][0]["value"] == str(
        int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
    )


def test_associations_are_read_in_batches():
    session = Mock(headers={})
    session.request.return_value = response({
        "results": [
            {"from": {"id": "1"}, "to": [{"toObjectId": 10, "associationTypes": [{"typeId": 1}]}]},
        ]
    })

    result = make_client(session).read_associations("deals", "companies", ["1", "2"])

    assert session.request.call_count == 1, "one call for the whole batch, not one per object"
    assert session.request.call_args.kwargs["json"]["inputs"] == [{"id": "1"}, {"id": "2"}]
    assert result["1"][0]["toObjectId"] == 10
    # Absent from the response means no links, not "not looked at". The loader
    # needs the difference to delete association rows that were removed.
    assert result["2"] == []


def test_association_batches_are_chunked(monkeypatch):
    monkeypatch.setattr(client_module, "ASSOCIATION_BATCH_SIZE", 2)
    session = Mock(headers={})
    session.request.return_value = response({"results": []})

    make_client(session).read_associations("deals", "contacts", ["1", "2", "3"])

    assert session.request.call_count == 2


def test_rate_limit_is_retried_with_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    session = Mock(headers={})
    session.request.side_effect = [
        response({}, status_code=429, headers={"Retry-After": "3"}),
        response({"results": [{"id": "1"}]}),
    ]

    rows = list(make_client(session).iter_objects("contacts", ["email"], None))

    assert [row["id"] for row in rows] == ["1"]
    assert slept == [3.0]
