"""Normalização de texto partilhada (nomes de fornecedores, tipos de material,
instaladores…): minúsculas, sem acentos e com espaços colapsados, para que
"  Verde  Milenar " e "verde milenar" sejam o mesmo nome."""
from __future__ import annotations

import unicodedata


def normalize_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", " ".join(text.split()).lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def clean_display(text: str) -> str:
    return " ".join(text.split())
