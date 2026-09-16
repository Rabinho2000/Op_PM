from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models.identity import User
from app.security.catalog import ROLES
from app.security.current_user import get_auth_context, get_current_user
from app.security.permissions import AuthContext

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: User = Depends(get_current_user), ctx: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "person_id": str(user.person_id),
        "display_name": user.person.display_name if user.person else user.email,
        "roles": sorted(ctx.role_codes),
        "role_labels": [ROLES.get(code, code) for code in sorted(ctx.role_codes)],
        "permissions": sorted(ctx.permission_codes),
    }
