"""Dados satélite do projeto (instalação/licenciamento/comunicação) — ver
app/models/project_data.py. Um registo 1:1 por projeto em cada tabela;
`PATCH` cria o registo na primeira edição (nunca exige um passo de
"criar" separado) e gera uma entrada de `ProjectDataHistory` por campo
efetivamente alterado, tal como `app/services/projects.py:update_project`
já faz para `Project`.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import TypeVar

from sqlalchemy.orm import Session

from app.models.project_data import (
    ProjectCommunicationData,
    ProjectDataHistory,
    ProjectInstallationData,
    ProjectLicensingData,
    ProjectPortalCredential,
    ProjectSimCard,
    ProjectSurplusContract,
)

_ModelT = TypeVar(
    "_ModelT", ProjectInstallationData, ProjectLicensingData, ProjectCommunicationData
)

ENTITY_TYPE_INSTALLATION = "installation"
ENTITY_TYPE_LICENSING = "licensing"
ENTITY_TYPE_COMMUNICATION = "communication"
ENTITY_TYPE_CREDENTIAL = "credential"
ENTITY_TYPE_SURPLUS = "surplus"
ENTITY_TYPE_SIM = "sim"

# Etapas do licenciamento, da menor para a maior. Estado derivado = a maior
# etapa que tem data preenchida (ver `derive_licensing_state`).
LICENSING_STAGES: tuple[tuple[str, str], ...] = (
    ("cadastrado", "registration_date"),
    ("certificacao_pedida", "certification_request_date"),
    ("inspecionado", "inspection_date"),
    ("certificado_provisorio", "provisional_certificate_date"),
    ("certificado_definitivo", "certificate_date"),
)
LICENSING_STATE_WITHOUT_STAGE = "sem_registo"

# Marcador do histórico para passwords: o valor nunca entra no histórico.
PASSWORD_HISTORY_MARKER = "[definida]"
# Mesma regra para PIN/PUK de SIM.
SECRET_HISTORY_MARKER = "[definido]"

_ENTITY_TYPE_BY_MODEL: dict[type, str] = {
    ProjectInstallationData: ENTITY_TYPE_INSTALLATION,
    ProjectLicensingData: ENTITY_TYPE_LICENSING,
    ProjectCommunicationData: ENTITY_TYPE_COMMUNICATION,
}


def get_installation_data(db: Session, project_id: uuid.UUID) -> ProjectInstallationData | None:
    return db.query(ProjectInstallationData).filter(ProjectInstallationData.project_id == project_id).one_or_none()


def get_licensing_data(db: Session, project_id: uuid.UUID) -> ProjectLicensingData | None:
    return db.query(ProjectLicensingData).filter(ProjectLicensingData.project_id == project_id).one_or_none()


def get_communication_data(db: Session, project_id: uuid.UUID) -> ProjectCommunicationData | None:
    return (
        db.query(ProjectCommunicationData)
        .filter(ProjectCommunicationData.project_id == project_id)
        .one_or_none()
    )


def derive_licensing_state(data: ProjectLicensingData | None) -> str:
    """Estado derivado: a etapa mais avançada com data preenchida. Não é
    guardado — é calculado na leitura, para não haver dois sítios a divergir."""
    if data is None:
        return LICENSING_STATE_WITHOUT_STAGE
    state = LICENSING_STATE_WITHOUT_STAGE
    for state_name, field_name in LICENSING_STAGES:
        if getattr(data, field_name, None) is not None:
            state = state_name
    return state


def _record_history(
    db: Session,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    record_id: uuid.UUID,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    changed_by_person_id: uuid.UUID | None,
    source: str = "ui",
    note: str = "",
) -> None:
    db.add(
        ProjectDataHistory(
            project_id=project_id,
            entity_type=entity_type,
            record_id=record_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by_person_id=changed_by_person_id,
            source=source,
            note=note,
        )
    )


# --- Credenciais de portais (0..n por projeto) -----------------------------

CREDENTIAL_PORTALS = ("dgeg_login_geral", "mastervantagem", "outro")


def list_portal_credentials(db: Session, project_id: uuid.UUID) -> list[ProjectPortalCredential]:
    return (
        db.query(ProjectPortalCredential)
        .filter(
            ProjectPortalCredential.project_id == project_id,
            ProjectPortalCredential.deleted_at.is_(None),
        )
        .order_by(ProjectPortalCredential.created_at, ProjectPortalCredential.id)
        .all()
    )


def get_portal_credential(
    db: Session, project_id: uuid.UUID, credential_id: uuid.UUID
) -> ProjectPortalCredential | None:
    return (
        db.query(ProjectPortalCredential)
        .filter(
            ProjectPortalCredential.id == credential_id,
            ProjectPortalCredential.project_id == project_id,
            ProjectPortalCredential.deleted_at.is_(None),
        )
        .one_or_none()
    )


def create_portal_credential(
    db: Session,
    *,
    project_id: uuid.UUID,
    values: dict,
    encrypted_password: str | None,
    changed_by_person_id: uuid.UUID | None,
) -> ProjectPortalCredential:
    """`encrypted_password` já vem cifrado (a cifra é responsabilidade da rota,
    que falha fechado antes de tocar na BD)."""
    credential = ProjectPortalCredential(
        project_id=project_id,
        portal=values["portal"],
        username=values["username"],
        email=values.get("email") or None,
        password_encrypted=encrypted_password,
    )
    db.add(credential)
    db.flush()
    _record_history(
        db,
        project_id=project_id,
        entity_type=ENTITY_TYPE_CREDENTIAL,
        record_id=credential.id,
        field_name="created",
        old_value=None,
        new_value=f"{credential.portal}:{credential.username}",
        changed_by_person_id=changed_by_person_id,
        note="",
    )
    db.commit()
    db.refresh(credential)
    return credential


def update_portal_credential(
    db: Session,
    *,
    credential: ProjectPortalCredential,
    changes: dict,
    password_given: bool,
    encrypted_password: str | None,
    changed_by_person_id: uuid.UUID | None,
) -> ProjectPortalCredential:
    project_id = credential.project_id
    for field_name in ("portal", "username", "email"):
        if field_name not in changes:
            continue
        new_value = changes[field_name]
        if field_name == "email" and new_value == "":
            new_value = None
        old_value = getattr(credential, field_name)
        if old_value == new_value:
            continue
        _record_history(
            db,
            project_id=project_id,
            entity_type=ENTITY_TYPE_CREDENTIAL,
            record_id=credential.id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by_person_id=changed_by_person_id,
        )
        setattr(credential, field_name, new_value)

    if password_given:
        had_password = credential.password_encrypted is not None
        # Só o facto de haver/ter sido alterada a password entra no histórico.
        _record_history(
            db,
            project_id=project_id,
            entity_type=ENTITY_TYPE_CREDENTIAL,
            record_id=credential.id,
            field_name="password",
            old_value=PASSWORD_HISTORY_MARKER if had_password else None,
            new_value=PASSWORD_HISTORY_MARKER if encrypted_password is not None else None,
            changed_by_person_id=changed_by_person_id,
            note="password alterada" if encrypted_password is not None else "password removida",
        )
        credential.password_encrypted = encrypted_password

    db.commit()
    db.refresh(credential)
    return credential


def delete_portal_credential(
    db: Session,
    *,
    credential: ProjectPortalCredential,
    deleted_by_person_id: uuid.UUID | None,
) -> None:
    """Remoção lógica. A password cifrada é apagada no mesmo passo — não fica
    nenhum segredo em linhas removidas."""
    credential.deleted_at = dt.datetime.now(dt.timezone.utc)
    credential.deleted_by_person_id = deleted_by_person_id
    credential.password_encrypted = None
    _record_history(
        db,
        project_id=credential.project_id,
        entity_type=ENTITY_TYPE_CREDENTIAL,
        record_id=credential.id,
        field_name="deleted",
        old_value=f"{credential.portal}:{credential.username}",
        new_value=None,
        changed_by_person_id=deleted_by_person_id,
    )
    db.commit()


def record_password_reveal(
    db: Session,
    *,
    credential: ProjectPortalCredential,
    revealed_by_person_id: uuid.UUID | None,
) -> None:
    """Regista quem revelou e quando, sem o valor. `changed_at` é preenchido
    pela BD."""
    _record_history(
        db,
        project_id=credential.project_id,
        entity_type=ENTITY_TYPE_CREDENTIAL,
        record_id=credential.id,
        field_name="password_revealed",
        old_value=None,
        new_value=None,
        changed_by_person_id=revealed_by_person_id,
        note="password revelada",
    )
    db.commit()


# --- Cartões SIM (0..n por projeto) ----------------------------------------

SIM_PURPOSES = ("comunicacoes", "dados_moveis", "outro")
SIM_FIELDS = ("purpose", "operator", "phone_number", "iccid", "verified_on_portal", "verified_date", "notes")


def list_sim_cards(db: Session, project_id: uuid.UUID) -> list[ProjectSimCard]:
    return (
        db.query(ProjectSimCard)
        .filter(ProjectSimCard.project_id == project_id, ProjectSimCard.deleted_at.is_(None))
        .order_by(ProjectSimCard.created_at, ProjectSimCard.id)
        .all()
    )


def get_sim_card(db: Session, project_id: uuid.UUID, sim_id: uuid.UUID) -> ProjectSimCard | None:
    return (
        db.query(ProjectSimCard)
        .filter(
            ProjectSimCard.id == sim_id,
            ProjectSimCard.project_id == project_id,
            ProjectSimCard.deleted_at.is_(None),
        )
        .one_or_none()
    )


def _sim_value(field_name: str, value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "sim" if value else "não"
    return str(value)


def create_sim_card(
    db: Session,
    *,
    project_id: uuid.UUID,
    values: dict,
    encrypted_pin: str | None,
    encrypted_puk: str | None,
    changed_by_person_id: uuid.UUID | None,
) -> ProjectSimCard:
    """`values` só com campos não secretos. PIN/PUK já cifrados pela rota."""
    sim = ProjectSimCard(project_id=project_id, purpose=values["purpose"], notes=values.get("notes") or "")
    for field_name in SIM_FIELDS:
        if field_name in values and field_name not in ("purpose", "notes"):
            setattr(sim, field_name, values[field_name])
    sim.pin_encrypted = encrypted_pin
    sim.puk_encrypted = encrypted_puk
    db.add(sim)
    db.flush()
    _record_history(
        db,
        project_id=project_id,
        entity_type=ENTITY_TYPE_SIM,
        record_id=sim.id,
        field_name="created",
        old_value=None,
        new_value=f"{sim.purpose}:{sim.iccid or sim.phone_number or ''}",
        changed_by_person_id=changed_by_person_id,
    )
    if encrypted_pin is not None or encrypted_puk is not None:
        _record_history(
            db,
            project_id=project_id,
            entity_type=ENTITY_TYPE_SIM,
            record_id=sim.id,
            field_name="secrets",
            old_value=None,
            new_value=SECRET_HISTORY_MARKER,
            changed_by_person_id=changed_by_person_id,
            note="PIN/PUK definidos",
        )
    db.commit()
    db.refresh(sim)
    return sim


def update_sim_card(
    db: Session,
    *,
    sim: ProjectSimCard,
    changes: dict,
    secret_changes: dict[str, str | None],
    changed_by_person_id: uuid.UUID | None,
) -> ProjectSimCard:
    """`changes`: campos não secretos enviados. `secret_changes`: {"pin"|"puk": valor
    cifrado ou None (remover)} só para os segredos enviados no corpo."""
    project_id = sim.project_id
    for field_name in SIM_FIELDS:
        if field_name not in changes:
            continue
        new_value = changes[field_name]
        if field_name == "notes" and new_value is None:
            new_value = ""
        if field_name == "purpose" and new_value is None:
            continue
        old_value = getattr(sim, field_name)
        if old_value == new_value:
            continue
        _record_history(
            db,
            project_id=project_id,
            entity_type=ENTITY_TYPE_SIM,
            record_id=sim.id,
            field_name=field_name,
            old_value=_sim_value(field_name, old_value),
            new_value=_sim_value(field_name, new_value),
            changed_by_person_id=changed_by_person_id,
        )
        setattr(sim, field_name, new_value)

    for kind, column in (("pin", "pin_encrypted"), ("puk", "puk_encrypted")):
        if kind not in secret_changes:
            continue
        new_token = secret_changes[kind]
        had = getattr(sim, column) is not None
        has = new_token is not None
        if not had and not has:
            continue  # remover algo que não existia: nada a registar
        if had and has:
            note = f"{kind.upper()} alterado"
        elif has:
            note = f"{kind.upper()} definido"
        else:
            note = f"{kind.upper()} removido"
        _record_history(
            db,
            project_id=project_id,
            entity_type=ENTITY_TYPE_SIM,
            record_id=sim.id,
            field_name=kind,
            old_value=SECRET_HISTORY_MARKER if had else None,
            new_value=SECRET_HISTORY_MARKER if has else None,
            changed_by_person_id=changed_by_person_id,
            note=note,
        )
        setattr(sim, column, new_token)

    db.commit()
    db.refresh(sim)
    return sim


def delete_sim_card(db: Session, *, sim: ProjectSimCard, deleted_by_person_id: uuid.UUID | None) -> None:
    """Remoção lógica. PIN/PUK cifrados apagados no mesmo passo."""
    sim.deleted_at = dt.datetime.now(dt.timezone.utc)
    sim.deleted_by_person_id = deleted_by_person_id
    sim.pin_encrypted = None
    sim.puk_encrypted = None
    _record_history(
        db,
        project_id=sim.project_id,
        entity_type=ENTITY_TYPE_SIM,
        record_id=sim.id,
        field_name="deleted",
        old_value=f"{sim.purpose}:{sim.iccid or sim.phone_number or ''}",
        new_value=None,
        changed_by_person_id=deleted_by_person_id,
    )
    db.commit()


def record_sim_secrets_reveal(db: Session, *, sim: ProjectSimCard, revealed_by_person_id: uuid.UUID | None) -> None:
    """Regista quem revelou PIN/PUK e quando, sem valores."""
    _record_history(
        db,
        project_id=sim.project_id,
        entity_type=ENTITY_TYPE_SIM,
        record_id=sim.id,
        field_name="secrets_revealed",
        old_value=None,
        new_value=None,
        changed_by_person_id=revealed_by_person_id,
        note="PIN/PUK revelados",
    )
    db.commit()


# --- Contratos de venda de excedente (0..n por projeto) -------------------

SURPLUS_FIELDS = (
    "commercializer",
    "contract_type",
    "contract_sent_date",
    "signed_received_date",
    "sent_to_commercializer_date",
    "status",
    "duration_months",
    "start_date",
    "end_date",
    "notes",
)


def list_surplus_contracts(db: Session, project_id: uuid.UUID) -> list[ProjectSurplusContract]:
    return (
        db.query(ProjectSurplusContract)
        .filter(
            ProjectSurplusContract.project_id == project_id,
            ProjectSurplusContract.deleted_at.is_(None),
        )
        .order_by(ProjectSurplusContract.created_at, ProjectSurplusContract.id)
        .all()
    )


def get_surplus_contract(
    db: Session, project_id: uuid.UUID, contract_id: uuid.UUID
) -> ProjectSurplusContract | None:
    return (
        db.query(ProjectSurplusContract)
        .filter(
            ProjectSurplusContract.id == contract_id,
            ProjectSurplusContract.project_id == project_id,
            ProjectSurplusContract.deleted_at.is_(None),
        )
        .one_or_none()
    )


def _surplus_value(field_name: str, value):
    if value is None:
        return None
    if field_name == "notes":
        return value
    return str(value)


def create_surplus_contract(
    db: Session,
    *,
    project_id: uuid.UUID,
    values: dict,
    changed_by_person_id: uuid.UUID | None,
) -> ProjectSurplusContract:
    contract = ProjectSurplusContract(project_id=project_id, notes="")
    for field_name in SURPLUS_FIELDS:
        if field_name in values:
            value = values[field_name]
            if field_name == "notes" and value is None:
                value = ""
            setattr(contract, field_name, value)
    db.add(contract)
    db.flush()
    _record_history(
        db,
        project_id=project_id,
        entity_type=ENTITY_TYPE_SURPLUS,
        record_id=contract.id,
        field_name="created",
        old_value=None,
        new_value=_surplus_value("commercializer", contract.commercializer),
        changed_by_person_id=changed_by_person_id,
    )
    db.commit()
    db.refresh(contract)
    return contract


def update_surplus_contract(
    db: Session,
    *,
    contract: ProjectSurplusContract,
    changes: dict,
    changed_by_person_id: uuid.UUID | None,
) -> ProjectSurplusContract:
    for field_name in SURPLUS_FIELDS:
        if field_name not in changes:
            continue
        new_value = changes[field_name]
        if field_name == "notes" and new_value is None:
            new_value = ""
        old_value = getattr(contract, field_name)
        if old_value == new_value:
            continue
        _record_history(
            db,
            project_id=contract.project_id,
            entity_type=ENTITY_TYPE_SURPLUS,
            record_id=contract.id,
            field_name=field_name,
            old_value=_surplus_value(field_name, old_value),
            new_value=_surplus_value(field_name, new_value),
            changed_by_person_id=changed_by_person_id,
        )
        setattr(contract, field_name, new_value)
    db.commit()
    db.refresh(contract)
    return contract


def delete_surplus_contract(
    db: Session,
    *,
    contract: ProjectSurplusContract,
    deleted_by_person_id: uuid.UUID | None,
) -> None:
    contract.deleted_at = dt.datetime.now(dt.timezone.utc)
    contract.deleted_by_person_id = deleted_by_person_id
    _record_history(
        db,
        project_id=contract.project_id,
        entity_type=ENTITY_TYPE_SURPLUS,
        record_id=contract.id,
        field_name="deleted",
        old_value=_surplus_value("commercializer", contract.commercializer),
        new_value=None,
        changed_by_person_id=deleted_by_person_id,
    )
    db.commit()


def _upsert(
    db: Session,
    *,
    model_cls: type[_ModelT],
    project_id: uuid.UUID,
    changes: dict,
    changed_by_person_id: uuid.UUID | None,
    source: str = "ui",
    note: str = "",
    commit: bool = True,
) -> _ModelT:
    entity_type = _ENTITY_TYPE_BY_MODEL[model_cls]
    instance = db.query(model_cls).filter(model_cls.project_id == project_id).one_or_none()
    if instance is None:
        instance = model_cls(project_id=project_id)
        db.add(instance)

    columns = model_cls.__table__.columns
    for field_name, new_value in changes.items():
        # Colunas NOT NULL (ex. `notes`) não aceitam null: o schema de update
        # aceita null para "limpar o campo", que aqui significa valor vazio.
        column = columns.get(field_name)
        if new_value is None and column is not None and not column.nullable:
            new_value = ""
        old_value = getattr(instance, field_name, None)
        if old_value == new_value:
            continue
        db.add(
            ProjectDataHistory(
                project_id=project_id,
                entity_type=entity_type,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by_person_id=changed_by_person_id,
                source=source,
                note=note,
            )
        )
        setattr(instance, field_name, new_value)

    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(instance)
    return instance


def upsert_installation_data(
    db: Session,
    *,
    project_id: uuid.UUID,
    changes: dict,
    changed_by_person_id: uuid.UUID | None,
    source: str = "ui",
    note: str = "",
    commit: bool = True,
) -> ProjectInstallationData:
    return _upsert(
        db,
        model_cls=ProjectInstallationData,
        project_id=project_id,
        changes=changes,
        changed_by_person_id=changed_by_person_id,
        source=source,
        note=note,
        commit=commit,
    )


def upsert_licensing_data(
    db: Session,
    *,
    project_id: uuid.UUID,
    changes: dict,
    changed_by_person_id: uuid.UUID | None,
    source: str = "ui",
    note: str = "",
    commit: bool = True,
) -> ProjectLicensingData:
    return _upsert(
        db,
        model_cls=ProjectLicensingData,
        project_id=project_id,
        changes=changes,
        changed_by_person_id=changed_by_person_id,
        source=source,
        note=note,
        commit=commit,
    )


def upsert_communication_data(
    db: Session,
    *,
    project_id: uuid.UUID,
    changes: dict,
    changed_by_person_id: uuid.UUID | None,
    source: str = "ui",
    note: str = "",
) -> ProjectCommunicationData:
    return _upsert(
        db,
        model_cls=ProjectCommunicationData,
        project_id=project_id,
        changes=changes,
        changed_by_person_id=changed_by_person_id,
        source=source,
        note=note,
    )


def list_data_history(
    db: Session,
    project_id: uuid.UUID,
    *,
    entity_type: str | None = None,
    allowed_entity_types: set[str] | frozenset[str] | None = None,
) -> list[ProjectDataHistory]:
    query = db.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project_id)
    if entity_type is not None:
        query = query.filter(ProjectDataHistory.entity_type == entity_type)
    if allowed_entity_types is not None:
        query = query.filter(ProjectDataHistory.entity_type.in_(allowed_entity_types))
    return query.order_by(ProjectDataHistory.changed_at.desc()).all()
