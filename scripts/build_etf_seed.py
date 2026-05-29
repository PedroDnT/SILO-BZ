"""Generate / refresh the curated B3 ETF seed (src/store/seeds/etf_registry_seed.csv).

Why a curated seed?  CVM open data has no ETF flag — neither TP_FUNDO
(FI/FACFIF/FAPI/FCCE) nor the CVM-175 `Classificacao` distinguishes ETFs.
B3 (which assigns the ticker) is the only authoritative ETF enumerator, and its
public funds API returns no ETF rows from CI IPs.  So we maintain a small,
verified ticker->CNPJ map here and join it to CVM's existing data.

Each curated CNPJ below was resolved against CVM's own registries (cad_fi.csv +
registro_fundo_classe.zip) — live ETFs are named "... CLASSE DE ÍNDICE" /
"FUNDO DE ÍNDICE" and resolve to an active class CNPJ that appears in
cvm_fi_diario (CNPJ_FUNDO_CLASSE).  This script re-fetches those registries to
fill the legal name + situacao and to verify each CNPJ still resolves, then
writes the CSV the ingest path loads.

To add an ETF: append a row to CURATED with its ticker, the class CNPJ, the
provider, the underlying index, and a segment, then re-run this script.

Usage:
    python scripts/build_etf_seed.py            # fetch CVM, verify, write CSV
    python scripts/build_etf_seed.py --offline  # write CSV from CURATED only
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import urllib.request
import zipfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_PATH = os.path.join(_REPO_ROOT, "src", "store", "seeds", "etf_registry_seed.csv")

FIELDS = ["ticker", "cnpj", "fund_name", "provider", "underlying_index", "segment"]

# ticker, class CNPJ (14 digits), provider, underlying index, segment
# segment: equities_br | equities_intl | fixed_income | crypto | commodities
CURATED = [
    ("BOVA11", "10406511000161", "BlackRock (iShares)", "Ibovespa",                 "equities_br"),
    ("SMAL11", "10406600000108", "BlackRock (iShares)", "Índice Small Cap (SMLL)",  "equities_br"),
    ("BRAX11", "11455378000104", "BlackRock (iShares)", "IBrX-100",                 "equities_br"),
    ("IVVB11", "19909560000191", "BlackRock (iShares)", "S&P 500",                  "equities_intl"),
    ("BOVV11", "21407758000119", "Itaú (It Now)",       "Ibovespa",                 "equities_br"),
    ("DIVO11", "13416245000146", "Itaú (It Now)",       "IDIV (Dividendos)",        "equities_br"),
    ("FIND11", "11961094000181", "Itaú (It Now)",       "IFNC (Financeiro)",        "equities_br"),
    ("MATB11", "13416228000109", "Itaú (It Now)",       "IMAT (Materiais Básicos)", "equities_br"),
    ("ISUS11", "12984444000198", "Itaú (It Now)",       "ISE (Sustentabilidade)",   "equities_br"),
    ("HASH11", "38314708000190", "Hashdex",             "Nasdaq Crypto Index",      "crypto"),
    ("USTK11", "40751130000180", "Investo",             "MSCI US Technology",       "equities_intl"),
    ("WRLD11", "61689798000115", "Investo",             "FTSE All-World",           "equities_intl"),
    ("XINA11", "65836654000103", "Investo",             "FTSE China A Inclusion",   "equities_intl"),
]

_BASE = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=90).read()


def _norm(cnpj: str) -> str:
    digits = re.sub(r"\D", "", cnpj or "")
    return digits.zfill(14) if digits else ""


def _build_cvm_index() -> dict:
    """Map normalised CNPJ -> (legal_name, situacao) from CVM registries."""
    index: dict = {}
    cad = _fetch(f"{_BASE}/cad_fi.csv").decode("latin-1", "replace")
    for r in csv.DictReader(io.StringIO(cad), delimiter=";"):
        index[_norm(r.get("CNPJ_FUNDO"))] = (r.get("DENOM_SOCIAL", ""), r.get("SIT", ""))
    zf = zipfile.ZipFile(io.BytesIO(_fetch(f"{_BASE}/registro_fundo_classe.zip")))
    for member, cnpj_col in (("registro_classe.csv", "CNPJ_Classe"),
                             ("registro_fundo.csv", "CNPJ_Fundo")):
        text = zf.read(member).decode("latin-1", "replace")
        for r in csv.DictReader(io.StringIO(text), delimiter=";"):
            cnpj = _norm(r.get(cnpj_col))
            if cnpj and cnpj not in index:
                index[cnpj] = (r.get("Denominacao_Social", ""), r.get("Situacao", ""))
    return index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip CVM fetch/verify")
    args = ap.parse_args()

    index = {} if args.offline else _build_cvm_index()
    if index:
        print(f"CVM registry index: {len(index)} CNPJs")

    rows = []
    for ticker, cnpj, provider, idx, segment in CURATED:
        cnpj = _norm(cnpj)
        name, sit = index.get(cnpj, ("", ""))
        if index and not name:
            print(f"  WARNING: {ticker} {cnpj} not found in CVM registry")
        elif index:
            print(f"  ok {ticker} {cnpj} [{sit}] {name[:50]}")
        rows.append({
            "ticker": ticker,
            "cnpj": cnpj,
            "fund_name": name,
            "provider": provider,
            "underlying_index": idx,
            "segment": segment,
        })

    rows.sort(key=lambda r: r["ticker"])
    os.makedirs(os.path.dirname(SEED_PATH), exist_ok=True)
    with open(SEED_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {len(rows)} ETFs -> {os.path.relpath(SEED_PATH, _REPO_ROOT)}")


if __name__ == "__main__":
    main()
