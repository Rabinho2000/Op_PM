"""Afectações de equipas por obra (PR C / D-080)."""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from app.db import SessionLocal, engine
from app.models.installer import Installer, InstallerTeam
from app.models.people import Person
from app.models.project import Project, ProjectHistory, ProjectTeamAssignment

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"
ALFA = "Instalador Sintético Alfa"
BETA = "Instalador Sintético Beta"
OWN = "Instalação Sintética de Demonstração"
OTHER = "Instalação Sintética Incompleta"
LEGACY_PM = "Instalação Sintética F — PM Legado"


def _h(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _team(db, installer_name: str, team_name: str) -> InstallerTeam:
    installer = db.query(Installer).filter(Installer.name == installer_name).one()
    return next(team for team in installer.teams if team.name == team_name)


def _project(db, name: str) -> Project:
    return db.query(Project).filter(Project.name == name).one()


def _plan(api_client, project: Project, **body):
    return api_client.patch(f"/api/projects/{project.id}/work-plan", json=body, headers=_h(CHEFE))


def _assign(api_client, project: Project, team: InstallerTeam, start: dt.date, end: dt.date, **extra):
    body = {"team_id": str(team.id), "start_date": start.isoformat(), "end_date": end.isoformat()}
    body.update(extra)
    return api_client.post(f"/api/projects/{project.id}/team-assignments", json=body, headers=_h(CHEFE))


def _make_assignable(api_client, db, name: str = OTHER) -> Project:
    project = _project(db, name)
    installer = db.query(Installer).filter(Installer.name == ALFA).one()
    response = _plan(
        api_client,
        project,
        installer_id=str(installer.id),
        work_start_date="2034-01-10",
        work_end_date="2034-01-20",
    )
    assert response.status_code == 200, response.text
    return project


def test_work_can_have_two_non_overlapping_team_assignments_and_legacy_primary(api_client, db_session):
    project = _make_assignable(api_client, db_session)
    team_one = _team(db_session, ALFA, "Equipa 1")
    team_two = _team(db_session, ALFA, "Equipa 2")

    first = _assign(api_client, project, team_one, dt.date(2034, 1, 10), dt.date(2034, 1, 13))
    second = _assign(api_client, project, team_two, dt.date(2034, 1, 14), dt.date(2034, 1, 20))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["warning"] is None
    assert first.json()["team_leader_name"] == "Chefe Sintético Um"
    assert first.json()["team_leader_phone"] == "+351 210 000 011"

    rows = api_client.get(f"/api/projects/{project.id}/team-assignments", headers=_h(CHEFE))
    assert rows.status_code == 200
    assert [row["team_name"] for row in rows.json()] == ["Equipa 1", "Equipa 2"]
    assert project.installer_team_id == team_one.id

    history = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).all()
    assert sum(entry.field_name == "team_assignment" for entry in history) == 2
    assert any(entry.field_name == "installer_team_id" for entry in history)


def test_assignment_rules_return_bad_request_and_window_warning(api_client, db_session):
    project = _make_assignable(api_client, db_session)
    team_one = _team(db_session, ALFA, "Equipa 1")
    team_two = _team(db_session, ALFA, "Equipa 2")
    beta_team = _team(db_session, BETA, "Equipa B") if db_session.query(InstallerTeam).filter(InstallerTeam.name == "Equipa B").count() else None
    if beta_team is None:
        beta = db_session.query(Installer).filter(Installer.name == BETA).one()
        beta_team = InstallerTeam(installer_id=beta.id, name="Equipa B", name_key="equipa b")
        db_session.add(beta_team)
        db_session.flush()

    reversed_dates = _assign(api_client, project, team_one, dt.date(2034, 1, 20), dt.date(2034, 1, 10))
    assert reversed_dates.status_code == 400

    first = _assign(api_client, project, team_one, dt.date(2034, 1, 10), dt.date(2034, 1, 13))
    assert first.status_code == 201, first.text
    overlap = _assign(api_client, project, team_one, dt.date(2034, 1, 13), dt.date(2034, 1, 14))
    assert overlap.status_code == 400

    wrong_installer = _assign(api_client, project, beta_team, dt.date(2034, 1, 14), dt.date(2034, 1, 15))
    assert wrong_installer.status_code == 400 and "instalador" in wrong_installer.json()["detail"]

    team_two.is_active = False
    db_session.flush()
    inactive = _assign(api_client, project, team_two, dt.date(2034, 1, 14), dt.date(2034, 1, 15))
    assert inactive.status_code == 400 and "inativa" in inactive.json()["detail"]

    outside = _assign(api_client, project, team_two, dt.date(2034, 1, 1), dt.date(2034, 1, 5))
    assert outside.status_code == 400  # team_two was deliberately made inactive
    team_two.is_active = True
    db_session.flush()
    outside = _assign(api_client, project, team_two, dt.date(2034, 1, 1), dt.date(2034, 1, 5))
    assert outside.status_code == 201
    assert outside.json()["warning"]


def test_assignment_crud_and_scope_and_permission(api_client, db_session):
    project = _make_assignable(api_client, db_session)
    team = _team(db_session, ALFA, "Equipa 1")
    created = _assign(api_client, project, team, dt.date(2034, 1, 10), dt.date(2034, 1, 12), note="janela 1")
    assert created.status_code == 201
    assignment_id = created.json()["id"]

    visible_to_comercial = api_client.get(
        f"/api/projects/{project.id}/team-assignments", headers=_h(COMERCIAL)
    )
    assert visible_to_comercial.status_code == 200
    assert [row["id"] for row in visible_to_comercial.json()] == [assignment_id]

    updated = api_client.patch(
        f"/api/projects/{project.id}/team-assignments/{assignment_id}",
        json={"end_date": "2034-01-15", "note": "janela corrigida"},
        headers=_h(CHEFE),
    )
    assert updated.status_code == 200
    assert updated.json()["end_date"] == "2034-01-15"

    deleted = api_client.delete(
        f"/api/projects/{project.id}/team-assignments/{assignment_id}", headers=_h(CHEFE)
    )
    assert deleted.status_code == 204
    assert api_client.get(f"/api/projects/{project.id}/team-assignments", headers=_h(CHEFE)).json() == []
    assert db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count() >= 4

    no_plan_post = api_client.post(
        f"/api/projects/{project.id}/team-assignments",
        json={"team_id": str(team.id), "start_date": "2034-01-10", "end_date": "2034-01-12"},
        headers=_h(COMERCIAL),
    )
    assert no_plan_post.status_code == 403

    other_pm = _project(db_session, LEGACY_PM)
    hidden = api_client.post(
        f"/api/projects/{other_pm.id}/team-assignments",
        json={"team_id": str(team.id), "start_date": "2034-01-10", "end_date": "2034-01-12"},
        headers=_h(PM_UM),
    )
    assert hidden.status_code == 404


def test_changing_installer_is_blocked_when_assignments_exist(api_client, db_session):
    project = _make_assignable(api_client, db_session)
    team = _team(db_session, ALFA, "Equipa 1")
    assert _assign(api_client, project, team, dt.date(2034, 1, 10), dt.date(2034, 1, 12)).status_code == 201
    beta = db_session.query(Installer).filter(Installer.name == BETA).one()

    response = _plan(api_client, project, installer_id=str(beta.id))
    assert response.status_code == 422
    assert "afecta" in response.json()["detail"].lower()
    db_session.refresh(project)
    assert project.installer_id == team.installer_id
    assert db_session.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.project_id == project.id).count() == 1


def test_team_leader_process_resolves_all_assigned_teams(api_client, db_session):
    project = _make_assignable(api_client, db_session)
    team_one = _team(db_session, ALFA, "Equipa 1")
    team_two = _team(db_session, ALFA, "Equipa 2")
    assert _assign(api_client, project, team_one, dt.date(2034, 1, 10), dt.date(2034, 1, 12)).status_code == 201
    assert _assign(api_client, project, team_two, dt.date(2034, 1, 13), dt.date(2034, 1, 20)).status_code == 201

    body = api_client.get(f"/api/projects/{project.id}/process", headers=_h(CHEFE))
    assert body.status_code == 200, body.text
    stages = {stage["code"]: stage for phase in body.json()["phases"] for stage in phase["stages"]}
    responsible = stages["etapa-14"]["responsible"]
    assert responsible["names"] == ["Chefe Sintético Um", "Chefe Sintético Dois"]
    assert responsible["unresolved"] is False


def test_assignment_migration_converts_legacy_team_and_window(tmp_path):
    """Exercita a revisão e a conversão numa base Alembic isolada, sem o seed da suite."""
    db_path = tmp_path / "legacy.db"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update({"DATABASE_URL": f"sqlite:///{db_path}", "APP_ENV": "test", "GRAPH_FALLBACK_DIR": str(tmp_path / "outbox")})
    root = Path(__file__).resolve().parents[1]
    python = sys.executable

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [python, "-m", "alembic", *args], cwd=root, env=env, text=True, capture_output=True, check=True
        )

    run("upgrade", "d7a2c5e9b3f1")
    seed = (
        "from app.db import SessionLocal; "
        "from app.models.installer import Installer, InstallerTeam; "
        "from app.models.project import Project; "
        "import datetime as dt; "
        "db=SessionLocal(); i=Installer(name='Migrador Sintético', name_key='migrador sintetico'); db.add(i); db.flush(); "
        "t=InstallerTeam(installer_id=i.id, name='Equipa Sintética', name_key='equipa sintetica'); db.add(t); db.flush(); "
        "p=Project(name='Obra Migrada Sintética', installer_id=i.id, installer_team_id=t.id, "
        "work_start_date=dt.date(2035,1,1), work_end_date=dt.date(2035,1,4), is_active=True); db.add(p); db.commit(); db.close()"
    )
    subprocess.run([python, "-c", seed], cwd=root, env=env, text=True, capture_output=True, check=True)
    run("upgrade", "head")
    check = (
        "from app.db import SessionLocal; from app.models.project import Project, ProjectTeamAssignment; "
        "db=SessionLocal(); p=db.query(Project).filter(Project.name=='Obra Migrada Sintética').one(); "
        "a=db.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.project_id==p.id).one(); "
        "assert (a.installer_id, a.team_id, a.start_date.isoformat(), a.end_date.isoformat()) == "
        "(p.installer_id, p.installer_team_id, '2035-01-01', '2035-01-04'); db.close()"
    )
    subprocess.run([python, "-c", check], cwd=root, env=env, text=True, capture_output=True, check=True)
    run("downgrade", "d7a2c5e9b3f1")
    run("upgrade", "head")
    subprocess.run([python, "-c", check], cwd=root, env=env, text=True, capture_output=True, check=True)


def test_teams_view_conflicts_only_compare_visible_assignments(api_client, db_session):
    team = _team(db_session, ALFA, "Equipa 1")
    visible = _project(db_session, OWN)
    hidden = _project(db_session, LEGACY_PM)
    for project in (visible, hidden):
        project.installer_id = team.installer_id
        project.lifecycle_status = "construcao"
        db_session.add(
            ProjectTeamAssignment(
                project_id=project.id,
                installer_id=team.installer_id,
                team_id=team.id,
                start_date=dt.date(2047, 2, 10),
                end_date=dt.date(2047, 2, 12),
            )
        )
    db_session.flush()

    scoped = api_client.get(
        "/api/works/teams",
        params={"date": "2047-02-10", "days": 3, "installer_id": str(team.installer_id)},
        headers=_h(PM_UM),
    )
    scoped_team = next(
        item
        for installer in scoped.json()["installers"]
        for item in installer["teams"]
        if item["name"] == "Equipa 1"
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped_team["status"] == "ocupada"
    assert len(scoped_team["assignments"]) == 1
    assert scoped_team["assignments"][0]["project_name"] == OWN
    assert scoped_team["assignments"][0]["conflict"] is False
    assert LEGACY_PM not in scoped.text

    broad = api_client.get(
        "/api/works/teams",
        params={"date": "2047-02-10", "days": 3, "installer_id": str(team.installer_id)},
        headers=_h(CHEFE),
    )
    broad_team = next(
        item
        for installer in broad.json()["installers"]
        for item in installer["teams"]
        if item["name"] == "Equipa 1"
    )
    assert broad.status_code == 200, broad.text
    assert {row["project_name"] for row in broad_team["assignments"]} == {OWN, LEGACY_PM}
    assert all(row["conflict"] is True for row in broad_team["assignments"])


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="o lock de corrida exige PostgreSQL")
def test_postgres_overlap_check_is_serialized_before_insert(monkeypatch):
    from app.models.identity import User
    from app.security.permissions import AuthContext
    from app.services import team_assignments

    setup = SessionLocal()
    project_id = None
    try:
        team = (
            setup.query(InstallerTeam)
            .filter(InstallerTeam.name == "Equipa 1")
            .filter(InstallerTeam.installer.has(name=ALFA))
            .one()
        )
        user = setup.query(User).filter(User.email == CHEFE).one()
        project = Project(
            name=f"Corrida sintética {uuid.uuid4()}",
            lifecycle_status="construcao",
            is_active=True,
            installer_id=team.installer_id,
        )
        setup.add(project)
        setup.commit()
        project_id = project.id
        team_id = team.id
        user_id = user.id
        person_id = user.person_id
    finally:
        setup.close()

    original = team_assignments._check_same_project_overlap
    barrier = __import__("threading").Barrier(2, timeout=15)
    successes: list[str] = []
    errors: list[str] = []

    def synchronized_check(*args, **kwargs):
        barrier.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(team_assignments, "_check_same_project_overlap", synchronized_check)

    def worker() -> None:
        db = SessionLocal()
        try:
            project_row = db.query(Project).filter(Project.id == project_id).one()
            user_row = db.query(User).filter(User.id == user_id).one()
            ctx = AuthContext(
                user=user_row,
                person_id=person_id,
                role_codes=frozenset({"chefe_operacoes"}),
                permission_codes=frozenset({"project.view_all", "project.plan_work"}),
            )
            team_assignments.create_project_assignment(
                db,
                project=project_row,
                team_id=team_id,
                start_date=dt.date(2051, 2, 10),
                end_date=dt.date(2051, 2, 12),
                note="corrida sintética",
                ctx=ctx,
            )
            successes.append("created")
        except Exception as exc:  # noqa: BLE001 - the loser is asserted below
            errors.append(type(exc).__name__)
            db.rollback()
        finally:
            db.close()

    threads = [__import__("threading").Thread(target=worker) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)

        check = SessionLocal()
        try:
            persisted = check.query(ProjectTeamAssignment).filter(
                ProjectTeamAssignment.project_id == project_id,
                ProjectTeamAssignment.team_id == team_id,
                ProjectTeamAssignment.start_date == dt.date(2051, 2, 10),
                ProjectTeamAssignment.end_date == dt.date(2051, 2, 12),
            ).count()
        finally:
            check.close()
        assert successes == ["created"]
        assert errors == ["AssignmentError"]
        assert persisted == 1
    finally:
        monkeypatch.setattr(team_assignments, "_check_same_project_overlap", original)
        cleanup = SessionLocal()
        try:
            cleanup.query(ProjectHistory).filter(ProjectHistory.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.mark.parametrize("field", ["team_id", "start_date", "end_date"])
def test_assignment_update_rejects_null_for_required_fields(api_client, db_session, field):
    project = _make_assignable(api_client, db_session)
    team = _team(db_session, ALFA, "Equipa 1")
    created = _assign(api_client, project, team, dt.date(2034, 1, 10), dt.date(2034, 1, 12))
    assert created.status_code == 201, created.text

    response = api_client.patch(
        f"/api/projects/{project.id}/team-assignments/{created.json()['id']}",
        json={field: None},
        headers=_h(CHEFE),
    )

    assert response.status_code == 422, response.text


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="a serialização de PATCH exige PostgreSQL")
def test_postgres_same_assignment_patches_refresh_target_and_preserve_omitted_fields(monkeypatch):
    """Dois PATCHs concorrentes usam a linha actual depois do lock Project.

    Cada PATCH envia apenas uma data. A linha final tem de combinar as duas
    alterações serializadas, e cada evento de histórico deve guardar o valor
    que estava persistido quando essa alteração ganhou o lock.
    """
    from app.security.permissions import AuthContext
    from app.services import team_assignments

    setup = SessionLocal()
    person = Person(
        display_name=f"TEAM002 person {uuid.uuid4()}",
        email=f"team002-{uuid.uuid4()}@example.invalid",
    )
    installer = Installer(
        name=f"TEAM002 installer {uuid.uuid4()}",
        name_key=f"team002-installer-{uuid.uuid4()}",
    )
    setup.add_all([person, installer])
    setup.flush()
    team = InstallerTeam(
        installer_id=installer.id,
        name=f"TEAM002 team {uuid.uuid4()}",
        name_key=f"team002-team-{uuid.uuid4()}",
    )
    project = Project(
        name=f"TEAM002 project {uuid.uuid4()}",
        lifecycle_status="construcao",
        is_active=True,
        installer_id=installer.id,
    )
    setup.add_all([team, project])
    setup.flush()
    assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=installer.id,
        team_id=team.id,
        start_date=dt.date(2054, 1, 1),
        end_date=dt.date(2054, 1, 10),
    )
    setup.add(assignment)
    setup.commit()
    project_id, assignment_id, person_id = project.id, assignment.id, person.id
    installer_id, team_id = installer.id, team.id
    setup.close()

    barrier = threading.Barrier(2, timeout=20)
    original = team_assignments._check_same_project_overlap
    successes: list[str] = []
    errors: list[str] = []
    mutex = threading.Lock()

    def synchronized_check(*args, **kwargs):
        barrier.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(team_assignments, "_check_same_project_overlap", synchronized_check)

    def worker(changes: dict[str, dt.date]) -> None:
        session = SessionLocal()
        try:
            project_row = session.query(Project).filter(Project.id == project_id).one()
            assignment_row = (
                session.query(ProjectTeamAssignment)
                .filter(ProjectTeamAssignment.id == assignment_id)
                .one()
            )
            team_assignments.update_project_assignment(
                session,
                project=project_row,
                assignment=assignment_row,
                changes=changes,
                ctx=AuthContext(
                    user=None,
                    person_id=person_id,
                    role_codes=frozenset({"chefe_operacoes"}),
                    permission_codes=frozenset({"project.view_all", "project.plan_work"}),
                ),
            )
            with mutex:
                successes.append("ok")
        except Exception as exc:  # noqa: BLE001 - assert exact race outcome below
            with mutex:
                errors.append(type(exc).__name__)
            session.rollback()
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=({"start_date": dt.date(2054, 1, 4)},)),
        threading.Thread(target=worker, args=({"end_date": dt.date(2054, 1, 20)},)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)

        check = SessionLocal()
        try:
            final = check.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.id == assignment_id).one()
            history = (
                check.query(ProjectHistory)
                .filter(
                    ProjectHistory.project_id == project_id,
                    ProjectHistory.field_name.in_(
                        ["team_assignment.start_date", "team_assignment.end_date"]
                    ),
                )
                .all()
            )
            by_field = {entry.field_name: entry for entry in history}
            assert successes == ["ok", "ok"]
            assert errors == []
            assert (final.start_date, final.end_date) == (dt.date(2054, 1, 4), dt.date(2054, 1, 20))
            assert by_field["team_assignment.start_date"].old_value == "2054-01-01"
            assert by_field["team_assignment.start_date"].new_value == "2054-01-04"
            assert by_field["team_assignment.end_date"].old_value == "2054-01-10"
            assert by_field["team_assignment.end_date"].new_value == "2054-01-20"
        finally:
            check.close()
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(ProjectHistory).filter(ProjectHistory.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
            cleanup.query(InstallerTeam).filter(InstallerTeam.id == team_id).delete(synchronize_session=False)
            cleanup.query(Installer).filter(Installer.id == installer_id).delete(synchronize_session=False)
            cleanup.query(Person).filter(Person.id == person_id).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="a serialização de PATCH exige PostgreSQL")
def test_postgres_stale_delete_refreshes_assignment_before_history():
    """DELETE usa a linha actual quando a rota recebeu um ORM stale."""
    from app.security.permissions import AuthContext
    from app.services import team_assignments

    setup = SessionLocal()
    person = Person(
        display_name=f"TEAM002 delete person {uuid.uuid4()}",
        email=f"team002-delete-{uuid.uuid4()}@example.invalid",
    )
    installer = Installer(
        name=f"TEAM002 delete installer {uuid.uuid4()}",
        name_key=f"team002-delete-installer-{uuid.uuid4()}",
    )
    setup.add_all([person, installer])
    setup.flush()
    team = InstallerTeam(
        installer_id=installer.id,
        name=f"TEAM002 delete team {uuid.uuid4()}",
        name_key=f"team002-delete-team-{uuid.uuid4()}",
    )
    project = Project(
        name=f"TEAM002 delete project {uuid.uuid4()}",
        lifecycle_status="construcao",
        is_active=True,
        installer_id=installer.id,
    )
    setup.add_all([team, project])
    setup.flush()
    assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=installer.id,
        team_id=team.id,
        start_date=dt.date(2056, 1, 1),
        end_date=dt.date(2056, 1, 3),
    )
    setup.add(assignment)
    setup.commit()
    project_id, assignment_id, person_id = project.id, assignment.id, person.id
    installer_id, team_id = installer.id, team.id
    setup.close()

    stale = SessionLocal()
    writer = SessionLocal()
    try:
        stale_project = stale.query(Project).filter(Project.id == project_id).one()
        stale_assignment = (
            stale.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.id == assignment_id).one()
        )
        writer_project = writer.query(Project).filter(Project.id == project_id).one()
        writer_assignment = (
            writer.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.id == assignment_id).one()
        )
        ctx = AuthContext(
            user=None,
            person_id=person_id,
            role_codes=frozenset({"chefe_operacoes"}),
            permission_codes=frozenset({"project.view_all", "project.plan_work"}),
        )
        team_assignments.update_project_assignment(
            writer,
            project=writer_project,
            assignment=writer_assignment,
            changes={"start_date": dt.date(2056, 1, 4), "end_date": dt.date(2056, 1, 6)},
            ctx=ctx,
        )
        team_assignments.delete_project_assignment(
            stale,
            project=stale_project,
            assignment=stale_assignment,
            ctx=ctx,
        )
    finally:
        writer.close()

    try:
        check = SessionLocal()
        try:
            assert (
                check.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.id == assignment_id).one_or_none()
                is None
            )
            deleted = (
                check.query(ProjectHistory)
                .filter(
                    ProjectHistory.project_id == project_id,
                    ProjectHistory.field_name == "team_assignment",
                    ProjectHistory.new_value.is_(None),
                )
                .one()
            )
            assert deleted.old_value == f"{team_id}:2056-01-04:2056-01-06"
        finally:
            check.close()
    finally:
        stale.close()
        cleanup = SessionLocal()
        try:
            cleanup.query(ProjectHistory).filter(ProjectHistory.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
            cleanup.query(InstallerTeam).filter(InstallerTeam.id == team_id).delete(synchronize_session=False)
            cleanup.query(Installer).filter(Installer.id == installer_id).delete(synchronize_session=False)
            cleanup.query(Person).filter(Person.id == person_id).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="a serialização de PATCH exige PostgreSQL")
def test_postgres_same_assignment_patch_audit_old_values_follow_serialized_row(monkeypatch):
    """PATCHs completos concorrentes encadeiam o old_value de auditoria."""
    from app.security.permissions import AuthContext
    from app.services import team_assignments

    setup = SessionLocal()
    person = Person(
        display_name=f"TEAM002 audit person {uuid.uuid4()}",
        email=f"team002-audit-{uuid.uuid4()}@example.invalid",
    )
    installer = Installer(
        name=f"TEAM002 audit installer {uuid.uuid4()}",
        name_key=f"team002-audit-installer-{uuid.uuid4()}",
    )
    setup.add_all([person, installer])
    setup.flush()
    team = InstallerTeam(
        installer_id=installer.id,
        name=f"TEAM002 audit team {uuid.uuid4()}",
        name_key=f"team002-audit-team-{uuid.uuid4()}",
    )
    project = Project(
        name=f"TEAM002 audit project {uuid.uuid4()}",
        lifecycle_status="construcao",
        is_active=True,
        installer_id=installer.id,
    )
    setup.add_all([team, project])
    setup.flush()
    assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=installer.id,
        team_id=team.id,
        start_date=dt.date(2055, 1, 1),
        end_date=dt.date(2055, 1, 3),
    )
    setup.add(assignment)
    setup.commit()
    project_id, assignment_id, person_id = project.id, assignment.id, person.id
    installer_id, team_id = installer.id, team.id
    setup.close()

    barrier = threading.Barrier(2, timeout=20)
    original = team_assignments._check_same_project_overlap
    results: list[tuple[dt.date, dt.date]] = []
    errors: list[str] = []
    mutex = threading.Lock()

    def synchronized_check(*args, **kwargs):
        barrier.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(team_assignments, "_check_same_project_overlap", synchronized_check)

    def worker(start: dt.date, end: dt.date) -> None:
        session = SessionLocal()
        try:
            project_row = session.query(Project).filter(Project.id == project_id).one()
            assignment_row = (
                session.query(ProjectTeamAssignment)
                .filter(ProjectTeamAssignment.id == assignment_id)
                .one()
            )
            team_assignments.update_project_assignment(
                session,
                project=project_row,
                assignment=assignment_row,
                changes={"start_date": start, "end_date": end},
                ctx=AuthContext(
                    user=None,
                    person_id=person_id,
                    role_codes=frozenset({"chefe_operacoes"}),
                    permission_codes=frozenset({"project.view_all", "project.plan_work"}),
                ),
            )
            with mutex:
                results.append((start, end))
        except Exception as exc:  # noqa: BLE001 - assert exact race outcome below
            with mutex:
                errors.append(type(exc).__name__)
            session.rollback()
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(dt.date(2055, 1, 4), dt.date(2055, 1, 6))),
        threading.Thread(target=worker, args=(dt.date(2055, 1, 7), dt.date(2055, 1, 9))),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert all(not thread.is_alive() for thread in threads)

        check = SessionLocal()
        try:
            history = (
                check.query(ProjectHistory)
                .filter(
                    ProjectHistory.project_id == project_id,
                    ProjectHistory.field_name == "team_assignment.start_date",
                )
                .order_by(ProjectHistory.changed_at, ProjectHistory.id)
                .all()
            )
            final = check.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.id == assignment_id).one()
            assert len(results) == 2
            assert errors == []
            assert len(history) == 2
            assert history[0].old_value == "2055-01-01"
            assert history[1].old_value != "2055-01-01"
            assert {entry.new_value for entry in history} == {"2055-01-04", "2055-01-07"}
            assert final.start_date in {dt.date(2055, 1, 4), dt.date(2055, 1, 7)}
        finally:
            check.close()
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(ProjectHistory).filter(ProjectHistory.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(ProjectTeamAssignment).filter(ProjectTeamAssignment.project_id == project_id).delete(
                synchronize_session=False
            )
            cleanup.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
            cleanup.query(InstallerTeam).filter(InstallerTeam.id == team_id).delete(synchronize_session=False)
            cleanup.query(Installer).filter(Installer.id == installer_id).delete(synchronize_session=False)
            cleanup.query(Person).filter(Person.id == person_id).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
