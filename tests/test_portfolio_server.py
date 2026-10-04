"""Offline tests of the engine's HTTP server (src/portfolio/server.py).

SILO is read through the FakeClient over the canned rows, as in
test_portfolio_engine.py, and the report runs with SILO_LLM_PROVIDER=fake: no
network, no key. The real PDF renderer runs only where WeasyPrint is installed
(the engine image's CI job runs this file inside the image); elsewhere it is
stubbed, so the server path is still exercised by the offline suite.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("pydantic")

from src.portfolio import server  # noqa: E402
from src.portfolio.client import FakeClient, load_fake_rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs" / "reference" / "portfolio" / "statement-template.xlsx"
FAKE_ROWS = ROOT / "tests" / "fixtures" / "portfolio" / "fake_silo_rows.json"
TOKEN = "test-token-not-a-secret"
UPLOAD_NAME = "MARIA_FICTICIA_12345-6.xlsx"

# What the template carries about the holder; none of it may reach a log line.
PRIVATE = ["MARIA FICTÍCIA", "MARIA", "FICTICIA", "123.456.789-09", "12345678909", "12345-6", UPLOAD_NAME]


def _client():
    return FakeClient(load_fake_rows(FAKE_ROWS))


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv(server.TOKEN_ENV, TOKEN)
    monkeypatch.setenv("SILO_LLM_PROVIDER", "fake")
    return server.create_app(client_factory=_client).test_client()


def _auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _stub_pdf(monkeypatch):
    def fake_pdf(html_text, out_path):
        assert "<html" in html_text.lower()
        Path(out_path).write_bytes(b"%PDF-1.7\n% stub\n")
        return Path(out_path)

    monkeypatch.setattr(server, "html_to_pdf", fake_pdf)


def _assert_no_private(caplog, capfd):
    out, err = capfd.readouterr()
    text = caplog.text + out + err
    for s in PRIVATE:
        assert s not in text, f"{s!r} reached the logs"


def test_health(app):
    r = app.get("/health")
    assert r.status_code == 200 and r.data == b"ok\n"


def test_health_answers_without_the_token_configured(monkeypatch):
    monkeypatch.delenv(server.TOKEN_ENV, raising=False)
    r = server.create_app(client_factory=_client).test_client().get("/health")
    assert r.status_code == 200


@pytest.mark.parametrize("headers", [{}, _auth("wrong"), {"Authorization": TOKEN}, {"Authorization": f"Basic {TOKEN}"}])
def test_diagnose_refuses_without_the_right_bearer_token(app, headers):
    r = app.post("/diagnose", data=TEMPLATE.read_bytes(), headers=headers)
    assert r.status_code == 401
    assert r.json == {"erro": server.MSG[401]}


@pytest.mark.parametrize("value", [None, ""])
def test_diagnose_refuses_everything_when_the_token_is_not_configured(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(server.TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(server.TOKEN_ENV, value)
    c = server.create_app(client_factory=_client).test_client()
    for headers in ({}, _auth(""), _auth(TOKEN)):
        r = c.post("/diagnose", data=b"x", headers=headers)
        assert r.status_code == 503 and r.json == {"erro": server.MSG[503]}


def test_upload_over_the_limit_is_refused(app):
    big = b"PK\x03\x04" + b"0" * server.MAX_UPLOAD_BYTES
    r = app.post("/diagnose", data=big, headers=_auth())
    assert r.status_code == 413 and r.json == {"erro": server.MSG[413]}
    r = app.post(
        "/diagnose",
        data={"file": (io.BytesIO(big), UPLOAD_NAME)},
        content_type="multipart/form-data",
        headers=_auth(),
    )
    assert r.status_code == 413


def test_empty_and_unknown_uploads(app):
    assert app.post("/diagnose", data=b"", headers=_auth()).status_code == 400
    r = app.post("/diagnose", data=b"titular;cpf\n", headers=_auth())
    assert r.status_code == 415 and r.json == {"erro": server.MSG[415]}


def test_unreadable_statement_is_a_fixed_422_with_nothing_logged(app, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    r = app.post("/diagnose", data=b"PK\x03\x04 " + "MARIA FICTÍCIA 123.456.789-09 not a zip".encode(), headers=_auth())
    assert r.status_code == 422 and r.json == {"erro": server.MSG[422]}
    _assert_no_private(caplog, capfd)


def test_statement_that_does_not_reconcile_is_a_fixed_422(app, caplog, capfd, tmp_path):
    from openpyxl import load_workbook

    wb = load_workbook(TEMPLATE)
    ws = wb.worksheets[0]
    for row in ws.iter_rows():
        if row[0].value == "total_extrato":
            row[1].value = 1.0
    bad = tmp_path / "bad.xlsx"
    wb.save(bad)
    caplog.set_level(logging.DEBUG)
    r = app.post(
        "/diagnose",
        data={"file": (io.BytesIO(bad.read_bytes()), UPLOAD_NAME)},
        content_type="multipart/form-data",
        headers=_auth(),
    )
    assert r.status_code == 422 and r.json == {"erro": server.MSG[422]}
    assert b"5651424" not in r.data and b"MARIA" not in r.data
    _assert_no_private(caplog, capfd)


def test_engine_failure_is_a_fixed_500_with_no_traceback(monkeypatch, caplog, capfd):
    monkeypatch.setenv(server.TOKEN_ENV, TOKEN)

    def boom():
        raise RuntimeError("MARIA FICTÍCIA 12345-6")

    c = server.create_app(client_factory=boom).test_client()
    caplog.set_level(logging.DEBUG)
    r = c.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth())
    assert r.status_code == 500 and r.json == {"erro": server.MSG[500]}
    assert "Traceback" not in caplog.text
    _assert_no_private(caplog, capfd)


def test_missing_llm_key_is_a_fixed_502(monkeypatch, app):
    monkeypatch.setenv("SILO_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _stub_pdf(monkeypatch)
    r = app.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth())
    assert r.status_code == 502 and r.json == {"erro": server.MSG[502]}


@pytest.mark.parametrize("multipart", [False, True])
def test_diagnose_returns_a_pdf_with_the_renderer_stubbed(app, monkeypatch, caplog, capfd, multipart):
    _stub_pdf(monkeypatch)
    caplog.set_level(logging.DEBUG)
    if multipart:
        r = app.post(
            "/diagnose",
            data={"file": (io.BytesIO(TEMPLATE.read_bytes()), UPLOAD_NAME)},
            content_type="multipart/form-data",
            headers=_auth(),
        )
    else:
        r = app.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth())
    assert r.status_code == 200, r.data[:200]
    assert r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert r.headers["Cache-Control"] == "no-store"
    assert "diagnose 200 format=xlsx" in caplog.text
    _assert_no_private(caplog, capfd)


def test_diagnose_renders_a_real_pdf(app, caplog, capfd):
    pytest.importorskip("weasyprint")
    caplog.set_level(logging.DEBUG)
    r = app.post(
        "/diagnose",
        data={"file": (io.BytesIO(TEMPLATE.read_bytes()), UPLOAD_NAME)},
        content_type="multipart/form-data",
        headers=_auth(),
    )
    assert r.status_code == 200, r.data[:200]
    assert r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert len(r.data) > 10_000
    _assert_no_private(caplog, capfd)


def test_temporary_files_are_removed(app, monkeypatch, tmp_path):
    monkeypatch.setattr(server.tempfile, "tempdir", str(tmp_path))
    _stub_pdf(monkeypatch)
    assert app.post("/diagnose", data=TEMPLATE.read_bytes(), headers=_auth()).status_code == 200
    assert app.post("/diagnose", data=b"PK\x03\x04 broken", headers=_auth()).status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_unknown_path_and_method_answer_json(app):
    assert app.get("/nope").status_code == 404
    r = app.get("/diagnose")
    assert r.status_code == 405 and r.json == {"erro": server.MSG[405]}
