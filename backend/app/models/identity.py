"""Identidade, papéis e permissões.

Separação deliberada entre `User` (conta de login, no máximo os utilizadores
ativos decididos pelo negócio) e `Person` (qualquer ser humano referenciado
no histórico operacional — incluindo PMs antigos sem conta de login). Isto
cumpre o requisito "até 5 utilizadores ativos, mas não pode apagar o
histórico dos 8 PMs existentes": um `Person` sem `User` associado continua a
aparecer no histórico e nos projetos antigos, só não consegue autenticar-se.

Papéis (a partir de docs/PRODUCT_SCOPE.md): administrador, chefe_operacoes,
project_manager, comercial, financeiro. São dados em tabela, não um enum
fixo em código, para poderem ser ajustados sem migração de schema.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, GUID
from app.models.base import TimestampMixin, UUIDPk


class Role(UUIDPk, TimestampMixin, Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")


class Permission(UUIDPk, TimestampMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")


class RolePermission(UUIDPk, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    role_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("permissions.id"), nullable=False
    )

    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship()


class User(UUIDPk, TimestampMixin, Base):
    """Conta de login. `person_id` liga sempre a um `Person` — a identidade
    "humana" e o "acesso ao sistema" são conceitos distintos de propósito."""

    __tablename__ = "users"

    person_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("people.id"), unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    entra_object_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="user")
    roles: Mapped[list["UserRole"]] = relationship(back_populates="user")


class UserRole(UUIDPk, TimestampMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("roles.id"), nullable=False)

    user: Mapped["User"] = relationship(back_populates="roles")
    role: Mapped["Role"] = relationship()


class AuthAuditLog(UUIDPk, Base):
    """Auditoria de eventos de autenticação — hoje só a ligação
    "just-in-time" automática entre um email de token Entra ID e um
    `User.entra_object_id` ainda não ligado (D-029). Append-only, como
    `ProjectHistory` — sem `updated_at` de propósito, nunca é alterada
    depois de criada."""

    __tablename__ = "auth_audit_log"

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)  # ex.: 'jit_link_by_email'
    detail: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
