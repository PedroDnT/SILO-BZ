"""Conditional download (#874): a CVM file unchanged since its last ok load is skipped.

Offline: aiohttp and the database are faked. What is pinned:

* the fetcher sends the stored validator and turns a 304 into ``SourceUnchanged``;
* it records the validator of what it downloaded, also from the on-disk cache;
* the ingestor skips only in the daily run, only for the listed slices, and
  writes one ``skipped`` audit row whose reason starts with ``unchanged:``;
* a validator is stored only after an ``ok`` slice with rows, never after a
  failure, so a skip cannot hide a failed slice;
* ``check_staleness`` reads the unchanged skip as fresh.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.fetchers import conditional
from src.fetchers.conditional import SliceSources, SourceUnchanged, Validator
from src.fetchers.cvm_fetcher import CVMFetcher
from src.pipeline import cvm_pipeline
from src.pipeline.cvm_pipeline import CVMIngestor, CVMSliceError, _classify_finish

URL = "https://dados.cvm.gov.br/dados/FI/DOC/CDA/DADOS/cda_fi_202609.zip"
V1 = Validator('"6ad2f27d-c6bdc3"', "Sat, 17 Oct 2026 03:58:53 GMT", 13024707)


class _Response:
    def __init__(self, status, headers=None, body=b"zip"):
        self.status, self.headers, self._body = status, headers or {}, body

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, response):
        self.response, self.requests = response, []

    def get(self, url, headers=None):
        self.requests.append(headers)
        return self.response

    async def close(self):
        return None


@pytest.fixture
def fetcher(tmp_path, monkeypatch):
    f = CVMFetcher()
    f.cache_dir = str(tmp_path)
    f.max_retries = 1
    CVMFetcher.reset_circuit()
    return f


@contextmanager
def _serving(fetcher, response):
    session = _Session(response)

    async def build(timeout, rotation):
        return session

    with patch.object(fetcher, "_build_session", build):
        yield session


def _download(fetcher, url=URL):
    cache, meta = fetcher._cache_paths(url)
    return asyncio.run(fetcher._download_uncached(url, cache, meta))


# --------------------------------------------------------------------- fetcher
def test_stored_validator_is_sent_and_304_raises_unchanged(fetcher):
    token = conditional.current.set(SliceSources(stored={URL: V1}))
    try:
        with _serving(fetcher, _Response(304)) as session:
            with pytest.raises(SourceUnchanged) as err:
                _download(fetcher)
    finally:
        conditional.current.reset(token)
    assert session.requests == [{
        "If-None-Match": V1.etag, "If-Modified-Since": V1.last_modified,
    }]
    assert str(err.value).startswith(conditional.UNCHANGED_PREFIX)
    assert "13024707 bytes not downloaded" in str(err.value)


def test_no_conditional_request_without_a_slice_or_a_stored_validator(fetcher):
    with _serving(fetcher, _Response(200, {"ETag": '"a"'})) as session:
        _download(fetcher)
    assert session.requests == [None]


def test_a_304_nobody_asked_for_is_an_error_not_a_skip(fetcher):
    with _serving(fetcher, _Response(304)):
        with pytest.raises(RuntimeError, match="HTTP 304"):
            _download(fetcher)


def test_download_records_the_validator_and_the_cache_repeats_it(fetcher):
    sources = SliceSources()
    token = conditional.current.set(sources)
    try:
        headers = {"ETag": V1.etag, "Last-Modified": V1.last_modified, "Content-Length": "13024707"}
        with _serving(fetcher, _Response(200, headers)):
            _download(fetcher)
        assert sources.seen == {URL: V1}
        sources.seen.clear()
        # Same run, another slice of the same ZIP: served from disk, same validator.
        asyncio.run(fetcher._download(URL))
        assert sources.seen == {URL: V1}
    finally:
        conditional.current.reset(token)


def test_a_response_without_validators_records_nothing(fetcher):
    sources = SliceSources()
    token = conditional.current.set(sources)
    try:
        with _serving(fetcher, _Response(200, {})):
            _download(fetcher)
    finally:
        conditional.current.reset(token)
    assert sources.seen == {}


def test_a_slice_that_loaded_two_files_is_never_conditional():
    sources = SliceSources(stored={URL: V1, URL + "2": V1})
    assert sources.validator_for(URL) is None
    assert SliceSources(stored={URL: V1}).validator_for(URL) == V1


# -------------------------------------------------------------------- ingestor
class _Cursor:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return None


class _Client:
    def __init__(self, stored=()):
        self.cur = _Cursor(list(stored))

    def cursor(self):
        return self.cur


def _ingestor(stored=(), daily=True):
    ing = CVMIngestor.__new__(CVMIngestor)
    ing._supabase = _Client(stored)
    ing._conditional_fetch = daily
    ing.finished = []
    ing._log_start = lambda *a, **k: None
    ing._write_finish = lambda run_id, rows, status, error, deleted: ing.finished.append(
        (status, rows, error)
    )
    return ing


STORED = [(URL, V1.etag, V1.last_modified, V1.content_length)]


def _run(ing, work, entity="fi", doc_type="cda", year=2026, month=9):
    with patch.object(cvm_pipeline, "upsert_rows") as upsert:
        try:
            rows = asyncio.run(ing._audited(entity, doc_type, year, month, work))
        except CVMSliceError:
            rows = "error"
    return rows, upsert


def test_unchanged_file_is_one_skipped_row_and_stores_nothing():
    ing = _ingestor(STORED)

    async def work():
        assert conditional.current.get().validator_for(URL) == V1
        raise SourceUnchanged(URL, V1)

    rows, upsert = _run(ing, work)
    assert rows == 0
    assert len(ing.finished) == 1
    status, _, reason = ing.finished[0]
    assert status == "skipped" and reason.startswith(conditional.UNCHANGED_PREFIX)
    assert ing.failures == []
    assert any("unchanged:" in s for s in ing.skips)
    upsert.assert_not_called()
    assert conditional.current.get() is None


def test_ok_slice_stores_what_it_saw_and_a_failed_one_stores_nothing():
    async def ok():
        conditional.current.get().seen[URL] = V1
        return 10, 10

    ing = _ingestor()
    rows, upsert = _run(ing, ok)
    assert rows == 10 and ing.finished[0][0] == "ok"
    (_, table, written), kwargs = upsert.call_args
    assert table == "cvm_source_validator"
    assert written[0]["url"] == URL and written[0]["etag"] == V1.etag
    assert (written[0]["period_year"], written[0]["period_month"]) == (2026, 9)

    async def broken():
        conditional.current.get().seen[URL] = V1
        raise RuntimeError("parse failed")

    ing = _ingestor(STORED)
    rows, upsert = _run(ing, broken)
    assert rows == "error" and ing.finished[0][0] == "error"
    upsert.assert_not_called()


def test_an_ok_slice_with_no_rows_stores_nothing():
    async def empty():
        conditional.current.get().seen[URL] = V1
        return 0, 0

    ing = _ingestor()
    _, upsert = _run(ing, empty)
    assert ing.finished[0][0] == "ok"
    upsert.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"daily": False},                       # a backfill re-reads on purpose
    {"entity": "fi", "doc_type": "perfil_mensal"},  # not a listed slice
    {"entity": "cia_aberta", "doc_type": "itr"},    # the incremental reader
])
def test_other_runs_and_slices_never_look_up_or_skip(kwargs):
    ing = _ingestor(STORED, daily=kwargs.pop("daily", True))

    async def work():
        assert conditional.current.get() is None
        return 5, 5

    rows, upsert = _run(ing, work, **kwargs)
    assert rows == 5
    assert not [q for q, _ in ing._supabase.cur.sql if "cvm_source_validator" in q]
    upsert.assert_not_called()


def test_the_kill_switch_turns_every_skip_off(monkeypatch):
    monkeypatch.setenv("CVM_CONDITIONAL_DOWNLOAD", "0")
    ing = _ingestor(STORED)

    async def work():
        assert conditional.current.get() is None
        return 5, 5

    assert _run(ing, work)[0] == 5


def test_failed_validator_lookup_downloads_in_full():
    ing = _ingestor(STORED)

    def boom(*a, **k):
        raise RuntimeError("db down")

    ing._supabase.cur.execute = boom

    async def work():
        assert conditional.current.get().stored == {}
        return 5, 5

    assert _run(ing, work)[0] == 5


def test_the_lookup_is_scoped_to_the_slice_the_parser_and_the_age():
    ing = _ingestor(STORED)

    async def work():
        return 1, 1

    _run(ing, work)
    sql, params = ing._supabase.cur.sql[0]
    assert "parser_version IS NOT DISTINCT FROM" in sql and "verified_at >" in sql
    assert params[:4] == ("fi", "cda", 2026, 9)
    assert params[-1] == conditional.max_age_days() == 7


def test_classifier_reads_the_unchanged_prefix_as_skipped():
    assert _classify_finish(f"{conditional.UNCHANGED_PREFIX} x", None, 0)[0] == "skipped"
    assert _classify_finish("unchanged ... but not a prefix", None, 0)[0] == "error"


# ----------------------------------------------------------- check_staleness
def test_staleness_counts_an_unchanged_skip_as_fresh_and_a_plain_skip_as_not():
    import scripts.check_staleness as cs

    seen = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            seen.append((sql, params))

        def fetchone(self):
            return (None,)

    class Conn:
        def cursor(self):
            return Cur()

    assert cs.last_success_age_hours(Conn(), "fi", "cda") is None
    sql, params = seen[0]
    assert "status = 'ok' OR (status = 'skipped' AND error_msg LIKE %s)" in sql
    assert params == ("fi", "cda", conditional.UNCHANGED_PREFIX + "%")
