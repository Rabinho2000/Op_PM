"""`app/utils/text.py`: fonte única da normalização de texto.

Cada função tem testes de exemplos e uma comparação com a implementação
original (copiada abaixo) do chamador que substituiu, para provar que a
unificação não mudou nenhum resultado — incluindo os casos em que as
variantes divergem de propósito (espaços interiores, ordem das operações,
NFC vs. NFKD)."""
from __future__ import annotations

import unicodedata

import pytest

from app.utils.text import (
    alnum_casefold_key,
    clean_display,
    lower_strip_accents,
    nfc_lower_strip,
    normalize_key,
    normalize_search_text,
    strip_accents,
)

SAMPLES = [
    "",
    "   ",
    "Instalador A",
    "  Instalador   A ",
    "Ação  de Fixação",
    "Estruturas  de Fixação",
    "CERTIFICADO FINAL",
    "Em construção",
    "ﬁxação ﬂexível",
    "Straße",
    "İstanbul",
    "école",  # e + acento combinante
    "école",  # é pré-composto
    "a¨b",  # trema isolado: o NFKD gera um espaço
    "¨a",
    "x y",  # espaço duro
    "\t tab\nnova linha ",
    "Ⅻ ① ㎏",
    "ΐ ͅ",
    "Nº 12/2024 - Câmara (Lisboa)",
]


# --- implementações originais (referência) ------------------------------


def _legacy_normalize_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", " ".join(text.split()).lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _legacy_lifecycle_normalize(raw: str) -> str:
    decomposed = unicodedata.normalize("NFKD", raw.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _legacy_strip_accents_lower(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _legacy_category_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in decomposed if char.isalnum())


def _legacy_normalise_status(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().lower()


@pytest.mark.parametrize("sample", SAMPLES)
def test_functions_match_the_original_implementations(sample):
    assert normalize_key(sample) == _legacy_normalize_key(sample)
    assert lower_strip_accents(sample) == _legacy_lifecycle_normalize(sample)
    assert normalize_search_text(sample) == _legacy_strip_accents_lower(sample)
    assert alnum_casefold_key(sample) == _legacy_category_key(sample)
    assert nfc_lower_strip(sample) == _legacy_normalise_status(sample)


# --- exemplos ------------------------------------------------------------


def test_strip_accents_removes_combining_marks_only():
    assert strip_accents("Ação Fixação ü") == "Acao Fixacao u"
    assert strip_accents("é") == "e"
    assert strip_accents("ABC 123") == "ABC 123"


def test_normalize_key_collapses_spaces_lowercases_and_strips_accents():
    assert normalize_key("  Instalador   A ") == "instalador a"
    assert normalize_key("Estruturas  de Fixação") == "estruturas de fixacao"
    assert normalize_key("INVERSORES") == normalize_key("inversores")


def test_clean_display_only_collapses_spaces():
    assert clean_display("  Ação   de  Fixação ") == "Ação de Fixação"


def test_lower_strip_accents_keeps_inner_spaces():
    # Divergência deliberada face a normalize_key: o estado legado não colapsa.
    assert lower_strip_accents("  Em  Construção ") == "em  construcao"
    assert normalize_key("  Em  Construção ") == "em construcao"


def test_normalize_search_text_accepts_any_value():
    assert normalize_search_text(None) == ""
    assert normalize_search_text(0) == ""
    assert normalize_search_text(12) == "12"
    assert normalize_search_text("  Câmara   Municipal ") == "camara municipal"


def test_variants_diverge_only_in_the_documented_edge_case():
    # NFKD primeiro (search) vs. colapsar primeiro (key): o espaço gerado pelo
    # NFKD de um trema isolado fica à frente em normalize_key.
    assert normalize_key("¨a") == " a"
    assert normalize_search_text("¨a") == "a"


def test_alnum_casefold_key_keeps_only_letters_and_digits():
    assert alnum_casefold_key("Estruturas / Fixação") == "estruturasfixacao"
    assert alnum_casefold_key("Straße") == "strasse"


def test_nfc_lower_strip_keeps_accents():
    assert nfc_lower_strip("  Em Construção ") == "em construção"
    assert nfc_lower_strip("é") == "é"
