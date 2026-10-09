-- Synthetic data only; no retained market records, all writes roll back.
BEGIN;
INSERT INTO public.b3_credit_capture
(capture_id,source,requested_from,requested_to,observed_at,source_url,payload_sha256,
 raw_csv,status,expected_dates,delivered_dates,missing_dates,source_rows,debenture_rows,dropped_rows)
SELECT ('cccccccc-0000-4000-8000-' || lpad(i::text,12,'0'))::uuid,
 'b3_bdi_consolidated_records','2001-01-02','2001-01-02',
 ('2020-01-0' || CASE WHEN i=5 THEN 8 ELSE i END || ' 10:00+00')::timestamptz,'test://credit',repeat('a',64),'synthetic',
 CASE WHEN i=3 THEN 'incomplete' ELSE 'complete' END,
 '["2001-01-02"]'::jsonb,'["2001-01-02"]'::jsonb,
 CASE WHEN i=3 THEN '["2001-01-02"]'::jsonb ELSE '[]'::jsonb END,1,0,0
FROM generate_series(1,5) i;
-- Snapshot 1 has two settlements and two classifications; snapshot 2 REMOVES KEEP01.
INSERT INTO public.fact_credit_market
(capture_id,source,instrument_code,trade_date,settlement_date,trade_classification,
 isin,issuer_name,metric,unit,value,row_sha256)
SELECT ('cccccccc-0000-4000-8000-' || lpad(s.i::text,12,'0'))::uuid,
 'b3_bdi_consolidated_records',s.code,'2001-01-02', '2001-01-02'::date+s.days,
 s.classification,'BRTESTDB0001','Synthetic issuer',m.metric,m.unit,
 CASE WHEN m.metric='reference_price' THEN NULL ELSE s.amount END,repeat('b',64)
FROM (VALUES (1,'KEEP01',0,'EXTRAGRUPO',10),(1,'KEEP01',1,'EXTRAGRUPO',20),
 (1,'KEEP01',0,'INTRAGRUPO',30),(1,'OTHR01',0,'EXTRAGRUPO',40),
 (2,'OTHR01',0,'EXTRAGRUPO',50),(3,'KEEP01',0,'EXTRAGRUPO',999),
 (4,'KEEP01',0,'EXTRAGRUPO',60)) s(i,code,days,classification,amount)
CROSS JOIN (VALUES ('quantity','units'),('min_price','BRL/unit'),('avg_price','BRL/unit'),
 ('max_price','BRL/unit'),('last_price','BRL/unit'),('reference_price','BRL/unit'),
 ('trade_count','trades'),('volume_brl','BRL'),('oscillation_pct','percent')) m(metric,unit);
-- 1001 distinct groups on a single date prove a date-only cap cannot trim groups.
INSERT INTO public.fact_credit_market
(capture_id,source,instrument_code,trade_date,settlement_date,trade_classification,
 metric,unit,value,row_sha256)
SELECT 'cccccccc-0000-4000-8000-000000000005','b3_bdi_consolidated_records','CAPS01',
 '2001-01-02','2001-01-02'::date+i,'EXTRAGRUPO',m.metric,m.unit,1,repeat('c',64)
FROM generate_series(1,1001) i CROSS JOIN
 (VALUES ('quantity','units'),('min_price','BRL/unit'),('avg_price','BRL/unit'),
 ('max_price','BRL/unit'),('last_price','BRL/unit'),('reference_price','BRL/unit'),
 ('trade_count','trades'),('volume_brl','BRL'),('oscillation_pct','percent')) m(metric,unit);
UPDATE public.b3_credit_capture c SET debenture_rows=(SELECT count(*)/9 FROM public.fact_credit_market f WHERE f.capture_id=c.capture_id)
WHERE c.capture_id::text LIKE 'cccccccc-0000-4000-8000-%';
INSERT INTO public.cvm_ingest_log(run_id,entity,doc_type,status,rows_upserted,started_at,finished_at)
SELECT c.capture_id,'b3','credit_consolidated','ok',c.debenture_rows*9,
 c.observed_at-interval '1 minute',c.observed_at+CASE WHEN c.capture_id::text LIKE '%000004' THEN interval '2 days' ELSE interval '1 minute' END
FROM public.b3_credit_capture c WHERE c.capture_id::text LIKE 'cccccccc-0000-4000-8000-%';
DO $test$
DECLARE n INT; amount NUMERIC; role_name TEXT; bad TEXT;
BEGIN
 SELECT count(*),sum(volume_brl) INTO n,amount FROM api.credit_market_history(' keep01 ','2001-01-02','2001-01-02','2020-01-01 11:00+00');
 IF n<>3 OR amount<>60 THEN RAISE EXCEPTION 'full grain lost: %/%',n,amount; END IF;
 IF EXISTS (SELECT 1 FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','2020-01-01 11:00+00') WHERE reference_price IS NOT NULL OR units->>'volume_brl'<>'BRL') THEN RAISE EXCEPTION 'NULL or units changed'; END IF;
 SELECT count(*) INTO n FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','2020-01-02 11:00+00');
 IF n<>0 THEN RAISE EXCEPTION 'removed instrument resurrected'; END IF;
 SELECT count(*) INTO n FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','2020-01-04 11:00+00');
 IF n<>0 THEN RAISE EXCEPTION 'partial or unfinished capture accepted'; END IF;
 -- Late audit is still too late at the prior cutoff; at completion it becomes eligible.
 SELECT count(*),sum(volume_brl) INTO n,amount FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','2020-01-07 11:00+00');
 -- Snapshot 4 becomes visible only after its audit finishes; snapshot 5 later removes it.
 IF n<>1 OR amount<>60 THEN RAISE EXCEPTION 'late audit availability violated'; END IF;
 SELECT count(*) INTO n FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','2020-01-08 11:00+00');
 IF n<>0 THEN RAISE EXCEPTION 'global snapshot selection violated'; END IF;
 SELECT count(*) INTO n FROM api.credit_market_history('OTHR01','1999-01-01','1999-02-01','2020-01-02 11:00+00');
 IF n<>0 THEN RAISE EXCEPTION 'empty window fabricated'; END IF;
 BEGIN PERFORM * FROM api.credit_market_history('CAPS01','2001-01-02','2001-01-02','2020-01-05 09:00+00'); RAISE EXCEPTION 'future code recognized'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_market_history('CAPS01','2001-01-02','2001-01-02','2020-01-08 11:00+00'); RAISE EXCEPTION 'cap silently trimmed'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_market_history('NOPE01','2001-01-02','2001-01-02'); RAISE EXCEPTION 'unknown accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_market_history('KEEP01',NULL,'2001-01-02'); RAISE EXCEPTION 'null window accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_market_history('KEEP01','2001-01-03','2001-01-02'); RAISE EXCEPTION 'reverse window accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02',NULL); RAISE EXCEPTION 'null cutoff accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 BEGIN PERFORM * FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','infinity'); RAISE EXCEPTION 'infinite cutoff accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated','silo_api'] LOOP
 IF has_table_privilege(role_name,'public.b3_credit_capture','SELECT') OR has_table_privilege(role_name,'public.fact_credit_market','SELECT') THEN RAISE EXCEPTION 'landing exposed'; END IF;
 IF NOT has_function_privilege(role_name,'api.credit_market_history(text,date,date,timestamptz)','EXECUTE') THEN RAISE EXCEPTION 'serving grant missing'; END IF;
 END LOOP;
END $test$;
SET LOCAL ROLE anon;
SELECT * FROM api.credit_market_history('KEEP01','2001-01-02','2001-01-02','2020-01-01 11:00+00');
RESET ROLE;
ROLLBACK;
