"""Payment milestone API for projects."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.project_payments import ProjectPaymentMilestoneRead, ProjectPaymentMilestoneUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied
from app.services.project_payments import (
    InvalidPaymentMilestone,
    ProjectPaymentsNotFound,
    get_project_payment_milestones,
    set_project_payment_milestone,
)

router = APIRouter(prefix="/api/projects", tags=["project-payments"])


@router.get("/{project_id}/payments", response_model=list[ProjectPaymentMilestoneRead])
def get_project_payments_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectPaymentMilestoneRead]:
    try:
        return get_project_payment_milestones(db, ctx=ctx, project_id=project_id)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="Sem permissão para ver os pagamentos deste projeto.") from exc
    except ProjectPaymentsNotFound as exc:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.") from exc


@router.put(
    "/{project_id}/payments/{milestone}",
    response_model=ProjectPaymentMilestoneRead,
)
def set_project_payment_endpoint(
    project_id: uuid.UUID,
    milestone: str,
    body: ProjectPaymentMilestoneUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectPaymentMilestoneRead:
    try:
        return set_project_payment_milestone(
            db,
            ctx=ctx,
            project_id=project_id,
            milestone=milestone,
            received=body.received,
        )
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail="Sem permissão para editar os pagamentos deste projeto.") from exc
    except ProjectPaymentsNotFound as exc:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.") from exc
    except InvalidPaymentMilestone as exc:
        raise HTTPException(status_code=422, detail=f"Marco de pagamento inválido: {exc}.") from exc
