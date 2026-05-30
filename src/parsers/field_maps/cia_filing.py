"""CIA_ABERTA ITR/DFP filing-header field map (W7).

Source CSV: the summary header member inside each ITR/DFP yearly ZIP, e.g.
            dfp_cia_aberta_2024.csv (latin-1, ; delimited). One row per filing
            (company x reference date x version). Fetched with
            CIAFetcher.fetch_zip_members(..., include_summary=True).
Target:     cia_filing  (UNIQUE on cd_cvm, doc_type, dt_refer, versao)

Header (verified live 2026-05-29 against dfp_cia_aberta_2023.zip):
    CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC

Notes
-----
* ``doc_type`` (itr/dfp) is injected by ``ingest_cia_filing`` from the call
  argument — it is not a CSV column.
* ``CD_CVM`` is zero-padded in ITR/DFP; the ``cd_cvm`` coerce strips leading zeros
  so cia_filing.cd_cvm matches cia_company / cia_account.
* cia_filing has no ``raw`` JSONB column in the DDL, so unmapped fields
  (CNPJ_CIA, DENOM_CIA, CATEG_DOC) are discarded by the ingest module — CNPJ /
  name are denormalised against cia_company (joinable by cd_cvm).
* The natural key is (cd_cvm, doc_type, dt_refer, versao); the PK is a surrogate
  BIGSERIAL and the UNIQUE constraint enforces idempotency.
"""

TABLE = "cia_filing"
CONFLICT = ("cd_cvm", "doc_type", "dt_refer", "versao")

FIELD_MAP = {
    "cd_cvm":   (["CD_CVM"],    "cd_cvm"),
    "dt_refer": (["DT_REFER"],  "date"),
    "versao":   (["VERSAO"],    "int"),
    "id_doc":   (["ID_DOC"],    "text"),
    "dt_receb": (["DT_RECEB"],  "date"),
    "link_doc": (["LINK_DOC"],  "text"),
}
