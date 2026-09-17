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
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.inventory import InventoryItem
from app.models.people import Person
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.task import (
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    TASK_TYPE_COMISSIONAMENTO,
    TASK_TYPE_FOTOS_DRIVE,
    TASK_TYPE_INSTALACAO,
    TASK_TYPE_PREPARACAO_INSTALACAO,
    TASK_TYPE_VISITA_TECNICA,
    Task,
)
from app.models.workflow import WorkflowStage
from app.workflow.definition import EXAMPLE_DEFINITION_PATH, apply_definition, load_definition
from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES
from app.services.tasks import ensure_default_tasks_for_project


def _relative_birth_date(days_from_today: int) -> dt.date:
    """Constrói uma data de nascimento cujo dia/mês cai `days_from_today`
    dias a partir de hoje — para que "aniversários próximos" no dashboard
    fique sempre demonstrável, seja qual for o dia em que o seed correr
    (ver requisito explícito: "a página inicial deve ficar demonstrável
    logo depois de correr o seed"). O ano é só um valor plausível — nunca
    usado para calcular idade nesta fase (ver app/services/dashboard.py)."""
    target = dt.date.today() + dt.timedelta(days=days_from_today)
    birth_year = target.year - 30
    try:
        return dt.date(birth_year, target.month, target.day)
    except ValueError:
        # 29 de fevereiro num ano de nascimento sintético não bissexto.
        return dt.date(birth_year, target.month, 28)

# Percurso de obra: o seed usa o processo de EXEMPLO de 18 etapas
# (app/workflow/processo_exemplo.json) — o processo oficial carrega-se de
# um ficheiro local fora do Git (D-052). Códigos do seed genérico antigo
# (6 etapas, antes da D-052), substituídos automaticamente se ainda
# existirem sem progresso.
LEGACY_GENERIC_STAGE_CODES = frozenset(
    {
        "handover.entrega",
        "licenc.registos",
        "visita.tecnica",
        "prep.procurement",
        "obra.execucao",
        "fecho.comissionamento",
    }
)

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
    """Carrega o processo de exemplo numa base sem percurso, ou em vez do
    seed genérico antigo. Nunca toca num percurso já carregado de outra
    forma (ex. o processo oficial via `app.cli.workflow`)."""
    stage_codes = {code for (code,) in db.query(WorkflowStage.code).all()}
    if stage_codes and not stage_codes <= LEGACY_GENERIC_STAGE_CODES:
        return
    apply_definition(db, load_definition(EXAMPLE_DEFINITION_PATH))


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
    resultado)."""
    if db.query(Project).count() > 0:
        return
    today = dt.date.today()
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

    overdue_tasks = _tasks_by_type(ensure_default_tasks_for_project(db, overdue_project))
    overdue_tasks[TASK_TYPE_VISITA_TECNICA].status = STATUS_DONE
    overdue_tasks[TASK_TYPE_VISITA_TECNICA].completed_at = dt.datetime.now(dt.timezone.utc)
    overdue_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].status = STATUS_IN_PROGRESS
    overdue_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].due_date = today - dt.timedelta(days=5)
    overdue_tasks[TASK_TYPE_PREPARACAO_INSTALACAO].assigned_to_person_id = pm_um.id
    overdue_tasks[TASK_TYPE_INSTALACAO].status = STATUS_BLOCKED
    overdue_tasks[TASK_TYPE_INSTALACAO].notes = "Bloqueado à espera de material sintético."

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
    today = dt.date.today()
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


def seed_supplier_and_inventory(db: Session) -> None:
    if db.query(Supplier).count() == 0:
        db.add(Supplier(name="Fornecedor Sintético Lda.", category="material_eletrico", is_preferred=True, lead_time_days=10))
    if db.query(InventoryItem).count() == 0:
        db.add(InventoryItem(sku="SYNTH-INV-001", name="Item de inventário sintético", unit="un", min_stock=5))


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
        seed_supplier_and_inventory(db)
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
