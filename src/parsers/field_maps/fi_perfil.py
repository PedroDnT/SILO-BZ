"""FI monthly investor profile (PERFIL_MENSAL) field map.

Source CSV: inf_perfil_mensal_fi_{year}{month:02d}.csv (latin-1, ';'-delimited).
Target table: cvm_fi_perfil.

The perfil_mensal CSV carries many demographic/AUM columns.  The schema
currently only has cnpj + period + raw; columns here are candidates to lift
when the schema is extended (see W3 numeric-precision audit).  For now only
the key columns are typed; everything else falls through to residual raw.
"""

TABLE = "cvm_fi_perfil"
CONFLICT = ("cnpj", "period")

FIELD_MAP = {
    "cnpj":          (["CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"],  "cnpj"),
    "period":        (["DT_COMPTC", "DT_REF"],               "date"),
    # Extended columns — present in schema via ADD COLUMN migrations
    "tp_fundo":      (["TP_FUNDO_CLASSE", "TP_FUNDO"],       "text"),
    "mod_var":       (["MOD_VAR"],                           "text"),
}
