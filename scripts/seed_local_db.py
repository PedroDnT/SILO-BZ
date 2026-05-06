"""
Seed a local DuckDB database with real CVM data fetched live from dados.cvm.gov.br.

Usage:
    python scripts/seed_local_db.py             # full seed (~15 min)
    python scripts/seed_local_db.py --skip-fi   # skip FI inf_diario (large), ~2 min
    python scripts/seed_local_db.py --db PATH   # custom DB file path

DB file default: .local_db/iliquid_local.duckdb
Requires internet. No Supabase credentials needed.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb

from src.fetchers.cvm_fetcher import CVMFetcher
from src.pipeline.cvm_pipeline import (
    _find_cnpj_field,
    _find_field,
    _find_inadimpl,
    _normalize_cnpj,
    _period_to_date,
)

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".local_db", "iliquid_local.duckdb")

# ---------------------------------------------------------------------------
# DuckDB schema (partitioning removed; JSONB→JSON; BIGSERIAL→BIGINT)
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS cvm_fi_diario (
    cnpj          TEXT    NOT NULL,
    tp_fundo      TEXT,
    dt_comptc     DATE    NOT NULL,
    vl_total      DECIMAL(20,6),
    vl_quota      DECIMAL(20,12),
    vl_patrim_liq DECIMAL(20,6),
    captc_dia     DECIMAL(20,6),
    resg_dia      DECIMAL(20,6),
    nr_cotst      INTEGER,
    raw           JSON    NOT NULL,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, dt_comptc)
);

CREATE TABLE IF NOT EXISTS cvm_fi_cda (
    cnpj              TEXT NOT NULL,
    period            DATE NOT NULL,
    tp_aplic          TEXT,
    tp_ativo          TEXT,
    vl_merc_pos_final DECIMAL(20,6),
    raw               JSON NOT NULL,
    fetched_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, period, tp_aplic, tp_ativo)
);

CREATE TABLE IF NOT EXISTS cvm_fidc_mensal (
    cnpj          TEXT    NOT NULL,
    period        DATE    NOT NULL,
    vl_total      DECIMAL(20,6),
    vl_quota      DECIMAL(20,12),
    vl_patrim_liq DECIMAL(20,6),
    vl_inadimpl   DECIMAL(20,6),
    nr_cotst      INTEGER,
    raw           JSON    NOT NULL,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, period)
);

CREATE TABLE IF NOT EXISTS cvm_fip_periodic (
    cnpj          TEXT,
    doc_type      TEXT    NOT NULL,
    period_year   INTEGER NOT NULL,
    vl_patrim_liq DECIMAL(20,6),
    raw           JSON    NOT NULL,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, doc_type, period_year)
);

CREATE TABLE IF NOT EXISTS cvm_fii_mensal (
    cnpj          TEXT    NOT NULL,
    period        DATE    NOT NULL,
    doc_subtype   TEXT    NOT NULL DEFAULT 'geral',
    vl_patrim_liq DECIMAL(20,6),
    raw           JSON    NOT NULL,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, period, doc_subtype)
);

CREATE TABLE IF NOT EXISTS cvm_securit_mensal (
    instrument_type TEXT    NOT NULL,
    period_year     INTEGER NOT NULL,
    cnpj_securit    TEXT,
    dt_emissao      DATE,
    dt_vencto       DATE,
    vl_emissao      DECIMAL(20,6),
    vl_unit         DECIMAL(20,6),
    qt_titulos      DECIMAL(20,0),
    vl_total        DECIMAL(20,6),
    tp_ativo        TEXT,
    raw             JSON    NOT NULL,
    fetched_at      TIMESTAMPTZ DEFAULT NOW()
);
"""

SEP = "=" * 64


# ---------------------------------------------------------------------------
# Normalizers (mirror cvm_pipeline.py ingest methods)
# ---------------------------------------------------------------------------

def _norm_fi_diario(row: Dict) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row, prefer_suffix="classe") or _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if len(cnpj) != 14:
        return None
    return {
        "cnpj":          cnpj,
        "tp_fundo":      _find_field(row, "TP_FUNDO_CLASSE"),
        "dt_comptc":     _find_field(row, "DT_COMPTC"),
        "vl_total":      _find_field(row, "VL_TOTAL"),
        "vl_quota":      _find_field(row, "VL_QUOTA"),
        "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
        "captc_dia":     _find_field(row, "CAPTC_DIA"),
        "resg_dia":      _find_field(row, "RESG_DIA"),
        "nr_cotst":      _find_field(row, "NR_COTST"),
        "raw":           json.dumps(row, ensure_ascii=False),
    }


def _norm_fi_cda(row: Dict, year: int, month: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if len(cnpj) != 14:
        return None
    return {
        "cnpj":               cnpj,
        "period":             f"{year}-{month:02d}-01",
        "tp_aplic":           _find_field(row, "TP_APLIC"),
        "tp_ativo":           _find_field(row, "TP_ATIVO"),
        "vl_merc_pos_final":  _find_field(row, "VL_MERC_POS_FINAL"),
        "raw":                json.dumps(row, ensure_ascii=False),
    }


def _norm_fidc_mensal(row: Dict, year: int, month: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if len(cnpj) != 14:
        return None
    period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
    return {
        "cnpj":          cnpj,
        "period":        period,
        "vl_total":      _find_field(row, "VL_TOTAL", "VL_CARTEIRA_TOTAL"),
        "vl_quota":      _find_field(row, "VL_QUOTA"),
        "vl_patrim_liq": _find_field(row, "TAB_IV_A_VL_PL", "VL_PATRIM_LIQ"),
        "vl_inadimpl":   _find_inadimpl(row),
        "nr_cotst":      _find_field(row, "NR_COTST"),
        "raw":           json.dumps(row, ensure_ascii=False),
    }


def _norm_fip(row: Dict, doc_type: str, year: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
    return {
        "cnpj":          cnpj,
        "doc_type":      doc_type,
        "period_year":   year,
        "vl_patrim_liq": _find_field(row, "VL_PATRIM_LIQ"),
        "raw":           json.dumps(row, ensure_ascii=False),
    }


def _norm_fii_mensal(row: Dict, doc_type: str, year: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if not cnpj:
        return None
    period_str = _find_field(row, "Data_Referencia", "DT_COMPTC")
    period = period_str[:7] + "-01" if period_str and len(period_str) >= 7 else f"{year}-01-01"
    if "geral" in doc_type:
        subtype = "geral"
    elif "complemento" in doc_type:
        subtype = "complemento"
    else:
        subtype = "ativo_passivo"
    return {
        "cnpj":          cnpj,
        "period":        period,
        "doc_subtype":   subtype,
        "vl_patrim_liq": _find_field(row, "Patrimonio_Liquido", "VL_PATRIM_LIQ"),
        "raw":           json.dumps(row, ensure_ascii=False),
    }


def _norm_securit(row: Dict, instrument_type: str, year: int) -> Dict:
    cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
    return {
        "instrument_type": instrument_type,
        "period_year":     year,
        "cnpj_securit":    cnpj,
        "dt_emissao":      _find_field(row, "Data_Referencia", "DT_EMISSAO"),
        "dt_vencto":       _find_field(row, "DT_VENCTO", "DT_VENCIMENTO"),
        "vl_emissao":      _find_field(row, "Valor_Atualizado_Emissao", "VL_EMISSAO"),
        "vl_unit":         _find_field(row, "VL_UNIT", "PU_EMISSAO"),
        "qt_titulos":      _find_field(row, "QT_TITULOS"),
        "vl_total":        _find_field(row, "Ativo", "VL_TOTAL"),
        "tp_ativo":        _find_field(row, "TP_ATIVO"),
        "raw":             json.dumps(row, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

# Tables without a clean PK (nullable composite keys) use plain INSERT
_NO_CONFLICT_TABLES = {"cvm_securit_mensal"}


def _insert(conn: duckdb.DuckDBPyConnection, table: str, cols: List[str], records: List[Dict]) -> int:
    if not records:
        return 0
    placeholders = ", ".join(["?" for _ in cols])
    col_list = ", ".join(cols)
    keyword = "INSERT" if table in _NO_CONFLICT_TABLES else "INSERT OR IGNORE"
    sql = f"{keyword} INTO {table} ({col_list}) VALUES ({placeholders})"
    data = [[r.get(c) for c in cols] for r in records]
    conn.executemany(sql, data)
    return len(data)


# ---------------------------------------------------------------------------
# Per-entity seed tasks
# ---------------------------------------------------------------------------

async def seed_fi_diario(conn, fetcher, months):
    cols = ["cnpj","tp_fundo","dt_comptc","vl_total","vl_quota","vl_patrim_liq",
            "captc_dia","resg_dia","nr_cotst","raw"]
    total = 0
    for year, month in months:
        t0 = time.time()
        print(f"  FI inf_diario {year}-{month:02d} … fetching", end="", flush=True)
        raw_rows = await fetcher.fetch("fi", "inf_diario", year=year, month=month)
        records = [r for row in raw_rows if (r := _norm_fi_diario(row))]
        n = _insert(conn, "cvm_fi_diario", cols, records)
        total += n
        print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
    return total


async def seed_fi_cda(conn, fetcher, months):
    cols = ["cnpj","period","tp_aplic","tp_ativo","vl_merc_pos_final","raw"]
    total = 0
    for year, month in months:
        t0 = time.time()
        print(f"  FI cda {year}-{month:02d} … fetching", end="", flush=True)
        raw_rows = await fetcher.fetch("fi", "cda", year=year, month=month)
        records = [r for row in raw_rows if (r := _norm_fi_cda(row, year, month))]
        n = _insert(conn, "cvm_fi_cda", cols, records)
        total += n
        print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
    return total


async def seed_fidc_mensal(conn, fetcher, months):
    cols = ["cnpj","period","vl_total","vl_quota","vl_patrim_liq","vl_inadimpl","nr_cotst","raw"]
    total = 0
    for year, month in months:
        t0 = time.time()
        print(f"  FIDC mensal {year}-{month:02d} … fetching", end="", flush=True)
        raw_rows = await fetcher.fetch("fidc", "mensal", year=year, month=month)
        records = [_norm_fidc_mensal(row, year, month) for row in raw_rows]
        records = [r for r in records if r]
        n = _insert(conn, "cvm_fidc_mensal", cols, records)
        total += n
        print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
    return total


async def seed_fip(conn, fetcher, years):
    cols = ["cnpj","doc_type","period_year","vl_patrim_liq","raw"]
    total = 0
    for year in years:
        t0 = time.time()
        print(f"  FIP inf_quadrimestral {year} … fetching", end="", flush=True)
        raw_rows = await fetcher.fetch("fip", "inf_quadrimestral", year=year)
        records = [_norm_fip(row, "inf_quadrimestral", year) for row in raw_rows]
        n = _insert(conn, "cvm_fip_periodic", cols, records)
        total += n
        print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
    return total


async def seed_fii(conn, fetcher, years):
    cols = ["cnpj","period","doc_subtype","vl_patrim_liq","raw"]
    total = 0
    for doc_type in ["mensal_geral", "mensal_complemento"]:
        for year in years:
            t0 = time.time()
            print(f"  FII {doc_type} {year} … fetching", end="", flush=True)
            try:
                raw_rows = await fetcher.fetch("fii", doc_type, year=year)
                records = [r for row in raw_rows if (r := _norm_fii_mensal(row, doc_type, year))]
                n = _insert(conn, "cvm_fii_mensal", cols, records)
                total += n
                print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
            except Exception as e:
                print(f"  ERROR: {e}")
    return total


async def seed_securit(conn, fetcher, years):
    cols = ["instrument_type","period_year","cnpj_securit","dt_emissao","dt_vencto",
            "vl_emissao","vl_unit","qt_titulos","vl_total","tp_ativo","raw"]
    total = 0
    for instrument in ["cra_mensal", "cri_mensal"]:
        for year in years:
            t0 = time.time()
            print(f"  SECURIT {instrument} {year} … fetching", end="", flush=True)
            try:
                raw_rows = await fetcher.fetch("securit", instrument, year=year)
                records = [_norm_securit(row, instrument, year) for row in raw_rows]
                n = _insert(conn, "cvm_securit_mensal", cols, records)
                total += n
                print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
            except Exception as e:
                print(f"  ERROR: {e}")
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(db_path: str, skip_fi: bool):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    print(f"\n{SEP}")
    print(f"  CVM LOCAL DB SEED")
    print(f"  DB: {db_path}")
    print(SEP)

    conn = duckdb.connect(db_path)
    conn.execute(SCHEMA)
    print("  Schema applied.")

    fetcher = CVMFetcher()
    t_start = time.time()

    fi_months  = [(2025, 1), (2025, 2), (2025, 3)]
    cda_months = [(2025, 3)]
    fidc_months = [(2025, 1), (2025, 2), (2025, 3)]
    fip_years   = [2024]
    fii_years   = [2024]
    securit_years = [2024]

    print(f"\n--- FI ---")
    if not skip_fi:
        await seed_fi_diario(conn, fetcher, fi_months)
    else:
        print("  FI inf_diario skipped (--skip-fi)")
    await seed_fi_cda(conn, fetcher, cda_months)

    print(f"\n--- FIDC ---")
    await seed_fidc_mensal(conn, fetcher, fidc_months)

    print(f"\n--- FIP ---")
    await seed_fip(conn, fetcher, fip_years)

    print(f"\n--- FII ---")
    await seed_fii(conn, fetcher, fii_years)

    print(f"\n--- SECURIT ---")
    await seed_securit(conn, fetcher, securit_years)

    conn.close()
    elapsed = time.time() - t_start
    print(f"\n{SEP}")
    print(f"  Seed complete in {elapsed:.0f}s. DB: {db_path}")
    print(SEP)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fi", action="store_true", help="Skip FI inf_diario (large file)")
    parser.add_argument("--db", default=DEFAULT_DB, help="DuckDB file path")
    args = parser.parse_args()
    asyncio.run(main(args.db, args.skip_fi))
