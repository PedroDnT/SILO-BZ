"""Apify-backed ETF market fetcher — scrapes etfsbrasil.com.br/etfs/<ticker>.

Why this exists
---------------
CVM open data does not expose ETF NAV / quotaholders for post-CVM-175 share
classes (etf_daily is empty — the registry's fund-level CNPJ no longer matches
the class-level CNPJ in cvm_fi_diario). etfsbrasil.com.br carries the per-ETF NAV,
number of cotistas, returns, fees and index, but renders NAV/cotistas via JS and
rate-limits direct scraping — so we drive a headless-browser Apify actor with
rotating RESIDENTIAL proxies.

Default actor is ``apify/playwright-scraper`` (limited permissions). The older
default ``apify/web-scraper`` was upgraded to full permissions on 2026-08-31;
until an operator approves it in Console, the API returns HTTP 403
``full-permission-actor-not-approved``. That error is raised as
``ApifyActorNotApprovedError`` so the daily run can skip the scrape the same
way it skips an unset ``APIFY_TOKEN`` — the scrape never started, so there is
no data to fabricate or to fail the rest of ingest over.

Public surface
--------------
    ApifyETFFetcher().fetch(tickers) -> list[dict]   # one scraped record per ticker

The actor's pageFunction lives in apify/etfsbrasil_scraper.js (read at call time
and passed in the run input), so there is nothing to pre-deploy on Apify — only an
API token is required.

Configuration (env)
-------------------
    APIFY_TOKEN                required — Apify API token.
    APIFY_ETF_ACTOR            optional — actor id (default 'apify~playwright-scraper').
    APIFY_PROXY_GROUPS         optional — comma list (default 'RESIDENTIAL').
    APIFY_ETF_CONCURRENCY      optional — actor maxConcurrency (default 5).
    APIFY_ETF_RUN_BUDGET_SECS  optional — whole-run wall clock (default 1500).

How the run is driven
---------------------
Asynchronously: POST /acts/{actor}/runs, then GET /actor-runs/{id} with
``waitForFinish=60`` until a terminal status, then GET the run's dataset items.
Apify's synchronous ``run-sync-get-dataset-items`` holds a request for at most
300 seconds and then answers HTTP 408 ``run-timeout-exceeded``; the 2026-09-03
daily (run 33721538761) died on exactly that once the scrape moved to a full
browser per page. The cap is Apify's, not a knob, so the sync path is gone.

Data-integrity: a failed run (non-2xx, a run ending FAILED/TIMED-OUT/ABORTED,
a run outliving its budget, or an empty dataset) RAISES — it never returns a
plausible-looking empty/fallback result. Parsing/validation and the DB upsert
live in src/pipeline/ingest_etf_market.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ETF_URL = "https://www.etfsbrasil.com.br/etfs/{ticker}"
_PAGE_FUNCTION_PATH = Path(__file__).resolve().parents[2] / "apify" / "etfsbrasil_scraper.js"
_APIFY_BASE = "https://api.apify.com/v2"
_DEFAULT_ACTOR = "apify~playwright-scraper"
_APPROVAL_ERROR_TYPE = "full-permission-actor-not-approved"

# Apify's run-status vocabulary (OpenAPI: READY, RUNNING, SUCCEEDED, FAILED,
# TIMING-OUT, TIMED-OUT, ABORTING, ABORTED). Only these four end a run; the
# poller keeps waiting through the transitional ones.
_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"})
# GET /actor-runs/{id}?waitForFinish=N holds the request open up to N seconds
# (server maximum 60), which turns polling into one request per minute.
_WAIT_FOR_FINISH_SECS = 60
# Slack past the run budget before the poller gives up: Apify enforces the
# `timeout` we pass when starting the run, so this only covers the last
# long-poll straddling the deadline.
_BUDGET_GRACE_SECS = 90
# Wall-clock allowance for one scrape. The 2026-09-03 run needed more than the
# 300 s the synchronous endpoint allows; 25 minutes is generous for ~200 pages
# and still short enough that a stuck run cannot eat the whole daily job.
_DEFAULT_RUN_BUDGET_SECS = 1500


class ApifyActorNotApprovedError(RuntimeError):
    """The Apify store actor needs a one-time Console permission grant.

    Distinct from a scrape that ran and returned bad data: the actor never
    started. Same class of unavailability as an unset APIFY_TOKEN.
    """


class ApifyETFFetcher:
    """Runs the etfsbrasil scraper on Apify and returns the dataset items."""

    def __init__(
        self,
        token: Optional[str] = None,
        actor: Optional[str] = None,
        timeout_secs: int = 600,
        run_budget_secs: Optional[int] = None,
    ) -> None:
        self._token = token or os.getenv("APIFY_TOKEN")
        if not self._token:
            raise RuntimeError(
                "APIFY_TOKEN is not set — required to run the etfsbrasil ETF scraper"
            )
        # Apify actor ids use '~' between owner and name in the REST path.
        self._actor = actor or os.getenv("APIFY_ETF_ACTOR", _DEFAULT_ACTOR)
        # Per-request HTTP timeout. Each long-poll holds for up to 60 s, so
        # this must stay comfortably above _WAIT_FOR_FINISH_SECS.
        self._timeout = timeout_secs
        # Whole-run wall clock, passed to Apify as the run's own `timeout` and
        # enforced again by the poller.
        self._run_budget = int(
            run_budget_secs
            if run_budget_secs is not None
            else os.getenv("APIFY_ETF_RUN_BUDGET_SECS", str(_DEFAULT_RUN_BUDGET_SECS))
        )
        self._proxy_groups = [
            g.strip()
            for g in os.getenv("APIFY_PROXY_GROUPS", "RESIDENTIAL").split(",")
            if g.strip()
        ]
        self._page_function = _PAGE_FUNCTION_PATH.read_text(encoding="utf-8")

    def _uses_playwright(self) -> bool:
        return "playwright" in self._actor.lower()

    def _build_input(self, tickers: List[str]) -> Dict[str, Any]:
        start_urls = [
            {"url": _ETF_URL.format(ticker=t.strip().lower())}
            for t in tickers
            if t and t.strip()
        ]
        if not start_urls:
            raise ValueError("ApifyETFFetcher.fetch called with no tickers")
        payload: Dict[str, Any] = {
            "startUrls": start_urls,
            "pageFunction": self._page_function,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": self._proxy_groups,
            },
            "maxConcurrency": int(os.getenv("APIFY_ETF_CONCURRENCY", "5")),
            "maxRequestRetries": 3,
            "pageLoadTimeoutSecs": 60,
            # Start URLs only — do not enqueue the rest of etfsbrasil.com.br.
            "linkSelector": "",
        }
        if self._uses_playwright():
            # Playwright enum is a string; Puppeteer web-scraper wants a list.
            payload["waitUntil"] = "networkidle"
            payload["pageFunctionTimeoutSecs"] = 90
        else:
            payload["waitUntil"] = ["networkidle2"]
            payload["injectJQuery"] = False
        return payload

    # ------------------------------------------------------------------
    # HTTP plumbing. One place maps transport failures to exceptions so the
    # three calls below cannot drift into three different error shapes.
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        query: Dict[str, Any],
        body: Optional[Dict[str, Any]] = None,
        *,
        run_id: Optional[str] = None,
    ) -> Any:
        params = {"token": self._token, **query}
        url = f"{_APIFY_BASE}{path}?{urllib.parse.urlencode(params)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            if run_id:
                detail = f"run {run_id}: {detail}"
            raise apify_http_error(self._actor, exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Apify run failed (network): {exc}") from exc
        return json.loads(payload) if payload else None

    def _start_run(self, run_input: Dict[str, Any]) -> Dict[str, Any]:
        """POST the run and return Apify's Run object (status READY/RUNNING)."""
        resp = self._request(
            "POST",
            f"/acts/{self._actor}/runs",
            # Apify kills the run itself at this many seconds, so a runaway
            # scrape is capped on their side too, not only by our poller.
            {"timeout": self._run_budget},
            body=run_input,
        )
        run = resp.get("data") if isinstance(resp, dict) else None
        if not isinstance(run, dict) or not run.get("id"):
            raise RuntimeError(
                "Apify did not return a run object when starting the etfsbrasil "
                f"scrape — refusing to guess a run id (got {str(resp)[:200]!r})"
            )
        logger.info("etfsbrasil scrape started: Apify run %s (%s)",
                    run["id"], run.get("status"))
        return run

    def _wait_for_run(self, run_id: str) -> Dict[str, Any]:
        """Long-poll until the run reaches a terminal status or the budget is spent.

        `waitForFinish` makes Apify hold each request open for up to 60 s, so
        this is one request per minute, not a tight loop. The budget is wall
        clock from the first poll; on exhaustion the run is aborted (best
        effort — a paid run must not be left burning) and the caller gets a
        RuntimeError naming the run so it can be inspected in the Console.
        """
        deadline = time.monotonic() + self._run_budget + _BUDGET_GRACE_SECS
        run: Dict[str, Any] = {"id": run_id, "status": "UNKNOWN"}
        while True:
            resp = self._request(
                "GET", f"/actor-runs/{run_id}",
                {"waitForFinish": _WAIT_FOR_FINISH_SECS}, run_id=run_id,
            )
            run = (resp or {}).get("data") or run
            status = run.get("status")
            if status in _TERMINAL_STATUSES:
                return run
            if time.monotonic() >= deadline:
                self._abort_run(run_id)
                raise RuntimeError(
                    f"Apify run {run_id} for the etfsbrasil scrape did not finish "
                    f"within {self._run_budget}s (last status {status}); aborted. "
                    f"Inspect it at https://console.apify.com/actors/runs/{run_id}"
                )
            logger.info("etfsbrasil scrape: run %s still %s", run_id, status)

    def _abort_run(self, run_id: str) -> None:
        try:
            self._request("POST", f"/actor-runs/{run_id}/abort", {}, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 — cleanup after a failure already being raised
            logger.warning("could not abort Apify run %s: %s", run_id, exc)

    def _dataset_items(self, run_id: str) -> Any:
        return self._request(
            "GET", f"/actor-runs/{run_id}/dataset/items",
            {"format": "json", "clean": "true"}, run_id=run_id,
        )

    def fetch(self, tickers: List[str]) -> List[Dict[str, Any]]:
        """Run the scraper and return one record per scraped ticker.

        Asynchronous on purpose. The earlier implementation used Apify's
        `run-sync-get-dataset-items`, whose documented behaviour is to hold the
        request for at most 300 seconds and then return HTTP 408
        `run-timeout-exceeded`. Daily CVM Ingest 33721538761 (2026-09-03) hit
        exactly that: ~187 tickers through a full browser over residential
        proxies at concurrency 5 needs longer than five minutes, and the cap
        is on Apify's side, not ours. So: start the run, long-poll it, read
        its dataset — no endpoint in that path has a fixed ceiling.

        Raises on any transport error, non-2xx status, a run that ends in any
        status but SUCCEEDED, a run that outlives the budget, or an empty
        dataset — a failed scrape must surface, never masquerade as "no ETFs".
        """
        run_input = self._build_input(tickers)
        run = self._start_run(run_input)
        run_id = run["id"]
        run = self._wait_for_run(run_id)

        status = run.get("status")
        if status != "SUCCEEDED":
            raise RuntimeError(
                f"Apify run {run_id} for the etfsbrasil scrape ended {status}"
                f" (exit code {run.get('exitCode')}): "
                f"{run.get('statusMessage') or 'no status message'}"
            )

        items = self._dataset_items(run_id)
        if not isinstance(items, list) or not items:
            raise RuntimeError(
                f"Apify run {run_id} succeeded but its dataset is empty — refusing "
                "to treat as success (check proxy blocks or the page function)"
            )
        logger.info("etfsbrasil scrape: %d ETF records for %d tickers (run %s)",
                    len(items), len(tickers), run_id)
        return items


def apify_http_error(actor: str, code: int, detail: str) -> RuntimeError:
    """Map an Apify HTTP error body to the exception the daily run should see."""
    approval_url = _approval_url(detail)
    if code == 403 and (
        _APPROVAL_ERROR_TYPE in detail or approval_url is not None
    ):
        where = approval_url or (
            f"https://console.apify.com/actors/{actor.replace('~', '/')}?approvePermissions=true"
        )
        return ApifyActorNotApprovedError(
            f"Apify actor {actor} requires a one-time Console permission "
            f"approval before it can run. Approve at {where} — until then "
            f"the scrape cannot start (HTTP {code})."
        )
    return RuntimeError(
        f"Apify run failed for etfsbrasil scrape: HTTP {code} — {detail}"
    )


def _approval_url(detail: str) -> Optional[str]:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    err = payload.get("error") or {}
    if not isinstance(err, dict):
        return None
    if err.get("type") != _APPROVAL_ERROR_TYPE:
        return None
    data = err.get("data") or {}
    if not isinstance(data, dict):
        return None
    url = data.get("approvalUrl")
    return url if isinstance(url, str) and url else None
