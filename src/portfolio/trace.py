"""One OTLP/JSON trace per portfolio diagnosis (ADR 0003).

``build_trace`` turns what ``server.diagnose`` collected about one run into an
OpenTelemetry trace export (``resourceSpans`` -> ``scopeSpans`` -> ``spans``, the
OTLP/JSON encoding: attributes as ``[{key, value: {stringValue|intValue|...}}]``,
64-bit integers and nanosecond times as strings, ids as lowercase hex). The
Worker writes it to the private R2 bucket ``silo-diagnosis-traces`` together with
the large items, which are separate objects named by their SHA-256
(``artifact_objects``): the masked engine JSON and the PDF.

Span and attribute names follow the OpenTelemetry GenAI semantic conventions
pinned in ``GENAI_SEMCONV`` where one exists: ``invoke_agent <name>`` spans with
``gen_ai.operation.name``, ``gen_ai.agent.name``, ``gen_ai.provider.name``,
``gen_ai.request.model``, ``gen_ai.usage.input_tokens`` and
``gen_ai.usage.output_tokens``; ``error.type`` and the ``exception`` event with
``exception.type``. ``invoke_workflow diagnosis`` (the root) and ``engine.run``
are this application's own names, and every ``app.*`` attribute is ours.

What a trace never carries: the uploaded statement's bytes or any part of them,
an exception message (only its type name), the Revisor's reason text or a
finding's text (a fixed reason code and the text's SHA-256 instead), and the
free-text ``reason`` of a section (its status and reason codes only). The engine
JSON artifact is the engine's own output, in which the statement readers already
replaced holder, CPF and account with fixed tokens (``src/portfolio/mask.py``).

Pure and offline: no clock or randomness except where the caller lets it default.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

GENAI_SEMCONV = "open-telemetry/semantic-conventions-genai@2026-10-02"
SCOPE_NAME = "silo.portfolio.diagnosis"
SCOPE_VERSION = "1"
SERVICE_NAME = "silo-portfolio-engine"

SPAN_KIND_INTERNAL = 1
STATUS_UNSET, STATUS_OK, STATUS_ERROR = 0, 1, 2

TRACE_PREFIX = "traces"
ARTIFACT_PREFIX = "artifacts"

# Removal.reason (src/portfolio/report/revisor.py) is Portuguese text and, for the LLM pass, model prose.
# Only the fixed code below reaches a trace. Order matters: the first prefix that matches wins.
_REMOVAL_CODES: tuple[tuple[str, str], ...] = (
    ("Revisor (LLM)", "llm_review"),
    ("marcador malformado", "malformed_placeholder"),
    ("algarismo fora de marcador", "digit_outside_placeholder"),
    ("fonte citada fora da proveniência", "source_outside_provenance"),
    ("risco só em tabela", "risk_table_only"),
    ("semáforo do movimento incomum", "movement_light_table_only"),
    ("movimento incomum", "movement_attention_table_only"),
    ("marcador sem caminho", "placeholder_without_path"),
    ("marcador com valor nulo", "placeholder_null"),
    ("marcador não escalar", "placeholder_not_scalar"),
    ("valor extremo", "extreme_value_unconfirmed"),
    ("sem citação de proveniência", "no_citation"),
    ("citação inexistente", "unknown_citation"),
    ("sem título", "no_title"),
    ("nenhuma frase restou", "no_sentence_left"),
)
_TITLE_PREFIX = "título: "


def removal_code(reason: str | None) -> tuple[str, str]:
    """``(code, part)`` for a Revisor removal reason; ``part`` is ``title`` or ``text``. Never the reason text."""
    text = str(reason or "")
    part = "text"
    if text.startswith(_TITLE_PREFIX):
        part, text = "title", text[len(_TITLE_PREFIX):]
    for prefix, code in _REMOVAL_CODES:
        if text.startswith(prefix):
            return code, part
    return "other", part


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def _value(v: Any) -> dict[str, Any]:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_value(x) for x in v]}}
    return {"stringValue": str(v)}


def attributes(attrs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """OTLP/JSON key-value list; a ``None`` value is left out, never written as a guess."""
    return [{"key": k, "value": _value(v)} for k, v in attrs.items() if v is not None]


@dataclass
class RunRecord:
    """What ``server.diagnose`` collected about one run. Times are unix nanoseconds."""

    start_ns: int
    end_ns: int
    status: int
    stage: str
    files: int = 0
    formats: str = "-"
    in_bytes: int = 0
    engine_rev: str = ""
    schema_version: str | None = None
    git_sha: str | None = None
    exc_type: str | None = None
    engine_start_ns: int | None = None
    engine_end_ns: int | None = None
    report_start_ns: int | None = None
    report_end_ns: int | None = None
    engine_doc: Mapping[str, Any] | None = None
    narrative: Any = None
    engine_json: bytes | None = None
    pdf: bytes | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # engine 1.12: the investigator's read-once cache entries (public documents only), for the Worker to write
    documents: dict[str, bytes] = field(default_factory=dict)
    # engine 1.12: the investigator's calls on the report's cost meter (role, model, tokens, cost; no content)
    investigator_calls: list[dict[str, Any]] = field(default_factory=list)


def _span(trace_id: str, span_id: str, parent: str | None, name: str, start: int, end: int,
          attrs: Mapping[str, Any], status: int = STATUS_UNSET, events: Iterable[dict] = ()) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": SPAN_KIND_INTERNAL,
        "startTimeUnixNano": str(int(start)),
        "endTimeUnixNano": str(int(max(end, start))),
        "attributes": attributes(attrs),
        "status": {"code": status},
    }
    if parent:
        span["parentSpanId"] = parent
    ev = list(events)
    if ev:
        span["events"] = ev
    return span


def _event(name: str, at: int, attrs: Mapping[str, Any]) -> dict[str, Any]:
    return {"timeUnixNano": str(int(at)), "name": name, "attributes": attributes(attrs)}


def _engine_attrs(doc: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, sec in (doc.get("section_status") or {}).items():
        out[f"app.section.{name}.status"] = str(sec.get("status"))
        out[f"app.section.{name}.reason_codes"] = [str(c) for c in sec.get("reason_codes") or []]
    counts = (doc.get("identification") or {}).get("counts") or {}
    for k, v in counts.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[f"app.identification.{k}"] = v
    stmt = doc.get("statement") or {}
    if isinstance(stmt.get("n_lines"), int):
        out["app.statement.n_lines"] = stmt["n_lines"]
    if isinstance(stmt.get("source_format"), str):
        out["app.statement.source_format"] = stmt["source_format"]
    eng = doc.get("engine") or {}
    if isinstance(eng.get("version"), str):
        out["app.engine.version"] = eng["version"]
    if isinstance(eng.get("client"), str):
        out["app.engine.client"] = eng["client"]
    return out


def _agent_role(call: Mapping[str, Any]) -> str:
    # The fake provider books its calls as role "fake"; only the Redator calls it (build.make_narrative
    # skips the LLM Revisor for the fake provider), so they belong to the redator span.
    role = str(call.get("role") or "")
    return "revisor" if role == "revisor" else "redator"


def _is_investigator(call: Mapping[str, Any]) -> bool:
    return str(call.get("role") or "").startswith("investigator")


# engine 1.12 (#605): the investigator's roles on the report's one cost meter, by span. Exa runs and page reads
# (role investigator_exa) belong to the investigator's span, priced like the LLM calls (app.cost_usd).
_INVESTIGATOR_SPANS = (("investigator", ("investigator_extractor", "investigator_exa")),
                       ("investigator_judge", ("investigator_judge",)))


def _investigator_spans(rec: RunRecord, trace_id: str, parent: str) -> list[dict[str, Any]]:
    """``invoke_agent investigator`` (extractor and Exa) and ``invoke_agent investigator_judge``, when they ran.

    The calls come from ``rec.investigator_calls`` (set by the server right after the engine, so a report that
    fails later keeps them), else from the narrative's meter. Only roles, models, tokens and cost: never a
    prompt, a document or a fact.
    """
    calls = list(rec.investigator_calls or [])
    if not calls and rec.narrative is not None:
        calls = [c for c in list(getattr(rec.narrative, "calls", None) or []) if _is_investigator(c)]
    if not calls:
        return []
    start = rec.engine_start_ns or rec.start_ns
    spans = []
    for name, roles in _INVESTIGATOR_SPANS:
        cs = [c for c in calls if str(c.get("role") or "") in roles]
        if not cs:
            continue
        ts = [int(c["ended_unix_nano"]) for c in cs if isinstance(c.get("ended_unix_nano"), int)]
        end = max(ts) if ts else (rec.engine_end_ns or rec.end_ns)
        llm_cs = [c for c in cs if c.get("role") != "investigator_exa"]
        exa_cs = [c for c in cs if c.get("role") == "investigator_exa"]
        attrs: dict[str, Any] = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": name,
            "gen_ai.request.model": next((str(c["model"]) for c in llm_cs if c.get("model")), None),
            "gen_ai.response.model": next((str(c["model"]) for c in reversed(llm_cs) if c.get("model")), None),
            "gen_ai.usage.input_tokens": sum(int(c.get("input_tokens") or 0) for c in llm_cs) if llm_cs else None,
            "gen_ai.usage.output_tokens": sum(int(c.get("output_tokens") or 0) for c in llm_cs) if llm_cs else None,
            "app.llm.calls": len(llm_cs),
            "app.llm.reasoning_tokens": sum(int(c.get("reasoning_tokens") or 0) for c in llm_cs) if llm_cs else None,
            "app.exa.calls": len(exa_cs) if name == "investigator" else None,
            "app.exa.cost_usd": round(sum(float(c.get("cost_usd") or 0.0) for c in exa_cs), 6) if exa_cs else None,
            "app.cost_usd": round(sum(float(c.get("cost_usd") or 0.0) for c in cs), 6),
        }
        spans.append(_span(trace_id, new_span_id(), parent, f"invoke_agent {name}", start, end, attrs))
    return spans


def _agent_spans(rec: RunRecord, trace_id: str, parent: str) -> list[dict[str, Any]]:
    n = rec.narrative
    if n is None or rec.report_start_ns is None:
        return []
    # the investigator's calls are on the same meter (engine 1.12) but get their own spans (_investigator_spans)
    calls = [c for c in list(getattr(n, "calls", None) or []) if not _is_investigator(c)]
    report_end = rec.report_end_ns or rec.end_ns
    by_role: dict[str, list[Mapping[str, Any]]] = {"redator": [], "revisor": []}
    for c in calls:
        by_role[_agent_role(c)].append(c)

    def ended(cs: list[Mapping[str, Any]]) -> int | None:
        ts = [int(c["ended_unix_nano"]) for c in cs if isinstance(c.get("ended_unix_nano"), int)]
        return max(ts) if ts else None

    removed = list(getattr(n, "removed", None) or [])
    spans = []
    t = rec.report_start_ns
    for role in ("redator", "revisor"):
        cs = by_role[role]
        rem = [r for r in removed if role == "revisor"]
        if role == "revisor" and not cs and not rem:
            continue
        end = ended(cs) or (report_end if role == "revisor" or not by_role["revisor"] else t)
        tok_in = sum(int(c.get("input_tokens") or 0) for c in cs)
        tok_out = sum(int(c.get("output_tokens") or 0) for c in cs)
        attrs: dict[str, Any] = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": role,
            "gen_ai.provider.name": str(getattr(n, "provider", "") or "") or None,
            "gen_ai.request.model": str(getattr(n, "model", "") or "") or None,
            "gen_ai.response.model": next((str(c["model"]) for c in reversed(cs) if c.get("model")), None),
            "gen_ai.usage.input_tokens": tok_in if cs else None,
            "gen_ai.usage.output_tokens": tok_out if cs else None,
            "app.llm.calls": len(cs),
            "app.llm.reasoning_tokens": sum(int(c.get("reasoning_tokens") or 0) for c in cs) if cs else None,
            "app.cost_usd": round(sum(float(c.get("cost_usd") or 0.0) for c in cs), 6),
        }
        if role == "redator":
            attrs["app.narrative.status"] = str(getattr(n, "status", "") or "") or None
            code = getattr(n, "reason_code", None)
            attrs["app.narrative.reason_code"] = str(code) if code else None
            attrs["app.findings.kept"] = len(getattr(n, "kept", None) or [])
        else:
            attrs["app.findings.removed"] = len(rem)
        events = []
        for r in rem:
            code, part = removal_code(getattr(r, "reason", ""))
            events.append(_event("app.revisor.removed", end, {
                "app.revisor.rule": code,
                "app.revisor.part": part,
                "app.finding.section": str(getattr(r, "section", "") or "") or None,
                "app.finding.id": str(getattr(r, "finding_id", "") or "") or None,
                "app.finding.whole": bool(getattr(r, "whole_finding", False)),
                "app.finding.text_sha256": sha256_hex(str(getattr(r, "text", "") or "").encode()),
            }))
        status = STATUS_OK if role == "redator" and getattr(n, "status", None) == "complete" else STATUS_UNSET
        spans.append(_span(trace_id, new_span_id(), parent, f"invoke_agent {role}", t, end, attrs, status, events))
        t = end
    return spans


def build_trace(rec: RunRecord, trace_id: str | None = None) -> dict[str, Any]:
    """The OTLP/JSON export of one run: a root span, ``engine.run`` when the engine started, and the agents."""
    trace_id = trace_id or new_trace_id()
    root_id = new_span_id()
    failed = rec.status != 200
    root_attrs: dict[str, Any] = {
        "app.semconv": GENAI_SEMCONV,
        "app.engine.schema_version": rec.schema_version,
        "app.engine.rev": rec.engine_rev or None,
        "app.http.status": rec.status,
        "app.failed_stage": rec.stage if failed else None,
        "app.files": rec.files,
        "app.formats": rec.formats,
        "app.in_bytes": rec.in_bytes,
        "app.git_sha": rec.git_sha,
        "app.pdf.sha256": sha256_hex(rec.pdf) if rec.pdf is not None else None,
        "app.pdf.bytes": len(rec.pdf) if rec.pdf is not None else None,
        "app.engine_json.sha256": sha256_hex(rec.engine_json) if rec.engine_json is not None else None,
        "app.engine_json.bytes": len(rec.engine_json) if rec.engine_json is not None else None,
        # the report's one meter (engine 1.12: investigator included); without a narrative, what the investigator spent
        "app.cost_usd": (float(getattr(rec.narrative, "cost_usd", 0.0) or 0.0) if rec.narrative is not None
                         else round(sum(float(c.get("cost_usd") or 0.0) for c in rec.investigator_calls), 6)
                         if rec.investigator_calls else None),
        "error.type": rec.exc_type if failed else None,
        **rec.extra,
    }
    events = [_event("exception", rec.end_ns, {"exception.type": rec.exc_type})] if failed and rec.exc_type else []
    spans = [_span(trace_id, root_id, None, "invoke_workflow diagnosis", rec.start_ns, rec.end_ns, root_attrs,
                   STATUS_ERROR if failed else STATUS_OK, events)]
    if rec.engine_start_ns is not None:
        engine_failed = failed and rec.stage == "engine"
        eng_attrs = _engine_attrs(rec.engine_doc or {})
        if engine_failed:
            eng_attrs["error.type"] = rec.exc_type
        spans.append(_span(trace_id, new_span_id(), root_id, "engine.run", rec.engine_start_ns,
                           rec.engine_end_ns or rec.end_ns, eng_attrs,
                           STATUS_ERROR if engine_failed else (STATUS_OK if rec.engine_end_ns else STATUS_UNSET),
                           [_event("exception", rec.end_ns, {"exception.type": rec.exc_type})]
                           if engine_failed and rec.exc_type else []))
    spans.extend(_investigator_spans(rec, trace_id, root_id))
    spans.extend(_agent_spans(rec, trace_id, root_id))
    return {
        "resourceSpans": [{
            "resource": {"attributes": attributes({"service.name": SERVICE_NAME, "service.version": rec.engine_rev or None})},
            "scopeSpans": [{
                "scope": {"name": SCOPE_NAME, "version": SCOPE_VERSION},
                "schemaUrl": "",
                "spans": spans,
            }],
        }]
    }


def trace_id_of(trace: Mapping[str, Any]) -> str:
    return trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"]


def root_attributes(trace: Mapping[str, Any]) -> dict[str, Any]:
    """The root span's attributes as a plain dict (tests and the deploy probe read it)."""
    span = trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    out: dict[str, Any] = {}
    for kv in span["attributes"]:
        v = kv["value"]
        out[kv["key"]] = next(iter(v.values()))
    return out


def artifact_objects(engine_json: bytes | None, pdf: bytes | None) -> dict[str, bytes]:
    """``{key: bytes}`` of the large items, each named by its SHA-256: ``artifacts/<sha>.json`` and ``.pdf``."""
    out: dict[str, bytes] = {}
    if engine_json is not None:
        out[f"{ARTIFACT_PREFIX}/{sha256_hex(engine_json)}.json"] = engine_json
    if pdf is not None:
        out[f"{ARTIFACT_PREFIX}/{sha256_hex(pdf)}.pdf"] = pdf
    return out
