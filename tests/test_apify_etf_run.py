"""The ETF scrape drives Apify asynchronously: start, long-poll, read the dataset.

THE RUN THIS EXISTS FOR. Daily CVM Ingest 33721538761 (2026-09-03 06:03Z)
ingested 3,186,158 rows and then failed on the one source it scrapes:

    Apify run failed for etfsbrasil scrape: HTTP 408 — {"error": {"type":
    "run-timeout-exceeded", "message": "Actor run exceeded the timeout of
    300 seconds for this API endpoint"}}

Not the 403 of the day before — the playwright-scraper actor is authorised and
ran. It simply needs more than the five minutes Apify's synchronous
`run-sync-get-dataset-items` will hold a request for, and that ceiling is
documented on their side, not tunable on ours. The failure then skipped
ANALYZE and the analytical refresh for the whole day.

These tests script the three-call conversation with a fake urlopen and assert
the properties that keep the scrape honest:

  * the run is STARTED, POLLED with waitForFinish, and its dataset READ — in
    that order, at those paths;
  * only SUCCEEDED yields data: FAILED / TIMED-OUT / ABORTED raise with the run
    id and Apify's status message, and the dataset is never fetched;
  * a run that outlives the budget is aborted and raised, never waited on
    forever;
  * an empty dataset from a SUCCEEDED run still raises;
  * the 403 permission mapping from #186 survives on the start call.
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any, Dict, List
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from src.fetchers.apify_etf_fetcher import (
    ApifyActorNotApprovedError,
    ApifyETFFetcher,
)

RUN_ID = "abc123RUN"


class _Resp:
    def __init__(self, payload: Any):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _run(status: str, **extra) -> Dict[str, Any]:
    return {"data": {"id": RUN_ID, "status": status, "defaultDatasetId": "ds1", **extra}}


class _Apify:
    """A scripted Apify: records every request, answers from a queue per path kind."""

    def __init__(self, poll_statuses: List[str], items: Any = None, start_status: str = "RUNNING"):
        self.calls: List[tuple] = []  # (method, path, query)
        self._polls = list(poll_statuses)
        self._items = [] if items is None else items
        self._start_status = start_status

    def __call__(self, req, timeout=None):
        url = urlparse(req.full_url)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        method = req.get_method()
        self.calls.append((method, url.path, query))
        if url.path.endswith("/runs") and method == "POST":
            return _Resp(_run(self._start_status))
        if url.path.endswith("/abort"):
            return _Resp(_run("ABORTING"))
        if url.path.endswith("/dataset/items"):
            return _Resp(self._items)
        if "/actor-runs/" in url.path:
            status = self._polls.pop(0) if self._polls else "RUNNING"
            return _Resp(_run(status, statusMessage=f"msg for {status}", exitCode=1 if status == "FAILED" else 0))
        raise AssertionError(f"unexpected request {method} {url.path}")


def _fetcher(**kw) -> ApifyETFFetcher:
    return ApifyETFFetcher(token="tok", run_budget_secs=kw.pop("budget", 1500), **kw)


class TestHappyPath:
    def test_start_poll_read_in_that_order(self):
        api = _Apify(poll_statuses=["RUNNING", "SUCCEEDED"], items=[{"ticker": "BOVA11"}])
        with patch("urllib.request.urlopen", api):
            items = _fetcher().fetch(["BOVA11"])
        assert items == [{"ticker": "BOVA11"}]
        paths = [(m, p) for m, p, _ in api.calls]
        assert paths == [
            ("POST", "/v2/acts/apify~playwright-scraper/runs"),
            ("GET", f"/v2/actor-runs/{RUN_ID}"),
            ("GET", f"/v2/actor-runs/{RUN_ID}"),
            ("GET", f"/v2/actor-runs/{RUN_ID}/dataset/items"),
        ]

    def test_start_carries_the_run_timeout_and_polls_long_poll(self):
        api = _Apify(poll_statuses=["SUCCEEDED"], items=[{"ticker": "IVVB11"}])
        with patch("urllib.request.urlopen", api):
            _fetcher(budget=900).fetch(["IVVB11"])
        start_q = api.calls[0][2]
        poll_q = api.calls[1][2]
        read_q = api.calls[2][2]
        assert start_q["timeout"] == "900", "Apify must cap the run on its side too"
        assert start_q["token"] == "tok"
        assert poll_q["waitForFinish"] == "60", "polling must be a long-poll, not a tight loop"
        assert read_q["format"] == "json" and read_q["clean"] == "true"

    def test_the_sync_endpoint_is_gone(self):
        api = _Apify(poll_statuses=["SUCCEEDED"], items=[{"x": 1}])
        with patch("urllib.request.urlopen", api):
            _fetcher().fetch(["BOVA11"])
        assert not any("run-sync" in p for _, p, _ in api.calls), (
            "run-sync-get-dataset-items holds for 300 s max and 408s past that; "
            "the scrape must not go back to it"
        )

    def test_never_polls_when_the_start_already_succeeded(self):
        """A tiny run can be SUCCEEDED by the time POST returns; one poll confirms and reads."""
        api = _Apify(poll_statuses=["SUCCEEDED"], items=[{"x": 1}], start_status="SUCCEEDED")
        with patch("urllib.request.urlopen", api):
            _fetcher().fetch(["BOVA11"])
        assert sum(1 for m, p, _ in api.calls if m == "GET" and p.endswith(RUN_ID)) == 1


class TestTerminalFailures:
    @pytest.mark.parametrize("status", ["FAILED", "TIMED-OUT", "ABORTED"])
    def test_non_success_raises_with_run_id_and_message(self, status):
        api = _Apify(poll_statuses=["RUNNING", status], items=[{"x": 1}])
        with patch("urllib.request.urlopen", api):
            with pytest.raises(RuntimeError) as exc:
                _fetcher().fetch(["BOVA11"])
        msg = str(exc.value)
        assert RUN_ID in msg and status in msg and f"msg for {status}" in msg
        assert not any(p.endswith("/dataset/items") for _, p, _ in api.calls), (
            "a failed run's dataset must never be read as if it were data"
        )

    def test_transitional_statuses_keep_polling(self):
        api = _Apify(poll_statuses=["READY", "RUNNING", "TIMING-OUT", "TIMED-OUT"])
        with patch("urllib.request.urlopen", api):
            with pytest.raises(RuntimeError, match="TIMED-OUT"):
                _fetcher().fetch(["BOVA11"])
        assert sum(1 for m, p, _ in api.calls if m == "GET" and p.endswith(RUN_ID)) == 4

    def test_empty_dataset_from_a_succeeded_run_raises(self):
        api = _Apify(poll_statuses=["SUCCEEDED"], items=[])
        with patch("urllib.request.urlopen", api):
            with pytest.raises(RuntimeError, match="dataset is empty"):
                _fetcher().fetch(["BOVA11"])

    def test_non_list_dataset_raises(self):
        api = _Apify(poll_statuses=["SUCCEEDED"], items={"error": "oops"})
        with patch("urllib.request.urlopen", api):
            with pytest.raises(RuntimeError, match="dataset is empty"):
                _fetcher().fetch(["BOVA11"])

    def test_start_without_a_run_object_raises_instead_of_guessing(self):
        class _Weird(_Apify):
            def __call__(self, req, timeout=None):
                return _Resp([])  # a list where a run object should be

        with patch("urllib.request.urlopen", _Weird(poll_statuses=[])):
            with pytest.raises(RuntimeError, match="refusing to guess a run id"):
                _fetcher().fetch(["BOVA11"])


class TestBudget:
    def test_a_run_that_outlives_the_budget_is_aborted_and_raised(self):
        api = _Apify(poll_statuses=["RUNNING"] * 50)
        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 100.0  # every call advances 100 s
            return clock["t"]

        with patch("urllib.request.urlopen", api), \
             patch("src.fetchers.apify_etf_fetcher.time.monotonic", fake_monotonic):
            with pytest.raises(RuntimeError) as exc:
                _fetcher(budget=300).fetch(["BOVA11"])
        msg = str(exc.value)
        assert "did not finish within 300s" in msg and RUN_ID in msg
        assert "console.apify.com" in msg, "the operator must be pointed at the run"
        assert any(p.endswith(f"/actor-runs/{RUN_ID}/abort") for _, p, _ in api.calls), (
            "a paid run past its budget must be aborted, not left burning"
        )
        assert not any(p.endswith("/dataset/items") for _, p, _ in api.calls)

    def test_abort_failure_does_not_mask_the_budget_error(self):
        class _AbortBreaks(_Apify):
            def __call__(self, req, timeout=None):
                if req.full_url.split("?")[0].endswith("/abort"):
                    raise HTTPError(req.full_url, 500, "boom", hdrs=None, fp=BytesIO(b"x"))
                return super().__call__(req, timeout)

        api = _AbortBreaks(poll_statuses=["RUNNING"] * 50)
        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 100.0
            return clock["t"]

        with patch("urllib.request.urlopen", api), \
             patch("src.fetchers.apify_etf_fetcher.time.monotonic", fake_monotonic):
            with pytest.raises(RuntimeError, match="did not finish within"):
                _fetcher(budget=300).fetch(["BOVA11"])

    def test_budget_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("APIFY_ETF_RUN_BUDGET_SECS", "777")
        assert ApifyETFFetcher(token="tok")._run_budget == 777

    def test_budget_default(self, monkeypatch):
        monkeypatch.delenv("APIFY_ETF_RUN_BUDGET_SECS", raising=False)
        assert ApifyETFFetcher(token="tok")._run_budget == 1500


class TestStartErrors:
    def test_permission_403_on_start_is_actor_not_approved(self):
        body = json.dumps({"error": {"type": "full-permission-actor-not-approved",
                                     "data": {"approvalUrl": "https://console.apify.com/actors/x?approvePermissions=true"}}})
        err = HTTPError("https://api.apify.com/v2/acts/x/runs", 403, "Forbidden",
                        hdrs=None, fp=BytesIO(body.encode()))
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ApifyActorNotApprovedError):
                _fetcher(actor="apify~web-scraper").fetch(["BOVA11"])

    def test_http_error_while_polling_names_the_run(self):
        class _PollBreaks(_Apify):
            def __call__(self, req, timeout=None):
                if "/actor-runs/" in req.full_url and req.get_method() == "GET":
                    raise HTTPError(req.full_url, 500, "boom", hdrs=None, fp=BytesIO(b"server error"))
                return super().__call__(req, timeout)

        with patch("urllib.request.urlopen", _PollBreaks(poll_statuses=[])):
            with pytest.raises(RuntimeError) as exc:
                _fetcher().fetch(["BOVA11"])
        assert "HTTP 500" in str(exc.value) and RUN_ID in str(exc.value)
