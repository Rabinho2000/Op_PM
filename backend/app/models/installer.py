"""Instaladores (subempreiteiros) e as suas equipas (D-071).

Um instalador (ex. uma empresa subempreiteira) tem zero ou mais equipas, cada
uma com o seu chefe de equipa. O chefe é uma pessoa **externa** à Solcor: guarda-se
o nome e o telefone, sem `Person` nem login. Uma obra (`Project`) fica ligada ao
instalador e, opcionalmente, a uma das suas equipas — a base de dados garante que
a equipa pertence ao instalador (chave estrangeira composta em `projects`).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk


class Installer(UUIDPk, TimestampMixin, Base):
    __tablename__ = "installers"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Nome sem maiúsculas/acentos: dois instaladores não podem diferir só nisso.
    name_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    teams: Mapped[list["InstallerTeam"]] = relationship(
        back_populates="installer", order_by="InstallerTeam.name_key", lazy="selectin"
    )


class InstallerTeam(UUIDPk, TimestampMixin, Base):
    __tablename__ = "installer_teams"
    __table_args__ = (
        # Alvo da chave estrangeira composta de `projects` (instalador, equipa).
        UniqueConstraint("installer_id", "id", name="uq_installer_team_pair"),
        UniqueConstraint("installer_id", "name_key", name="uq_installer_team_name"),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("installers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_key: Mapped[str] = mapped_column(String(128), nullable=False)
    leader_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    leader_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    installer: Mapped[Installer] = relationship(back_populates="teams")
