"""CVM registered debenture offerings under ICVM 400: oferta_distribuicao.csv.

Source: the other member of dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/
oferta_distribuicao.zip (latin-1, ';', CRLF). Target table:
cvm_oferta_distrib_400 (migration 81), one row per (Numero_Registro_Oferta,
Serie). Adding Tipo_Oferta and Tipo_Componente_Oferta_Mista to the key separates
no further row (measured), and the second is mostly empty.

The file holds every pre-Resolution-160 offering (48,944 rows, 76 columns on
2026-10-21), but it has no natural key for most of them: an ICVM 476 offering
repeats once per notice, often with Valor_Total 0.00, and has no registration
number or issue date. Owner decision 2026-10-21: keep only the registered
offerings, Rito_Oferta starting 'ICVM 400', of debentures (Tipo_Ativo containing
'DEBÊNTURES'). Measured: 1,832 such rows; 21 have no Numero_Registro_Oferta and
19 share a key with another row with different values. Both are dropped and
counted: the file does not say which duplicate is right. 1,205 rows, nearly
all registered before 2005, publish no CNPJ_Emissor; it stays NULL.

Dates are ISO, decimals use '.'. Quantidade_Total is '9000.00', so quantities
are numeric, never int. Atualizacao_Monetaria and Juros are free text as filed
(IGPM, IGP-M, 'NAO', '12% A.A.') and stay text.
"""

TABLE = "cvm_oferta_distrib_400"
CONFLICT = ("numero_registro_oferta", "serie")
REQUIRED = ("numero_registro_oferta", "serie", "tipo_ativo", "rito_oferta")

FIELD_MAP = {
    "numero_registro_oferta": (["Numero_Registro_Oferta"], "text"),
    "serie":                  (["Serie"], "text"),
    "tipo_oferta":            (["Tipo_Oferta"], "text"),
    "tipo_componente":        (["Tipo_Componente_Oferta_Mista"], "text"),
    "numero_processo":        (["Numero_Processo"], "text"),
    "tipo_ativo":             (["Tipo_Ativo"], "text"),
    "rito_oferta":            (["Rito_Oferta"], "text"),
    "modalidade_registro":    (["Modalidade_Registro"], "text"),
    "cnpj_emissor":           (["CNPJ_Emissor"], "cnpj"),
    "nome_emissor":           (["Nome_Emissor"], "text"),
    "cnpj_lider":             (["CNPJ_Lider"], "text"),
    "nome_lider":             (["Nome_Lider"], "text"),
    "data_protocolo":         (["Data_Protocolo"], "date"),
    "data_registro_oferta":   (["Data_Registro_Oferta"], "date"),
    "data_inicio_oferta":     (["Data_Inicio_Oferta"], "date"),
    "data_encerramento_oferta": (["Data_Encerramento_Oferta"], "date"),
    "emissao":                (["Emissao"], "text"),
    "classe_ativo":           (["Classe_Ativo"], "text"),
    "especie_ativo":          (["Especie_Ativo"], "text"),
    "forma_ativo":            (["Forma_Ativo"], "text"),
    "data_emissao":           (["Data_Emissao"], "date"),
    "data_vencimento":        (["Data_Vencimento"], "date"),
    "quantidade_total":       (["Quantidade_Total"], "numeric"),
    "preco_unitario":         (["Preco_Unitario"], "numeric"),
    "valor_total":            (["Valor_Total"], "numeric"),
    "oferta_incentivo_fiscal": (["Oferta_Incentivo_Fiscal"], "text"),
    "atualizacao_monetaria":  (["Atualizacao_Monetaria"], "text"),
    "juros":                  (["Juros"], "text"),
    "tipo_societario_emissor": (["Tipo_Societario_Emissor"], "text"),
    "ultimo_comunicado":      (["Ultimo_Comunicado"], "text"),
    "data_comunicado":        (["Data_Comunicado"], "date"),
}
