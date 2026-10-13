"""aj_index (#846): an act names an inventoried AJ by domain or name, or none; never guessed."""

from __future__ import annotations

from datetime import datetime, timezone

from src.fetchers.rj import aj_index
from src.fetchers.rj.aj_index import aj_named_in
from src.fetchers.rj.djen import parse_item
from src.pipeline.ingest_rj_djen import rows_for

SEEN = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def test_a_cited_domain_names_its_aj():
    aj = aj_named_in("Documentos disponíveis em www.vonsaltiel.com.br/recuperacao-judicial.")
    assert aj is not None and aj.domain == "vonsaltiel.com.br"


def test_an_inventoried_name_names_its_aj():
    aj = aj_named_in("Nomeio como administradora judicial ADJUD Administradores Judiciais Ltda, que deverá...")
    assert aj is not None and aj.domain == "adjud.com.br" and aj.name == "ADJUD Administradores Judiciais Ltda"


def test_generic_words_and_unknown_names_name_nobody():
    assert aj_named_in("Intime-se a Administração Judicial Ltda para manifestação.") is None
    assert aj_named_in("Nomeio administrador judicial FULANO DE TAL CONSULTORIA ÚNICA.") is None
    assert aj_named_in("") is None


def test_two_different_ajs_name_none():
    assert aj_named_in("vonsaltiel.com.br e adjud.com.br") is None


def test_generic_only_names_are_not_indexed():
    assert not aj_index._specific("administracao judicial ltda")
    assert not aj_index._specific("administracao de empresas")
    assert "fegos consultores ltda" in aj_index._index()[1]  # trailing "." dropped
    assert aj_index._specific("adjud administradores judiciais ltda")


def _raw(texto, numero="5024740-14.2026.8.24.0023"):
    return {"numero_processo": numero.replace("-", "").replace(".", ""), "codigoClasse": "129",
            "siglaTribunal": "TJSC", "texto": texto, "data_disponibilizacao": "2026-09-15",
            "hash": "h", "link": "https://eproc.example.jus.br/doc?id=1"}


def test_rows_set_the_case_aj_only_when_its_acts_agree():
    one = rows_for([parse_item(_raw("Ver www.vonsaltiel.com.br"))], SEEN)[0][0]
    assert one["aj_name"] == aj_index._index()[0]["vonsaltiel.com.br"].name
    split = rows_for([parse_item(_raw("Ver www.vonsaltiel.com.br")), parse_item(_raw("Ver adjud.com.br"))], SEEN)[0][0]
    assert split["aj_name"] is None
    none = rows_for([parse_item(_raw("Intimação sem administrador citado."))], SEEN)[0][0]
    assert none["aj_name"] is None
