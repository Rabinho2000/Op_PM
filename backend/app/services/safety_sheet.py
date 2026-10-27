from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.models.installer import InstallerTeam
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project, ProjectTeamAssignment
from app.models.safety_sheet import (
    ProjectSafetySheet,
    ProjectSafetySheetHistory,
    ProjectSafetySheetWorker,
)


class SafetySheetVersionConflict(ValueError):
    def __init__(self, current_version: int):
        super().__init__("A ficha foi alterada por outra pessoa. Atualize os dados antes de guardar.")
        self.current_version = current_version


class SafetySheetWorkerPersonNotFound(ValueError):
    pass


@dataclass(frozen=True)
class SafetySheetHistoryEntry:
    version: int
    snapshot: dict
    changed_by_person_id: uuid.UUID | None
    changed_at: object


_FIELDS = (
    "roof_type",
    "roof_other",
    "approximate_height_m",
    "access_method",
    "access_other",
    "risk_other",
    "measure_other",
    "safety_responsible",
    "emergency_contacts",
    "observations",
    "work_start_date",
    "work_end_date",
)


def _worker_read(worker: ProjectSafetySheetWorker) -> dict:
    return {
        "person_id": worker.person_id,
        "name": worker.name_snapshot,
        "installer_id": worker.installer_id,
        "team_id": worker.team_id,
    }


def safety_sheet_snapshot(project_id: uuid.UUID, sheet: ProjectSafetySheet | None) -> dict:
    if sheet is None:
        return {
            "project_id": project_id,
            "version": 0,
            "roof_type": None,
            "roof_other": None,
            "approximate_height_m": None,
            "access_method": None,
            "access_other": None,
            "risks": [],
            "risk_other": None,
            "safety_measures": [],
            "measure_other": None,
            "workers": [],
            "safety_responsible": None,
            "emergency_contacts": None,
            "observations": None,
            "work_start_date": None,
            "work_end_date": None,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "project_id": sheet.project_id,
        "version": sheet.version,
        "roof_type": sheet.roof_type,
        "roof_other": sheet.roof_other,
        "approximate_height_m": sheet.approximate_height_m,
        "access_method": sheet.access_method,
        "access_other": sheet.access_other,
        "risks": json.loads(sheet.risks_json or "[]"),
        "risk_other": sheet.risk_other,
        "safety_measures": json.loads(sheet.safety_measures_json or "[]"),
        "measure_other": sheet.measure_other,
        "workers": [_worker_read(worker) for worker in sheet.workers],
        "safety_responsible": sheet.safety_responsible,
        "emergency_contacts": sheet.emergency_contacts,
        "observations": sheet.observations,
        "work_start_date": sheet.work_start_date,
        "work_end_date": sheet.work_end_date,
        "created_at": sheet.created_at,
        "updated_at": sheet.updated_at,
    }


def get_safety_sheet(db: Session, project_id: uuid.UUID) -> ProjectSafetySheet | None:
    return (
        db.query(ProjectSafetySheet)
        .options(joinedload(ProjectSafetySheet.workers))
        .filter(ProjectSafetySheet.project_id == project_id)
        .one_or_none()
    )


def save_safety_sheet(
    db: Session,
    *,
    project_id: uuid.UUID,
    values: dict,
    changed_by_person_id: uuid.UUID | None,
) -> ProjectSafetySheet:
    # Lock the parent first so the first insert and later version checks share
    # one serialization point on both PostgreSQL and SQLite.
    project = (
        db.query(Project)
        .populate_existing()
        .filter(Project.id == project_id, Project.deleted_at.is_(None))
        .with_for_update()
        .one_or_none()
    )
    if project is None:
        raise LookupError("Projeto não encontrado.")

    sheet = (
        db.query(ProjectSafetySheet)
        .populate_existing()
        .options(joinedload(ProjectSafetySheet.workers))
        .filter(ProjectSafetySheet.project_id == project_id)
        .with_for_update()
        .one_or_none()
    )
    current_version = sheet.version if sheet is not None else 0
    if values["expected_version"] != current_version:
        raise SafetySheetVersionConflict(current_version)

    worker_inputs = values.get("workers", [])
    person_ids = [worker["person_id"] for worker in worker_inputs if worker.get("person_id") is not None]
    if len(person_ids) != len(set(person_ids)):
        raise ValueError("A mesma pessoa não pode constar mais do que uma vez na lista de trabalhadores.")
    people_by_id = {}
    if person_ids:
        people_by_id = {
            person.id: person
            for person in db.query(Person).filter(Person.id.in_(person_ids)).all()
        }
        if set(people_by_id) != set(person_ids):
            raise SafetySheetWorkerPersonNotFound("Uma das pessoas selecionadas já não existe.")

    if sheet is None:
        sheet = ProjectSafetySheet(project_id=project_id)
        db.add(sheet)

    for field in _FIELDS:
        setattr(sheet, field, values.get(field))
    sheet.risks_json = json.dumps(values.get("risks", []), ensure_ascii=False)
    sheet.safety_measures_json = json.dumps(values.get("safety_measures", []), ensure_ascii=False)
    sheet.version = current_version + 1
    sheet.workers.clear()
    # Flush orphan deletions before inserting rows at the same list positions;
    # otherwise the unique (sheet, position) key can collide during UPDATE.
    db.flush()
    for position, worker in enumerate(worker_inputs):
        person_id = worker.get("person_id")
        person = people_by_id.get(person_id) if person_id else None
        sheet.workers.append(
            ProjectSafetySheetWorker(
                person_id=person_id,
                name_snapshot=person.display_name if person else worker["name"],
                position=position,
                installer_id=worker.get("installer_id"),
                team_id=worker.get("team_id"),
            )
        )

    db.flush()
    snapshot = safety_sheet_snapshot(project_id, sheet)
    db.add(
        ProjectSafetySheetHistory(
            project_id=project_id,
            version=sheet.version,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False, default=str),
            changed_by_person_id=changed_by_person_id,
        )
    )
    db.commit()
    db.refresh(sheet)
    return sheet


def list_safety_sheet_history(db: Session, project_id: uuid.UUID) -> list[SafetySheetHistoryEntry]:
    entries = (
        db.query(ProjectSafetySheetHistory)
        .filter(ProjectSafetySheetHistory.project_id == project_id)
        .order_by(ProjectSafetySheetHistory.version.desc())
        .all()
    )
    return [
        SafetySheetHistoryEntry(
            version=entry.version,
            snapshot=json.loads(entry.snapshot_json),
            changed_by_person_id=entry.changed_by_person_id,
            changed_at=entry.changed_at,
        )
        for entry in entries
    ]


def prefill_safety_sheet_workers(db: Session, project: Project) -> list[dict]:
    assigned = (
        db.query(ProjectTeamAssignment, InstallerTeam)
        .join(InstallerTeam, InstallerTeam.id == ProjectTeamAssignment.team_id)
        .filter(ProjectTeamAssignment.project_id == project.id)
        .order_by(ProjectTeamAssignment.start_date, ProjectTeamAssignment.created_at)
        .all()
    )
    if not assigned and project.installer_team_id is not None:
        team = db.get(InstallerTeam, project.installer_team_id)
        if team is not None:
            assigned = [(None, team)]

    installer_ids: set[uuid.UUID] = set()
    workers: list[dict] = []
    seen_people: set[uuid.UUID] = set()
    seen_leader_names: set[str] = set()
    for assignment, team in assigned:
        installer_id = assignment.installer_id if assignment is not None else project.installer_id
        if installer_id is not None:
            installer_ids.add(installer_id)
        if team.leader_name:
            key = team.leader_name.strip().casefold()
            if key and key not in seen_leader_names:
                workers.append(
                    {
                        "person_id": None,
                        "name": team.leader_name.strip(),
                        "installer_id": installer_id,
                        "team_id": team.id,
                    }
                )
                seen_leader_names.add(key)

    if not assigned and project.installer_id is not None:
        installer_ids.add(project.installer_id)
    if installer_ids:
        memberships = (
            db.query(InstallerAccessMembership, Person)
            .join(Person, Person.id == InstallerAccessMembership.person_id)
            .filter(
                InstallerAccessMembership.installer_id.in_(installer_ids),
                InstallerAccessMembership.is_active.is_(True),
            )
            .order_by(Person.display_name, Person.id)
            .all()
        )
        for membership, person in memberships:
            if person.id in seen_people:
                continue
            workers.append(
                {
                    "person_id": person.id,
                    "name": person.display_name,
                    "installer_id": membership.installer_id,
                    "team_id": None,
                }
            )
            seen_people.add(person.id)
    return workers
