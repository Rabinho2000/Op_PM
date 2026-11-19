"""Normalização de endereços de email usados como identificador de login."""
from __future__ import annotations


def normalize_email(value: str) -> str:
    """Forma canónica guardada em `User.email`: sem espaços nas pontas e em
    minúsculas. A autenticação compara com `lower(email)`, por isso `A@x` e
    `a@x` têm de ser o mesmo utilizador (ver o índice único `uq_users_email_lower`)."""
    return value.strip().lower()
