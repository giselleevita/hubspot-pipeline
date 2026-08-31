from datetime import datetime, timezone
from unittest.mock import MagicMock

from extract.state import get_watermark, set_watermark


def test_get_missing_watermark_returns_none():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    assert get_watermark(conn, "contacts") is None


def test_set_watermark_uses_object_key():
    conn = MagicMock()
    stamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    set_watermark(conn, "contacts", stamp)
    args = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
    assert args == ("contacts", stamp)
