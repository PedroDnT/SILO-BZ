"""ZIP member selection must never substitute a different dataset.

Guards the bug found on 2026-08-13: FII `trimestral` was configured with
csv_name_pattern = "inf_trimestral_fii_{year}.csv", a member that has never
existed in inf_trimestral_fii_{year}.zip. The fetcher fell back to "the first
CSV in the archive", so every trimestral ingest actually parsed
inf_trimestral_fii_alienacao_imovel_{year}.csv — a register of properties the
funds SOLD — and wrote those rows into cvm_fii_periodic labelled
doc_type='trimestral'. Same defect hit FII `anual`, FI `hist_inf_diario`
(January twelve times) and FI `hist_cda` (the FI-Imobiliário file).

A row must be what its provenance says it is, so a pattern matching no member is
now fatal. These tests pin that, and pin the real member names of every
multi-member archive so a future config edit that stops resolving fails here
instead of silently ingesting the wrong file.
"""

import io
import zipfile

import pytest

from src.fetchers.cvm_config import dataset_config
from src.fetchers.cvm_fetcher import CVMFetcher

# Real 2025 member list of inf_trimestral_fii_2025.zip (verified against
# dados.cvm.gov.br). Note there is no "inf_trimestral_fii_2025.csv".
FII_TRIMESTRAL_MEMBERS = [
    "inf_trimestral_fii_alienacao_imovel_2025.csv",
    "inf_trimestral_fii_alienacao_terreno_2025.csv",
    "inf_trimestral_fii_aquisicao_imovel_2025.csv",
    "inf_trimestral_fii_aquisicao_terreno_2025.csv",
    "inf_trimestral_fii_ativo_2025.csv",
    "inf_trimestral_fii_ativo_garantia_rentabilidade_2025.csv",
    "inf_trimestral_fii_complemento_2025.csv",
    "inf_trimestral_fii_direito_2025.csv",
    "inf_trimestral_fii_geral_2025.csv",
    "inf_trimestral_fii_imovel_2025.csv",
    "inf_trimestral_fii_imovel_desempenho_2025.csv",
    "inf_trimestral_fii_imovel_renda_acabado_contrato_2025.csv",
    "inf_trimestral_fii_imovel_renda_acabado_inquilino_2025.csv",
    "inf_trimestral_fii_rentabilidade_efetiva_2025.csv",
    "inf_trimestral_fii_resultado_contabil_financeiro_2025.csv",
    "inf_trimestral_fii_terreno_2025.csv",
]


def _zip_with(members) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in members:
            zf.writestr(name, f"COL_A;COL_B\n{name};1\n".encode("latin-1"))
    return buf.getvalue()


class TestFallbackIsFatal:
    def test_pattern_matching_no_member_raises(self):
        fetcher = CVMFetcher()
        content = _zip_with(FII_TRIMESTRAL_MEMBERS)
        with pytest.raises(ValueError) as exc:
            fetcher._extract_csv_from_zip(
                content, "inf_trimestral_fii_{year}.csv", 2025, None
            )
        msg = str(exc.value)
        assert "not found in archive" in msg
        # the error must name what the archive actually holds, so the operator
        # can fix csv_name_pattern without downloading the file by hand
        assert "inf_trimestral_fii_geral_2025.csv" in msg
        assert "csv_name_pattern" in msg

    def test_no_silent_substitution_of_the_first_member(self):
        """The old behaviour: fall through to the alphabetically-first CSV."""
        fetcher = CVMFetcher()
        content = _zip_with(FII_TRIMESTRAL_MEMBERS)
        with pytest.raises(ValueError):
            fetcher._extract_csv_from_zip(
                content, "inf_trimestral_fii_{year}.csv", 2025, None
            )
        # ... and prove the member it *would* have picked is the wrong dataset
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            assert zf.namelist()[0] == "inf_trimestral_fii_alienacao_imovel_2025.csv"

    def test_archive_without_any_csv_raises(self):
        fetcher = CVMFetcher()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", b"nothing here")
        with pytest.raises(ValueError, match="No CSV file found"):
            fetcher._extract_csv_from_zip(buf.getvalue(), "anything_{year}.csv", 2025, None)

    def test_ambiguous_pattern_raises(self):
        """Two members the pattern cannot choose between is an error, not a coin flip."""
        fetcher = CVMFetcher()
        content = _zip_with(["v1/x_geral_2025.csv", "v2/x_geral_2025.csv"])
        with pytest.raises(ValueError, match="ambiguous"):
            fetcher._extract_csv_from_zip(content, "x_geral_{year}.csv", 2025, None)

    def test_exact_basename_wins_over_longer_sibling(self):
        """A pattern that is a prefix of a sibling still resolves exactly."""
        fetcher = CVMFetcher()
        content = _zip_with(["inf_trimestral_fii_imovel_2025.csv",
                             "inf_trimestral_fii_imovel_desempenho_2025.csv"])
        text = fetcher._extract_csv_from_zip(
            content, "inf_trimestral_fii_imovel_{year}.csv", 2025, None
        )
        assert "inf_trimestral_fii_imovel_2025.csv" in text
        assert "desempenho" not in text


class TestConfiguredPatternsResolve:
    """Every configured pattern must hit exactly one member of the real archive."""

    @pytest.mark.parametrize(
        "doc_type,expected_member",
        [
            ("trimestral_geral", "inf_trimestral_fii_geral_2025.csv"),
            ("trimestral_complemento", "inf_trimestral_fii_complemento_2025.csv"),
            ("trimestral_imovel", "inf_trimestral_fii_imovel_2025.csv"),
        ],
    )
    def test_fii_trimestral_members_resolve(self, doc_type, expected_member):
        cfg = dataset_config.get_dataset_config("fii", doc_type)
        fetcher = CVMFetcher()
        text = fetcher._extract_csv_from_zip(
            _zip_with(FII_TRIMESTRAL_MEMBERS), cfg["csv_name_pattern"], 2025, None
        )
        assert expected_member in text

    def test_fii_anual_resolves_to_the_geral_member(self):
        # Real 2025 member list of inf_anual_fii_2025.zip — no inf_anual_fii_2025.csv.
        members = [
            "inf_anual_fii_ativo_adquirido_2025.csv",
            "inf_anual_fii_ativo_transacao_2025.csv",
            "inf_anual_fii_ativo_valor_contabil_2025.csv",
            "inf_anual_fii_complemento_2025.csv",
            "inf_anual_fii_diretor_responsavel_2025.csv",
            "inf_anual_fii_distribuicao_cotistas_2025.csv",
            "inf_anual_fii_experiencia_profissional_2025.csv",
            "inf_anual_fii_geral_2025.csv",
            "inf_anual_fii_prestador_servico_2025.csv",
            "inf_anual_fii_processo_2025.csv",
            "inf_anual_fii_processo_semelhante_2025.csv",
            "inf_anual_fii_representante_cotista_2025.csv",
        ]
        cfg = dataset_config.get_dataset_config("fii", "anual")
        text = CVMFetcher()._extract_csv_from_zip(
            _zip_with(members), cfg["csv_name_pattern"], 2025, None
        )
        assert "inf_anual_fii_geral_2025.csv" in text

    def test_fi_hist_diario_selects_the_requested_month(self):
        """HIST holds 12 monthly members — the config must not ask for a yearly one."""
        members = [f"inf_diario_fi_2020{m:02d}.csv" for m in range(1, 13)]
        cfg = dataset_config.get_dataset_config("fi", "hist_inf_diario")
        fetcher = CVMFetcher()
        for month in (1, 7, 12):
            text = fetcher._extract_csv_from_zip(
                _zip_with(members), cfg["csv_name_pattern"], 2020, month
            )
            assert f"inf_diario_fi_2020{month:02d}.csv" in text

    def test_fi_hist_cda_targets_blc_1_like_the_monthly_dataset(self):
        members = ["cda_fiim_2022.csv"] + [f"cda_fi_BLC_{i}_2022.csv" for i in range(1, 9)] + [
            "cda_fi_PL_2022.csv"
        ]
        cfg = dataset_config.get_dataset_config("fi", "hist_cda")
        text = CVMFetcher()._extract_csv_from_zip(
            _zip_with(members), cfg["csv_name_pattern"], 2022, None
        )
        assert "cda_fi_BLC_1_2022.csv" in text

    @pytest.mark.parametrize("doc_type,member", [
        ("hist_cda_acoes", "cda_fi_BLC_4_2022.csv"),
        ("hist_cda_cotas", "cda_fi_BLC_2_2022.csv"),
    ])
    def test_fi_hist_holdings_target_their_own_blocks(self, doc_type, member):
        """Blocks 4 and 2 of the archive hist_cda reads block 1 of.

        Verified against the real 2005, 2015 and 2022 archives: both members are
        present in all of them.
        """
        members = ["cda_fiim_2022.csv"] + [f"cda_fi_BLC_{i}_2022.csv" for i in range(1, 9)] + [
            "cda_fi_PL_2022.csv"
        ]
        cfg = dataset_config.get_dataset_config("fi", doc_type)
        text = CVMFetcher()._extract_csv_from_zip(
            _zip_with(members), cfg["csv_name_pattern"], 2022, None
        )
        assert member in text

    def test_retired_fii_trimestral_doc_type_is_gone(self):
        """The broken doc_type must not be reachable, aliases included."""
        assert "trimestral" not in dataset_config.get_available_doc_types("fii")
        with pytest.raises(ValueError, match="Unknown document type"):
            dataset_config.get_dataset_config("fii", "trimestral")


class TestYearlyArchivesKeepTheirMonths:
    """The second variant of the bug this module is named for.

    Selecting the right member is only half of it. `hist_cda` resolved to the
    correct CSV and then threw away eleven twelfths of it a different way:
    ingest_fi_hist_cda called ingest_fi_cda(rows, year, 1), and ingest_fi_cda
    overwrote every row's period with January. Under the
    (cnpj, period, tp_aplic, tp_ativo) key, December's portfolio overwrote
    January's, so each pre-2023 year of cvm_fi_cda held one month.

    Same outcome as the member-substitution bugs above — a table that looks
    populated and is not — reached through the parse stage instead of the fetch
    stage, which is why the earlier fix did not catch it.
    """

    ROWS = [
        {"CNPJ_FUNDO": "00.102.322/0001-41", "DT_COMPTC": f"2022-{m:02d}-28",
         "TP_APLIC": "Títulos Públicos", "TP_ATIVO": "Tesouro Selic",
         "QT_POS_FINAL": f"{m}000.0", "VL_MERC_POS_FINAL": f"{m}0000.00"}
        for m in range(1, 13)
    ]

    def _capture(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            "src.pipeline.ingest_fi.upsert_rows",
            lambda conn, table, rows, **kw: seen.setdefault("rows", rows) and 0 or len(rows),
        )
        return seen

    def test_month_none_keeps_all_twelve(self, monkeypatch):
        from src.pipeline.ingest_fi import ingest_fi_cda

        seen = self._capture(monkeypatch)
        ingest_fi_cda(object(), self.ROWS, 2022, None)
        periods = {r["period"] for r in seen["rows"]}
        assert len(periods) == 12, f"a yearly archive collapsed to {len(periods)} month(s)"

    def test_an_explicit_month_still_wins_for_monthly_files(self, monkeypatch):
        """The monthly path is unchanged: one file is one competency month.

        DT_COMPTC there can be any day of the month, and the caller knows which
        month it asked for, so the argument stays authoritative.
        """
        from src.pipeline.ingest_fi import ingest_fi_cda

        seen = self._capture(monkeypatch)
        ingest_fi_cda(object(), self.ROWS[:1], 2026, 6)
        assert {str(r["period"]) for r in seen["rows"]} == {"2026-06-01"}

    def test_the_hist_caller_passes_none(self):
        """The fix lives at the call site; a literal month there reintroduces it."""
        from pathlib import Path

        body = (Path(__file__).resolve().parents[1] / "src/pipeline/cvm_pipeline.py").read_text()
        start = body.index("async def ingest_fi_hist_cda(")
        hist = body[start : body.index("return rows_inserted", start)]
        assert "ingest_fi_cda(self._supabase, chunk, year, None)" in hist
        assert "chunk, year, 1)" not in hist, "a fixed month collapses the year again"
