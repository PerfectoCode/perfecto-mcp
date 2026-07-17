"""Datetime utility timezone tests."""

from tools.utils import get_date_time_iso


class TestDateTimeIsoTimezone:
    def test_returns_none_for_none_timestamp(self):
        assert get_date_time_iso(None) is None

    def test_returns_utc_timezone_for_unix_epoch(self):
        assert get_date_time_iso(0) == "1970-01-01T00:00:00+00:00"

    def test_returns_utc_timezone_for_known_timestamp(self):
        assert get_date_time_iso(1710000000) == "2024-03-09T16:00:00+00:00"
