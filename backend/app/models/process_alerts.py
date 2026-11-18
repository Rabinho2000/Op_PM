"""Subscrições de alarmes por etapa do processo (um utilizador → etapas do catálogo)."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import GUID, Base
from app.models.base import UUIDPk


class ProcessStageSubscription(UUIDPk, Base):
    __tablename__ = "process_stage_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "stage_id", name="uq_process_stage_subscription"),)

    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    stage_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workflow_stages.id"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
