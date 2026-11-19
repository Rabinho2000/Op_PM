"""Cálculos determinísticos e operações de calendário de feriados."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models.holiday import Holiday
from app.schemas.holidays import HolidayCreate, HolidayUpdate
from app.security.permissions import AuthContext
from app.security.perm import Perm


def easter_sunday(year: int) -> dt.date:
    """Devolve o Domingo de Páscoa no calendário gregoriano (computus de Meeus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def list_holidays(
    db: Session,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    include_inactive: bool = False,
) -> list[Holiday]:
    query = db.query(Holiday)
    if start_date is not None:
        query = query.filter(Holiday.date >= start_date)
    if end_date is not None:
        query = query.filter(Holiday.date <= end_date)
    if not include_inactive:
        query = query.filter(Holiday.is_active.is_(True))
    return query.order_by(Holiday.date.asc(), Holiday.name.asc(), Holiday.id.asc()).all()


def create_holiday(db: Session, *, changes: HolidayCreate, ctx: AuthContext) -> Holiday:
    ctx.require(Perm.HOLIDAY_MANAGE)
    holiday = Holiday(date=changes.date, name=changes.name, scope=changes.scope, is_active=True)
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


def update_holiday(db: Session, *, holiday: Holiday, changes: HolidayUpdate, ctx: AuthContext) -> Holiday:
    ctx.require(Perm.HOLIDAY_MANAGE)
    for field, value in changes.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(holiday, field, value)
    db.commit()
    db.refresh(holiday)
    return holiday


def deactivate_holiday(db: Session, *, holiday: Holiday, ctx: AuthContext) -> Holiday:
    ctx.require(Perm.HOLIDAY_MANAGE)
    holiday.is_active = False
    db.commit()
    db.refresh(holiday)
    return holiday
