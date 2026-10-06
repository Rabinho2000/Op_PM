from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.my_process import MyProcessStageRead
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext
from app.services.my_process import list_my_process_stages as build_my_process_stages
from app.utils.timezones import today_lisbon

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/process-stages", response_model=list[MyProcessStageRead])
def list_my_process_stages_endpoint(
    db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> list[MyProcessStageRead]:
    return build_my_process_stages(db, ctx, today_lisbon())
