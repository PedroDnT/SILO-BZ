"""CVM 175 class level: registro_classe.csv (member of registro_fundo_classe.zip).

Target table: cvm_registro_classe (migration 67), one row per ID_Registro_Classe,
carrying ID_Registro_Fundo, the registry's own pointer to the parent fund
(cvm_registro_fundo). A class reaches its fund through that id only.

Columns as published by CVM (dados.cvm.gov.br/pages/novidades, 2024-10-07):
ID_Registro_Fundo, ID_Registro_Classe, CNPJ_Classe, Codigo_CVM, Data_Registro,
Data_Constituicao, Data_Inicio, Tipo_Classe, Denominacao_Social, Situacao,
Classificacao, Indicador_Desempenho, Classe_Cotas, Classificacao_Anbima, ...
The file has no CNPJ_Fundo column.

Classe_Cotas is S/N on FIF classes and empty on the other families (measured
2026-10-03). S marks a classe de investimento em cotas (Res. CVM 175 Anexo I
Art. 2 VI, at least 95% of NAV in quotas of other classes). It is mapped as
text here and parsed by ingest_misc._classe_cotas, not by the generic "bool"
coercion, because that one would turn an unexpected value into False.
"""

TABLE = "cvm_registro_classe"
CONFLICT = ("id_registro_classe",)
REQUIRED = ("id_registro_classe", "id_registro_fundo")

FIELD_MAP = {
    "id_registro_classe":   (["ID_Registro_Classe"],   "text"),
    "id_registro_fundo":    (["ID_Registro_Fundo"],    "text"),
    "cnpj_classe":          (["CNPJ_Classe"],          "cnpj"),
    "codigo_cvm":           (["Codigo_CVM"],           "text"),
    "tipo_classe":          (["Tipo_Classe"],          "text"),
    "denominacao_social":   (["Denominacao_Social"],   "text"),
    "situacao":             (["Situacao"],             "text"),
    "data_registro":        (["Data_Registro"],        "date"),
    "classificacao":        (["Classificacao"],        "text"),
    "classe_cotas":         (["Classe_Cotas"],         "text"),  # S/N, see module doc
    "classificacao_anbima": (["Classificacao_Anbima"], "text"),
}
