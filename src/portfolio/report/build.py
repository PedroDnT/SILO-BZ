"""CLI: engine JSON to a Portuguese report (HTML and PDF).

    python -m src.portfolio.report.build engine.json --out report.pdf \\
        [--html report.html] [--provider fake|anthropic|openai] [--signature TEXT]

``--provider fake`` writes the findings with the deterministic template writer
and needs no network and no key. ``--provider anthropic`` (default, or
``SILO_LLM_PROVIDER``) uses the Redator and Revisor over the Messages API
(``ANTHROPIC_API_KEY``); ``--provider openai`` over the Responses API
(``OPENAI_API_KEY``, model ``SILO_LLM_MODEL``, default ``gpt-5.1`` at medium
reasoning). Both stay within the US$1.00 per report cap. Without ``--out`` only
HTML is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.portfolio.report import adapt, llm, redator, revisor
from src.portfolio.report.render import Narrative, html_to_pdf, render_html


def make_narrative(engine: dict, provider: llm.Provider, llm_review: bool = True) -> Narrative:
    """Redator, then the deterministic Revisor, then the optional LLM pass."""
    meter = provider.meter
    drafted = redator.write(engine, provider)
    narrative = Narrative(
        status=drafted.status,
        reason=drafted.reason,
        reason_code=drafted.reason_code,
        provider=provider.name,
        model=getattr(provider, "model", ""),
        cost_cap_usd=meter.cap_usd,
    )
    if drafted.status == "complete":
        result = revisor.check(engine, drafted.findings)
        if llm_review and provider.name != "fake":
            result = revisor.llm_review(engine, result, provider)
        narrative.kept, narrative.removed, narrative.notes = result.kept, result.removed, result.notes
        if not result.kept:
            narrative.status = "unknown"
            narrative.reason = "o Revisor removeu todos os achados"
            narrative.reason_code = "revisor_removed_all"
    narrative.served_by = list(getattr(provider, "served_by", []))
    narrative.cost_usd = meter.spent_usd
    return narrative


def build(
    engine: dict,
    provider_name: str | None = None,
    signature: str | None = None,
    llm_review: bool = True,
) -> tuple[str, Narrative]:
    meter = llm.CostMeter()
    name = (provider_name or "").strip().lower() or None
    provider = llm.get_provider(name, meter=meter, fake_responses=lambda s, u, sch: redator.template_findings(_engine_from_user(u)))
    narrative = make_narrative(engine, provider, llm_review)
    narrative.calls = list(meter.calls)
    return render_html(engine, narrative, signature), narrative


def _engine_from_user(user_message: str) -> dict:
    """The fake provider's view: the engine JSON the Redator put in the user message."""
    start = user_message.index("\n") + 1
    end = user_message.rindex("\n\nEscreva")
    return json.loads(user_message[start:end])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.portfolio.report.build", description=__doc__.split("\n\n")[0])
    ap.add_argument("engine", help="engine output JSON")
    ap.add_argument("--out", help="PDF output path")
    ap.add_argument("--html", help="HTML output path")
    ap.add_argument("--provider", choices=["fake", "anthropic", "openai"], help="default: SILO_LLM_PROVIDER or anthropic")
    ap.add_argument("--signature", help="signature line (default: SILO_REPORT_SIGNATURE or the owner's)")
    ap.add_argument("--no-llm-review", action="store_true", help="skip the optional LLM pass of the Revisor")
    args = ap.parse_args(argv)
    if not args.out and not args.html:
        ap.error("give --out and/or --html")

    engine = json.loads(Path(args.engine).read_text(encoding="utf-8"))
    if adapt.is_engine_output(engine):
        engine = adapt.to_view(engine)  # the engine's schema 1.x, mapped to the report's view
    try:
        html_text, narrative = build(engine, args.provider, args.signature, not args.no_llm_review)
    except (llm.LLMError, redator.UnmaskedInputError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.html:
        Path(args.html).write_text(html_text, encoding="utf-8")
    if args.out:
        html_to_pdf(html_text, args.out)
    served = f", served by {sorted(set(narrative.served_by))}" if narrative.served_by else ""
    print(
        f"narrative={narrative.status} kept={len(narrative.kept)} removed={len(narrative.removed)} "
        f"provider={narrative.provider} model={narrative.model}{served} "
        f"cost_usd={narrative.cost_usd:.4f}/{narrative.cost_cap_usd:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
