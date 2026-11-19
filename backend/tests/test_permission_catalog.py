"""M6 — `Perm`, o catálogo e os literais de permissões (backend e frontend)
nunca podem divergir: uma permissão mal escrita nega o acesso em silêncio.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.cli.generate_permissions import (
    PERM_PY_PATH,
    PERM_TS_PATH,
    member_name,
    render_python,
    render_typescript,
    stale_files,
)
from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES
from app.security.perm import Perm

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
FRONTEND_SRC = BACKEND_DIR.parent / "frontend" / "src"

# Funções cujo argumento é um código de permissão: nunca aceitam um literal.
_PERMISSION_CALLS = {"require", "has_permission", "require_permission", "PermissionDenied"}
# Os únicos ficheiros onde os códigos aparecem como texto.
_CODE_SOURCES = {APP_DIR / "security" / "catalog.py", APP_DIR / "security" / "perm.py"}


def test_perm_has_exactly_the_catalog_permissions() -> None:
    assert {member.value for member in Perm} == set(PERMISSIONS)
    assert {member.name for member in Perm} == {member_name(code) for code in PERMISSIONS}


def test_perm_compares_equal_to_the_plain_string() -> None:
    assert Perm.PROJECT_VIEW_ALL == "project.view_all"
    assert Perm.PROJECT_VIEW_ALL in {"project.view_all"}
    assert "project.view_all" in frozenset({Perm.PROJECT_VIEW_ALL})
    assert f"{Perm.PROJECT_VIEW_ALL}" == "project.view_all"


def test_role_matrix_only_uses_catalog_permissions_and_roles() -> None:
    assert set(ROLE_PERMISSIONS) <= set(ROLES)
    for role, codes in ROLE_PERMISSIONS.items():
        assert set(codes) <= set(PERMISSIONS), role


def test_generated_files_are_up_to_date() -> None:
    """`perm.py` e `frontend/src/generated/permissions.ts` vêm do catálogo
    (`python -m app.cli.generate_permissions`)."""
    stale = stale_files()
    assert not stale, f"Desatualizados: {[str(p) for p in stale]} — correr `python -m app.cli.generate_permissions`"
    assert PERM_PY_PATH.read_text(encoding="utf-8") == render_python()
    if FRONTEND_SRC.exists():
        assert PERM_TS_PATH.read_text(encoding="utf-8") == render_typescript()


def _python_sources() -> list[Path]:
    return sorted(p for p in APP_DIR.rglob("*.py") if p not in _CODE_SOURCES)


def test_backend_has_no_permission_string_literals() -> None:
    """Todo o código de permissão no backend é `Perm.X`: nenhum literal igual a
    um código do catálogo e nenhum literal passado a `require/has_permission/...`
    (que apanharia também um código inventado ou em falta no catálogo)."""
    offenders: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            where = f"{path.relative_to(BACKEND_DIR)}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in _PERMISSION_CALLS:
                    # Os argumentos posicionais (e `permission_code=`) são códigos; `detail=` é texto.
                    args = [*node.args, *(kw.value for kw in node.keywords if kw.arg in {"permission_code", "code"})]
                    if any(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args):
                        offenders.append(f"{where}: literal em {name}(...)")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in PERMISSIONS
                and not isinstance(parents.get(node), (ast.Expr, ast.JoinedStr))  # docstrings/f-strings
            ):
                offenders.append(f"{where}: literal {node.value!r} (usar Perm.{member_name(node.value)})")
    assert not offenders, "\n".join(offenders)


# --- frontend ---------------------------------------------------------------

_LITERAL = re.compile(r"""["'`]([a-z][a-z_]*(?:\.[a-z_]+)+)["'`]""")
_PERMISSION_FIELD = re.compile(r"\bpermissions?\s*:\s*(\[[^\]]*\]|[\"'][^\"']*[\"'])")
# Texto que se parece com um código mas não é uma permissão.
_NOT_PERMISSIONS = {
    "import.meta.env",  # Vite
    "project.editable_fields",  # propriedade do projeto citada em comentários
}
_NOT_PERMISSION_PREFIXES = ("payment.",)  # etiquetas de marcos de pagamento (utils/labels.ts)


def _frontend_sources() -> list[Path]:
    generated = FRONTEND_SRC / "generated"
    return sorted(
        p for p in FRONTEND_SRC.rglob("*.ts*") if generated not in p.parents and p.suffix in {".ts", ".tsx"}
    )


@pytest.mark.skipif(not FRONTEND_SRC.exists(), reason="frontend/ não existe neste checkout")
def test_frontend_has_no_permission_literal_outside_the_catalog() -> None:
    """Nenhum literal de permissão em `frontend/src/**` fica fora do catálogo
    (o `tsc` apanha o resto: `can()` e as listas de navegação aceitam só `Perm`)."""
    prefixes = {code.split(".")[0] for code in PERMISSIONS}
    offenders: list[str] = []
    for path in _frontend_sources():
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for match in _LITERAL.finditer(line):
                value = match.group(1)
                if value in PERMISSIONS or value in _NOT_PERMISSIONS or value.startswith(_NOT_PERMISSION_PREFIXES):
                    continue
                if value.split(".")[0] in prefixes:
                    offenders.append(f"{path.relative_to(FRONTEND_SRC)}:{number}: {value}")
        for match in _PERMISSION_FIELD.finditer(text):
            for value in re.findall(r"""["']([^"']+)["']""", match.group(1)):
                if value not in PERMISSIONS:
                    line_no = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.relative_to(FRONTEND_SRC)}:{line_no}: {value}")
    assert not offenders, "Permissões fora do catálogo:\n" + "\n".join(sorted(set(offenders)))
