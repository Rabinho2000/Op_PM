"""Testes da cópia SQLite -> PostgreSQL (`app.cli.migrate_sqlite_to_postgres`).

A origem é sintética: o esquema vem de `alembic upgrade head` sobre um SQLite
temporário e os dados do seed de desenvolvimento + demonstração (nada real).
O destino é uma base PostgreSQL descartável, criada a partir de um modelo
(`CREATE DATABASE ... TEMPLATE`) já migrado por Alembic.

Os testes que precisam de PostgreSQL são saltados se não houver servidor:
- `OPPM_TEST_PG_ADMIN_URL` (preferido), ou
- `DATABASE_URL` quando já aponta para PostgreSQL (job `backend-postgres` do CI).
O utilizador tem de poder fazer `CREATE DATABASE`. Local, por exemplo:

    docker run -d --rm --name pg-test -e POSTGRES_PASSWORD=x -p 127.0.0.1:55432:5432 postgres:16-alpine
    OPPM_TEST_PG_ADMIN_URL=postgresql+psycopg://postgres:x@127.0.0.1:55432/postgres pytest tests/test_migrate_sqlite_to_postgres.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Column, Date, DateTime, Integer, MetaData, Numeric, String, Table, Boolean, text
from sqlalchemy import JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.cli import migrate_sqlite_to_postgres as mig
from app.cli.migrate_sqlite_to_postgres import (
    ConvertError,
    CopyRefused,
    build_converter,
    canonical,
    main,
    run_copy,
    verify_only,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Conversões (não precisam de PostgreSQL)
# --------------------------------------------------------------------------


def _converter(type_, nullable=True):
    metadata = MetaData()
    table = Table("t_unit", metadata, Column("c", type_, nullable=nullable))
    return build_converter(table.c.c)


def test_convert_uuid_and_rejects_garbage():
    conv = _converter(PG_UUID(as_uuid=True))
    value = uuid.uuid4()
    assert conv(str(value)) == value
    with pytest.raises(ConvertError, match="uuid_invalido"):
        conv("não-é-uuid")


def test_convert_booleans_only_zero_or_one():
    conv = _converter(Boolean())
    assert conv(1) is True and conv(0) is False
    with pytest.raises(ConvertError, match="booleano_invalido"):
        conv(2)
    with pytest.raises(ConvertError, match="booleano_invalido"):
        conv("true")


def test_convert_naive_datetime_is_utc_and_aware_is_kept():
    conv = _converter(DateTime(timezone=True))
    assert conv("2026-11-18 10:30:00") == datetime(2026, 11, 18, 10, 30, tzinfo=timezone.utc)
    assert conv("2026-11-18 10:30:00.123456").microsecond == 123456
    assert conv("2026-11-18T10:30:00+01:00").utcoffset().total_seconds() == 3600
    with pytest.raises(ConvertError, match="datetime_invalido"):
        conv("ontem")


def test_convert_date_rejects_datetime_text():
    conv = _converter(Date())
    assert conv("2026-11-18") == date(2026, 11, 18)
    with pytest.raises(ConvertError, match="data_invalida"):
        conv("2026-11-18 10:00:00")


def test_convert_json_distinguishes_sql_null_from_json_null():
    conv = _converter(JSON())
    assert conv(None) is None
    assert conv("null") is mig.JSON_NULL
    assert conv('{"a": [1, 2.5, "x"]}') == {"a": [1, 2.5, "x"]}
    with pytest.raises(ConvertError, match="json_invalido"):
        conv("{não é json")
    with pytest.raises(ConvertError, match="json_invalido"):
        conv("NaN")


def test_convert_numeric_scale_precision_and_ints():
    conv = _converter(Numeric(10, 2))
    assert conv(5) == Decimal(5)
    assert conv(12.5) == Decimal("12.5")
    with pytest.raises(ConvertError, match="numeric_perderia_casas_decimais"):
        conv(0.1 + 0.2)
    with pytest.raises(ConvertError, match="numeric_excede_precisao"):
        conv(10**8)


def test_convert_varchar_length_nul_and_not_null():
    conv = _converter(String(5), nullable=False)
    assert conv("12345") == "12345"
    with pytest.raises(ConvertError, match="excede_varchar_5"):
        conv("123456")
    with pytest.raises(ConvertError, match="caractere_nul_no_texto"):
        conv("a\x00b")
    with pytest.raises(ConvertError, match="null_em_coluna_not_null"):
        conv(None)


def test_convert_int_range():
    conv = _converter(Integer())
    assert conv(2**31 - 1) == 2**31 - 1
    with pytest.raises(ConvertError, match="inteiro_fora_de_intervalo"):
        conv(2**31)


def test_canonical_is_equal_for_equivalent_values():
    assert canonical("numeric", Decimal("12.50")) == canonical("numeric", Decimal("12.5"))
    assert canonical("datetime", datetime(2026, 1, 1, 12, tzinfo=timezone.utc)) == canonical(
        "datetime", datetime.fromisoformat("2026-01-01T13:00:00+01:00")
    )
    assert canonical("json", {"b": 1, "a": 2}) == canonical("json", {"a": 2, "b": 1})
    assert canonical("json", mig.JSON_NULL) != canonical("json", None)


def test_self_references_are_ordered_parent_first():
    metadata = MetaData()
    table = Table(
        "tree",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("tree.id"), nullable=True),
    )
    rows = [{"id": 3, "parent_id": 2}, {"id": 2, "parent_id": 1}, {"id": 1, "parent_id": None}, {"id": 4, "parent_id": 99}]
    ordered = mig._order_self_references(table, ["id", "parent_id"], rows)
    position = {r["id"]: i for i, r in enumerate(ordered)}
    assert position[1] < position[2] < position[3]
    assert len(ordered) == 4


def test_self_reference_cycle_is_detected():
    metadata = MetaData()
    table = Table(
        "loop",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("loop.id"), nullable=True),
    )
    with pytest.raises(mig.CopyFailed, match="ciclo"):
        mig._order_self_references(table, ["id", "parent_id"], [{"id": 1, "parent_id": 2}, {"id": 2, "parent_id": 1}])


def test_refuses_non_postgres_target(tmp_path):
    source = tmp_path / "s.db"
    sqlite3.connect(source).close()
    with pytest.raises(CopyRefused, match="PostgreSQL"):
        run_copy(str(source), f"sqlite:///{tmp_path / 'd.db'}")


def test_refuses_missing_source(tmp_path):
    with pytest.raises(CopyRefused, match="inexistente"):
        mig.open_source(str(tmp_path / "nao_existe.db"))


# --------------------------------------------------------------------------
# Com PostgreSQL
# --------------------------------------------------------------------------


def _admin_url() -> str | None:
    explicit = os.environ.get("OPPM_TEST_PG_ADMIN_URL")
    if explicit:
        return explicit
    current = os.environ.get("DATABASE_URL", "")
    return current if current.startswith("postgresql") else None


def _with_database(admin_url: str, database: str) -> str:
    return make_url(admin_url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def pg_admin():
    url = _admin_url()
    if not url:
        pytest.skip("sem PostgreSQL disponível (OPPM_TEST_PG_ADMIN_URL ou DATABASE_URL postgresql)")
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL inacessível: {type(exc).__name__}")
    yield engine, url
    engine.dispose()


def _subprocess_env(database_url: str, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"EXPECTED_DB_DIALECT", "SECRET_KEY_FILE", "DATABASE_URL_FILE"}}
    env.update({"DATABASE_URL": database_url, "APP_ENV": "local", "PYTHONPATH": str(BACKEND_DIR)})
    env.update(extra)
    return env


def _run(args: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(args, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.fixture(scope="module")
def synthetic_source(tmp_path_factory) -> Path:
    """SQLite migrado por Alembic e populado com os dados sintéticos do seed."""
    folder = tmp_path_factory.mktemp("sqlite_src")
    path = folder / "synthetic.db"
    env = _subprocess_env(f"sqlite:///{path.as_posix()}", GRAPH_FALLBACK_DIR=str(folder / "outbox"))
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
    seed = (
        "from app.db import SessionLocal;"
        "from app.migration.seed_dev import run_seed;"
        "from app.migration.seed_demo import seed_demo_data;"
        "run_seed();"
        "db = SessionLocal(); seed_demo_data(db); db.commit(); db.close()"
    )
    _run([sys.executable, "-c", seed], env)
    # Checkpoint do WAL para o ficheiro único.
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture(scope="module")
def pg_template(pg_admin):
    """Base PostgreSQL migrada por Alembic, usada como modelo."""
    engine, admin_url = pg_admin
    name = f"oppm_tpl_{uuid.uuid4().hex[:10]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _with_database(admin_url, name)
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], _subprocess_env(url))
    yield name
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture()
def target(pg_admin, pg_template):
    engine, admin_url = pg_admin
    name = f"oppm_cp_{uuid.uuid4().hex[:10]}"
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{pg_template}"'))
    url = _with_database(admin_url, name)
    yield url
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture()
def source_copy(synthetic_source, tmp_path) -> Path:
    path = tmp_path / "copy.db"
    shutil.copy(synthetic_source, path)
    return path


def _scalar(url: str, sql: str):
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql)).scalar()
    finally:
        engine.dispose()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_full_copy_is_verified_and_committed(source_copy, target):
    before = _sha(source_copy)
    report = run_copy(str(source_copy), target)
    assert report.committed and report.verified and not report.issues
    assert report.tables and all(t.ok for t in report.tables.values())
    assert sum(t.source_rows for t in report.tables.values()) > 500  # o seed é não trivial
    assert "alembic_version" not in report.tables
    # as tabelas semeadas pelas migrações foram substituídas pelas da origem
    assert report.truncated_seed_tables
    # os dados chegaram mesmo ao PostgreSQL
    src = sqlite3.connect(f"file:{source_copy}?mode=ro", uri=True)
    expected = src.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    src.close()
    assert expected > 0
    assert _scalar(target, "SELECT COUNT(*) FROM users") == expected
    assert _scalar(target, "SELECT version_num FROM alembic_version") == report.source_revision
    # a origem não foi tocada
    assert _sha(source_copy) == before
    # e a verificação independente confirma
    assert verify_only(str(source_copy), target).verified


def test_dry_run_leaves_target_untouched(source_copy, target):
    seeded_before = _scalar(target, "SELECT COUNT(*) FROM permissions")
    report = run_copy(str(source_copy), target, dry_run=True)
    assert report.verified and not report.committed
    assert _scalar(target, "SELECT COUNT(*) FROM users") == 0
    assert _scalar(target, "SELECT COUNT(*) FROM permissions") == seeded_before


def test_refuses_non_empty_target_unless_explicit(source_copy, target):
    run_copy(str(source_copy), target)
    with pytest.raises(CopyRefused, match="dados"):
        run_copy(str(source_copy), target)
    again = run_copy(str(source_copy), target, replace_existing=True)
    assert again.committed and again.verified


def test_refuses_different_revisions(source_copy, target):
    conn = sqlite3.connect(source_copy)
    conn.execute("UPDATE alembic_version SET version_num='000000000000'")
    conn.commit()
    conn.close()
    with pytest.raises(CopyRefused, match="revisões"):
        run_copy(str(source_copy), target)
    assert _scalar(target, "SELECT COUNT(*) FROM users") == 0


def _sqlite_exec(path: Path, *statements: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA ignore_check_constraints=ON")
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def test_detects_rows_postgres_would_reject_without_leaking_content(source_copy, target, capsys):
    secret = "segredo-que-nao-pode-aparecer"
    _sqlite_exec(
        source_copy,
        # VARCHAR(320) excedido
        f"UPDATE users SET email = '{secret}' || printf('%0400d', 1) WHERE rowid = (SELECT MIN(rowid) FROM users)",
        # booleano fora de 0/1
        "UPDATE people SET is_active = 2 WHERE rowid = (SELECT MIN(rowid) FROM people)",
        # NUL no texto
        "UPDATE people SET legacy_ref = 'a' || char(0) || 'b' WHERE rowid = (SELECT MAX(rowid) FROM people)",
        # chave estrangeira órfã
        "UPDATE user_roles SET user_id = '00000000-0000-4000-8000-000000000001' WHERE rowid = (SELECT MIN(rowid) FROM user_roles)",
    )
    with pytest.raises(CopyRefused) as excinfo:
        run_copy(str(source_copy), target)
    report = excinfo.value.report
    assert report is not None
    keys = set(report.issues)
    assert ("users", "email", "excede_varchar_320") in keys
    assert ("people", "is_active", "booleano_invalido") in keys
    assert ("people", "legacy_ref", "caractere_nul_no_texto") in keys
    assert ("user_roles", "user_id", "fk_orfa_para_users") in keys
    assert all(n >= 1 for n in report.issues.values())
    assert _scalar(target, "SELECT COUNT(*) FROM users") == 0  # nada foi gravado

    # o CLI recusa (código 2) e o relatório impresso não contém o conteúdo
    code = main(["--source", str(source_copy), "--target-url", target, "--dry-run"])
    captured = capsys.readouterr()
    assert code == 2
    assert secret not in captured.out + captured.err
    assert "excede_varchar_320" in captured.out


def test_dry_run_counts_what_only_the_engine_can_judge(source_copy, target):
    """CHECK que o SQLite deixou passar: só o PostgreSQL o consegue avaliar."""
    _sqlite_exec(
        source_copy,
        "UPDATE projects SET installer_id = NULL, "
        "installer_team_id = (SELECT id FROM installer_teams LIMIT 1) "
        "WHERE rowid = (SELECT MIN(rowid) FROM projects) AND EXISTS (SELECT 1 FROM installer_teams)",
    )
    conn = sqlite3.connect(source_copy)
    violated = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE installer_team_id IS NOT NULL AND installer_id IS NULL"
    ).fetchone()[0]
    conn.close()
    if not violated:
        pytest.skip("o seed não tem equipas de instaladores para provocar o CHECK")
    report = run_copy(str(source_copy), target, dry_run=True)
    assert not report.committed and not report.verified
    assert any(table == "projects" and "ck_project_team_needs_installer" in detail for table, _s, detail in report.engine_rejections)
    assert _scalar(target, "SELECT COUNT(*) FROM projects") == 0
    # sem --dry-run a cópia real falha e deixa o destino intocado
    with pytest.raises(mig.CopyFailed, match="rejeitou"):
        run_copy(str(source_copy), target)
    assert _scalar(target, "SELECT COUNT(*) FROM projects") == 0


def test_checksum_detects_a_changed_value(source_copy, target):
    run_copy(str(source_copy), target)
    engine = create_engine(target)
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET email = email || 'x' WHERE id = (SELECT id FROM users LIMIT 1)"))
    engine.dispose()
    report = verify_only(str(source_copy), target)
    assert not report.verified
    assert [n for n, t in report.tables.items() if not t.ok] == ["users"]
    assert report.tables["users"].source_rows == report.tables["users"].target_rows  # contagem igual, checksum diferente


def test_cli_dry_run_and_json_report(source_copy, target, tmp_path, capsys):
    report_file = tmp_path / "relatorio.json"
    code = main(["--source", str(source_copy), "--target-url", target, "--dry-run", "--report", str(report_file)])
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY-RUN" in out and "Verificação: OK" in out
    assert oct(report_file.stat().st_mode & 0o777) == "0o600"
    import json

    data = json.loads(report_file.read_text())
    assert data["verified"] is True and data["dry_run"] is True


def test_sequences_are_adjusted(pg_admin, target):
    engine = create_engine(target)
    metadata = MetaData()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE seq_probe (id serial PRIMARY KEY, note text)"))
        conn.execute(text("INSERT INTO seq_probe (id, note) VALUES (41, 'a'), (42, 'b')"))
        metadata.reflect(bind=conn, only=["seq_probe"])
        report = mig.Report(dry_run=False)
        mig._adjust_sequences(conn, [metadata.tables["seq_probe"]], report)
        assert report.sequences_adjusted == ["seq_probe.id"]
        assert conn.execute(text("INSERT INTO seq_probe (note) VALUES ('c') RETURNING id")).scalar() == 43
    engine.dispose()


def test_immutable_source_works_and_refuses_pending_wal(source_copy, target, tmp_path):
    report = run_copy(str(source_copy), target, dry_run=True, immutable_source=True)
    assert report.verified
    wal = Path(f"{source_copy}-wal")
    wal.write_bytes(b"x" * 64)
    with pytest.raises(CopyRefused, match="-wal"):
        run_copy(str(source_copy), target, dry_run=True, immutable_source=True)
