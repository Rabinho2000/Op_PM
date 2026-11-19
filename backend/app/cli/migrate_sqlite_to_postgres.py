"""Copia uma base SQLite do Op_PM para PostgreSQL (Fase 1, A8/C1).

O esquema do destino é SEMPRE criado antes por `alembic upgrade head` (nunca
por `create_all`). Esta ferramenta só copia dados:

    # 1. esquema no destino (PostgreSQL vazio)
    DATABASE_URL=postgresql+psycopg://... python -m alembic upgrade head
    # 2. ensaio (não grava nada, mas faz a cópia toda dentro de uma transação)
    python -m app.cli.migrate_sqlite_to_postgres --source /caminho/copia.db --dry-run
    # 3. cópia real
    python -m app.cli.migrate_sqlite_to_postgres --source /caminho/copia.db

O destino vem de `--target-url` ou, por omissão, de `DATABASE_URL` /
`DATABASE_URL_FILE` / `DATABASE_PASSWORD_FILE` (ver `app/config.py`).

Garantias:

- A origem é aberta só em modo de leitura (`mode=ro`). Use sempre uma CÓPIA
  (backup), nunca o ficheiro vivo.
- Tudo corre numa única transação no PostgreSQL: ou fica tudo copiado e
  verificado, ou não fica nada. `--dry-run` faz exatamente o mesmo caminho e
  faz `ROLLBACK` no fim.
- Copia tabela a tabela por ordem de chaves estrangeiras (as auto-referências
  são ordenadas pai-primeiro), em lotes, com conversões explícitas: UUID,
  JSON, Numeric, booleanos (0/1) e datas/horas (texto sem fuso é lido como
  UTC e gravado em `timestamptz`).
- `alembic_version` nunca é copiada (o destino já está na revisão certa; as
  duas revisões têm de coincidir com o `head` do código).
- O SQLite não impõe comprimentos de VARCHAR, CHECKs nem chaves estrangeiras.
  Antes de gravar, a ferramenta analisa a origem e reporta (tabela, coluna,
  motivo, contagem; nunca conteúdo) o que o PostgreSQL rejeitaria. Com
  `--dry-run`, as linhas rejeitadas por CHECK/UNIQUE/FK que só o motor
  consegue avaliar também ficam contadas (por tabela e constraint).
- Verificação final, dentro da mesma transação: contagem e checksum por
  tabela sobre as colunas normalizadas (ordem das linhas irrelevante).
  Qualquer divergência faz `ROLLBACK` e sai com código 1.
- Sequences (se existirem colunas serial/identity) são acertadas no fim.
- O destino tem de estar vazio. Depois de `alembic upgrade head` há linhas de
  referência semeadas pelas próprias migrações (permissões, papéis,
  feriados, marcadores `*_provisioning`): essas são toleradas e substituídas
  pelas da origem. Qualquer outra tabela com dados faz a ferramenta recusar,
  a menos que se passe `--replace-existing-data` (que apaga TUDO no destino
  antes de copiar).

Códigos de saída: 0 sucesso; 1 erro ou verificação falhada; 2 recusado
(destino não vazio, revisões diferentes) ou linhas que o PostgreSQL rejeita.

Nada do que a ferramenta imprime contém valores das linhas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterator

from sqlalchemy import MetaData, Table, create_engine, func, select, text
from sqlalchemy import types as sqltypes
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import sort_tables_and_constraints

EXCLUDED_TABLES = frozenset({"alembic_version"})
# Tabelas que as próprias migrações Alembic semeiam (dados de referência).
# Num destino acabado de migrar têm linhas, e isso não conta como "dados".
SEEDED_TABLES = frozenset({"roles", "permissions", "role_permissions", "holidays"})
SEEDED_SUFFIX = "_provisioning"

DEFAULT_BATCH_SIZE = 1000
_JSON_NULL = JSON_NULL = sqltypes.JSON.NULL
_INT32 = 2**31


def _is_seeded_table(name: str) -> bool:
    return name in SEEDED_TABLES or name.endswith(SEEDED_SUFFIX)


class ConvertError(Exception):
    """Valor que o PostgreSQL não aceitaria; `reason` é segura para imprimir."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------
# Conversões SQLite -> valores Python tipados (os que o SQLAlchemy envia ao PG)
# --------------------------------------------------------------------------


def _kind_of(col_type: sqltypes.TypeEngine) -> str:
    # Ordem importa: Float e Text herdam de Numeric e String.
    if isinstance(col_type, sqltypes.Uuid):
        return "uuid"
    if isinstance(col_type, sqltypes.Boolean):
        return "bool"
    if isinstance(col_type, sqltypes.JSON):
        return "json"
    if isinstance(col_type, sqltypes.Float):
        return "float"
    if isinstance(col_type, sqltypes.Numeric):
        return "numeric"
    if isinstance(col_type, sqltypes.DateTime):
        return "datetime"
    if isinstance(col_type, sqltypes.Date):
        return "date"
    if isinstance(col_type, sqltypes.Time):
        return "time"
    if isinstance(col_type, sqltypes.Integer):
        return "int"
    if isinstance(col_type, sqltypes.String):
        return "str"
    return "other"


def _reject_constant(_name: str) -> None:
    raise ValueError("constante JSON não suportada")


def parse_json_text(raw: str) -> Any:
    """JSON como o PostgreSQL o aceita (sem NaN/Infinity). `null` literal
    devolve JSON.NULL para se distinguir de NULL SQL."""
    value = json.loads(raw, parse_constant=_reject_constant)
    return _JSON_NULL if value is None else value


def build_converter(col) -> Callable[[Any], Any]:
    """Devolve `fn(valor_sqlite) -> valor_pg`. Levanta ConvertError."""
    col_type = col.type
    kind = _kind_of(col_type)
    max_len = getattr(col_type, "length", None) if kind == "str" else None
    scale = getattr(col_type, "scale", None) if kind == "numeric" else None
    precision = getattr(col_type, "precision", None) if kind == "numeric" else None

    def convert(value: Any) -> Any:
        if value is None:
            if not col.nullable:
                raise ConvertError("null_em_coluna_not_null")
            return None
        if kind == "uuid":
            if not isinstance(value, str):
                raise ConvertError("uuid_invalido")
            try:
                return uuid.UUID(value)
            except ValueError:
                raise ConvertError("uuid_invalido") from None
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            raise ConvertError("booleano_invalido")
        if kind == "json":
            if not isinstance(value, str):
                raise ConvertError("json_invalido")
            try:
                return parse_json_text(value)
            except ValueError:
                raise ConvertError("json_invalido") from None
        if kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConvertError("numero_invalido")
            return float(value)
        if kind == "numeric":
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ConvertError("numero_invalido")
            try:
                number = Decimal(repr(value) if isinstance(value, float) else str(value))
            except InvalidOperation:
                raise ConvertError("numero_invalido") from None
            if not number.is_finite():
                raise ConvertError("numero_invalido")
            if scale is not None and -number.as_tuple().exponent > scale:
                raise ConvertError("numeric_perderia_casas_decimais")
            if precision is not None and scale is not None:
                if abs(number) >= Decimal(10) ** (precision - scale):
                    raise ConvertError("numeric_excede_precisao")
            return number
        if kind == "datetime":
            if not isinstance(value, str):
                raise ConvertError("datetime_invalido")
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                raise ConvertError("datetime_invalido") from None
            return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
        if kind == "date":
            if not isinstance(value, str) or len(value) != 10:
                raise ConvertError("data_invalida")
            try:
                return date.fromisoformat(value)
            except ValueError:
                raise ConvertError("data_invalida") from None
        if kind == "time":
            if not isinstance(value, str):
                raise ConvertError("hora_invalida")
            try:
                return dtime.fromisoformat(value)
            except ValueError:
                raise ConvertError("hora_invalida") from None
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConvertError("inteiro_invalido")
            if isinstance(col_type, sqltypes.SmallInteger):
                limit = 2**15
            elif isinstance(col_type, sqltypes.BigInteger):
                limit = 2**63
            else:
                limit = _INT32
            if not -limit <= value < limit:
                raise ConvertError("inteiro_fora_de_intervalo")
            return value
        if kind == "str":
            if not isinstance(value, str):
                raise ConvertError("texto_com_tipo_inesperado")
            if "\x00" in value:
                raise ConvertError("caractere_nul_no_texto")
            if max_len is not None and len(value) > max_len:
                raise ConvertError(f"excede_varchar_{max_len}")
            return value
        return value

    return convert


def canonical(kind: str, value: Any) -> Any:
    """Forma normalizada (serializável em JSON) de um valor já tipado, igual
    para o que vem da origem convertida e para o que o PostgreSQL devolve."""
    if value is None:
        return None
    if kind == "uuid":
        return str(value)
    if kind == "bool":
        return bool(value)
    if kind == "json":
        if value is _JSON_NULL:
            return {"$json": "null"}
        return {"$json": json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)}
    if kind == "float":
        return {"$float": repr(float(value))}
    if kind == "numeric":
        return {"$num": format(Decimal(value).normalize(), "f")}
    if kind == "datetime":
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if kind in ("date", "time"):
        return value.isoformat()
    return value


def _json_from_pg_text(raw: str | None) -> Any:
    return None if raw is None else parse_json_text(raw)


class _Digest:
    """Checksum independente da ordem das linhas: soma módulo 2**256 dos
    SHA-256 de cada linha normalizada."""

    def __init__(self) -> None:
        self.count = 0
        self._sum = 0

    def add(self, canonical_row: list[Any]) -> None:
        payload = json.dumps(canonical_row, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
        self._sum = (self._sum + int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16)) % (1 << 256)
        self.count += 1

    def hexdigest(self) -> str:
        return f"{self._sum:064x}"


# --------------------------------------------------------------------------
# Modelo do relatório
# --------------------------------------------------------------------------


@dataclass
class TableResult:
    name: str
    source_rows: int = 0
    copied_rows: int = 0
    target_rows: int | None = None
    source_checksum: str | None = None
    target_checksum: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.target_rows == self.source_rows
            and self.source_checksum is not None
            and self.source_checksum == self.target_checksum
        )


@dataclass
class Report:
    dry_run: bool
    source_revision: str | None = None
    target_revision: str | None = None
    tables: dict[str, TableResult] = field(default_factory=dict)
    # (tabela, coluna(s), motivo) -> nº de linhas
    issues: Counter = field(default_factory=Counter)
    # (tabela, sqlstate, constraint/coluna) -> nº de linhas (só com --dry-run)
    engine_rejections: Counter = field(default_factory=Counter)
    truncated_seed_tables: list[str] = field(default_factory=list)
    sequences_adjusted: list[str] = field(default_factory=list)
    batch_size: int = DEFAULT_BATCH_SIZE
    seconds_copy: float = 0.0
    seconds_total: float = 0.0
    verified: bool = False
    committed: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "committed": self.committed,
            "verified": self.verified,
            "source_revision": self.source_revision,
            "target_revision": self.target_revision,
            "seconds_copy": round(self.seconds_copy, 2),
            "seconds_total": round(self.seconds_total, 2),
            "tables": {
                n: {
                    "source_rows": t.source_rows,
                    "target_rows": t.target_rows,
                    "source_checksum": t.source_checksum,
                    "target_checksum": t.target_checksum,
                    "ok": t.ok,
                }
                for n, t in self.tables.items()
            },
            "issues": [
                {"table": t, "column": c, "reason": r, "rows": n} for (t, c, r), n in sorted(self.issues.items())
            ],
            "engine_rejections": [
                {"table": t, "sqlstate": s, "detail": d, "rows": n}
                for (t, s, d), n in sorted(self.engine_rejections.items())
            ],
            "truncated_seed_tables": self.truncated_seed_tables,
            "sequences_adjusted": self.sequences_adjusted,
        }


class CopyRefused(Exception):
    """Pré-condição não cumprida (destino não vazio, revisões diferentes...).
    `report` leva o que já foi apurado (por exemplo as linhas rejeitáveis)."""

    report: Report | None = None


class CopyFailed(Exception):
    """Falha durante a cópia ou verificação."""


# --------------------------------------------------------------------------
# Origem e destino
# --------------------------------------------------------------------------


def open_source(path: str, *, immutable: bool = False) -> sqlite3.Connection:
    """Abre a origem só em leitura. `immutable=True` serve para um ficheiro
    num suporte só de leitura (por exemplo montado com `:ro` num contentor),
    onde o SQLite não consegue criar os ficheiros auxiliares do modo WAL;
    recusa-se se existir um `-wal` com conteúdo (ficaria por ler)."""
    source = Path(path)
    if not source.is_file():
        raise CopyRefused(f"ficheiro de origem inexistente: {source}")
    uri = f"file:{source.resolve().as_posix()}?mode=ro"
    if immutable:
        wal = Path(f"{source}-wal")
        if wal.exists() and wal.stat().st_size > 0:
            raise CopyRefused("--immutable recusado: existe um -wal com dados ao lado da origem (faça um backup consistente)")
        uri += "&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.text_factory = lambda raw: raw.decode("utf-8", errors="surrogateescape")
    try:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.DatabaseError:
        conn.close()
        raise CopyRefused("a origem não é uma base SQLite válida") from None
    return conn


def _source_tables(src: sqlite3.Connection) -> set[str]:
    return {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _source_columns(src: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in src.execute(f'PRAGMA table_info("{table}")')]


def _revision(conn_exec: Callable[[str], Any]) -> str | None:
    try:
        row = conn_exec("SELECT version_num FROM alembic_version").fetchone()
    except Exception:  # noqa: BLE001 - tabela ausente
        return None
    return row[0] if row else None


def _code_heads() -> set[str] | None:
    ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not ini.is_file():
        return None
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    return set(ScriptDirectory.from_config(cfg).get_heads())


def _ordered_tables(metadata: MetaData) -> list[Table]:
    ordered: list[Table] = []
    for table, _constraints in sort_tables_and_constraints(metadata.tables.values()):
        if table is not None and table.name not in EXCLUDED_TABLES:
            ordered.append(table)
    return ordered


def reflect_target(conn: Connection) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=conn)
    for table in metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, sqltypes.JSON):
                # None -> NULL SQL; o JSON `null` usa JSON.NULL explicitamente.
                col.type = sqltypes.JSON(none_as_null=True)
    return metadata


# --------------------------------------------------------------------------
# Análise da origem (o que o PostgreSQL rejeitaria)
# --------------------------------------------------------------------------


def _check_structure(src: sqlite3.Connection, tables: list[Table], report: Report) -> None:
    src_tables = _source_tables(src) - EXCLUDED_TABLES
    target_names = {t.name for t in tables}
    extra = sorted(src_tables - target_names)
    if extra:
        raise CopyRefused(
            "tabelas na origem sem correspondência no destino (esquema do Alembic desatualizado?): " + ", ".join(extra)
        )
    for table in tables:
        if table.name not in src_tables:
            continue
        have = set(_source_columns(src, table.name))
        want = {c.name for c in table.columns}
        missing_in_target = sorted(have - want)
        if missing_in_target:
            raise CopyRefused(f"{table.name}: colunas na origem que o destino não tem: {', '.join(missing_in_target)}")
        for col in table.columns:
            if col.name not in have and not col.nullable and col.server_default is None:
                raise CopyRefused(f"{table.name}.{col.name}: NOT NULL sem valor por omissão e ausente na origem")


def _analyse_rows_and_fks(src: sqlite3.Connection, tables: list[Table], report: Report) -> None:
    src_tables = _source_tables(src)
    for table in tables:
        if table.name not in src_tables:
            continue
        have = set(_source_columns(src, table.name))
        cols = [c for c in table.columns if c.name in have]
        converters = {c.name: build_converter(c) for c in cols}
        names = [c.name for c in cols]
        quoted = ", ".join(f'"{n}"' for n in names)
        for row in src.execute(f'SELECT {quoted} FROM "{table.name}"'):
            for name, value in zip(names, row):
                try:
                    converters[name](value)
                except ConvertError as exc:
                    report.issues[(table.name, name, exc.reason)] += 1
        for fk in table.foreign_key_constraints:
            parent = fk.referred_table
            if parent.name not in src_tables:
                continue
            local = [c.name for c in fk.columns]
            remote = [e.column.name for e in fk.elements]
            if any(n not in have for n in local):
                continue
            cond = " AND ".join(f'p."{r}" = c."{l}"' for l, r in zip(local, remote))
            notnull = " AND ".join(f'c."{l}" IS NOT NULL' for l in local)
            sql = (
                f'SELECT COUNT(*) FROM "{table.name}" c WHERE {notnull} '
                f'AND NOT EXISTS (SELECT 1 FROM "{parent.name}" p WHERE {cond})'
            )
            orphans = src.execute(sql).fetchone()[0]
            if orphans:
                report.issues[(table.name, ",".join(local), f"fk_orfa_para_{parent.name}")] += orphans


# --------------------------------------------------------------------------
# Cópia
# --------------------------------------------------------------------------


def _iter_source_batches(
    src: sqlite3.Connection, table: Table, names: list[str], batch_size: int
) -> Iterator[list[tuple]]:
    quoted = ", ".join(f'"{n}"' for n in names)
    cursor = src.execute(f'SELECT {quoted} FROM "{table.name}"')
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        yield rows


def _order_self_references(table: Table, names: list[str], rows: list[dict]) -> list[dict]:
    """Pai primeiro, para as FK de uma tabela para si própria."""
    self_fks = [fk for fk in table.foreign_key_constraints if fk.referred_table is table]
    if not self_fks:
        return rows
    pk_cols = [c.name for c in table.primary_key.columns]
    if len(pk_cols) != 1:
        raise CopyFailed(f"{table.name}: auto-referência numa tabela sem PK simples")
    pk = pk_cols[0]
    parent_cols = [fk.columns[0].name for fk in self_fks]
    by_id = {r[pk]: r for r in rows}
    ordered: list[dict] = []
    done: set[Any] = set()
    pending = list(rows)
    while pending:
        progressed = False
        waiting = []
        for row in pending:
            deps = [row[c] for c in parent_cols if row[c] is not None and row[c] in by_id and row[c] != row[pk]]
            if all(d in done for d in deps):
                ordered.append(row)
                done.add(row[pk])
                progressed = True
            else:
                waiting.append(row)
        if not progressed:
            raise CopyFailed(f"{table.name}: ciclo nas referências da própria tabela")
        pending = waiting
    return ordered


def _rejection_key(table: str, exc: DBAPIError) -> tuple[str, str, str]:
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    sqlstate = getattr(orig, "sqlstate", None) or "?"
    detail = (
        getattr(diag, "constraint_name", None)
        or getattr(diag, "column_name", None)
        or type(orig).__name__
    )
    return (table, str(sqlstate), str(detail))


def _insert_rows(
    conn: Connection, table: Table, rows: list[dict], report: Report, *, trial: bool
) -> int:
    """Insere um lote. Em `trial` (dry-run), uma falha é isolada linha a linha
    com SAVEPOINTs e contada, em vez de abortar."""
    if not rows:
        return 0
    if not trial:
        try:
            conn.execute(table.insert(), rows)
        except DBAPIError as exc:
            sqlstate, detail = _rejection_key(table.name, exc)[1:]
            raise CopyFailed(
                f"{table.name}: o PostgreSQL rejeitou um lote (sqlstate={sqlstate}, {detail})"
            ) from None
        return len(rows)
    try:
        with conn.begin_nested():
            conn.execute(table.insert(), rows)
        return len(rows)
    except DBAPIError:
        pass
    inserted = 0
    for row in rows:
        try:
            with conn.begin_nested():
                conn.execute(table.insert(), [row])
            inserted += 1
        except DBAPIError as exc:
            report.engine_rejections[_rejection_key(table.name, exc)] += 1
    return inserted


def _copy_table(
    conn: Connection, src: sqlite3.Connection, table: Table, report: Report, batch_size: int, *, trial: bool
) -> tuple[int, _Digest]:
    """Copia uma tabela; devolve (linhas inseridas, digest da origem)."""
    result = report.tables[table.name]
    src_tables = _source_tables(src)
    if table.name not in src_tables:
        return 0, _Digest()
    have = set(_source_columns(src, table.name))
    cols = [c for c in table.columns if c.name in have]
    names = [c.name for c in cols]
    converters = {c.name: build_converter(c) for c in cols}
    kinds = {c.name: _kind_of(c.type) for c in cols}
    digest = _Digest()
    has_self_fk = any(fk.referred_table is table for fk in table.foreign_key_constraints)
    inserted = 0

    def convert_batch(raw_rows: list[tuple]) -> list[dict]:
        converted: list[dict] = []
        for raw in raw_rows:
            try:
                row = {n: converters[n](v) for n, v in zip(names, raw)}
            except ConvertError:
                continue  # já contada na análise; só chega aqui com --dry-run
            converted.append(row)
        return converted

    if has_self_fk:
        all_rows = convert_batch([r for batch in _iter_source_batches(src, table, names, batch_size) for r in batch])
        all_rows = _order_self_references(table, names, all_rows)
        batches: Iterator[list[dict]] = (
            all_rows[i : i + batch_size] for i in range(0, len(all_rows), batch_size)
        )
    else:
        batches = (convert_batch(raw) for raw in _iter_source_batches(src, table, names, batch_size))

    for batch in batches:
        for row in batch:
            digest.add([canonical(kinds[n], row[n]) for n in sorted(names)])
        inserted += _insert_rows(conn, table, batch, report, trial=trial)
    result.copied_rows = inserted
    return inserted, digest


def _target_digest(conn: Connection, table: Table, names: list[str]) -> _Digest:
    digest = _Digest()
    kinds = {c.name: _kind_of(c.type) for c in table.columns}
    exprs = []
    for n in names:
        col = table.c[n]
        exprs.append(col.cast(sqltypes.Text).label(n) if kinds[n] == "json" else col)
    stream = conn.execution_options(stream_results=True, yield_per=2000).execute(select(*exprs))
    for row in stream:
        values = {}
        for n, v in zip(names, row):
            values[n] = _json_from_pg_text(v) if kinds[n] == "json" else v
        digest.add([canonical(kinds[n], values[n]) for n in sorted(names)])
    return digest


def _adjust_sequences(conn: Connection, tables: list[Table], report: Report) -> None:
    for table in tables:
        for col in table.primary_key.columns:
            if not isinstance(col.type, sqltypes.Integer):
                continue
            seq = conn.execute(
                text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": f'"{table.name}"', "c": col.name}
            ).scalar()
            if not seq:
                continue
            conn.execute(
                text(f'SELECT setval(:s, COALESCE((SELECT MAX("{col.name}") FROM "{table.name}"), 1), '
                     f'(SELECT COUNT(*) > 0 FROM "{table.name}"))'),
                {"s": seq},
            )
            report.sequences_adjusted.append(f"{table.name}.{col.name}")


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------


def _check_target_is_empty(conn: Connection, tables: list[Table], report: Report, replace_existing: bool) -> None:
    populated = {}
    for table in tables:
        n = conn.execute(select(func.count()).select_from(table)).scalar()
        if n:
            populated[table.name] = n
    unexpected = sorted(n for n in populated if not _is_seeded_table(n))
    if unexpected and not replace_existing:
        raise CopyRefused(
            f"o destino já tem dados em {len(unexpected)} tabelas (por exemplo: "
            + ", ".join(f"{n} ({populated[n]})" for n in unexpected[:5])
            + "). Recusado. Use um PostgreSQL novo (só `alembic upgrade head`) ou, sabendo o que faz, "
            "--replace-existing-data (apaga TUDO no destino antes de copiar)."
        )
    report.truncated_seed_tables = sorted(populated)
    if populated:
        names = ", ".join(f'"{t.name}"' for t in tables)
        conn.execute(text(f"TRUNCATE TABLE {names}"))


def run_copy(
    source_path: str,
    target_url: str,
    *,
    dry_run: bool = False,
    replace_existing: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    immutable_source: bool = False,
    engine: Engine | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> Report:
    started = time.monotonic()
    report = Report(dry_run=dry_run, batch_size=batch_size)
    owns_engine = engine is None
    if engine is None:
        if not make_url(target_url).get_backend_name().startswith("postgresql"):
            raise CopyRefused("o destino tem de ser PostgreSQL")
        engine = create_engine(target_url, future=True)
    elif engine.dialect.name != "postgresql":
        raise CopyRefused("o destino tem de ser PostgreSQL")
    src = open_source(source_path, immutable=immutable_source)
    try:
        with engine.connect() as conn:
            metadata = reflect_target(conn)
            if "alembic_version" not in metadata.tables:
                raise CopyRefused("o destino não tem `alembic_version`: corra primeiro `alembic upgrade head`")
            tables = _ordered_tables(metadata)

            report.target_revision = _revision(lambda q: conn.execute(text(q)))
            report.source_revision = _revision(src.execute)
            heads = _code_heads()
            if report.source_revision != report.target_revision:
                raise CopyRefused(
                    f"revisões Alembic diferentes (origem={report.source_revision}, destino={report.target_revision}); "
                    "migre a origem e o destino para a mesma revisão"
                )
            if heads is not None and report.target_revision not in heads:
                raise CopyRefused(
                    f"o destino está na revisão {report.target_revision}, que não é o head do código ({', '.join(sorted(heads))})"
                )

            _check_structure(src, tables, report)
            log("a analisar a origem (valores que o PostgreSQL rejeitaria)...")
            _analyse_rows_and_fks(src, tables, report)
            if report.issues and not dry_run:
                refused = CopyRefused("a origem tem linhas que o PostgreSQL rejeitaria (ver relatório); nada foi gravado")
                refused.report = report
                raise refused

            for table in tables:
                report.tables[table.name] = TableResult(name=table.name)
                report.tables[table.name].source_rows = (
                    src.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
                    if table.name in _source_tables(src)
                    else 0
                )

            conn.rollback()  # fecha a transação implícita das leituras acima
            transaction = conn.begin()
            try:
                _check_target_is_empty(conn, tables, report, replace_existing)
                copy_started = time.monotonic()
                digests: dict[str, _Digest] = {}
                for table in tables:
                    log(f"a copiar {table.name} ({report.tables[table.name].source_rows} linhas)")
                    _inserted, digests[table.name] = _copy_table(
                        conn, src, table, report, batch_size, trial=dry_run
                    )
                _adjust_sequences(conn, tables, report)
                report.seconds_copy = time.monotonic() - copy_started

                log("a verificar contagens e checksums...")
                skip_verify = bool(report.issues or report.engine_rejections)
                for table in tables:
                    res = report.tables[table.name]
                    have = _source_columns(src, table.name) if table.name in _source_tables(src) else []
                    names = [c.name for c in table.columns if c.name in have]
                    res.source_checksum = digests[table.name].hexdigest()
                    res.target_rows = conn.execute(
                        select(func.count()).select_from(table)
                    ).scalar()
                    res.target_checksum = _target_digest(conn, table, names).hexdigest() if names else digests[table.name].hexdigest()
                if not skip_verify:
                    bad = [t.name for t in report.tables.values() if not t.ok]
                    if bad:
                        raise CopyFailed("verificação falhada (contagem ou checksum) em: " + ", ".join(bad))
                    report.verified = True
                if dry_run:
                    transaction.rollback()
                else:
                    transaction.commit()
                    report.committed = True
            except BaseException:
                if transaction.is_active:
                    transaction.rollback()
                raise
    finally:
        src.close()
        if owns_engine:
            engine.dispose()
        report.seconds_total = time.monotonic() - started
    return report


def verify_only(
    source_path: str, target_url: str, *, immutable_source: bool = False, engine: Engine | None = None
) -> Report:
    """Compara uma cópia já feita (contagens e checksums), sem gravar nada."""
    report = Report(dry_run=True)
    owns_engine = engine is None
    engine = engine or create_engine(target_url, future=True)
    src = open_source(source_path, immutable=immutable_source)
    try:
        with engine.connect() as conn:
            metadata = reflect_target(conn)
            tables = _ordered_tables(metadata)
            src_tables = _source_tables(src)
            for table in tables:
                res = report.tables.setdefault(table.name, TableResult(name=table.name))
                if table.name not in src_tables:
                    continue
                have = set(_source_columns(src, table.name))
                cols = [c for c in table.columns if c.name in have]
                names = [c.name for c in cols]
                kinds = {c.name: _kind_of(c.type) for c in cols}
                converters = {c.name: build_converter(c) for c in cols}
                digest = _Digest()
                for batch in _iter_source_batches(src, table, names, DEFAULT_BATCH_SIZE):
                    for raw in batch:
                        try:
                            row = {n: converters[n](v) for n, v in zip(names, raw)}
                        except ConvertError as exc:
                            report.issues[(table.name, "?", exc.reason)] += 1
                            continue
                        digest.add([canonical(kinds[n], row[n]) for n in sorted(names)])
                res.source_rows = src.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()[0]
                res.source_checksum = digest.hexdigest()
                res.target_rows = conn.execute(select(func.count()).select_from(table)).scalar()
                res.target_checksum = _target_digest(conn, table, names).hexdigest()
            report.verified = all(t.ok for t in report.tables.values()) and not report.issues
    finally:
        src.close()
        if owns_engine:
            engine.dispose()
    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def print_report(report: Report, *, out=None) -> None:
    out = out or sys.stdout
    rejected = bool(report.issues or report.engine_rejections)

    def p(msg: str = "") -> None:
        print(msg, file=out)

    mode = "DRY-RUN (nada foi gravado)" if report.dry_run else ("COMMIT" if report.committed else "ABORTADO")
    p(f"Modo: {mode}")
    p(f"Revisão Alembic: origem={report.source_revision} destino={report.target_revision}")
    if report.truncated_seed_tables:
        p(f"Tabelas do destino esvaziadas antes da cópia (dados semeados pelas migrações): {len(report.truncated_seed_tables)}")
    if report.issues:
        p("Linhas que o PostgreSQL rejeitaria (tabela, coluna, motivo: nº de linhas):")
        for (table, column, reason), n in sorted(report.issues.items()):
            p(f"  - {table}.{column}: {reason}: {n}")
    if report.engine_rejections:
        p("Linhas rejeitadas pelo motor no ensaio (tabela, sqlstate, constraint/coluna: nº de linhas):")
        for (table, state, detail), n in sorted(report.engine_rejections.items()):
            p(f"  - {table}: {state} {detail}: {n}")
    if report.tables:
        p(f"{'tabela':45} {'origem':>8} {'destino':>8}  checksum")
        for name in sorted(report.tables):
            t = report.tables[name]
            flag = "OK" if t.ok else ("n/a (há linhas rejeitadas)" if rejected else "DIVERGE")
            p(f"{name:45} {t.source_rows:>8} {t.target_rows if t.target_rows is not None else '-':>8}  {flag}")
        total_src = sum(t.source_rows for t in report.tables.values())
        total_dst = sum(t.target_rows or 0 for t in report.tables.values())
        good = sum(1 for t in report.tables.values() if t.ok)
        if rejected:
            p("Nota: uma rejeição pode arrastar as linhas que dependem dela (chaves estrangeiras); a verificação não se aplica.")
        p(f"Total: {len(report.tables)} tabelas, {total_src} linhas na origem, {total_dst} no destino; {good} tabelas com contagem e checksum iguais")
    if report.sequences_adjusted:
        p(f"Sequences acertadas: {len(report.sequences_adjusted)}")
    p(f"Duração: cópia {report.seconds_copy:.1f}s, total {report.seconds_total:.1f}s")
    p("Verificação: " + ("OK" if report.verified else "NÃO CONCLUÍDA/COM DIVERGÊNCIAS"))


def _default_target_url() -> str:
    from app.config import get_settings

    return get_settings().database_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.migrate_sqlite_to_postgres",
        description="Copia uma base SQLite (cópia/backup) para um PostgreSQL já migrado por Alembic.",
    )
    parser.add_argument("--source", required=True, help="ficheiro SQLite de origem (uma CÓPIA; abre-se só em leitura)")
    parser.add_argument("--target-url", help="URL SQLAlchemy do PostgreSQL; por omissão DATABASE_URL[_FILE] / DATABASE_PASSWORD_FILE")
    parser.add_argument("--dry-run", action="store_true", help="faz tudo numa transação e desfaz no fim")
    parser.add_argument("--verify-only", action="store_true", help="só compara contagens e checksums de uma cópia já feita")
    parser.add_argument(
        "--replace-existing-data",
        action="store_true",
        help="permite um destino com dados: apaga TUDO no destino antes de copiar",
    )
    parser.add_argument(
        "--immutable",
        action="store_true",
        help="abre a origem com immutable=1 (para um ficheiro montado só em leitura; recusa um -wal com dados)",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--report", help="escreve o relatório em JSON (0600) neste caminho")
    args = parser.parse_args(argv)

    if args.batch_size < 1:
        parser.error("--batch-size tem de ser >= 1")
    try:
        target_url = args.target_url or _default_target_url()
        if args.verify_only:
            report = verify_only(args.source, target_url, immutable_source=args.immutable)
        else:
            report = run_copy(
                args.source,
                target_url,
                dry_run=args.dry_run,
                replace_existing=args.replace_existing_data,
                batch_size=args.batch_size,
                immutable_source=args.immutable,
                log=lambda m: print(m, file=sys.stderr),
            )
    except CopyRefused as exc:
        print(f"RECUSADO: {exc}", file=sys.stderr)
        if exc.report is not None:
            print_report(exc.report)
        return 2
    except CopyFailed as exc:
        print(f"FALHOU: {exc}", file=sys.stderr)
        return 1
    except DBAPIError as exc:
        key = _rejection_key("?", exc)
        print(f"FALHOU: erro do PostgreSQL (sqlstate={key[1]}, {key[2]})", file=sys.stderr)
        return 1

    print_report(report)
    if args.report:
        path = Path(args.report)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report.to_json(), handle, indent=2, ensure_ascii=False)
    if report.issues or report.engine_rejections:
        return 2
    return 0 if report.verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
