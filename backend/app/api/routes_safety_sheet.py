from __future__ import annotations

import html
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.schemas.safety_sheet import (
    SafetySheetHistoryRead,
    SafetySheetPrefillRead,
    SafetySheetRead,
    SafetySheetUpdate,
    SafetySheetWorkerRead,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_edit_project, can_view_project
from app.services.projects import get_visible_project
from app.services.safety_sheet import (
    SafetySheetVersionConflict,
    SafetySheetWorkerPersonNotFound,
    get_safety_sheet,
    list_safety_sheet_history,
    prefill_safety_sheet_workers,
    safety_sheet_snapshot,
    save_safety_sheet,
)

router = APIRouter(prefix="/api/projects", tags=["safety-sheet"])

_ROOF_LABELS = {
    "telha_ceramica": "Telha cerâmica",
    "chapa_sandwich": "Chapa sandwich",
    "chapa_simples_fibrocimento": "Chapa simples / fibrocimento",
    "laje_terraco": "Laje / terraço",
    "solo": "Solo",
    "outro": "Outro",
}
_ACCESS_LABELS = {
    "escada": "Escada",
    "andaime": "Andaime",
    "plataforma_elevatoria": "Plataforma elevatória",
    "outro": "Outro",
}
_RISK_LABELS = {
    "queda_altura": "Queda em altura",
    "eletrico_dc_ac": "Risco elétrico DC/AC",
    "fragil_claraboias": "Cobertura frágil / claraboias",
    "condicoes_meteorologicas": "Condições meteorológicas",
    "outro": "Outro",
}
_MEASURE_LABELS = {
    "linha_vida": "Linha de vida",
    "arnes": "Arnês",
    "capacete": "Capacete",
    "luvas_dieleticas": "Luvas dielétricas",
    "calcado": "Calçado de segurança",
    "guarda_corpos": "Guarda-corpos",
    "outro": "Outro",
}


def _get_project_or_404(db: Session, project_id: uuid.UUID, ctx: AuthContext):
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return project


def _require_edit(ctx: AuthContext, project) -> None:
    if not can_view_project(ctx, project):
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    if not (can_edit_project(ctx, project) or ctx.has_permission("project.safety_sheet.edit")):
        raise HTTPException(status_code=403, detail="Sem permissão para editar a ficha de segurança.")


def _escape(value) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value), quote=True).replace("\n", "<br>")


def _checked_values(values: list[str], labels: dict[str, str]) -> str:
    if not values:
        return "—"
    return ", ".join(html.escape(labels.get(value, value), quote=True) for value in values)


def _print_html(project, sheet_data: dict, pm_name: str | None) -> str:
    roof = _ROOF_LABELS.get(sheet_data["roof_type"], sheet_data["roof_type"]) if sheet_data["roof_type"] else None
    access = (
        _ACCESS_LABELS.get(sheet_data["access_method"], sheet_data["access_method"])
        if sheet_data["access_method"]
        else None
    )
    height = f"{sheet_data['approximate_height_m']} m" if sheet_data["approximate_height_m"] is not None else None
    power = f"{project.power_kwp:g} kWp" if project.power_kwp is not None else None
    workers = "".join(f"<li>{_escape(worker['name'])}</li>" for worker in sheet_data["workers"]) or "<li>—</li>"
    project_name = _escape(project.name)
    return f"""<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ficha de segurança — {project_name}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
* {{ box-sizing: border-box; }}
body {{ color: #17202a; font: 10.5pt/1.4 Arial, sans-serif; margin: 0; }}
h1 {{ font-size: 19pt; margin: 0 0 3mm; }}
h2 {{ border-bottom: 1px solid #8795a1; font-size: 12pt; margin: 7mm 0 2mm; padding-bottom: 1mm; }}
.project {{ color: #455a64; margin-bottom: 5mm; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #b0bec5; padding: 2.2mm; text-align: left; vertical-align: top; }}
th {{ background: #edf2f4; width: 31%; }}
ul {{ margin: 1mm 0; padding-left: 5mm; }}
footer {{ border-top: 1px solid #b0bec5; color: #607d8b; font-size: 8pt; margin-top: 8mm; padding-top: 2mm; }}
</style>
</head>
<body>
<h1>Ficha de segurança da obra</h1>
<div class="project"><strong>{project_name}</strong><br>
Morada: {_escape(project.address)}<br>
PM: {_escape(pm_name)}<br>
Potência: {_escape(power)}</div>
<h2>Condições e acesso</h2>
<table><tbody>
<tr><th>Tipo de telhado</th><td>{_escape(roof)}{f" — {_escape(sheet_data['roof_other'])}" if sheet_data['roof_other'] else ""}</td></tr>
<tr><th>Altura aproximada</th><td>{_escape(height)}</td></tr>
<tr><th>Acesso</th><td>{_escape(access)}{f" — {_escape(sheet_data['access_other'])}" if sheet_data['access_other'] else ""}</td></tr>
<tr><th>Riscos</th><td>{_checked_values(sheet_data['risks'], _RISK_LABELS)}{f" — {_escape(sheet_data['risk_other'])}" if sheet_data['risk_other'] else ""}</td></tr>
<tr><th>Medidas / EPI</th><td>{_checked_values(sheet_data['safety_measures'], _MEASURE_LABELS)}{f" — {_escape(sheet_data['measure_other'])}" if sheet_data['measure_other'] else ""}</td></tr>
</tbody></table>
<h2>Equipa e contactos</h2>
<table><tbody>
<tr><th>Trabalhadores</th><td><ul>{workers}</ul></td></tr>
<tr><th>Responsável de segurança em obra</th><td>{_escape(sheet_data['safety_responsible'])}</td></tr>
<tr><th>Contactos de emergência / hospital mais próximo</th><td>{_escape(sheet_data['emergency_contacts'])}</td></tr>
<tr><th>Datas dos trabalhos</th><td>{_escape(sheet_data['work_start_date'])} — {_escape(sheet_data['work_end_date'])}</td></tr>
<tr><th>Observações</th><td>{_escape(sheet_data['observations'])}</td></tr>
</tbody></table>
<footer>Ficha de segurança · Versão {sheet_data['version']}</footer>
</body>
</html>"""


@router.get("/{project_id}/safety-sheet/print", response_class=Response)
def print_safety_sheet_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> Response:
    project = _get_project_or_404(db, project_id, ctx)
    sheet_data = safety_sheet_snapshot(project_id, get_safety_sheet(db, project_id))
    pm = db.get(Person, project.pm_person_id) if project.pm_person_id else None
    return Response(content=_print_html(project, sheet_data, pm.display_name if pm else None), media_type="text/html")


@router.get("/{project_id}/safety-sheet/workers-prefill", response_model=SafetySheetPrefillRead)
def prefill_safety_sheet_workers_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> SafetySheetPrefillRead:
    project = _get_project_or_404(db, project_id, ctx)
    return SafetySheetPrefillRead(
        project_id=project_id,
        workers=[SafetySheetWorkerRead.model_validate(worker) for worker in prefill_safety_sheet_workers(db, project)],
    )


@router.get("/{project_id}/safety-sheet/history", response_model=list[SafetySheetHistoryRead])
def safety_sheet_history_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[SafetySheetHistoryRead]:
    _get_project_or_404(db, project_id, ctx)
    return [SafetySheetHistoryRead.model_validate(entry.__dict__) for entry in list_safety_sheet_history(db, project_id)]


@router.get("/{project_id}/safety-sheet", response_model=SafetySheetRead)
def get_safety_sheet_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> SafetySheetRead:
    _get_project_or_404(db, project_id, ctx)
    return SafetySheetRead.model_validate(safety_sheet_snapshot(project_id, get_safety_sheet(db, project_id)))


@router.put("/{project_id}/safety-sheet", response_model=SafetySheetRead)
def update_safety_sheet_endpoint(
    project_id: uuid.UUID,
    body: SafetySheetUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> SafetySheetRead:
    project = _get_project_or_404(db, project_id, ctx)
    _require_edit(ctx, project)
    try:
        sheet = save_safety_sheet(
            db,
            project_id=project_id,
            values=body.model_dump(),
            changed_by_person_id=ctx.person_id,
        )
    except SafetySheetVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "current_version": exc.current_version},
        ) from exc
    except SafetySheetWorkerPersonNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SafetySheetRead.model_validate(safety_sheet_snapshot(project_id, sheet))
