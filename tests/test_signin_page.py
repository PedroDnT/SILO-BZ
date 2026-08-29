"""The sign-in page is the only front door to the authenticated tier.

It is a static file served straight to browsers, so nothing else in the repo
validates it — no build step compiles it, no linter reads it. These tests hold
the handful of properties that would silently break it.

Why it lives in dashboard/static/: the Evidence CLI copies './static/' verbatim
into the SvelteKit template (node_modules/@evidence-dev/evidence/cli.js, the
sourceRelative './static/' entry), which lands it in dashboard/build/ — the
directory vercel.json publishes. Verified against the installed package.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "dashboard" / "static" / "signin.html"
SKILL = ROOT / "skill.md"


@pytest.fixture(scope="module")
def html() -> str:
    assert PAGE.exists(), (
        "dashboard/static/signin.html is the authenticated tier's only front door; "
        "without it, enabling the OAuth providers gives nobody a way to sign in"
    )
    return PAGE.read_text(encoding="utf-8")


def test_page_is_served_from_the_evidence_static_directory():
    # Evidence only copies ./static/ — a page one directory over is never built.
    assert PAGE.parent.name == "static"
    assert PAGE.parent.parent.name == "dashboard"


def test_publishable_key_matches_the_one_source_of_truth(html: str):
    """The page must authenticate with the key the docs actually publish.

    The key appears in skill.md, throughout api-docs/, and inside api.catalog().
    A rotation that misses this file would leave the sign-in page talking to a
    dead credential — and the failure would look like "OAuth is broken" rather
    than "the key changed", which is a bad afternoon.
    """
    published = re.findall(r"sb_publishable_[A-Za-z0-9_]+", SKILL.read_text(encoding="utf-8"))
    assert published, "skill.md no longer contains a publishable key"
    in_page = set(re.findall(r"sb_publishable_[A-Za-z0-9_]+", html))
    assert in_page == {published[0]}, (
        f"signin.html embeds {in_page or 'no key'} but skill.md publishes {published[0]}"
    )


def test_no_secret_key_is_ever_embedded(html: str):
    """A publishable key in a static page is fine. A secret one is a breach."""
    for forbidden in ("sb_secret_", "service_role", "SUPABASE_SERVICE", "eyJhbGciOi"):
        assert forbidden not in html, f"{forbidden!r} must never appear in a browser-served page"


def test_both_providers_are_wired(html: str):
    assert "signInWithOAuth" in html
    for provider in ("github", "google"):
        assert f'signIn("{provider}")' in html, f"{provider} sign-in is not wired to a button"


def test_auth_library_is_pinned_to_an_exact_version(html: str):
    """A floating major would let a breaking release land on users unannounced.

    This page cannot be smoke-tested by CI (it needs a browser and a real OAuth
    round-trip), so the dependency has to be boring.
    """
    m = re.search(r"@supabase/supabase-js@(\d+\.\d+\.\d+)/", html)
    assert m, "supabase-js must be loaded from an exactly pinned version"
    assert "supabase-js@2/" not in html, "a bare major pin is not a pin"


def test_the_expiry_is_stated_not_buried(html: str):
    """The token dies in ~1h and the failure mode is genuinely confusing.

    An expired token does not produce an auth error — the caller silently drops
    to the anonymous tier and a 4-id panel starts raising 22023. The page has to
    say so, because nothing else will.
    """
    assert "expires" in html.lower()
    assert "22023" in html, "the page must name the symptom an expired token produces"
    assert "renderExpiry" in html, "there must be a live countdown, not just prose"


def test_rows_per_response_is_not_advertised_as_a_tier_benefit(html: str):
    """db-max-rows is server-wide; claiming otherwise would be a lie on the page.

    Signing in raises ids, page sizes and the timeout — never rows per response.
    """
    assert re.search(r"Rows per response.*?1000.*?1000", html, re.S), (
        "the tier table must show 1000 rows for BOTH tiers"
    )


def test_tier_numbers_match_the_contract(html: str):
    """These are the ceilings enforced by api.assert_panel_ids and the clamps."""
    for value in ("3", "50", "25", "200", "2000"):
        assert f">{value}<" in html, f"tier limit {value} is missing from the page's table"


def test_redirect_target_is_stable(html: str):
    """redirectTo must be origin+pathname, with no query or hash carried over.

    Supabase matches redirects against an allow-list; a URL carrying a stale
    ?error= or #access_token= from a previous attempt will not match, and the
    user gets an opaque failure on their second try.
    """
    assert "window.location.origin + window.location.pathname" in html
