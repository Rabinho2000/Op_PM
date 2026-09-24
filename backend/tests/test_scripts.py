"""Scripts de apoio em `scripts/` (não fazem parte da aplicação): tradução dos
responsáveis do legado para chaves neutras e a verificação de nomes de pessoas."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.services.process_catalog import RESPONSIBLE_RULES

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract = _load("extract_process_from_legacy")
check = _load("check_no_personal_names")


def _data(*labels: str) -> dict:
    return {"stages": [{"code": f"etapa-{i:02d}", "responsible": label} for i, label in enumerate(labels, start=1)]}


# --- tradução dos responsáveis -----------------------------------------------------


def test_function_labels_translate_without_any_mapping_file():
    data = extract.translate_responsibles(_data("Comercial", "Sales Support", "PM", "VM", "CE"))
    assert [s["responsible"] for s in data["stages"]] == ["comercial", "sales_support", "pm", "instalador", "chefe_equipa"]


def test_person_labels_need_the_local_mapping_and_are_all_reported_at_once():
    with pytest.raises(ValueError) as exc:
        extract.translate_responsibles(_data("PM", "Etiqueta A", "Etiqueta B", "Etiqueta A"))
    message = str(exc.value)
    assert "Etiqueta A" in message and "Etiqueta B" in message and "--responsible-map" in message

    data = extract.translate_responsibles(
        _data("Etiqueta A", "Etiqueta B", "PM"), {"Etiqueta A": "chefe_departamento", "Etiqueta B": "suporte"}
    )
    assert [s["responsible"] for s in data["stages"]] == ["chefe_departamento", "suporte", "pm"]


def test_a_mapping_to_an_unknown_neutral_key_is_rejected():
    with pytest.raises(ValueError, match="chaves neutras inexistentes"):
        extract.translate_responsibles(_data("Etiqueta A"), {"Etiqueta A": "chave_inventada"})


def test_every_neutral_key_the_extractor_produces_is_known_to_the_loader():
    assert extract.NEUTRAL_KEYS == set(RESPONSIBLE_RULES)
    assert set(extract.FUNCTION_LABELS.values()) <= set(RESPONSIBLE_RULES)


def test_loader_keys_are_neutral_identifiers_never_person_names():
    """Chaves em minúsculas e sem espaços (`suporte`, `chefe_departamento`…): um nome de
    pessoa, com maiúscula ou espaços, não é uma chave válida."""
    assert all(key == key.lower() and " " not in key for key in RESPONSIBLE_RULES)


# --- verificação de nomes ---------------------------------------------------------------


def test_find_names_ignores_case_and_accents_and_matches_whole_words_only():
    files = {
        "a.md": "Falou o Fulano Exemplo ontem.\nNada aqui.\nFULANO",
        "b.py": "exemplos = 1  # palavra diferente\nBeltrano Fictício e beltrano",
        "c.txt": "sem nomes",
    }
    hits = check.find_names(files, ["Fulano Exemplo", "fulano", "Exemplo", "beltrano", "Fictício"])
    assert ("a.md", 1, "Fulano Exemplo") in hits and ("a.md", 1, "fulano") in hits and ("a.md", 1, "Exemplo") in hits
    assert ("a.md", 3, "fulano") in hits
    assert not [h for h in hits if h[0] == "b.py" and h[1] == 1]  # "exemplos" não é "Exemplo"
    assert ("b.py", 2, "beltrano") in hits and ("b.py", 2, "Fictício") in hits
    assert not [h for h in hits if h[0] == "c.txt"]


def test_check_never_prints_the_line_content_and_reports_exit_codes(tmp_path, capsys, monkeypatch):
    names = tmp_path / "nomes.json"
    names.write_text(json.dumps(["Nome Fictício"]), encoding="utf-8")
    monkeypatch.setattr(check, "tracked_files", lambda: {"x.md": "linha com Nome Fictício e mais texto", "y.md": "limpo"})
    assert check.main(["--names-file", str(names)]) == 1
    out = capsys.readouterr().out
    assert "x.md:1: Nome Fictício" in out and "mais texto" not in out
    monkeypatch.setattr(check, "tracked_files", lambda: {"y.md": "limpo"})
    assert check.main(["--names-file", str(names)]) == 0
    assert check.main(["--names-file", str(tmp_path / "nao-existe.json")]) == 2
    names.write_text(json.dumps({"não": "é lista"}), encoding="utf-8")
    assert check.main(["--names-file", str(names)]) == 2
