"""
Exploration script: hits real CVM URLs, prints raw field names, sample rows,
pipeline-normalized records, and DataValidator quality report for each entity.

Usage:
    python scripts/explore_cvm_output.py

Requires internet access. Supabase is stubbed — no writes happen.
"""

import asyncio
import io
import json
import sys
import os
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fetchers.cvm_fetcher import CVMFetcher
from src.fetchers.cvm_config import DatasetConfig, FetcherConfig
from src.parsers.validation import DataValidator

# Representative (entity, doc_type, year, month) — small recent files
PROBES = [
    ("fi",      "inf_diario",        2025, 3),
    ("fi",      "cda",               2025, 3),
    ("fidc",    "mensal",            2025, 3),
    ("fip",     "inf_quadrimestral", 2024, None),
    ("fii",     "mensal_geral",      2024, None),
    ("fii",     "mensal_ativo_passivo", 2024, None),
    ("securit", "cra_mensal",        2024, None),
]

# ZIP-based datasets where we want to inspect all internal files
ZIP_INSPECT = {("fidc", "mensal"), ("fii", "mensal_geral"), ("fii", "mensal_ativo_passivo")}

SEP = "=" * 70


def _safe_truncate(val, max_len=60):
    s = str(val)
    return s[:max_len] + "…" if len(s) > max_len else s


def _print_rows(rows, n=2):
    if not rows:
        print("  (no rows returned)")
        return
    cols = list(rows[0].keys())
    print(f"  Columns ({len(cols)}): {cols}")
    for i, row in enumerate(rows[:n]):
        print(f"\n  Row {i+1}:")
        for k, v in row.items():
            print(f"    {k}: {_safe_truncate(v)}")


def _print_quality(rows):
    validator = DataValidator()
    report = validator.validate_dataset(rows)
    print(f"\n  DataValidator report:")
    print(f"    total_records      : {report['total_records']}")
    print(f"    quality_score      : {report['quality_score']:.1f}")
    print(f"    parsing_success_rate: {report['parsing_success_rate']:.1f}%")
    print(f"    records_with_errors: {report['records_with_errors']}")
    if report["validation_errors"]:
        print(f"    validation_errors  : {report['validation_errors'][:3]}")
    if report["warnings"]:
        print(f"    warnings (first 3) : {report['warnings'][:3]}")
    print(f"    field_stats keys   : {list(report['field_stats'].keys())}")


async def _inspect_zip(fetcher, entity, doc_type, year, month):
    """Download the raw ZIP and list all internal files + their column headers."""
    try:
        ds = DatasetConfig.get_dataset_config(entity, doc_type)
        cfg = FetcherConfig()
        kwargs = {"base_url": cfg.CVM_BASE_URL, "year": year}
        if month is not None:
            kwargs["month"] = month
        url = ds["url_pattern"].format(**kwargs)
        raw = await fetcher._download(url)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            print(f"\n  ZIP internal files ({len(names)}): {names}")
            for name in names:
                content = zf.read(name).decode("latin-1")
                first_line = content.split("\n")[0]
                cols = first_line.split(";")
                print(f"\n  [{name}] — {len(cols)} columns")
                print(f"    {cols}")
    except Exception as e:
        print(f"  ZIP inspect error: {e}")


async def probe(entity, doc_type, year, month):
    label = f"{entity.upper()} / {doc_type}"
    print(f"\n{SEP}")
    print(f"  {label}  (year={year}, month={month})")
    print(SEP)

    fetcher = CVMFetcher()

    if (entity, doc_type) in ZIP_INSPECT:
        await _inspect_zip(fetcher, entity, doc_type, year, month)

    try:
        kwargs = {"entity": entity, "doc_type": doc_type, "year": year}
        if month is not None:
            kwargs["month"] = month
        rows = await fetcher.fetch(**kwargs)
    except Exception as e:
        print(f"  FETCH ERROR: {e}")
        return

    print(f"\n  Fetched {len(rows)} rows")
    _print_rows(rows, n=2)
    _print_quality(rows)


async def main():
    print("CVM Output Explorer")
    print("Fetching sample data from dados.cvm.gov.br …\n")
    for entity, doc_type, year, month in PROBES:
        await probe(entity, doc_type, year, month)
    print(f"\n{SEP}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
