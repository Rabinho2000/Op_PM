"""Pedidos de material a fornecedores (D-067): máquina de estados no servidor,
permissões por ação, âmbito, histórico append-only, total em Decimal e o
rascunho de email que o sistema nunca envia.
"""
from __future__ import annotations

import dataclasses
import os
import uuid
from decimal import Decimal

import pytest

from app.models.identity import User
from app.models.inventory import InventoryItem, MaterialRequest, MaterialRequestHistory
from app.models.project import Project
from app.models.supplier import Supplier
from app.security.permissions import PermissionDenied, load_auth_context
from app.services.material_requests import allowed_actions, apply_action

CHEFE = "chefe.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


@pytest.fixture()
def supplier(db_session):
    s = Supplier(name="Fornecedor de pedidos", email="orcamentos@fornecedor.invalid", contact="Ana", materials="Cabos", is_active=True)
    db_session.add(s)
    db_session.commit()
    return s


@pytest.fixture()
def item(db_session):
    it = InventoryItem(sku=f"REQ-{uuid.uuid4().hex[:8]}", name="Cabo solar 6mm", unit="m")
    db_session.add(it)
    db_session.commit()
    return it


@pytest.fixture()
def project(db_session):
    """Projeto do PM Um (pode criar pedidos aqui)."""
    return db_session.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


@pytest.fixture()
def other_project(db_session):
    """Projeto SEM PM — invisível ao PM Um."""
    return db_session.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def _create(api_client, project, *, supplier=None, item=None, email=CHEFE, lines=None, notes=""):
    lines = lines if lines is not None else [
        {"item_id": str(item.id) if item else None, "description": "" if item else "Painel 450 W", "quantity": "10"},
        {"description": "Conectores MC4", "quantity": "5"},
    ]
    body = {"project_id": str(project.id), "lines": lines, "notes": notes}
    if supplier:
        body["supplier_id"] = str(supplier.id)
    return api_client.post("/api/material-requests", json=body, headers=_h(email))


def _act(api_client, request_id, action, *, email=CHEFE, note="", prices=None):
    return api_client.post(
        f"/api/material-requests/{request_id}/actions",
        json={"action": action, "note": note, "prices": prices or []},
        headers=_h(email),
    )


def _prices(request_json, *values):
    return [{"line_id": line["id"], "unit_price": str(v)} for line, v in zip(request_json["lines"], values)]


def _to_quote(api_client, project, supplier, item=None, prices=("10.10", "4.33")):
    """Cria e leva o pedido até `orcamento_recebido` (como Chefe)."""
    body = _create(api_client, project, supplier=supplier, item=item).json()
    assert _act(api_client, body["id"], "send").status_code == 200
    resp = _act(api_client, body["id"], "record_quote", prices=_prices(body, *prices))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Criação ---


def test_pm_creates_a_draft_on_their_own_project(api_client, project, supplier, item):
    resp = _create(api_client, project, supplier=supplier, item=item, email=PM)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "rascunho"
    assert body["supplier_name"] == "Fornecedor de pedidos"
    assert body["created_by_display_name"] == "PM Sintético Um"
    assert body["lines"][0]["description"] == "Cabo solar 6mm"  # vem do item quando não há descrição
    assert body["lines"][0]["unit"] == "m"
    assert body["total"] is None  # sem preços não há total (nunca um parcial)
    # PM só cria: pode cancelar o seu rascunho, não o pode enviar (envio é aprovação humana)
    assert body["allowed_actions"] == ["cancel"]
    assert [h["action"] for h in body["history"]] == ["create"]


def test_pm_cannot_create_on_a_project_that_is_not_theirs(api_client, other_project):
    resp = _create(api_client, other_project, email=PM)
    assert resp.status_code in (403, 404)  # 404: nem sequer vê o projeto


def test_roles_without_material_request_create_are_refused(api_client, project):
    assert _create(api_client, project, email=COMERCIAL).status_code == 403


@pytest.mark.parametrize(
    "lines, expected",
    [
        ([], 422),  # schema: pelo menos uma linha
        ([{"description": "X", "quantity": "0"}], 400),
        ([{"description": "X", "quantity": "-1"}], 400),
        ([{"description": "", "quantity": "1"}], 400),  # sem item nem descrição
        ([{"item_id": str(uuid.uuid4()), "quantity": "1"}], 400),  # item inexistente
    ],
)
def test_line_validation(api_client, project, lines, expected):
    assert _create(api_client, project, lines=lines).status_code == expected


def test_unknown_or_inactive_supplier_is_refused(db_session, api_client, project):
    inactive = Supplier(name="Inativo", is_active=False)
    db_session.add(inactive)
    db_session.commit()
    assert _create(api_client, project, supplier=inactive).status_code == 400
    ghost = type("S", (), {"id": uuid.uuid4()})()
    assert _create(api_client, project, supplier=ghost).status_code == 400


# --- Fluxo completo e histórico ---


def test_full_lifecycle_records_who_did_each_step(db_session, api_client, project, supplier, item):
    created = _create(api_client, project, supplier=supplier, item=item, email=PM).json()  # o PM cria...
    rid = created["id"]
    # ...o Chefe envia, regista o orçamento, aprova e adjudica.
    assert _act(api_client, rid, "send").json()["status"] == "pedido_enviado"
    quoted = _act(api_client, rid, "record_quote", prices=_prices(created, "10.10", "4.33"))
    assert quoted.json()["status"] == "orcamento_recebido"
    approved = _act(api_client, rid, "approve").json()
    assert approved["status"] == "aprovado"
    assert approved["approved_by_display_name"] == "Chefe Sintético"
    done = _act(api_client, rid, "adjudicate").json()
    assert done["status"] == "adjudicado"

    history = done["history"]
    assert [(h["action"], h["from_status"], h["to_status"]) for h in history] == [
        ("create", None, "rascunho"),
        ("send", "rascunho", "pedido_enviado"),
        ("record_quote", "pedido_enviado", "orcamento_recebido"),
        ("approve", "orcamento_recebido", "aprovado"),
        ("adjudicate", "aprovado", "adjudicado"),
    ]
    assert [h["changed_by_display_name"] for h in history] == ["PM Sintético Um"] + ["Chefe Sintético"] * 4
    assert done["allowed_actions"] == []  # adjudicado é terminal neste MVP


def test_total_is_a_decimal_rounded_half_up_to_two_places(api_client, project, supplier):
    lines = [{"description": "A", "quantity": "3"}, {"description": "B", "quantity": "2.5"}]
    body = _create(api_client, project, supplier=supplier, lines=lines).json()
    _act(api_client, body["id"], "send")
    quoted = _act(api_client, body["id"], "record_quote", prices=_prices(body, "10.10", "4.33")).json()
    # 3 × 10.10 + 2.5 × 4.33 = 30.30 + 10.825 = 41.125 -> 41.13 (nunca 41.12 por float)
    assert Decimal(quoted["total"]) == Decimal("41.13")
    assert [Decimal(line["line_total"]) for line in quoted["lines"]] == [Decimal("30.30"), Decimal("10.83")]


# --- Máquina de estados ---


@pytest.mark.parametrize(
    "action",
    ["record_quote", "approve", "adjudicate"],
)
def test_cannot_skip_steps_from_a_draft(api_client, project, supplier, action):
    body = _create(api_client, project, supplier=supplier).json()
    resp = _act(api_client, body["id"], action, prices=_prices(body, "1", "1"))
    assert resp.status_code == 400
    assert "não permitida" in resp.json()["detail"]


def test_cannot_adjudicate_before_the_quote_is_approved(api_client, project, supplier):
    quoted = _to_quote(api_client, project, supplier)
    assert _act(api_client, quoted["id"], "adjudicate").status_code == 400


def test_terminal_states_allow_nothing(api_client, project, supplier):
    quoted = _to_quote(api_client, project, supplier)
    _act(api_client, quoted["id"], "approve")
    _act(api_client, quoted["id"], "adjudicate")
    for action in ("send", "record_quote", "approve", "adjudicate", "cancel"):
        assert _act(api_client, quoted["id"], action, note="x").status_code == 400

    cancelled = _create(api_client, project, supplier=supplier).json()
    assert _act(api_client, cancelled["id"], "cancel").status_code == 200
    for action in ("send", "cancel"):
        assert _act(api_client, cancelled["id"], action, note="x").status_code == 400


def test_a_quote_can_be_corrected_before_approval(api_client, project, supplier):
    quoted = _to_quote(api_client, project, supplier, prices=("10", "10"))
    again = _act(api_client, quoted["id"], "record_quote", prices=_prices(quoted, "9", "9")).json()
    assert again["status"] == "orcamento_recebido"
    assert Decimal(again["total"]) == Decimal("135.00")  # 10×9 + 5×9
    assert [h["action"] for h in again["history"]].count("record_quote") == 2


def test_send_needs_a_supplier(api_client, project):
    body = _create(api_client, project).json()  # sem fornecedor
    resp = _act(api_client, body["id"], "send")
    assert resp.status_code == 400 and "fornecedor" in resp.json()["detail"].lower()


def test_quote_must_price_every_line_with_positive_values(api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier).json()
    _act(api_client, body["id"], "send")
    only_first = [_prices(body, "10")[0]]
    assert _act(api_client, body["id"], "record_quote", prices=only_first).status_code == 400  # falta uma linha
    assert _act(api_client, body["id"], "record_quote", prices=_prices(body, "10", "0")).status_code == 400
    assert _act(api_client, body["id"], "record_quote", prices=_prices(body, "10", "-2")).status_code == 400
    foreign = [{"line_id": str(uuid.uuid4()), "unit_price": "1"}, *_prices(body, "10", "5")]
    assert _act(api_client, body["id"], "record_quote", prices=foreign).status_code == 400
    dup = _prices(body, "10", "5") + [_prices(body, "1")[0]]
    assert _act(api_client, body["id"], "record_quote", prices=dup).status_code == 400  # linha repetida
    # nada ficou gravado pelas tentativas falhadas
    assert api_client.get(f"/api/material-requests/{body['id']}", headers=_h(CHEFE)).json()["status"] == "pedido_enviado"


def test_cancelling_a_sent_request_needs_a_reason(api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier).json()
    _act(api_client, body["id"], "send")
    assert _act(api_client, body["id"], "cancel").status_code == 400
    resp = _act(api_client, body["id"], "cancel", note="Fornecedor sem stock")
    assert resp.status_code == 200 and resp.json()["history"][-1]["note"] == "Fornecedor sem stock"


# --- Permissões ---


def test_pm_cannot_send_approve_or_adjudicate(api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier, email=PM).json()
    assert _act(api_client, body["id"], "send", email=PM).status_code == 403  # nem o seu próprio rascunho
    quoted = _to_quote(api_client, project, supplier)
    assert _act(api_client, quoted["id"], "approve", email=PM).status_code == 403
    assert _act(api_client, quoted["id"], "approve").status_code == 200  # o Chefe aprova...
    assert _act(api_client, quoted["id"], "adjudicate", email=PM).status_code == 403  # ...o PM não adjudica


def test_pm_can_cancel_only_their_own_draft_never_a_sent_request(api_client, project, supplier):
    mine = _create(api_client, project, supplier=supplier, email=PM).json()
    assert _act(api_client, mine["id"], "cancel", email=PM).status_code == 200

    sent = _create(api_client, project, supplier=supplier, email=PM).json()
    _act(api_client, sent["id"], "send")  # o Chefe envia
    assert _act(api_client, sent["id"], "cancel", email=PM, note="quero cancelar").status_code == 403

    # rascunho de OUTRA pessoa (criado pelo Chefe) também não
    chefes = _create(api_client, project, supplier=supplier).json()
    assert _act(api_client, chefes["id"], "cancel", email=PM).status_code == 403


def test_approve_permission_does_not_imply_adjudicate(db_session, api_client, project, supplier):
    """Nenhum perfil do catálogo aprova sem adjudicar, por isso testa-se o
    serviço com um contexto a que se retira `material_request.adjudicate`."""
    quoted = _to_quote(api_client, project, supplier)
    _act(api_client, quoted["id"], "approve")
    chefe = db_session.query(User).filter(User.email == CHEFE).one()
    full = load_auth_context(db_session, chefe)
    limited = dataclasses.replace(full, permission_codes=full.permission_codes - {"material_request.adjudicate"})
    request = db_session.get(MaterialRequest, uuid.UUID(quoted["id"]))
    with pytest.raises(PermissionDenied):
        apply_action(db_session, limited, request, project, action="adjudicate")
    assert request.status == "aprovado"  # nada mudou
    assert "adjudicate" not in allowed_actions(limited, request, project)


def test_allowed_actions_follow_state_and_role(api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier).json()
    assert body["allowed_actions"] == ["send", "cancel"]  # Chefe em rascunho
    sent = _act(api_client, body["id"], "send").json()
    assert sent["allowed_actions"] == ["record_quote", "cancel"]
    quoted = _act(api_client, body["id"], "record_quote", prices=_prices(body, "1", "1")).json()
    assert quoted["allowed_actions"] == ["record_quote", "approve", "cancel"]
    approved = _act(api_client, body["id"], "approve").json()
    assert approved["allowed_actions"] == ["adjudicate", "cancel"]


# --- Âmbito ---


def test_requests_of_projects_outside_the_scope_are_invisible(db_session, api_client, other_project, supplier):
    body = _create(api_client, other_project, supplier=supplier).json()  # Chefe cria num projeto sem PM
    assert api_client.get(f"/api/material-requests/{body['id']}", headers=_h(PM)).status_code == 404
    listing = api_client.get("/api/material-requests", headers=_h(PM)).json()
    assert body["id"] not in {r["id"] for r in listing}
    assert _act(api_client, body["id"], "cancel", email=PM).status_code == 404  # nem sabe que existe
    # o Chefe vê-o
    assert api_client.get(f"/api/material-requests/{body['id']}", headers=_h(CHEFE)).status_code == 200


def test_roles_without_inventory_view_cannot_list(api_client):
    assert api_client.get("/api/material-requests", headers=_h(COMERCIAL)).status_code == 403


def test_list_filters(api_client, project, supplier):
    a = _create(api_client, project, supplier=supplier).json()
    _act(api_client, a["id"], "send")
    b = _create(api_client, project).json()
    by_status = api_client.get("/api/material-requests?status=pedido_enviado", headers=_h(CHEFE)).json()
    assert {r["id"] for r in by_status} == {a["id"]}
    by_supplier = api_client.get(f"/api/material-requests?supplier_id={supplier.id}", headers=_h(CHEFE)).json()
    assert {r["id"] for r in by_supplier} == {a["id"]}
    by_project = api_client.get(f"/api/material-requests?project_id={project.id}", headers=_h(CHEFE)).json()
    assert {a["id"], b["id"]} <= {r["id"] for r in by_project}


# --- Edição do rascunho ---


def test_only_a_draft_is_editable(api_client, project, supplier, item):
    body = _create(api_client, project, supplier=supplier, email=PM).json()
    edited = api_client.patch(
        f"/api/material-requests/{body['id']}",
        json={"notes": "Urgente", "lines": [{"item_id": str(item.id), "quantity": "20"}]},
        headers=_h(PM),
    )
    assert edited.status_code == 200
    assert edited.json()["notes"] == "Urgente"
    assert [(line["description"], Decimal(line["quantity"])) for line in edited.json()["lines"]] == [
        ("Cabo solar 6mm", Decimal("20"))
    ]
    _act(api_client, body["id"], "send")
    again = api_client.patch(f"/api/material-requests/{body['id']}", json={"notes": "tarde demais"}, headers=_h(PM))
    assert again.status_code == 400


def test_status_can_never_be_set_by_editing(api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier).json()
    resp = api_client.patch(f"/api/material-requests/{body['id']}", json={"status": "adjudicado"}, headers=_h(CHEFE))
    assert resp.status_code == 422  # extra="forbid": só as ações mudam o estado
    assert api_client.get(f"/api/material-requests/{body['id']}", headers=_h(CHEFE)).json()["status"] == "rascunho"


def test_pm_cannot_edit_a_draft_created_by_someone_else(api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier).json()  # criado pelo Chefe
    resp = api_client.patch(f"/api/material-requests/{body['id']}", json={"notes": "x"}, headers=_h(PM))
    assert resp.status_code == 403


# --- Rascunho de email ---


def test_email_draft_is_text_for_a_person_and_the_system_never_sends_it(db_session, api_client, project, supplier, item):
    body = _create(api_client, project, supplier=supplier, item=item, notes="Entrega antes de dia 30").json()
    _act(api_client, body["id"], "send")
    _act(api_client, body["id"], "record_quote", prices=_prices(body, "10.10", "4.33"))

    outbox = os.environ.get("GRAPH_FALLBACK_DIR", "")
    before = sorted(os.listdir(outbox)) if outbox and os.path.isdir(outbox) else []
    draft = api_client.get(f"/api/material-requests/{body['id']}/email-draft", headers=_h(CHEFE)).json()
    after = sorted(os.listdir(outbox)) if outbox and os.path.isdir(outbox) else []

    assert draft["to"] == "orcamentos@fornecedor.invalid"
    assert project.name in draft["subject"]
    assert "Cabo solar 6mm" in draft["body"] and "Conectores MC4" in draft["body"]
    assert "Entrega antes de dia 30" in draft["body"]
    assert "10.10" not in draft["body"] and "4.33" not in draft["body"]  # nunca preços no pedido de orçamento
    assert before == after  # o GET não escreveu nenhum .eml (D-010): só devolve texto


def test_email_draft_needs_visibility(api_client, other_project, supplier):
    body = _create(api_client, other_project, supplier=supplier).json()
    assert api_client.get(f"/api/material-requests/{body['id']}/email-draft", headers=_h(PM)).status_code == 404


# --- Auditoria e desempenho ---


def test_history_is_append_only_and_failed_attempts_leave_no_trace(db_session, api_client, project, supplier):
    body = _create(api_client, project, supplier=supplier).json()
    before = db_session.query(MaterialRequestHistory).filter_by(request_id=uuid.UUID(body["id"])).count()
    assert _act(api_client, body["id"], "approve").status_code == 400  # transição inválida
    assert _act(api_client, body["id"], "send", email=PM).status_code == 403  # sem permissão
    assert db_session.query(MaterialRequestHistory).filter_by(request_id=uuid.UUID(body["id"])).count() == before
    assert not hasattr(MaterialRequestHistory, "updated_at")  # sem updated_at, como as outras auditorias


def test_list_query_count_does_not_grow_with_the_number_of_requests(db_session, api_client, project, supplier, item):
    from sqlalchemy import event

    from app.db import engine

    def count() -> int:
        counter = {"n": 0}

        def _on(*_a, **_k):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on)
        try:
            assert api_client.get("/api/material-requests", headers=_h(CHEFE)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on)
        return counter["n"]

    _create(api_client, project, supplier=supplier, item=item)
    few = count()
    for _ in range(10):
        _create(api_client, project, supplier=supplier, item=item)
    assert count() <= few + 1, "queries a crescer com o nº de pedidos — provável N+1"


def test_lines_keep_the_order_they_were_entered(api_client, project, supplier):
    """Regressão: as linhas ordenavam-se por `created_at` (1 s de resolução em
    SQLite), por isso as criadas no mesmo segundo saíam por UUID aleatório. A
    lista vai por email ao fornecedor — a ordem tem de ser a introduzida."""
    names = [f"Material {chr(ord('A') + i)}" for i in range(9)][::-1]  # ordem 'estranha' de propósito
    lines = [{"description": n, "quantity": str(i + 1)} for i, n in enumerate(names)]
    body = _create(api_client, project, supplier=supplier, lines=lines).json()
    assert [line["description"] for line in body["lines"]] == names

    for _ in range(3):  # estável entre leituras, no detalhe, na listagem e no email
        detail = api_client.get(f"/api/material-requests/{body['id']}", headers=_h(CHEFE)).json()
        assert [line["description"] for line in detail["lines"]] == names
    listed = next(r for r in api_client.get("/api/material-requests", headers=_h(CHEFE)).json() if r["id"] == body["id"])
    assert [line["description"] for line in listed["lines"]] == names
    draft = api_client.get(f"/api/material-requests/{body['id']}/email-draft", headers=_h(CHEFE)).json()["body"]
    assert [draft.index(n) for n in names] == sorted(draft.index(n) for n in names)

    reversed_lines = list(reversed(lines))  # editar o rascunho substitui as linhas pela nova ordem
    edited = api_client.patch(
        f"/api/material-requests/{body['id']}", json={"lines": reversed_lines}, headers=_h(CHEFE)
    ).json()
    assert [line["description"] for line in edited["lines"]] == list(reversed(names))


def test_unit_price_keeps_up_to_four_decimals_and_is_never_rounded_silently(api_client, project, supplier):
    """Regressão: `unit_price` era Numeric(12,2) e um preço de 4.325 €/un ficava
    4.33 sem aviso, alterando o total. Materiais custam frações de cêntimo."""
    lines = [{"description": "Cabo", "quantity": "40"}, {"description": "Conector", "quantity": "1000"}]
    body = _create(api_client, project, supplier=supplier, lines=lines).json()
    _act(api_client, body["id"], "send")

    quoted = _act(api_client, body["id"], "record_quote", prices=_prices(body, "4.325", "0.0875")).json()
    assert [Decimal(line["unit_price"]) for line in quoted["lines"]] == [Decimal("4.325"), Decimal("0.0875")]
    # 40 × 4.325 = 173.00 ; 1000 × 0.0875 = 87.50 ; total 260.50
    # (com os preços arredondados a 2 casas — 4.33 e 0.09 — seria 263.20)
    assert [Decimal(line["line_total"]) for line in quoted["lines"]] == [Decimal("173.00"), Decimal("87.50")]
    assert Decimal(quoted["total"]) == Decimal("260.50")


@pytest.mark.parametrize("price", ["1.23456", "0.00001"])
def test_a_price_with_more_than_four_decimals_is_refused_not_rounded(api_client, project, supplier, price):
    body = _create(api_client, project, supplier=supplier).json()
    _act(api_client, body["id"], "send")
    resp = _act(api_client, body["id"], "record_quote", prices=_prices(body, price, "1"))
    assert resp.status_code == 400
    assert "4 casas decimais" in resp.json()["detail"]
    # nada ficou gravado
    assert api_client.get(f"/api/material-requests/{body['id']}", headers=_h(CHEFE)).json()["status"] == "pedido_enviado"
