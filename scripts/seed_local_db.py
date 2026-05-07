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

CREATE TABLE IF NOT EXISTS cvm_fidc_tranche (
    cnpj               TEXT    NOT NULL,
    period             DATE    NOT NULL,
    classe_serie       TEXT    NOT NULL,
    qt_cota            DECIMAL(20,8),
    vl_cota            DECIMAL(20,8),
    vl_rentab_mes      DECIMAL(10,6),
    pr_desemp_esperado DECIMAL(10,6),
    pr_desemp_real     DECIMAL(10,6),
    raw                JSON,
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, period, classe_serie)
);

CREATE TABLE IF NOT EXISTS cvm_fidc_tranche_flows (
    cnpj         TEXT    NOT NULL,
    period       DATE    NOT NULL,
    classe_serie TEXT    NOT NULL,
    tp_oper      TEXT    NOT NULL,
    vl_total     DECIMAL(20,6),
    qt_cota      DECIMAL(20,8),
    fetched_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, period, classe_serie, tp_oper)
);

CREATE TABLE IF NOT EXISTS cvm_securit_serie (
    instrument_type           TEXT    NOT NULL,
    cnpj_securit              TEXT,
    codigo_identificacao      TEXT    NOT NULL,
    data_referencia           DATE,
    classe                    TEXT,
    numero_serie              INTEGER,
    tipo_oferta               TEXT,
    codigo_cetip              TEXT,
    codigo_isin               TEXT,
    data_vencimento           DATE,
    situacao                  TEXT,
    valor_total_integralizado DECIMAL(20,6),
    taxa_juros                TEXT,
    pagamento_periodicidade   TEXT,
    quantidade_certificados   DECIMAL(20,0),
    valor_certificados        DECIMAL(20,6),
    rendimentos               DECIMAL(20,6),
    amortizacoes              DECIMAL(20,6),
    rentabilidade             DECIMAL(20,8),
    classificacao_risco_atual TEXT,
    indice_subordinacao_minimo DECIMAL(10,6),
    raw                       JSON,
    fetched_at                TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cvm_securit_fluxo (
    instrument_type                   TEXT NOT NULL,
    cnpj_securit                      TEXT,
    codigo_identificacao              TEXT NOT NULL,
    data_referencia                   DATE,
    recebimentos_direitos_creditorios DECIMAL(20,6),
    pagamentos_despesas               DECIMAL(20,6),
    pagamentos_classe_senior          DECIMAL(20,6),
    pagamentos_senior_principal       DECIMAL(20,6),
    pagamentos_senior_juros           DECIMAL(20,6),
    pagamentos_mezanino               DECIMAL(20,6),
    pagamentos_mezanino_principal     DECIMAL(20,6),
    pagamentos_mezanino_juros         DECIMAL(20,6),
    pagamentos_junior                 DECIMAL(20,6),
    pagamentos_junior_principal       DECIMAL(20,6),
    pagamentos_junior_juros           DECIMAL(20,6),
    variacao_liquida_caixa            DECIMAL(20,6),
    raw                               JSON,
    fetched_at                        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cvm_fidc_aging (
    cnpj                 TEXT    NOT NULL,
    period               DATE    NOT NULL,
    vl_prazo_30          DECIMAL(20,6),
    vl_prazo_60          DECIMAL(20,6),
    vl_prazo_90          DECIMAL(20,6),
    vl_prazo_120         DECIMAL(20,6),
    vl_prazo_150         DECIMAL(20,6),
    vl_prazo_180         DECIMAL(20,6),
    vl_prazo_360         DECIMAL(20,6),
    vl_prazo_720         DECIMAL(20,6),
    vl_prazo_1080        DECIMAL(20,6),
    vl_prazo_maior_1080  DECIMAL(20,6),
    vl_inad_30           DECIMAL(20,6),
    vl_inad_60           DECIMAL(20,6),
    vl_inad_90           DECIMAL(20,6),
    vl_inad_120          DECIMAL(20,6),
    vl_inad_150          DECIMAL(20,6),
    vl_inad_180          DECIMAL(20,6),
    vl_inad_360          DECIMAL(20,6),
    vl_inad_720          DECIMAL(20,6),
    vl_inad_1080         DECIMAL(20,6),
    vl_inad_maior_1080   DECIMAL(20,6),
    vl_total_inad        DECIMAL(20,6),
    raw                  JSON,
    fetched_at           TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cnpj, period)
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


def _norm_fidc_tranche(row: Dict, year: int, month: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if not cnpj:
        return None
    period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
    return {
        "cnpj":               cnpj,
        "period":             period,
        "classe_serie":       _find_field(row, "TAB_X_CLASSE_SERIE") or "",
        "qt_cota":            _find_field(row, "TAB_X_QT_COTA"),
        "vl_cota":            _find_field(row, "TAB_X_VL_COTA"),
        "raw":                json.dumps(row, ensure_ascii=False),
    }


def _norm_fidc_tranche_flows(row: Dict, year: int, month: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if not cnpj:
        return None
    period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
    return {
        "cnpj":        cnpj,
        "period":      period,
        "classe_serie": _find_field(row, "TAB_X_CLASSE_SERIE") or "",
        "tp_oper":     _find_field(row, "TAB_X_TP_OPER") or "",
        "vl_total":    _find_field(row, "TAB_X_VL_TOTAL"),
        "qt_cota":     _find_field(row, "TAB_X_QT_COTA"),
    }


def _norm_fidc_aging(row: Dict, year: int, month: int) -> Optional[Dict]:
    cnpj_raw = _find_cnpj_field(row)
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else ""
    if not cnpj:
        return None
    period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
    return {
        "cnpj":               cnpj,
        "period":             period,
        "vl_prazo_30":        _find_field(row, "TAB_VI_A_VL_1",  "TAB_VI_VL_PRAZO_1_30"),
        "vl_prazo_60":        _find_field(row, "TAB_VI_A_VL_2",  "TAB_VI_VL_PRAZO_31_60"),
        "vl_prazo_90":        _find_field(row, "TAB_VI_A_VL_3",  "TAB_VI_VL_PRAZO_61_90"),
        "vl_prazo_120":       _find_field(row, "TAB_VI_A_VL_4",  "TAB_VI_VL_PRAZO_91_120"),
        "vl_prazo_150":       _find_field(row, "TAB_VI_A_VL_5",  "TAB_VI_VL_PRAZO_121_150"),
        "vl_prazo_180":       _find_field(row, "TAB_VI_A_VL_6",  "TAB_VI_VL_PRAZO_151_180"),
        "vl_prazo_360":       _find_field(row, "TAB_VI_A_VL_7",  "TAB_VI_VL_PRAZO_181_360"),
        "vl_prazo_720":       _find_field(row, "TAB_VI_A_VL_8",  "TAB_VI_VL_PRAZO_361_720"),
        "vl_prazo_1080":      _find_field(row, "TAB_VI_A_VL_9",  "TAB_VI_VL_PRAZO_721_1080"),
        "vl_prazo_maior_1080": _find_field(row, "TAB_VI_A_VL_10", "TAB_VI_VL_PRAZO_MAIS_1080"),
        "vl_inad_30":         _find_field(row, "TAB_VI_B_VL_1",  "TAB_VI_VL_INAD_1_30"),
        "vl_inad_60":         _find_field(row, "TAB_VI_B_VL_2",  "TAB_VI_VL_INAD_31_60"),
        "vl_inad_90":         _find_field(row, "TAB_VI_B_VL_3",  "TAB_VI_VL_INAD_61_90"),
        "vl_inad_120":        _find_field(row, "TAB_VI_B_VL_4",  "TAB_VI_VL_INAD_91_120"),
        "vl_inad_150":        _find_field(row, "TAB_VI_B_VL_5",  "TAB_VI_VL_INAD_121_150"),
        "vl_inad_180":        _find_field(row, "TAB_VI_B_VL_6",  "TAB_VI_VL_INAD_151_180"),
        "vl_inad_360":        _find_field(row, "TAB_VI_B_VL_7",  "TAB_VI_VL_INAD_181_360"),
        "vl_inad_720":        _find_field(row, "TAB_VI_B_VL_8",  "TAB_VI_VL_INAD_361_720"),
        "vl_inad_1080":       _find_field(row, "TAB_VI_B_VL_9",  "TAB_VI_VL_INAD_721_1080"),
        "vl_inad_maior_1080": _find_field(row, "TAB_VI_B_VL_10", "TAB_VI_VL_INAD_MAIS_1080"),
        "vl_total_inad":      _find_field(row, "TAB_VI_B_VL_TOTAL", "TAB_VI_VL_TOTAL_INAD"),
        "raw":                json.dumps(row, ensure_ascii=False),
    }


def _norm_securit_serie(row: Dict, doc_type: str) -> Dict:
    cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
    instrument_type = doc_type.rsplit("_", 1)[0] + "_mensal"
    return {
        "instrument_type":           instrument_type,
        "cnpj_securit":              cnpj,
        "codigo_identificacao":      _find_field(row, "Codigo_Identificacao", "CNPJ_Fundo") or "",
        "data_referencia":           _find_field(row, "Data_Referencia", "DT_COMPETENCIA"),
        "classe":                    _find_field(row, "Classe"),
        "numero_serie":              _find_field(row, "Numero_Serie"),
        "tipo_oferta":               _find_field(row, "Tipo_Oferta"),
        "codigo_cetip":              _find_field(row, "Codigo_CETIP"),
        "codigo_isin":               _find_field(row, "Codigo_ISIN"),
        "data_vencimento":           _find_field(row, "Data_Vencimento"),
        "situacao":                  _find_field(row, "Situacao"),
        "valor_total_integralizado": _find_field(row, "Valor_Total_Integralizado"),
        "taxa_juros":                _find_field(row, "Taxa_Juros"),
        "pagamento_periodicidade":   _find_field(row, "Pagamento_Periodicidade"),
        "quantidade_certificados":   _find_field(row, "Quantidade_Certificados"),
        "valor_certificados":        _find_field(row, "Valor_Certificados"),
        "rendimentos":               _find_field(row, "Rendimentos"),
        "amortizacoes":              _find_field(row, "Amortizacoes"),
        "rentabilidade":             _find_field(row, "Rentabilidade"),
        "classificacao_risco_atual": _find_field(row, "Classificacao_Risco_Atual"),
        "indice_subordinacao_minimo": _find_field(row, "Indice_Subordinacao_Minimo"),
        "raw":                       json.dumps(row, ensure_ascii=False),
    }


def _norm_securit_fluxo(row: Dict, doc_type: str) -> Dict:
    cnpj_raw = _find_cnpj_field(row, prefer_suffix="securit")
    cnpj = _normalize_cnpj(cnpj_raw) if cnpj_raw else None
    instrument_type = doc_type.rsplit("_", 1)[0] + "_mensal"
    return {
        "instrument_type":                   instrument_type,
        "cnpj_securit":                      cnpj,
        "codigo_identificacao":              _find_field(row, "Codigo_Identificacao", "CNPJ_Fundo") or "",
        "data_referencia":                   _find_field(row, "Data_Referencia", "DT_COMPETENCIA"),
        "recebimentos_direitos_creditorios": _find_field(row, "Recebimentos_Direitos_Creditorios"),
        "pagamentos_despesas":               _find_field(row, "Pagamentos_Despesas"),
        "pagamentos_classe_senior":          _find_field(row, "Pagamentos_Classe_Senior"),
        "pagamentos_senior_principal":       _find_field(row, "Pagamentos_Classe_Senior_Principal", "Pagamentos_Senior_Principal"),
        "pagamentos_senior_juros":           _find_field(row, "Pagamentos_Classe_Senior_Juros", "Pagamentos_Senior_Juros"),
        "pagamentos_mezanino":               _find_field(row, "Pagamentos_Classe_Subordinada_Mezanino"),
        "pagamentos_mezanino_principal":     _find_field(row, "Pagamentos_Classe_Subordinada_Mezanino_Principal"),
        "pagamentos_mezanino_juros":         _find_field(row, "Pagamentos_Classe_Subordinada_Mezanino_Juros"),
        "pagamentos_junior":                 _find_field(row, "Pagamentos_Classe_Subordinada_Junior"),
        "pagamentos_junior_principal":       _find_field(row, "Pagamentos_Classe_Subordinada_Junior_Principal"),
        "pagamentos_junior_juros":           _find_field(row, "Pagamentos_Classe_Subordinada_Junior_Juros"),
        "variacao_liquida_caixa":            _find_field(row, "Variacao_Liquida_Caixa"),
        "raw":                               json.dumps(row, ensure_ascii=False),
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


async def seed_fidc_tranche(conn, fetcher, months):
    total = 0
    for year, month in months:
        t0 = time.time()
        print(f"  FIDC tranche {year}-{month:02d} … fetching", end="", flush=True)
        try:
            rows_x2 = await fetcher.fetch("fidc", "mensal_tab_X2", year=year, month=month)
            rows_x3 = await fetcher.fetch("fidc", "mensal_tab_X3", year=year, month=month)
            rows_x6 = await fetcher.fetch("fidc", "mensal_tab_X6", year=year, month=month)

            def _key(row):
                cnpj = _normalize_cnpj(_find_cnpj_field(row) or "")
                period = _period_to_date(_find_field(row, "DT_COMPTC"), year, month)
                return (cnpj, period, _find_field(row, "TAB_X_CLASSE_SERIE") or "")

            x3 = {_key(r): r for r in rows_x3}
            x6 = {_key(r): r for r in rows_x6}

            records = []
            for row in rows_x2:
                base = _norm_fidc_tranche(row, year, month)
                if not base:
                    continue
                k = (base["cnpj"], base["period"], base["classe_serie"])
                r3 = x3.get(k, {})
                r6 = x6.get(k, {})
                base["vl_rentab_mes"]      = _find_field(r3, "TAB_X_VL_RENTAB_MES")
                base["pr_desemp_esperado"] = _find_field(r6, "TAB_X_PR_DESEMP_ESPERADO")
                base["pr_desemp_real"]     = _find_field(r6, "TAB_X_PR_DESEMP_REAL")
                records.append(base)

            cols = ["cnpj","period","classe_serie","qt_cota","vl_cota",
                    "vl_rentab_mes","pr_desemp_esperado","pr_desemp_real","raw"]
            n = _insert(conn, "cvm_fidc_tranche", cols, records)
            total += n
            print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  ERROR: {e}")

    rows_flows = await _seed_fidc_tranche_flows(conn, fetcher, months)
    rows_aging = await _seed_fidc_aging(conn, fetcher, months)
    return total + rows_flows + rows_aging


async def _seed_fidc_tranche_flows(conn, fetcher, months):
    cols = ["cnpj","period","classe_serie","tp_oper","vl_total","qt_cota"]
    total = 0
    for year, month in months:
        t0 = time.time()
        print(f"  FIDC tranche_flows {year}-{month:02d} … fetching", end="", flush=True)
        try:
            raw_rows = await fetcher.fetch("fidc", "mensal_tab_X4", year=year, month=month)
            records = [r for row in raw_rows if (r := _norm_fidc_tranche_flows(row, year, month))]
            n = _insert(conn, "cvm_fidc_tranche_flows", cols, records)
            total += n
            print(f"  → {n:,} rows  ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  ERROR: {e}")
    return total


async def _seed_fidc_aging(conn, fetcher, months):
    cols = [
        "cnpj","period",
        "vl_prazo_30","vl_prazo_60","vl_prazo_90","vl_prazo_120","vl_prazo_150",
        "vl_prazo_180","vl_prazo_360","vl_prazo_720","vl_prazo_1080","vl_prazo_maior_1080",
        "vl_inad_30","vl_inad_60","vl_inad_90","vl_inad_120","vl_inad_150",
        "vl_inad_180","vl_inad_360","vl_inad_720","vl_inad_1080","vl_inad_maior_1080",
        "vl_total_inad","raw",
    ]
    total = 0
    for year, month in months:
        t0 = time.time()
        print(f"  FIDC aging {year}-{month:02d} … fetching", end="", flush=True)
        try:
            raw_rows = await fetcher.fetch("fidc", "mensal_tab_VI", year=year, month=month)
            records = [r for row in raw_rows if (r := _norm_fidc_aging(row, year, month))]
            n = _insert(conn, "cvm_fidc_aging", cols, records)
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

    # serie and fluxo tables
    serie_cols = [
        "instrument_type","cnpj_securit","codigo_identificacao","data_referencia",
        "classe","numero_serie","tipo_oferta","codigo_cetip","codigo_isin","data_vencimento",
        "situacao","valor_total_integralizado","taxa_juros","pagamento_periodicidade",
        "quantidade_certificados","valor_certificados","rendimentos","amortizacoes",
        "rentabilidade","classificacao_risco_atual","indice_subordinacao_minimo","raw",
    ]
    fluxo_cols = [
        "instrument_type","cnpj_securit","codigo_identificacao","data_referencia",
        "recebimentos_direitos_creditorios","pagamentos_despesas","pagamentos_classe_senior",
        "pagamentos_senior_principal","pagamentos_senior_juros","pagamentos_mezanino",
        "pagamentos_mezanino_principal","pagamentos_mezanino_juros","pagamentos_junior",
        "pagamentos_junior_principal","pagamentos_junior_juros","variacao_liquida_caixa","raw",
    ]
    _NO_CONFLICT_TABLES.add("cvm_securit_serie")
    _NO_CONFLICT_TABLES.add("cvm_securit_fluxo")
    for base in ["cra", "cri"]:
        for year in years:
            for doc_type, cols_list, table in [
                (f"{base}_classe", serie_cols, "cvm_securit_serie"),
                (f"{base}_fluxo",  fluxo_cols, "cvm_securit_fluxo"),
            ]:
                t0 = time.time()
                print(f"  SECURIT {doc_type} {year} … fetching", end="", flush=True)
                try:
                    raw_rows = await fetcher.fetch("securit", doc_type, year=year)
                    norm_fn = _norm_securit_serie if "classe" in doc_type else _norm_securit_fluxo
                    records = [norm_fn(row, doc_type) for row in raw_rows]
                    n = _insert(conn, table, cols_list, records)
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
    await seed_fidc_tranche(conn, fetcher, fidc_months)

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
