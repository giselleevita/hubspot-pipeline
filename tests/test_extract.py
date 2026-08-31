from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from extract import extract as extract_module
from extract.extract import extract_from, load_associations, lookback_minutes

WATERMARK = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def test_extract_start_subtracts_the_lookback(monkeypatch):
    monkeypatch.delenv("EXTRACT_LOOKBACK_MINUTES", raising=False)
    monkeypatch.delenv("FULL_REFRESH", raising=False)
    with patch.object(extract_module, "get_watermark", return_value=WATERMARK):
        assert extract_from(MagicMock(), "contacts") == WATERMARK - timedelta(minutes=5)


def test_first_run_has_no_start_and_reads_everything(monkeypatch):
    monkeypatch.delenv("FULL_REFRESH", raising=False)
    with patch.object(extract_module, "get_watermark", return_value=None):
        assert extract_from(MagicMock(), "contacts") is None


def test_full_refresh_ignores_the_watermark(monkeypatch):
    monkeypatch.setenv("FULL_REFRESH", "true")
    with patch.object(extract_module, "get_watermark", return_value=WATERMARK):
        assert extract_from(MagicMock(), "contacts") is None


def test_lookback_override_must_be_numeric(monkeypatch):
    monkeypatch.setenv("EXTRACT_LOOKBACK_MINUTES", "soon")
    with pytest.raises(ValueError, match="EXTRACT_LOOKBACK_MINUTES"):
        lookback_minutes()


def test_associations_clear_stale_edges_for_every_object_looked_at():
    """A deal that lost its company has no row to update, so the delete has to
    run for objects that came back with no associations too."""
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    client = MagicMock()
    client.read_associations.return_value = {
        "1": [{"toObjectId": 99, "associationTypes": [{"typeId": 1, "label": "Primary"}]}],
        "2": [],
    }

    loaded = load_associations(conn, client, "contacts", ["1", "2"], datetime.now(timezone.utc))

    deletes = [c for c in cursor.execute.call_args_list if "DELETE FROM" in c.args[0]]
    assert {c.args[1][0] for c in deletes} == {"1", "2"}
    assert loaded == 1


def test_associations_are_requested_once_per_type_not_once_per_object():
    conn, cursor = MagicMock(), MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    client = MagicMock()
    client.read_associations.return_value = {str(i): [] for i in range(50)}

    load_associations(conn, client, "deals", [str(i) for i in range(50)], datetime.now(timezone.utc))

    # deals associate to contacts and companies: two calls, not one hundred.
    assert client.read_associations.call_count == 2
