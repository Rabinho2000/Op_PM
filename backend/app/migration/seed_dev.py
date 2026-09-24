"""Semente de dados sintéticos para desenvolvimento local e testes.

Nunca contém dados reais — nomes, emails e projetos aqui são todos
fictícios (ver `.gitignore`/regras do repositório: nenhum dado de produção
pode entrar no Git). Cobre deliberadamente o requisito "5 utilizadores
ativos, sem apagar o histórico dos 8 PMs existentes": cria 5 `User` (um por
papel) e mais 3 `Person` sem `User` associado, representando PMs antigos
cujo histórico se preserva mas que já não têm acesso de login.

Utilização:
    python -m app.migration.seed_dev

**Nunca corre em staging/produção** (docs/STAGING_RUNBOOK.md): mesma
barreira de `HARDENED_ENVIRONMENTS` já usada em `app/config.py`
(D-020/D-032) e em `app/cli/ingest_staging.py` (D-037) — este seed cria
utilizadores/pessoas/projetos sintéticos (`*.invalid`), pensados só para
`local`/`test`. Staging usa pessoas/utilizadores reais desde o início
(provisionados manualmente — ver `docs/STAGING_RUNBOOK.md` secção
"Utilizadores") e só recebe projetos via `app.cli.ingest_staging`
(D-037), nunca via este seed.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

import app.models  # noqa: F401  — garante que todas as tabelas estão registadas em Base.metadata
from app.config import HARDENED_ENVIRONMENTS, get_settings
from app.db import Base, SessionLocal, engine
from app.models.absence import TYPE_BAIXA_MEDICA, TYPE_FERIAS, Absence
from app.models.calendar import CalendarEvent
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.inventory import (
    CENTRAL_LOCATION_CODE,
    LOCATION_TYPE_CENTRAL,
    MOVEMENT_CONSUMO,
    MOVEMENT_ENTRADA,
    MOVEMENT_ENTREGA,
    MOVEMENT_LIBERTA_RESERVA,
    MOVEMENT_RESERVA,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    ProjectMaterialRequirement,
)
from app.models.map_ops import PickupPoint, ProjectIssue
from app.models.people import Person
from app.models.performance import GoalPeriod
from app.models.project import Project
from app.models.project_data import ProjectCommunicationData, ProjectInstallationData, ProjectLicensingData
from app.models.supplier import Supplier
from app.models.task import (
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    STATUS_TODO,
    TASK_CATEGORY_FIELD,
    TASK_CATEGORY_MATERIAL,
    TASK_TYPE_COMISSIONAMENTO,
    TASK_TYPE_FOTOS_DRIVE,
    TASK_TYPE_INSTALACAO,
    TASK_TYPE_PREPARACAO_INSTALACAO,
    TASK_TYPE_VISITA_TECNICA,
    Task,
)
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES
from app.services.tasks import ensure_default_tasks_for_project
from app.utils.timezones import today_lisbon


def _relative_birth_date(days_from_today: int) -> dt.date:
    """Constrói uma data de nascimento cujo dia/mês cai `days_from_today`
    dias a partir de hoje — para que "aniversários próximos" no dashboard
    fique sempre demonstrável, seja qual for o dia em que o seed correr
    (ver requisito explícito: "a página inicial deve ficar demonstrável
    logo depois de correr o seed"). O ano é só um valor plausível — nunca
    usado para calcular idade nesta fase (ver app/services/dashboard.py)."""
    target = today_lisbon() + dt.timedelta(days=days_from_today)
    birth_year = target.year - 30
    try:
        return dt.date(birth_year, target.month, target.day)
    except ValueError:
        # 29 de fevereiro num ano de nascimento sintético não bissexto.
        return dt.date(birth_year, target.month, 28)

# Fases/etapas genéricas — mesma forma do processo legado (6 fases), mas com
# títulos e subtarefas de exemplo, não o texto proprietário do processo real.
GENERIC_WORKFLOW = [
    {
        "code": "handover",
        "name": "Handover e arranque",
        "color": "#2E75B6",
        "stages": [
            {
                "code": "handover.entrega",
                "title": "Obra entregue às Operações (exemplo)",
                "role": "chefe_operacoes",
                "subtasks": ["Confirmar receção do processo"],
            },
        ],
    },
    {
        "code": "licenc",
        "name": "Licenciamento e legalização",
        "color": "#C0392B",
        "stages": [
            {
                "code": "licenc.registos",
                "title": "Registos legais (exemplo)",
                "role": "chefe_operacoes",
                "subtasks": ["Registo de exemplo A", "Registo de exemplo B"],
            },
        ],
    },
    {
        "code": "visita",
        "name": "Visita técnica e subempreiteiro",
        "color": "#E07B39",
        "stages": [
            {
                "code": "visita.tecnica",
                "title": "Visita técnica (exemplo)",
                "role": "project_manager",
                "subtasks": ["Preencher formulário", "Registo fotográfico"],
            },
        ],
    },
    {
        "code": "prep",
        "name": "Preparação e procurement",
        "color": "#7C58B8",
        "stages": [
            {
                "code": "prep.procurement",
                "title": "Procurement (exemplo)",
                "role": "project_manager",
                "subtasks": ["Material principal", "Transporte e entrega"],
            },
        ],
    },
    {
        "code": "obra",
        "name": "Obra",
        "color": "#4F8A3B",
        "stages": [
            {
                "code": "obra.execucao",
                "title": "Execução de obra (exemplo)",
                "role": "project_manager",
                "subtasks": ["Início de obra", "Acompanhamento"],
            },
        ],
    },
    {
        "code": "fecho",
        "name": "Fecho e comissionamento",
        "color": "#0E93B8",
        "stages": [
            {
                "code": "fecho.comissionamento",
                "title": "Comissionamento (exemplo)",
                "role": "project_manager",
                "subtasks": ["Registo fotográfico obrigatório", "Relatório de comissionamento"],
            },
        ],
    },
]

# 5 utilizadores ativos (um por papel) + 3 PMs "legados" sem conta de login.
# O 4º elemento é o desvio (em dias, a partir de hoje) da data de
# nascimento sintética — cobre deliberadamente vários cenários do
# dashboard: aniversário mesmo hoje, daqui a poucos dias, dentro da janela
# de 30 dias, e fora dela (ver _relative_birth_date acima).
SYNTHETIC_ACTIVE_PEOPLE = [
    ("Admin Sintético", "admin.sintetico@example.invalid", "administrador", 5),
    ("Chefe Sintético", "chefe.sintetico@example.invalid", "chefe_operacoes", 20),
    ("PM Sintético Um", "pm.um.sintetico@example.invalid", "project_manager", -10),
    ("Comercial Sintético", "comercial.sintetico@example.invalid", "comercial", 0),
    ("Financeiro Sintético", "financeiro.sintetico@example.invalid", "financeiro", 200),
]
SYNTHETIC_LEGACY_PMS_WITHOUT_LOGIN = [
    "PM Sintético Legado Dois",
    "PM Sintético Legado Três",
    "PM Sintético Legado Quatro",
]


def seed_catalog(db: Session) -> dict[str, Role]:
    role_objs: dict[str, Role] = {}
    for code, name in ROLES.items():
        role = db.query(Role).filter(Role.code == code).one_or_none()
        if role is None:
            role = Role(code=code, name=name)
            db.add(role)
            db.flush()
        role_objs[code] = role

    perm_objs: dict[str, Permission] = {}
    for code, description in PERMISSIONS.items():
        perm = db.query(Permission).filter(Permission.code == code).one_or_none()
        if perm is None:
            perm = Permission(code=code, description=description)
            db.add(perm)
            db.flush()
        perm_objs[code] = perm

    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        role = role_objs[role_code]
        existing = {
            rp.permission_id
            for rp in db.query(RolePermission).filter(RolePermission.role_id == role.id).all()
        }
        for perm_code in perm_codes:
            perm = perm_objs[perm_code]
            if perm.id not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    return role_objs


def seed_workflow(db: Session) -> None:
    if db.query(Phase).count() > 0:
        return
    for phase_order, phase_def in enumerate(GENERIC_WORKFLOW):
        phase = Phase(
            code=phase_def["code"], name=phase_def["name"], color_hex=phase_def["color"], sort_order=phase_order
        )
        db.add(phase)
        db.flush()
        for stage_order, stage_def in enumerate(phase_def["stages"]):
            stage = WorkflowStage(
                phase_id=phase.id,
                code=stage_def["code"],
                title=stage_def["title"],
                responsible_role_code=stage_def["role"],
                sort_order=stage_order,
            )
            db.add(stage)
            db.flush()
            for sub_order, sub_title in enumerate(stage_def["subtasks"]):
                db.add(
                    WorkflowSubtask(
                        stage_id=stage.id,
                        code=f"{stage_def['code']}.{sub_order}",
                        title=sub_title,
                        sort_order=sub_order,
                    )
                )


def seed_people_and_users(db: Session, role_objs: dict[str, Role]) -> None:
    if db.query(Person).count() > 0:
        return
    for name, email, role_code, birth_offset_days in SYNTHETIC_ACTIVE_PEOPLE:
        person = Person(
            display_name=name, email=email, is_active=True, birth_date=_relative_birth_date(birth_offset_days)
        )
        db.add(person)
        db.flush()
        user = User(person_id=person.id, email=email, is_active=True)
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role_objs[role_code].id))

    for name in SYNTHETIC_LEGACY_PMS_WITHOUT_LOGIN:
        # Pessoa preservada no histórico, sem User associado — sem acesso de
        # login, mas presente em `people` para qualquer FK antiga continuar
        # a resolver-se corretamente.
        db.add(Person(display_name=name, email=None, is_active=False, legacy_ref=name.lower().replace(" ", "_")))
    db.flush()  # SessionLocal tem autoflush=False — sem isto, seed_sample_projects não veria estas pessoas


def _tasks_by_type(created: list[Task]) -> dict[str, Task]:
    return {t.task_type: t for t in created}


def seed_sample_projects(db: Session) -> None:
    """Cria os 2 projetos sintéticos originais (nomes usados literalmente
    em vários testes — nunca renomear/remover) mais um conjunto adicional
    de projetos, cada um com a checklist padrão de tarefas (ver
    app/services/tasks.py:ensure_default_tasks_for_project) em estados
    diferentes, para a página inicial ficar demonstrável logo depois de
    correr o seed (todos os indicadores do dashboard têm pelo menos um
    resultado).

    Cobre também os 5 cenários do mapa operacional (attention — ver
    docs/DECISIONS.md D-058), sem projetos dedicados extra:
    - green: "Instalação Sintética F — PM Legado" (sem tarefa field/
      material aberta).
    - yellow (tarefa operacional): "Instalação Sintética A — Início
      Próximo" (tarefa category=field aberta, sem atraso).
    - red (tarefa operacional atrasada): "Instalação Sintética B —
      Atrasada" (tarefa category=material, aberta e atrasada).
    - yellow (material físico, sem tarefa operacional):
      "Instalação Sintética de Demonstração" (reserva de cabo já
      existente via seed_map_and_inventory — só visível com
      inventory.view).
    - sem coordenadas: "Instalação Sintética Incompleta" (lat/lon=None).
    """
    if db.query(Project).count() > 0:
        return
    today = today_lisbon()
    pm_um = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    chefe = db.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    pm_legado = db.query(Person).filter(Person.display_name == "PM Sintético Legado Dois").one()

    demo = Project(
        name="Instalação Sintética de Demonstração",
        client_name="Cliente Sintético",
        client_contact="Contacto Sintético",
        client_email="cliente.sintetico@example.invalid",
        address="Morada sintética, sem correspondência real",
        lat=38.7,
        lon=-9.1,
        power_kwp=9.9,
        pm_person_id=pm_um.id,
        is_active=True,
    )
    db.add(demo)

    incompleta = Project(
        name="Instalação Sintética Incompleta",
        client_name=None,
        client_contact=None,
        client_email=None,
        address=None,
        lat=None,
        lon=None,
        power_kwp=None,
        pm_person_id=None,
        is_active=True,
        notes="Projeto sintético deliberadamente incompleto, para testar a preservação de campos em falta.",
    )
    db.add(incompleta)

    starting_soon = Project(
        name="Instalação Sintética A — Início Próximo",
        client_name="Cliente Sintético A",
        client_contact="Contacto Sintético A",
        client_email="cliente.a.sintetico@example.invalid",
        address="Morada sintética A",
        lat=41.15,
        lon=-8.6,
        power_kwp=15.4,
        pm_person_id=pm_um.id,
        start_date=today + dt.timedelta(days=15),
        is_active=True,
    )
    db.add(starting_soon)

    overdue_project = Project(
        name="Instalação Sintética B — Atrasada",
        client_name="Cliente Sintético B",
        client_contact="Contacto Sintético B",
        client_email="cliente.b.sintetico@example.invalid",
        address="Morada sintética B",
        lat=39.4,
        lon=-8.2,
        power_kwp=22.0,
        pm_person_id=pm_um.id,
        start_date=today - dt.timedelta(days=60),
        is_active=True,
    )
    db.add(overdue_project)

    photos_pending_project = Project(
        name="Instalação Sintética C — Fotos Pendentes",
        client_name="Cliente Sintético C",
        client_contact="Contacto Sintético C",
        client_email="cliente.c.sintetico@example.invalid",
        address="Morada sintética C",
        lat=38.0,
        lon=-9.4,
        power_kwp=11.2,
        pm_person_id=pm_um.id,
        start_date=today - dt.timedelta(days=20),
        is_active=True,
    )
    db.add(photos_pending_project)

    missing_pm_project = Project(
        name="Instalação Sintética E — Sem PM Atribuído",
        client_name="Cliente Sintético E",
        client_contact="Contacto Sintético E",
        client_email="cliente.e.sintetico@example.invalid",
        address="Morada sintética E",
        lat=40.2,
        lon=-8.4,
        power_kwp=8.0,
        pm_person_id=None,
        start_date=today + dt.timedelta(days=3),
        is_active=True,
    )
    db.add(missing_pm_project)

    legacy_pm_project = Project(
        name="Instalação Sintética F — PM Legado",
        client_name="Cliente Sintético F",
        client_contact="Contacto Sintético F",
        client_email="cliente.f.sintetico@example.invalid",
        address="Morada sintética F",
        lat=37.1,
        lon=-7.9,
        power_kwp=30.5,
        pm_person_id=pm_legado.id,
        start_date=today - dt.timedelta(days=100),
        is_active=True,
    )
    db.add(legacy_pm_project)

    urgent_project = Project(
        name="Instalação Sintética G — Trabalho Urgente",
        client_name="Cliente Sintético G",
        client_contact="Contacto Sintético G",
        client_email="cliente.g.sintetico@example.invalid",
        address="Morada sintética G",
        lat=41.5,
        lon=-8.4,
        power_kwp=18.3,
        pm_person_id=pm_um.id,
        start_date=today - dt.timedelta(days=5),
        is_active=True,
    )
    db.add(urgent_project)

    inactive_project = Project(
        name="Instalação Sintética H — Inativa",
        client_name="Cliente Sintético H",
        pm_person_id=None,
        is_active=False,
        notes="Projeto sintético inativo — nunca deve aparecer nas contagens do dashboard.",
    )
    db.add(inactive_project)

    db.flush()  # garante project.id antes de criar tarefas

    # --- Tarefas padrão por projeto, depois ajustadas para cada cenário ---
    ensure_default_tasks_for_project(db, demo)
    ensure_default_tasks_for_project(db, incompleta)

    starting_soon_tasks = _tasks_by_type(ensure_default_tasks_for_project(db, starting_soon))
    starting_soon_tasks[TASK_TYPE_VISITA_TECNICA].due_date = today + dt.timedelta(days=18)
    starting_soon_tasks[TASK_TYPE_VISITA_TECNICA].assigned_to_person_id = pm_um.id
    # Tarefa operacional (category=field) aberta, sem atraso/bloqueio/
    # urgência — demonstra attention='yellow' no mapa operacional (D-058)
    # só por existir dívida de campo, distinta do cenário de material.
    db.add(
        Task(
            project_id=starting_soon.id,
            title="Verificar acesso ao telhado antes da visita técnica",
            task_type="custom",
            category=TASK_CATEGORY_FIELD,
            description="Tarefa sintética de campo — confirma attention='yellow' no mapa (D-058).",
            status=STATUS_TODO,
            priority="medium",
            due_date=today + dt.timedelta(days=20),
            assigned_to_person_id=pm_um.id,
            created_by_person_id=chefe.id,
        )
    )

    overdue_tasks = _tasks_by_type(ensure_default_tasks_for_project(db, overdue_project))
    overdue_tasks[TASK_TYPE_VISITA_TECNICA].status = STATUS_DONE
    overdue_tasks[TASK_TYPE_VISITA_TECNICA].completed_at = dt.datetime.now(dt.timezone.utc)
    overdue_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].status = STATUS_IN_PROGRESS
    overdue_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].due_date = today - dt.timedelta(days=5)
    overdue_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].assigned_to_person_id = pm_um.id
    overdue_tasks[TASK_TYPE_INSTALACAO].status = STATUS_BLOCKED
    overdue_tasks[TASK_TYPE_INSTALACAO].notes = "Bloqueado à espera de material sintético."
    # Tarefa operacional (category=material) atrasada — demonstra
    # attention='red' no mapa operacional (D-058): tarefa field/material
    # aberta e atrasada (Europe/Lisbon). A tarefa de workflow acima
    # (INSTALACAO, bloqueada) nunca conta para attention por desenho —
    # só field/material contam.
    db.add(
        Task(
            project_id=overdue_project.id,
            title="Recolher módulos sintéticos em falta no armazém",
            task_type="custom",
            category=TASK_CATEGORY_MATERIAL,
            description="Tarefa sintética de material, atrasada — confirma attention='red' no mapa (D-058).",
            status=STATUS_TODO,
            priority="high",
            due_date=today - dt.timedelta(days=3),
            assigned_to_person_id=pm_um.id,
            created_by_person_id=chefe.id,
        )
    )

    photos_tasks = _tasks_by_type(ensure_default_tasks_for_project(db, photos_pending_project))
    for task_type in (TASK_TYPE_VISITA_TECNICA, TASK_TYPE_PREPARACAO_INSTALACAO, TASK_TYPE_INSTALACAO):
        photos_tasks[task_type].status = STATUS_DONE
        photos_tasks[task_type].completed_at = dt.datetime.now(dt.timezone.utc)
    photos_tasks[TASK_TYPE_COMISSIONAMENTO].status = STATUS_DONE
    photos_tasks[TASK_TYPE_COMISSIONAMENTO].completed_at = dt.datetime.now(dt.timezone.utc)
    photos_tasks[TASK_TYPE_COMISSIONAMENTO].due_date = today  # também conta como "esta semana"
    photos_tasks[TASK_TYPE_FOTOS_DRIVE].assigned_to_person_id = chefe.id
    # fotos_drive fica 'todo' de propósito — aciona o aviso persistente.

    missing_pm_tasks = _tasks_by_type(ensure_default_tasks_for_project(db, missing_pm_project))
    missing_pm_tasks[TASK_TYPE_VISITA_TECNICA].due_date = today + dt.timedelta(days=2)  # esta semana

    legacy_tasks = _tasks_by_type(ensure_default_tasks_for_project(db, legacy_pm_project))
    legacy_tasks[TASK_TYPE_VISITA_TECNICA].status = STATUS_DONE
    legacy_tasks[TASK_TYPE_VISITA_TECNICA].completed_at = dt.datetime.now(dt.timezone.utc)
    legacy_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].status = STATUS_DONE
    legacy_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].completed_at = dt.datetime.now(dt.timezone.utc)
    legacy_tasks[TASK_TYPE_COMISSIONAMENTO].status = STATUS_CANCELLED
    legacy_tasks[TASK_TYPE_COMISSIONAMENTO].notes = "Cliente sintético cancelou o comissionamento agendado."

    ensure_default_tasks_for_project(db, urgent_project)
    db.add(
        Task(
            project_id=urgent_project.id,
            title="Resolver reclamação urgente do cliente sintético",
            task_type="custom",
            description="Tarefa ad-hoc sintética, fora da checklist padrão.",
            priority="urgent",
            status=STATUS_IN_PROGRESS,
            assigned_to_person_id=pm_um.id,
            due_date=today + dt.timedelta(days=3),
            created_by_person_id=chefe.id,
        )
    )

    ensure_default_tasks_for_project(db, inactive_project)


def seed_absences(db: Session) -> None:
    if db.query(Absence).count() > 0:
        return
    today = today_lisbon()
    pm_um = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    chefe = db.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    comercial = db.query(Person).filter(Person.display_name == "Comercial Sintético").one()
    financeiro = db.query(Person).filter(Person.display_name == "Financeiro Sintético").one()

    db.add(
        Absence(
            person_id=pm_um.id,
            start_date=today - dt.timedelta(days=2),
            end_date=today + dt.timedelta(days=3),
            type=TYPE_FERIAS,
            note="Férias sintéticas em curso.",
            created_by_person_id=pm_um.id,
        )
    )
    db.add(
        Absence(
            person_id=chefe.id,
            start_date=today + dt.timedelta(days=10),
            end_date=today + dt.timedelta(days=17),
            type=TYPE_FERIAS,
            note="Férias sintéticas próximas (dentro de 30 dias).",
            created_by_person_id=chefe.id,
        )
    )
    db.add(
        Absence(
            person_id=comercial.id,
            start_date=today + dt.timedelta(days=45),
            end_date=today + dt.timedelta(days=50),
            type=TYPE_FERIAS,
            note="Férias sintéticas fora da janela de 30 dias — não deve aparecer como 'próxima'.",
            created_by_person_id=comercial.id,
        )
    )
    db.add(
        Absence(
            person_id=financeiro.id,
            start_date=today + dt.timedelta(days=5),
            end_date=today + dt.timedelta(days=6),
            type=TYPE_BAIXA_MEDICA,
            note="Ausência sintética cancelada — nunca deve aparecer no dashboard.",
            status="cancelada",
            created_by_person_id=financeiro.id,
        )
    )


def seed_map_and_inventory(db: Session) -> None:
    """Localização central IdealMinde, fornecedores, ponto de recolha,
    pendências de obra, e o cenário exato de inventário pedido para a
    demonstração (ver docs/PLAN_OPERATIONS_MVP.md secção 10):

        Stock físico central: 95 km
        Stock disponível:     80 km
        Reservado (Projeto A - demo): 15 km
        Consumido (Projeto A - demo): 5 km

    Alcançado com: 100 km entram -> reserva 20 -> consome 5 -> liberta 10
    -> reserva mais 10. Escrito diretamente como `InventoryMovement`
    (mesmo resultado que chamar app/services/inventory.py, sem os commits
    intermédios que o serviço faz a cada operação — aqui só há um commit
    no fim de run_seed())."""
    if db.query(Supplier).count() > 0:
        return

    pm_um = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    chefe = db.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    demo = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    starting_soon = db.query(Project).filter(Project.name.like("%Início Próximo%")).first()

    supplier_a = Supplier(
        name="Fornecedor Sintético de Material Elétrico Lda.",
        category="material_eletrico",
        contact="Contacto Sintético do Fornecedor A",
        email="fornecedor.a.sintetico@example.invalid",
        address="Morada sintética do Fornecedor A",
        lat=41.15,
        lon=-8.61,
        is_preferred=True,
        lead_time_days=10,
        materials="Cabo DC, conectores MC4, quadros elétricos",
        is_active=True,
    )
    supplier_b = Supplier(
        name="Fornecedor Sintético de Estruturas Lda.",
        category="estruturas",
        contact="Contacto Sintético do Fornecedor B",
        email="fornecedor.b.sintetico@example.invalid",
        address="Morada sintética do Fornecedor B",
        lat=40.98,
        lon=-8.42,
        is_preferred=False,
        lead_time_days=15,
        materials="Estruturas de fixação, parafusaria",
        is_active=True,
    )
    db.add_all([supplier_a, supplier_b])
    db.flush()

    db.add(
        PickupPoint(
            name="Ponto de Recolha Sintético Central",
            supplier_id=supplier_a.id,
            address="Morada sintética do ponto de recolha",
            lat=41.10,
            lon=-8.55,
            schedule="Dias úteis, 9h-18h",
            contact="Contacto Sintético do Armazém",
            materials="Cabo DC, conectores MC4",
            is_active=True,
        )
    )

    central = InventoryLocation(
        code=CENTRAL_LOCATION_CODE, name="Armazém IdealMinde", location_type=LOCATION_TYPE_CENTRAL
    )
    db.add(central)

    cable = InventoryItem(
        sku="CABO-DC-6MM", name="Cabo solar DC 6mm²", unit="km", min_stock="10.000", preferred_supplier_id=supplier_a.id
    )
    connectors = InventoryItem(sku="MC4-PAR", name="Par de conectores MC4", unit="un", min_stock="50.000")
    breaker = InventoryItem(sku="DISJ-DC-16A", name="Disjuntor DC 16A", unit="un", min_stock="5.000")
    rail = InventoryItem(
        sku="TRILHO-AL-4M", name="Trilho de alumínio 4m", unit="un", min_stock="20.000", preferred_supplier_id=supplier_b.id
    )
    clamp = InventoryItem(sku="GRAMPO-MEIO", name="Grampo intermédio", unit="un", min_stock="100.000")
    db.add_all([cable, connectors, breaker, rail, clamp])
    db.flush()

    db.add_all(
        [
            InventoryMovement(
                item_id=cable.id,
                movement_type=MOVEMENT_ENTRADA,
                quantity="100.000",
                location_id=central.id,
                reference="Entrada sintética inicial de cabo DC.",
                created_by_person_id=chefe.id,
            ),
            InventoryMovement(
                item_id=cable.id,
                movement_type=MOVEMENT_RESERVA,
                quantity="20.000",
                project_id=demo.id,
                reference="Reserva sintética para a instalação de demonstração.",
                created_by_person_id=pm_um.id,
            ),
            InventoryMovement(
                item_id=cable.id,
                movement_type=MOVEMENT_CONSUMO,
                quantity="5.000",
                project_id=demo.id,
                reference="Consumo sintético durante a instalação.",
                created_by_person_id=pm_um.id,
            ),
            InventoryMovement(
                item_id=cable.id,
                movement_type=MOVEMENT_LIBERTA_RESERVA,
                quantity="10.000",
                project_id=demo.id,
                reference="Libertação sintética de reserva sobrante.",
                created_by_person_id=pm_um.id,
            ),
            InventoryMovement(
                item_id=cable.id,
                movement_type=MOVEMENT_RESERVA,
                quantity="10.000",
                project_id=demo.id,
                reference="Segunda reserva sintética — fase seguinte da instalação.",
                created_by_person_id=pm_um.id,
            ),
            InventoryMovement(
                item_id=connectors.id,
                movement_type=MOVEMENT_ENTRADA,
                quantity="200.000",
                location_id=central.id,
                created_by_person_id=chefe.id,
            ),
            InventoryMovement(
                item_id=breaker.id,
                movement_type=MOVEMENT_ENTRADA,
                quantity="2.000",
                location_id=central.id,
                created_by_person_id=chefe.id,
            ),
        ]
    )

    # Material fisicamente na instalação de demonstração (D-064): o "material
    # no local" do mapa deixou de ser o saldo reservado e passou a vir de
    # entregas/recolhas — sem esta entrega o projeto deixava de ser amarelo
    # por material. 15 km entregues (coincide com os 15 reservados líquidos
    # deste cenário, mas os dois saldos são independentes).
    db.add(
        InventoryMovement(
            item_id=cable.id,
            movement_type=MOVEMENT_ENTREGA,
            quantity="15.000",
            project_id=demo.id,
            reference="Entrega sintética de cabo DC à instalação de demonstração.",
            created_by_person_id=pm_um.id,
        )
    )

    db.add(
        ProjectMaterialRequirement(
            project_id=demo.id,
            item_id=cable.id,
            quantity_required="30.000",
            notes="Necessidade sintética de cabo DC para a instalação de demonstração.",
            created_by_person_id=pm_um.id,
        )
    )
    # Item propositadamente sem stock nenhum, para demonstrar "material em
    # falta" com o stock central insuficiente para cobrir a necessidade.
    db.add(
        ProjectMaterialRequirement(
            project_id=demo.id,
            item_id=breaker.id,
            quantity_required="10.000",
            notes="Necessidade sintética acima do stock disponível — demonstra material em falta.",
            created_by_person_id=pm_um.id,
        )
    )

    db.add(
        ProjectIssue(
            project_id=demo.id,
            description="Painéis ainda em obra — falta concluir a fixação da última fileira.",
            category="obra",
            priority="high",
            status="aberta",
            assigned_to_person_id=pm_um.id,
            lat=demo.lat,
            lon=demo.lon,
            created_by_person_id=chefe.id,
        )
    )
    if starting_soon is not None:
        db.add(
            ProjectIssue(
                project_id=starting_soon.id,
                description="Documentação de licenciamento em falta antes do início da obra.",
                category="documentacao",
                priority="medium",
                status="aberta",
                lat=starting_soon.lat,
                lon=starting_soon.lon,
                created_by_person_id=chefe.id,
            )
        )

    db.add(
        ProjectInstallationData(
            project_id=demo.id,
            client_nif="123456789",
            contact_person_name="Contacto Sintético da Instalação",
            contact_person_role="Proprietário",
            contact_email="contacto.instalacao.sintetico@example.invalid",
            contact_phone="912345678",
            address=demo.address,
            district="Porto",
            municipality="Porto",
            power_kwp=demo.power_kwp,
            panel_count=24,
            panel_power_wp=450,
            inverters="1x inversor híbrido sintético 10kW",
            batteries="1x bateria sintética 10kWh",
            has_backup=True,
            installation_type="Autoconsumo com armazenamento",
            injection_type="Injeção parcial na rede",
            notes="Dados de instalação sintéticos para demonstração.",
        )
    )
    db.add(
        ProjectLicensingData(
            project_id=demo.id,
            upac_number="UPAC-SINT-0001",
            dgeg_number="DGEG-SINT-0001",
            licensing_status="registado",
            registration_date=today_lisbon() - dt.timedelta(days=60),
            installer="Instalador Sintético Lda.",
            annual_production_kwh=14500.0,
            comments="Licenciamento sintético para demonstração.",
        )
    )
    db.add(
        ProjectCommunicationData(
            project_id=demo.id,
            operator="Operador Sintético",
            gsm_m2m_number="912000000",
            communication_status="ativo",
            notes="Dados de comunicação/M2M sintéticos — nunca contêm credenciais.",
        )
    )


def seed_calendar_events(db: Session) -> None:
    """Eventos de calendário sintéticos, ligados a tarefas reais dos
    projetos de demonstração (ver docs/MAP_AND_PLANNING.md) — para a
    página /planning já mostrar dados ao abrir, tal como as outras áreas
    do MVP de Operações."""
    if db.query(CalendarEvent).count() > 0:
        return
    today = today_lisbon()
    pm_um = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    chefe = db.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    demo = db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    starting_soon = db.query(Project).filter(Project.name.like("%Início Próximo%")).first()

    def _at(days_from_today: int, hour: int, minute: int = 0) -> dt.datetime:
        return dt.datetime.combine(today + dt.timedelta(days=days_from_today), dt.time(hour, minute))

    visita_demo = (
        db.query(Task).filter(Task.project_id == demo.id, Task.task_type == TASK_TYPE_VISITA_TECNICA).first()
    )
    events = [
        CalendarEvent(
            project_id=demo.id,
            task_id=visita_demo.id if visita_demo else None,
            assigned_to_person_id=pm_um.id,
            title="Visita técnica sintética — Instalação de Demonstração",
            starts_at=_at(2, 9, 30),
            ends_at=_at(2, 11, 0),
            status="aprovado",
        ),
        CalendarEvent(
            project_id=demo.id,
            assigned_to_person_id=chefe.id,
            title="Reunião sintética de acompanhamento de obra",
            starts_at=_at(-1, 14, 0),
            ends_at=_at(-1, 15, 0),
            status="publicado",
        ),
    ]
    if starting_soon is not None:
        comissionamento = (
            db.query(Task)
            .filter(Task.project_id == starting_soon.id, Task.task_type == TASK_TYPE_COMISSIONAMENTO)
            .first()
        )
        events.append(
            CalendarEvent(
                project_id=starting_soon.id,
                task_id=comissionamento.id if comissionamento else None,
                assigned_to_person_id=pm_um.id,
                title="Comissionamento sintético agendado",
                starts_at=_at(5, 10, 0),
                ends_at=_at(5, 12, 0),
                status="rascunho",
            )
        )
    db.add_all(events)


def seed_performance_goals(db: Session) -> None:
    if db.query(GoalPeriod).count() > 0:
        return
    chefe = db.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    pm_um = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    year = today_lisbon().year
    quarter = (today_lisbon().month - 1) // 3 + 1

    db.add_all(
        [
            GoalPeriod(
                period_type="year",
                year=year,
                metric="installations",
                target_value="40.000",
                scope="company",
                created_by_person_id=chefe.id,
                notes="Meta anual sintética de instalações concluídas.",
            ),
            GoalPeriod(
                period_type="year",
                year=year,
                metric="kwp",
                target_value="500.000",
                scope="company",
                created_by_person_id=chefe.id,
                notes="Meta anual sintética de potência instalada (kWp).",
            ),
            GoalPeriod(
                period_type="quarter",
                year=year,
                quarter=quarter,
                metric="installations",
                target_value="10.000",
                scope="pm",
                pm_person_id=pm_um.id,
                created_by_person_id=chefe.id,
                notes="Meta trimestral sintética individual do PM Um.",
            ),
        ]
    )


class SeedNotAllowedError(RuntimeError):
    """Erro de negócio conhecido — mensagem sempre segura para mostrar
    diretamente a quem corre o comando."""


def assert_seed_allowed_environment(app_env: str) -> None:
    """Barreira contra dados sintéticos em staging/produção. Separada de
    `run_seed()` para ser testável sem depender do cache de
    `get_settings()` (mesmo padrão de
    `app.cli.ingest_staging.assert_staging_only_environment`)."""
    if app_env in HARDENED_ENVIRONMENTS:
        raise SeedNotAllowedError(
            f"seed sintético recusado em APP_ENV={app_env!r} — este seed cria utilizadores, "
            "pessoas e projetos fictícios (*.invalid), só para local/test. Em staging/produção, "
            "os 5 utilizadores são provisionados manualmente (docs/STAGING_RUNBOOK.md secção "
            "\"Utilizadores\") e os projetos chegam só via app.cli.ingest_staging (D-037)."
        )


def run_seed() -> None:
    assert_seed_allowed_environment(get_settings().app_env)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        role_objs = seed_catalog(db)
        seed_workflow(db)
        seed_people_and_users(db, role_objs)
        seed_sample_projects(db)
        seed_absences(db)
        seed_map_and_inventory(db)
        seed_calendar_events(db)
        seed_performance_goals(db)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    try:
        run_seed()
    except SeedNotAllowedError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("Seed sintético aplicado com sucesso.")
