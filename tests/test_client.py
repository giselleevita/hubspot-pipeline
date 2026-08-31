from datetime import datetime, timezone
from unittest.mock import Mock

from extract.client import HubSpotClient


def response(payload):
    item = Mock(status_code=200, headers={})
    item.json.return_value = payload
    return item


def test_cursor_pagination():
    session = Mock(headers={})
    session.request.side_effect = [
        response({"results": [{"id": "1"}], "paging": {"next": {"after": "abc"}}}),
        response({"results": [{"id": "2"}]}),
    ]
    rows = list(HubSpotClient("token", session=session).iter_objects("contacts", ["email"], None))
    assert [row["id"] for row in rows] == ["1", "2"]
    assert session.request.call_args_list[1].kwargs["params"]["after"] == "abc"


def test_incremental_uses_search_and_watermark():
    session = Mock(headers={})
    session.request.return_value = response({"results": []})
    watermark = datetime(2025, 1, 1, tzinfo=timezone.utc)
    list(HubSpotClient("token", session=session).iter_objects("deals", ["amount"], watermark))
    body = session.request.call_args.kwargs["json"]
    assert body["filterGroups"][0]["filters"][0]["value"] == str(int(watermark.timestamp() * 1000))


def test_association_cursor_pagination():
    session = Mock(headers={})
    session.request.side_effect = [
        response({"results": [{"toObjectId": 10}], "paging": {"next": {"after": "next"}}}),
        response({"results": [{"toObjectId": 11}]}),
    ]
    rows = list(HubSpotClient("token", session=session).iter_associations("deals", "1", "contacts"))
    assert [row["toObjectId"] for row in rows] == [10, 11]
    assert session.request.call_args_list[1].kwargs["params"]["after"] == "next"
