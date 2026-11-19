"""API de leitura e gestão de feriados."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.holiday import Holiday
from app.schemas.holidays import HolidayCreate, HolidayRead, HolidayUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.holidays import (
    create_holiday,
    deactivate_holiday,
    list_holidays,
    update_holiday,
)
from app.security.guards import require_permission
from app.security.perm import Perm

router = APIRouter(prefix="/api/holidays", tags=["holidays"])


require_holiday_manage = require_permission(
    Perm.HOLIDAY_MANAGE, detail="Sem permissão para gerir feriados", with_reason=True
)


@router.get("", response_model=list[HolidayRead])
def list_holidays_endpoint(
    from_date: dt.date | None = Query(default=None, alias="from"),
    to_date: dt.date | None = Query(default=None, alias="to"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _ctx: AuthContext = Depends(get_auth_context),
) -> list[HolidayRead]:
    if from_date is not None and to_date is not None and to_date < from_date:
        raise HTTPException(status_code=422, detail="A data final do intervalo não pode ser anterior à inicial.")
    holidays = list_holidays(
        db,
        start_date=from_date,
        end_date=to_date,
        include_inactive=include_inactive,
    )
    return [HolidayRead.model_validate(holiday) for holiday in holidays]


@router.post("", response_model=HolidayRead, status_code=201)
def create_holiday_endpoint(
    body: HolidayCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_holiday_manage),
) -> HolidayRead:
    holiday = create_holiday(db, changes=body, ctx=ctx)
    return HolidayRead.model_validate(holiday)


@router.patch("/{holiday_id}", response_model=HolidayRead)
def update_holiday_endpoint(
    holiday_id: uuid.UUID,
    body: HolidayUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_holiday_manage),
) -> HolidayRead:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status_code=404, detail="Feriado não encontrado.")
    updated = update_holiday(db, holiday=holiday, changes=body, ctx=ctx)
    return HolidayRead.model_validate(updated)


@router.delete("/{holiday_id}", response_model=HolidayRead)
def delete_holiday_endpoint(
    holiday_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_holiday_manage),
) -> HolidayRead:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status_code=404, detail="Feriado não encontrado.")
    deactivated = deactivate_holiday(db, holiday=holiday, ctx=ctx)
    return HolidayRead.model_validate(deactivated)
