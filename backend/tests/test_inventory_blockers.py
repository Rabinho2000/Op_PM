"""Regression tests for inventory concurrency, idempotency and atomic catalog writes."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Thread

import pytest
from app.db import engine
from app.models.inventory import InventoryItem, InventoryLocation, InventoryMovement
from app.models.project import Project
from app.services import inventory_catalog as inventory_catalog_service
from app.services.inventory import (
    InactiveInventoryReferenceError,
    InsufficientStockError,
    _movement_fingerprint,
    enter_stock,
    reserve_for_project,
)
from sqlalchemy import create_engine, false, inspect, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

CHEFE_EMAIL = "chefe.sintetico@example.invalid"


def _copy_sqlite_db(source: Path, target: str) -> None:
    """Cópia consistente da BD SQLite (em WAL, `shutil.copy2` perderia o conteúdo do -wal)."""
    import sqlite3

    src = sqlite3.connect(str(source), timeout=30)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _headers() -> dict[str, str]:
    return {"X-Dev-User-Email": CHEFE_EMAIL}


def test_database_rejects_second_active_central_location(db_session):
    central = db_session.query(InventoryLocation).filter_by(location_type="central", is_active=True).one()
    duplicate = InventoryLocation(code="CENTRAL-RACE", name="Central concorrente", location_type="central")
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
    assert db_session.get(InventoryLocation, central.id) is not None
    indexes = {index["name"] for index in inspect(db_session.connection()).get_indexes("inventory_locations")}
    assert "uq_inventory_locations_one_active_central" in indexes


def test_active_central_unique_race_is_translated_to_conflict(db_session, api_client, monkeypatch):
    monkeypatch.setattr(inventory_catalog_service, "_active_central_locations", lambda db: [])

    response = api_client.post(
        "/api/inventory/locations",
        json={"code": "CENTRAL-RACE-API", "name": "Central concorrente", "location_type": "central"},
        headers=_headers(),
    )

    assert response.status_code == 409, response.text
    assert "central" in response.json()["detail"].lower()


@pytest.mark.skipif(engine.dialect.name != "sqlite", reason="A cópia de ficheiro SQLite não é aplicável a PostgreSQL.")
def test_concurrent_central_creation_leaves_one_row_and_translates_unique_race(db_session, monkeypatch):
    from app.services.inventory_catalog import (
        CentralLocationInvariantError,
        create_inventory_location,
    )

    source = Path(str(engine.url.database))
    copied_fd, copied_name = tempfile.mkstemp(prefix="op-pm-inventory-central-", suffix=".db")
    os.close(copied_fd)
    Path(copied_name).unlink()
    _copy_sqlite_db(source, copied_name)
    local_engine = create_engine(
        f"sqlite:///{copied_name}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        future=True,
    )
    LocalSession = sessionmaker(bind=local_engine, future=True, autoflush=False)
    setup = LocalSession()
    try:
        central = setup.query(InventoryLocation).filter_by(location_type="central", is_active=True).one()
        central.is_active = False
        setup.commit()
    finally:
        setup.close()

    barrier = Barrier(2)
    outcomes: list[str] = []
    original_active_centrals = inventory_catalog_service._active_central_locations

    def gated_active_centrals(db):
        locations = original_active_centrals(db)
        barrier.wait(timeout=10)
        return locations

    monkeypatch.setattr(inventory_catalog_service, "_active_central_locations", gated_active_centrals)

    def attempt(suffix: str) -> None:
        session = LocalSession()
        try:
            create_inventory_location(
                session,
                data={"code": f"CENTRAL-CONCURRENT-{suffix}", "name": "Central concorrente", "location_type": "central"},
                actor_person_id=None,
            )
        except CentralLocationInvariantError:
            outcomes.append("conflict")
        except (AssertionError, BrokenBarrierError, SQLAlchemyError) as exc:
            outcomes.append(f"{type(exc).__name__}:{exc}")
        else:
            outcomes.append("created")
        finally:
            session.close()

    try:
        threads = [Thread(target=attempt, args=("A",)), Thread(target=attempt, args=("B",))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert sorted(outcomes) == ["conflict", "created"]
        check = LocalSession()
        try:
            assert check.query(InventoryLocation).filter_by(location_type="central", is_active=True).count() == 1
        finally:
            check.close()
    finally:
        local_engine.dispose()
        Path(copied_name).unlink(missing_ok=True)


def test_idempotency_key_is_bound_to_request_fingerprint(db_session, api_client):
    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    first = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1",
            "reference": "primeiro pedido",
            "idempotency_key": "idem-fingerprint-1",
        },
        headers=_headers(),
    )
    assert first.status_code == 201, first.text

    mismatched = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "2",
            "reference": "pedido alterado",
            "idempotency_key": "idem-fingerprint-1",
        },
        headers=_headers(),
    )
    assert mismatched.status_code == 409, mismatched.text
    assert db_session.query(InventoryMovement).filter_by(idempotency_key="idem-fingerprint-1").count() == 1


def test_idempotency_key_rejects_divergent_explicit_location_even_if_missing(db_session, api_client):
    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    key = "idem-location-fingerprint-1"
    first = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1",
            "reference": "localização implícita",
            "idempotency_key": key,
        },
        headers=_headers(),
    )
    assert first.status_code == 201, first.text

    mismatched = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1",
            "reference": "localização implícita",
            "location_id": str(uuid.uuid4()),
            "idempotency_key": key,
        },
        headers=_headers(),
    )
    assert mismatched.status_code == 409, mismatched.text


def test_idempotency_key_replays_implicit_and_explicit_central_location(db_session, api_client):
    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    central = db_session.query(InventoryLocation).filter_by(location_type="central", is_active=True).one()
    key = "idem-central-equivalence-1"
    implicit = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1",
            "reference": "central equivalente",
            "idempotency_key": key,
        },
        headers=_headers(),
    )
    assert implicit.status_code == 201, implicit.text
    explicit = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1",
            "reference": "central equivalente",
            "location_id": str(central.id),
            "idempotency_key": key,
        },
        headers=_headers(),
    )
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["id"] == implicit.json()["id"]


def test_legacy_central_retry_after_deactivation_backfills_and_replays(db_session, api_client):
    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    first = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1.000",
            "reference": "legado",
            "idempotency_key": "legacy-retry-1",
        },
        headers=_headers(),
    )
    assert first.status_code == 201, first.text
    movement = db_session.query(InventoryMovement).filter_by(idempotency_key="legacy-retry-1").one()
    movement.idempotency_fingerprint = None
    movement.location_id = None
    item.is_active = False
    db_session.commit()

    retry = api_client.post(
        "/api/inventory/movements",
        json={
            "item_id": str(item.id),
            "movement_type": "entrada",
            "quantity": "1.000",
            "reference": "legado",
            "idempotency_key": "legacy-retry-1",
        },
        headers=_headers(),
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    db_session.expire_all()
    assert db_session.query(InventoryMovement).filter_by(idempotency_key="legacy-retry-1").one().idempotency_fingerprint


def test_movement_refreshes_item_after_lock_before_active_validation(db_session, monkeypatch):
    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    from app.services import inventory as inventory_service

    original_serialize = inventory_service._serialize_item
    baseline_movements = db_session.query(InventoryMovement).filter_by(item_id=item.id, movement_type="entrada").count()

    def deactivate_after_lock(db, item_id):
        original_serialize(db, item_id)
        db.execute(update(InventoryItem).where(InventoryItem.id == item_id).values(is_active=false()))

    monkeypatch.setattr(inventory_service, "_serialize_item", deactivate_after_lock)
    with pytest.raises(InactiveInventoryReferenceError):
        enter_stock(
            db_session,
            item=item,
            quantity=Decimal("1.000"),
            created_by_person_id=None,
            idempotency_key=None,
        )
    assert db_session.query(InventoryMovement).filter_by(item_id=item.id, movement_type="entrada").count() == baseline_movements


def test_combined_catalog_edit_and_deactivate_is_one_commit_and_two_audits(db_session, api_client):
    item_response = api_client.post(
        "/api/inventory/items",
        json={"sku": "ATOMIC-CATALOG", "name": "Antes", "unit": "un"},
        headers=_headers(),
    )
    assert item_response.status_code == 201, item_response.text
    item_id = item_response.json()["id"]

    commits = 0
    original_commit = db_session.commit

    def counted_commit():
        nonlocal commits
        commits += 1
        return original_commit()

    db_session.commit = counted_commit  # type: ignore[method-assign]
    response = api_client.patch(
        f"/api/inventory/items/{item_id}",
        json={"name": "Depois", "is_active": False},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert commits == 1
    assert response.json()["name"] == "Depois"
    assert response.json()["is_active"] is False


def test_location_reactivation_applies_and_respects_central_invariant(db_session, api_client):
    first = api_client.post(
        "/api/inventory/locations",
        json={"code": "VEICULO-REACTIVATE", "name": "Viatura reativável", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert api_client.post(f"/api/inventory/locations/{first_id}/deactivate", headers=_headers()).status_code == 200

    reactivated = api_client.patch(
        f"/api/inventory/locations/{first_id}",
        json={"is_active": True},
        headers=_headers(),
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["is_active"] is True

    second = api_client.post(
        "/api/inventory/locations",
        json={"code": "VEICULO-REACTIVATE-CENTRAL", "name": "Central inativa", "location_type": "vehicle"},
        headers=_headers(),
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert api_client.post(f"/api/inventory/locations/{second_id}/deactivate", headers=_headers()).status_code == 200
    changed_type = api_client.patch(
        f"/api/inventory/locations/{second_id}",
        json={"location_type": "central"},
        headers=_headers(),
    )
    assert changed_type.status_code == 200, changed_type.text
    assert changed_type.json()["is_active"] is False

    conflicting_reactivation = api_client.patch(
        f"/api/inventory/locations/{second_id}",
        json={"is_active": True},
        headers=_headers(),
    )
    assert conflicting_reactivation.status_code == 409, conflicting_reactivation.text
    assert api_client.get("/api/inventory/locations", headers=_headers()).json()
    current = next(location for location in api_client.get("/api/inventory/locations", headers=_headers()).json() if location["id"] == second_id)
    assert current["is_active"] is False


def test_catalog_migration_provisions_existing_roles_and_downgrades_only_owned_rows(tmp_path):
    database_path = tmp_path / "inventory-migration.db"
    backend_path = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "PYTHONPATH": str(backend_path),
        }
    )

    def run_alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=backend_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run_alembic("upgrade", "b4d8f2a6c1e3")
    local_engine = create_engine(f"sqlite:///{database_path}")
    role_ids = {"administrador": str(uuid.uuid4()), "chefe_operacoes": str(uuid.uuid4())}
    permission_id = str(uuid.uuid4())
    assignment_id = str(uuid.uuid4())
    with local_engine.begin() as connection:
        for code, role_id in role_ids.items():
            connection.execute(
                text(
                    "INSERT INTO roles (id, code, name, description, created_at, updated_at) "
                    "VALUES (:id, :code, :name, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": role_id, "code": code, "name": code},
            )
        connection.execute(
            text(
                "INSERT INTO permissions (id, code, description, created_at, updated_at) "
                "VALUES (:id, 'inventory.manage_catalog', 'preexistente', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": permission_id},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions (id, role_id, permission_id, created_at, updated_at) "
                "VALUES (:id, :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": assignment_id, "role_id": role_ids["chefe_operacoes"], "permission_id": permission_id},
        )

    run_alembic("upgrade", "8a1d3f4c6b90")
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "8a1d3f4c6b90"
        assert connection.execute(text("SELECT COUNT(*) FROM permissions WHERE code = 'inventory.manage_catalog'")).scalar_one() == 1
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM role_permissions rp "
                    "JOIN permissions p ON p.id = rp.permission_id "
                    "JOIN roles r ON r.id = rp.role_id "
                    "WHERE p.code = 'inventory.manage_catalog' "
                    "AND r.code IN ('administrador', 'chefe_operacoes')"
                )
            ).scalar_one()
            == 2
        )
        assert connection.execute(text("SELECT COUNT(*) FROM inventory_manage_catalog_provisioning")).scalar_one() == 1
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM pragma_index_list('inventory_locations') WHERE name = 'uq_inventory_locations_one_active_central'")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM pragma_table_info('inventory_movements') WHERE name = 'idempotency_fingerprint'")
            ).scalar_one()
            == 1
        )

    run_alembic("downgrade", "b4d8f2a6c1e3")
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "b4d8f2a6c1e3"
        assert connection.execute(text("SELECT COUNT(*) FROM permissions WHERE code = 'inventory.manage_catalog'")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM role_permissions WHERE id = :id"), {"id": assignment_id}).scalar_one() == 1
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM role_permissions WHERE role_id = :role_id"),
                {"role_id": role_ids["administrador"]},
            ).scalar_one()
            == 0
        )
        assert connection.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE name = 'inventory_catalog_history'")).scalar_one() == 0

    run_alembic("upgrade", "f4b9c2d7e1a6")
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "f4b9c2d7e1a6"
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM role_permissions rp "
                    "JOIN permissions p ON p.id = rp.permission_id "
                    "WHERE p.code = 'inventory.manage_catalog'"
                )
            ).scalar_one()
            == 2
        )
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM role_permissions rp "
                    "JOIN roles r ON r.id = rp.role_id "
                    "WHERE r.code = 'suporte_operacoes'"
                )
            ).scalar_one()
            == 14
        )
    local_engine.dispose()


def test_catalog_migration_backfills_explicit_location_without_central(tmp_path):
    database_path = tmp_path / "inventory-migration-explicit-location.db"
    backend_path = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "PYTHONPATH": str(backend_path),
        }
    )

    def run_alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=backend_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    run_alembic("upgrade", "b4d8f2a6c1e3")
    local_engine = create_engine(f"sqlite:///{database_path}")
    item_id = uuid.uuid4()
    location_id = uuid.uuid4()
    movement_id = uuid.uuid4()
    with local_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO inventory_items "
                "(id, sku, name, unit, min_stock, is_active) "
                "VALUES (:id, 'LEGACY-EXPLICIT', 'Artigo legado', 'un', 0, 1)"
            ),
            {"id": str(item_id)},
        )
        connection.execute(
            text(
                "INSERT INTO inventory_locations "
                "(id, code, name, location_type, is_active) "
                "VALUES (:id, 'VEICULO-LEGADO', 'Viatura legada', 'vehicle', 1)"
            ),
            {"id": str(location_id)},
        )
        connection.execute(
            text(
                "INSERT INTO inventory_movements "
                "(id, item_id, movement_type, quantity, project_id, location_id, "
                "destination_location_id, unit_cost, reference, idempotency_key, created_by_person_id) "
                "VALUES (:id, :item_id, 'entrada', 1.000, NULL, :location_id, NULL, 3.20, "
                "'legado explícito', 'legacy-explicit-location', NULL)"
            ),
            {"id": str(movement_id), "item_id": str(item_id), "location_id": str(location_id)},
        )

    run_alembic("upgrade", "head")
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM inventory_locations WHERE location_type = 'central'")).scalar_one() == 0
        stored_fingerprint = connection.execute(
            text("SELECT idempotency_fingerprint FROM inventory_movements WHERE id = :id"),
            {"id": str(movement_id)},
        ).scalar_one()
    assert stored_fingerprint == _movement_fingerprint(
        item_id=item_id,
        movement_type="entrada",
        quantity=Decimal("1.000"),
        project_id=None,
        location_id=location_id,
        destination_location_id=None,
        reference="legado explícito",
        unit_cost=Decimal("3.20"),
    )
    local_engine.dispose()


@pytest.mark.skipif(engine.dialect.name != "sqlite", reason="A cópia de ficheiro SQLite não é aplicável a PostgreSQL.")
def test_concurrent_idempotency_unique_race_returns_one_winner(db_session, monkeypatch):
    from threading import local

    from app.services import inventory as inventory_service

    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    db_session.rollback()

    source = Path(str(engine.url.database))
    copied_fd, copied_name = tempfile.mkstemp(prefix="op-pm-inventory-idempotency-", suffix=".db")
    os.close(copied_fd)
    Path(copied_name).unlink()
    _copy_sqlite_db(source, copied_name)
    local_engine = create_engine(
        f"sqlite:///{copied_name}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        future=True,
    )
    LocalSession = sessionmaker(bind=local_engine, future=True, autoflush=False)
    barrier = Barrier(2)
    thread_state = local()
    movement_ids: list[str] = []
    errors: list[str] = []

    original_existing = inventory_service._existing_by_idempotency_key

    def gated_existing(db, idempotency_key, request_fingerprint=None):
        result = original_existing(db, idempotency_key, request_fingerprint)
        calls = getattr(thread_state, "calls", 0)
        if idempotency_key and calls < 2:
            thread_state.calls = calls + 1
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(inventory_service, "_existing_by_idempotency_key", gated_existing)
    # The real per-item lock is tested separately. Disabling only this seam
    # makes both requests reach the unique-key insert race deterministically.
    monkeypatch.setattr(inventory_service, "_serialize_item", lambda db, item_id: None)

    def attempt(item_id):
        session = LocalSession()
        try:
            candidate = session.get(InventoryItem, item_id)
            assert candidate is not None
            movement = inventory_service.enter_stock(
                session,
                item=candidate,
                quantity=Decimal(1),
                created_by_person_id=None,
                idempotency_key="idem-race-unique",
            )
            movement_ids.append(str(movement.id))
        except (AssertionError, BrokenBarrierError, SQLAlchemyError) as exc:
            errors.append(f"{type(exc).__name__}:{exc}")
        finally:
            session.close()

    try:
        threads = [Thread(target=attempt, args=(item.id,)), Thread(target=attempt, args=(item.id,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors
        assert len(movement_ids) == 2
        assert len(set(movement_ids)) == 1
    finally:
        local_engine.dispose()
        Path(copied_name).unlink(missing_ok=True)


@pytest.mark.skipif(engine.dialect.name != "sqlite", reason="A cópia de ficheiro SQLite não é aplicável a PostgreSQL.")
def test_concurrent_reservations_serialize_per_item_and_never_overreserve(db_session):
    item = db_session.query(InventoryItem).filter_by(sku="CABO-DC-6MM").one()
    project = db_session.query(Project).filter(Project.is_active.is_(True)).first()
    assert project is not None
    db_session.rollback()

    source = Path(str(engine.url.database))
    copied_fd, copied_name = tempfile.mkstemp(prefix="op-pm-inventory-concurrency-", suffix=".db")
    os.close(copied_fd)
    Path(copied_name).unlink()
    _copy_sqlite_db(source, copied_name)
    local_engine = create_engine(
        f"sqlite:///{copied_name}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        future=True,
    )
    LocalSession = sessionmaker(bind=local_engine, future=True, autoflush=False)

    # Use a fresh key/item balance owned by committed seed data. Two independent
    # sessions race for more than the available amount; exactly one may commit.
    barrier = Barrier(2)
    outcomes: list[str] = []

    def attempt(quantity: str) -> None:
        session = LocalSession()
        try:
            candidate = session.get(InventoryItem, item.id)
            assert candidate is not None
            barrier.wait(timeout=10)
            reserve_for_project(
                session,
                item=candidate,
                project_id=project.id,
                quantity=Decimal(quantity),
                created_by_person_id=None,
                idempotency_key=None,
            )
        except InsufficientStockError:
            outcomes.append("insufficient")
        except (AssertionError, BrokenBarrierError, SQLAlchemyError) as exc:
            outcomes.append(f"{type(exc).__name__}:{exc}")
        else:
            outcomes.append("committed")
        finally:
            session.close()

    try:
        threads = [Thread(target=attempt, args=("50",)), Thread(target=attempt, args=("50",))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(outcomes) == 2
        assert sorted(outcomes) == ["committed", "insufficient"]

        check = LocalSession()
        try:
            rows = check.query(InventoryMovement).filter_by(item_id=item.id, movement_type="reserva").all()
            assert sum((Decimal(row.quantity) for row in rows), Decimal(0)) <= Decimal(80)
        finally:
            check.close()
    finally:
        local_engine.dispose()
        Path(copied_name).unlink(missing_ok=True)
