-- Executed checks for api.rj_listed_documents (34_api_rj_listed.sql, catalog
-- v75, #842). The Python tests pin the SQL text; this proves the view and the
-- function DO the right thing on rows. Synthetic CVM codes (99xxx) and
-- protocols, inside a transaction that is rolled back:
--
--   psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -f tests/sql/rj_listed_documents_behaviour.sql

BEGIN;

INSERT INTO cia_company (cd_cvm, cnpj_cia, denom_cia, raw) VALUES
    ('99001', '99000000000101', 'RJ CATEGORIA SA',
     '{"SIT_EMISSOR": "EM RECUPERAÇÃO JUDICIAL OU EQUIVALENTE", "DT_INI_SIT_EMISSOR": "2026-03-01"}'),
    ('99002', '99000000000102', 'RJ SO FATO SA',
     '{"SIT_EMISSOR": "FASE OPERACIONAL", "DT_INI_SIT_EMISSOR": ""}');

INSERT INTO cia_event
    (cd_cvm, cnpj_cia, data_refer, data_entrega, categoria, tipo, especie, assunto,
     protocolo, versao, link_download)
VALUES
    -- RJ category, two versions of one protocol: only version 2 is served.
    ('99001', '99000000000101', '2026-03-01', '2026-03-02 00:00+00',
     'Informações de Companhias em Recuperação Judicial ou Extrajudicial',
     'Petição Inicial', NULL, 'Pedido de RJ', 'P99-0001', 1, 'https://rad.example/v1'),
    ('99001', '99000000000101', '2026-03-01', '2026-03-03 00:00+00',
     'Informações de Companhias em Recuperação Judicial ou Extrajudicial',
     'Petição Inicial', NULL, 'Pedido de RJ', 'P99-0001', 2, 'https://rad.example/v2'),
    -- RJ category, a plan, with a reference date far in the future.
    ('99001', '99000000000101', '3036-01-01', '2026-05-10 00:00+00',
     'Informações de Companhias em Recuperação Judicial ou Extrajudicial',
     'Plano de Recuperação', NULL, 'Plano', 'P99-0002', 1, 'https://rad.example/plano'),
    -- Fato Relevante naming the recovery: served as fato_relevante.
    ('99002', '99000000000102', '2026-08-16', '2026-08-17 00:00+00',
     'Fato Relevante', NULL, NULL, 'Deferimento do Processamento da Recuperação Judicial',
     'P99-0003', 1, 'https://rad.example/fr1'),
    ('99002', '99000000000102', '2026-08-20', '2026-08-20 00:00+00',
     'Fato Relevante', NULL, NULL, 'Prorrogação das obrigações das Recuperandas',
     'P99-0004', 1, 'https://rad.example/fr2'),
    -- Fato Relevante about something else: not served.
    ('99002', '99000000000102', '2026-08-21', '2026-08-21 00:00+00',
     'Fato Relevante', NULL, NULL, 'Recuperação de créditos tributários',
     'P99-0005', 1, 'https://rad.example/fr3'),
    -- Falência category: not served.
    ('99002', '99000000000102', '2026-08-22', '2026-08-22 00:00+00',
     'Informações Companhias em Falência', 'Relatório final', NULL, 'x',
     'P99-0006', 1, 'https://rad.example/fal');

DO $$
DECLARE
    n   INT;
    r   RECORD;
BEGIN
    -- Every company, wide window: 4 protocols, newest version only.
    SELECT count(*) INTO n FROM api.rj_listed_documents(NULL, '2026-01-01', '2026-12-31')
     WHERE cd_cvm LIKE '99%';
    ASSERT n = 4, format('expected 4 RJ rows, got %s', n);

    SELECT * INTO r FROM api.rj_listed_documents('99001', '2026-01-01', '2026-12-31', 'Petição Inicial');
    ASSERT r.version = 2 AND r.source_url = 'https://rad.example/v2', 'newest version served';
    ASSERT r.signal = 'categoria', 'category signal';
    ASSERT r.cadastro_status = 'EM RECUPERAÇÃO JUDICIAL OU EQUIVALENTE', 'cadastro status as filed';
    ASSERT r.cadastro_status_since = DATE '2026-03-01', 'cadastro date parsed';
    ASSERT r.delivery_date = DATE '2026-03-03', 'delivery date of the served version';

    -- A Fato Relevante that names the recovery, and the cadastro that lags.
    SELECT count(*) INTO n FROM api.rj_listed_documents('99002', '2026-01-01', '2026-12-31')
     WHERE signal = 'fato_relevante';
    ASSERT n = 2, format('expected 2 fato_relevante rows, got %s', n);
    SELECT * INTO r FROM api.rj_listed_documents('99002', '2026-08-17', '2026-08-17');
    ASSERT r.cadastro_status = 'FASE OPERACIONAL' AND r.cadastro_status_since IS NULL,
        'a lagging cadastro is served as filed, an empty date stays NULL';

    -- The window is the delivery date, never the reference date.
    SELECT count(*) INTO n FROM api.rj_listed_documents('99001', '3036-01-01', '3036-12-31');
    ASSERT n = 0, 'reference_date does not drive the window';

    -- An id that resolves to nothing returns no rows.
    SELECT count(*) INTO n FROM api.rj_listed_documents('00000', '2026-01-01', '2026-12-31');
    ASSERT n = 0, 'unknown id is empty';

    -- An unknown doc_type and an inverted window refuse with 22023.
    BEGIN
        PERFORM api.rj_listed_documents(NULL, NULL, NULL, 'Not a type');
        RAISE EXCEPTION 'unknown doc_type was accepted';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;
    BEGIN
        PERFORM api.rj_listed_documents(NULL, '2026-12-31', '2026-01-01');
        RAISE EXCEPTION 'inverted window was accepted';
    EXCEPTION WHEN sqlstate '22023' THEN NULL;
    END;

    RAISE NOTICE 'rj_listed_documents OK';
END $$;

-- anon can call it; the view stays private.
SET LOCAL ROLE anon;
SELECT count(*) FROM api.rj_listed_documents(NULL, '2026-01-01', '2026-12-31');
DO $$
BEGIN
    PERFORM 1 FROM public.rj_listed_documents LIMIT 1;
    RAISE EXCEPTION 'anon read the internal view';
EXCEPTION WHEN insufficient_privilege THEN NULL;
END $$;
RESET ROLE;

ROLLBACK;
