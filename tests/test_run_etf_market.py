"""The ETF market snapshot runs as its own daily job (#868).

It used to run at the end of run_daily, with the contract these tests pin: an
unset APIFY_TOKEN skips without failing, a skipped scrape (Apify refused, 0
rows) is not a failure, and a scrape that ran and failed exits non-zero.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.pipeline.run_etf_market as rem


@pytest.mark.asyncio
async def test_absent_apify_token_skips_and_is_not_a_failure(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    ingest = AsyncMock()
    with patch.object(rem, "ingest_etf_market", new=ingest), \
         patch.object(rem, "get_pg_client", return_value=MagicMock()) as conn:
        await rem.main()
    ingest.assert_not_awaited()
    conn.assert_not_called()  # no connection opened for a no-op


@pytest.mark.asyncio
async def test_scrape_failure_exits_nonzero(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    with patch.object(rem, "ingest_etf_market",
                      new=AsyncMock(side_effect=RuntimeError("scrape blocked"))), \
         patch.object(rem, "get_pg_client", return_value=MagicMock()):
        with pytest.raises(SystemExit) as exc:
            await rem.main()
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_scrape_skipped_is_not_a_failure(monkeypatch):
    """ingest_etf_market returns 0 when Apify skips (403 actor-not-approved,
    403 usage hard limit, 408 run-timeout-exceeded, ABORTED): it writes the
    `skipped` audit row itself. Per-variant behaviour: test_etf_market.py."""
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    with patch.object(rem, "ingest_etf_market", new=AsyncMock(return_value=0)), \
         patch.object(rem, "get_pg_client", return_value=MagicMock()):
        await rem.main()  # no SystemExit


@pytest.mark.asyncio
async def test_runs_without_the_cvm_probe(monkeypatch):
    """Not a CVM source: CVM_REACHABLE=false must not stop it (it reads the
    stored cvm_etf_registry), as it did not in run_daily (#866)."""
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    monkeypatch.setenv("CVM_REACHABLE", "false")
    ingest = AsyncMock(return_value=5)
    with patch.object(rem, "ingest_etf_market", new=ingest), \
         patch.object(rem, "get_pg_client", return_value=MagicMock()):
        await rem.main()
    ingest.assert_awaited_once()
