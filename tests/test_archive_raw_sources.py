"""scripts/archive_raw_sources.py keeps each CVM file version once, by content (#982).

Contract pinned here:
  a file not in the bucket          -> put-object under <prefix>/<url path>/<sha256>
  the same bytes again              -> head-object finds it, nothing uploaded
  a changed file at the same URL    -> a second object (new sha), the old one stays
  head-object fails other than 404  -> recorded as an error, exit 1, other files still tried
  a .meta without its .cache        -> recorded as an error, exit 1
"""

import hashlib
import json
import subprocess

import pytest

from scripts import archive_raw_sources as arc

URL = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_202610.zip"


def _cache(tmp_path, name, url, body: bytes):
    (tmp_path / f"{name}.cache").write_bytes(body)
    (tmp_path / f"{name}.meta").write_text(json.dumps(
        {"timestamp": "2026-10-18T06:10:00+00:00", "url": url, "size": len(body)}
    ))


class FakeBucket:
    def __init__(self, held=(), head_error=None):
        self.held = set(held)
        self.head_error = head_error
        self.puts = []

    def __call__(self, cmd):
        key = cmd[cmd.index("--key") + 1]
        if "head-object" in cmd:
            if self.head_error:
                return subprocess.CompletedProcess(cmd, 255, "", self.head_error)
            if key in self.held:
                return subprocess.CompletedProcess(cmd, 0, "{}", "")
            return subprocess.CompletedProcess(
                cmd, 254, "", "An error occurred (404) when calling the HeadObject operation: Not Found")
        assert "put-object" in cmd
        self.puts.append((key, cmd[cmd.index("--metadata") + 1]))
        self.held.add(key)
        return subprocess.CompletedProcess(cmd, 0, "{}", "")


def _key(body: bytes) -> str:
    return "raw/cvm/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_202610.zip/" + hashlib.sha256(body).hexdigest()


def test_a_new_file_is_uploaded_under_its_url_path_and_sha(tmp_path):
    _cache(tmp_path, "a", URL, b"v1")
    bucket = FakeBucket()
    counts = arc.archive(str(tmp_path), "b", "https://r2", run=bucket)
    assert counts == {"uploaded": 1, "already_held": 0, "errors": []}
    (key, metadata), = bucket.puts
    assert key == _key(b"v1")
    assert f"source-url={URL}" in metadata and "fetched-at=2026-10-18T06:10:00+00:00" in metadata


def test_the_same_bytes_are_not_uploaded_again(tmp_path):
    _cache(tmp_path, "a", URL, b"v1")
    bucket = FakeBucket(held={_key(b"v1")})
    counts = arc.archive(str(tmp_path), "b", "https://r2", run=bucket)
    assert counts["uploaded"] == 0 and counts["already_held"] == 1 and bucket.puts == []


def test_a_corrected_file_becomes_a_second_version(tmp_path):
    _cache(tmp_path, "a", URL, b"v2")
    bucket = FakeBucket(held={_key(b"v1")})
    arc.archive(str(tmp_path), "b", "https://r2", run=bucket)
    assert bucket.held == {_key(b"v1"), _key(b"v2")}


def test_a_head_failure_is_an_error_and_other_files_still_run(tmp_path):
    _cache(tmp_path, "a", URL, b"v1")
    _cache(tmp_path, "b", URL.replace("202610", "202609"), b"v0")
    bucket = FakeBucket(head_error="An error occurred (403) when calling the HeadObject operation: Forbidden")
    counts = arc.archive(str(tmp_path), "b", "https://r2", run=bucket)
    assert len(counts["errors"]) == 2 and counts["uploaded"] == 0


def test_a_meta_without_its_cache_file_is_an_error(tmp_path):
    (tmp_path / "x.meta").write_text(json.dumps({"timestamp": "t", "url": URL}))
    counts = arc.archive(str(tmp_path), "b", "https://r2", run=FakeBucket())
    assert len(counts["errors"]) == 1


def test_main_exits_1_on_any_error(tmp_path, monkeypatch):
    (tmp_path / "x.meta").write_text(json.dumps({"timestamp": "t", "url": URL}))
    monkeypatch.setattr(arc, "_run", FakeBucket())
    assert arc.main(["--cache-dir", str(tmp_path), "--bucket", "b", "--endpoint", "https://r2"]) == 1


def test_an_empty_cache_is_a_clean_no_op(tmp_path):
    assert arc.archive(str(tmp_path), "b", "https://r2", run=FakeBucket()) == {
        "uploaded": 0, "already_held": 0, "errors": []}


def test_a_url_without_a_path_is_refused():
    with pytest.raises(ValueError):
        arc.object_key("raw/cvm", "https://dados.cvm.gov.br", "abc")


def test_the_daily_step_is_gated_loud_and_after_the_publish_steps():
    yaml = pytest.importorskip("yaml")
    from pathlib import Path
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/daily_ingest.yml").read_text())
    names = [s["name"] for s in wf["jobs"]["ingest"]["steps"]]
    step = wf["jobs"]["ingest"]["steps"][names.index("Archive downloaded CVM files (R2)")]
    assert "vars.RAW_ARCHIVE_ENABLED == '1'" in step["if"]
    assert "continue-on-error" not in step
    assert names.index("Archive downloaded CVM files (R2)") > names.index("Trigger dashboard rebuild (Vercel deploy hook)")
    assert "scripts/archive_raw_sources.py" in step["run"]
