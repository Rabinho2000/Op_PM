"""Dados sintéticos adicionais para a demonstração local (D-051).

Corre sempre DEPOIS de `app.migration.seed_dev.run_seed()` e só acrescenta
dados — nunca altera nem remove os projetos/pessoas do seed de
desenvolvimento (vários testes dependem dos nomes exatos desses). Serve
só para a demonstração ter volume e variedade suficientes (projetos em
todas as fases, tarefas atrasadas/urgentes/desta semana, fotografias
pendentes, férias, aniversários, histórico).

Tudo aqui é fictício: nomes marcados "Sintético/Sintética", emails
`*.invalid`, moradas sem correspondência real. Nenhum `User` novo é
criado — os 5 utilizadores continuam a ser os do seed de desenvolvimento
(D-003); as pessoas extra são técnicos sem conta de login.

**Só corre com `APP_ENV=local`** (`assert_demo_allowed_environment`) —
mais restrito do que o seed de desenvolvimento, que também aceita `test`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.audit.log import record_project_change, record_task_change
from app.models.absence import TYPE_FERIAS, TYPE_OUTRO, Absence
from app.models.people import Person
from app.models.project import Project, ProjectStageProgress, ProjectSubtaskProgress
from app.models.task import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_URGENT,
    STATUS_BLOCKED,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_TODO,
    TASK_TYPE_COMISSIONAMENTO,
    TASK_TYPE_FOTOS_DRIVE,
    TASK_TYPE_INSTALACAO,
    TASK_TYPE_PREPARACAO_INSTALACAO,
    TASK_TYPE_VISITA_TECNICA,
    Task,
)
from app.models.workflow import WorkflowStage, WorkflowSubtask
from app.services.tasks import ensure_default_tasks_for_project
from app.utils.timezones import today_lisbon

DEMO_ALLOWED_ENVIRONMENTS = frozenset({"local"})

# Marcador de idempotência: se este projeto já existe, o seed demo já correu.
DEMO_MARKER_PROJECT_NAME = "Escola Sintética do Vale — Cobertura Fotovoltaica"

DEMO_TECHNICIANS = [
    # (nome, email, desvio em dias do próximo aniversário)
    ("Técnica Sintética Ana", "tecnica.ana.sintetica@example.invalid", 3),
    ("Técnico Sintético Bruno", "tecnico.bruno.sintetico@example.invalid", 12),
]

PM_UM = "PM Sintético Um"
CHEFE = "Chefe Sintético"
ADMIN = "Admin Sintético"
LEGADO_DOIS = "PM Sintético Legado Dois"
LEGADO_TRES = "PM Sintético Legado Três"
TEC_ANA = "Técnica Sintética Ana"
TEC_BRUNO = "Técnico Sintético Bruno"


class DemoSeedNotAllowedError(RuntimeError):
    """Mensagem sempre segura para mostrar diretamente a quem corre o comando."""


def assert_demo_allowed_environment(app_env: str) -> None:
    if app_env not in DEMO_ALLOWED_ENVIRONMENTS:
        raise DemoSeedNotAllowedError(
            f"dados de demonstração recusados em APP_ENV={app_env!r} — a demonstração "
            "com dados sintéticos só existe em APP_ENV=local (ver docs/MVP_DEMO.md)."
        )


@dataclass
class TaskSpec:
    status: str = STATUS_TODO
    due_in_days: int | None = None
    assignee: str | None = None
    priority: str | None = None
    completed_days_ago: int | None = None
    notes: str = ""


@dataclass
class CustomTaskSpec:
    title: str
    priority: str
    status: str = STATUS_TODO
    due_in_days: int | None = None
    assignee: str | None = None
    description: str = ""


@dataclass
class ProjectSpec:
    name: str
    client_name: str | None
    pm: str | None
    start_in_days: int | None
    power_kwp: float | None
    lat: float | None = None
    lon: float | None = None
    with_contact: bool = True
    with_email: bool = True
    notes: str = ""
    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    custom_tasks: list[CustomTaskSpec] = field(default_factory=list)
    history: list[tuple[str, str | None, str, str]] = field(default_factory=list)  # (campo, antes, depois, autor)


def _done(days_ago: int = 20, **kw) -> TaskSpec:
    return TaskSpec(status=STATUS_DONE, completed_days_ago=days_ago, **kw)


DEMO_PROJECTS: list[ProjectSpec] = [
    ProjectSpec(
        name=DEMO_MARKER_PROJECT_NAME,
        client_name="Agrupamento Sintético do Vale",
        pm=PM_UM,
        start_in_days=-40,
        power_kwp=48.6,
        lat=40.64,
        lon=-8.65,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(35, assignee=TEC_ANA),
            TASK_TYPE_PREPARACAO_INSTALACAO: _done(10, assignee=PM_UM),
            TASK_TYPE_INSTALACAO: TaskSpec(STATUS_IN_PROGRESS, due_in_days=2, assignee=TEC_BRUNO, priority=PRIORITY_HIGH),
            TASK_TYPE_COMISSIONAMENTO: TaskSpec(due_in_days=9, assignee=PM_UM),
            TASK_TYPE_FOTOS_DRIVE: TaskSpec(due_in_days=12, assignee=TEC_ANA),
        },
        history=[("notes", "", "Instalação em duas fases por causa do calendário escolar.", CHEFE)],
    ),
    ProjectSpec(
        name="Armazém Logístico Sintético Norte",
        client_name="Logística Sintética, S.A.",
        pm=CHEFE,
        start_in_days=8,
        power_kwp=120.0,
        lat=41.24,
        lon=-8.52,
        tasks={
            TASK_TYPE_VISITA_TECNICA: TaskSpec(due_in_days=1, assignee=TEC_ANA, priority=PRIORITY_HIGH),
        },
    ),
    ProjectSpec(
        name="Hotel Sintético Atlântico",
        client_name="Hotelaria Sintética Atlântico",
        pm=PM_UM,
        start_in_days=-120,
        power_kwp=64.2,
        lat=38.69,
        lon=-9.42,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(110),
            TASK_TYPE_PREPARACAO_INSTALACAO: _done(90),
            TASK_TYPE_INSTALACAO: _done(60),
            TASK_TYPE_COMISSIONAMENTO: _done(30),
            TASK_TYPE_FOTOS_DRIVE: _done(1, assignee=PM_UM),
        },
        history=[("role", None, "Instalação concluída e entregue ao cliente.", PM_UM)],
    ),
    ProjectSpec(
        name="Quinta Sintética das Oliveiras",
        client_name="Sociedade Agrícola Sintética",
        pm=LEGADO_TRES,
        start_in_days=-75,
        power_kwp=33.0,
        lat=39.23,
        lon=-7.98,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(70),
            TASK_TYPE_PREPARACAO_INSTALACAO: _done(45),
            TASK_TYPE_INSTALACAO: _done(15),
            TASK_TYPE_COMISSIONAMENTO: TaskSpec(due_in_days=-3, assignee=CHEFE, priority=PRIORITY_HIGH),
        },
    ),
    ProjectSpec(
        name="Clínica Sintética Central",
        client_name="Clínica Sintética Central, Lda.",
        pm=PM_UM,
        start_in_days=21,
        power_kwp=18.9,
        lat=38.52,
        lon=-8.89,
        tasks={TASK_TYPE_VISITA_TECNICA: TaskSpec(due_in_days=12, assignee=PM_UM)},
    ),
    ProjectSpec(
        name="Pavilhão Desportivo Sintético",
        client_name="Associação Desportiva Sintética",
        pm=None,
        start_in_days=27,
        power_kwp=75.5,
        lat=40.21,
        lon=-8.43,
        with_email=False,
        notes="Aguarda atribuição de PM.",
    ),
    ProjectSpec(
        name="Supermercado Sintético Sol Nascente",
        client_name="Distribuição Sintética Sol Nascente",
        pm=CHEFE,
        start_in_days=-30,
        power_kwp=92.4,
        lat=37.02,
        lon=-7.93,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(25, assignee=TEC_BRUNO),
            TASK_TYPE_PREPARACAO_INSTALACAO: TaskSpec(STATUS_IN_PROGRESS, due_in_days=3, assignee=CHEFE),
            TASK_TYPE_INSTALACAO: TaskSpec(STATUS_BLOCKED, due_in_days=14, notes="Bloqueado: aguarda licença sintética."),
            TASK_TYPE_FOTOS_DRIVE: _done(22, assignee=TEC_BRUNO, notes="Fotografias da visita técnica já na Drive."),
        },
    ),
    ProjectSpec(
        name="Fábrica Sintética de Cerâmica",
        client_name="Cerâmica Sintética Industrial",
        pm=PM_UM,
        start_in_days=-90,
        power_kwp=210.0,
        lat=40.35,
        lon=-8.59,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(85),
            TASK_TYPE_PREPARACAO_INSTALACAO: _done(60),
            TASK_TYPE_INSTALACAO: _done(20),
            TASK_TYPE_COMISSIONAMENTO: _done(0, assignee=PM_UM),
            TASK_TYPE_FOTOS_DRIVE: TaskSpec(due_in_days=-1, assignee=PM_UM, priority=PRIORITY_URGENT),
        },
    ),
    ProjectSpec(
        name="Condomínio Sintético Jardim",
        client_name="Administração Sintética de Condomínios",
        pm=PM_UM,
        start_in_days=-12,
        power_kwp=24.0,
        lat=41.55,
        lon=-8.42,
        tasks={TASK_TYPE_VISITA_TECNICA: TaskSpec(STATUS_IN_PROGRESS, due_in_days=0, assignee=TEC_ANA)},
        custom_tasks=[
            CustomTaskSpec(
                "Confirmar acesso à cobertura com a administração",
                PRIORITY_URGENT,
                due_in_days=1,
                assignee=PM_UM,
                description="Sem acesso confirmado não é possível agendar a visita.",
            )
        ],
    ),
    ProjectSpec(
        name="Adega Cooperativa Sintética",
        client_name="Adega Cooperativa Sintética, CRL",
        pm=LEGADO_DOIS,
        start_in_days=-50,
        power_kwp=56.8,
        lat=38.57,
        lon=-7.91,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(40),
            TASK_TYPE_PREPARACAO_INSTALACAO: TaskSpec(
                STATUS_BLOCKED, due_in_days=-8, assignee=CHEFE, notes="Material em atraso no fornecedor sintético."
            ),
            TASK_TYPE_FOTOS_DRIVE: _done(38, notes="Fotografias da visita técnica já na Drive."),
        },
    ),
    ProjectSpec(
        name="Centro de Dia Sintético",
        client_name="Instituição Sintética de Solidariedade",
        pm=CHEFE,
        start_in_days=5,
        power_kwp=12.3,
        lat=None,
        lon=None,
        with_contact=False,
        tasks={TASK_TYPE_VISITA_TECNICA: TaskSpec(due_in_days=4, assignee=TEC_BRUNO)},
    ),
    ProjectSpec(
        name="Oficina Sintética Horizonte",
        client_name="Oficina Sintética Horizonte, Lda.",
        pm=PM_UM,
        start_in_days=-20,
        power_kwp=15.0,
        lat=39.74,
        lon=-8.81,
        tasks={
            TASK_TYPE_VISITA_TECNICA: _done(15, assignee=TEC_ANA),
            TASK_TYPE_PREPARACAO_INSTALACAO: _done(2, assignee=PM_UM),
            TASK_TYPE_INSTALACAO: TaskSpec(STATUS_IN_PROGRESS, due_in_days=4, assignee=TEC_BRUNO),
            TASK_TYPE_FOTOS_DRIVE: TaskSpec(due_in_days=5, assignee=TEC_ANA, priority=PRIORITY_LOW),
        },
        custom_tasks=[
            CustomTaskSpec("Encomendar estrutura de fixação adicional", PRIORITY_HIGH, STATUS_IN_PROGRESS, 6, CHEFE),
        ],
    ),
    ProjectSpec(
        name="Piscina Municipal Sintética",
        client_name="Município Sintético",
        pm=CHEFE,
        start_in_days=-3,
        power_kwp=140.0,
        lat=39.29,
        lon=-7.43,
        tasks={TASK_TYPE_VISITA_TECNICA: TaskSpec(due_in_days=-1, assignee=TEC_ANA, priority=PRIORITY_HIGH)},
    ),
    ProjectSpec(
        name="Restaurante Sintético Maré",
        client_name="Restauração Sintética Maré",
        pm=PM_UM,
        start_in_days=2,
        power_kwp=9.6,
        lat=37.1,
        lon=-8.67,
        tasks={TASK_TYPE_VISITA_TECNICA: TaskSpec(due_in_days=2, assignee=PM_UM)},
        custom_tasks=[CustomTaskSpec("Enviar proposta de calendário ao cliente", PRIORITY_LOW, due_in_days=6, assignee=PM_UM)],
    ),
]


def _people_by_name(db: Session) -> dict[str, Person]:
    return {p.display_name: p for p in db.query(Person).all()}


def _birth_date_in(days: int, today: dt.date) -> dt.date:
    target = today + dt.timedelta(days=days)
    try:
        return dt.date(target.year - 32, target.month, target.day)
    except ValueError:
        return dt.date(target.year - 32, target.month, 28)


def _completed_at(days_ago: int, today: dt.date) -> dt.datetime:
    day = today - dt.timedelta(days=days_ago)
    return dt.datetime(day.year, day.month, day.day, 16, 30, tzinfo=dt.timezone.utc)


def _seed_technicians(db: Session, today: dt.date) -> None:
    existing = {p.display_name for p in db.query(Person).all()}
    for name, email, birthday_in in DEMO_TECHNICIANS:
        if name in existing:
            continue
        db.add(Person(display_name=name, email=email, is_active=True, birth_date=_birth_date_in(birthday_in, today)))
    db.flush()


def _seed_projects(db: Session, today: dt.date) -> None:
    people = _people_by_name(db)
    chefe = people[CHEFE]
    for spec in DEMO_PROJECTS:
        slug = spec.name.split("—")[0].strip().lower().replace(" ", ".")
        project = Project(
            name=spec.name,
            client_name=spec.client_name,
            client_contact=f"Contacto {spec.client_name}" if spec.with_contact and spec.client_name else None,
            client_email=f"{slug}@example.invalid" if spec.with_email else None,
            address="Morada sintética, sem correspondência real",
            lat=spec.lat,
            lon=spec.lon,
            power_kwp=spec.power_kwp,
            pm_person_id=people[spec.pm].id if spec.pm else None,
            start_date=today + dt.timedelta(days=spec.start_in_days) if spec.start_in_days is not None else None,
            is_active=True,
            notes=spec.notes,
        )
        db.add(project)
        db.flush()

        tasks = {t.task_type: t for t in ensure_default_tasks_for_project(db, project)}
        db.flush()
        for task_type, task_spec in spec.tasks.items():
            task = tasks[task_type]
            task.status = task_spec.status
            task.notes = task_spec.notes
            if task_spec.due_in_days is not None:
                task.due_date = today + dt.timedelta(days=task_spec.due_in_days)
            if task_spec.assignee:
                task.assigned_to_person_id = people[task_spec.assignee].id
            if task_spec.priority:
                task.priority = task_spec.priority
            if task_spec.status == STATUS_DONE:
                task.completed_at = _completed_at(task_spec.completed_days_ago or 0, today)
            if task_spec.status != STATUS_TODO:
                record_task_change(
                    db,
                    task_id=task.id,
                    field_name="status",
                    old_value=STATUS_TODO,
                    new_value=task_spec.status,
                    source="ui",
                    changed_by_person_id=people[spec.pm].id if spec.pm in (PM_UM, CHEFE) else chefe.id,
                    note="Registo sintético de demonstração.",
                )

        for custom in spec.custom_tasks:
            db.add(
                Task(
                    project_id=project.id,
                    title=custom.title,
                    task_type="custom",
                    description=custom.description,
                    priority=custom.priority,
                    status=custom.status,
                    assigned_to_person_id=people[custom.assignee].id if custom.assignee else None,
                    due_date=today + dt.timedelta(days=custom.due_in_days) if custom.due_in_days is not None else None,
                    created_by_person_id=chefe.id,
                )
            )

        for field_name, old_value, new_value, author in spec.history:
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                source="ui",
                changed_by_person_id=people[author].id,
                note="Registo sintético de demonstração.",
            )
            setattr(project, field_name, new_value)
    db.flush()


def _seed_absences(db: Session, today: dt.date) -> None:
    people = _people_by_name(db)
    entries = [
        (TEC_ANA, 12, 16, TYPE_FERIAS, "Férias sintéticas."),
        (TEC_BRUNO, 1, 1, TYPE_OUTRO, "Formação sintética de segurança em coberturas."),
        (ADMIN, 25, 29, TYPE_FERIAS, "Férias sintéticas."),
        (PM_UM, -40, -35, TYPE_FERIAS, "Férias sintéticas já gozadas."),
    ]
    for name, start, end, kind, note in entries:
        person = people[name]
        db.add(
            Absence(
                person_id=person.id,
                start_date=today + dt.timedelta(days=start),
                end_date=today + dt.timedelta(days=end),
                type=kind,
                note=note,
                created_by_person_id=people[CHEFE].id,
            )
        )


def _business_days_elapsed(start: dt.date, today: dt.date) -> int:
    """Número do dia útil de hoje no calendário do projeto (0 se ainda não
    começou) — mesma contagem de app/services/workflow.py."""
    if today < start:
        return 0
    days = 0
    current = start
    while current <= today:
        if current.weekday() < 5:
            days += 1
        current += dt.timedelta(days=1)
    return days


def _seed_workflow_progress(db: Session, today: dt.date) -> None:
    """Progresso sintético no percurso de obra (D-052), coerente com a data
    de início de cada projeto: etapas cujo prazo já passou ficam feitas, a
    etapa em curso fica a meio — e um em cada três projetos fica com uma
    etapa em atraso e um contacto por fazer, para a demonstração mostrar
    alertas."""
    stages = db.query(WorkflowStage).order_by(WorkflowStage.sort_order).all()
    subs_by_stage: dict = {}
    for sub in db.query(WorkflowSubtask).order_by(WorkflowSubtask.sort_order).all():
        subs_by_stage.setdefault(sub.stage_id, []).append(sub)
    people = _people_by_name(db)
    names = [spec.name for spec in DEMO_PROJECTS]
    projects = db.query(Project).filter(Project.name.in_(names)).all()
    for project in sorted(projects, key=lambda p: names.index(p.name)):
        if project.start_date is None:
            continue
        elapsed = _business_days_elapsed(project.start_date, today)
        if elapsed == 0:
            continue
        index = names.index(project.name)
        finished = all(t.status == STATUS_DONE for t in db.query(Task).filter(Task.project_id == project.id, Task.task_type != "custom"))
        lagging = not finished and index % 3 == 1
        author = project.pm_person_id or people[CHEFE].id
        done_at = dt.datetime.combine(today, dt.time(9, 0), tzinfo=dt.timezone.utc)
        lag_stage = None
        if lagging:
            overdue = [s for s in stages if (s.planned_end_offset_days or 0) < elapsed]
            lag_stage = overdue[-1].id if overdue else None
        for stage in stages:
            subs = subs_by_stage.get(stage.id, [])
            start_day = stage.planned_start_offset_days or 0
            end_day = stage.planned_end_offset_days or 0
            if finished or end_day < elapsed:
                count = len(subs)
            elif start_day <= elapsed:
                count = len(subs) // 2
            else:
                count = 0
            if stage.id == lag_stage:
                count = max(0, len(subs) - 1)
            for sub in subs[:count]:
                db.add(
                    ProjectSubtaskProgress(
                        project_id=project.id, subtask_id=sub.id, done=True, done_at=done_at, done_by_person_id=author
                    )
                )
            if stage.has_contact_checkpoint and stage.contact_day and (finished or stage.contact_day < elapsed):
                if stage.id == lag_stage:
                    continue
                db.add(
                    ProjectStageProgress(
                        project_id=project.id,
                        stage_id=stage.id,
                        contact_done=True,
                        contact_done_at=done_at,
                        contact_done_by_person_id=author,
                    )
                )
    db.flush()


def seed_demo_data(db: Session, today: dt.date | None = None) -> bool:
    """Acrescenta os dados de demonstração. Idempotente: devolve False (e
    não escreve nada) se já tiverem sido aplicados. Não faz commit."""
    if db.query(Project).filter(Project.name == DEMO_MARKER_PROJECT_NAME).count() > 0:
        return False
    today = today or today_lisbon()
    _seed_technicians(db, today)
    _seed_projects(db, today)
    _seed_absences(db, today)
    _seed_workflow_progress(db, today)
    db.flush()
    return True
