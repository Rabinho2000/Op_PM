"""Reconciliação de pessoas/PMs — etapa explícita ANTES de ingerir
projetos (ver docs/DECISIONS.md D-023).

Cumpre diretamente os quatro requisitos pedidos:

- "preservar todos os PMs históricos como Person": não é este módulo que
  faz isso — é uma propriedade do modelo de dados (`Person` nunca é
  apagado; ver D-003) — mas este módulo NUNCA apaga nem ignora um `Person`
  existente ao reconciliar, só acrescenta.
- "associar User apenas aos utilizadores ativos": `create_new` aqui cria
  sempre um `Person` sem `User` associado (`is_active=False` por omissão)
  — dar-lhe login é uma decisão separada, humana, fora deste módulo.
- "enviar nomes de PM desconhecidos ou ambíguos para revisão":
  `reconcile_pm_names` faz exatamente isto, para `PersonReconciliationItem`.
- "nunca promover silenciosamente um projeto com PM conhecido mas não
  resolvido": este módulo não promove nada — só classifica e regista a
  fila. O bloqueio real está em `app/migration/staging.py`
  (`ingest_export` marca o registo como `conflict`/`pm_unresolved`, e
  `promote_staging_record` recusa-se a promover um registo com PM por
  resolver, mesmo que alguém tente contornar a fila).
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import new_uuid
from app.models.migration import PersonReconciliationItem
from app.models.people import Person


@dataclass
class PmClassification:
    status: str  # empty | resolved | ignored | unresolved
    person: Person | None
    candidate_person_ids: list[str]


def _normalize(name: str) -> str:
    return name.strip().lower()


def _find_person_candidates(db: Session, normalized_name: str) -> list[Person]:
    return db.query(Person).filter(func.lower(func.trim(Person.display_name)) == normalized_name).all()


def classify_pm_name(db: Session, pm_name_raw) -> PmClassification:
    """Classifica um nome de PM tal como aparece num registo do export —
    usado tanto por `reconcile_pm_names` como por `app/migration/staging.py`
    (ingestão e nova tentativa de resolução), para nunca haver duas lógicas
    de decisão divergentes."""
    if not pm_name_raw or not isinstance(pm_name_raw, str) or not pm_name_raw.strip():
        return PmClassification(status="empty", person=None, candidate_person_ids=[])

    normalized = _normalize(pm_name_raw)
    candidates = _find_person_candidates(db, normalized)
    if len(candidates) == 1:
        return PmClassification(status="resolved", person=candidates[0], candidate_person_ids=[])

    # Sem correspondência única — verifica se já existe uma decisão de
    # reconciliação para este nome (mais recente primeiro).
    queue_item = (
        db.query(PersonReconciliationItem)
        .filter(func.lower(func.trim(PersonReconciliationItem.raw_name)) == normalized)
        .filter(PersonReconciliationItem.status != "pending")
        .order_by(PersonReconciliationItem.resolved_at.desc())
        .first()
    )
    if queue_item is not None:
        if queue_item.status == "ignored":
            return PmClassification(status="ignored", person=None, candidate_person_ids=[])
        if queue_item.resolved_person_id is not None:
            resolved_person = db.get(Person, queue_item.resolved_person_id)
            if resolved_person is not None:
                return PmClassification(status="resolved", person=resolved_person, candidate_person_ids=[])

    return PmClassification(
        status="unresolved", person=None, candidate_person_ids=[str(c.id) for c in candidates]
    )


def _distinct_pm_names(payload: dict) -> set[str]:
    names: set[str] = set()
    for record in payload.get("projects", {}).values():
        pm = record.get("pm")
        if isinstance(pm, str) and pm.strip():
            names.add(pm.strip())
    return names


def reconcile_pm_names(
    db: Session,
    *,
    payload: dict,
) -> dict:
    """Percorre todos os nomes de PM distintos de um export e regista, na
    fila de revisão, os que não resolvem sem ambiguidade contra `people` —
    nunca cria nem liga uma `Person` automaticamente aqui. Chamar SEMPRE
    antes de `app.migration.staging.ingest_export` sobre o mesmo payload,
    para que a fila de revisão já reflita o que vai bloquear a ingestão.

    Idempotente: reexecutar sobre o mesmo payload não duplica itens já
    pendentes para o mesmo nome normalizado.
    """
    if "projects" not in payload or not isinstance(payload["projects"], dict):
        raise ValueError("payload inválido: esperado um objeto com a chave 'projects'")

    created = 0
    already_open = 0
    already_resolved = 0

    for raw_name in sorted(_distinct_pm_names(payload)):
        normalized = _normalize(raw_name)
        candidates = _find_person_candidates(db, normalized)
        if len(candidates) == 1:
            already_resolved += 1
            continue

        existing_pending = (
            db.query(PersonReconciliationItem)
            .filter(
                func.lower(func.trim(PersonReconciliationItem.raw_name)) == normalized,
                PersonReconciliationItem.status == "pending",
            )
            .one_or_none()
        )
        if existing_pending is not None:
            already_open += 1
            continue

        db.add(
            PersonReconciliationItem(
                id=new_uuid(),
                raw_name=raw_name,
                normalized_name=normalized,
                reason="ambiguous" if candidates else "unknown",
                candidate_person_ids_json=json.dumps([str(c.id) for c in candidates]),
                status="pending",
            )
        )
        created += 1

    db.commit()
    return {"created": created, "already_open": already_open, "already_resolved": already_resolved}


def resolve_person_reconciliation(
    db: Session,
    *,
    item_id: uuid.UUID,
    action: str,  # link_existing | create_new | ignore
    actor_person_id: uuid.UUID,
    target_person_id: uuid.UUID | None = None,
    new_person_display_name: str | None = None,
    note: str = "",
) -> PersonReconciliationItem:
    item = db.get(PersonReconciliationItem, item_id)
    if item is None:
        raise ValueError(f"item de reconciliação não encontrado: {item_id}")
    if item.status != "pending":
        raise ValueError(f"só é possível resolver um item pendente (estado atual: {item.status!r})")

    now = dt.datetime.now(dt.timezone.utc)

    if action == "link_existing":
        if target_person_id is None:
            raise ValueError("a ação 'link_existing' exige target_person_id")
        person = db.get(Person, target_person_id)
        if person is None:
            raise ValueError(f"pessoa alvo não encontrada: {target_person_id}")
        item.resolved_person_id = person.id
        item.status = "resolved"
    elif action == "create_new":
        # Pessoa nova, sem User associado — histórico preservado, sem
        # login por omissão (ver docs/DECISIONS.md D-003/D-023).
        person = Person(
            id=new_uuid(),
            display_name=new_person_display_name or item.raw_name,
            is_active=False,
            legacy_ref=f"reconciled:{item.normalized_name}",
        )
        db.add(person)
        db.flush()
        item.resolved_person_id = person.id
        item.status = "created_new"
    elif action == "ignore":
        item.status = "ignored"
    else:
        raise ValueError(f"ação desconhecida: {action!r} (esperado link_existing, create_new ou ignore)")

    item.resolved_by_person_id = actor_person_id
    item.resolved_at = now
    item.resolution_note = note

    db.commit()
    db.refresh(item)
    return item
