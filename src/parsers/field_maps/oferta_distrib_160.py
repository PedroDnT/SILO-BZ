"""CVM public offerings under Resolução CVM 160: oferta_resolucao_160.csv.

Source: dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.zip, one
of its two members (latin-1, ';', CRLF). Target table: cvm_oferta_distrib_160
(migration 81), one row per Numero_Requerimento.

Read from the real file on 2026-10-21 (zip dated 21-Oct-2026 01:56): 14,922
rows and 71 columns, Data_requerimento from 2023-01-05 to 2026-10-20,
Numero_Requerimento unique and never empty, every CNPJ_Emissor a valid CNPJ.
1,978 rows are Valor_Mobiliario = 'Debêntures'; the file covers every security
type (FIDC, CRI, CRA, FII, notas comerciais and others), so all are kept.
Dates are ISO, decimals use '.'. There is no ISIN, no series and no
remuneration column: the indexer of a debenture is not in this file.

Typed: the key, the issuer and lead manager, the dates, the status, the amounts
and the descriptive flags. The investor-type counts (Num_Invest_* and
Qtde_VM_*) and the long prose columns fall through to `raw`. CNPJ_Lider and the
agent columns are text: a lead or an agent is never padded into a CNPJ.
"""

TABLE = "cvm_oferta_distrib_160"
CONFLICT = ("numero_requerimento",)
REQUIRED = ("numero_requerimento", "cnpj_emissor")

FIELD_MAP = {
    "numero_requerimento":    (["Numero_Requerimento"], "text"),
    "rito_requerimento":      (["Rito_Requerimento"], "text"),
    "numero_processo":        (["Numero_Processo"], "text"),
    "data_requerimento":      (["Data_requerimento"], "date"),
    "data_registro":          (["Data_Registro"], "date"),
    "data_encerramento":      (["Data_Encerramento"], "date"),
    "status_requerimento":    (["Status_Requerimento"], "text"),
    "valor_mobiliario":       (["Valor_Mobiliario"], "text"),
    "tipo_requerimento":      (["Tipo_requerimento"], "text"),
    "cnpj_emissor":           (["CNPJ_Emissor"], "cnpj"),
    "nome_emissor":           (["Nome_Emissor"], "text"),
    "cnpj_lider":             (["CNPJ_Lider"], "text"),
    "nome_lider":             (["Nome_Lider"], "text"),
    "tipo_oferta":            (["Tipo_Oferta"], "text"),
    "emissao":                (["Emissao"], "text"),
    "qtde_total_registrada":  (["Qtde_Total_Registrada"], "numeric"),
    "valor_total_registrado": (["Valor_Total_Registrado"], "numeric"),
    "oferta_inicial":         (["Oferta_inicial"], "text"),
    "publico_alvo":           (["Publico_alvo"], "text"),
    "titulo_incentivado":     (["Titulo_incentivado"], "text"),
    "titulo_sustentavel":     (["Titulo_classificado_como_sustentavel"], "text"),
    "regime_distribuicao":    (["Regime_distribuicao"], "text"),
    "mercado_negociacao":     (["Mercado_negociacao"], "text"),
    "tipo_lastro":            (["Tipo_lastro"], "text"),
    "regime_fiduciario":      (["Regime_fiduciario"], "text"),
    "tipo_societario":        (["Tipo_societario"], "text"),
    "agente_fiduciario":      (["Agente_fiduciario"], "text"),
    "data_deliberacao":       (["Data_deliberacao_aprovou_oferta"], "date"),
}
