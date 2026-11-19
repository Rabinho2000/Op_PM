"""Gera, a partir de `app/security/catalog.py`, os dois ficheiros que mantêm o
vocabulário de permissões alinhado entre o backend e o frontend (M6):

- `app/security/perm.py` — `Perm(StrEnum)`, usado em `AuthContext.require/has_permission`
  e em `require_permission(...)`;
- `frontend/src/generated/permissions.ts` — o tipo `Perm` e a lista `PERMISSION_CODES`.

O catálogo é a fonte de verdade: não editar os ficheiros gerados à mão.

Utilização (a partir de `backend/`):
    python -m app.cli.generate_permissions          # reescreve os ficheiros
    python -m app.cli.generate_permissions --check  # falha se estiverem desatualizados
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.security.catalog import PERMISSIONS

_BACKEND_DIR = Path(__file__).resolve().parents[2]
PERM_PY_PATH = _BACKEND_DIR / "app" / "security" / "perm.py"
PERM_TS_PATH = _BACKEND_DIR.parent / "frontend" / "src" / "generated" / "permissions.ts"

_REGENERATE = "python -m app.cli.generate_permissions"


def member_name(code: str) -> str:
    """`project.safety_sheet.edit` -> `PROJECT_SAFETY_SHEET_EDIT`."""
    return code.replace(".", "_").upper()


def render_python(codes: list[str] | None = None) -> str:
    codes = sorted(PERMISSIONS) if codes is None else codes
    names = [member_name(code) for code in codes]
    if len(set(names)) != len(names):
        raise ValueError("Dois códigos de permissão dão o mesmo nome de membro de Perm.")
    lines = [
        '"""GERADO por `app/cli/generate_permissions.py` a partir de `app/security/catalog.py`.',
        "",
        "Não editar à mão: alterar o catálogo e voltar a correr",
        f"`{_REGENERATE}` (o teste `test_permission_catalog` falha se este ficheiro",
        "estiver desatualizado).",
        "",
        "`Perm` é um `StrEnum`: cada membro compara igual (e tem o mesmo hash) à string",
        "do código, por isso `ctx.has_permission(Perm.PROJECT_VIEW_ALL)` e",
        '`"project.view_all" in ctx.permission_codes` continuam equivalentes.',
        '"""',
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "",
        "",
        "class Perm(StrEnum):",
    ]
    lines += [f'    {name} = "{code}"' for name, code in zip(names, codes)]
    return "\n".join(lines) + "\n"


def render_typescript(codes: list[str] | None = None) -> str:
    codes = sorted(PERMISSIONS) if codes is None else codes
    lines = [
        "// GERADO por backend/app/cli/generate_permissions.py a partir de",
        "// backend/app/security/catalog.py — não editar à mão.",
        f"// Para atualizar: (cd backend && {_REGENERATE})",
        "",
        "export const PERMISSION_CODES = [",
    ]
    lines += [f'  "{code}",' for code in codes]
    lines += [
        "] as const;",
        "",
        "export type Perm = (typeof PERMISSION_CODES)[number];",
        "",
    ]
    return "\n".join(lines)


def outputs() -> dict[Path, str]:
    return {PERM_PY_PATH: render_python(), PERM_TS_PATH: render_typescript()}


def _source_root(path: Path) -> Path:
    return _BACKEND_DIR.parent / "frontend" / "src" if path == PERM_TS_PATH else path.parent


def stale_files() -> list[Path]:
    """Ficheiros gerados que não coincidem com o catálogo (ou não existem)."""
    stale: list[Path] = []
    for path, expected in outputs().items():
        if not _source_root(path).exists():
            continue  # p.ex. imagem do backend sem o diretório do frontend
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            stale.append(path)
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera Perm (Python) e Perm (TypeScript) a partir do catálogo.")
    parser.add_argument("--check", action="store_true", help="falha se os ficheiros gerados estiverem desatualizados")
    args = parser.parse_args(argv)
    if args.check:
        stale = stale_files()
        for path in stale:
            print(f"Desatualizado: {path.relative_to(_BACKEND_DIR.parent)}", file=sys.stderr)
        if stale:
            print(f"Correr: (cd backend && {_REGENERATE})", file=sys.stderr)
            return 1
        return 0
    for path, content in outputs().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Escrito {path.relative_to(_BACKEND_DIR.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
