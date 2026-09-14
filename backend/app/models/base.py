from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GUID, new_uuid


class UUIDPk:
    """Chave primária UUID gerada em código — estável entre ambientes e nunca
    dependente da ordem de inserção (ao contrário de um serial autoincrement),
    o que facilita fundir dados de staging/produção sem colisão de IDs."""

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
