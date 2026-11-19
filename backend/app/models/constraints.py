"""Construtores de CHECK a partir das constantes Python dos vocabulários.

Os vocabulários fechados (estados, tipos de movimento, ...) vivem como
constantes nos modelos/serviços. Para não duplicar à mão a lista na BD, o
CHECK é gerado a partir da própria constante — modelo: `UserRequest`.

As migrações NÃO importam estas constantes: congelam os valores em literais
(uma migração tem de continuar a significar o mesmo daqui a um ano). O teste
`tests/test_check_constraints.py` confirma que o esquema migrado e os modelos
declaram os mesmos CHECKs.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import CheckConstraint


def sql_in_list(values: Iterable[str]) -> str:
    """`'a', 'b'` — conjuntos são ordenados para o texto ser determinístico;
    sequências (tuplos/listas) mantêm a ordem dada."""
    ordered = sorted(values) if isinstance(values, (set, frozenset)) else list(values)
    if not ordered:
        raise ValueError("Um vocabulário fechado não pode estar vazio.")
    for value in ordered:
        if "'" in value:
            raise ValueError(f"Valor de vocabulário inválido para SQL: {value!r}")
    return ", ".join(f"'{value}'" for value in ordered)


def vocabulary_check(
    column: str,
    values: Iterable[str],
    *,
    name: str,
    nullable: bool = False,
) -> CheckConstraint:
    """`column IN (...)`; com `nullable=True` aceita também NULL (explícito,
    para o texto ser igual em SQLite e PostgreSQL)."""
    clause = f"{column} IN ({sql_in_list(values)})"
    if nullable:
        clause = f"{column} IS NULL OR {clause}"
    return CheckConstraint(clause, name=name)
