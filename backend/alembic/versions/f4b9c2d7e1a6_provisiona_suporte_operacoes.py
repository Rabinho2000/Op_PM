"""provisiona o papel de Suporte de Operações e as suas permissões

Revision ID: f4b9c2d7e1a6
Revises: e7c4a1b9d2f0
Create Date: 2026-10-01

A migração copia deliberadamente a matriz relevante do catálogo no momento da
sua criação. Migrações históricas não importam ``app.security.catalog``: uma
alteração posterior do catálogo não pode alterar o significado de um upgrade
ou downgrade já publicado.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

import app.db  # tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = "f4b9c2d7e1a6"
down_revision: Union[str, Sequence[str], None] = "e7c4a1b9d2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVISIONING_TABLE = "support_role_provisioning"

# Cópia literal de ROLE_PERMISSIONS[ROLE_SUPORTE_OPERACOES] em
# app/security/catalog.py. A ordem é mantida para tornar a revisão explícita;
# a BD aplica a unicidade role_id/permission_id.
_SUPPORT_ROLE_PERMISSIONS = (
    "project.view_delegated",
    "workflow.update_progress",
    "task.view_own",
    "task.edit_own",
    "document.view",
    "document.edit",
    "project.view_installation_data",
    "project.edit_installation_data",
    "project.view_licensing_data",
    "project.edit_licensing_data",
    "supplier.view",
    "calendar.view",
    "absence.view_own",
    "absence.manage_own",
)

# Estes são os papéis que, no catálogo desta revisão, recebem
# ``absence.approve``. O Administrador é ``administrador`` no catálogo, não
# um alias de dados.
_ABSENCE_APPROVER_ROLES = ("chefe_operacoes", "administrador")

_PERMISSION_DESCRIPTIONS = {
    "project.view_delegated": "Ver os projetos dos PMs que delegam em mim (Suporte de Operações)",
    "absence.approve": "Aprovar ou rejeitar pedidos de férias",
    "workflow.update_progress": "Marcar subtarefas e pontos de contacto do processo dos projetos visíveis (todos, ou só os próprios como PM)",
    "task.view_own": "Ver tarefas dos projetos próprios (como PM) e tarefas atribuídas a si",
    "task.edit_own": "Criar tarefas atribuídas a si mesmo e editar tarefas que criou ou que lhe estão atribuídas — nunca atribuir/reatribuir a outra pessoa (ver app/security/permissions.py:can_edit_task/can_create_task)",
    "document.view": "Ver biblioteca documental",
    "document.edit": "Anexar/editar documentos",
    "project.view_installation_data": "Ver dados de instalação do projeto",
    "project.edit_installation_data": "Editar dados de instalação do projeto (combinado com o âmbito de project.edit_*)",
    "project.view_licensing_data": "Ver dados de licenciamento do projeto",
    "project.edit_licensing_data": "Editar dados de licenciamento do projeto (combinado com o âmbito de project.edit_*)",
    "supplier.view": "Ver a lista de fornecedores (contactos, tipos de material, localização)",
    "calendar.view": "Ver eventos de calendário/planeamento",
    "absence.view_own": "Ver as próprias férias/ausências",
    "absence.manage_own": "Registar/cancelar as próprias férias",
}


def _tables():
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    roles = sa.table(
        "roles",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=64)),
        sa.column("name", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("id", app.db.GUID()),
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
    )
    return permissions, roles, role_permissions, provisioning


def _ensure_permission(bind, permissions, provisioning, code: str):
    row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
    if row is not None:
        return row[0]

    permission_id = uuid.uuid4()
    bind.execute(
        permissions.insert().values(
            id=permission_id,
            code=code,
            description=_PERMISSION_DESCRIPTIONS[code],
        )
    )
    bind.execute(
        provisioning.insert().values(
            id=uuid.uuid4(),
            kind="permission",
            owned_row_id=permission_id,
            permission_id=permission_id,
            role_id=None,
        )
    )
    return permission_id


def _ensure_role_permission(bind, role_permissions, provisioning, role_id, permission_id) -> None:
    existing = bind.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).first()
    if existing is not None:
        return

    assignment_id = uuid.uuid4()
    bind.execute(
        role_permissions.insert().values(
            id=assignment_id,
            role_id=role_id,
            permission_id=permission_id,
        )
    )
    bind.execute(
        provisioning.insert().values(
            id=uuid.uuid4(),
            kind="role_permission",
            owned_row_id=assignment_id,
            permission_id=permission_id,
            role_id=role_id,
        )
    )


def upgrade() -> None:
    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=True),
        sa.Column("role_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()

    role_row = bind.execute(sa.select(roles.c.id).where(roles.c.code == "suporte_operacoes")).first()
    if role_row is None:
        role_id = uuid.uuid4()
        bind.execute(
            roles.insert().values(
                id=role_id,
                code="suporte_operacoes",
                name="Suporte de Operações",
                description="",
            )
        )
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(),
                kind="role",
                owned_row_id=role_id,
                permission_id=None,
                role_id=None,
            )
        )
    else:
        role_id = role_row[0]

    permission_ids = {
        code: _ensure_permission(bind, permissions, provisioning, code)
        for code in set(_SUPPORT_ROLE_PERMISSIONS) | {"absence.approve"}
    }

    for code in _SUPPORT_ROLE_PERMISSIONS:
        _ensure_role_permission(bind, role_permissions, provisioning, role_id, permission_ids[code])

    for role_code in _ABSENCE_APPROVER_ROLES:
        approver = bind.execute(sa.select(roles.c.id).where(roles.c.code == role_code)).first()
        if approver is not None:
            _ensure_role_permission(
                bind,
                role_permissions,
                provisioning,
                approver[0],
                permission_ids["absence.approve"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()
    user_roles = sa.table(
        "user_roles",
        sa.column("role_id", app.db.GUID()),
    )

    owned = bind.execute(
        sa.select(
            provisioning.c.kind,
            provisioning.c.owned_row_id,
            provisioning.c.permission_id,
            provisioning.c.role_id,
        )
    ).all()

    created_role_ids: set[object] = set()
    created_permission_ids: set[object] = set()
    for kind, owned_row_id, permission_id, role_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission" and permission_id is not None:
            created_permission_ids.add(permission_id)
        elif kind == "role":
            created_role_ids.add(owned_row_id)

    # A permission created here is removed only when no later/pre-existing
    # grant references it. Otherwise keeping it is safer than deleting another
    # actor's role_permission row or violating the foreign key.
    for permission_id in created_permission_ids:
        still_referenced = bind.execute(
            sa.select(role_permissions.c.id)
            .where(role_permissions.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if still_referenced is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    # Do not delete a role that acquired a user or a grant outside this
    # migration. The migration never creates user_roles, but this guard keeps
    # downgrade non-destructive on a live database.
    for role_id in created_role_ids:
        has_user = bind.execute(
            sa.select(user_roles.c.role_id).where(user_roles.c.role_id == role_id).limit(1)
        ).first()
        has_grant = bind.execute(
            sa.select(role_permissions.c.id).where(role_permissions.c.role_id == role_id).limit(1)
        ).first()
        if has_user is None and has_grant is None:
            bind.execute(roles.delete().where(roles.c.id == role_id))

    op.drop_table(_PROVISIONING_TABLE)
