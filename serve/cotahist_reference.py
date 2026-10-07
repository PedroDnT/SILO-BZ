"""Dated COTAHIST reference, not a current or point-in-time taxonomy.

Descriptions paraphrase B3 layout revision 2.0 (2020-10-05). Unknown codes
remain valid source values; a dictionary entry is not evidence of observations.
"""
from __future__ import annotations

SOURCE_URL = "https://www.b3.com.br/data/files/33/67/B9/50/D84057102C784E47AC094EA8/SeriesHistoricas_Layout.pdf"
REFERENCE_DATE = "2020-10-05"

CODBDI = {
    "02": "Standard lot",
    "05": "Sanction status (2020 label; repo also uses it for fund subtype)",
    "06": "Legacy insolvency",
    "07": "Extrajudicial recovery",
    "08": "Judicial recovery",
    "09": "Special administration",
    "10": "Rights / receipts",
    "11": "Intervention",
    "12": "Real-estate funds",
    "14": "Investment certificates / public debt (legacy label)",
    "18": "Obligations",
    "22": "Private bonus instruments",
    "26": "Public debt instruments",
    "32": "Index call exercises",
    "33": "Index put exercises",
    "38": "Call exercises",
    "42": "Put exercises",
    "46": "Unquoted-security auctions",
    "48": "Privatization auctions",
    "49": "Espírito Santo recovery-fund auctions",
    "50": "Auctions",
    "51": "FINOR auctions",
    "52": "FINAM auctions",
    "53": "FISET auctions",
    "54": "Delinquent-share auctions",
    "56": "Court-authorized sales",
    "58": "Other",
    "60": "Share exchanges",
    "61": "META",
    "62": "Forwards",
    "66": "Debentures, maturity ≤3 years",
    "68": "Debentures, maturity >3 years",
    "70": "Retained-gain futures",
    "71": "Futures",
    "74": "Index calls",
    "75": "Index puts",
    "78": "Calls",
    "82": "Puts",
    "83": "BovespaFix",
    "84": "SomaFix",
    "90": "Registered spot-forward",
    "96": "Odd lots",
    "99": "General total"
}
OBSERVED_OUTSIDE_REFERENCE = ['13', '34', '35', '36', '92', '93']
TPMERC = {
    "010": "Spot", "012": "Call exercise", "013": "Put exercise",
    "017": "Auction", "020": "Odd lot", "030": "Forward",
    "050": "Retained-gain futures", "060": "Continuous-settlement futures",
    "070": "Call options", "080": "Put options",
}
INDOPC = {"1": "USD correction", "2": "TJLP correction", "8": "IGP-M correction", "9": "URV correction"}


def code_metadata(family: str, code: str) -> dict:
    """Describe only codes documented in the dated reference; never guess."""
    mapping = {"codbdi": CODBDI, "tpmerc": TPMERC, "indopc": INDOPC}[family]
    label = mapping.get(code)
    return {"code": code, "description": label,
            "status": "documented_in_reference" if label is not None else "unknown_in_reference"}


def cotahist_reference() -> dict:
    return {
        "source_url": SOURCE_URL,
        "reference_date": REFERENCE_DATE,
        "reference_version": "2.0",
        "description_language": "en",
        "description_basis": "Paraphrases of the dated layout; not certified current descriptions or historical validity intervals.",
        "unknown_codes": "Preserve source codes. Missing descriptions stay null; do not reject a row or infer a label.",
        "coverage": "Dictionary presence does not mean observations exist. Consult coverage() and the dated storage/serving audit.",
        "codbdi": {code: code_metadata("codbdi", code) for code in sorted(set(CODBDI) | set(OBSERVED_OUTSIDE_REFERENCE))},
        "tpmerc": {code: code_metadata("tpmerc", code) for code in sorted(set(TPMERC) | {"021"})},
        "indopc": {code: code_metadata("indopc", code) for code in sorted(set(INDOPC) | {"0"})},
        "especi": "Original text is spec; asset_class/fund_type are separate derived classifications. The dated CODBDI label is not an asset-class rule.",
        "record_type": "Only valid register-01 quotes are stored. TIPREG 99 trailer differs from CODBDI 99.",
        "natural_key": ["codneg", "trade_date", "tpmerc", "codbdi", "prazot"],
        "source_fields": {
            "trade_date": "Session date", "board": "CODBDI", "ticker": "CODNEG (codneg on derivative routes)",
            "market": "TPMERC", "short_name": "NOMRES", "spec": "ESPECI", "term_days": "PRAZOT",
            "currency": "MODREF; legacy routes may replace null with R$", "open": "PREABE", "high": "PREMAX",
            "low": "PREMIN", "average": "PREMED", "close": "PREULT (exercise_price on exercise events)",
            "bid": "PREOFC", "ask": "PREOFV", "trades": "TOTNEG", "quantity": "QUATOT", "volume": "VOLTOT",
            "contract_price": "PREEXE (strike on option routes); not yield or credit spread",
            "contract_correction": "INDOPC (strike_correction on option routes)",
            "contract_expiry": "DATVEN (expiry on option routes); 99991231 decoded to null",
            "quotation_factor": "FATCOT", "contract_points_raw": "PTOEXE original text",
            "isin": "CODISI; options carry underlying identity, not necessarily the option series ISIN",
            "distribution_number": "DISMES sequence, not a cash distribution amount",
        },
        "derived_fields": {"contract_points": "PTOEXE / 1e6; zero filler or unreadable points become null; strike_points on option routes", "close_unit": "close / NULLIF(quotation_factor, 0), not a corporate-event adjustment"},
        "routes": {
            "cash": {"market": ["010"], "view": "quotes", "history": "quote_history", "latest": "quote_latest"},
            "classified_cash": {"market": ["010", "020", "021"], "views": ["equities", "bdrs", "units", "fund_quotas", "cash_securities"], "limitation": "Only these five classes have typed views; index/right/bonus 010 prints remain in quotes."},
            "options": {"market": ["070", "080"], "functions": ["option_chain", "option_history"]},
            "exercises": {"market": ["012", "013"], "function": "option_exercises", "kind": "event"},
            "auctions": {"market": ["017"], "view": "auctions", "kind": "event"},
            "forward": {"market": ["030"], "function": "termo_history"},
        },
        "local_http_optional_fields": "Additional raw quote_history fields are selectable with fields; adjusted/total-return fields stay SQL-only.",
        "local_http_default_history_fields": ["open", "high", "low", "close", "volume", "trades"],
        "provenance_limit": "fetched_at is warehouse time; source is the dataset identifier, not file identity. No byte-exact payload, header/trailer reconciliation or source-vintage archive.",
    }
