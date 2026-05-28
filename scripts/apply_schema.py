"""
Apply schema.sql changes to Supabase by executing DDL via direct PostgreSQL.

Usage:
    python scripts/apply_schema.py

Requires: POSTGRES_URL in .env (postgresql://... format)
Falls back to manual instructions if connection fails.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# DDL blocks to apply (all idempotent — safe to re-run)
# ---------------------------------------------------------------------------

MIGRATIONS = [
    ("FII new columns (Phase 0)", """
ALTER TABLE cvm_fii_mensal
    ADD COLUMN IF NOT EXISTS nr_cotst               INT,
    ADD COLUMN IF NOT EXISTS vl_ativo               NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS cotas_emitidas         NUMERIC(28,6),
    ADD COLUMN IF NOT EXISTS vl_patrimonial_cotas   NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_rentab_efetiva_mes NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_rentab_patrimonial NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_dividend_yield_mes NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS pct_amortizacao_mes    NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS rendimentos_distribuir NUMERIC(20,6)
"""),
    ("Widen numeric precision (post smoke-test)", """
ALTER TABLE cvm_fidc_tranche
    ALTER COLUMN qt_cota            TYPE NUMERIC(28,8),
    ALTER COLUMN vl_cota            TYPE NUMERIC(28,8),
    ALTER COLUMN vl_rentab_mes      TYPE NUMERIC(20,6),
    ALTER COLUMN pr_desemp_esperado TYPE NUMERIC(20,6),
    ALTER COLUMN pr_desemp_real     TYPE NUMERIC(20,6);
ALTER TABLE cvm_fidc_tranche_flows
    ALTER COLUMN qt_cota TYPE NUMERIC(28,8);
ALTER TABLE cvm_fii_mensal
    ALTER COLUMN cotas_emitidas         TYPE NUMERIC(28,6),
    ALTER COLUMN pct_rentab_efetiva_mes TYPE NUMERIC(20,6),
    ALTER COLUMN pct_rentab_patrimonial TYPE NUMERIC(20,6),
    ALTER COLUMN pct_dividend_yield_mes TYPE NUMERIC(20,6),
    ALTER COLUMN pct_amortizacao_mes    TYPE NUMERIC(20,6)
"""),

    ("cvm_fidc_tranche (Phase 1)", """
CREATE TABLE IF NOT EXISTS cvm_fidc_tranche (
    id                 BIGSERIAL    PRIMARY KEY,
    cnpj               TEXT         NOT NULL,
    period             DATE         NOT NULL,
    classe_serie       TEXT         NOT NULL,
    qt_cota            NUMERIC(28,8),
    vl_cota            NUMERIC(28,8),
    vl_rentab_mes      NUMERIC(20,6),
    pr_desemp_esperado NUMERIC(20,6),
    pr_desemp_real     NUMERIC(20,6),
    raw                JSONB,
    fetched_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_tranche UNIQUE (cnpj, period, classe_serie)
)
"""),
    ("cvm_fidc_tranche indexes", """
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_cnpj   ON cvm_fidc_tranche (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_period ON cvm_fidc_tranche (period DESC)
"""),

    ("cvm_fidc_tranche_flows (Phase 1)", """
CREATE TABLE IF NOT EXISTS cvm_fidc_tranche_flows (
    id           BIGSERIAL    PRIMARY KEY,
    cnpj         TEXT         NOT NULL,
    period       DATE         NOT NULL,
    classe_serie TEXT         NOT NULL,
    tp_oper      TEXT         NOT NULL,
    vl_total     NUMERIC(20,6),
    qt_cota      NUMERIC(28,8),
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_tranche_flows UNIQUE (cnpj, period, classe_serie, tp_oper)
)
"""),
    ("cvm_fidc_tranche_flows indexes", """
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_flows_cnpj   ON cvm_fidc_tranche_flows (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_tranche_flows_period ON cvm_fidc_tranche_flows (period DESC)
"""),

    ("cvm_fidc_aging (Phase 1)", """
CREATE TABLE IF NOT EXISTS cvm_fidc_aging (
    id                   BIGSERIAL    PRIMARY KEY,
    cnpj                 TEXT         NOT NULL,
    period               DATE         NOT NULL,
    vl_prazo_30          NUMERIC(20,6),
    vl_prazo_60          NUMERIC(20,6),
    vl_prazo_90          NUMERIC(20,6),
    vl_prazo_120         NUMERIC(20,6),
    vl_prazo_150         NUMERIC(20,6),
    vl_prazo_180         NUMERIC(20,6),
    vl_prazo_360         NUMERIC(20,6),
    vl_prazo_720         NUMERIC(20,6),
    vl_prazo_1080        NUMERIC(20,6),
    vl_prazo_maior_1080  NUMERIC(20,6),
    vl_inad_30           NUMERIC(20,6),
    vl_inad_60           NUMERIC(20,6),
    vl_inad_90           NUMERIC(20,6),
    vl_inad_120          NUMERIC(20,6),
    vl_inad_150          NUMERIC(20,6),
    vl_inad_180          NUMERIC(20,6),
    vl_inad_360          NUMERIC(20,6),
    vl_inad_720          NUMERIC(20,6),
    vl_inad_1080         NUMERIC(20,6),
    vl_inad_maior_1080   NUMERIC(20,6),
    vl_total_inad        NUMERIC(20,6),
    raw                  JSONB,
    fetched_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fidc_aging UNIQUE (cnpj, period)
)
"""),
    ("cvm_fidc_aging indexes", """
CREATE INDEX IF NOT EXISTS idx_fidc_aging_cnpj   ON cvm_fidc_aging (cnpj);
CREATE INDEX IF NOT EXISTS idx_fidc_aging_period ON cvm_fidc_aging (period DESC)
"""),

    ("cvm_securit_serie (Phase 2)", """
CREATE TABLE IF NOT EXISTS cvm_securit_serie (
    id                        BIGSERIAL    PRIMARY KEY,
    instrument_type           TEXT         NOT NULL,
    cnpj_securit              TEXT,
    codigo_identificacao      TEXT         NOT NULL,
    data_referencia           DATE         NOT NULL,
    classe                    TEXT,
    numero_serie              INT,
    tipo_oferta               TEXT,
    codigo_cetip              TEXT,
    codigo_isin               TEXT,
    data_vencimento           DATE,
    situacao                  TEXT,
    valor_total_integralizado NUMERIC(20,6),
    taxa_juros                TEXT,
    pagamento_periodicidade   TEXT,
    quantidade_certificados   NUMERIC(20,0),
    valor_certificados        NUMERIC(20,6),
    rendimentos               NUMERIC(20,6),
    amortizacoes              NUMERIC(20,6),
    rentabilidade             NUMERIC(20,8),
    classificacao_risco_atual TEXT,
    indice_subordinacao_minimo NUMERIC(10,6),
    fetched_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_serie UNIQUE NULLS NOT DISTINCT
        (instrument_type, cnpj_securit, codigo_identificacao, data_referencia, numero_serie)
)
"""),
    ("cvm_securit_serie indexes", """
CREATE INDEX IF NOT EXISTS idx_securit_serie_cnpj     ON cvm_securit_serie (cnpj_securit);
CREATE INDEX IF NOT EXISTS idx_securit_serie_isin     ON cvm_securit_serie (codigo_isin);
CREATE INDEX IF NOT EXISTS idx_securit_serie_situacao ON cvm_securit_serie (situacao, data_referencia DESC)
"""),

    ("cvm_securit_fluxo (Phase 2)", """
CREATE TABLE IF NOT EXISTS cvm_securit_fluxo (
    id                                BIGSERIAL    PRIMARY KEY,
    instrument_type                   TEXT         NOT NULL,
    cnpj_securit                      TEXT,
    codigo_identificacao              TEXT         NOT NULL,
    data_referencia                   DATE         NOT NULL,
    recebimentos_direitos_creditorios NUMERIC(20,6),
    pagamentos_despesas               NUMERIC(20,6),
    pagamentos_classe_senior          NUMERIC(20,6),
    pagamentos_senior_principal       NUMERIC(20,6),
    pagamentos_senior_juros           NUMERIC(20,6),
    pagamentos_mezanino               NUMERIC(20,6),
    pagamentos_mezanino_principal     NUMERIC(20,6),
    pagamentos_mezanino_juros         NUMERIC(20,6),
    pagamentos_junior                 NUMERIC(20,6),
    pagamentos_junior_principal       NUMERIC(20,6),
    pagamentos_junior_juros           NUMERIC(20,6),
    variacao_liquida_caixa            NUMERIC(20,6),
    fetched_at                        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_securit_fluxo UNIQUE NULLS NOT DISTINCT
        (instrument_type, cnpj_securit, codigo_identificacao, data_referencia)
)
"""),
    ("cvm_securit_fluxo indexes", """
CREATE INDEX IF NOT EXISTS idx_securit_fluxo_cnpj ON cvm_securit_fluxo (cnpj_securit);
CREATE INDEX IF NOT EXISTS idx_securit_fluxo_date ON cvm_securit_fluxo (data_referencia DESC)
"""),
]


def apply_via_psycopg2(db_url: str):
    import psycopg2  # type: ignore
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    ok = err = 0
    for name, sql in MIGRATIONS:
        try:
            cur.execute(sql.strip())
            print(f"  ✓ {name}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            err += 1
    cur.close()
    conn.close()
    return ok, err


def apply_via_asyncpg(db_url: str):
    import asyncio, asyncpg  # type: ignore

    async def _run():
        conn = await asyncpg.connect(db_url)
        ok = err = 0
        for name, sql in MIGRATIONS:
            try:
                await conn.execute(sql.strip())
                print(f"  ✓ {name}")
                ok += 1
            except Exception as e:
                print(f"  ✗ {name}: {e}")
                err += 1
        await conn.close()
        return ok, err

    return asyncio.run(_run())


def print_manual_instructions():
    print("\n  ── MANUAL FALLBACK ──────────────────────────────────────────────")
    print("  Paste the following SQL blocks into Supabase Dashboard → SQL Editor:")
    print()
    for name, sql in MIGRATIONS:
        print(f"  -- {name}")
        print(sql.strip())
        print()


def main():
    print("=" * 68)
    print("  CVM SCHEMA MIGRATION")
    print("=" * 68)

    db_url = os.environ.get("POSTGRES_URL")
    if not db_url:
        print("  POSTGRES_URL not set.")
        print_manual_instructions()
        return

    print(f"  DB URL: {db_url[:40]}…")
    print(f"  Applying {len(MIGRATIONS)} migration blocks…\n")

    for driver, fn in [("psycopg2", apply_via_psycopg2), ("asyncpg", apply_via_asyncpg)]:
        try:
            __import__(driver.replace("psycopg2", "psycopg2"))
            ok, err = fn(db_url)
            print(f"\n  Done: {ok} OK, {err} errors  (driver: {driver})")
            return
        except ImportError:
            continue
        except Exception as e:
            print(f"  Connection failed ({driver}): {e}")
            break

    print("\n  No PostgreSQL driver available. Falling back to manual instructions.")
    print_manual_instructions()


if __name__ == "__main__":
    main()
