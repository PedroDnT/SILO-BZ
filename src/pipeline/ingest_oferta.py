"""CVM public offerings (OFERTA/DISTRIB): parse and upsert (#1005).

Two members of one zip, two tables. Both are snapshots: CVM rewrites the whole
file, so a load reads it whole and upserts on the source's own key.

* ``ingest_oferta_160``: every Resolução CVM 160 offering (2023 on), keyed on
  Numero_Requerimento.
* ``ingest_oferta_400``: only the registered ICVM 400 debenture offerings of
  the legacy file (owner decision, 2026-10-21), keyed on
  (Numero_Registro_Oferta, Serie). The ICVM 476 offerings have no natural key
  and are not loaded.

A row with no key, an invalid issuer CNPJ or a key the file repeats is dropped
and counted, never guessed. Unmapped columns go to ``raw``; a numeric or date
cell that did not parse is kept there under ``_unparsed``.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List

from src.parsers.field_maps import oferta_distrib_160 as _f160
from src.parsers.field_maps import oferta_distrib_400 as _f400
from src.parsers.mapping import apply_map, assert_map_matches
from src.parsers.validation import DataValidator
from src.pipeline.ingest_fi import _unparsed_cells
from src.store.pg_client import upsert_rows

logger = logging.getLogger(__name__)
_validator = DataValidator()


def _typed_rows(raw_rows, fmap, source_file: str, keep=lambda row: True):
    records: List[Dict[str, Any]] = []
    dropped: Counter = Counter()
    for row in raw_rows:
        if not keep(row):
            continue
        typed, residual = apply_map(row, fmap.FIELD_MAP)
        if any(not typed.get(k) for k in fmap.CONFLICT):
            dropped["no_key"] += 1
            continue
        cnpj = typed.get("cnpj_emissor")
        if cnpj is not None and not _validator._validate_cnpj(cnpj)[0]:
            dropped["bad_cnpj"] += 1
            continue
        unparsed = _unparsed_cells(row, fmap.FIELD_MAP, typed)
        if unparsed:
            residual = {**residual, "_unparsed": unparsed}
        typed["source_file"] = source_file
        typed["raw"] = residual
        records.append(typed)

    # A key the file repeats: the file does not say which row is right, so
    # every row of that key is dropped (and counted), never "last one wins".
    keys = Counter(tuple(r[k] for k in fmap.CONFLICT) for r in records)
    repeated = {k for k, n in keys.items() if n > 1}
    if repeated:
        before = len(records)
        records = [r for r in records if tuple(r[k] for k in fmap.CONFLICT) not in repeated]
        dropped["repeated_key"] += before - len(records)
    if dropped:
        logger.warning("%s %s: dropped %s of %d source row(s)", fmap.TABLE, source_file,
                       dict(dropped), len(raw_rows))
    return records


def ingest_oferta_160(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    assert_map_matches(raw_rows, _f160.FIELD_MAP, dataset="oferta/distrib_160",
                       required=_f160.REQUIRED)
    records = _typed_rows(raw_rows, _f160, "oferta_resolucao_160.csv")
    if not records:
        return 0
    return upsert_rows(conn, _f160.TABLE, records, conflict_columns=",".join(_f160.CONFLICT))


def _registered_debenture(row: Dict[str, Any]) -> bool:
    rito = (row.get("Rito_Oferta") or "").strip()
    ativo = (row.get("Tipo_Ativo") or "").strip().upper()
    return rito.startswith("ICVM 400") and "DEBÊNTURES" in ativo


def ingest_oferta_400(conn: Any, raw_rows: List[Dict[str, Any]]) -> int:
    assert_map_matches(raw_rows, _f400.FIELD_MAP, dataset="oferta/distrib",
                       required=_f400.REQUIRED)
    records = _typed_rows(raw_rows, _f400, "oferta_distribuicao.csv", keep=_registered_debenture)
    if not records:
        return 0
    return upsert_rows(conn, _f400.TABLE, records, conflict_columns=",".join(_f400.CONFLICT))
