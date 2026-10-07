-- Run THROUGH scripts/guard_noop_ddl.py before psql, like the schema action.
BEGIN;
CREATE TEMP TABLE guard_replay_rows (a text, b text);
ALTER TABLE guard_replay_rows ADD CONSTRAINT guard_old_check CHECK (a <> 'forbidden');
ALTER TABLE guard_replay_rows DROP CONSTRAINT IF EXISTS guard_old_check;
ALTER TABLE guard_replay_rows DROP CONSTRAINT IF EXISTS guard_old_check;
CREATE UNIQUE INDEX guard_replay_unique ON guard_replay_rows(a) NULLS NOT DISTINCT;
CREATE TEMP TABLE guard_replay_oid (phase text, index_oid oid);
INSERT INTO guard_replay_oid VALUES ('narrow', 'guard_replay_unique'::regclass);
DROP INDEX IF EXISTS guard_replay_unique;
CREATE UNIQUE INDEX IF NOT EXISTS guard_replay_unique ON guard_replay_rows(a, b) NULLS NOT DISTINCT;
INSERT INTO guard_replay_oid VALUES ('wide', 'guard_replay_unique'::regclass);
DROP INDEX IF EXISTS guard_replay_unique;
CREATE UNIQUE INDEX IF NOT EXISTS guard_replay_unique ON guard_replay_rows(a, b) NULLS NOT DISTINCT;
DO $test$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='guard_replay_rows'::regclass
             AND conname='guard_old_check') THEN
    RAISE EXCEPTION 'required constraint drop did not run';
  END IF;
  IF (SELECT index_oid FROM guard_replay_oid WHERE phase='narrow') =
     (SELECT index_oid FROM guard_replay_oid WHERE phase='wide') THEN
    RAISE EXCEPTION 'required widening did not rebuild';
  END IF;
  IF 'guard_replay_unique'::regclass::oid <>
     (SELECT index_oid FROM guard_replay_oid WHERE phase='wide') THEN
    RAISE EXCEPTION 'identical index was rebuilt';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_index WHERE indexrelid='guard_replay_unique'::regclass
                 AND indnkeyatts=2 AND indisvalid AND indisunique AND indnullsnotdistinct) THEN
    RAISE EXCEPTION 'wrong resulting unique index';
  END IF;
END
$test$;
INSERT INTO guard_replay_rows VALUES ('same','one'), ('same','two'), (NULL,NULL);
DO $test$
BEGIN
  BEGIN
    INSERT INTO guard_replay_rows VALUES (NULL,NULL);
    RAISE EXCEPTION 'NULL uniqueness lost';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END
$test$;
ROLLBACK;
