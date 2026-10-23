"""Offline ANBIMA search-list contracts (#1006, #1014).

Card labels are the ones data.anbima.com.br rendered on 2026-10-23; every
value is synthetic. No browser and no database are used.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.parsers import anbima_listing as L
from src.parsers.anbima_debenture import AnbimaParseError
from src.pipeline import anbima_debenture_pipeline as A


def deb_card(code, pu, lei=False):
    tag = "LEI 12.431\n" if lei else ""
    return (f"{code}\n{tag}Calcular ativo\nVer detalhes\nEmissor\nEMISSORA TESTE S.A.\n"
            f"Remuneração\nDI + 0,9200%\nData de vencimento\n14/11/2031\nDuration\n-\n"
            f"Setor\nFinanceiro\nData da emissão\n15/12/2025\nPU PAR\nR$ 1.126,34\nPU Indicativo\n{pu}\n")


def cri_card(code, pu, name=None, tipo="CRI"):
    head = f"{code}\n•\n{name}\n{tipo}\n" if name else f"{code}\n{tipo}\n"
    return (head + "Calcular ativo\nVer detalhes\nDevedor\nDEVEDORA TESTE S.A.\nSérie e Emissão\n"
            "2ª Série e 26ª Emissão\nRemuneração\nIPCA + 4,5081%\nDuration\n329,77\n"
            "Securitizadora\nSECURITIZADORA TESTE S.A.\nData da emissão\n15/03/2019\n"
            f"Data de vencimento\n15/03/2029\nPU Indicativo\n{pu}\n")


def page(cards, first, last, total):
    return ("HOME\nBUSCA\nDEBÊNTURES\nOrdenar por:\nAtivo (A-Z)\n" + "".join(cards)
            + f"Itens por página:\n100\nExibindo {first} - {last} de {total} resultados\n")


def test_debenture_cards_read_code_and_priced():
    got = L.parse_listing(page([deb_card("TSTA11", "R$ 1.020,12"), deb_card("TSTB12", "-", lei=True),
                                deb_card("SNB 11", "-")], "4.101", "4.103", "4.167"))
    assert got.items == [L.Listed("TSTA11", True), L.Listed("TSTB12", False), L.Listed("SNB 11", False)]
    assert (got.first, got.last, got.total) == (4101, 4103, 4167)


def test_cri_cra_cards_skip_the_name_tag():
    got = L.parse_listing(page([cri_card("CRA019001E7", "R$ 1.470,22", name="Klabin", tipo="CRA"),
                                cri_card("13F0056986", "-")], 1, 2, 503))
    assert got.items == [L.Listed("CRA019001E7", True), L.Listed("13F0056986", False)]


def test_card_count_must_match_the_counter():
    with pytest.raises(AnbimaParseError, match="1-3 but 2 cards"):
        L.parse_listing(page([deb_card("TSTA11", "-"), deb_card("TSTB12", "-")], 1, 3, 3))


def test_page_without_counter_raises():
    with pytest.raises(AnbimaParseError, match="counter"):
        L.parse_listing("".join([deb_card("TSTA11", "-")]))


def test_card_without_code_raises():
    with pytest.raises(AnbimaParseError, match="without a code"):
        L.parse_listing(page([deb_card("Klabin S.A.", "-")], 1, 1, 1))


class ListFetcher:
    def __init__(self, listed):
        self.listed, self.fetched = listed, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_codes(self):
        return self.listed

    async def fetch(self, code, page):
        self.fetched.append((code, page))
        raise RuntimeError("not needed")


def _run(listed, pages=("precos",)):
    fake = ListFetcher(listed)
    with patch.object(A, "upsert_rows", return_value=1), \
         patch.object(A.ingest_log, "start"), patch.object(A.ingest_log, "finish") as finish:
        ing = A.AnbimaDebentureIngestor(conn=MagicMock(), fetcher_factory=lambda: fake)
        try:
            asyncio.run(ing.ingest(None, pages))
        except Exception:  # noqa: BLE001 — the fake fetch fails; the codes are what is checked
            pass
    return fake, finish


def test_all_priced_captures_only_priced_codes():
    fake, _ = _run([L.Listed("TSTA11", True), L.Listed("TSTB12", False), L.Listed("TSTC13", True)])
    assert sorted(fake.fetched) == [("TSTA11", "precos"), ("TSTC13", "precos")]


def test_all_priced_with_nothing_priced_fails_the_run():
    fake, finish = _run([L.Listed("TSTB12", False)])
    assert fake.fetched == []
    assert finish.call_args.kwargs["status"] == "error"


def test_cli_needs_codes_or_all_priced():
    with pytest.raises(SystemExit):
        A.main([])
    with pytest.raises(SystemExit):
        A.main(["--codes", "TSTA11", "--all-priced"])
    with pytest.raises(SystemExit, match="needs --codes"):
        A.main(["--all-priced", "--dry-run"])
