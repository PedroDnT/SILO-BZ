"""DJEN discovery (#846): parsing, the proxy rule, paging, the cap and the rows.

Offline: httpx.MockTransport and synthetic items. The names below are invented;
the shape (destinatarios with polo, codigoClasse as text, a 20-digit number,
link and hash) is DJEN's as measured on 2026-10-13.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.fetchers.rj import djen
from src.fetchers.rj.djen import DjenClient, DjenError, parse_item
from src.pipeline import ingest_rj_djen
from src.pipeline.ingest_rj_djen import DjenIngestor, rows_for

ROOT = Path(__file__).resolve().parents[1]
SEEN = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _item(numero="5024740-14.2026.8.24.0023", code="129", polos=(("A", "EMPRESA FICTICIA LTDA"), ("T", "Terceiro X")),
          tipo_doc="DESPACHO/DECISÃO", texto="Defiro o processamento da recuperação judicial.", link=True):
    return {
        "numero_processo": numero.replace("-", "").replace(".", ""), "codigoClasse": code,
        "nomeClasse": "RECUPERAÇÃO JUDICIAL", "siglaTribunal": "TJSC", "nomeOrgao": "Vara Regional de Falências",
        "tipoComunicacao": "Intimação", "tipoDocumento": tipo_doc, "texto": texto,
        "data_disponibilizacao": "2026-09-15", "hash": "abc123" if link else "",
        "link": "https://eproc.example.jus.br/doc?id=1" if link else "",
        "destinatarios": [{"comunicacao_id": 1, "nome": n, "polo": p} for p, n in polos],
    }


def test_only_rj_classes_with_a_cnj_number_are_kept():
    assert parse_item(_item()).numero_processo == "50247401420268240023"
    assert parse_item(_item(code="128")) is not None
    assert parse_item(_item(code="156")) is None  # cumprimento de sentença that only mentions RJ
    assert parse_item(_item(numero="123")) is None


def test_party_names_are_never_read_into_the_case():
    # Polo ativo mixes the debtor with partners, rural producers and lawyers (2026-10-13).
    items = [parse_item(_item(polos=(("A", "PESSOA FISICA"), ("A", "EMPRESA B LTDA"), ("P", "CREDOR"))))]
    assert not hasattr(items[0], "polo_ativo")
    cases, _ = rows_for(items, SEEN)
    assert cases[0]["devedor_nome"] is None


def test_client_refuses_without_a_brazilian_route(monkeypatch):
    for var in ("BR_PROXY_URL", "DJEN_RELAY_URL", "DJEN_RELAY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(DjenError, match="no Brazilian route"):
        DjenClient()
    monkeypatch.setenv("DJEN_RELAY_URL", "https://relay.example/djen-relay")
    with pytest.raises(DjenError, match="no Brazilian route"):  # a URL without its token is no route
        DjenClient()
    monkeypatch.setenv("BR_PROXY_URL", "http://proxy.example:3128")
    DjenClient().close()  # the proxy still works when the relay token is missing


def test_relay_mode_sends_the_token_to_the_relay_only():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "relay.example":
            return httpx.Response(200, json={"status": "success", "count": 1, "items": [_item()]})
        return httpx.Response(200)

    client = DjenClient(relay_url="https://relay.example/djen-relay", relay_token="s3cret",
                        transport=httpx.MockTransport(handler), sleep=lambda s: None)
    items = client.day("TJSC", date(2026, 9, 15))
    assert [i.numero_processo for i in items] == ["50247401420268240023"]
    relay = seen[0]
    assert relay.url.path == "/djen-relay" and relay.url.params["siglaTribunal"] == "TJSC"
    assert relay.headers["x-relay-token"] == "s3cret" and relay.headers["x-region"] == "sa-east-1"
    assert client.status("https://eproc.example.jus.br/doc?id=1") == 200
    act = seen[-1]
    assert act.url.host == "eproc.example.jus.br" and "x-relay-token" not in act.headers


def _client(pages, counts=None):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        n = int(request.url.params["pagina"])
        items = pages[n - 1] if n <= len(pages) else []
        return httpx.Response(200, json={"status": "success", "count": (counts or 0), "items": items})

    return DjenClient(proxy="", transport=httpx.MockTransport(handler), sleep=lambda s: None), calls


def test_day_pages_until_a_short_page_and_filters_classes():
    full = [_item(code="156")] * 99 + [_item()]
    client, calls = _client([full, [_item(numero="1000832-35.2025.8.24.0359")]])
    items = client.day("TJSC", date(2026, 9, 15))
    assert [c["pagina"] for c in calls] == ["1", "2"]
    assert calls[0]["dataDisponibilizacaoInicio"] == calls[0]["dataDisponibilizacaoFim"] == "2026-09-15"
    assert {i.numero_processo for i in items} == {"50247401420268240023", "10008323520258240359"}


def test_a_day_at_the_count_cap_raises():
    client, _ = _client([[_item()]], counts=djen.COUNT_CAP)
    with pytest.raises(DjenError, match="cap"):
        client.day("TJSP", date(2026, 9, 15))


def test_a_blocked_egress_raises():
    client = DjenClient(proxy="", transport=httpx.MockTransport(lambda r: httpx.Response(403, text="blocked")),
                        sleep=lambda s: None)
    with pytest.raises(DjenError, match="403"):
        client.day("TJSP", date(2026, 9, 15))


def test_rows_case_per_process_and_one_document_per_linked_act():
    items = [parse_item(_item()), parse_item(_item(tipo_doc="Edital", texto="Edital do art. 52, § 1º")),
             parse_item(_item(link=False))]
    cases, docs = rows_for(items, SEEN)
    assert len(cases) == 1
    case = cases[0]
    assert case["source"] == "djen" and case["devedor_nome"] is None
    assert case["aj_name"] is None and "first_seen_at" not in case
    assert len(docs) == 2  # the act with no link is a case signal only
    assert {d["tipo"] for d in docs} == {"decisao_deferimento", "relacao_credores_devedor"}
    assert all(d["found_on"] == f"{djen.BASE}/abc123/certidao" for d in docs)
    assert all(d["data_publicacao"] == "2026-09-15" for d in docs)
    assert all("texto" not in d for d in docs)  # the text is read, never stored


def test_a_host_that_never_answers_is_skipped_after_three_failures():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "esaj.dead.jus.br":
            raise httpx.ConnectTimeout("no answer", request=request)
        return httpx.Response(200)

    client = DjenClient(proxy="", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    dead = [client.status(f"https://esaj.dead.jus.br/doc?id={i}") for i in range(6)]
    assert dead == [None] * 6  # unchecked, never marked dead
    assert calls.count("esaj.dead.jus.br") == djen.HOST_FAILURES_TO_SKIP
    assert client.status("https://pje.live.jus.br/doc?id=1") == 200  # other hosts still checked


def test_a_failed_tribunal_is_an_error_row_and_the_run_is_red():
    class Down:
        def day(self, t, d):
            raise DjenError("DJEN HTTP 403")

        def close(self):
            pass

    ing = DjenIngestor.__new__(DjenIngestor)
    ing._pg, ing._client_factory, ing._head_budget = object(), Down, 0
    statuses = []

    async def fake_audited(pg, entity, doc_type, fn, **kw):
        try:
            return await fn()
        except Exception:
            statuses.append((doc_type, "error"))
            raise

    with patch.object(ingest_rj_djen, "audited", fake_audited):
        import asyncio
        with pytest.raises(RuntimeError, match="2 of 2 DJEN tribunals failed"):
            asyncio.run(ing.collect(["TJSP", "TJSC"], date(2026, 9, 15), date(2026, 9, 15)))
    assert statuses == [("djen:TJSP", "error"), ("djen:TJSC", "error")]


def test_the_workflow_passes_the_relay_and_proxy_to_the_djen_step():
    wf = (ROOT / ".github/workflows/rj_collect.yml").read_text()
    step = wf[wf.index("- name: Discover RJ cases on DJEN"):]
    assert "DJEN_RELAY_URL: https://zcjbtpxuhdekpwcxmepn.supabase.co/functions/v1/djen-relay" in step
    assert "DJEN_RELAY_TOKEN: ${{ secrets.DJEN_RELAY_TOKEN }}" in step
    assert "BR_PROXY_URL: ${{ secrets.BR_PROXY_URL }}" in step
    assert "python -m src.pipeline.ingest_rj_djen" in step
