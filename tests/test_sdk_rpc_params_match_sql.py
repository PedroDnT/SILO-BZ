"""Every key the SDK sends must be a parameter the SQL function declares.

THE BUG THIS EXISTS FOR. `SiloClient.option_exercises` sent `p_underlying`.
`api.option_exercises` declares `p_prefix`. PostgREST resolves an RPC by
argument names, so that call could never have succeeded — it would come back
404 "function not found" against a function that exists and is granted. Nothing
caught it: the offline suite mocks the transport, and the live smoke test never
exercised that method.

A wrong parameter name is invisible in every test that stops at the HTTP
boundary, and the two sides live in different languages in different
directories. This module joins them: parse the parameter list of each
`api.<name>(...)` out of the analytical contract, parse the body each
`self._rpc("<name>", {...})` sends out of the client, and require the second to
be a subset of the first.

Subset, not equality — a function may declare parameters the SDK chooses not to
expose, and defaulting them is the point of a default.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "src/store/analytical/19_api_contract.sql"
CLIENT = ROOT / "sdk/silo_client/client.py"


def _sql_params() -> dict[str, set[str]]:
    """{function name: {declared parameter names}} from the shipped contract."""
    text = SQL.read_text()
    out: dict[str, set[str]] = {}
    for m in re.finditer(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+api\.(\w+)\s*\((.*?)\)\s*\n\s*RETURNS",
        text, re.S | re.I,
    ):
        name, body = m.group(1), m.group(2)
        params = set(re.findall(r"\b(p_\w+)\s", body))
        # A later CREATE OR REPLACE of the same name is the shipped signature.
        out[name] = params
    return out


def _sdk_calls() -> list[tuple[str, set[str], int]]:
    """[(rpc name, {keys sent}, lineno)] for every literal self._rpc(...) call."""
    tree = ast.parse(CLIENT.read_text())
    calls: list[tuple[str, set[str], int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "_rpc"):
            continue
        if len(node.args) < 2:
            continue
        name_node, body_node = node.args[0], node.args[1]
        if not (isinstance(name_node, ast.Constant) and isinstance(name_node.value, str)):
            continue
        if not isinstance(body_node, ast.Dict):
            continue
        keys = {
            k.value for k in body_node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        calls.append((name_node.value, keys, node.lineno))
    return calls


def test_the_sdk_actually_makes_rpc_calls_we_can_see():
    """Guard the parser itself: an empty scan would make this module vacuous."""
    calls = _sdk_calls()
    assert len(calls) >= 10, f"only found {len(calls)} _rpc calls — the AST scan broke"
    assert _sql_params(), "no api.* functions parsed out of the contract"


@pytest.mark.parametrize("rpc,keys,lineno", _sdk_calls())
def test_every_key_the_sdk_sends_is_a_declared_parameter(rpc, keys, lineno):
    """PostgREST matches on argument NAMES, so a typo is a 404, not a warning."""
    declared = _sql_params()
    assert rpc in declared, (
        f"{CLIENT.name}:{lineno} calls api.{rpc}, which the contract does not define"
    )
    unknown = keys - declared[rpc]
    assert not unknown, (
        f"{CLIENT.name}:{lineno} sends {sorted(unknown)} to api.{rpc}, which declares "
        f"{sorted(declared[rpc])} — PostgREST resolves by argument name, so this call "
        "returns 404 against a function that exists"
    )


def test_option_exercises_sends_the_prefix_it_requires():
    """Named explicitly so the original defect cannot silently return."""
    calls = {name: keys for name, keys, _ in _sdk_calls()}
    assert "p_prefix" in calls["option_exercises"], (
        "api.option_exercises requires p_prefix (>= 3 chars) and raises 22023 "
        "without it; the SDK once sent p_underlying, which does not exist"
    )
    assert "p_underlying" not in calls["option_exercises"]
