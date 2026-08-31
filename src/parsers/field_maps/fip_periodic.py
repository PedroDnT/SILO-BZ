"""FIP periodic reports field map.

Source CSV: inf_trimestral_fip_{year}.csv (2010-2023) or
           inf_quadrimestral_fip_{year}.csv (2024+).
Target table: cvm_fip_periodic.

WHAT WAS WRONG. The key was (cnpj, doc_type, period_year) and the reference
date was never extracted at all — DT_COMPTC sat in `raw`, unread. But a FIP
yearly CSV holds every filing of that year: four quarters for inf_trimestral,
three periods for inf_quadrimestral, and one row per share class within each.
Every one of those collided on a key that could only hold one row per fund per
year, so the last row written survived and the rest were discarded.

Measured on the real published files:

    file                  rows    survived under the old key       lost
    inf_trimestral_2015  3,154    887                              72%
    inf_trimestral_2022  6,753    1,580                            77%
    inf_quadrimestral_2025 7,880  2,193                            72%

That is the same failure as the CDA month collapse, one grain up: a table that
looks populated, is not, and reports whichever filing happened to be last in
the file. It is also why FIP has always presented as a single December 31 row
per fund.

THE KEY, audited against those three files:

    cnpj + doc_type + period                      2015 UNIQUE  2022 726  2025 1100
    + classe_cota                                 2015 UNIQUE  2022   7  2025  133
    + classe_cota + row_hash                      UNIQUE on all three

CLASSE_COTA is load-bearing: a fund files one row per share class (A, B, C…)
with different subscribed capital and quota counts per class. Dropping it
merges classes that hold genuinely different money.

row_hash is the LAST element and only a tiebreaker. What remains after
classe_cota is CVM restating the same (fund, date, class) with different
capital figures — no published column separates the two filings, so a natural
key cannot. Rather than pick one and discard the other, both are kept and
`fetched_at` orders them; a serving layer that wants one row takes the latest.
The hash is a sha256 over the row's own published fields (src/parsers/mapping.py
row_hash) — nothing invented, and re-ingesting an unchanged file is an exact
no-op.

period is the row's own DT_COMPTC, not the archive year. period_year is kept as
a stored column because the coverage checks and the backfill gate read it, but
it is no longer part of the key.
"""

TABLE = "cvm_fip_periodic"
CONFLICT = ("cnpj", "doc_type", "period", "classe_cota", "row_hash")

FIELD_MAP = {
    "cnpj":          (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],  "cnpj"),
    "period":        (["DT_COMPTC"],                        "date"),
    "classe_cota":   (["CLASSE_COTA"],                      "text"),
    "tp_fundo":      (["TP_FUNDO_CLASSE", "TP_FUNDO"],      "text"),
    "denom_social":  (["DENOM_SOCIAL"],                     "text"),
    "vl_patrim_liq": (["VL_PATRIM_LIQ"],                    "numeric"),
    "qt_cota":       (["QT_COTA"],                          "numeric"),
    "vl_patrim_cota": (["VL_PATRIM_COTA"],                  "numeric"),
    "nr_cotst":      (["NR_COTST"],                         "numeric"),
    "vl_cap_comprom": (["VL_CAP_COMPROM"],                  "numeric"),
    "vl_cap_subscr": (["VL_CAP_SUBSCR"],                    "numeric"),
    "vl_cap_integr": (["VL_CAP_INTEGR"],                    "numeric"),
}
