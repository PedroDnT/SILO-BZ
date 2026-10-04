"""FCA valores-mobiliários: the published CNPJ↔ticker map (cia_ticker).

Offline: rows are real lines from fca_cia_aberta_valor_mobiliario_2026.csv
(downloaded and verified 2026-08-27), parsed through the same apply_map path
the pipeline uses. No network, no database — upsert_rows is captured.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from src.parsers.field_maps import cia_fca_valor_mobiliario as fm
from src.parsers.mapping import apply_map
from src.pipeline import ingest_cia

# Verbatim structure from the live 2026 file (latin-1, ';'). BSLI3/BSLI4 is
# the important case: one CNPJ, two tickers, two share classes.
_FIXTURE = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;"
    "Valor_Mobiliario;Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;"
    "Codigo_Negociacao;Composicao_BDR_Unit;Mercado;Sigla_Entidade_Administradora;"
    "Entidade_Administradora;Data_Inicio_Negociacao;Data_Fim_Negociacao;Segmento;"
    "Data_Inicio_Listagem;Data_Fim_Listagem\n"
    "00.000.000/0001-91;2026-01-01;3;160576;BCO BRASIL S.A.;"
    "Ações Ordinárias;;;BBAS3;;Bolsa;B3;B3 S.A.;2006-05-31;;"
    "Novo Mercado;1977-07-20;\n"
    "00.000.208/0001-00;2026-01-01;1;154896;BRB BANCO DE BRASILIA S.A.;"
    "Ações Ordinárias;;;bsli3;;Bolsa;B3;B3 S.A.;2010-01-01;;"
    "Básico;1993-09-24;\n"
    "00.000.208/0001-00;2026-01-01;1;154896;BRB BANCO DE BRASILIA S.A.;"
    "Ações Preferenciais;;;BSLI4;;Bolsa;B3;B3 S.A.;2010-01-01;;"
    "Básico;1993-09-24;\n"
    # Unlisted security: no ticker. Kept in the table, skipped by the bridge.
    "00.000.208/0001-00;2026-01-01;1;154896;BRB BANCO DE BRASILIA S.A.;"
    "Debêntures;;;;;Balcão Organizado;B3;B3 S.A.;;;;;\n"
    # Unkeyable: no CNPJ. Must be dropped, never coerced.
    ";2026-01-01;1;0;GHOST;Ações Ordinárias;;;XXXX3;;Bolsa;B3;B3;;;;;\n"
)


def _rows():
    return list(csv.DictReader(io.StringIO(_FIXTURE), delimiter=";"))


class _CaptureConn:
    pass


def _run_ingest(monkeypatch, rows):
    captured = {}

    def fake_upsert(conn, table, records, conflict_columns):
        captured["table"] = table
        captured["records"] = records
        captured["conflict"] = conflict_columns
        return len(records)

    monkeypatch.setattr(ingest_cia, "upsert_rows", fake_upsert)
    n = ingest_cia.ingest_cia_ticker(_CaptureConn(), rows)
    return n, captured


def test_field_map_matches_the_live_header():
    # Every candidate column name must exist in the real header — this is the
    # drift guard that would have caught the FIAGRO rename incident.
    header = _rows()[0].keys()
    for col, (candidates, _t) in fm.FIELD_MAP.items():
        assert any(c in header for c in candidates), (
            f"{col}: none of {candidates} in the live FCA header"
        )


def test_rows_parse_with_published_identifiers(monkeypatch):
    n, cap = _run_ingest(monkeypatch, _rows())
    assert cap["table"] == "cia_ticker"
    assert cap["conflict"] == ",".join(fm.CONFLICT)
    # 4 keyable rows (ghost dropped): BBAS3, BSLI3, BSLI4, debenture-no-ticker
    assert n == 4
    by_ticker = {r["codneg"]: r for r in cap["records"]}
    assert by_ticker["BBAS3"]["cnpj_cia"] == "00000000000191"
    assert by_ticker["BBAS3"]["segmento"] == "Novo Mercado"
    assert str(by_ticker["BBAS3"]["data_refer"]) == "2026-01-01"
    # one CNPJ → two tickers, distinct share classes, from the same source rows
    assert by_ticker["BSLI3"]["cnpj_cia"] == by_ticker["BSLI4"]["cnpj_cia"]
    assert by_ticker["BSLI3"]["valor_mobiliario"].startswith("Ações Ordin")
    assert by_ticker["BSLI4"]["valor_mobiliario"].startswith("Ações Prefer")


def test_ticker_is_uppercased_to_match_the_b3_tape(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    assert all(
        r["codneg"] == r["codneg"].upper()
        for r in cap["records"]
        if r["codneg"] is not None
    )
    assert any(r["codneg"] == "BSLI3" for r in cap["records"])


def test_unlisted_security_is_kept_with_null_ticker(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    no_ticker = [r for r in cap["records"] if r["codneg"] is None]
    assert len(no_ticker) == 1
    assert no_ticker[0]["valor_mobiliario"].startswith("Deb")


def test_unkeyable_row_is_dropped_never_coerced(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    assert all(r["cnpj_cia"] for r in cap["records"])
    assert not any(r.get("codneg") == "XXXX3" for r in cap["records"])


def test_residual_lands_in_raw(monkeypatch):
    _n, cap = _run_ingest(monkeypatch, _rows())
    bbas = next(r for r in cap["records"] if r["codneg"] == "BBAS3")
    assert bbas["raw"].get("Nome_Empresarial") == "BCO BRASIL S.A."


def test_dataset_is_configured_and_wired():
    from src.fetchers.cvm_config import dataset_config

    ds = dataset_config.get_dataset_config("cia_aberta", "fca_valor_mobiliario")
    assert ds["csv_name_pattern"] == "fca_cia_aberta_valor_mobiliario_{year}.csv"
    assert "/DOC/FCA/DADOS/" in ds["url_pattern"]

    # Wired into both entry points — an unwired dataset is never fetched.
    src = Path("src/pipeline/cvm_pipeline.py").read_text(encoding="utf-8")
    assert src.count("self.ingest_cia_fca(year)") >= 2, (
        "ingest_cia_fca must be wired into BOTH daily_update and backfill"
    )
    assert '"cia_ticker",' in src


def test_migration_25_bridge_is_published_mapping_only():
    sql = Path("src/store/migrations/25_cia_ticker.sql").read_text(encoding="utf-8")
    assert "UNIQUE NULLS NOT DISTINCT" in sql
    assert "CREATE OR REPLACE VIEW vw_company_ticker" in sql
    # The bridge must never fall back to name matching or ticker-shape guesses.
    assert "ILIKE" not in sql
    assert "denom" not in sql.lower()
    assert "DISTINCT ON (t.cnpj_cia, t.codneg)" in sql
    assert "t.data_refer DESC, t.versao DESC" in sql


# --- migration 63: is_active means "in the company's newest FCA filing" (#381) ---

_M63 = Path("src/store/migrations/63_company_ticker_active.sql")
_VIEW_COLUMNS = [
    "cnpj_cia",
    "codneg",
    "valor_mobiliario",
    "sigla_classe",
    "mercado",
    "segmento",
    "dt_inicio_neg",
    "dt_fim_neg",
    "is_active",
    "data_refer",
    "versao",
]


def _output_columns(body: str) -> list[str]:
    """The view's output column names, in order, from its SELECT list."""
    select = body[body.index("\n", body.index("SELECT DISTINCT ON")) : body.index("FROM cia_ticker t")]
    # An expression ends where the next "t.<col>," item starts: split on the
    # top-level commas (the only parentheses here hold no commas).
    items = [i.strip() for i in select.split(",") if i.strip()]
    cols = []
    for item in items:
        m = re.search(r"AS\s+(\w+)\s*$", item)
        cols.append(m.group(1) if m else item.rsplit(".", 1)[-1])
    return cols


def _view_body(sql: str) -> str:
    start = sql.index("CREATE OR REPLACE VIEW vw_company_ticker")
    end = sql.index(";", start)
    return sql[start:end]


def test_migration_63_keeps_the_view_shape_and_changes_only_is_active():
    old = _view_body(
        Path("src/store/migrations/25_cia_ticker.sql").read_text(encoding="utf-8")
    )
    new = _view_body(_M63.read_text(encoding="utf-8"))
    # CREATE OR REPLACE VIEW needs the same columns, names and order.
    assert _output_columns(old) == _VIEW_COLUMNS
    assert _output_columns(new) == _VIEW_COLUMNS
    assert "DISTINCT ON (t.cnpj_cia, t.codneg)" in new
    assert "ORDER BY t.cnpj_cia, t.codneg, t.data_refer DESC, t.versao DESC" in new
    assert "WHERE t.codneg IS NOT NULL" in new


def test_migration_63_is_active_needs_the_newest_filing_of_the_company():
    new = _view_body(_M63.read_text(encoding="utf-8"))
    assert "t.dt_fim_neg IS NULL" in new
    assert "t.data_refer = n.data_refer" in new
    assert "t.versao = n.versao" in new
    # The newest filing is taken over ALL of the company's rows, not only the
    # ones that carry a ticker, and not per ticker.
    assert "SELECT DISTINCT ON (cnpj_cia) cnpj_cia, data_refer, versao" in new
    assert "ORDER BY cnpj_cia, data_refer DESC, versao DESC" in new
    assert "FROM cia_ticker\n    ORDER BY" in new
    # Still the published mapping only: no name matching, no ticker shapes.
    sql = _M63.read_text(encoding="utf-8")
    assert "ILIKE" not in sql and "denom" not in sql.lower()


def test_migration_63_is_the_last_definition_and_is_never_a_second_edit_of_25():
    # Migration 25 is historical and stays as shipped (the old is_active); every
    # schema apply replays it and then 63, which puts the new definition back.
    old = Path("src/store/migrations/25_cia_ticker.sql").read_text(encoding="utf-8")
    assert "(t.dt_fim_neg IS NULL) AS is_active" in old
    definers = sorted(
        p.name
        for p in Path("src/store/migrations").glob("*.sql")
        if "CREATE OR REPLACE VIEW vw_company_ticker" in p.read_text(encoding="utf-8")
    )
    assert definers == [
        "25_cia_ticker.sql",
        "63_company_ticker_active.sql",
        "69_company_ticker_liquidity.sql",
    ]
    # schema.sql and the analytical layer do not (re)define the view.
    assert "vw_company_ticker" not in Path("src/store/schema.sql").read_text(
        encoding="utf-8"
    )
    for p in Path("src/store/analytical").glob("*.sql"):
        assert "VIEW public.vw_company_ticker" not in p.read_text(encoding="utf-8")
        assert "VIEW vw_company_ticker" not in p.read_text(encoding="utf-8")


def test_the_behaviour_file_runs_in_ci_and_covers_the_three_cases():
    wf = Path(".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "tests/sql/company_ticker_active_behaviour.sql" in wf
    sql = Path("tests/sql/company_ticker_active_behaviour.sql").read_text(
        encoding="utf-8"
    )
    assert "BEGIN;" in sql and sql.rstrip().endswith("ROLLBACK;")
    # absent from the newest filing, in it, and in it with an end date
    assert "OLDA3=false" in sql and "KEPT3=true" in sql and "ENDD3=false" in sql


# --- migration 69: is_active also needs the ticker to trade (#381 follow-up) ---

_M69 = Path("src/store/migrations/69_company_ticker_liquidity.sql")


def test_migration_69_keeps_the_view_shape_and_migration_63_conditions():
    new = _view_body(_M69.read_text(encoding="utf-8"))
    assert _output_columns(new) == _VIEW_COLUMNS
    assert "DISTINCT ON (t.cnpj_cia, t.codneg)" in new
    assert "ORDER BY t.cnpj_cia, t.codneg, t.data_refer DESC, t.versao DESC" in new
    assert "WHERE t.codneg IS NOT NULL" in new
    # Migration 63's newest-filing rule stays.
    assert "t.dt_fim_neg IS NULL" in new
    assert "t.data_refer = n.data_refer" in new and "t.versao = n.versao" in new
    assert "SELECT DISTINCT ON (cnpj_cia) cnpj_cia, data_refer, versao" in new


def test_migration_69_is_active_needs_five_sessions_in_thirty_days():
    """The owner's threshold (2026-10-04): at least 5 distinct cash-market
    sessions with trades in the last 30 calendar days. Rows are executed in
    tests/sql/company_ticker_active_behaviour.sql; this pins the text."""
    new = re.sub(r"\s+", " ", _view_body(_M69.read_text(encoding="utf-8")))
    assert "SELECT count(DISTINCT b.trade_date) FROM b3_cotahist b" in new
    assert "b.codneg = t.codneg" in new
    assert "b.tpmerc = '010'" in new, "cash market only, the partial index's predicate"
    assert "b.negocios > 0" in new
    assert "b.trade_date > current_date - 30" in new
    assert ") >= 5) AS is_active" in new
    # Still the published mapping only: no name matching.
    sql = _M69.read_text(encoding="utf-8")
    assert "ILIKE" not in sql and "denom" not in sql.lower()


def test_the_behaviour_file_covers_the_liquidity_cases():
    sql = Path("tests/sql/company_ticker_active_behaviour.sql").read_text(encoding="utf-8")
    for case in ("LIQ53=true", "THIN3=false", "STAL3=false", "ZERO3=false", "BRDS3=true", "NOTP3=false"):
        assert case in sql
