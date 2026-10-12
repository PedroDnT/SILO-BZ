"""The RJ seed files (#844): src/fetchers/rj/aj_sites.csv and tj_registries.csv.

Offline. The collector in #845 trusts these columns and values, and the files
must never carry personal data (LGPD): no e-mail, phone or CPF.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RJ = ROOT / "src" / "fetchers" / "rj"

ALL_TJS = {
    "TJAC", "TJAL", "TJAM", "TJAP", "TJBA", "TJCE", "TJDFT", "TJES", "TJGO",
    "TJMA", "TJMG", "TJMS", "TJMT", "TJPA", "TJPB", "TJPE", "TJPI", "TJPR",
    "TJRJ", "TJRN", "TJRO", "TJRR", "TJRS", "TJSC", "TJSE", "TJSP", "TJTO",
}
SITE_COLUMNS = [
    "domain", "aj_names", "cnpj", "tjs", "case_list_url", "structure", "robots_ok",
    "platform", "n_cases", "paginated", "has_process_number", "has_doc_links",
    "case_page_example", "fetch_error", "notes", "checked_at",
]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"\(\d{2}\)\s?\d{4,5}-?\d{4}")
CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")


def _rows(name: str) -> list[dict[str, str]]:
    with open(RJ / name, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_every_tj_has_a_registry_status():
    rows = _rows("tj_registries.csv")
    tjs = [r["tj"] for r in rows]
    assert len(tjs) == len(set(tjs))
    assert ALL_TJS <= set(tjs)
    for r in rows:
        assert r["status"] in {"used", "unusable", "blocked", "not_found"}, r["tj"]
        assert r["n_entries"].isdigit(), r["tj"]
        assert (int(r["n_entries"]) > 0) == (r["status"] == "used"), r["tj"]


def test_sites_have_the_collector_columns_and_known_values():
    with open(RJ / "aj_sites.csv", encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == SITE_COLUMNS
    rows = _rows("aj_sites.csv")
    domains = [r["domain"] for r in rows]
    assert len(domains) == len(set(domains))
    for r in rows:
        assert r["structure"] in {"html", "js", "login", "none", "fetch_error"}, r["domain"]
        assert r["robots_ok"] in {"yes", "no", "unknown"}, r["domain"]
        assert not r["domain"].startswith("www."), r["domain"]
        for c in r["cnpj"].split():
            assert re.fullmatch(r"\d{14}", c), r["domain"]
        if r["structure"] in {"html", "js"}:
            assert r["case_list_url"].startswith("http"), r["domain"]


def test_no_personal_data():
    for name in ("aj_sites.csv", "tj_registries.csv"):
        text = (RJ / name).read_text(encoding="utf-8")
        # A URL can hold "@" (eproc's acao=tjto@...); an address cannot have a slash before it.
        emails = [m for m in EMAIL.findall(text) if "/" not in m]
        assert not emails, (name, emails[:3])
        assert not PHONE.search(text), name
        assert not CPF.search(text), name
