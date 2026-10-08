BEGIN;
-- Synthetic source rows only; every fixture is rolled back.
INSERT INTO b3_cotahist
(codneg,trade_date,tpmerc,codbdi,prazot,nome_resumido,especi,moeda,
 preco_abertura,preco_maximo,preco_minimo,preco_medio,preco_fechamento,
 oferta_compra,oferta_venda,negocios,quantidade,volume,preco_exercicio,
 data_vencimento,fator_cotacao,isin,raw)
SELECT code,DATE '2026-01-05',market,board,term,'FIELD TEST',spec,'R$',
 10,13,9,11,12,11.5,12.5,7,100,1200,42.25,DATE '2026-03-20',1000,
 'BRZZZZACN000',jsonb_build_object('indopc','7','ptoexe',points,'dismes','007')
FROM (VALUES
 ('ZZZA3','010','88','','ON','0000001234567'),
 ('ZZZA3F','020','96','','ON','0000001234567'),
 ('ZZZA3X','021','93','','ON','0000001234567'),
 ('ZZZA11','010','12','','CI','0000001234567'),
 ('ZZZADR','010','34','','DRN','0000001234567'),
 ('ZZZAUNT','010','02','','UNT','0000001234567'),
 ('ZZZARES','010','58','','CPA','0000001234567'),
 ('ZZZAOPT','070','78','','ON','0000001234567'),
 ('ZZZABAD','070','78','','ON','unreadablexxxx'),
 ('ZZZAPUT','080','82','','ON','0000000000000'),
 ('ZZZAEX','012','38','','ON','0000001234567'),
 ('ZZZAEP','013','42','','ON','0000001234567'),
 ('ZZZAUC','017','50','','ON','0000001234567'),
 ('ZZZATER','030','62','030','ON','0000001234567'),
 ('ZZZATER','030','62','060','ON','0000000000000'),
 ('ZZZATER','030','88','030','ON','0000001234567')
) AS f(code,market,board,term,spec,points);

DO $$
DECLARE r RECORD; j JSONB; n INT; item TEXT;
BEGIN
 SELECT * INTO r FROM api.equities WHERE ticker='ZZZA3X' AND trade_date='2026-01-05';
 ASSERT r.lot='block' AND r.market='021',r;
 SELECT * INTO r FROM api.equities WHERE ticker='ZZZA3F' AND trade_date='2026-01-05';
 ASSERT r.lot='odd',r;
 SELECT * INTO r FROM api.equities WHERE ticker='ZZZA3' AND trade_date='2026-01-05';
 ASSERT r.lot='standard',r;
 SELECT * INTO r FROM api.termo_history('ZZZATER','2026-01-05','2026-01-05')
 WHERE board='62' AND term_days='030';
 ASSERT r.contract_price=42.25 AND r.contract_expiry=DATE '2026-03-20',r;
 ASSERT r.contract_points=1.234567 AND r.contract_points_raw='0000001234567',r;
 ASSERT r.contract_correction='7' AND r.distribution_number='007',r;
 ASSERT r.market='030' AND r.short_name='FIELD TEST' AND r.fetched_at IS NOT NULL,r;
 SELECT count(*) INTO n FROM api.termo_history('ZZZATER','2026-01-05','2026-01-05');
 ASSERT n=3,'board and term natural-key distinctions collapsed';
 SELECT * INTO r FROM api.termo_history('ZZZATER','2026-01-05','2026-01-05') WHERE term_days='060';
 ASSERT r.contract_points IS NULL AND r.contract_points_raw='0000000000000',r;

 SELECT * INTO r FROM api.option_history('ZZZAOPT','2026-01-05','2026-01-05');
 ASSERT r.board='78' AND r.market='070' AND r.strike=42.25,r;
 ASSERT r.strike_points=1.234567 AND r.contract_points_raw='0000001234567',r;
 ASSERT r.term_days='' AND r.short_name='FIELD TEST',r;
 SELECT * INTO r FROM api.option_chain('ZZZA',NULL,'2026-01-05',100) WHERE codneg='ZZZAOPT';
 ASSERT r.average=11 AND r.bid=11.5 AND r.ask=12.5 AND r.quotation_factor=1000,r;
 ASSERT r.currency='R$' AND r.board='78' AND r.market='070',r;
 SELECT * INTO r FROM api.option_history('ZZZABAD','2026-01-05','2026-01-05');
 ASSERT r.strike_points IS NULL AND r.contract_points_raw='unreadablexxxx',r;
 SELECT * INTO r FROM api.option_history('ZZZAPUT','2026-01-05','2026-01-05');
 ASSERT r.strike_points IS NULL AND r.contract_points_raw='0000000000000',r;
 SELECT * INTO r FROM api.option_exercises('ZZZA','2026-01-05','2026-01-05') WHERE codneg='ZZZAEX';
 ASSERT r.exercise_price=12 AND r.open=10 AND r.average=11,r;
 ASSERT r.contract_points=1.234567 AND r.contract_correction='7' AND r.distribution_number='007',r;

 FOREACH item IN ARRAY ARRAY['quotes','equities','bdrs','units','fund_quotas','cash_securities','auctions'] LOOP
  EXECUTE format('SELECT * FROM api.%I WHERE trade_date=DATE ''2026-01-05'' AND ticker LIKE ''ZZZA%%'' LIMIT 1',item) INTO r;
  ASSERT r.market IS NOT NULL AND r.contract_price=42.25 AND r.contract_points=1.234567,item;
  ASSERT r.contract_correction='7' AND r.distribution_number='007',item;
 END LOOP;
 SELECT * INTO r FROM api.quote_latest('ZZZA3');
 ASSERT r.market='010' AND r.board='88' AND r.distribution_number='007',r;
 SELECT q INTO j FROM api.quote_history('ZZZA3','2026-01-05','2026-01-05',NULL,NULL,
 ARRAY['close','market','term_days','contract_price','contract_expiry','contract_points',
       'contract_points_raw','contract_correction','distribution_number','fetched_at']) q;
 ASSERT j->>'board' IS NULL,'unselected fields leaked';
 ASSERT j->>'market'='010' AND (j->>'contract_points')::numeric=1.234567,j;
 ASSERT j->>'contract_points_raw'='0000001234567' AND j->>'distribution_number'='007',j;
 ASSERT api.catalog()->'cotahist'->'codbdi'->'34'->'description'='null'::jsonb,
        'undocumented reference code was given an invented label';
 ASSERT api.catalog()->'cotahist'->>'reference_date'='2020-10-05';
END $$;

-- The existing page refusal survives the widened output shape.
INSERT INTO b3_cotahist(codneg,trade_date,tpmerc,codbdi,prazot,preco_fechamento,raw)
SELECT 'ZZZACAP',d::date,'030','62','030',10,'{}'::jsonb
FROM generate_series(DATE '2020-01-01',DATE '2022-09-27',INTERVAL '1 day') d;
DO $$ BEGIN
 BEGIN
  PERFORM * FROM api.termo_history('ZZZACAP','2020-01-01','2022-09-27');
  RAISE EXCEPTION 'over-cap output silently trimmed';
 EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
 END;
END $$;
SET ROLE anon;
SELECT market,board,contract_price FROM api.termo_history('ZZZATER','2026-01-05','2026-01-05');
DO $$ BEGIN
 BEGIN
  PERFORM * FROM public.b3_cotahist LIMIT 1;
  RAISE EXCEPTION 'private landing table became public';
 EXCEPTION WHEN insufficient_privilege THEN NULL;
 END;
END $$;
RESET ROLE;
ROLLBACK;
