"""Statement template reader and masking (offline, synthetic data only)."""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from src.portfolio.mask import Masker
from src.portfolio.statement import (
    StatementFormatError,
    StatementTotalMismatch,
    parse_rows,
    read_statement,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"

NAME = "JOAQUIM SINTETICO DE OLIVEIRA"
CPF = "987.654.321-00"
CONTA = "55501-7"
ORIGINALS = (NAME, "JOAQUIM", "OLIVEIRA", CPF, "98765432100", CONTA, "555017")

HEADER = ["linha_extrato", "tipo", "codigo", "quantidade", "preco_unitario", "valor", "data_posicao"]


def rows(total, positions, holder=True):
    head = []
    if holder:
        head += [["titular", NAME], ["cpf", CPF], ["conta", CONTA]]
    head += [["corretora", "Corretora Teste"], ["total_extrato", total], [], HEADER]
    return head + positions


def pos(name, tipo, valor, codigo=None, qtd=1, preco=None, data=dt.date(2026, 9, 30)):
    return [name, tipo, codigo, qtd, preco if preco is not None else valor, valor, data]


def test_template_file_reads_and_reconciles():
    s = read_statement(TEMPLATE)
    assert len(s.positions) == 13  # the reader keeps every row; the engine merges the repeated CDB (engine 1.7)
    cdb = s.positions[8]
    assert cdb.tipo == "CDB" and cdb.vencimento == dt.date(2028, 3, 15) and cdb.taxa_texto == "105,00% do CDI"
    assert s.positions[0].vencimento is None and s.positions[0].taxa_texto is None
    assert abs(s.sum_of_lines - s.stated_total) <= s.tolerance
    assert s.holder.titular == "[TITULAR]" and s.holder.cpf == "[CPF]" and s.holder.conta == "[CONTA]"
    assert s.position_date == dt.date(2026, 9, 30)
    assert s.source_format == "xlsx"


def test_csv_semicolon_pt_br_numbers(tmp_path):
    f = tmp_path / "extrato.csv"
    f.write_text(
        "titular;Fulano\ntotal_extrato;1.500,50\n\n" + ";".join(HEADER) + "\n"
        "ACAO X;ação;PETR4;100;10,00;1.000,00;30/09/2026\n"
        "FUNDO Y;fundo;;500;1,001;500,50;2026-09-30\n",
        encoding="utf-8",
    )
    s = read_statement(f)
    assert s.stated_total == Decimal("1500.50")
    assert [p.valor for p in s.positions] == [Decimal("1000.00"), Decimal("500.50")]
    assert s.source_format == "csv"


def test_total_within_tolerance_passes_and_beyond_raises():
    p = [pos("A", "ação", 100.0, "PETR4"), pos("B", "fundo", 50.0)]
    parse_rows(rows(150.02, p))  # 0.02 = 0.01 x 2 rows
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_rows(rows(150.03, p))
    e = ei.value
    assert e.difference == Decimal("-0.03")
    assert e.n_rows == 2 and e.unreadable_rows == []
    assert "R$ -0.03" in str(e)


def test_unreadable_row_is_named_never_dropped():
    p = [pos("A", "ação", 100.0, "PETR4"), ["B", "fundo", None, 1, 1, "abc", dt.date(2026, 9, 30)], pos("C", "tipo-invalido", 5.0)]
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_rows(rows(105.0, p))
    rows_not_read = {u.source_row: u.reason for u in ei.value.unreadable_rows}
    assert set(rows_not_read) == {9, 10}  # sheet rows: 7 header rows, positions start at row 8
    assert "valor is not a number" in rows_not_read[9]
    assert "tipo" in rows_not_read[10]
    assert "row 9" in str(ei.value) and "row 10" in str(ei.value)


def test_unreadable_row_raises_even_when_sum_ties():
    # the unreadable row's value is unknown, so a tie of the readable ones must not hide it
    p = [pos("A", "ação", 100.0, "PETR4"), ["B", "fundo", None, 1, 1, 0, "31-12-2026"]]
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_rows(rows(100.0, p))
    assert len(ei.value.unreadable_rows) == 1


@pytest.mark.parametrize(
    "bad",
    [
        [["titular", "X"], HEADER, pos("A", "ação", 1.0)],  # no total
        [["total_extrato", 1.0], ["linha_extrato", "tipo", "valor"], ["A", "ação", 1.0]],  # missing data_posicao
        [["total_extrato", 1.0], HEADER],  # no rows
        [["total_extrato", "xx"], HEADER, pos("A", "ação", 1.0)],  # total not a number
        [["total_extrato", 1.0], ["A", "ação", 1.0]],  # no header row
    ],
)
def test_format_errors(bad):
    with pytest.raises(StatementFormatError):
        parse_rows(bad)


def test_mixed_position_dates_use_latest_and_say_so():
    p = [pos("A", "ação", 10.0, data=dt.date(2026, 9, 29)), pos("B", "ação", 10.0, data=dt.date(2026, 9, 30))]
    s = parse_rows(rows(20.0, p))
    assert s.position_date == dt.date(2026, 9, 30)
    assert s.position_dates == (dt.date(2026, 9, 29), dt.date(2026, 9, 30))
    assert s.notes and "2026-09-30" in s.notes[0]


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def _no_originals(text: str) -> None:
    for o in ORIGINALS:
        assert o not in text, o


def test_masker_replaces_name_cpf_account_in_any_cell():
    m = Masker(NAME, CPF, CONTA)
    assert m.scrub(f"FUNDO DE {NAME} LTDA") == "FUNDO DE [TITULAR] LTDA"
    assert m.scrub("cpf 98765432100") == "cpf [CPF]"
    assert m.scrub("conta 555017") == "conta [CONTA]"
    assert m.scrub("outro 111.222.333-44") == "outro [CPF]"  # any formatted CPF
    assert m.scrub(12.5) == 12.5
    _no_originals(repr(m) + str(m))


def test_masker_person_like_cnpj_in_cpf_field():
    m = Masker("EMPRESA INDIVIDUAL", "12.345.678/0001-95", None)
    assert m.holder.cpf == "[CNPJ_TITULAR]"
    assert m.scrub("12345678000195") == "[CNPJ_TITULAR]"


def test_statement_never_holds_originals_even_in_line_names():
    p = [pos(f"CARTEIRA DE {NAME}", "outro", 10.0, codigo="555017")]
    s = parse_rows(rows(10.0, p))
    _no_originals(repr(s))
    assert s.positions[0].linha_extrato == "CARTEIRA DE [TITULAR]"
    assert s.positions[0].codigo == "[CONTA]"


def test_exceptions_and_logs_carry_no_originals(caplog):
    caplog.set_level(logging.DEBUG)
    p = [pos(f"X {NAME}", "ação", 100.0, "PETR4"), [f"Y {CPF}", "fundo", None, 1, 1, "abc", dt.date(2026, 9, 30)]]
    with pytest.raises(StatementTotalMismatch) as ei:
        parse_rows(rows(100.0, p))
    _no_originals(str(ei.value) + repr(ei.value.unreadable_rows))
    with pytest.raises(StatementFormatError) as ei2:
        parse_rows([["titular", NAME], ["cpf", CPF], HEADER, pos("A", "ação", 1.0)])
    _no_originals(str(ei2.value))
    _no_originals(caplog.text)
