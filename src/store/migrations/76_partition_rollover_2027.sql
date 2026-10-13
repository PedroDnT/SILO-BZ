-- 76_partition_rollover_2027.sql — the 2027 year partitions (#867).
--
-- cvm_fi_diario, cia_account and b3_cotahist are range-partitioned by year with
-- a `_future` catch-all bound FROM ('2027-01-01') TO (MAXVALUE). A plain
-- CREATE of a `_2027` partition overlaps that bound and Postgres refuses it, so
-- for each table this block, in one transaction (the DO block):
--
--   1. detaches `<t>_future`,
--   2. creates `<t>_2027` FROM ('2027-01-01') TO ('2028-01-01'),
--   3. moves any 2027 rows from `_future` into the parent (they route to _2027),
--   4. deletes them from `_future`,
--   5. re-attaches `_future` FROM ('2028-01-01') TO (MAXVALUE).
--
-- schema.sql and every migration replay on every run, so the block does nothing
-- for a table whose `_2027` partition already exists. On a fresh database
-- schema.sql already bounds cvm_fi_diario_future / b3_cotahist_future from
-- 2028; cia_account_future (migrations/04_cia.sql, historical, not edited)
-- still starts in 2027 there and is re-attached from 2028 here.
--
-- The move is a plain INSERT on purpose. The rows come from a detached
-- partition, so they cannot collide with the parent's unique key; if one ever
-- did, ON CONFLICT DO NOTHING would drop it and the DELETE below would then lose
-- it. Raising aborts the whole block instead, and nothing changes.
--
-- Runbook: docs/reference/DATABASE_MAINTENANCE.md §6.

DO $rollover$
DECLARE
    t       RECORD;
    fut     TEXT;
    y2027   TEXT;
    cols    TEXT;
    moved   BIGINT;
BEGIN
    FOR t IN
        SELECT * FROM (VALUES
            ('cvm_fi_diario', 'dt_comptc'),
            ('cia_account',   'dt_refer'),
            ('b3_cotahist',   'trade_date')
        ) AS v(parent, part_key)
    LOOP
        fut   := t.parent || '_future';
        y2027 := t.parent || '_2027';

        IF to_regclass('public.' || t.parent) IS NULL THEN
            RAISE NOTICE '76: % does not exist; skipping', t.parent;
            CONTINUE;
        END IF;
        IF to_regclass('public.' || y2027) IS NOT NULL THEN
            RAISE NOTICE '76: % already exists; nothing to do', y2027;
            CONTINUE;
        END IF;

        IF to_regclass('public.' || fut) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.%I DETACH PARTITION public.%I',
                           t.parent, fut);
        END IF;

        EXECUTE format(
            'CREATE TABLE public.%I PARTITION OF public.%I '
            'FOR VALUES FROM (%L) TO (%L)',
            y2027, t.parent, '2027-01-01', '2028-01-01');

        IF to_regclass('public.' || fut) IS NOT NULL THEN
            SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum)
              INTO cols
              FROM pg_attribute a
             WHERE a.attrelid = ('public.' || t.parent)::regclass
               AND a.attnum > 0
               AND NOT a.attisdropped
               AND a.attgenerated = '';

            EXECUTE format(
                'INSERT INTO public.%I (%s) SELECT %s FROM public.%I WHERE %I < %L',
                t.parent, cols, cols, fut, t.part_key, '2028-01-01');
            GET DIAGNOSTICS moved = ROW_COUNT;

            EXECUTE format('DELETE FROM public.%I WHERE %I < %L',
                           fut, t.part_key, '2028-01-01');

            EXECUTE format(
                'ALTER TABLE public.%I ATTACH PARTITION public.%I '
                'FOR VALUES FROM (%L) TO (MAXVALUE)',
                t.parent, fut, '2028-01-01');

            RAISE NOTICE '76: created %, moved % row(s) from %, % now starts 2028-01-01',
                y2027, moved, fut, fut;
        ELSE
            RAISE NOTICE '76: created % (no % to re-bound)', y2027, fut;
        END IF;
    END LOOP;
END
$rollover$;
