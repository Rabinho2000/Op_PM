"""Verificação do provisionamento do papel de Suporte de Operações."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.db import engine
from app.models.identity import Permission, Role, RolePermission, UserRole
from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLE_SUPORTE_OPERACOES


@pytest.mark.skipif(
    "support_role_provisioning" not in inspect(engine).get_table_names(),
    reason="exige uma base preparada por alembic upgrade head",
)
def test_head_migration_provisions_support_role_with_catalog_permissions(db_session):
    role = db_session.query(Role).filter(Role.code == ROLE_SUPORTE_OPERACOES).one()
    assert role.name == "Suporte de Operações"

    permission_rows = (
        db_session.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id)
        .all()
    )
    permission_codes = {permission.code for permission in permission_rows}
    assert permission_codes == set(ROLE_PERMISSIONS[ROLE_SUPORTE_OPERACOES])
    assert {permission.code: permission.description for permission in permission_rows} == {
        code: PERMISSIONS[code] for code in ROLE_PERMISSIONS[ROLE_SUPORTE_OPERACOES]
    }

    assert (
        db_session.query(UserRole)
        .filter(UserRole.role_id == role.id)
        .count()
        == 0
    )

    tracked_kinds = {
        kind
        for (kind,) in db_session.execute(
            text("SELECT kind FROM support_role_provisioning")
        ).all()
    }
    assert {"role", "permission", "role_permission"} <= tracked_kinds
