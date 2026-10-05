"""Run the investigator of official documents by hand on PUBLIC assets (engine 1.12, #605).

    python scripts/investigate_documents.py --cra-isin <ISIN> [--credit-json row.json] \\
        [--fip-cnpj <14 digits>] --out facts.json [--fixtures DIR] [--canned-extraction FILE] [--no-judge]

Never pass a client's position: only public identifiers (an ISIN, a CETIP code, a fund's CNPJ) go in, and
the output is the ``investigation`` section the engine would write for them (facts with citations,
documents consulted, discarded count, messages).

Live (default): Fundos.NET and RAD over the network, the extractor and judge from ``SILO_LLM_PROVIDER`` and
the ``SILO_INVESTIGATOR_*_MODEL`` variables, Exa when ``EXA_API_KEY`` is set.

``--fixtures DIR`` answers from files captured elsewhere, for a session whose network cannot reach FNET:
``listar_<term>.json`` (listarFundos), ``lista_idFundo_<id>.json`` and ``lista_cnpj_<cnpj>.json`` (one listing
page each), ``fnet_<id>.txt`` or ``.pdf`` (a document body). Anything not captured answers 404, which the
investigator reports as "não lido".

``--canned-extraction FILE`` replaces the LLM extractor with a list of ``{"match": <text>, "facts": [...]}``:
the facts of the first entry whose ``match`` is in the document. It is for a session with no LLM key; the
tiers (A, B, C) and the number rule still run, in code, against the real document text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio.client import FakeClient, McpClient, utc_now  # noqa: E402
from src.portfolio.investigator import extract as ex  # noqa: E402
from src.portfolio.investigator import run as R  # noqa: E402
from src.portfolio.investigator.cache import MemoryDocumentCache  # noqa: E402
from src.portfolio.investigator.sources import ExaClient, HttpResponse, UrllibHttp  # noqa: E402
from src.portfolio.report.llm import FakeProvider  # noqa: E402


class FixtureHttp:
    """FNET answers from captured files; every other request is a 404 (nothing is invented)."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[str] = []

    def _file(self, name: str, ctype: str) -> HttpResponse:
        p = self.root / name
        if not p.exists():
            return HttpResponse(404, "text/plain", "não capturado".encode("utf-8"))
        return HttpResponse(200, ctype, p.read_bytes())

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> HttpResponse:
        params = params or {}
        self.calls.append(url)
        if url.endswith("/listarFundos"):
            return self._file(f"listar_{params.get('term')}.json", "application/json")
        if url.endswith("/pesquisarGerenciadorDocumentosDados"):
            if int(params.get("s", 0)) > 0:
                return HttpResponse(200, "application/json", b'{"data": [], "recordsTotal": 0}')
            key = f"idFundo_{params['idFundo']}" if "idFundo" in params else f"cnpj_{params.get('cnpjFundo')}"
            return self._file(f"lista_{key}.json", "application/json")
        if url.endswith("/downloadDocumento"):
            fid = params.get("id")
            if (self.root / f"fnet_{fid}.pdf").exists():
                return self._file(f"fnet_{fid}.pdf", "application/pdf")
            return self._file(f"fnet_{fid}.txt", "text/plain; charset=utf-8")
        return HttpResponse(404, "text/plain", b"")

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> HttpResponse:
        self.calls.append(url)
        return HttpResponse(404, "text/plain", b"")


def canned_models(path: Path, judge: bool) -> ex.Models:
    entries = json.loads(path.read_text(encoding="utf-8"))

    def respond(system, user, schema):
        text = json.loads(user)["text"]
        for e in entries:
            if e["match"] in text:
                return {"facts": e["facts"]}
        return {"facts": []}

    extractor = FakeProvider(respond)
    extractor.model = "canned-extraction"
    if not judge:
        return ex.pair(extractor, None)
    raise SystemExit("--canned-extraction runs without a judge: a canned 'yes' would confirm nothing")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cra-isin", help="ISIN of a public CRA")
    ap.add_argument("--cri-isin", help="ISIN of a public CRI")
    ap.add_argument("--credit-json", help="the portfolio_instruments row of that CRA or CRI, for the cross-check")
    ap.add_argument("--fip-cnpj", help="CNPJ of a public FIP")
    ap.add_argument("--fip-name", help="its name as CVM publishes it")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fixtures", help="answer FNET from captured files in this folder")
    ap.add_argument("--canned-extraction", help="canned extractor facts (no LLM key in this session)")
    ap.add_argument("--no-judge", action="store_true", help="tier B off")
    args = ap.parse_args(argv)

    http = FixtureHttp(Path(args.fixtures)) if args.fixtures else UrllibHttp(timeout=60.0)
    if args.canned_extraction:
        models = canned_models(Path(args.canned_extraction), judge=not args.no_judge)
    else:
        models = ex.models_from_env()
        if args.no_judge:
            models = ex.pair(models.extractor, None, models.meter)
    import os

    key = (os.environ.get("EXA_API_KEY") or "").strip()
    exa = ExaClient(UrllibHttp(timeout=60.0), key) if key and not args.fixtures else None
    deps = R.InvestigatorDeps(http=http, cache=MemoryDocumentCache(), models=models, exa=exa,
                              exa_note=None if exa else R.MSG_NO_EXA)
    credit = json.loads(Path(args.credit_json).read_text(encoding="utf-8")) if args.credit_json else None
    if credit is not None:
        credit = {**credit, "matched": True}
    triggers = []
    for tipo, isin in (("CRA", args.cra_isin), ("CRI", args.cri_isin)):
        if isin:
            triggers.append(R.manual_trigger(len(triggers) + 1, tipo, isin=isin, codigo=(credit or {}).get("code"),
                                             credit=credit))
    if args.fip_cnpj:
        triggers.append(R.manual_trigger(len(triggers) + 1, "FIP", cnpj=args.fip_cnpj, nome_cvm=args.fip_name))
    if not triggers:
        ap.error("nothing to investigate: pass --cra-isin, --cri-isin or --fip-cnpj")
    client = FakeClient({}) if args.fixtures else McpClient()
    section = R.Investigator(deps).run_triggers(triggers, client, utc_now)
    section["run"] = {"mode": "fixtures" if args.fixtures else "live", "requests": len(getattr(http, "calls", [])),
                      "extractor": "canned" if args.canned_extraction else models.extractor_model}
    Path(args.out).write_text(json.dumps(section, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = section["counts"]
    print(f"triggers={c['triggers']} facts={c['facts']} (A={c['tier_a']} B={c['tier_b']}) discarded={c['discarded']} "
          f"divergences={c['divergences']} documents read={c['documents_read']} not read={c['documents_not_read']} "
          f"searches={section['searches_used']}")
    for m in section["messages"]:
        print(" -", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
