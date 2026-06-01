"""Tests for scripts/check_staleness.py — the watchdog's staleness logic.

DB is stubbed: a fake cursor returns a single `MAX(finished_at)` value so we can
drive is_stale() across fresh / stale / never-ran / weekend cases offline.

Time is pinned: cs.datetime.now() is patched to a fixed instant T with a chosen
weekday, and the stubbed "last finished" timestamp is expressed relative to that
same T so age arithmetic is deterministic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import scripts.check_staleness as cs

# 2024-01-01 is a Monday (weekday 0); add `weekday` days to land on any day.
_BASE_MONDAY = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _fixed_now(weekday: int) -> datetime:
    return _BASE_MONDAY + timedelta(days=weekday)


class _Cursor:
    def __init__(self, last_finished):
        self._last = last_finished

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return [self._last]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _Conn:
    def __init__(self, last_finished):
        self._last = last_finished

    def cursor(self):
        return _Cursor(self._last)

    def close(self):
        pass


def _patch_now(weekday: int):
    """Patch cs.datetime so now(tz) returns a fixed instant on `weekday`."""
    fixed = _fixed_now(weekday)

    class _DT:
        @staticmethod
        def now(tz=None):
            return fixed

    return patch.object(cs, "datetime", _DT), fixed


def test_last_success_age_none_when_never_ran():
    conn = _Conn(None)
    assert cs.last_success_age_hours(conn, "fi", "inf_diario") is None


def test_last_success_age_computes_hours():
    p, fixed = _patch_now(weekday=1)  # Tuesday
    with p:
        conn = _Conn(fixed - timedelta(hours=5))
        age = cs.last_success_age_hours(conn, "fi", "inf_diario")
    assert age == pytest.approx(5.0, abs=1e-6)


def test_fresh_run_is_not_stale():
    p, fixed = _patch_now(weekday=2)  # Wednesday
    with p:
        conn = _Conn(fixed - timedelta(hours=2))  # within 26h
        assert cs.is_stale(conn, "fi", "inf_diario", 26) is False


def test_old_run_is_stale_on_weekday():
    p, fixed = _patch_now(weekday=2)
    with p:
        conn = _Conn(fixed - timedelta(hours=40))  # older than 26h
        assert cs.is_stale(conn, "fi", "inf_diario", 26) is True


def test_never_ran_is_stale():
    p, _ = _patch_now(weekday=2)
    with p:
        conn = _Conn(None)
        assert cs.is_stale(conn, "fi", "inf_diario", 26) is True


def test_weekend_suppresses_staleness():
    p, fixed = _patch_now(weekday=5)  # Saturday
    with p:
        conn = _Conn(fixed - timedelta(hours=40))  # stale on a weekday
        assert cs.is_stale(conn, "fi", "inf_diario", 26, weekday_only=True) is False


def test_weekend_not_suppressed_when_flag_off():
    p, fixed = _patch_now(weekday=6)  # Sunday
    with p:
        conn = _Conn(fixed - timedelta(hours=40))
        assert cs.is_stale(conn, "fi", "inf_diario", 26, weekday_only=False) is True


def test_naive_timestamp_treated_as_utc():
    # cvm_ingest_log stores TIMESTAMPTZ, but guard against a naive value too.
    p, fixed = _patch_now(weekday=1)
    with p:
        naive = (fixed - timedelta(hours=3)).replace(tzinfo=None)
        conn = _Conn(naive)
        age = cs.last_success_age_hours(conn, "fi", "inf_diario")
    assert age == pytest.approx(3.0, abs=1e-6)
