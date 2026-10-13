-- 78_rj_document_new_tipos.sql
-- Four more values for rj_document.tipo (#845, epic #841), approved by the owner
-- on 2026-10-13. Each one names a kind of document that AJ sites publish and that
-- fell to 'outros' before (measured on the stored AJ titles, 2026-10-13):
--
--   termo_compromisso      the AJ's signed oath of office            (~575 rows)
--   constatacao_previa     the art. 51-A check: its order and report  (~612 rows)
--   nomeacao_aj            the decision that appoints the AJ          (~188 rows)
--   sentenca_encerramento  the decision that closes the case          (~120 rows)
--
-- The classifier (src/fetchers/rj/parse.py) sets them; existing rows change on
-- the next collector run, which upserts every document it reads.
-- The constraint is replaced, not edited in place: Postgres has no ALTER for a
-- CHECK. Every current value stays allowed, so no existing row can violate it.
-- Idempotent: DROP ... IF EXISTS, then ADD. psql -v ON_ERROR_STOP=1 clean.

BEGIN;

ALTER TABLE rj_document DROP CONSTRAINT IF EXISTS rj_document_tipo_check;
ALTER TABLE rj_document ADD CONSTRAINT rj_document_tipo_check CHECK (tipo IN (
    'peticao_inicial', 'relacao_credores_devedor', 'relacao_credores_aj',
    'plano', 'aditivo_plano', 'rma', 'qgc', 'ata_agc', 'edital_agc',
    'decisao_deferimento', 'sentenca_concessao',
    'demonstracoes_contabeis', 'termo_compromisso', 'constatacao_previa',
    'nomeacao_aj', 'sentenca_encerramento', 'outros'));

COMMIT;
