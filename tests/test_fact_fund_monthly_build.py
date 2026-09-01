"""fact_fund_monthly build: the shape Daily CVM Ingest #207 died on.

#177 seeded the FIP unique-key collision and that apply now succeeds. #207
(run 33535880218) then failed later in the same CREATE, with
`connection to server was lost` at the statement's closing semicolon, and
05/07/11 died at the same ~4m44s because the session pooler had dropped the
client while DROP ... CASCADE still held AccessExclusiveLock.

Two things have to stay true or that apply fails the same way again:

1. apply_analytical.sh must probe the socket the way pg_client.py already
   does — a quiet CREATE sends nothing on the wire, and CI uses the
   session pooler.
2. The FI branch must scan cvm_fi_diario once. Two passes (snapshot DISTINCT
   ON + a second GROUP BY for flows) is what made the CREATE miss the
   pooler's idle cap after #177 added FIP de-dup work. MAX(captc_mes) is
   load-bearing: the window is already at fund-month grain, so SUM would
   multiply inflows by the number of subclasses.
"""
from __future__ import annotations

import re
from pathlib import Path

import src.store.pg_client as pg

ROOT = Path(__file__).resolve().parents[1]
FACT_SQL = (ROOT / "src" / "store" / "analytical" / "04_fact_fund_monthly.sql").read_text(
    encoding="utf-8"
)
APPLY_SH = (ROOT / "scripts" / "apply_analytical.sh").read_text(encoding="utf-8")


def _uncommented(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def test_apply_analytical_sends_the_same_tcp_keepalives_as_ingest():
    """Idle CREATE MV must not wait for the kernel's 2h keepalive default.

    Daily CVM Ingest #207 dropped at 4m44s through the session pooler with
    `server closed the connection unexpectedly`. pg_client.py already probes
    after 30s; the analytical apply was the one psql path that did not.
    """
    assert "keepalives=1" in APPLY_SH
    assert "keepalives_idle=30" in APPLY_SH
    assert "keepalives_interval=10" in APPLY_SH
    assert "keepalives_count=3" in APPLY_SH
    assert pg._KEEPALIVES == dict(
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )
    # Never echo the rewritten URL: it carries POSTGRES_URL's password.
    assert not re.search(r"echo .*\$POSTGRES_URL", APPLY_SH)


def test_fi_branch_scans_cvm_fi_diario_once():
    body = _uncommented(FACT_SQL).lower()
    assert body.count("from cvm_fi_diario") == 1, (
        "a second pass over cvm_fi_diario is the memory and wall-clock cost "
        "that let the session pooler drop the client during CREATE"
    )
    assert "fi_flows as" not in body
    assert "join fi_flows" not in body
    assert "sum(d.captc_dia) over" in body
    assert "sum(d.resg_dia) over" in body
    assert "not exists" in body and "cvm_etf_registry" in body


def test_fi_fund_level_flows_are_not_summed_across_subclasses():
    # The window is PARTITION BY (cnpj, month). Every subclass row of that
    # fund-month carries the same captc_mes; SUM would double-count.
    body = _uncommented(FACT_SQL).lower()
    assert "max(p.captc_mes)" in body
    assert "max(p.resg_mes)" in body
    assert "sum(p.captc_mes)" not in body
    assert "sum(p.resg_mes)" not in body


def test_fact_build_stays_single_threaded_without_jit():
    body = _uncommented(FACT_SQL).lower()
    assert "set local max_parallel_workers_per_gather = 0" in body
    assert "set local jit = off" in body
    assert "set local statement_timeout = '30min'" in body
