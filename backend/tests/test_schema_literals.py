"""Os `Literal` dos schemas `*Read` (vocabulários fechados, já validados na
escrita) têm de coincidir com as constantes dos modelos/serviços: se alguém
acrescentar um valor numa constante e esquecer o schema, a resposta passaria a
falhar com 500 — este teste apanha-o antes.
"""
from __future__ import annotations

import typing

import pytest

from app.models import absence, inventory, map_ops, task
from app.schemas import absences as absences_schema
from app.schemas import inventory as inventory_schema
from app.schemas import map as map_schema
from app.schemas import material_requests as material_requests_schema
from app.schemas import tasks as tasks_schema
from app.services import material_requests as material_requests_service

_MATERIAL_REQUEST_STATUSES = {
    material_requests_service.STATUS_RASCUNHO,
    material_requests_service.STATUS_PEDIDO_ENVIADO,
    material_requests_service.STATUS_ORCAMENTO_RECEBIDO,
    material_requests_service.STATUS_APROVADO,
    material_requests_service.STATUS_ADJUDICADO,
    material_requests_service.STATUS_CANCELADO,
}


@pytest.mark.parametrize(
    "literal, expected",
    [
        (tasks_schema.TaskStatus, task.TASK_STATUSES),
        (tasks_schema.TaskPriority, task.TASK_PRIORITIES),
        (tasks_schema.TaskCategory, task.TASK_CATEGORIES),
        (absences_schema.AbsenceTypeValue, absence.ABSENCE_TYPES),
        (absences_schema.AbsenceStatusValue, absence.ABSENCE_STATUSES),
        (inventory_schema.MovementType, inventory.MOVEMENT_TYPES),
        (material_requests_schema.MaterialRequestStatus, _MATERIAL_REQUEST_STATUSES),
        (map_schema.IssueCategory, map_ops.ISSUE_CATEGORIES),
        (map_schema.IssueStatus, map_ops.ISSUE_STATUSES),
        (map_schema.IssuePriority, map_ops.ISSUE_PRIORITIES),
    ],
)
def test_read_literal_matches_the_model_constant(literal, expected):
    assert set(typing.get_args(literal)) == set(expected)
