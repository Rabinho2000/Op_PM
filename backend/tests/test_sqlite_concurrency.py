"""Concorrência SQLite: WAL + BEGIN IMMEDIATE evitam `database is locked` (D-0xx).

Usa um ficheiro SQLite próprio (não o da suite) e um motor construído pelo mesmo
`_make_engine` de produção, para validar exatamente a configuração publicada.
"""
from __future__ import annotations

import threading

import pytest
from sqlalchemy import text


@pytest.fixture()
def sqlite_engine(tmp_path, monkeypatch):
    """Motor novo, construído pelo `_make_engine` de produção, sobre um ficheiro próprio."""
    from app import config, db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'burst.db').as_posix()}")
    config.get_settings.cache_clear()
    engine = db._make_engine()
    try:
        yield engine
    finally:
        engine.dispose()
        monkeypatch.undo()
        config.get_settings.cache_clear()


def test_sqlite_engine_uses_wal_and_busy_timeout(sqlite_engine):
    if sqlite_engine.dialect.name != "sqlite":
        pytest.skip("só aplicável a SQLite")
    with sqlite_engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL


def test_read_then_write_burst_does_not_lock(sqlite_engine):
    """12 threads a fazer ler→escrever (o padrão do PATCH de subtarefas)."""
    if sqlite_engine.dialect.name != "sqlite":
        pytest.skip("só aplicável a SQLite")
    with sqlite_engine.begin() as conn:
        conn.execute(text("create table counter(id integer primary key, n integer)"))
        conn.execute(text("insert into counter values (1, 0)"))

    errors: list[str] = []
    done = 0
    guard = threading.Lock()

    def work() -> None:
        nonlocal done
        for _ in range(20):
            try:
                with sqlite_engine.begin() as conn:
                    n = conn.execute(text("select n from counter where id = 1")).scalar_one()
                    conn.execute(text("update counter set n = :n where id = 1"), {"n": n + 1})
                with guard:
                    done += 1
            except Exception as exc:  # noqa: BLE001 - queremos ver qualquer falha
                with guard:
                    errors.append(f"{type(exc).__name__}: {exc}"[:120])

    threads = [threading.Thread(target=work) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with sqlite_engine.connect() as conn:
        final = conn.execute(text("select n from counter")).scalar_one()
    assert errors == []
    assert done == 240
    assert final == 240  # nenhuma escrita perdida


def test_readers_do_not_block_writer_and_see_consistent_data(sqlite_engine):
    if sqlite_engine.dialect.name != "sqlite":
        pytest.skip("só aplicável a SQLite")
    with sqlite_engine.begin() as conn:
        conn.execute(text("create table t(id integer primary key, v integer)"))
        conn.execute(text("insert into t values (1, 0)"))

    failures: list[str] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                with sqlite_engine.connect().execution_options(sqlite_read_only=True) as conn:
                    with conn.begin():
                        conn.execute(text("select v from t where id = 1")).scalar_one()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"leitor: {exc}"[:120])

    readers = [threading.Thread(target=reader) for _ in range(6)]
    for thread in readers:
        thread.start()
    try:
        for i in range(1, 51):
            with sqlite_engine.begin() as conn:
                conn.execute(text("update t set v = :v where id = 1"), {"v": i})
    except Exception as exc:  # noqa: BLE001
        failures.append(f"escritor: {exc}"[:120])
    finally:
        stop.set()
        for thread in readers:
            thread.join()

    assert failures == []
    with sqlite_engine.connect() as conn:
        assert conn.execute(text("select v from t")).scalar_one() == 50
