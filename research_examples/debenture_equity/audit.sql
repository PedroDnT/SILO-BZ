-- Read-only, one capture; render through audit.py (UUID substitution only).
-- Names, including commercial names, generate candidates, NEVER verified links.
WITH capture AS MATERIALIZED (
    SELECT capture_id, source, requested_from, requested_to, observed_at,
           status, expected_dates, delivered_dates, missing_dates, source_rows,
           debenture_rows, dropped_rows, payload_sha256,
           octet_length(raw_csv) AS raw_bytes,
           encode(sha256(convert_to(raw_csv, 'UTF8')), 'hex') = payload_sha256 AS hash_valid
    FROM public.b3_credit_capture WHERE capture_id = '__CAPTURE_ID__'::uuid
), facts AS MATERIALIZED (
    SELECT f.* FROM public.fact_credit_market f JOIN capture c USING (capture_id)
), tape AS MATERIALIZED (
    SELECT t.codneg, t.trade_date, t.nome_resumido, t.preco_fechamento, t.fetched_at
    FROM public.b3_cotahist t CROSS JOIN capture c
    WHERE t.trade_date BETWEEN c.requested_from AND c.requested_to AND t.tpmerc = '010'
), equity_tickers AS MATERIALIZED (
    SELECT DISTINCT cnpj_cia, codneg FROM public.cia_ticker
    WHERE valor_mobiliario IN ('Ações Ordinárias', 'Ações Preferenciais', 'Units')
      AND nullif(btrim(codneg), '') IS NOT NULL
), aliases AS (
    SELECT cnpj_cia, denom_cia AS name, 'cia_company.denom_cia' AS source FROM public.cia_company
    UNION ALL
    SELECT cnpj_cia, raw->>'DENOM_COMERC', 'cia_company.DENOM_COMERC' FROM public.cia_company
    UNION ALL
    SELECT cnpj_cia, raw->>'Nome_Empresarial', 'cia_ticker.Nome_Empresarial' FROM public.cia_ticker
    UNION ALL
    SELECT e.cnpj_cia, t.nome_resumido, 'b3_cotahist.nome_resumido'
    FROM tape t JOIN equity_tickers e USING (codneg)
    UNION ALL
    SELECT e.cnpj_cia, r.nome_instituicao, 'b3_instrument_registry.nome_instituicao'
    FROM public.b3_instrument_registry r JOIN equity_tickers e ON e.codneg = r.instrumento
    CROSS JOIN capture c WHERE r.reference_date BETWEEN c.requested_from AND c.requested_to
), normalized_aliases AS MATERIALIZED (
    SELECT DISTINCT cnpj_cia, name, source,
        regexp_replace(translate(upper(name), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
            'AAAAAEEEEIIIIOOOOOUUUUC'), '[^A-Z0-9]', '', 'g') AS name_key
    FROM aliases WHERE nullif(btrim(name), '') IS NOT NULL
), bonds AS (
    SELECT instrument_code, array_agg(DISTINCT isin ORDER BY isin) FILTER (WHERE isin IS NOT NULL) AS isins,
        array_agg(DISTINCT issuer_name ORDER BY issuer_name) FILTER (WHERE issuer_name IS NOT NULL) AS issuer_names
    FROM facts GROUP BY instrument_code
), names AS (
    SELECT DISTINCT instrument_code,
        regexp_replace(translate(upper(issuer_name), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
            'AAAAAEEEEIIIIOOOOOUUUUC'), '[^A-Z0-9]', '', 'g') AS name_key
    FROM facts WHERE issuer_name IS NOT NULL
), candidates AS (
    SELECT n.instrument_code, a.cnpj_cia,
           jsonb_agg(DISTINCT jsonb_build_object('name', a.name, 'source', a.source)) AS evidence
    FROM names n JOIN normalized_aliases a USING (name_key)
    WHERE n.name_key <> '' GROUP BY n.instrument_code, a.cnpj_cia
), ticker_coverage AS (
    SELECT e.cnpj_cia, e.codneg, count(DISTINCT t.trade_date) FILTER (
        WHERE t.preco_fechamento > 0) AS priced_sessions
    FROM equity_tickers e LEFT JOIN tape t USING (codneg) GROUP BY e.cnpj_cia, e.codneg
), candidate_rows AS (
    SELECT k.instrument_code, k.cnpj_cia, k.evidence,
           coalesce((SELECT jsonb_agg(jsonb_build_object('ticker', t.codneg,
               'priced_sessions', t.priced_sessions) ORDER BY t.codneg)
               FROM ticker_coverage t WHERE t.cnpj_cia = k.cnpj_cia), '[]'::jsonb) AS equities
    FROM candidates k
), bond_rows AS (
    SELECT b.*, (SELECT count(*) FROM candidate_rows k WHERE k.instrument_code = b.instrument_code) AS candidate_count,
        coalesce((SELECT jsonb_agg(to_jsonb(k) - 'instrument_code' ORDER BY k.cnpj_cia)
            FROM candidate_rows k WHERE k.instrument_code = b.instrument_code), '[]'::jsonb) AS candidates
    FROM bonds b
), sessions AS (
    SELECT trade_date, count(*) AS facts, count(DISTINCT instrument_code) AS bonds,
        count(*) FILTER (WHERE isin IS NULL) AS missing_isin_facts,
        count(*) FILTER (WHERE source <> (SELECT source FROM capture)) AS wrong_source_facts,
        count(DISTINCT (instrument_code, settlement_date, trade_classification)) AS groups
    FROM facts GROUP BY trade_date
), metrics AS (
    SELECT metric, count(*) AS facts, count(value) AS populated FROM facts GROUP BY metric
)
SELECT jsonb_build_object(
    'capture', (SELECT to_jsonb(c) FROM capture c),
    'sessions', coalesce((SELECT jsonb_agg(to_jsonb(s) ORDER BY trade_date) FROM sessions s), '[]'::jsonb),
    'metrics', coalesce((SELECT jsonb_agg(to_jsonb(m) ORDER BY metric) FROM metrics m), '[]'::jsonb),
    'cash_sessions', coalesce((SELECT jsonb_agg(d.trade_date ORDER BY d.trade_date)
        FROM (SELECT DISTINCT trade_date FROM tape) d), '[]'::jsonb),
    'bonds', coalesce((SELECT jsonb_agg(to_jsonb(b) ORDER BY instrument_code) FROM bond_rows b), '[]'::jsonb),
    'equity_note', 'FCA registration plus positive raw cash closes in this window only; not active-listing, adjusted-return or PIT certification',
    'mapping_note', 'Names from all stored FCA vintages and latest company register are candidate evidence only; no historical publication timestamp or definitive bond-to-CNPJ bridge'
) AS audit;
