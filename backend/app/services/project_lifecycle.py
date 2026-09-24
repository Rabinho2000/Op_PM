"""Estado do ciclo de vida de um projeto (D-069): On hold pelo cliente,
Preparação, Construção, Construído, Entregue ao cliente, Certificado final.

Distinto de `Project.status` (derivado das tarefas: nao_iniciado/em_curso/
concluido — ver `app/services/projects.py`). O Op_PM é a fonte de verdade deste
estado; `clickup_status_mirror` continua a ser só um espelho e só serve para
inicializar o valor na importação.

Lista única: a UI lê-a de `GET /api/projects/lifecycle-statuses`, nunca a
duplica.
"""
from __future__ import annotations

import unicodedata

# (código estável, rótulo). A ordem é a de apresentação.
LIFECYCLE_STATUSES: tuple[tuple[str, str], ...] = (
    ("on_hold_cliente", "On hold pelo cliente"),
    ("preparacao", "Preparação"),
    ("construcao", "Construção"),
    ("construido", "Construído"),
    ("entregue_cliente", "Entregue ao cliente"),
    ("certificado_final", "Certificado final"),
)
LIFECYCLE_STATUS_CODES = frozenset(code for code, _ in LIFECYCLE_STATUSES)
LIFECYCLE_STATUS_LABELS = dict(LIFECYCLE_STATUSES)

# Sequência normal de uma obra. `on_hold_cliente` fica fora: pode entrar-se e
# sair dele em qualquer ponto (D6 — transições livres).
LIFECYCLE_FLOW: tuple[str, ...] = (
    "preparacao",
    "construcao",
    "construido",
    "entregue_cliente",
    "certificado_final",
)

ON_HOLD = "on_hold_cliente"

# Valores do `clickupStatus` do export legado (já sem acentos/maiúsculas).
_LEGACY_MAP: dict[str, str] = {
    "on hold pelo cliente": "on_hold_cliente",
    "em preparacao": "preparacao",
    "preparacao": "preparacao",
    "em construcao": "construcao",
    "construcao": "construcao",
    "construido": "construido",
    "entregue ao cliente": "entregue_cliente",
    "certificado final": "certificado_final",
    # D2: o legado tem 1 projeto "vendido"; ainda não começou, fica em espera.
    "vendido": "on_hold_cliente",
}


def _normalize(raw: str) -> str:
    decomposed = unicodedata.normalize("NFKD", raw.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def lifecycle_status_from_legacy(raw: str | None) -> str | None:
    """Estado inicial a partir do `clickupStatus` do export legado.

    - Valor conhecido → o código correspondente.
    - Vazio → `on_hold_cliente` (D2: o único projeto do legado sem estado foi
      posto em "On hold pelo cliente" por decisão explícita).
    - Qualquer outro valor → `None` (sem estado): nunca se adivinha, fica
      visível para decisão humana.
    """
    if raw is None or not raw.strip():
        return ON_HOLD
    return _LEGACY_MAP.get(_normalize(raw))


def status_change_warning(old: str | None, new: str) -> str | None:
    """Aviso (nunca bloqueio — D6) quando a mudança salta estados da sequência
    normal, por exemplo de Preparação diretamente para Entregue ao cliente."""
    if old not in LIFECYCLE_FLOW or new not in LIFECYCLE_FLOW:
        return None
    skipped = LIFECYCLE_FLOW.index(new) - LIFECYCLE_FLOW.index(old) - 1
    if skipped <= 0:
        return None
    plural = "estado" if skipped == 1 else "estados"
    return (
        f"Mudou de «{LIFECYCLE_STATUS_LABELS[old]}» para «{LIFECYCLE_STATUS_LABELS[new]}», "
        f"a saltar {skipped} {plural} da sequência normal."
    )
