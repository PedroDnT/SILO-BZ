"""The matviews schema.sql owns are refreshed by the analytical apply.

Every other matview is dropped and re-created by `src/store/analytical/`, so
applying the layer is their daily refresh. `mv_b3_isin_subtype` and
`mv_b3_monthly_activity` are not: schema.sql creates them and refreshes them
only while they are empty. Their daily refresh was two pg_cron jobs in
`08_cron_schedules.sql`, and the live database has no pg_cron.

Measured 2026-09-29 (docs/planning/OPEN_ITEMS.md item 16): both still held what
they held on 2026-08-28. `/markets`, `/etf` and `/flows` showed August with 19
of its 21 sessions and no September. A test already asserted that the ISIN map
"is refreshed on a schedule"; it read the cron file, which was true and
refreshed nothing.

These tests pin the refresh that actually runs. The behaviour itself (new tape
rows reach both matviews, twice, and from empty) was proved against a local
Postgres 16 with the schema and the whole analytical layer applied.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYTICAL = ROOT / "src" / "store" / "analytical"
SCHEMA = (ROOT / "src" / "store" / "schema.sql").read_text(encoding="utf-8")
APPLY = (ROOT / "scripts" / "apply_analytical.sh").read_text(encoding="utf-8")

CRON_FILE = "08_cron_schedules.sql"
REFRESH_FILE = ANALYTICAL / "22_b3_tape_matviews.sql"

_REFRESH = re.compile(
    r"REFRESH\s+MATERIALIZED\s+VIEW\s+(CONCURRENTLY\s+)?(?:public\.)?(\w+)", re.I
)


def _code(sql: str) -> str:
    """SQL with `--` comments removed, so prose about a REFRESH is not one."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _schema_owned_matviews() -> list[str]:
    return re.findall(
        r"CREATE\s+MATERIALIZED\s+VIEW\s+IF\s+NOT\s+EXISTS\s+(?:public\.)?(\w+)",
        _code(SCHEMA),
        re.I,
    )


def _refreshes(path: Path) -> list[tuple[str, bool]]:
    """(matview, concurrently) for each REFRESH statement in the file, in order."""
    return [
        (m.group(2), bool(m.group(1)))
        for m in _REFRESH.finditer(_code(path.read_text(encoding="utf-8")))
    ]


def test_schema_owns_the_two_b3_matviews():
    # Keeps the next test from passing on an empty list.
    owned = _schema_owned_matviews()
    assert "mv_b3_isin_subtype" in owned
    assert "mv_b3_monthly_activity" in owned


def test_every_schema_owned_matview_is_refreshed_by_the_apply():
    """A matview created in schema.sql is not re-created by the analytical
    layer, so some numbered analytical file has to REFRESH it. The cron file
    does not count: it only schedules a job, and only where pg_cron exists."""
    refreshed = {
        name
        for path in sorted(ANALYTICAL.glob("[0-9][0-9]_*.sql"))
        if path.name != CRON_FILE
        for name, _ in _refreshes(path)
    }
    missing = [mv for mv in _schema_owned_matviews() if mv not in refreshed]
    assert not missing, (
        f"{missing} are created in schema.sql and refreshed by no analytical file "
        f"other than {CRON_FILE}. schema.sql refreshes a matview only while it is "
        "empty, so it would freeze at its first contents (OPEN_ITEMS.md item 16)."
    )


def test_the_isin_map_is_refreshed_before_the_monthly_aggregate():
    """mv_b3_monthly_activity reads vw_b3_instrument_typed, which falls back to
    mv_b3_isin_subtype for a fund quota's subtype. The other order would bake a
    day-old subtype into the monthly ETF/FII splits."""
    order = [name for name, _ in _refreshes(REFRESH_FILE)]
    assert order.index("mv_b3_isin_subtype") < order.index("mv_b3_monthly_activity")
    # One transaction, so the second statement sees the first.
    body = _code(REFRESH_FILE.read_text(encoding="utf-8"))
    assert body.count("BEGIN;") == 1 and body.count("COMMIT;") == 1


def test_refresh_never_blocks_readers_and_still_fills_an_empty_matview():
    """CONCURRENTLY keeps api.fund_quotas, the quote views and a dashboard build
    readable during the rebuild, and it refuses an unpopulated matview, so each
    one also needs the plain form behind a relispopulated check."""
    body = _code(REFRESH_FILE.read_text(encoding="utf-8"))
    forms = _refreshes(REFRESH_FILE)
    for mv in ("mv_b3_isin_subtype", "mv_b3_monthly_activity"):
        assert (mv, True) in forms, f"{mv} must be refreshed CONCURRENTLY"
        assert (mv, False) in forms, f"{mv} needs the plain REFRESH for the empty case"
    assert body.count("relispopulated") == 2


def test_a_failed_refresh_cannot_be_downgraded_to_a_warning():
    """apply_analytical.sh turns a failure of the cron file into a warning when
    its output mentions pg_cron, and that file's own NOTICE does. A REFRESH in
    there could fail unseen, so the refresh lives in a file of its own."""
    assert '[ "$base" = "08_cron_schedules.sql" ]' in APPLY, (
        "the pg_cron tolerance must stay keyed to the cron file alone"
    )
    assert REFRESH_FILE.name != CRON_FILE
    assert re.fullmatch(r"[0-9][0-9]_.+\.sql", REFRESH_FILE.name), (
        "apply_analytical.sh only applies files matching [0-9][0-9]_*.sql"
    )
    assert "src/store/analytical/[0-9][0-9]_*.sql" in APPLY


def test_the_full_tape_pass_is_bounded_in_memory_and_time():
    """mv_b3_monthly_activity is one pass over the whole tape. The settings are
    the ones 04_fact_fund_monthly.sql needed: parallel workers and JIT drove the
    memory peak that killed the connection (#175), and LOCAL survives a pooler
    that ignores a session SET (#207)."""
    body = _code(REFRESH_FILE.read_text(encoding="utf-8"))
    assert re.search(r"SET LOCAL statement_timeout\s*=\s*'\d+min'", body)
    assert "SET LOCAL max_parallel_workers_per_gather = 0" in body
    assert "SET LOCAL jit = off" in body
