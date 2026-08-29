"""The Postgres connection pool: waiting, discarding, and actual parallelism.

_PgClient was one connection behind an RLock — correct, but it capped the whole
ingest at a single writer. It is now a ThreadedConnectionPool, which changes
three things that can go wrong silently:

  1. psycopg2's getconn() *raises* when the pool is exhausted instead of
     waiting, so a busy moment would kill an ingest slice;
  2. a connection returned after an error is still in a failed state, so
     putting it straight back deals the same broken connection to the next
     caller;
  3. holding a checkout longer than the statement it serves deadlocks the pool.

Offline: psycopg2.pool is stubbed. The real end-to-end behaviour is exercised
against an ephemeral Postgres separately (see the PR).
"""

from __future__ import annotations

import threading
import time

import pytest

import src.store.pg_client as pg


class FakeConn:
    _seq = 0

    def __init__(self):
        FakeConn._seq += 1
        self.id = FakeConn._seq
        self.autocommit = False
        self.closed = False
        self.cursors = 0

    def cursor(self):
        self.cursors += 1
        return FakeCursor(self)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False

    def execute(self, *a, **k):
        pass

    def close(self):
        self.closed = True


class FakePool:
    """Mimics ThreadedConnectionPool, including its raise-when-exhausted."""

    def __init__(self, minconn, maxconn, dsn=None, **kwargs):
        self.maxconn = maxconn
        self.dsn = dsn
        self.connect_kwargs = kwargs
        self._free = [FakeConn() for _ in range(minconn)]
        self._out = 0
        self._made = minconn
        self.closed_conns = []
        self.returned_conns = []
        self._lock = threading.Lock()

    def getconn(self):
        with self._lock:
            if self._out >= self.maxconn:
                raise pg.psycopg2.pool.PoolError("connection pool exhausted")
            self._out += 1
            if self._free:
                return self._free.pop()
            self._made += 1
            return FakeConn()

    def putconn(self, conn, close=False):
        with self._lock:
            self._out -= 1
            self.returned_conns.append((conn.id, close))
            if close:
                conn.closed = True
                self.closed_conns.append(conn.id)
            else:
                self._free.append(conn)

    def closeall(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pg.psycopg2.pool, "ThreadedConnectionPool", FakePool)
    monkeypatch.delenv("CVM_DB_POOL_SIZE", raising=False)
    return pg._PgClient("postgresql://stub", pool_size=3)


class TestPoolSizing:
    def test_defaults_to_four_not_max_connections(self, monkeypatch):
        monkeypatch.delenv("CVM_DB_POOL_SIZE", raising=False)
        assert pg._get_pool_size() == pg._DEFAULT_POOL_SIZE == 4

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("CVM_DB_POOL_SIZE", "8")
        assert pg._get_pool_size() == 8

    @pytest.mark.parametrize("bad", ["nonsense", "0", "-3", ""])
    def test_bad_values_fall_back_to_the_default(self, monkeypatch, bad):
        monkeypatch.setenv("CVM_DB_POOL_SIZE", bad)
        assert pg._get_pool_size() == pg._DEFAULT_POOL_SIZE


class TestCheckout:
    def test_yields_a_usable_cursor_and_sets_autocommit(self, client):
        with client.cursor() as cur:
            assert cur.conn.autocommit is True
        assert cur.closed

    def test_connection_is_returned_alive_on_success(self, client):
        with client.cursor() as cur:
            conn_id = cur.conn.id
        assert (conn_id, False) in client._pool.returned_conns
        assert conn_id not in client._pool.closed_conns

    def test_concurrent_checkouts_get_distinct_connections(self, client):
        seen, barrier = [], threading.Barrier(3)

        def worker():
            with client.cursor() as cur:
                seen.append(cur.conn.id)
                barrier.wait(timeout=5)   # all three hold a checkout at once

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(seen) == 3
        assert len(set(seen)) == 3, f"connections were shared: {seen}"

    def test_exhaustion_waits_instead_of_raising(self, client):
        # psycopg2 raises PoolError when every connection is out. A slice dying
        # because the pool was momentarily busy is a fabricated failure, so the
        # semaphore has to turn that into a wait.
        release = threading.Event()
        started = threading.Barrier(4)   # 3 holders + main
        result = {}

        def holder():
            with client.cursor():
                started.wait(timeout=5)
                release.wait(timeout=5)

        holders = [threading.Thread(target=holder) for _ in range(3)]
        for t in holders:
            t.start()
        started.wait(timeout=5)          # pool is now fully checked out

        def fourth():
            try:
                with client.cursor() as cur:
                    result["got"] = cur.conn.id
            except Exception as exc:      # noqa: BLE001 - recorded, asserted below
                result["error"] = exc

        t4 = threading.Thread(target=fourth)
        t4.start()
        t4.join(timeout=0.3)
        assert t4.is_alive(), "the fourth caller should be waiting, not finished"
        assert "error" not in result, f"pool raised instead of waiting: {result}"

        release.set()
        for t in holders:
            t.join(timeout=5)
        t4.join(timeout=5)
        assert "error" not in result
        assert "got" in result

    def test_a_failed_connection_is_discarded_not_reused(self, client):
        with pytest.raises(RuntimeError, match="boom"):
            with client.cursor() as cur:
                bad_id = cur.conn.id
                raise RuntimeError("boom")

        assert (bad_id, True) in client._pool.returned_conns
        assert bad_id in client._pool.closed_conns, (
            "a connection left in a failed state was handed back to the pool"
        )

        # And the next caller gets a different, live one.
        with client.cursor() as cur:
            assert cur.conn.id != bad_id
            assert cur.conn.closed is False

    def test_slot_is_released_even_when_the_body_raises(self, client):
        for _ in range(10):
            with pytest.raises(ValueError):
                with client.cursor():
                    raise ValueError("x")
        # If the semaphore leaked a slot per failure the pool would be dead by
        # now; this must still complete.
        with client.cursor() as cur:
            assert cur is not None

    def test_slot_is_released_when_getconn_itself_fails(self, client, monkeypatch):
        def boom():
            raise pg.psycopg2.pool.PoolError("nope")

        monkeypatch.setattr(client._pool, "getconn", boom)
        for _ in range(5):
            with pytest.raises(pg.psycopg2.pool.PoolError):
                with client.cursor():
                    pass
        # Semaphore fully restored: all 3 slots still available.
        assert client._slots._value == 3


class TestParallelism:
    def test_writes_actually_overlap(self, client):
        """The point of the pool: N slices write at once, not one at a time.

        With the old single-connection RLock these bodies serialised, so total
        wall time was N x hold. Overlapping means the pool is doing its job.
        """
        hold = 0.15
        n = 3
        started = time.monotonic()

        def worker():
            with client.cursor():
                time.sleep(hold)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        elapsed = time.monotonic() - started
        assert elapsed < hold * n * 0.8, (
            f"{n} checkouts took {elapsed:.3f}s — serialised rather than parallel"
        )


class TestReconnectContract:
    def test_reconnect_is_safe_and_does_not_disturb_the_pool(self, client):
        # upsert_rows() still calls it between retry attempts. With a pool the
        # failed connection is already discarded by cursor(), so this must be a
        # harmless marker rather than something that tears the pool down.
        before = len(client._pool.returned_conns)
        client.reconnect()
        assert len(client._pool.returned_conns) == before
        with client.cursor() as cur:
            assert cur is not None


class TestKeepalives:
    def test_pool_enables_tcp_keepalives(self, client):
        """Idle pooled sockets must not wait for the kernel's 2h default.

        Run 33237536770 died on `SSL SYSCALL error: EOF detected` after the
        B3 events fetch left the pool idle ~12 min and the session pooler
        had already dropped the socket.
        """
        kw = client._pool.connect_kwargs
        assert kw["keepalives"] == 1
        assert kw["keepalives_idle"] == 30
        assert kw["keepalives_interval"] == 10
        assert kw["keepalives_count"] == 3
