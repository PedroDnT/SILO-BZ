"""Every third-party module src/portfolio imports is installed in the engine image.

The image (deploy/cloudflare/engine/Dockerfile) installs only deploy/cloudflare/engine/requirements.txt,
not the repository's requirements.txt, so a new import passes the offline suite and still crashes the
Container at boot: engine 1.11 imported ``yaml`` and the image smoke failed with ModuleNotFoundError.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQS = ROOT / "deploy" / "cloudflare" / "engine" / "requirements.txt"

# Import name -> distribution name, where they differ.
DIST = {"yaml": "pyyaml"}
# Installed as a dependency of a listed distribution (flask brings werkzeug).
TRANSITIVE = {"werkzeug"}


def _imports() -> set[str]:
    out: set[str] = set()
    for path in (ROOT / "src" / "portfolio").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                out |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
    return out


def _requirements() -> set[str]:
    names = set()
    for line in REQS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(re.split(r"[<>=!~\[ ]", line, maxsplit=1)[0].lower())
    return names


def test_every_third_party_import_is_in_the_engine_image():
    third_party = {m for m in _imports() if m not in sys.stdlib_module_names and m != "src"}
    missing = sorted(m for m in third_party - TRANSITIVE if DIST.get(m, m).lower() not in _requirements())
    assert not missing, f"add to {REQS.relative_to(ROOT)}: {missing}"
