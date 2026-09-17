"""Definição do percurso de obra (fases → etapas → subtarefas) a partir de
um ficheiro JSON, aplicada à base de dados de forma idempotente (D-052).

O repositório só traz um processo de EXEMPLO (`processo_exemplo.json`); o
processo oficial vive num ficheiro local fora do Git e é carregado com
`python -m app.cli.workflow load --file <ficheiro> --apply`.

Chaves estáveis: etapa `etapa.NN` (número da etapa), subtarefa
`etapa.NN.M` (posição dentro da etapa, a partir de 1) ou o `code`
explícito da subtarefa, se o ficheiro o indicar. O progresso de cada
projeto referencia estas linhas por chave estrangeira — por isso a
aplicação **nunca apaga** uma etapa/subtarefa que já tenha progresso
registado; recusa e explica.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.security.catalog import ROLES

EXAMPLE_DEFINITION_PATH = Path(__file__).with_name("processo_exemplo.json")


class PhaseDef(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    color: str = Field(default="#888888", pattern=r"^#[0-9A-Fa-f]{6}$")


class ContactDef(BaseModel):
    day: int = Field(ge=1)
    type: Literal["contacto", "update"]
    note: str = ""


class SubtaskDef(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    client_contact: bool = False
    code: str | None = Field(default=None, max_length=96)


class StageDef(BaseModel):
    number: int = Field(ge=1)
    phase: str
    title: str = Field(min_length=1, max_length=256)
    responsible_role: str | None = None
    responsible_label: str = Field(default="", max_length=128)
    depends_on: int | None = None
    start_day: int = Field(ge=1)
    end_day: int = Field(ge=1)
    contact: ContactDef | None = None
    note: str = ""
    subtasks: list[SubtaskDef] = Field(min_length=1)

    @field_validator("subtasks", mode="before")
    @classmethod
    def _accept_plain_titles(cls, value):
        # Cada subtarefa pode ser só o título (texto) ou um objeto.
        return [{"title": item} if isinstance(item, str) else item for item in value]

    @field_validator("responsible_role")
    @classmethod
    def _known_role(cls, value: str | None) -> str | None:
        if value is not None and value not in ROLES:
            raise ValueError(f"papel desconhecido: {value!r} (conhecidos: {', '.join(sorted(ROLES))})")
        return value

    @model_validator(mode="after")
    def _days_in_order(self):
        if self.end_day < self.start_day:
            raise ValueError(f"etapa {self.number}: end_day ({self.end_day}) antes de start_day ({self.start_day})")
        return self

    @property
    def code(self) -> str:
        return stage_code(self.number)


class WorkflowDefinition(BaseModel):
    name: str = ""
    description: str = ""
    phases: list[PhaseDef] = Field(min_length=1)
    stages: list[StageDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self):
        phase_codes = [p.code for p in self.phases]
        if len(set(phase_codes)) != len(phase_codes):
            raise ValueError("códigos de fase repetidos")
        numbers = [s.number for s in self.stages]
        if len(set(numbers)) != len(numbers):
            raise ValueError("números de etapa repetidos")
        for stage in self.stages:
            if stage.phase not in phase_codes:
                raise ValueError(f"etapa {stage.number}: fase desconhecida {stage.phase!r}")
            if stage.depends_on is not None:
                if stage.depends_on not in numbers:
                    raise ValueError(f"etapa {stage.number}: depende da etapa {stage.depends_on}, que não existe")
                if stage.depends_on == stage.number:
                    raise ValueError(f"etapa {stage.number}: não pode depender de si própria")
        sub_codes = [code for stage in self.stages for code, _ in subtask_codes(stage)]
        if len(set(sub_codes)) != len(sub_codes):
            raise ValueError("códigos de subtarefa repetidos")
        return self


def stage_code(number: int) -> str:
    return f"etapa.{number:02d}"


def subtask_codes(stage: StageDef) -> list[tuple[str, SubtaskDef]]:
    return [(sub.code or f"{stage.code}.{index}", sub) for index, sub in enumerate(stage.subtasks, start=1)]


def load_definition(path: Path) -> WorkflowDefinition:
    with path.open(encoding="utf-8") as fh:
        return WorkflowDefinition.model_validate(json.load(fh))


class WorkflowDefinitionConflict(Exception):
    """A nova definição removeria etapas/subtarefas com progresso registado."""


@dataclasses.dataclass
class ApplyReport:
    phases_created: int = 0
    phases_updated: int = 0
    stages_created: int = 0
    stages_updated: int = 0
    stages_removed: int = 0
    subtasks_created: int = 0
    subtasks_updated: int = 0
    subtasks_removed: int = 0
    phases_removed: int = 0

    @property
    def changed(self) -> bool:
        return any(dataclasses.astuple(self))

    def lines(self) -> list[str]:
        return [
            f"fases: +{self.phases_created} ~{self.phases_updated} -{self.phases_removed}",
            f"etapas: +{self.stages_created} ~{self.stages_updated} -{self.stages_removed}",
            f"subtarefas: +{self.subtasks_created} ~{self.subtasks_updated} -{self.subtasks_removed}",
        ]


def _assign(obj, values: dict) -> bool:
    changed = False
    for key, value in values.items():
        if getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True
    return changed


def apply_definition(db: Session, definition: WorkflowDefinition) -> ApplyReport:
    """Cria/atualiza/remove fases, etapas e subtarefas para ficarem iguais
    à definição. Não faz commit — quem chama decide (o CLI faz rollback em
    modo de simulação)."""
    report = ApplyReport()

    phases = {p.code: p for p in db.query(Phase).all()}
    for order, phase_def in enumerate(definition.phases):
        values = {"name": phase_def.name, "color_hex": phase_def.color, "sort_order": order}
        phase = phases.get(phase_def.code)
        if phase is None:
            phase = Phase(code=phase_def.code, **values)
            db.add(phase)
            phases[phase_def.code] = phase
            report.phases_created += 1
        elif _assign(phase, values):
            report.phases_updated += 1
    db.flush()

    wanted_stage_codes = {s.code for s in definition.stages}
    wanted_sub_codes = {code for s in definition.stages for code, _ in subtask_codes(s)}

    # Recusar antes de tocar em etapas/subtarefas se algo com progresso
    # fosse removido (quem chama faz rollback das fases já atualizadas).
    stale_subtasks = db.query(WorkflowSubtask).filter(WorkflowSubtask.code.notin_(wanted_sub_codes)).all()
    stale_stages = db.query(WorkflowStage).filter(WorkflowStage.code.notin_(wanted_stage_codes)).all()
    blocked = [
        s.code
        for s in stale_subtasks
        if db.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.subtask_id == s.id).first()
    ] + [
        s.code
        for s in stale_stages
        if db.query(ProjectStageProgress).filter(ProjectStageProgress.stage_id == s.id).first()
    ]
    if blocked:
        raise WorkflowDefinitionConflict(
            "a definição removeria itens com progresso registado em projetos: " + ", ".join(sorted(blocked))
        )

    stages = {s.code: s for s in db.query(WorkflowStage).all()}
    created_stage_codes: set[str] = set()
    updated_stage_codes: set[str] = set()
    for stage_def in definition.stages:
        values = {
            "phase_id": phases[stage_def.phase].id,
            "title": stage_def.title,
            "responsible_role_code": stage_def.responsible_role,
            "responsible_label": stage_def.responsible_label,
            "sort_order": stage_def.number,
            "planned_start_offset_days": stage_def.start_day,
            "planned_end_offset_days": stage_def.end_day,
            "has_contact_checkpoint": stage_def.contact is not None,
            "contact_type": stage_def.contact.type if stage_def.contact else None,
            "contact_day": stage_def.contact.day if stage_def.contact else None,
            "contact_note": stage_def.contact.note if stage_def.contact else "",
            "note": stage_def.note,
        }
        stage = stages.get(stage_def.code)
        if stage is None:
            stage = WorkflowStage(code=stage_def.code, **values)
            db.add(stage)
            stages[stage_def.code] = stage
            created_stage_codes.add(stage_def.code)
        elif _assign(stage, values):
            updated_stage_codes.add(stage_def.code)
    db.flush()

    # Dependências só depois de todas as etapas terem id.
    for stage_def in definition.stages:
        stage = stages[stage_def.code]
        dep_id = stages[stage_code(stage_def.depends_on)].id if stage_def.depends_on is not None else None
        if stage.depends_on_stage_id != dep_id:
            stage.depends_on_stage_id = dep_id
            if stage_def.code not in created_stage_codes:
                updated_stage_codes.add(stage_def.code)
    report.stages_created = len(created_stage_codes)
    report.stages_updated = len(updated_stage_codes)

    subtasks = {s.code: s for s in db.query(WorkflowSubtask).all()}
    for stage_def in definition.stages:
        stage = stages[stage_def.code]
        for order, (code, sub_def) in enumerate(subtask_codes(stage_def), start=1):
            values = {
                "stage_id": stage.id,
                "title": sub_def.title,
                "sort_order": order,
                "is_client_contact": sub_def.client_contact,
            }
            sub = subtasks.get(code)
            if sub is None:
                db.add(WorkflowSubtask(code=code, **values))
                report.subtasks_created += 1
            elif _assign(sub, values):
                report.subtasks_updated += 1
    db.flush()

    for sub in stale_subtasks:
        db.delete(sub)
        report.subtasks_removed += 1
    db.flush()
    for stage in stale_stages:
        # Etapas antigas que dependiam de outra etapa antiga.
        stage.depends_on_stage_id = None
    db.flush()
    for stage in stale_stages:
        db.delete(stage)
        report.stages_removed += 1
    db.flush()

    wanted_phase_codes = {p.code for p in definition.phases}
    for code, phase in phases.items():
        if code not in wanted_phase_codes:
            in_use = db.query(WorkflowStage).filter(WorkflowStage.phase_id == phase.id).first() or (
                db.query(Project).filter(Project.current_phase_id == phase.id).first()
            )
            if not in_use:
                db.delete(phase)
                report.phases_removed += 1
    db.flush()
    return report
