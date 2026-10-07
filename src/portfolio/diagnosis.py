"""One portfolio diagnosis, from the uploaded statements to the report: the entry point every caller shares.

    stmt = read_uploads([(data, "xlsx")], workdir)               # the readers, then consolidate.py
    result = diagnose(stmt, client_factory=McpClient, pdf_renderer=html_to_pdf, workdir=workdir)
    result.engine_json, result.view, result.html, result.narrative, result.pdf, result.record

``diagnose`` runs the steps ``server.py``'s ``/diagnose`` and the two CLIs
(``diagnose`` then ``report.build``) run: the client constraints are checked,
the engine runs, its JSON is serialised once (the masked artifact of the run
trace) and read back, so the report sees the same JSON the CLI writes; the view
is adapted, the Redator, the Revisor and the renderer write the HTML, and the
PDF is rendered when a renderer is given. ``render_report`` is the second half
alone, for an engine JSON already on disk (``report.build``'s CLI).

Its dependencies are parameters: the SILO client (a factory, called once after
the constraints passed), the investigator (a factory taking the report's one
cost meter), the LLM provider's name (``None``: ``SILO_LLM_PROVIDER``) and the
PDF renderer. What it learns about the run goes on a ``trace.RunRecord`` (ADR
0003): ``record.stage`` names the step running when an exception leaves.

A refusal the caller answers with a fixed message is a ``Refused`` subclass
carrying only the type name of the exception behind it, never its message:
``UnreadableStatement``, ``InvalidConstraints``, ``ReportFailed``. Anything else
(``SiloUnavailable`` among them) propagates unchanged.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.portfolio import client_fit, trace
from src.portfolio.client import SiloClient
from src.portfolio.engine import default_params, dumps, run_engine
from src.portfolio.report import adapt, build, llm, redator
from src.portfolio.report.render import Narrative
from src.portfolio.statement import Statement, read_statement


class Refused(Exception):
    """A step refused the run. ``exc_type`` is the type name of the exception behind it, for the trace only."""

    def __init__(self, exc_type: str | None = None):
        super().__init__(exc_type or type(self).__name__)
        self.exc_type = exc_type


class UnreadableStatement(Refused):
    """A statement could not be read, or several could not be consolidated."""


class InvalidConstraints(Refused):
    """The client constraints do not validate against the statement's position date."""


class ReportFailed(Refused):
    """The narrative could not be written: an LLM error, or an engine JSON that is not masked."""


@dataclass
class Report:
    view: dict[str, Any]
    html: str
    narrative: Narrative


@dataclass
class Diagnosis:
    engine_json: str  # the masked engine JSON, as the CLI writes it
    engine: dict[str, Any]  # that JSON read back
    view: dict[str, Any]  # what the report read (adapt.to_view of the engine's schema 1.x)
    html: str
    narrative: Narrative
    pdf: bytes | None
    record: trace.RunRecord
    engine_s: float  # wall seconds, for the caller's log line
    report_s: float  # the report and the PDF


def read_one(data: bytes, fmt: str, workdir: Path) -> Statement:
    """One statement from its bytes: ``pdf`` (either BTG layout, told apart by content) or ``xlsx`` (the template).

    The xlsx reader needs a path: the bytes are written in ``workdir`` and removed at once."""
    if fmt == "pdf":
        from src.portfolio.statement_pdf_extrato import read_any_pdf_bytes

        stmt, _diag, _layout = read_any_pdf_bytes(data)
        return stmt
    path = workdir / "extrato.xlsx"
    path.write_bytes(data)
    try:
        return read_statement(path)
    finally:
        path.unlink(missing_ok=True)


def read_uploads(parts: Sequence[tuple[bytes, str]], workdir: Path) -> Statement:
    """Every ``(bytes, format)`` part read, then consolidated when there are several (one per account).

    Any failure is ``UnreadableStatement`` with the exception's type name only."""
    try:
        stmts = [read_one(d, f, workdir) for d, f in parts]
        if len(stmts) == 1:
            return stmts[0]
        from src.portfolio.consolidate import consolidate

        return consolidate(stmts).statement
    except Exception as exc:  # noqa: BLE001 - every reader failure is one refusal; the type alone is kept
        raise UnreadableStatement(type(exc).__name__) from None


def render_report(
    engine: dict[str, Any],
    provider_name: str | None = None,
    signature: str | None = None,
    llm_review: bool = True,
    meter: llm.CostMeter | None = None,
) -> Report:
    """Engine JSON (schema 1.x, or a view already) to the report's HTML and narrative. LLM errors propagate."""
    view = adapt.to_view(engine) if adapt.is_engine_output(engine) else engine
    html_text, narrative = build.build(view, provider_name, signature, llm_review, meter=meter)
    return Report(view, html_text, narrative)


def diagnose(
    stmt: Statement,
    client_factory: Callable[[], SiloClient],
    constraints: Any = None,
    investigator_factory: Callable[[llm.CostMeter], Any] | None = None,
    provider_name: str | None = None,
    pdf_renderer: Callable[[str, Path], Path] | None = None,
    workdir: Path | None = None,
    record: trace.RunRecord | None = None,
) -> Diagnosis:
    """The engine and the report over one (consolidated) statement. ``pdf_renderer`` None: HTML only."""
    if pdf_renderer is not None and workdir is None:
        raise ValueError("a PDF needs a workdir")
    rec = record if record is not None else trace.RunRecord(start_ns=time.time_ns(), end_ns=0, status=0, stage="engine")
    rec.stage = "engine"
    t1 = time.monotonic()
    rec.engine_start_ns = time.time_ns()
    meter = llm.CostMeter()  # one per report: the investigator books first, the Redator and Revisor after
    investigator = investigator_factory(meter) if investigator_factory is not None else None
    extra: dict[str, Any] = {"investigator": investigator} if investigator is not None else {}
    try:
        # Checked here, before SILO is read, so a bad constraint is a refusal and not an engine failure.
        # The only validation of this run: the engine takes the typed result and does not check again.
        declared = client_fit.declare(constraints, stmt.position_date)
    except (ValueError, TypeError):
        raise InvalidConstraints() from None
    if declared is not None:
        extra["client_constraints"] = declared
    doc = run_engine(stmt, client_factory(), default_params(stmt.position_date), **extra)
    pending = getattr(getattr(getattr(investigator, "deps", None), "cache", None), "pending", None)
    rec.documents = pending() if callable(pending) else {}  # public documents read once (#605, Q35)
    rec.investigator_calls = [dict(c) for c in meter.calls]  # only the investigator has booked so far
    engine_text = dumps(doc)  # the masked engine JSON: the trace's artifact, hashed once
    rec.engine_json = engine_text.encode("utf-8")
    engine = json.loads(engine_text)  # the CLI's round trip, so the report sees the same JSON
    rec.engine_doc = trace_summary(engine)
    rec.engine_end_ns = time.time_ns()
    view = adapt.to_view(engine) if adapt.is_engine_output(engine) else engine
    t2 = time.monotonic()
    rec.stage = "report"
    rec.report_start_ns = time.time_ns()
    try:
        html_text, narrative = build.build(view, provider_name, meter=meter)
    except (llm.LLMError, redator.UnmaskedInputError) as exc:
        raise ReportFailed(type(exc).__name__) from None
    rec.narrative = narrative
    rec.html = html_text.encode("utf-8")  # kept in the trace for the owner's page, PDF or not
    rec.report_end_ns = time.time_ns()
    pdf = None
    if pdf_renderer is not None:
        rec.stage = "pdf"
        pdf = pdf_renderer(html_text, workdir / "diagnostico.pdf").read_bytes()
        rec.pdf = pdf
    t3 = time.monotonic()
    return Diagnosis(engine_text, engine, view, html_text, narrative, pdf, rec, t2 - t1, t3 - t2)


def trace_summary(engine: dict) -> dict:
    """The few engine fields the trace's ``engine.run`` span reads (statuses, reason codes, counts)."""
    stmt = engine.get("statement") or {}
    return {
        "section_status": engine.get("section_status") or {},
        "identification": {"counts": (engine.get("identification") or {}).get("counts") or {}},
        "statement": {"n_lines": stmt.get("n_lines"), "source_format": stmt.get("source_format")},
        "engine": {k: (engine.get("engine") or {}).get(k) for k in ("version", "client")},
    }
