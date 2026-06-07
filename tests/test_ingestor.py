"""
Unit tests for the consolidated pipeline — supabase_client helpers,
CVM helper functions, and BACEN ingestor.

All Supabase and external HTTP calls are mocked so these run offline.
"""

import pytest
from datetime import date
from typing import Any, Dict, List
from unittest.mock import MagicMock, AsyncMock, patch


class _FakeCursor:
    """Minimal psycopg2-style cursor usable as a context manager."""

    def __init__(self, fetch: List[Any] | None = None):
        self._fetch = fetch or []
        self.executed: List[Any] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._fetch


class _FakeClient:
    """Returns the same _FakeCursor each call so tests can inspect it."""

    def __init__(self, fetch: List[Any] | None = None):
        self.cursor_obj = _FakeCursor(fetch)

    def cursor(self):
        return self.cursor_obj


# ---------------------------------------------------------------------------
# supabase_client helpers
# ---------------------------------------------------------------------------

class TestUpsertRows:
    """Tests for the supabase_client.upsert_rows chunking helper."""

    def _make_client(self):
        """Return a psycopg2-compatible client stub with a no-op cursor."""
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        client = MagicMock()
        client.cursor.return_value = cur
        client.reconnect = MagicMock()
        return client

    def test_upsert_empty_rows_returns_zero(self):
        from src.store.pg_client import upsert_rows
        client = self._make_client()
        assert upsert_rows(client, "test_table", []) == 0
        client.cursor.assert_not_called()

    def test_upsert_small_batch_single_call(self):
        from src.store.pg_client import upsert_rows
        call_sizes: List[int] = []

        with patch("psycopg2.extras.execute_values") as mock_ev:
            def _capture(cur, sql, vals, **kw):
                call_sizes.append(len(vals))
            mock_ev.side_effect = _capture

            rows = [{"id": i} for i in range(10)]
            result = upsert_rows(self._make_client(), "test_table", rows)

        assert result == 10
        assert call_sizes == [10]

    def test_upsert_large_batch_chunked(self, monkeypatch):
        """Rows > 500 should be split into multiple execute_values calls."""
        from src.store.pg_client import upsert_rows
        call_sizes: List[int] = []

        monkeypatch.delenv("CVM_UPSERT_CHUNK_SIZE", raising=False)

        with patch("psycopg2.extras.execute_values") as mock_ev:
            def _capture(cur, sql, vals, **kw):
                call_sizes.append(len(vals))
            mock_ev.side_effect = _capture

            rows = [{"id": i} for i in range(1100)]
            result = upsert_rows(self._make_client(), "big_table", rows)

        assert result == 1100
        assert call_sizes == [500, 500, 100]

    def test_upsert_deduplicates_when_conflict_columns_set(self):
        """When conflict_columns is passed, duplicate keys collapse to last write."""
        from src.store.pg_client import upsert_rows
        captured_vals: List[Any] = []

        with patch("psycopg2.extras.execute_values") as mock_ev:
            def _capture(cur, sql, vals, **kw):
                captured_vals.extend(vals)
            mock_ev.side_effect = _capture

            rows = [
                {"cnpj": "A", "period": "2025-03-31", "k": "x", "v": 1},
                {"cnpj": "B", "period": "2025-03-31", "k": "y", "v": 2},
                {"cnpj": "A", "period": "2025-03-31", "k": "x", "v": 99},
            ]
            result = upsert_rows(
                self._make_client(), "t", rows, conflict_columns="cnpj,period,k"
            )

        assert result == 2
        assert len(captured_vals) == 2
        vals_sorted = sorted(captured_vals, key=lambda t: t[0])
        assert vals_sorted[0][3] == 99   # cnpj=A, last write wins
        assert vals_sorted[1][3] == 2    # cnpj=B

    def test_upsert_no_dedup_when_conflict_columns_unset(self):
        """Without conflict_columns, duplicate inputs are kept as-is."""
        from src.store.pg_client import upsert_rows
        captured_vals: List[Any] = []

        with patch("psycopg2.extras.execute_values") as mock_ev:
            def _capture(cur, sql, vals, **kw):
                captured_vals.extend(vals)
            mock_ev.side_effect = _capture

            rows = [{"id": 1}, {"id": 1}, {"id": 1}]
            result = upsert_rows(self._make_client(), "t", rows)

        assert result == 3
        assert len(captured_vals) == 3

    def test_upsert_chunk_size_can_be_overridden_by_env(self, monkeypatch):
        from src.store.pg_client import upsert_rows
        call_sizes: List[int] = []

        monkeypatch.setenv("CVM_UPSERT_CHUNK_SIZE", "250")

        with patch("psycopg2.extras.execute_values") as mock_ev:
            def _capture(cur, sql, vals, **kw):
                call_sizes.append(len(vals))
                assert kw["page_size"] == 250
            mock_ev.side_effect = _capture

            rows = [{"id": i} for i in range(600)]
            result = upsert_rows(self._make_client(), "env_table", rows)

        assert result == 600
        assert call_sizes == [250, 250, 100]


# ---------------------------------------------------------------------------
# cvm_ingestor helpers
# ---------------------------------------------------------------------------

class TestCVMIngestorHelpers:
    """Tests for field extraction and CNPJ normalisation helpers."""

    def test_normalize_cnpj_strips_punctuation(self):
        from src.pipeline.cvm_pipeline import _normalize_cnpj
        assert _normalize_cnpj("12.345.678/0001-90") == "12345678000190"

    def test_normalize_cnpj_already_digits(self):
        from src.pipeline.cvm_pipeline import _normalize_cnpj
        assert _normalize_cnpj("12345678000190") == "12345678000190"

    def test_normalize_cnpj_empty_string(self):
        from src.pipeline.cvm_pipeline import _normalize_cnpj
        assert _normalize_cnpj("") == ""

    def test_find_field_first_match(self):
        from src.pipeline.cvm_pipeline import _find_field
        row = {"DENOM_SOCIAL": "FUNDO X", "NM_FUNDO": "FUNDO Y"}
        assert _find_field(row, "DENOM_SOCIAL", "NM_FUNDO") == "FUNDO X"

    def test_find_field_fallback_match(self):
        from src.pipeline.cvm_pipeline import _find_field
        row = {"NM_FUNDO": "FUNDO Y"}
        assert _find_field(row, "DENOM_SOCIAL", "NM_FUNDO") == "FUNDO Y"

    def test_find_field_none_when_missing(self):
        from src.pipeline.cvm_pipeline import _find_field
        row = {"OTHER": "value"}
        assert _find_field(row, "DENOM_SOCIAL") is None

    def test_find_field_empty_string_returns_none(self):
        from src.pipeline.cvm_pipeline import _find_field
        row = {"DENOM_SOCIAL": ""}
        assert _find_field(row, "DENOM_SOCIAL") is None

    def test_find_cnpj_field_prefers_fundo_suffix(self):
        from src.pipeline.cvm_pipeline import _find_cnpj_field
        row = {"CNPJ_SECURIT": "11111111000111", "CNPJ_FUNDO": "22222222000122"}
        assert _find_cnpj_field(row, prefer_suffix="fundo") == "22222222000122"

    def test_find_cnpj_field_fallback_any_cnpj(self):
        from src.pipeline.cvm_pipeline import _find_cnpj_field
        row = {"CNPJ_FUNDO": "12345678000190"}
        assert _find_cnpj_field(row, prefer_suffix="securit") == "12345678000190"

    def test_find_inadimpl_matches_inadimpl_key(self):
        from src.pipeline.cvm_pipeline import _find_inadimpl
        row = {"VL_INADIMPL": "5000.00", "VL_QUOTA": "100"}
        assert _find_inadimpl(row) == "5000.00"

    def test_find_inadimpl_returns_none_when_absent(self):
        from src.pipeline.cvm_pipeline import _find_inadimpl
        row = {"VL_QUOTA": "100", "VL_PATRIM_LIQ": "1000000"}
        assert _find_inadimpl(row) is None

    def test_daily_month_pairs_handles_year_rollover(self):
        from src.pipeline.cvm_pipeline import _daily_month_pairs
        assert _daily_month_pairs(date(2026, 1, 15)) == [(2025, 12), (2026, 1)]

    def test_trailing_months_orders_oldest_first(self):
        from src.pipeline.cvm_pipeline import _trailing_months
        assert _trailing_months(date(2026, 6, 7), 4) == [
            (2026, 3), (2026, 4), (2026, 5), (2026, 6),
        ]

    def test_trailing_months_crosses_year_boundary(self):
        from src.pipeline.cvm_pipeline import _trailing_months
        assert _trailing_months(date(2026, 2, 1), 4) == [
            (2025, 11), (2025, 12), (2026, 1), (2026, 2),
        ]

    def test_iter_month_pairs_respects_available_from(self):
        from src.pipeline.cvm_pipeline import _iter_month_pairs
        months = _iter_month_pairs([2024, 2025], date(2025, 8, 10), available_from=date(2025, 5, 1))
        assert months == [(2025, 5), (2025, 6), (2025, 7), (2025, 8)]

    def test_resolve_securit_instrument_type_uses_explicit_map(self):
        from src.pipeline.ingest_securit import _resolve_instrument_type
        assert _resolve_instrument_type("cri_fluxo") == "cri_mensal"


class TestCVMIngestorOrchestration:
    @pytest.mark.asyncio
    async def test_daily_update_core_scope_skips_yearly_entities(self, monkeypatch):
        from src.pipeline.cvm_pipeline import CVMIngestor

        monkeypatch.setenv("CVM_DAILY_SCOPE", "core")
        monkeypatch.setenv("CVM_DAILY_CONCURRENCY", "2")

        ingestor = CVMIngestor.__new__(CVMIngestor)
        ingestor.ingest_fund_registry = AsyncMock(return_value=0)
        ingestor.ingest_fund_registry_cvm175 = AsyncMock(return_value=0)
        ingestor.ingest_etf_registry = AsyncMock(return_value=0)
        ingestor._refresh_etf_metrics = MagicMock()
        ingestor.ingest_fi_diario = AsyncMock(return_value=1)
        ingestor.ingest_fi_cda = AsyncMock(return_value=1)
        ingestor.ingest_fi_perfil = AsyncMock(return_value=1)
        ingestor.ingest_fidc_mensal = AsyncMock(return_value=1)
        ingestor.ingest_fidc_tranche = AsyncMock(return_value=1)
        ingestor.ingest_fidc_tranche_flows = AsyncMock(return_value=1)
        ingestor.ingest_fidc_aging = AsyncMock(return_value=1)
        ingestor.ingest_fiagro_mensal = AsyncMock(return_value=1)
        ingestor.ingest_fip_periodic = AsyncMock(return_value=1)
        ingestor.ingest_fii_mensal = AsyncMock(return_value=1)
        ingestor.ingest_fii_periodic = AsyncMock(return_value=1)
        ingestor.ingest_securit_mensal = AsyncMock(return_value=1)
        ingestor.ingest_securit_serie = AsyncMock(return_value=1)
        ingestor.ingest_securit_fluxo = AsyncMock(return_value=1)
        ingestor.ingest_securit_dfin = AsyncMock(return_value=1)

        totals = await ingestor.daily_update()

        assert totals["cvm_fi_diario"] > 0
        assert totals["cvm_fidc_mensal"] > 0
        assert totals["cvm_fiagro_mensal"] > 0
        assert totals["cvm_fip_periodic"] == 0
        assert totals["cvm_fii_mensal"] == 0
        assert totals["cvm_securit_mensal"] == 0
        assert ingestor.ingest_fund_registry.await_count == 1
        # ETF is a distinct entity but kept in core scope: it still refreshes,
        # and its materialized metrics are refreshed once after ingest.
        assert ingestor.ingest_etf_registry.await_count == 1
        assert ingestor._refresh_etf_metrics.call_count == 1
        assert ingestor.ingest_fip_periodic.await_count == 0
        assert ingestor.ingest_fii_mensal.await_count == 0
        assert ingestor.ingest_securit_mensal.await_count == 0


class TestResolveDailyEntities:
    """ETF is a first-class daily-scope entity, gated on its own token."""

    def test_all_scope_includes_etf(self, monkeypatch):
        from src.pipeline.cvm_pipeline import _resolve_daily_entities
        monkeypatch.setenv("CVM_DAILY_SCOPE", "all")
        assert "etf" in _resolve_daily_entities()

    def test_core_scope_includes_etf(self, monkeypatch):
        from src.pipeline.cvm_pipeline import _resolve_daily_entities
        monkeypatch.setenv("CVM_DAILY_SCOPE", "core")
        assert "etf" in _resolve_daily_entities()

    def test_etf_selectable_on_its_own(self, monkeypatch):
        from src.pipeline.cvm_pipeline import _resolve_daily_entities
        monkeypatch.setenv("CVM_DAILY_SCOPE", "etf")
        assert _resolve_daily_entities() == {"etf"}

    def test_explicit_scope_without_etf_excludes_it(self, monkeypatch):
        from src.pipeline.cvm_pipeline import _resolve_daily_entities
        monkeypatch.setenv("CVM_DAILY_SCOPE", "fidc,fii")
        assert "etf" not in _resolve_daily_entities()


class TestRefreshEtfMetrics:
    """ETF metrics are materialized; the pipeline refreshes them after ingest."""

    def test_refreshes_both_matviews_daily_before_latest(self):
        from src.pipeline.cvm_pipeline import CVMIngestor

        executed: List[str] = []

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                executed.append(sql)

        class _Client:
            def cursor(self):
                return _Cur()

        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = _Client()
        ing._refresh_etf_metrics()

        # etf_latest is derived from etf_daily, so etf_daily must refresh first;
        # CONCURRENTLY relies on the unique indexes added in migration 06.
        assert executed == [
            "REFRESH MATERIALIZED VIEW CONCURRENTLY etf_daily",
            "REFRESH MATERIALIZED VIEW CONCURRENTLY etf_latest",
        ]


class TestMonthlyTargets:
    """Gap-aware trailing window for monthly datasets (self-heals CVM's lag)."""

    def test_always_includes_current_and_previous_month(self):
        from src.pipeline.cvm_pipeline import CVMIngestor, _daily_month_pairs
        today = date(2026, 6, 7)
        ing = CVMIngestor.__new__(CVMIngestor)
        # Whole trailing window already loaded -> only the base months remain.
        from src.pipeline.cvm_pipeline import _trailing_months, _DAILY_LOOKBACK_MONTHS
        ing._supabase = _FakeClient(fetch=_trailing_months(today, _DAILY_LOOKBACK_MONTHS))
        targets = ing._monthly_targets("fidc", "mensal", today)
        assert targets == _daily_month_pairs(today)

    def test_fills_recently_published_gaps(self):
        from src.pipeline.cvm_pipeline import (
            CVMIngestor, _daily_month_pairs, _trailing_months, _DAILY_LOOKBACK_MONTHS,
        )
        today = date(2026, 6, 7)
        base = _daily_month_pairs(today)
        window = _trailing_months(today, _DAILY_LOOKBACK_MONTHS)
        # Only the newest month is loaded; older in-window months are gaps.
        loaded = [base[-1]]
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = _FakeClient(fetch=loaded)
        targets = ing._monthly_targets("fidc", "mensal_tab_x2", today)
        for ym in base:                       # base always present
            assert ym in targets
        for ym in window:                     # every unloaded in-window month healed
            if ym not in loaded:
                assert ym in targets
        assert targets == sorted(set(targets))  # sorted, deduped

    def test_falls_back_to_base_on_db_error(self):
        from src.pipeline.cvm_pipeline import CVMIngestor, _daily_month_pairs

        class _Boom:
            def cursor(self):
                raise RuntimeError("db down")

        today = date(2026, 6, 7)
        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = _Boom()
        # Degrades to current+previous only — never a deep-history fetch storm.
        assert ing._monthly_targets("fi", "inf_diario", today) == _daily_month_pairs(today)


class TestLogFinishStatus:
    """A not-yet-published month (404) is 'skipped', not a false 'error'."""

    def _status_for(self, error):
        from src.pipeline.cvm_pipeline import CVMIngestor
        ing = CVMIngestor.__new__(CVMIngestor)
        client = _FakeClient()
        ing._supabase = client
        ing._log_finish("run-id", 0, error)
        _sql, params = client.cursor_obj.executed[-1]
        return params[1]  # status is the 2nd bound parameter

    def test_data_not_found_is_skipped(self):
        assert self._status_for("Data not found at https://dados.cvm.gov.br/...202606...") == "skipped"

    def test_other_error_stays_error(self):
        assert self._status_for("No CSV file found in ZIP. Files: []") == "error"

    def test_success_is_ok(self):
        from src.pipeline.cvm_pipeline import CVMIngestor
        ing = CVMIngestor.__new__(CVMIngestor)
        client = _FakeClient()
        ing._supabase = client
        ing._log_finish("run-id", 42)
        _sql, params = client.cursor_obj.executed[-1]
        assert params[1] == "ok"
        assert params[0] == 42

    def test_refresh_swallows_errors(self):
        from src.pipeline.cvm_pipeline import CVMIngestor

        class _Client:
            def cursor(self):
                raise RuntimeError("db down")

        ing = CVMIngestor.__new__(CVMIngestor)
        ing._supabase = _Client()
        # Must not raise — a failed refresh should not abort the ingest run.
        ing._refresh_etf_metrics()

    def test_disabled_flag_parsing(self, monkeypatch):
        from src.pipeline.cvm_pipeline import _etf_refresh_disabled

        monkeypatch.delenv("CVM_SKIP_ETF_REFRESH", raising=False)
        assert _etf_refresh_disabled() is False
        for v in ("1", "true", "TRUE", "yes"):
            monkeypatch.setenv("CVM_SKIP_ETF_REFRESH", v)
            assert _etf_refresh_disabled() is True
        for v in ("0", "", "no", "false"):
            monkeypatch.setenv("CVM_SKIP_ETF_REFRESH", v)
            assert _etf_refresh_disabled() is False


def _mocked_daily_ingestor():
    """A CVMIngestor with every ingest_* method (and the matview refresh) mocked,
    for exercising daily_update's scope/refresh gating without a DB."""
    from src.pipeline.cvm_pipeline import CVMIngestor

    ing = CVMIngestor.__new__(CVMIngestor)
    for name in (
        "ingest_fund_registry", "ingest_fund_registry_cvm175", "ingest_etf_registry",
        "ingest_fi_diario", "ingest_fi_cda", "ingest_fi_perfil",
        "ingest_fidc_mensal", "ingest_fidc_tranche", "ingest_fidc_tranche_flows",
        "ingest_fidc_aging", "ingest_fiagro_mensal", "ingest_fip_periodic",
        "ingest_fii_mensal", "ingest_fii_periodic", "ingest_securit_mensal",
        "ingest_securit_serie", "ingest_securit_fluxo", "ingest_securit_dfin",
    ):
        setattr(ing, name, AsyncMock(return_value=0))
    ing._refresh_etf_metrics = MagicMock()
    return ing


class TestDailyEtfRefreshGating:
    """etf_daily is a matview over cvm_fi_diario, so an FI ingest (not just an ETF
    one) must refresh it — unless the refresh is deferred to an external step."""

    @pytest.mark.asyncio
    async def test_fi_only_scope_refreshes_metrics(self, monkeypatch):
        monkeypatch.setenv("CVM_DAILY_SCOPE", "fi")
        monkeypatch.delenv("CVM_SKIP_ETF_REFRESH", raising=False)
        ing = _mocked_daily_ingestor()
        await ing.daily_update()
        assert ing._refresh_etf_metrics.call_count == 1

    @pytest.mark.asyncio
    async def test_skip_env_defers_refresh(self, monkeypatch):
        monkeypatch.setenv("CVM_DAILY_SCOPE", "core")
        monkeypatch.setenv("CVM_SKIP_ETF_REFRESH", "1")
        ing = _mocked_daily_ingestor()
        await ing.daily_update()
        assert ing._refresh_etf_metrics.call_count == 0

    @pytest.mark.asyncio
    async def test_scope_without_fi_or_etf_skips_refresh(self, monkeypatch):
        monkeypatch.setenv("CVM_DAILY_SCOPE", "fidc,securit")
        monkeypatch.delenv("CVM_SKIP_ETF_REFRESH", raising=False)
        ing = _mocked_daily_ingestor()
        await ing.daily_update()
        assert ing._refresh_etf_metrics.call_count == 0


# ---------------------------------------------------------------------------
# BacenIngestor — ingest_sgs
# ---------------------------------------------------------------------------

class TestBacenIngestorSGS:
    @pytest.mark.asyncio
    async def test_ingest_sgs_flattens_multi_series(self):
        from src.pipeline.bacen_pipeline import BacenIngestor

        # BacenClient returns one record per date with all series as columns
        mock_records = [
            {
                "date": "2024-01-31",
                "SELIC_META": 11.75,
                "CDI": 11.65,
                "IPCA": 4.51,
                # Other series absent from this record — should be skipped
            }
        ]
        upserted: List[Dict] = []

        def _fake_upsert(client, table, rows, **kw):
            upserted.extend(rows)
            return len(rows)

        with patch("src.pipeline.bacen_pipeline.BacenClient") as mock_client_cls, \
             patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=_fake_upsert):
            mock_client = mock_client_cls.return_value
            mock_client.get_sgs_series = AsyncMock(return_value=mock_records)
            ingestor = BacenIngestor()
            count = await ingestor.ingest_sgs("2024-01-01", "2024-01-31")

        # 3 series present in mock record → 3 rows
        assert count == 3
        codes_seen = {r["series_name"] for r in upserted}
        assert codes_seen == {"SELIC_META", "CDI", "IPCA"}
        selic_row = next(r for r in upserted if r["series_name"] == "SELIC_META")
        assert selic_row["reference_date"] == "2024-01-31"
        assert selic_row["value"] == pytest.approx(11.75)

    @pytest.mark.asyncio
    async def test_ingest_sgs_empty_response_returns_zero(self):
        from src.pipeline.bacen_pipeline import BacenIngestor

        with patch("src.pipeline.bacen_pipeline.BacenClient") as mock_client_cls, \
             patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.bacen_pipeline.upsert_rows", return_value=0):
            mock_client = mock_client_cls.return_value
            mock_client.get_sgs_series = AsyncMock(return_value=[])
            ingestor = BacenIngestor()
            count = await ingestor.ingest_sgs("2024-01-01")

        assert count == 0

    @pytest.mark.asyncio
    async def test_ingest_sgs_fetch_error_returns_zero(self):
        from src.pipeline.bacen_pipeline import BacenIngestor

        with patch("src.pipeline.bacen_pipeline.BacenClient") as mock_client_cls, \
             patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.bacen_pipeline.upsert_rows", return_value=0):
            mock_client = mock_client_cls.return_value
            mock_client.get_sgs_series = AsyncMock(side_effect=Exception("BCB unreachable"))
            ingestor = BacenIngestor()
            count = await ingestor.ingest_sgs("2024-01-01")

        assert count == 0


# ---------------------------------------------------------------------------
# BacenIngestor — ingest_ptax
# ---------------------------------------------------------------------------

class TestBacenIngestorPTAX:
    @pytest.mark.asyncio
    async def test_ingest_ptax_usd_maps_rates(self):
        from src.pipeline.bacen_pipeline import BacenIngestor

        mock_records = [
            {"date": "2024-01-31", "cotacaoCompra": 4.9765, "cotacaoVenda": 4.9770}
        ]
        upserted: List[Dict] = []

        def _fake_upsert(client, table, rows, **kw):
            upserted.extend(rows)
            return len(rows)

        with patch("src.pipeline.bacen_pipeline.BacenClient") as mock_client_cls, \
             patch("src.pipeline.bacen_pipeline.get_pg_client", return_value=MagicMock()), \
             patch("src.pipeline.bacen_pipeline.upsert_rows", side_effect=_fake_upsert), \
             patch("src.pipeline.bacen_pipeline.PTAX_CURRENCIES", ["USD"]):
            mock_client = mock_client_cls.return_value
            mock_client.get_ptax_dolar_periodo = AsyncMock(return_value=mock_records)
            ingestor = BacenIngestor()
            count = await ingestor.ingest_ptax("2024-01-01", "2024-01-31")

        assert count == 1
        row = upserted[0]
        assert row["currency"] == "USD"
        assert row["buy_rate"] == pytest.approx(4.9765)
        assert row["sell_rate"] == pytest.approx(4.9770)
