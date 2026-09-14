"""Semente de dados sintéticos para desenvolvimento local e testes.

Nunca contém dados reais — nomes, emails e projetos aqui são todos
fictícios (ver `.gitignore`/regras do repositório: nenhum dado de produção
pode entrar no Git). Cobre deliberadamente o requisito "5 utilizadores
ativos, sem apagar o histórico dos 8 PMs existentes": cria 5 `User` (um por
papel) e mais 3 `Person` sem `User` associado, representando PMs antigos
cujo histórico se preserva mas que já não têm acesso de login.

Utilização:
    python -m app.migration.seed_dev
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import app.models  # noqa: F401  — garante que todas as tabelas estão registadas em Base.metadata
from app.db import Base, SessionLocal, engine
from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.inventory import InventoryItem
from app.models.people import Person
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES

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
SYNTHETIC_ACTIVE_PEOPLE = [
    ("Admin Sintético", "admin.sintetico@example.invalid", "administrador"),
    ("Chefe Sintético", "chefe.sintetico@example.invalid", "chefe_operacoes"),
    ("PM Sintético Um", "pm.um.sintetico@example.invalid", "project_manager"),
    ("Comercial Sintético", "comercial.sintetico@example.invalid", "comercial"),
    ("Financeiro Sintético", "financeiro.sintetico@example.invalid", "financeiro"),
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
    for name, email, role_code in SYNTHETIC_ACTIVE_PEOPLE:
        person = Person(display_name=name, email=email, is_active=True)
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


def seed_sample_projects(db: Session) -> None:
    if db.query(Project).count() > 0:
        return
    pm = db.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    db.add(
        Project(
            name="Instalação Sintética de Demonstração",
            client_name="Cliente Sintético",
            client_contact="Contacto Sintético",
            client_email="cliente.sintetico@example.invalid",
            address="Morada sintética, sem correspondência real",
            lat=38.7,
            lon=-9.1,
            power_kwp=9.9,
            pm_person_id=pm.id,
            is_active=True,
        )
    )
    db.add(
        Project(
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
    )


def seed_supplier_and_inventory(db: Session) -> None:
    if db.query(Supplier).count() == 0:
        db.add(Supplier(name="Fornecedor Sintético Lda.", category="material_eletrico", is_preferred=True, lead_time_days=10))
    if db.query(InventoryItem).count() == 0:
        db.add(InventoryItem(sku="SYNTH-INV-001", name="Item de inventário sintético", unit="un", min_stock=5))


def run_seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        role_objs = seed_catalog(db)
        seed_workflow(db)
        seed_people_and_users(db, role_objs)
        seed_sample_projects(db)
        seed_supplier_and_inventory(db)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
    print("Seed sintético aplicado com sucesso.")
