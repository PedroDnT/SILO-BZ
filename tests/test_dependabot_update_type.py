"""The Dependabot auto-merge gate reads a title and never guesses."""

import pytest

from scripts.dependabot_update_type import classify


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Bump aiohttp from 3.14.3 to 3.14.4", "patch"),
        ("Bump dnspython from 2.8.0 to 2.9.0", "minor"),
        ("Bump polars from 1.44.2 to 2.0.0", "major"),
        ("Update pypdf requirement from >=4.0 to >=6.20.0", "major"),
        ("Update pypdf requirement from >=6.1 to >=6.2.3", "minor"),
        ("Bump actions/checkout from v7.0.0 to v7.0.1", "patch"),
        ("Bump foo from 0.4.1 to 0.5.0", "major"),
        ("Bump foo from 0.4.1 to 0.4.2", "patch"),
        ("Bump foo from 1.2 to 1.2.1", "patch"),
    ],
)
def test_classify(title, expected):
    assert classify(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "Bump the pip group with 3 updates",
        "Bump actions/checkout from 3d3c42e to 9a1b2c3",
        "Bump foo from 2.0.0 to 1.9.0",
        "Bump foo from 1.0.0rc1 to 1.0.0",
        "Fix a bug in aiohttp from 3.14.3 to 3.14.4",
        "",
    ],
)
def test_unreadable_titles_are_unknown(title):
    assert classify(title) == "unknown"
