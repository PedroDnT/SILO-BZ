-- 11_fund_registry_admin_gestor.sql — lift administrator/gestor to typed columns
--
-- Goal: enable administrator and gestor (portfolio-manager) rankings without
-- parsing the raw JSONB at query time. These service-provider fields are present
-- in both source registries and are captured by fund_registry.FIELD_MAP at ingest:
--
--   legacy cad_fi:           CNPJ_ADMIN, ADMIN, CPF_CNPJ_GESTOR, GESTOR
--   CVM-175 registro_fundo:  CNPJ_Administrador, Administrador, CPF_CNPJ_Gestor, Gestor
--
-- admin_cnpj is always a 14-digit PJ; gestor_id may be a CPF (PF gestor) or CNPJ,
-- so it is stored as text. Re-run the registry ingest to backfill these columns
-- for existing rows (ON CONFLICT DO UPDATE refreshes them).
--
-- All statements are idempotent and single-statement. No semicolons in comments.

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS admin_cnpj  TEXT;

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS admin_name  TEXT;

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS gestor_id   TEXT;

ALTER TABLE cvm_fund_registry ADD COLUMN IF NOT EXISTS gestor_name TEXT;

CREATE INDEX IF NOT EXISTS idx_fund_registry_admin  ON cvm_fund_registry (admin_name);

CREATE INDEX IF NOT EXISTS idx_fund_registry_gestor ON cvm_fund_registry (gestor_name);
