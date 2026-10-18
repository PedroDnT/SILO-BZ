"""src/cnpj.py is the one CNPJ text helper (#876); each caller keeps the behaviour it had."""

from __future__ import annotations

import re

import pytest

from src import cnpj
from src.parsers.mapping import coerce

SAMPLES = [
    "12.345.678/0001-90", "12345678000190", "0012345678000190", "191", "00000000000191",
    "", None, "  ", "abc", "123.456.789-09", "12345678901", "123456789012345", " 33 000 167/0001-01 ",
]


def test_digits_strips_everything_but_ascii_digits():
    assert cnpj.digits("12.345.678/0001-90") == "12345678000190"
    assert cnpj.digits(None) == "" and cnpj.digits("") == "" and cnpj.digits("abc") == ""
    assert cnpj.digits(191) == "191"
    assert cnpj.digits("²١") == ""  # superscript and Arabic-Indic digits are not CNPJ digits


def test_exact_is_fourteen_digits_or_none_never_padded():
    assert cnpj.exact("12.345.678/0001-90") == "12345678000190"
    assert cnpj.exact("191") is None  # a dropped leading zero is not restored here
    assert cnpj.exact("123456789012345") is None
    assert cnpj.exact(None) is None


def test_pad_restores_a_dropped_leading_zero():
    assert cnpj.pad("191") == "00000000000191"
    assert cnpj.pad("12.345.678/0001-90") == "12345678000190"
    assert cnpj.pad("") is None and cnpj.pad(None) is None and cnpj.pad("abc") is None


def test_pad_never_truncates_a_longer_number():
    assert cnpj.pad("123456789012345") == "123456789012345"


def test_coerce_cnpj_goes_through_pad():
    for raw in SAMPLES:
        assert coerce(raw, "cnpj") == (cnpj.pad(str(raw).strip()) if raw is not None and str(raw).strip() else None)


def test_text_columns_are_not_padded():
    # AGENTS.md rule 4: a CPF-capable column is typed text, so an 11-digit CPF stays as filed.
    assert coerce("123.456.789-09", "text") == "123.456.789-09"
    assert coerce("12345678909", "text") == "12345678909"


def test_root_and_forms_need_a_full_cnpj():
    assert cnpj.root("33.000.167/0001-01") == "33000167"
    assert cnpj.root("33000167") is None and cnpj.root(None) is None
    assert cnpj.forms("33000167000101") == ("33000167000101", "33.000.167/0001-01")
    assert cnpj.forms("33000167") == ()


# --- parity with the implementations this module replaced ------------------------------------------

def _old_cvm_pipeline(raw):
    return re.sub(r"\D", "", str(raw)) if raw else ""


def _old_serve(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits if len(digits) == 14 else None


def _old_fnet(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits if re.fullmatch(r"\d{14}", digits) else None


def _old_b3_events(raw):
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits.zfill(14) if 0 < len(digits) <= 14 else ""


def _old_root(raw):
    if not raw:
        return None
    d = re.sub(r"\D", "", str(raw))
    return d[:8] if len(d) == 14 else None


@pytest.mark.parametrize("raw", SAMPLES)
def test_same_answers_as_the_copies_it_replaced(raw):
    from src.pipeline.cvm_pipeline import _normalize_cnpj
    from src.portfolio.common import cnpj_root

    assert _normalize_cnpj(raw) == _old_cvm_pipeline(raw)
    assert cnpj.exact(raw) == _old_serve(raw if isinstance(raw, str) or raw is None else str(raw))
    assert cnpj.exact(raw) == _old_fnet(raw if isinstance(raw, str) or raw is None else str(raw))
    padded = cnpj.pad(raw)
    assert (padded if padded and len(padded) == 14 else "") == _old_b3_events(raw)
    assert cnpj_root(raw) == _old_root(raw)


def test_serve_normalize_cnpj_still_refuses_a_short_number():
    from serve.app import normalize_cnpj, parse_ids

    assert normalize_cnpj("33.000.167/0001-01") == "33000167000101"
    with pytest.raises(ValueError, match="14 digits"):
        normalize_cnpj("191")
    assert parse_ids("PETR4,33.000.167/0001-01") == ["PETR4", "33000167000101"]
