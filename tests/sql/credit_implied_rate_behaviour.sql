-- Synthetic data only; all writes roll back. api.credit_implied_rate: the
-- calculated rows with their check tags, no ANBIMA rate or gap, refusals,
-- the row cap, and grants.
BEGIN;
INSERT INTO public.b3_credit_capture
(capture_id,source,requested_from,requested_to,observed_at,source_url,payload_sha256,
 raw_csv,status,expected_dates,delivered_dates,missing_dates,source_rows,debenture_rows,dropped_rows)
VALUES ('cccccccc-0000-4000-8000-0000000000a1','b3_bdi_consolidated_records','2001-01-02','2001-01-02',
 '2020-01-01 10:00+00','test://credit',repeat('a',64),'synthetic','complete',
 '["2001-01-02"]'::jsonb,'["2001-01-02"]'::jsonb,'[]'::jsonb,1,0,0);
INSERT INTO public.b3_credit_implied_rate
(codigo,trade_date,settlement_date,trade_classification,method_version,b3_capture_id,pu_brl,quantity,volume_brl,
 trade_count,indexador,forma_remuneracao,contract_rate_pct,implied_rate_pct,rate_basis,flows_used,inputs,solver,computed_at)
SELECT s.code,'2001-01-02','2001-01-02','EXTRAGRUPO','v1','cccccccc-0000-4000-8000-0000000000a1',1000,10,s.vol,
 2,'DI','spread',1,s.imp,'di_spread_aa',3,'{}'::jsonb,'{}'::jsonb,'2020-01-01 11:00+00'
FROM (VALUES ('CHK001',500000,12.00),('OUT001',10000,75.00),('NOA001',500000,12.00)) s(code,vol,imp);
-- 1001 rows for one code on distinct trade dates: the page edge refuses.
INSERT INTO public.b3_credit_implied_rate
(codigo,trade_date,settlement_date,trade_classification,method_version,b3_capture_id,pu_brl,
 indexador,forma_remuneracao,contract_rate_pct,implied_rate_pct,rate_basis,flows_used,inputs,solver,computed_at)
SELECT 'CAPS01','2001-01-02'::date+i,'2001-01-02'::date+i,'EXTRAGRUPO','v1','cccccccc-0000-4000-8000-0000000000a1',
 1000,'DI','spread',1,12,'di_spread_aa',3,'{}'::jsonb,'{}'::jsonb,'2020-01-01 11:00+00'
FROM generate_series(1,1001) i;
INSERT INTO public.anbima_debenture_indicative (codigo,data_referencia,taxa_indicativa_pct,capture_id,observed_at)
VALUES ('CHK001','2001-01-02',11.50,'cccccccc-0000-4000-8000-0000000000b1','2020-01-01 12:00+00'),
       ('OUT001','2001-01-02',15.00,'cccccccc-0000-4000-8000-0000000000b1','2020-01-01 12:00+00');
DO $test$
DECLARE r RECORD; n INT; role_name TEXT;
BEGIN
 SELECT * INTO r FROM api.credit_implied_rate(' chk001 ','2001-01-01','2001-01-31');
 IF r.implied_rate_pct<>12 OR NOT r.is_calculated OR r.confidence<>'checked' OR r.outlier OR r.thin_trade
    OR r.source<>'b3_traded_pu_calculated' OR r.method_version<>'v1' THEN RAISE EXCEPTION 'CHK001 wrong: %',r; END IF;
 SELECT * INTO r FROM api.credit_implied_rate('OUT001','2001-01-01','2001-01-31');
 IF r.confidence<>'divergent' OR NOT r.outlier OR NOT r.thin_trade THEN RAISE EXCEPTION 'OUT001 wrong: %',r; END IF;
 SELECT * INTO r FROM api.credit_implied_rate('NOA001','2001-01-01','2001-01-31');
 IF r.confidence<>'unchecked' OR r.outlier THEN RAISE EXCEPTION 'NOA001 wrong: %',r; END IF;
 -- No ANBIMA number is served.
 IF EXISTS (SELECT 1 FROM unnest(ARRAY['anbima_rate_pct','gap_pp','taxa_indicativa_pct']) c
            WHERE to_jsonb(r) ? c) THEN RAISE EXCEPTION 'ANBIMA field served'; END IF;
 SELECT count(*) INTO n FROM api.credit_implied_rate('CHK001','1999-01-01','1999-02-01');
 IF n<>0 THEN RAISE EXCEPTION 'empty window fabricated'; END IF;
 SELECT count(*) INTO n FROM api.credit_implied_rate('CAPS01','2001-01-02','2001-01-05');
 IF n<>3 THEN RAISE EXCEPTION 'window wrong: %',n; END IF;
 BEGIN PERFORM * FROM api.credit_implied_rate('CAPS01','2001-01-01','2005-01-01'); RAISE EXCEPTION 'cap silently trimmed'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_implied_rate('NOPE01','2001-01-01','2001-01-31'); RAISE EXCEPTION 'unknown accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_implied_rate('bad code','2001-01-01','2001-01-31'); RAISE EXCEPTION 'bad code accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_implied_rate('CHK001',NULL,'2001-01-31'); RAISE EXCEPTION 'null window accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_implied_rate('CHK001','2001-02-01','2001-01-31'); RAISE EXCEPTION 'reverse window accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','silo_api'] LOOP
  IF has_table_privilege(role_name,'public.b3_credit_implied_rate','SELECT')
     OR has_table_privilege(role_name,'public.credit_implied_vs_anbima','SELECT')
     OR has_table_privilege(role_name,'public.anbima_debenture_indicative','SELECT') THEN RAISE EXCEPTION 'tables exposed to %',role_name; END IF;
  IF NOT has_function_privilege(role_name,'api.credit_implied_rate(text,date,date)','EXECUTE') THEN RAISE EXCEPTION 'serving grant missing for %',role_name; END IF;
 END LOOP;
END $test$;
SET LOCAL ROLE anon;
SELECT * FROM api.credit_implied_rate('CHK001','2001-01-01','2001-01-31');
RESET ROLE;
ROLLBACK;
