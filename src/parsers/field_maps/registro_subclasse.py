"""CVM 175 subclass level: registro_subclasse.csv (member of registro_fundo_classe.zip).

Target table: cvm_registro_subclasse (migration 67), one row per
(ID_Registro_Classe, ID_Subclasse).

The file has NO CNPJ column. CVM lists its columns as ID_Registro_Classe,
ID_Subclasse, Codigo_CVM, Data_Constituicao, Data_Inicio, Denominacao_Social,
Situacao, Forma_Condominio, Exclusivo, Publico_Alvo (dados.cvm.gov.br/pages/
novidades, 2024-10-07), plus Data_Inicio_Situacao (2025-08-20) and
Previdenciario, Exclusivo_INR, Exclusivo_Previdencia_Complementar (2026-01-26).
Res. CVM 175 gives a subclass no CNPJ of its own, so the key is the registry's
identifiers and a CNPJ is never stamped on the row: the CNPJ is the class's,
reached through ID_Registro_Classe. ID_Subclasse is the same kind of code the
informe diário, the lâmina and the CDA publish as ID_SUBCLASSE (15 characters
in the lâmina, e.g. GPZ7A1744144200).

Keyed on the pair, not on ID_Subclasse alone: the pair is what the file states,
and a subclass id repeated under two classes then stays two rows instead of
one row silently re-pointed.
"""

TABLE = "cvm_registro_subclasse"
CONFLICT = ("id_registro_classe", "id_subclasse")
REQUIRED = ("id_registro_classe", "id_subclasse")

FIELD_MAP = {
    "id_registro_classe": (["ID_Registro_Classe"], "text"),
    "id_subclasse":       (["ID_Subclasse"],       "text"),
    "codigo_cvm":         (["Codigo_CVM"],         "text"),
    "denominacao_social": (["Denominacao_Social"], "text"),
    "situacao":           (["Situacao"],           "text"),
    "publico_alvo":       (["Publico_Alvo"],       "text"),
}
