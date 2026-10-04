"""HTTP server for the portfolio-diagnosis engine (map #510, slice E step 1).

    python -m src.portfolio.server            # 0.0.0.0:$PORT (default 8080), Flask's server
    gunicorn "src.portfolio.server:wsgi()"    # what the image runs (deploy/cloudflare/engine/)

``GET /health`` answers 200. ``POST /diagnose`` takes one statement (the
spreadsheet template ``.xlsx``, or a BTG PDF: the performance report or the
"Extrato da Conta Investimento", told apart by content) as a multipart field
``file`` or as the raw request body, runs the engine and the report exactly as
the two CLIs do (``diagnose`` then ``report.build``) and returns the PDF.
Several ``file`` parts (one statement per account, 10 MB in all) are read one by
one and consolidated (``consolidate.py``) before the engine runs.

Access: ``Authorization: Bearer <DEMO_ACCESS_TOKEN>``. Without the variable set
every ``/diagnose`` is refused with 503; a missing or wrong token gets 401.

Privacy: the upload is held in memory; the xlsx reader and the PDF renderer get
a private temporary directory that is deleted in a ``finally`` block. Log lines
carry status, timings, sizes and exception type names only, never the file, its
name, the holder, the CPF or the account, and an error answer is a fixed
Portuguese message with no stack trace and nothing of the request echoed.

A SILO that does not answer while the statement's lines are identified (a timeout,
a 5xx or a network error, still failing after the engine's one retry) is a
retryable failure, not a data gap: ``/diagnose`` answers 503 with ``Retry-After``
and ``X-Silo-Error: silo_unavailable`` and produces no PDF.

Data: SILO is read through the public read-only ``silo-mcp`` (``SILO_ENGINE_CLIENT``
``mcp``, the default, or ``postgrest``). There is deliberately no fake SILO
client here: canned rows on a real statement would be fabricated numbers. The
LLM provider is ``SILO_LLM_PROVIDER`` (``fake`` needs no key).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from src.portfolio.client import McpClient, PostgrestClient, SiloClient
from src.portfolio.common import SiloUnavailable
from src.portfolio.engine import default_params, dumps, run_engine
from src.portfolio.report import adapt, build, llm, redator
from src.portfolio.report.render import html_to_pdf
from src.portfolio.statement import Statement, read_statement

log = logging.getLogger("silo.portfolio.server")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TOKEN_ENV = "DEMO_ACCESS_TOKEN"
CLIENT_ENV = "SILO_ENGINE_CLIENT"

MSG = {
    400: "Envie o extrato no campo 'file' (multipart) ou no corpo da requisição.",
    401: "Acesso não autorizado.",
    404: "Caminho não encontrado.",
    405: "Método não permitido.",
    413: "Arquivo grande demais: o limite é 10 MB.",
    415: "Formato não suportado: envie a planilha modelo (.xlsx) ou o PDF do BTG (extrato da conta ou relatório de performance).",
    422: "Não foi possível ler o extrato. Confira se é a planilha modelo ou um PDF do BTG (extrato da conta ou relatório de performance).",
    500: "Erro interno ao gerar o diagnóstico.",
    502: "O relatório não pôde ser redigido agora. Tente de novo mais tarde.",
    503: "Serviço não configurado.",
}
# 503 for a SILO that did not answer (engine 1.7): retryable, and distinct from the unconfigured service.
MSG_UNAVAILABLE = "Os dados públicos do SILO não responderam agora. Nenhum relatório foi gerado; tente de novo em alguns minutos."
RETRY_AFTER_S = 120


class _Refusal(Exception):
    def __init__(self, status: int):
        self.status = status


def _unavailable(stage: str) -> tuple[Response, int]:
    """503 with ``Retry-After`` and a fixed ``X-Silo-Error`` code: SILO timed out or failed after the retry."""
    resp = jsonify({"erro": MSG_UNAVAILABLE})
    resp.headers["X-Silo-Stage"] = stage
    resp.headers["X-Silo-Error"] = SiloUnavailable.code
    resp.headers["Retry-After"] = str(RETRY_AFTER_S)
    return resp, 503


def _error(status: int, stage: str | None = None, exc: BaseException | None = None) -> tuple[Response, int]:
    resp = jsonify({"erro": MSG[status]})
    if stage:
        # Which step refused, so a deploy smoke can tell an egress or key failure
        # (stage engine or report) from a bad upload without reading the logs.
        resp.headers["X-Silo-Stage"] = stage
    if exc is not None:
        # The exception's type name (as the log line has it) and, for an HTTP
        # client error, its status code. Never its message: it can carry amounts.
        resp.headers["X-Silo-Error"] = type(exc).__name__
        code = getattr(exc, "status_code", None)
        if isinstance(code, int):
            resp.headers["X-Silo-Error-Status"] = str(code)
        # The provider's machine-readable error code (for example
        # "unsupported_country_region_territory"): an identifier, never free text.
        api_code = getattr(exc, "code", None)
        if isinstance(api_code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", api_code):
            resp.headers["X-Silo-Error-Code"] = api_code
    return resp, status


_IDENT = re.compile(r"^[A-Za-z_]+$")


def narrative_headers(narrative) -> dict[str, str]:
    """Why a narrative is unknown and what each LLM call used, safe for a header.

    ``X-Silo-Narrative-Reason`` is a bare identifier (an LLMError class name or
    ``revisor_removed_all``), never the exception message, which can quote the
    model. ``X-Silo-Llm-Calls`` is ``role:out=N:reasoning=N`` per call, numbers and
    fixed role names only: an output at the provider's max_output_tokens shows a
    truncation.
    """
    out: dict[str, str] = {}
    code = getattr(narrative, "reason_code", None)
    if code and _IDENT.match(str(code)):
        out["X-Silo-Narrative-Reason"] = str(code)
    parts = []
    for call in getattr(narrative, "calls", None) or []:
        role = str(call.get("role") or "llm")
        if not _IDENT.match(role):
            role = "llm"
        parts.append(f"{role}:out={int(call.get('output_tokens') or 0)}:reasoning={int(call.get('reasoning_tokens') or 0)}")
    if parts:
        out["X-Silo-Llm-Calls"] = ",".join(parts)
    return out


def default_client() -> SiloClient:
    kind = (os.environ.get(CLIENT_ENV) or "mcp").strip().lower()
    if kind == "mcp":
        return McpClient()
    if kind == "postgrest":
        return PostgrestClient()
    raise ValueError(f"{CLIENT_ENV} must be mcp or postgrest")


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"PK\x03\x04"):
        return "xlsx"
    if data.lstrip()[:5] == b"%PDF-":
        return "pdf"
    return None


def _read(data: bytes, fmt: str, workdir: Path) -> Statement:
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


def _authorized() -> None:
    expected = os.environ.get(TOKEN_ENV) or ""
    if not expected:
        raise _Refusal(503)
    header = request.headers.get("Authorization", "")
    scheme, _, given = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(given.strip().encode(), expected.encode()):
        raise _Refusal(401)


def _upload() -> list[bytes]:
    """Every ``file`` part of a multipart upload (one statement per account), or the raw body."""
    if request.content_length is not None and request.content_length > MAX_UPLOAD_BYTES:
        raise _Refusal(413)
    if request.mimetype == "multipart/form-data":
        parts = [f.read() for f in request.files.getlist("file")]
    else:
        parts = [request.get_data(cache=False)]
    if sum(len(d) for d in parts) > MAX_UPLOAD_BYTES:
        raise _Refusal(413)
    if not parts or not all(parts):
        raise _Refusal(400)
    return parts


def engine_rev(root: Path | None = None) -> str:
    """A content hash of ``src/portfolio`` (every file but bytecode), 12 hex digits.

    The image carries the same files as the checkout (Dockerfile.dockerignore), so
    a deploy smoke can compute it from the repository and wait until a Cloudflare
    instance answers with it: a rollout does not wait for instances to change image.
    """
    base = root or Path(__file__).resolve().parent
    h = hashlib.sha256()
    for f in sorted(p for p in base.rglob("*") if p.is_file()):
        rel = f.relative_to(base).as_posix()
        if "__pycache__" in rel.split("/") or rel.endswith(".pyc"):
            continue
        h.update(rel.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def create_app(client_factory: Callable[[], SiloClient] = default_client) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.logger.disabled = True  # Flask's own handler would log tracebacks; this module logs instead
    rev = engine_rev()

    @app.after_request
    def stamp(resp: Response) -> Response:
        resp.headers["X-Silo-Engine-Rev"] = rev
        return resp

    @app.get("/health")
    def health():
        return Response("ok\n", mimetype="text/plain")

    @app.post("/diagnose")
    def diagnose():
        t0 = time.monotonic()
        size = 0
        fmt = "-"
        stage = "auth"
        try:
            _authorized()
            stage = "upload"
            parts = _upload()
            size = sum(len(d) for d in parts)
            fmts = [_sniff(d) or "-" for d in parts]
            fmt = "+".join(fmts)
            if "-" in fmts:
                raise _Refusal(415)
            with tempfile.TemporaryDirectory(prefix="diag-") as tmp:
                work = Path(tmp)
                stage = "read"
                try:
                    stmts = [_read(d, f, work) for d, f in zip(parts, fmts)]
                    if len(stmts) == 1:
                        stmt = stmts[0]
                    else:
                        from src.portfolio.consolidate import consolidate

                        stmt = consolidate(stmts).statement
                except Exception as exc:  # noqa: BLE001 - every reader failure is one answer; the type alone is logged
                    log.warning("read failed: %s", type(exc).__name__)
                    raise _Refusal(422) from None
                del parts
                stage = "engine"
                t1 = time.monotonic()
                doc = run_engine(stmt, client_factory(), default_params(stmt.position_date))
                engine = json.loads(dumps(doc))  # the CLI's round trip, so the report sees the same JSON
                if adapt.is_engine_output(engine):
                    engine = adapt.to_view(engine)
                t2 = time.monotonic()
                stage = "report"
                try:
                    html_text, narrative = build.build(engine)
                except (llm.LLMError, redator.UnmaskedInputError) as exc:
                    log.warning("report failed: %s", type(exc).__name__)
                    raise _Refusal(502) from None
                stage = "pdf"
                pdf_path = html_to_pdf(html_text, work / "diagnostico.pdf")
                pdf = pdf_path.read_bytes()
                t3 = time.monotonic()
            log.info(
                "diagnose 200 format=%s files=%d in_bytes=%d out_bytes=%d engine_s=%.1f report_s=%.1f total_s=%.1f "
                "narrative=%s provider=%s cost_usd=%.4f",
                fmt, len(fmts), size, len(pdf), t2 - t1, t3 - t2, t3 - t0,
                narrative.status, narrative.provider, narrative.cost_usd,
            )
            return Response(
                pdf,
                mimetype="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="diagnostico.pdf"',
                    "Cache-Control": "no-store",
                    # The same fields as the log line, nothing of the statement.
                    "X-Silo-Narrative": str(narrative.status),
                    "X-Silo-Provider": str(narrative.provider),
                    "X-Silo-Cost-Usd": f"{narrative.cost_usd:.4f}",
                    "X-Silo-Seconds": f"{t3 - t0:.1f}",
                    **narrative_headers(narrative),
                },
            )
        except _Refusal as r:
            log.info("diagnose %d stage=%s format=%s in_bytes=%d total_s=%.1f", r.status, stage, fmt, size, time.monotonic() - t0)
            return _error(r.status, stage)
        except SiloUnavailable:
            # Identification could not finish because SILO did not answer: no PDF, the caller retries later.
            log.warning("diagnose 503 stage=%s format=%s in_bytes=%d error=%s total_s=%.1f",
                        stage, fmt, size, SiloUnavailable.code, time.monotonic() - t0)
            return _unavailable(stage)
        except RequestEntityTooLarge:
            log.info("diagnose 413 stage=%s total_s=%.1f", stage, time.monotonic() - t0)
            return _error(413, stage)
        except Exception as exc:  # noqa: BLE001 - no traceback in logs or answers: messages can carry amounts
            log.error("diagnose 500 stage=%s format=%s in_bytes=%d error=%s", stage, fmt, size, type(exc).__name__)
            return _error(500, stage, exc)

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        status = exc.code if exc.code in MSG else 500
        return _error(status)

    @app.errorhandler(Exception)
    def any_error(exc: Exception):
        log.error("unhandled %s", type(exc).__name__)
        return _error(500)

    return app


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def wsgi() -> Flask:
    """The image's entry point: ``gunicorn "src.portfolio.server:wsgi()"``."""
    _configure_logging()
    return create_app()


def main() -> None:
    """Local run with Flask's own threaded server."""
    _configure_logging()
    port = int(os.environ.get("PORT", "8080"))
    create_app().run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
