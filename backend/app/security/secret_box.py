"""Cifra simétrica das passwords de portais (Fernet, `cryptography`).

A chave é lida de um ficheiro indicado por `OPPM_SECRETS_KEY_FILE` (uma linha,
gerada com `Fernet.generate_key()`). Nunca é um valor inline nem fica no repo.
Sem chave configurada ou inválida, `SecretBoxUnavailable` é levantada e a rota
responde 503 — falha fechada: nunca se grava nem se devolve uma password em
claro por falta de chave.

Nenhuma mensagem de erro inclui o valor cifrado nem o claro.
"""
from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class SecretBoxUnavailable(RuntimeError):
    """Cifra indisponível (sem chave, ficheiro ilegível ou chave inválida)."""


class SecretBoxDecryptError(RuntimeError):
    """Token cifrado não pode ser decifrado com a chave atual."""


def _load_fernet(settings: Settings) -> Fernet:
    key_file = (settings.oppm_secrets_key_file or "").strip()
    if not key_file:
        raise SecretBoxUnavailable(
            "Cifra de credenciais não configurada: defina OPPM_SECRETS_KEY_FILE."
        )
    try:
        raw = Path(key_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SecretBoxUnavailable("Ficheiro de chave de credenciais ilegível.") from exc
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretBoxUnavailable("Chave de credenciais inválida.") from exc


def encrypt_secret(settings: Settings, plaintext: str) -> str:
    return _load_fernet(settings).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(settings: Settings, token: str) -> str:
    try:
        return _load_fernet(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretBoxDecryptError("Não foi possível decifrar a credencial.") from exc
