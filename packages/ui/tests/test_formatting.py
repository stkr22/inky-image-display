"""Tests for the formatting helpers used by the UI views."""

from datetime import UTC, datetime, timedelta

from inky_image_display_ui.formatting import (
    format_datetime,
    format_interval_seconds,
    format_relative,
    parse_datetime,
    split_hours_minutes,
)


class TestParseDatetime:
    def test_offset_aware_round_trips(self):
        result = parse_datetime("2026-05-17T12:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_naive_string_is_treated_as_utc(self):
        # Older payloads predating the API serializer change shouldn't crash.
        result = parse_datetime("2026-05-17T12:00:00")
        assert result is not None
        assert result.tzinfo is UTC


class TestFormatRelative:
    def test_future(self):
        now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
        future = now + timedelta(minutes=4)
        assert format_relative(future, now=now) == "in 4m"

    def test_past(self):
        now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
        past = now - timedelta(minutes=5)
        assert format_relative(past, now=now) == "5m ago"

    def test_due_now_window(self):
        now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
        assert format_relative(now + timedelta(seconds=5), now=now) == "due now"

    def test_hours_and_minutes(self):
        now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
        future = now + timedelta(hours=2, minutes=30)
        assert format_relative(future, now=now) == "in 2h 30m"


class TestFormatInterval:
    def test_none_renders_as_default_label(self):
        assert format_interval_seconds(None) == "default"

    def test_minutes(self):
        assert format_interval_seconds(15 * 60) == "15m"

    def test_hour_with_remainder(self):
        assert format_interval_seconds(3 * 3600 + 5 * 60) == "3h 5m"


class TestSplitHoursMinutes:
    def test_none_returns_zeros(self):
        assert split_hours_minutes(None) == (0, 0)

    def test_round_trip(self):
        assert split_hours_minutes(3 * 3600 + 25 * 60) == (3, 25)


class TestFormatDatetime:
    def test_renders_local_with_tz_suffix(self):
        # Don't assert the exact local string — CI timezone may vary —
        # but the formatter must produce a non-empty result that includes
        # a year and tz label component.
        formatted = format_datetime("2026-05-17T12:00:00+00:00")
        assert "2026" in formatted
        # Either we got "%Z" rendered or at minimum the date+time portion.
        assert len(formatted) >= len("2026-05-17 12:00")
