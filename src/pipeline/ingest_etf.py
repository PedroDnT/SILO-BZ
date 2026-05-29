"""ETF (Fundo de Índice) ingest — curated seed enriched from CVM cad_fi.

CVM open data has no ETF flag, so the ETF universe comes from a curated
ticker->CNPJ seed (src/store/seeds/etf_registry_seed.csv). This module loads
that seed, enriches each row with fee/admin/status fields from cad_fi (matched
by CNPJ), and upserts into cvm_etf_registry. AUM, quotaholders, NAV and returns
are not stored here — they are exposed by the etf_daily / etf_latest views,
which join this registry to cvm_fi_diario on CNPJ.

Run standalone:  python -m src.pipeline.ingest_etf
"""
from __future__ import annotations

import csv
import logging
import os
from typing import Any, Dict, List, Optional

from src.parsers.mapping import apply_map, coerce
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)

TABLE = "cvm_etf_registry"
CONFLICT = ("ticker",)

SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src", "store", "seeds", "etf_registry_seed.csv",
)

# Enrichment fields lifted from cad_fi by CNPJ (declarative, same engine as the
# rest of the pipeline). cad_fi is the legacy registry; CVM-175-only classes may
# be absent here, in which case these stay NULL.
_CAD_ENRICH_MAP = {
    "situacao":      (["SIT"],            "text"),
    "classe_anbima": (["CLASSE_ANBIMA"],  "text"),
    "taxa_adm":      (["TAXA_ADM"],       "numeric"),
    "taxa_perfm":    (["TAXA_PERFM"],     "numeric"),
    "admin":         (["ADMIN"],          "text"),
    "gestor":        (["GESTOR"],         "text"),
    "dt_reg":        (["DT_REG"],         "date"),
    "vl_patrim_liq": (["VL_PATRIM_LIQ"],  "numeric"),
    "dt_patrim_liq": (["DT_PATRIM_LIQ"],  "date"),
}


def load_etf_seed(path: str = SEED_PATH) -> List[Dict[str, str]]:
    """Read the curated ETF seed CSV into a list of dict rows."""
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _build_cad_index(cad_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map normalised CNPJ -> typed enrichment fields from cad_fi rows."""
    index: Dict[str, Dict[str, Any]] = {}
    for row in cad_rows:
        cnpj = coerce(row.get("CNPJ_FUNDO") or row.get("CNPJ_FUNDO_CLASSE"), "cnpj")
        if not cnpj:
            continue
        typed, _ = apply_map(row, _CAD_ENRICH_MAP)
        index[cnpj] = typed
    return index


def ingest_etf_registry(
    conn: Any,
    seed_rows: List[Dict[str, str]],
    cad_rows: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Build enriched ETF registry records from the seed and upsert them.

    Args:
        seed_rows -- rows from load_etf_seed()
        cad_rows  -- raw cad_fi rows for enrichment (optional; fees/status NULL if omitted)
    Returns:
        number of rows upserted
    """
    cad_index = _build_cad_index(cad_rows or [])
    records: List[Dict[str, Any]] = []

    for s in seed_rows:
        ticker = (s.get("ticker") or "").strip().upper()
        cnpj = coerce(s.get("cnpj"), "cnpj")
        if not ticker or not cnpj:
            continue
        enrich = cad_index.get(cnpj, {})
        records.append({
            "ticker":           ticker,
            "cnpj":             cnpj,
            "fund_name":        (s.get("fund_name") or "").strip() or None,
            "provider":         (s.get("provider") or "").strip() or None,
            "underlying_index": (s.get("underlying_index") or "").strip() or None,
            "segment":          (s.get("segment") or "").strip() or None,
            "situacao":         enrich.get("situacao"),
            "classe_anbima":    enrich.get("classe_anbima"),
            "taxa_adm":         enrich.get("taxa_adm"),
            "taxa_perfm":       enrich.get("taxa_perfm"),
            "admin":            enrich.get("admin"),
            "gestor":           enrich.get("gestor"),
            "dt_reg":           enrich.get("dt_reg"),
            "vl_patrim_liq":    enrich.get("vl_patrim_liq"),
            "dt_patrim_liq":    enrich.get("dt_patrim_liq"),
            "raw":              dict(s),
        })

    if not records:
        return 0

    return upsert_rows(conn, TABLE, records, conflict_columns=",".join(CONFLICT))


async def _run() -> int:
    """Standalone runner: fetch cad_fi, load seed, upsert registry."""
    from src.fetchers.cvm_fetcher import CVMFetcher
    from src.store.pg_client import get_pg_client

    conn = get_pg_client()
    seed = load_etf_seed()
    try:
        cad_rows = await CVMFetcher().fetch(entity="fi", doc_type="cad", year=None, month=None)
    except Exception as exc:  # enrichment is best-effort
        logger.warning("cad_fi fetch failed, ingesting seed without enrichment: %s", exc)
        cad_rows = []
    rows = ingest_etf_registry(conn, seed, cad_rows)
    logger.info("etf/registry: %d rows", rows)
    return rows


if __name__ == "__main__":
    import asyncio

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print("ETF registry rows upserted:", asyncio.run(_run()))
