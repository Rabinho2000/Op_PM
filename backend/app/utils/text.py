"""Normalização de texto partilhada — fonte única (nomes de fornecedores,
tipos de material, instaladores, estados, rótulos de importação…).

Cada chamador tinha a sua variante, com diferenças subtis (ordem de
minúsculas/decomposição, `strip` vs. colapso de espaços, `lower` vs.
`casefold`, NFC vs. NFKD). Para não mudar resultados já gravados (chaves
`name_key`, estados legados), cada variante mantém a sua função nomeada,
com o comportamento exato original:

- `normalize_key`: espaços colapsados, minúsculas, sem acentos (NFKD).
- `lower_strip_accents`: `strip`, minúsculas, sem acentos; NÃO colapsa os
  espaços interiores (estados legados do ClickUp).
- `normalize_search_text`: aceita qualquer valor; sem acentos primeiro,
  depois minúsculas e espaços colapsados (correspondência de nomes nos
  importadores).
- `alnum_casefold_key`: `casefold` e só letras/dígitos (categorias).
- `nfc_lower_strip`: NFC, `strip`, minúsculas; mantém os acentos.
- `strip_accents`: primitiva partilhada (NFKD e remoção das marcas).
"""
from __future__ import annotations

import unicodedata


def strip_accents(text: str) -> str:
    """Decompõe em NFKD e remove as marcas de combinação (acentos)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_key(text: str) -> str:
    return strip_accents(" ".join(text.split()).lower())


def clean_display(text: str) -> str:
    return " ".join(text.split())


def lower_strip_accents(text: str) -> str:
    """`strip` + minúsculas + sem acentos. Não colapsa espaços interiores."""
    return strip_accents(text.strip().lower())


def normalize_search_text(value: object) -> str:
    """Sem acentos, minúsculas e espaços colapsados; `None`/vazio dá ''.
    A ordem (acentos antes das minúsculas) é a original dos importadores."""
    return " ".join(strip_accents(str(value or "")).lower().split())


def alnum_casefold_key(text: str) -> str:
    """NFKD, `casefold` e só caracteres alfanuméricos (chave de categoria)."""
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    return "".join(char for char in decomposed if char.isalnum())


def nfc_lower_strip(text: str) -> str:
    """NFC + `strip` + minúsculas, mantendo os acentos."""
    return unicodedata.normalize("NFC", text).strip().lower()
