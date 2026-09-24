"""Calendário de obras (D-072): janela, âmbito, filtros, conflitos por equipa e
"por planear"."""
from __future__ import annotations

import datetime as dt


from app.models.identity import User
from app.models.installer import Installer, InstallerTeam
from app.models.people import Person
from app.models.project import Project

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"

ALFA = "Instalador Sintético Alfa"
D = dt.date


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _get(api_client, email=CHEFE, **params):
    """`from`/`to` obrigatórios; por omissão uma janela larga em torno de hoje."""
    today = dt.date.today()
    query = {"from": (today - dt.timedelta(days=200)).isoformat(), "to": (today + dt.timedelta(days=200)).isoformat()}
    query.update({k: v for k, v in params.items() if v is not None})
    return api_client.get("/api/works/calendar", params=query, headers=_h(email))


def _names(resp) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {w["name"] for w in resp.json()["works"]}


def _team(db, installer_name, team_name) -> InstallerTeam:
    installer = db.query(Installer).filter(Installer.name == installer_name).one()
    return next(t for t in installer.teams if t.name == team_name)


def _new(db, name, *, start, end, team=None, installer=None, state="construcao", pm=None, active=True) -> Project:
    project = Project(
        name=name,
        is_active=active,
        lifecycle_status=state,
        work_start_date=start,
        work_end_date=end,
        pm_person_id=pm,
        installer_id=(team.installer_id if team else (installer.id if installer else None)),
        installer_team_id=team.id if team else None,
    )
    db.add(project)
    db.flush()
    return project


# --- janela, âmbito, permissões ----------------------------------------------------


def test_seed_works_appear_with_installer_team_and_dates(api_client):
    body = _get(api_client).json()
    by_name = {w["name"]: w for w in body["works"]}
    demo = by_name["Instalação Sintética de Demonstração"]
    assert demo["installer_name"] == ALFA and demo["installer_team_name"] == "Equipa 1"
    assert demo["pm_display_name"] == "PM Sintético Um" and demo["lifecycle_status"] == "construcao"
    assert demo["work_start_date"] < demo["work_end_date"] and demo["work_dates_estimated"] is False
    assert body["summary"]["works"] == len(body["works"])


def test_window_is_inclusive_and_only_returns_overlapping_works(db_session, api_client):
    _new(db_session, "Janela A", start=D(2031, 1, 10), end=D(2031, 1, 20))
    inside = lambda a, b: _names(api_client.get("/api/works/calendar", params={"from": a, "to": b}, headers=_h(CHEFE)))  # noqa: E731
    assert "Janela A" in inside("2031-01-01", "2031-01-31")
    assert "Janela A" in inside("2031-01-20", "2031-02-05")  # toca no último dia
    assert "Janela A" in inside("2030-12-01", "2031-01-10")  # toca no primeiro dia
    assert "Janela A" not in inside("2031-01-21", "2031-02-05")
    assert "Janela A" not in inside("2030-12-01", "2031-01-09")
    assert "Janela A" in inside("2031-01-12", "2031-01-14")  # janela dentro da obra


def test_invalid_windows_and_parameters(api_client):
    assert api_client.get("/api/works/calendar", headers=_h(CHEFE)).status_code == 422  # sem from/to
    bad = api_client.get("/api/works/calendar", params={"from": "2031-02-01", "to": "2031-01-01"}, headers=_h(CHEFE))
    assert bad.status_code == 422 and "anterior" in bad.json()["detail"]
    huge = api_client.get("/api/works/calendar", params={"from": "2020-01-01", "to": "2031-01-01"}, headers=_h(CHEFE))
    assert huge.status_code == 422 and "800" in huge.json()["detail"]
    assert _get(api_client, lifecycle_status="inventado").status_code == 400
    assert _get(api_client, pm_person_id="não-é-uuid").status_code == 422


def test_pm_only_sees_own_works_and_chefe_sees_all(api_client):
    chefe = _names(_get(api_client))
    pm = _names(_get(api_client, email=PM_UM))
    assert pm and pm < chefe  # o PM vê um subconjunto estrito
    assert "Instalação Sintética de Demonstração" in pm
    assert "Instalação Sintética F — PM Legado" in chefe and "Instalação Sintética F — PM Legado" not in pm


def test_read_only_roles_can_see_and_users_without_project_access_cannot(db_session, api_client):
    assert _get(api_client, email=COMERCIAL).status_code == 200
    person = Person(display_name="Sem Papéis", email="sem.papeis@example.invalid", is_active=True)
    db_session.add(person)
    db_session.flush()
    db_session.add(User(person_id=person.id, email="sem.papeis@example.invalid", is_active=True))
    db_session.flush()
    assert _get(api_client, email="sem.papeis@example.invalid").status_code == 403


def test_inactive_projects_never_appear(db_session, api_client):
    _new(db_session, "Inativa com datas", start=D(2031, 3, 1), end=D(2031, 3, 5), active=False)
    resp = api_client.get("/api/works/calendar", params={"from": "2031-01-01", "to": "2031-12-31"}, headers=_h(CHEFE))
    assert "Inativa com datas" not in _names(resp)


# --- filtros ----------------------------------------------------------------------------


def test_filters_by_pm_state_installer_and_team(db_session, api_client):
    pm_um = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    all_names = _names(_get(api_client))

    by_pm = _names(_get(api_client, pm_person_id=str(pm_um.id)))
    assert by_pm and by_pm < all_names

    hold = _new(db_session, "Em espera", start=D.today(), end=D.today() + dt.timedelta(days=3), state="on_hold_cliente")
    only_hold = _names(_get(api_client, lifecycle_status="on_hold_cliente"))
    assert only_hold == {hold.name}
    two = _names(_get(api_client, lifecycle_status=["on_hold_cliente", "construcao"]))
    assert hold.name in two and "Instalação Sintética de Demonstração" in two

    alfa = db_session.query(Installer).filter(Installer.name == ALFA).one()
    by_installer = _names(_get(api_client, installer_id=str(alfa.id)))
    assert "Instalação Sintética de Demonstração" in by_installer and "Instalação Sintética F — PM Legado" not in by_installer
    equipa2 = _team(db_session, ALFA, "Equipa 2")
    assert _names(_get(api_client, team_id=str(equipa2.id))) == {"Instalação Sintética A — Início Próximo"}

    # Filtros combinados fazem interseção.
    assert _names(_get(api_client, pm_person_id=str(pm_um.id), lifecycle_status="on_hold_cliente")) == set()


# --- conflitos por equipa ----------------------------------------------------------------


def test_seed_pair_on_the_same_team_is_a_conflict(api_client):
    body = _get(api_client).json()
    flags = {w["name"]: w["conflict"] for w in body["works"]}
    assert flags["Instalação Sintética de Demonstração"] is True
    assert flags["Instalação Sintética G — Trabalho Urgente"] is True
    assert flags["Instalação Sintética A — Início Próximo"] is False  # outra equipa do mesmo instalador
    assert flags["Instalação Sintética B — Atrasada"] is False  # sem equipa
    assert body["summary"]["conflicts"] == 2


def test_conflict_survives_filters_that_hide_the_other_side(db_session, api_client):
    """Filtrar pelo PM de uma das obras não esconde que a outra (de outro PM) a sobrepõe."""
    demo = db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()
    other = db_session.query(Project).filter(Project.name == "Instalação Sintética G — Trabalho Urgente").one()
    other.pm_person_id = None  # o outro lado passa a ser de outro PM (nenhum)
    db_session.flush()
    resp = _get(api_client, pm_person_id=str(demo.pm_person_id))
    works = {w["name"]: w for w in resp.json()["works"]}
    assert "Instalação Sintética G — Trabalho Urgente" not in works
    assert works["Instalação Sintética de Demonstração"]["conflict"] is True


def test_conflict_rules_touching_days_states_and_teams(db_session, api_client):
    team = _team(db_session, ALFA, "Equipa 2")
    other_team = _team(db_session, ALFA, "Equipa 1")
    base = D(2032, 5, 10)

    def d(n):
        return base + dt.timedelta(days=n)

    a = _new(db_session, "C-A", start=d(0), end=d(4), team=team)
    b = _new(db_session, "C-B", start=d(4), end=d(8), team=team)  # partilha o dia 4 → conflito
    c = _new(db_session, "C-C", start=d(9), end=d(12), team=team)  # começa no dia seguinte a B → sem conflito
    e = _new(db_session, "C-E", start=d(0), end=d(12), team=other_team, state="construido")  # acabada: nunca conflito
    f = _new(db_session, "C-F", start=d(1), end=d(3), team=other_team, state="construido")
    g = _new(db_session, "C-G", start=d(20), end=d(25), team=team, state="on_hold_cliente")
    h = _new(db_session, "C-H", start=d(21), end=d(24), team=team, state="preparacao")  # G em espera não ocupa a equipa
    i = _new(db_session, "C-I", start=d(30), end=d(33), team=team, state="preparacao")
    j = _new(db_session, "C-J", start=d(32), end=d(35), team=team, state="construcao")  # preparação × construção → conflito
    k = _new(db_session, "C-K", start=d(0), end=d(12), state="construcao")  # sem equipa: nunca conflito
    l = _new(db_session, "C-L", start=d(0), end=d(12), state="construcao")

    resp = api_client.get(
        "/api/works/calendar", params={"from": d(-1).isoformat(), "to": d(40).isoformat()}, headers=_h(CHEFE)
    )
    flags = {w["name"]: w["conflict"] for w in resp.json()["works"] if w["name"].startswith("C-")}
    assert flags == {
        "C-A": True, "C-B": True, "C-C": False, "C-E": False, "C-F": False,
        "C-G": False, "C-H": False, "C-I": True, "C-J": True, "C-K": False, "C-L": False,
    }
    assert {a.id, b.id, c.id, e.id, f.id, g.id, h.id, i.id, j.id, k.id, l.id}  # criadas


def test_a_chain_of_overlaps_flags_every_member_but_not_the_gap(db_session, api_client):
    team = _team(db_session, ALFA, "Equipa 2")
    base = D(2033, 1, 3)
    for index, (s, e) in enumerate([(0, 6), (5, 10), (9, 14), (20, 22)]):
        _new(db_session, f"Ch-{index}", start=base + dt.timedelta(days=s), end=base + dt.timedelta(days=e), team=team)
    resp = api_client.get("/api/works/calendar", params={"from": "2033-01-01", "to": "2033-02-28"}, headers=_h(CHEFE))
    flags = {w["name"]: w["conflict"] for w in resp.json()["works"] if w["name"].startswith("Ch-")}
    assert flags == {"Ch-0": True, "Ch-1": True, "Ch-2": True, "Ch-3": False}


# --- por planear -----------------------------------------------------------------------------


def test_unscheduled_lists_active_projects_still_to_plan(db_session, api_client):
    _new(db_session, "Falta datas", start=None, end=None, state="preparacao")
    _new(db_session, "Só início", start=D(2031, 1, 1), end=None, state="construcao")
    _new(db_session, "Sem estado sem datas", start=None, end=None, state=None)
    _new(db_session, "Concluída sem datas", start=None, end=None, state="certificado_final")
    _new(db_session, "Entregue sem datas", start=None, end=None, state="entregue_cliente")
    _new(db_session, "Inativa sem datas", start=None, end=None, state="preparacao", active=False)

    body = _get(api_client).json()
    to_plan = {p["name"] for p in body["unscheduled"]}
    assert {"Falta datas", "Só início", "Sem estado sem datas"} <= to_plan
    assert not ({"Concluída sem datas", "Entregue sem datas", "Inativa sem datas"} & to_plan)
    assert body["summary"]["unscheduled"] >= 3
    # Uma obra só com uma das datas nunca aparece no calendário.
    assert "Só início" not in {w["name"] for w in body["works"]}


def test_unscheduled_respects_scope_and_filters(db_session, api_client):
    pm_um = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    _new(db_session, "Do PM Um sem datas", start=None, end=None, state="preparacao", pm=pm_um.id)
    _new(db_session, "De ninguém sem datas", start=None, end=None, state="preparacao")

    pm_view = {p["name"] for p in _get(api_client, email=PM_UM).json()["unscheduled"]}
    assert "Do PM Um sem datas" in pm_view and "De ninguém sem datas" not in pm_view
    filtered = {p["name"] for p in _get(api_client, lifecycle_status="construcao").json()["unscheduled"]}
    assert "Do PM Um sem datas" not in filtered  # está em preparação


# --- desempenho ---------------------------------------------------------------------------------


def test_query_count_does_not_grow_with_the_number_of_works(db_session, api_client):
    from sqlalchemy import event

    from app.db import engine

    def count() -> int:
        counter = {"n": 0}

        def _on(*_a, **_k):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on)
        try:
            assert _get(api_client).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on)
        return counter["n"]

    pm_um = db_session.query(Person).filter(Person.display_name == "PM Sintético Um").one()
    few = count()
    alfa = db_session.query(Installer).filter(Installer.name == ALFA).one()
    today = D.today()
    for n in range(25):
        team = alfa.teams[n % len(alfa.teams)]
        _new(db_session, f"Extra {n}", start=today, end=today + dt.timedelta(days=n % 7), team=team, pm=pm_um.id)
    assert count() <= few + 2, "queries a crescer com o nº de obras — provável N+1"
