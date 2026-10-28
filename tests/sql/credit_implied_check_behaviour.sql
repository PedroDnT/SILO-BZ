-- Synthetic data only; all writes roll back. The ANBIMA comparison view:
-- same code and day, gap = implied - indicative, the tags and the privacy.
BEGIN;
INSERT INTO public.b3_credit_capture
(capture_id,source,requested_from,requested_to,observed_at,source_url,payload_sha256,
 raw_csv,status,expected_dates,delivered_dates,missing_dates,source_rows,debenture_rows,dropped_rows)
VALUES ('cccccccc-0000-4000-8000-0000000000a1','b3_bdi_consolidated_records','2001-01-02','2001-01-02',
 '2020-01-01 10:00+00','test://credit',repeat('a',64),'synthetic','complete',
 '["2001-01-02"]'::jsonb,'["2001-01-02"]'::jsonb,'[]'::jsonb,1,0,0);
INSERT INTO public.b3_credit_implied_rate
(codigo,trade_date,settlement_date,trade_classification,method_version,b3_capture_id,pu_brl,volume_brl,
 trade_count,indexador,forma_remuneracao,contract_rate_pct,implied_rate_pct,rate_basis,flows_used,inputs,solver,computed_at)
SELECT s.code,'2001-01-02','2001-01-02','EXTRAGRUPO','v1','cccccccc-0000-4000-8000-0000000000a1',1000,s.vol,
 1,'DI','spread',1,s.imp,s.basis,3,'{}'::jsonb,'{}'::jsonb,'2020-01-01 11:00+00'
FROM (VALUES ('CHK001',500000,12.00,'di_spread_aa'),   -- gap 0.50: checked
             ('DIV001',500000,14.00,'di_spread_aa'),   -- gap 2.00: divergent
             ('OUT001',10000, 75.00,'di_spread_aa'),   -- gap 60: outlier, thin
             ('NOA001',500000,12.00,'di_spread_aa'),   -- no ANBIMA rate: unchecked
             ('PCT001',500000,101.0,'pct_di')) s(code,vol,imp,basis);
INSERT INTO public.anbima_debenture_indicative (codigo,data_referencia,taxa_indicativa_pct,capture_id,observed_at)
VALUES ('CHK001','2001-01-02',11.50,'cccccccc-0000-4000-8000-0000000000b1','2020-01-01 12:00+00'),
       ('DIV001','2001-01-02',12.00,'cccccccc-0000-4000-8000-0000000000b1','2020-01-01 12:00+00'),
       ('OUT001','2001-01-02',15.00,'cccccccc-0000-4000-8000-0000000000b1','2020-01-01 12:00+00'),
       ('PCT001','2001-01-02',100.0,'cccccccc-0000-4000-8000-0000000000b1','2020-01-01 12:00+00');
DO $test$
DECLARE r RECORD; role_name TEXT;
BEGIN
 SELECT * INTO r FROM public.credit_implied_vs_anbima WHERE codigo='CHK001';
 IF r.confidence<>'checked' OR r.gap_pp<>0.50 OR r.outlier OR r.thin_trade THEN RAISE EXCEPTION 'CHK001 wrong: %',r; END IF;
 SELECT * INTO r FROM public.credit_implied_vs_anbima WHERE codigo='DIV001';
 IF r.confidence<>'divergent' OR r.outlier THEN RAISE EXCEPTION 'DIV001 wrong: %',r; END IF;
 SELECT * INTO r FROM public.credit_implied_vs_anbima WHERE codigo='OUT001';
 IF r.confidence<>'divergent' OR NOT r.outlier OR NOT r.thin_trade THEN RAISE EXCEPTION 'OUT001 wrong: %',r; END IF;
 SELECT * INTO r FROM public.credit_implied_vs_anbima WHERE codigo='NOA001';
 IF r.confidence<>'unchecked' OR r.gap_pp IS NOT NULL OR r.outlier THEN RAISE EXCEPTION 'NOA001 wrong: %',r; END IF;
 SELECT * INTO r FROM public.credit_implied_vs_anbima WHERE codigo='PCT001';
 IF r.confidence<>'unchecked' OR r.anbima_rate_pct IS NOT NULL OR r.gap_pp IS NOT NULL THEN RAISE EXCEPTION 'pct_di compared: %',r; END IF;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','silo_api'] LOOP
  IF has_table_privilege(role_name,'public.credit_implied_vs_anbima','SELECT') THEN RAISE EXCEPTION 'view exposed to %',role_name; END IF;
 END LOOP;
END $test$;
ROLLBACK;
