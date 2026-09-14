"""Interface de leitura do ClickUp. Fonte de verdade do estado/workflow
ClickUp continua a ser o próprio ClickUp — esta interface só lê; nenhuma
implementação escreve de volta no ClickUp nesta fase (ver
docs/ARCHITECTURE_PROPOSAL.md, "Plano de integração com ClickUp").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ClickUpTask:
    task_id: str
    name: str
    status: str
    custom_fields: dict


class ClickUpAdapter(Protocol):
    def fetch_tasks(self) -> list[ClickUpTask]: ...
