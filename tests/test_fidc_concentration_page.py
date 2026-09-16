"""The /fidc page shows the concentration tabs the way they are filed.

Four Evidence sources over migration 38's tables. Each is pinned to: the
completeness clamp in its `latest` CTE (a bare max(period) lands on a
partially-filed month), zero-row safety, no `_pct` column (Evidence's format
tag would multiply percentage points by 100), the hierarchy rule (lettered
sectors only — never a parent with its children), the never-reranked rule
(rank 1 is read, not recomputed) and the share range guard.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "dashboard" / "sources" / "supabase"
PAGE = ROOT / "dashboard" / "pages" / "fidc.md"
SOURCE_NAMES = ("fidc_sector_mix", "fidc_scr_ladder", "fidc_concentration_top", "fidc_cedentes_top")


def _sql(name: str) -> str:
    text = (SOURCES / f"{name}.sql").read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("--")).lower()


def test_every_source_exists_clamps_to_the_complete_period_and_avoids_the_pct_tag():
    for name in SOURCE_NAMES:
        sql = _sql(name)
        assert "latest_complete_period('fidc')" in sql, f"{name}: no completeness clamp"
        assert re.search(r"max\(period\)\s+as\s+period\s+from\s+cvm_fidc_\w+\s+where\s+period\s*<=", sql), (
            f"{name}: the clamp must be in the `latest` CTE, not per fact row")
        assert not re.search(r"\w+_pct\b", sql), f"{name}: _pct is an Evidence format tag"


def test_structural_sources_always_return_their_axis():
    for name, n in (("fidc_sector_mix", 11), ("fidc_scr_ladder", 9)):
        sql = _sql(name)
        assert "cross join lateral unnest(" in sql, f"{name}: fixed axis via unnest"
        labels = re.search(r"unnest\(\s*array\[(.*?)\]", sql, re.S).group(1)
        assert labels.count("'") == 2 * n, f"{name}: expected {n} fixed labels"


def test_row_guarded_sources_survive_an_empty_table():
    for name in ("fidc_concentration_top", "fidc_cedentes_top"):
        sql = _sql(name)
        assert "row_guard" in sql and "left join" in sql and "on true" in sql, f"{name}: no zero-row guard"


def test_sector_mix_sums_the_lettered_level_only():
    sql = _sql("fidc_sector_mix")
    for col in ("vl_a_indust", "vl_b_imobil", "vl_c_comerc", "vl_d_serv", "vl_e_agroneg", "vl_f_financ",
                "vl_g_credito", "vl_h_factor", "vl_i_setor_publico", "vl_j_judicial", "vl_k_marca"):
        assert f"sum(s.{col})" in sql, f"missing sector {col}"
    assert not re.search(r"vl_[a-k]\d_", sql), "a numbered member would be counted inside its parent"
    assert "vl_carteira" not in sql, "share is of the summed lines, not of TOTAL"


def test_scr_ladder_serves_both_ladders():
    sql = _sql("fidc_scr_ladder")
    for grade in ("aa", "a", "b", "c", "d", "e", "f", "g", "h"):
        assert f"vl_devedor_{grade}" in sql and f"vl_oper_{grade}" in sql


def test_concentration_reads_rank_1_as_filed_and_joins_the_same_filing():
    sql = _sql("fidc_concentration_top")
    assert "filter (where k.seq = 1)" in sql, "rank 1 is CVM's rank, read not recomputed"
    assert "row_number()" not in sql and "rank()" not in sql
    assert "s.cnpj = r.cnpj and s.period = r.period" in sql, "tab VIII joins tab II of the same filing"
    assert "s.vl_carteira >= 1e7" in sql, "the R$10mm floor"
    assert "least(" not in sql and "greatest(" not in sql, "ratios above 100% are shown as filed, never capped"


def test_cedentes_top_never_sums_shares_and_range_checks_them():
    sql = _sql("fidc_cedentes_top")
    assert "sum(c.pr_cedente" not in sql, "a percent of one block plus a percent of another is not a number"
    assert "between 0 and 100" in sql and "n_share_outliers" in sql
    assert "count(distinct c.cnpj) filter (where c.seq = 1)" in sql
    assert "cia.cnpj_cia = o.cpf_cnpj_cedente" in sql, "names only through cia_company by CNPJ"
    assert "ilike" not in sql and "similarity(" not in sql
    assert "vt.is_active" in sql


def test_page_declares_every_source_and_the_caveats():
    page = PAGE.read_text(encoding="utf-8")
    for name in SOURCE_NAMES:
        assert f"```sql {name}\nselect * from supabase.{name}\n```" in page, name
        assert f"data={{{name}}}" in page, f"{name} declared but unused"
    assert "anonymized ranks" in page
    assert "not capped" in page
    assert "never adds shares across funds" in page
    assert "sums the lettered level only" in page
    assert "Tab X exists from 2023-10 only" in page
    assert "R$10mm" in page
