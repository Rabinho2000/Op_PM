"""Catálogo do processo (fases → etapas → subtarefas) e delegações de suporte,
carregados a partir de JSON (D-073).

O processo real da Solcor é interno: **não entra no repositório**. O ficheiro é
gerado a partir do `solcor-gestao.html` por `scripts/extract_process_from_legacy.py`
para uma pasta fora do Git e carregado por `python -m app.cli.load_process`.
Os testes e o seed usam um processo genérico com a mesma forma
(`app/migration/synthetic_process.json`).

Formato do JSON:
    {"phases": [{"code", "name", "color"}, …],
     "stages": [{"code", "phase", "title", "responsible", "depends_on",
                 "start_day", "end_day", "contact": {"day","kind","note"} | null,
                 "note", "subtasks": ["…", …]}, …]}

A carga é **idempotente por `code`** e nunca apaga: atualiza o que existe e cria o
que falta. Os códigos das subtarefas são `<etapa>.<índice a partir de 0>`, iguais às
chaves do `done` do legado (`"2.0"` = 1.ª subtarefa da etapa 2) — a migração do
progresso (PR 6) faz a correspondência sem tabelas intermédias.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.people import Person
from app.models.workflow import Phase, SupportDelegation, WorkflowStage, WorkflowSubtask
from app.utils.text import normalize_key

# Como cada responsável do legado é resolvido, por projeto (ver app/services/process.py):
# (regra, código do papel, texto a mostrar). Um responsável desconhecido é um erro:
# nunca se adivinha.
RESPONSIBLE_RULES: dict[str, tuple[str, str | None, str]] = {
    "Comercial": ("role", "comercial", "Comercial"),
    "Sales Support": ("role", "comercial", "Sales Support"),
    "Duarte": ("role", "chefe_operacoes", "Chefe do departamento"),
    "PM": ("pm", None, "PM do projeto"),
    "Bárbara": ("support_delegate", None, "Suporte"),
    "VM": ("installer", None, "Subempreiteiro"),
    "CE": ("team_leader", None, "Chefe de equipa"),
}

CONTACT_KINDS = ("contacto", "update")


class CatalogError(ValueError):
    """Ficheiro de catálogo inválido — mensagem segura para mostrar."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def validate_catalog(data: dict) -> None:
    """Valida o ficheiro inteiro **antes** de escrever, para uma carga nunca ficar a meio."""
    _require(isinstance(data, dict), "esperado um objeto JSON")
    phases, stages = data.get("phases"), data.get("stages")
    _require(isinstance(phases, list) and phases, "falta a lista 'phases'")
    _require(isinstance(stages, list) and stages, "falta a lista 'stages'")
    phase_codes: set[str] = set()
    for phase in phases:
        _require(isinstance(phase, dict) and phase.get("code") and phase.get("name"), "fase sem 'code'/'name'")
        _require(phase["code"] not in phase_codes, f"fase repetida: {phase['code']}")
        phase_codes.add(phase["code"])
    seen: set[str] = set()
    for stage in stages:
        code = stage.get("code") if isinstance(stage, dict) else None
        _require(bool(code) and bool(stage.get("title")), "etapa sem 'code'/'title'")
        _require(code not in seen, f"etapa repetida: {code}")
        _require(stage.get("phase") in phase_codes, f"etapa {code}: fase desconhecida {stage.get('phase')!r}")
        _require(
            stage.get("responsible") in RESPONSIBLE_RULES,
            f"etapa {code}: responsável desconhecido {stage.get('responsible')!r} "
            f"(esperado um de {', '.join(RESPONSIBLE_RULES)})",
        )
        start, end = stage.get("start_day"), stage.get("end_day")
        _require(
            isinstance(start, int) and isinstance(end, int) and 1 <= start <= end,
            f"etapa {code}: 'start_day'/'end_day' inválidos",
        )
        contact = stage.get("contact")
        if contact is not None:
            _require(
                isinstance(contact, dict) and isinstance(contact.get("day"), int) and contact["day"] >= 1,
                f"etapa {code}: contacto sem 'day' válido",
            )
            _require(contact.get("kind") in CONTACT_KINDS, f"etapa {code}: tipo de contacto inválido")
        subtasks = stage.get("subtasks")
        _require(isinstance(subtasks, list) and subtasks and all(isinstance(s, str) and s.strip() for s in subtasks),
                 f"etapa {code}: 'subtasks' vazio ou inválido")
        seen.add(code)
    for stage in stages:
        dep = stage.get("depends_on")
        _require(dep is None or dep in seen, f"etapa {stage['code']}: dependência desconhecida {dep!r}")
        _require(dep != stage["code"], f"etapa {stage['code']}: depende de si própria")


def load_process_catalog(db: Session, data: dict) -> dict:
    """Aplica o catálogo. Valida tudo primeiro; não faz commit (permite `--dry-run`)."""
    validate_catalog(data)
    summary = {"phases_created": 0, "phases_updated": 0, "stages_created": 0, "stages_updated": 0,
               "subtasks_created": 0, "subtasks_updated": 0}

    phases: dict[str, Phase] = {}
    for order, spec in enumerate(data["phases"]):
        phase = db.query(Phase).filter(Phase.code == spec["code"]).one_or_none()
        values = {"name": spec["name"], "color_hex": spec.get("color") or "#888888", "sort_order": order}
        if phase is None:
            phase = Phase(code=spec["code"], **values)
            db.add(phase)
            summary["phases_created"] += 1
        else:
            if any(getattr(phase, k) != v for k, v in values.items()):
                summary["phases_updated"] += 1
            for k, v in values.items():
                setattr(phase, k, v)
        phases[spec["code"]] = phase
    db.flush()

    stages: dict[str, WorkflowStage] = {}
    for order, spec in enumerate(data["stages"]):
        rule, role_code, label = RESPONSIBLE_RULES[spec["responsible"]]
        contact = spec.get("contact")
        values = {
            "phase_id": phases[spec["phase"]].id,
            "title": spec["title"],
            "responsible_rule": rule,
            "responsible_role_code": role_code,
            "responsible_label": label,
            "sort_order": order,
            "planned_start_offset_days": spec["start_day"],
            "planned_end_offset_days": spec["end_day"],
            "has_contact_checkpoint": contact is not None,
            "contact_note": (contact or {}).get("note") or "",
            "contact_day": contact["day"] if contact else None,
            "contact_kind": contact["kind"] if contact else None,
            "note": spec.get("note") or "",
        }
        stage = db.query(WorkflowStage).filter(WorkflowStage.code == spec["code"]).one_or_none()
        if stage is None:
            stage = WorkflowStage(code=spec["code"], **values)
            db.add(stage)
            summary["stages_created"] += 1
        else:
            if any(getattr(stage, k) != v for k, v in values.items()):
                summary["stages_updated"] += 1
            for k, v in values.items():
                setattr(stage, k, v)
        stages[spec["code"]] = stage
    db.flush()
    for spec in data["stages"]:
        stages[spec["code"]].depends_on_stage_id = stages[spec["depends_on"]].id if spec.get("depends_on") else None

    for spec in data["stages"]:
        stage = stages[spec["code"]]
        for index, title in enumerate(spec["subtasks"]):
            code = f"{spec['code']}.{index}"
            subtask = db.query(WorkflowSubtask).filter(WorkflowSubtask.code == code).one_or_none()
            if subtask is None:
                db.add(WorkflowSubtask(stage_id=stage.id, code=code, title=title.strip(), sort_order=index))
                summary["subtasks_created"] += 1
            else:
                if subtask.title != title.strip() or subtask.sort_order != index or subtask.stage_id != stage.id:
                    summary["subtasks_updated"] += 1
                subtask.title, subtask.sort_order, subtask.stage_id = title.strip(), index, stage.id
    db.flush()
    return summary


def sync_support_delegations(db: Session, entries: list) -> dict:
    """Define as delegações **exatamente** como no ficheiro (autoritativo): cria/atualiza
    as listadas e remove as que já não constam. Cada entrada: `{"pm": nome, "support":
    nome}` (nomes de `Person.display_name`, sem maiúsculas nem acentos). Uma entrada com
    nomes desconhecidos é reportada e não altera nada dessa entrada. Não faz commit."""
    summary = {"created": 0, "updated": 0, "removed": 0, "unchanged": 0, "invalid": []}
    by_key: dict[str, list[Person]] = {}
    for person in db.query(Person).all():
        by_key.setdefault(normalize_key(person.display_name), []).append(person)

    def find(name: object) -> Person | None:
        matches = by_key.get(normalize_key(str(name or "")), [])
        return matches[0] if len(matches) == 1 else None

    wanted: dict = {}
    for index, entry in enumerate(entries, start=1):
        label = f"entrada {index}"
        if not isinstance(entry, dict):
            summary["invalid"].append(f"{label}: não é um objeto")
            continue
        pm, support = find(entry.get("pm")), find(entry.get("support"))
        if pm is None or support is None:
            missing = "PM" if pm is None else "pessoa de suporte"
            summary["invalid"].append(f"{label}: {missing} desconhecido(a) ou ambíguo(a)")
            continue
        if pm.id == support.id:
            summary["invalid"].append(f"{label}: o PM não pode delegar em si próprio")
            continue
        wanted[pm.id] = support.id

    if summary["invalid"]:
        return summary  # nada é alterado se o ficheiro tiver erros (nem remoções)

    existing = {d.pm_person_id: d for d in db.query(SupportDelegation).all()}
    for pm_id, support_id in wanted.items():
        current = existing.get(pm_id)
        if current is None:
            db.add(SupportDelegation(pm_person_id=pm_id, support_person_id=support_id))
            summary["created"] += 1
        elif current.support_person_id != support_id:
            current.support_person_id = support_id
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1
    for pm_id, delegation in existing.items():
        if pm_id not in wanted:
            db.delete(delegation)
            summary["removed"] += 1
    db.flush()
    return summary
