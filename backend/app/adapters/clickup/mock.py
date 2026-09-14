from __future__ import annotations

import json
from pathlib import Path

from app.adapters.clickup.base import ClickUpTask

_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic_clickup_tasks.json"


class MockClickUpAdapter:
    """Lê tarefas sintéticas de um ficheiro fixture — nunca chama a API real
    do ClickUp. Serve para testar o fluxo de mapeamento por ID estável e a
    deteção de conflitos sem qualquer credencial ou dado real."""

    def __init__(self, fixture_path: Path | None = None):
        self.fixture_path = fixture_path or _FIXTURE_PATH

    def fetch_tasks(self) -> list[ClickUpTask]:
        raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        return [
            ClickUpTask(
                task_id=item["task_id"],
                name=item["name"],
                status=item["status"],
                custom_fields=item.get("custom_fields", {}),
            )
            for item in raw
        ]
