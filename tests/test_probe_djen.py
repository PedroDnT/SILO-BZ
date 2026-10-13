"""scripts/probe_djen.py (#843): offline, DJEN mocked. Counts only, failures raise."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("probe_djen", ROOT / "scripts" / "probe_djen.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

ITEMS = [
    {"codigoClasse": 129, "numero_processo": "10000000020268260100",
     "texto": "EDITAL (art. 52, § 1º) ... DEFERIU O PROCESSAMENTO ... Administradora Judicial: X"},
    {"nomeClasse": "Recuperação Extrajudicial", "numero_processo": "",
     "texto": "intimação sem administrador"},
    {"codigoClasse": 7, "numero_processo": "20000000020268260100",
     "texto": "ação de cobrança; recuperação judicial citada de passagem"},
]


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_summary_counts_flags_without_text():
    totals = probe.summarise(ITEMS)
    assert totals["items"] == 3
    assert totals["rj_class"] == 2
    assert totals["deferimento"] == 1
    assert totals["edital_art52"] == 1
    assert totals["names_aj"] == 1
    assert totals["rj_class_and_names_aj"] == 1
    assert totals["has_process_number"] == 2


def test_reach_prints_field_names_never_text(capsys):
    payload = {"status": "success", "count": 3, "items": ITEMS}
    with patch.object(probe, "MIN_INTERVAL_S", 0), \
         patch("urllib.request.urlopen", return_value=_Resp(json.dumps(payload).encode())):
        assert probe.main(["reach"]) == 0
    out = capsys.readouterr().out
    assert "reachable: yes" in out and "count: 3" in out and "texto" in out
    assert "DEFERIU" not in out and "cobrança" not in out


def test_blocked_runner_fails_loudly(capsys):
    err = urllib.error.HTTPError(probe.BASE, 403, "Forbidden", {}, io.BytesIO(b"blocked from your country"))
    with patch.object(probe, "MIN_INTERVAL_S", 0), patch("urllib.request.urlopen", side_effect=err):
        assert probe.main(["reach"]) == 1
    assert "HTTP 403" in capsys.readouterr().err


def test_reply_without_items_raises():
    with pytest.raises(probe.ProbeError):
        probe.items_of({"message": "x"})


def test_proxy_list_keeps_scheme_host_port_lines_only():
    text = "http://1.2.3.4:3128\r\nsocks5://5.6.7.8:1080\n\nhttp://1.2.3.4:3128\n<html>\nftp://9.9.9.9:21\n"
    assert probe.parse_proxy_list(text) == ["http://1.2.3.4:3128", "socks5://5.6.7.8:1080"]


def test_proxies_mode_fails_when_none_answers(monkeypatch):
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(b"http://1.2.3.4:3128\n"))
    monkeypatch.setattr(probe, "try_proxy", lambda p, timeout=15: "000")
    assert probe.main(["proxies", "--lists", "https://example.test/l.txt", "--rounds", "2", "--pause", "0"]) == 1


def test_proxies_mode_keeps_only_proxies_that_answer_every_round(monkeypatch, capsys):
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(b"http://1.1.1.1:80\nhttp://2.2.2.2:80\n"))
    calls = {"http://1.1.1.1:80": iter(["200", "200"]), "http://2.2.2.2:80": iter(["200", "403"])}
    monkeypatch.setattr(probe, "try_proxy", lambda p, timeout=15: next(calls[p]))
    assert probe.main(["proxies", "--lists", "https://example.test/l.txt", "--rounds", "2", "--pause", "0"]) == 0
    out = capsys.readouterr().out
    assert "1 of 2" in out and "ok http://1.1.1.1:80" in out and "2.2.2.2" not in out.split("all 2 rounds")[1]
