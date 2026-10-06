"""Importação das notas iniciais (`notas-iniciais-vNN.html`/`.json`) —
formulário usado pelo Comercial e pelo Sales Support. Ver
docs/DATA_IMPORTS.md para o desenho completo.

Regras de segurança inegociáveis:
- Nunca `eval`/`exec`/motor de JavaScript — HTML é lido como texto e o
  bloco `<script type="application/json" id="notas-iniciais-data">` é
  extraído com um parser HTML normal, nunca interpretado como código.
- Versão lida do conteúdo (`formVersion`), nunca do nome do ficheiro.
- Nunca escreve direto em `Project`/dados satélite — sempre
  preview (persistido em staging, `pending_confirmation`) → resolução de
  conflitos → `apply` explícito.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import re
import unicodedata
import uuid
from html.parser import HTMLParser
from urllib.parse import unquote, unquote_to_bytes

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.imports import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_PENDING_CONFIRMATION,
    CONFLICT_RESOLUTION_KEEP_OLD,
    CONFLICT_RESOLUTION_PENDING,
    CONFLICT_RESOLUTION_USE_NEW,
    RECORD_STATUS_APPLIED,
    SOURCE_TYPE_NOTES_HTML,
    SOURCE_TYPE_NOTES_JSON,
    FieldImportBatch,
    FieldImportConflict,
    FieldImportRecord,
)
from app.models.project import Project
from app.models.project_data import ProjectInstallationData, ProjectLicensingData
from app.services.project_data import upsert_installation_data, upsert_licensing_data

# Versões do formulário aceites — "v11" no nome do ficheiro pode conter
# conteúdo já na versão 12 (o nome do ficheiro nunca é a fonte de
# verdade); qualquer versão fora desta lista é rejeitada explicitamente.
COMPATIBLE_FORM_VERSIONS: frozenset[str] = frozenset({"10", "11", "12"})

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_FILENAME_LENGTH = 512
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".html", ".htm", ".json"})

SCRIPT_TAG_ID = "notas-iniciais-data"


class NotesImportError(ValueError):
    """Erro de negócio conhecido — mensagem sempre segura para mostrar."""


def _validate_filename(filename: str) -> None:
    if len(filename) > MAX_FILENAME_LENGTH:
        raise NotesImportError(
            f"Nome do ficheiro demasiado longo (máximo {MAX_FILENAME_LENGTH} caracteres)."
        )
    if any(unicodedata.category(character).startswith("C") for character in filename):
        raise NotesImportError("Nome do ficheiro contém caracteres de controlo Unicode.")


class _SensitiveValueBudgetExceeded(NotesImportError):
    """A sensitive-value safety budget cannot represent this payload safely."""

    def __init__(self) -> None:
        # Keep this message deliberately generic: it must not reveal a value,
        # the kind of limit, or the configured safety budget.
        super().__init__("Não foi possível processar os dados importados com segurança.")


class ImportPendingStateError(NotesImportError):
    """The request changed staging state that the route must commit."""


class DuplicateImportError(NotesImportError):
    pass


def _ensure_clean_import_session(db: Session) -> None:
    """Refuse importer writes when the caller has unrelated pending state."""
    if db.new or db.dirty or db.deleted:
        raise NotesImportError(
            "A sessão tem alterações pendentes; confirme-as ou faça rollback antes de importar."
        )


class _NotesScriptExtractor(HTMLParser):
    """Extrai só o texto de dentro de
    `<script type="application/json" id="notas-iniciais-data">` — nunca
    interpreta HTML/JS como código, só percorre a árvore de tags."""

    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self.captured: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attr_map = dict(attrs)
        if attr_map.get("id") == SCRIPT_TAG_ID:
            self._capturing = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self.captured = (self.captured or "") + data


_NUMBER_RE = re.compile(r"[-+]?\d[\d.,]*")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+|00)?\s*\d[\d\s().-]{6,}\d")
_DATA_URL_MAX_HEADER_CHARS = 4096
_ASCII_CONTROL_OR_SPACE = frozenset(chr(index) for index in range(0, 33)) | {chr(127)}
_SENSITIVE_COMPOUND_SUFFIXES = frozenset(
    {"field", "value", "values", "name", "key", "input", "label", "attribute", "property", "content"}
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?ix)"
    r"(?<![a-z0-9])"
    r"(?P<label>password|passwd|passcode|passphrase|secret|token|credential|credentials|"
    r"api[\s_-]*key|api[\s_-]*secret|api[\s_-]*token|access[\s_-]*token|"
    r"authorization|bearer|client[\s_-]*secret|private[\s_-]*key|refresh[\s_-]*token|"
    r"recovery[\s_-]*code|security[\s_-]*(?:answer|code)|session|senha|pin|puk|otp|mfa|2fa)"
    r"(?![a-z0-9])"
    r"(?P<separator>[\s\x00-\x20]*[:=][\s\x00-\x20]*)"
    r"(?P<value>[^,;&\)\]\}\"']+)"
)

# temporary-no-op
# store when a future form adds an unknown field. Labels are normalized before
# comparison, so both ``portalLogin`` and ``portal-login`` are covered.
SENSITIVE_LABEL_DENYLIST: frozenset[str] = frozenset(
    {
        "api key",
        "api secret",
        "api token",
        "access key",
        "access token",
        "authorization",
        "auth",
        "auth token",
        "bearer",
        "bearer token",
        "card number",
        "chave",
        "client id",
        "client secret",
        "codigo pin",
        "codigo puk",
        "credential",
        "credentials",
        "cookie",
        "id token",
        "login",
        "nome de utilizador",
        "palavra passe",
        "passcode",
        "pass",
        "passphrase",
        "passwd",
        "password",
        "portal access",
        "pin",
        "private key",
        "puk",
        "pwd",
        "refresh token",
        "recovery code",
        "secret",
        "secret key",
        "security answer",
        "security code",
        "session",
        "senha",
        "token",
        "one time password",
        "otp",
        "mfa",
        "2fa",
        "user",
        "username",
        "user name",
        "utilizador",
    }
)
SENSITIVE_VALUE_PLACEHOLDER = "[valor sensível omitido]"
SENSITIVE_FIELD_PLACEHOLDER = "[campo sensível omitido]"
DATA_URL_PLACEHOLDER = "[data-url omitido]"
DOCUMENT_OMITTED_PLACEHOLDER = "[documento omitido por segurança]"
SENSITIVE_DATA_OMITTED_PLACEHOLDER = "[dados omitidos por segurança]"
_MAX_ENTITY_UNESCAPE_PASSES = 8
_MAX_SENSITIVE_VALUE_COUNT = 2048
_MAX_SENSITIVE_VALUE_BYTES = 512 * 1024
_MAX_SENSITIVE_VALUE_LENGTH = 16 * 1024


def _normalize_html_entities(value: str) -> str | None:
    """Decode entities to a bounded stable fixed point.

    Classification must see the same value a browser would see, including
    legacy double/triple-encoded ``data:`` schemes and credential labels.
    """
    current = value
    for _ in range(_MAX_ENTITY_UNESCAPE_PASSES):
        decoded = html.unescape(current)
        if decoded == current:
            return decoded
        current = decoded
    # Never classify a partially decoded value. Callers fail closed when the
    # bounded fixed-point budget is exhausted.
    return None


def _strip_markup(value: str) -> str | None:
    """Decode entities and return only text nodes, joining markup-split words."""
    normalized = _normalize_html_entities(value)
    if normalized is None:
        return None
    parser = _PlainTextExtractor()
    try:
        parser.feed(normalized)
        parser.close()
    except (AssertionError, ValueError, RecursionError):
        # Never fall back to returning partially parsed untrusted text.
        return None
    return "".join(parser.parts)


def _canonical_label(value: str) -> str | None:
    text = _strip_markup(value)
    if text is None:
        return None
    # Split after decoding: an entity can hide the uppercase camel boundary.
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    expanded = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", expanded)
    decomposed = unicodedata.normalize("NFKD", expanded)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", without_accents).lower().split())


def _normalize_label(value: str) -> str:
    # JSON escapes are decoded by json.loads; HTML entities and markup are
    # decoded/removed before labels are used for either parsing or redaction.
    return _canonical_label(value) or ""


_SENSITIVE_LABEL_FORMS: tuple[tuple[list[str], str], ...] | None = None


def _sensitive_label_forms() -> tuple[tuple[list[str], str], ...]:
    global _SENSITIVE_LABEL_FORMS
    if _SENSITIVE_LABEL_FORMS is None:
        _SENSITIVE_LABEL_FORMS = tuple(
            (normalized.split(), "".join(normalized.split()))
            for alias in sorted(SENSITIVE_LABEL_DENYLIST)
            if (normalized := _canonical_label(alias))
        )
    return _SENSITIVE_LABEL_FORMS


def _is_sensitive_label(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = _canonical_label(value)
    if normalized is None:
        return True
    if not normalized:
        return False
    tokens = normalized.split()
    compact = "".join(tokens)
    for alias_tokens, alias_compact in _sensitive_label_forms():
        width = len(alias_tokens)
        if any(tokens[index : index + width] == alias_tokens for index in range(len(tokens))):
            return True
        if compact == alias_compact or (compact.startswith(alias_compact) and compact[len(alias_compact):].isdigit()):
            return True
        if compact.startswith(alias_compact) and compact[len(alias_compact):] in _SENSITIVE_COMPOUND_SUFFIXES:
            return True
    return False


class _PlainTextExtractor(HTMLParser):
    """Converts untrusted strings to text without retaining markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)



def _plain_text(value: str) -> str:
    """Strip markup after entity decoding, preserving readable text."""
    text = _strip_markup(value)
    if text is None:
        return SENSITIVE_VALUE_PLACEHOLDER
    return html.escape(" ".join(text.split()), quote=True)


def _find_data_url_start(value: str, start: int = 0) -> tuple[int, int] | None:
    """Find a bounded, canonicalized ``data:`` scheme.

    HTML entities have already been decoded by :func:`_strip_markup`. The
    scanner still accepts controls/whitespace between the scheme letters and
    around the colon because those forms are routinely produced by hostile
    exports, while the bounded header walk prevents an untrusted string from
    causing an unbounded scan.
    """
    length = len(value)
    index = max(0, start)
    while index < length:
        if value[index].lower() != "d" or (index and value[index - 1].isalnum()):
            index += 1
            continue
        cursor = index
        matched = True
        for expected in "data":
            while cursor < length and (
                value[cursor] in _ASCII_CONTROL_OR_SPACE or value[cursor].isspace()
            ):
                cursor += 1
            if cursor >= length or value[cursor].lower() != expected:
                matched = False
                break
            cursor += 1
        if not matched:
            index += 1
            continue
        while cursor < length and (
            value[cursor] in _ASCII_CONTROL_OR_SPACE or value[cursor].isspace()
        ):
            cursor += 1
        if cursor >= length or value[cursor] != ":":
            index += 1
            continue
        return index, cursor + 1
    return None


def _redact_data_urls(value: str) -> str:
    """Replace canonical data URLs without relying on a fragile regex."""
    result: list[str] = []
    position = 0
    while position < len(value):
        found = _find_data_url_start(value, position)
        if found is None:
            result.append(value[position:])
            break
        start, header_start = found
        result.append(value[position:start])
        header_end = min(len(value), header_start + _DATA_URL_MAX_HEADER_CHARS)
        comma = value.find(",", header_start, header_end)
        # A scheme followed by a bounded header is enough to fail closed. A
        # missing comma may be malformed input, but retaining its tail could
        # still expose a credential-looking payload.
        result.append(DATA_URL_PLACEHOLDER)
        if comma < 0:
            break
        # Data URL payloads may contain spaces and controls; there is no safe
        # token boundary to infer, so redact the remainder conservatively.
        break
    return "".join(result)


def _redact_credential_assignments(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        secret_value = match.group("value")
        if secret_value.startswith("[") and secret_value.endswith("]"):
            return match.group(0)
        suffix = ""
        lower_secret = secret_value.lower()
        for extension in (".html", ".htm", ".json"):
            if lower_secret.endswith(extension):
                suffix = secret_value[-len(extension) :]
                break
        return f"{match.group('label')}{match.group('separator')}{SENSITIVE_VALUE_PLACEHOLDER}{suffix}"

    return _CREDENTIAL_ASSIGNMENT_RE.sub(replace, value)


def _redact_text(value: str, sensitive_values: set[str] | frozenset[str] | _SensitiveValueMatcher = frozenset()) -> str:
    """Decode entities/markup before bounded one-pass secret redaction."""
    redacted = _strip_markup(value)
    if redacted is None:
        return SENSITIVE_VALUE_PLACEHOLDER
    redacted = _redact_data_urls(redacted)
    redacted = _redact_credential_assignments(redacted)
    matcher = sensitive_values if isinstance(sensitive_values, _SensitiveValueMatcher) else _SensitiveValueMatcher(sensitive_values)
    return html.escape(" ".join(matcher.redact(redacted).split()), quote=True)


def _safe_text(value: str) -> str:
    return _redact_text(" ".join(value.split())).strip()


_METADATA_LABEL_KEYS = frozenset(
    {
        "label",
        "field",
        "fieldname",
        "name",
        "key",
        "fieldlabel",
        "labelname",
        "property",
        "attribute",
        "caption",
        "title",
        "datafield",
        "dataname",
        "datalabel",
        "datakey",
        "dataproperty",
        "dataattribute",
        "fieldkey",
        "fieldproperty",
        "fieldattribute",
        "attributename",
        "propertyname",
        "arialabel",
    }
)


def _canonical_metadata_key(value: object) -> str:
    if not isinstance(value, str):
        value = str(value)
    canonical = _canonical_label(value) or ""
    return "".join(canonical.split())


def _metadata_label_values(value: dict) -> list[str]:
    labels: list[str] = []
    for raw_key, raw_value in value.items():
        normalized_key = _canonical_metadata_key(raw_key)
        if normalized_key in _METADATA_LABEL_KEYS and isinstance(raw_value, str):
            labels.append(raw_value)
    return labels


def _collect_sensitive_values(value: object, *, label: object | None = None) -> set[str]:
    """Collect a complete bounded index or fail closed before redaction."""
    collected: set[str] = set()
    total_bytes = 0
    pending: list[tuple[object, object | None]] = [(value, label)]
    while pending:
        current, current_label = pending.pop()
        if _is_sensitive_label(current_label):
            if isinstance(current, str):
                normalized = _strip_markup(current)
                if normalized is None:
                    raise _SensitiveValueBudgetExceeded()
                if not normalized or normalized in collected:
                    continue
                if len(normalized) > _MAX_SENSITIVE_VALUE_LENGTH:
                    raise _SensitiveValueBudgetExceeded()
                size = len(normalized.encode("utf-8"))
                if len(collected) >= _MAX_SENSITIVE_VALUE_COUNT or total_bytes + size > _MAX_SENSITIVE_VALUE_BYTES:
                    raise _SensitiveValueBudgetExceeded()
                collected.add(normalized)
                total_bytes += size
                continue
            if isinstance(current, dict):
                pending.extend((child, current_label) for child in reversed(tuple(current.values())))
                continue
            if isinstance(current, (list, tuple)):
                pending.extend((child, current_label) for child in reversed(current))
                continue
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                try:
                    normalized = str(current)
                    if not math.isfinite(float(current)) or normalized in collected:
                        continue
                    if len(normalized) > _MAX_SENSITIVE_VALUE_LENGTH:
                        raise _SensitiveValueBudgetExceeded()
                    size = len(normalized.encode("utf-8"))
                    if len(collected) >= _MAX_SENSITIVE_VALUE_COUNT or total_bytes + size > _MAX_SENSITIVE_VALUE_BYTES:
                        raise _SensitiveValueBudgetExceeded()
                    collected.add(normalized)
                    total_bytes += size
                except _SensitiveValueBudgetExceeded:
                    raise
                except (TypeError, ValueError, OverflowError):
                    continue
                continue
        elif isinstance(current, dict):
            labels = [marker for marker in _metadata_label_values(current) if _is_sensitive_label(marker)]
            if labels:
                pending.extend((child, labels[0]) for child in reversed(tuple(current.values())))
            else:
                pending.extend((child, key) for key, child in reversed(tuple(current.items())))
        elif isinstance(current, (list, tuple)):
            pending.extend((child, None) for child in reversed(current))
    return collected


class _SensitiveValueMatcher:
    """Bounded Aho–Corasick matcher: one pass per public string."""
    __slots__ = ("transitions", "failures", "longest")

    def __init__(self, values: set[str] | frozenset[str] = frozenset()) -> None:
        from collections import deque
        self.transitions: list[dict[str, int]] = [{}]
        self.failures: list[int] = [0]
        self.longest: list[int] = [0]
        total_bytes = 0
        value_count = 0
        for value in sorted(values):
            if not value:
                continue
            if len(value) > _MAX_SENSITIVE_VALUE_LENGTH:
                raise _SensitiveValueBudgetExceeded()
            size = len(value.encode("utf-8"))
            if value_count >= _MAX_SENSITIVE_VALUE_COUNT or total_bytes + size > _MAX_SENSITIVE_VALUE_BYTES:
                raise _SensitiveValueBudgetExceeded()
            value_count += 1
            total_bytes += size
            node = 0
            for char in value:
                node = self.transitions[node].setdefault(char, len(self.transitions))
                if node == len(self.transitions):
                    self.transitions.append({}); self.failures.append(0); self.longest.append(0)
            self.longest[node] = max(self.longest[node], len(value))
        queue = deque(self.transitions[0].values())
        while queue:
            node = queue.popleft(); failure = self.failures[node]
            self.longest[node] = max(self.longest[node], self.longest[failure])
            for char, child in self.transitions[node].items():
                fallback = failure
                while fallback and char not in self.transitions[fallback]:
                    fallback = self.failures[fallback]
                self.failures[child] = self.transitions[fallback].get(char, 0)
                queue.append(child)

    def redact(self, value: str) -> str:
        if len(self.transitions) == 1 or not value:
            return value
        intervals: list[tuple[int, int]] = []
        state = 0; start = end = None
        for index, char in enumerate(value):
            while state and char not in self.transitions[state]:
                state = self.failures[state]
            state = self.transitions[state].get(char, 0)
            length = self.longest[state]
            if not length:
                continue
            match_start, match_end = index + 1 - length, index + 1
            if start is None:
                start, end = match_start, match_end
            elif match_start <= end:
                end = max(end, match_end)
            else:
                intervals.append((start, end)); start, end = match_start, match_end
        if start is not None:
            intervals.append((start, end))
        if not intervals:
            return value
        parts: list[str] = []; cursor = 0
        for begin, finish in intervals:
            if begin > cursor: parts.append(value[cursor:begin])
            parts.append(SENSITIVE_VALUE_PLACEHOLDER); cursor = max(cursor, finish)
        if cursor < len(value): parts.append(value[cursor:])
        return "".join(parts)


def _sanitize_value(value: object, matcher: _SensitiveValueMatcher) -> object:
    if isinstance(value, dict):
        if any(_is_sensitive_label(marker) for marker in _metadata_label_values(value)):
            return {"label": SENSITIVE_FIELD_PLACEHOLDER, "value": SENSITIVE_VALUE_PLACEHOLDER}
        sanitized: dict[str, object] = {}; redacted_field_added = False
        for raw_key, child in value.items():
            key = str(raw_key)
            if _is_sensitive_label(key):
                if not redacted_field_added:
                    sanitized[SENSITIVE_FIELD_PLACEHOLDER] = SENSITIVE_VALUE_PLACEHOLDER
                    redacted_field_added = True
                continue
            sanitized[_redact_text(key, matcher)] = _sanitize_value(child, matcher)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(child, matcher) for child in value]
    if isinstance(value, tuple):
        return [_sanitize_value(child, matcher) for child in value]
    if isinstance(value, str):
        return _redact_text(value, matcher)
    return value


def _sanitize_payload(payload: object) -> object:
    return _sanitize_value(payload, _SensitiveValueMatcher(_collect_sensitive_values(payload)))


def _serialize_safe_payload(payload: object, *, already_sanitized: bool = False) -> str:
    """Return the only document form allowed in staging and the API.

    This is deterministic JSON generated from the parsed payload, never from
    the submitted HTML bytes. Values have already been reduced to escaped
    plain text, so the representation contains no executable markup.
    """
    try:
        sanitized = payload if already_sanitized else _sanitize_payload(payload)
        return json.dumps(
            sanitized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise NotesImportError("Não foi possível serializar com segurança os dados importados.") from exc



def _parse_number(value: str) -> float | None:
    token = value.strip().replace(" ", "")
    if not token:
        return None
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        parsed = float(token)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _numbers(value: str) -> list[float]:
    return [number for token in _NUMBER_RE.findall(value) if (number := _parse_number(token)) is not None]


def _as_int_or_float(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _parse_boolean(value: str) -> bool | str:
    normalized = _normalize_label(value)
    if normalized in {"sim", "yes", "true", "1", "incluido", "tem", "com"}:
        return True
    if normalized in {"nao", "no", "false", "0", "sem", "nao incluido", "não"}:
        return False
    return value.strip()


def _extract_pair(value: str) -> tuple[float, float] | None:
    coordinate_patterns = (
        r"(?:query|q|ll)=\s*([-+]?\d[\d.,]*)\s*[,; ]\s*([-+]?\d[\d.,]*)",
        r"@\s*([-+]?\d[\d.,]*)\s*[,; ]\s*([-+]?\d[\d.,]*)",
    )
    for pattern in coordinate_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            first = _parse_number(match.group(1))
            second = _parse_number(match.group(2))
            if first is not None and second is not None:
                return first, second
    matches = _NUMBER_RE.findall(value)
    numbers = [_parse_number(token) for token in matches]
    numbers = [number for number in numbers if number is not None]
    if len(numbers) < 2:
        return None
    return numbers[0], numbers[1]


def _attachment_from_url(url: str) -> tuple[str | None, int | None]:
    if not url.lower().startswith("data:"):
        return None, None
    header, _, data = url.partition(",")
    mime = header[5:].split(";", 1)[0].strip() or None
    if ";base64" in header.lower():
        padding = len(data) - len(data.rstrip("="))
        size = max(0, (len(data.rstrip("=")) * 3 // 4) - padding)
    else:
        size = len(unquote_to_bytes(data))
    return mime, size


class _LegacyFieldExtractor(HTMLParser):
    """Extrai o export estrutural legado sem executar HTML ou JavaScript.

    Os exports v12 usam pares `<dt>/<dd>` dentro de `<section>` e uma tabela
    para os inversores. A extração é orientada pelos rótulos genéricos do
    formulário, nunca por nomes de clientes ou outros marcadores da instalação.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, object] = {}
        self.unknown_fields: list[tuple[str, str]] = []
        self._in_dt = False
        self._dt_parts: list[str] = []
        self._current_label = ""
        self._dd_parts: list[str] | None = None
        self._dd_link_values: list[str] = []
        self._dd_table_rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._dd_attachments: list[dict[str, object | None]] = []
        self._footer_parts: list[str] = []
        self._in_footer = False
        self._form_field: str | None = None
        self._form_parts: list[str] = []
        self._form_value: str | None = None
        self._form_checked = False
        self._form_sensitive = False
        self._panel_description: str | None = None
        self._panel_data: dict[str, int | float] = {}
        self._dd_contacts: list[dict[str, str]] = []
        self._ct: dict[str, str] | None = None
        self._ct_depth = 0
        self._ct_capture: str | None = None
        self._ct_buffer: list[str] = []
        self._ct_invalid = False
        self.form_version = "10"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    _VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_map = {key.lower(): value for key, value in attrs}

        if tag == "dt":
            self._reset_contact_state()
            self._in_dt = True
            self._dt_parts = []
        elif tag == "dd":
            self._dd_parts = []
            self._dd_link_values = []
            self._dd_table_rows = []
            self._dd_attachments = []
            self._dd_contacts = []
            self._reset_contact_state()
        elif tag == "tr" and self._dd_parts is not None:
            self._current_row = []
        elif tag in {"th", "td"} and self._current_row is not None:
            self._current_cell = []

        if self._dd_parts is not None:
            self._track_contact_start(tag, attrs_map)
            if tag in {"a", "img"}:
                url = attrs_map.get("href") if tag == "a" else attrs_map.get("src")
                if url:
                    if tag == "a":
                        self._dd_link_values.append(url)
                    mime, size = _attachment_from_url(url)
                    is_download_link = tag == "a" and any(
                        attrs_map.get(key) for key in ("download", "data-filename", "data-name")
                    )
                    is_preview_link = tag == "a" and bool(attrs_map.get("title"))
                    if mime or url.lower().startswith("data:") or is_download_link or is_preview_link:
                        self._dd_attachments.append(
                            {
                                "nome": (
                                    attrs_map.get("download")
                                    or attrs_map.get("data-filename")
                                    or attrs_map.get("data-name")
                                    or attrs_map.get("title")
                                ),
                                "tipo": attrs_map.get("data-mime") or attrs_map.get("type") or mime,
                                "tamanho": _parse_number(attrs_map["data-size"] or "")
                                if attrs_map.get("data-size")
                                else size,
                                "prioridade": 2 if is_download_link else 1 if is_preview_link else 0,
                            }
                        )

        if tag == "footer":
            self._in_footer = True
        if tag in {"input", "textarea", "select"} and self._dd_parts is None:
            if self._form_field is not None:
                self._finish_form_field()
            self._begin_form_field(tag, attrs_map)
        elif tag == "option" and self._form_field is not None and attrs_map.get("selected") is not None:
            self._form_parts = []
        if tag in self._VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        self._track_contact_end(tag)
        if tag == "dt":
            self._current_label = " ".join(self._dt_parts).strip()
            self._in_dt = False
        elif tag in {"th", "td"} and self._current_row is not None and self._current_cell is not None:
            self._current_row.append(" ".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self._dd_table_rows.append(self._current_row)
            self._current_row = None
        elif tag == "dd" and self._dd_parts is not None:
            self._finish_dd()
        elif tag in {"input", "textarea", "select"} and self._form_field is not None:
            self._finish_form_field()
        elif tag == "option" and self._form_field is not None and self._form_parts:
            self._form_value = " ".join(self._form_parts).strip()
        elif tag == "footer":
            self._in_footer = False

    def handle_data(self, data: str) -> None:
        if self._ct_capture is not None and self._ct is not None:
            self._ct_buffer.append(data)
        if self._in_dt:
            self._dt_parts.append(data.strip())
        if self._dd_parts is not None:
            self._dd_parts.append(data.strip())
        if self._current_cell is not None:
            self._current_cell.append(data.strip())
        if self._form_field is not None and self._dd_parts is None:
            self._form_parts.append(data.strip())
        if self._in_footer:
            self._footer_parts.append(data.strip())

    def _begin_form_field(self, tag: str, attrs: dict[str, str | None]) -> None:
        self._form_field = attrs.get("data-field") or attrs.get("name") or attrs.get("id")
        input_type = _normalize_label(attrs.get("type") or "")
        self._form_sensitive = input_type in {"password", "secret", "token", "credential", "passcode", "pin", "puk"}
        self._form_parts = []
        self._form_value = attrs.get("value")
        self._form_checked = "checked" in attrs or attrs.get("aria-checked") == "true"
        if tag == "input" and self._form_checked and not self._form_value:
            self._form_value = "Sim"

    def _finish_form_field(self) -> None:
        if self._form_field and not self._form_sensitive and not _is_sensitive_label(self._form_field):
            value = self._form_value or " ".join(self._form_parts).strip()
            if value:
                self._store_value(self._form_field, value)
        self._form_field = None
        self._form_parts = []
        self._form_value = None
        self._form_checked = False
        self._form_sensitive = False

    _MAX_CONTACT_PEOPLE = 50

    def _track_contact_start(self, tag: str, attrs_map: dict[str, str | None]) -> None:
        """Blocos `div.ct` do export v11+: `<b>nome</b> <span class=fn>· função</span>`
        e `<a href=tel:…>`/`<a href=mailto:…>`. Só lê texto; nunca segue links."""
        classes = (attrs_map.get("class") or "").split()
        if tag == "div":
            if self._ct is None and "ct" in classes:
                if len(self._dd_contacts) >= self._MAX_CONTACT_PEOPLE:
                    return  # limite atingido: não cria estado nem captura texto
                self._ct = {}
                self._ct_depth = 1
                self._ct_invalid = False
            elif self._ct is not None:
                if "ct" in classes:
                    self._ct_invalid = True  # contacto aninhado: descarta o bloco exterior
                self._ct_depth += 1
            return
        if self._ct is None:
            return
        if tag == "b" and "nome" not in self._ct:
            self._ct_capture, self._ct_buffer = "nome", []
        elif tag == "span" and "fn" in classes:
            self._ct_capture, self._ct_buffer = "funcao", []
        elif tag == "a":
            href = (attrs_map.get("href") or "").strip()
            lowered = href.lower()
            if lowered.startswith("tel:"):
                number = re.split(r"[?;#]", unquote(href[4:]), maxsplit=1)[0].strip()
                if number:
                    self._ct.setdefault("telefone", _safe_text(number))
            elif lowered.startswith("mailto:"):
                address = unquote(href[7:]).split("?", 1)[0].strip()
                if _EMAIL_RE.fullmatch(address):
                    self._ct.setdefault("email", address)

    def _track_contact_end(self, tag: str) -> None:
        if self._ct is None:
            return
        if tag in {"b", "span"} and self._ct_capture is not None:
            text = _safe_text(" ".join(part.strip() for part in self._ct_buffer if part.strip()))
            text = text.lstrip("·-–— ").strip()
            if text:
                self._ct.setdefault(self._ct_capture, text)
            self._ct_capture = None
            self._ct_buffer = []
        elif tag == "div":
            self._ct_depth -= 1
            if self._ct_depth <= 0:
                contact = {key: value for key, value in self._ct.items() if value}
                if (
                    not self._ct_invalid
                    and contact.get("nome")
                    and len(self._dd_contacts) < self._MAX_CONTACT_PEOPLE
                ):
                    self._dd_contacts.append(contact)
                self._reset_contact_state()

    def _reset_contact_state(self) -> None:
        self._ct = None
        self._ct_depth = 0
        self._ct_capture = None
        self._ct_buffer = []
        self._ct_invalid = False

    def _store_contact_people(self, contacts: list[dict[str, str]]) -> None:
        self.fields["contactos"] = contacts
        first = contacts[0]
        for source_key, target_key in (
            ("nome", "contacto"),
            ("funcao", "funcao"),
            ("telefone", "telefone"),
            ("email", "email"),
        ):
            if first.get(source_key) and not self.fields.get(target_key):
                self.fields[target_key] = first[source_key]

    def _finish_dd(self) -> None:
        value = _safe_text(" ".join(part for part in self._dd_parts or [] if part))
        label = self._current_label.strip()
        normalized_label = _normalize_label(label)
        attachments = self._finalize_attachments(value)
        if self._dd_contacts and normalized_label.startswith(("pessoas de contacto", "pessoa de contacto", "contactos")):
            self._store_contact_people(self._dd_contacts)
        elif normalized_label in {"anexos", "anexo", "ficheiros", "ficheiros anexos"}:
            self._store_value(label, attachments or value)
        else:
            self._store_value(label, value, table_rows=self._dd_table_rows, link_values=self._dd_link_values)
        self._dd_parts = None
        self._dd_link_values = []
        self._dd_table_rows = []
        self._dd_attachments = []
        self._dd_contacts = []
        self._reset_contact_state()
        self._current_label = ""

    def _finalize_attachments(self, visible_value: str) -> list[dict[str, object | None]]:
        if not self._dd_attachments:
            return []
        preferred: dict[tuple[object | None, object | None], dict[str, object | None]] = {}
        for item in self._dd_attachments:
            key = (item.get("tipo"), item.get("tamanho"))
            previous = preferred.get(key)
            raw_item_priority = item.get("prioridade")
            item_priority: float = float(raw_item_priority) if isinstance(raw_item_priority, (int, float)) else 0.0
            raw_previous_priority = previous.get("prioridade") if previous else None
            previous_priority: float = (
                float(raw_previous_priority) if isinstance(raw_previous_priority, (int, float)) else 0.0
            )
            if previous is None or item_priority > previous_priority:
                preferred[key] = item
        metadata: list[dict[str, object | None]] = []
        for index, item in enumerate(preferred.values(), start=1):
            name = item.get("nome") or (visible_value if len(preferred) == 1 else None)
            if not name:
                name = f"anexo-{index}"
            raw_size = item.get("tamanho")
            clean_item = {
                "nome": _safe_text(str(name)),
                "tipo": str(item["tipo"]) if item.get("tipo") else None,
                "tamanho": _as_int_or_float(float(raw_size)) if isinstance(raw_size, (int, float)) else raw_size,
            }
            if clean_item not in metadata:
                metadata.append(clean_item)
        return metadata

    def _store_value(
        self,
        label: str,
        value: str | list[dict[str, object | None]],
        *,
        table_rows: list[list[str]] | None = None,
        link_values: list[str] | None = None,
    ) -> None:
        if not label:
            return
        normalized_label = _normalize_label(label)
        if isinstance(value, list):
            self.fields["anexos"] = value
            return
        value = _safe_text(value)
        if not value:
            return

        if normalized_label in {"cliente", "nome do cliente"}:
            self.fields["cliente"] = value
        elif "pessoa de contacto" in normalized_label or normalized_label in {"contacto", "nome do contacto"}:
            self.fields["contacto"] = value
        elif normalized_label in {"funcao dessa pessoa", "funcao do contacto", "cargo do contacto", "cargo"}:
            self.fields["funcao"] = value
        elif normalized_label in {"qual a funcao", "qual e a funcao", "outra funcao", "qual a funcao outra"}:
            self.fields["funcaoOutra"] = value
        elif "telefone" in normalized_label or "email" in normalized_label:
            self._store_contact_channels(value)
        elif "morada" in normalized_label or "endereco" in normalized_label:
            self.fields["morada"] = value
        elif normalized_label in {"nif", "nif do cliente", "numero de contribuinte", "contribuinte"} or normalized_label.startswith("nif "):
            self.fields["nif"] = value
        elif "distrito" in normalized_label:
            self.fields["distrito"] = value
        elif "concelho" in normalized_label or "municipio" in normalized_label:
            self.fields["concelho"] = value
        elif "coordenada" in normalized_label:
            pair = _extract_pair(" ".join([value, *(link_values or [])]))
            if pair:
                self.fields["lat"], self.fields["lon"] = pair
        elif normalized_label in {"paineis", "painel"}:
            self._panel_description = value
            self._merge_panel_data(value)
        elif "quantidade" in normalized_label and ("painel" in normalized_label or "painei" in normalized_label):
            self._merge_panel_data(value, quantity=True)
        elif "potencia" in normalized_label and "painel" in normalized_label:
            self._merge_panel_data(value, panel_power=True)
        elif "potencia" in normalized_label and ("calculada" in normalized_label or "calculo" in normalized_label):
            self.fields["potenciaKwpCalculada"] = self._first_number(value)
        elif "potencia" in normalized_label and ("declarada" in normalized_label or "instalada" in normalized_label):
            self.fields["potenciaKwpDeclarada"] = self._first_number(value)
            self.fields["potenciaKwpRaw"] = value
        elif normalized_label in {"potencia kwp", "potencia", "potencia total"}:
            self.fields["potenciaKwp"] = self._first_number(value)
            self.fields["potenciaKwpRaw"] = value
        elif "inversor" in normalized_label:
            rows = self._parse_inverter_rows(table_rows or [])
            self.fields["inversores"] = rows if rows else value
        elif "bateria" in normalized_label:
            self.fields["baterias"] = value
        elif "backup" in normalized_label:
            self.fields["backup"] = _parse_boolean(value)
        elif "carregador" in normalized_label and (
            " ve" in f" {normalized_label}" or "veiculo" in normalized_label or "veiculos" in normalized_label
        ):
            self.fields["carregadoresVe"] = value
        elif "tipo" in normalized_label and "instalacao" in normalized_label:
            self.fields["tipoInstalacao"] = value
        elif "controlador" in normalized_label:
            self.fields["controlador"] = value
        elif "outro equipamento" in normalized_label or "outros equipamento" in normalized_label:
            self.fields["outroEquipamento"] = value
        elif "injecao" in normalized_label:
            self.fields["injecao"] = value
        elif " o m" in f" {normalized_label}" or "om" in normalized_label or "manutencao" in normalized_label:
            self.fields["om"] = value
        elif "rgpd" in normalized_label or "consentimento" in normalized_label:
            self.fields["rgpd"] = _parse_boolean(value)
        elif "upac" in normalized_label:
            self.fields["upacExistente"] = _parse_boolean(value) if _normalize_label(value) in {"sim", "nao", "yes", "no"} else value
        elif "urgencia" in normalized_label:
            self.fields["urgencia"] = value
        elif normalized_label == "observacoes" or normalized_label.startswith("observacoes "):
            self.fields["observacoes"] = value
        elif "helioscope" in normalized_label and any(word in normalized_label for word in ("corresponde", "divergencia", "discrepancia")):
            self.fields["divergenciasHelioscope"] = value
        elif "helioscope" in normalized_label:
            self.fields["helioscopeIgnorar"] = value
        elif "pressupostos da proposta" in normalized_label or "pressuposto da proposta" in normalized_label:
            self.fields["pressupostosProposta"] = value
        else:
            self.unknown_fields.append((label, value))

    def _store_contact_channels(self, value: str) -> None:
        email = _EMAIL_RE.search(value)
        phone = _PHONE_RE.search(value)
        if email:
            self.fields["email"] = email.group(0)
        if phone:
            self.fields["telefone"] = phone.group(0).strip()
        if not email and not phone:
            self.unknown_fields.append((self._current_label or "contacto", value))

    @staticmethod
    def _first_number(value: str) -> float | None:
        values = _numbers(value)
        return values[0] if values else None

    def _merge_panel_data(self, value: str, *, quantity: bool = False, panel_power: bool = False) -> None:
        values = _numbers(value)
        if quantity and values:
            self._panel_data["quantidade"] = _as_int_or_float(values[0])
        elif panel_power:
            wp_match = re.search(r"([-+]?\d[\d.,]*)\s*(?:w\s*p|wp)\b", value, re.IGNORECASE)
            if wp_match:
                parsed = _parse_number(wp_match.group(1))
                if parsed is not None:
                    self._panel_data["potenciaWp"] = parsed
            elif values:
                self._panel_data["potenciaWp"] = values[0]
        elif values:
            wp_match = re.search(r"([-+]?\d[\d.,]*)\s*(?:w\s*p|wp)\b", value, re.IGNORECASE)
            if wp_match:
                wp = _parse_number(wp_match.group(1))
                if wp is not None:
                    self._panel_data["potenciaWp"] = wp
                before_wp = value[: wp_match.start()]
                before_values = _numbers(before_wp)
                if before_values:
                    self._panel_data["quantidade"] = _as_int_or_float(before_values[-1])
            else:
                self._panel_data["quantidade"] = _as_int_or_float(values[0])
        self.fields["paineis"] = dict(self._panel_data)

    @staticmethod
    def _parse_inverter_rows(rows: list[list[str]]) -> list[dict[str, int | float | str]]:
        if len(rows) < 2:
            return []
        headers = [_normalize_label(cell) for cell in rows[0]]
        model_index = next((i for i, header in enumerate(headers) if "modelo" in header or "inversor" in header), 0)
        quantity_index = next(
            (i for i, header in enumerate(headers) if "quantidade" in header or header in {"qtd", "quant", "qty"}),
            1 if len(rows[0]) > 1 else None,
        )
        parsed: list[dict[str, int | float | str]] = []
        for row in rows[1:]:
            if not row or not any(row):
                continue
            model = row[model_index].strip() if model_index < len(row) else ""
            if not model:
                continue
            item: dict[str, int | float | str] = {"modelo": model}
            if quantity_index is not None and quantity_index < len(row):
                quantity = _numbers(row[quantity_index])
                if quantity:
                    item["quantidade"] = _as_int_or_float(quantity[0])
            parsed.append(item)
        return parsed

    def finalize(self) -> None:
        footer = _normalize_label(" ".join(self._footer_parts))
        match = re.search(r"(?:versao|version)\s*(?:do formulario)?\s*[:\-]?\s*v\s*(\d+)\b", footer)
        if match is None:
            match = re.search(r"\bv\s*(\d+)\b", footer)
        self.form_version = match.group(1) if match else "10"

        role = self.fields.get("funcao")
        qualifier = self.fields.pop("funcaoOutra", None)
        if role:
            inline_qualifier = re.match(r"^\s*outra\s*(?::|[-–—])?\s+(.+)$", str(role), flags=re.IGNORECASE)
            if inline_qualifier and not qualifier:
                qualifier = inline_qualifier.group(1).strip()
                role = "Outra"
        if qualifier and (not role or _normalize_label(str(role)) == "outra"):
            self.fields["funcao"] = f"Outra — {qualifier}"
        elif role and qualifier and _normalize_label(str(role)) != _normalize_label(str(qualifier)):
            self.fields["funcao"] = f"{role} — {qualifier}"

        if self._panel_data:
            if self.form_version == "10" and self._panel_description and set(self._panel_data) >= {"quantidade", "potenciaWp"}:
                self.fields["paineis"] = {"descricao": self._panel_description}
            else:
                self.fields["paineis"] = dict(self._panel_data)

        panel = self.fields.get("paineis")
        if isinstance(panel, dict) and panel.get("quantidade") is not None and panel.get("potenciaWp") is not None:
            calculated = float(panel["quantidade"]) * float(panel["potenciaWp"]) / 1000
            self.fields.setdefault("potenciaKwpCalculada", calculated)
        if self.fields.get("potenciaKwpDeclarada") is not None:
            self.fields["potenciaKwp"] = self.fields["potenciaKwpDeclarada"]
        elif self.fields.get("potenciaKwp") is None and self.fields.get("potenciaKwpCalculada") is not None:
            self.fields["potenciaKwp"] = self.fields["potenciaKwpCalculada"]



def compute_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_payload(*, filename: str, content: bytes) -> dict:
    """Devolve o payload JSON normalizado a partir de um `.json` solto ou
    de um `.html` com o bloco `<script id="notas-iniciais-data">`.
    Nunca executa o conteúdo — só extrai texto e faz `json.loads`."""
    lower_name = filename.lower()
    if lower_name.endswith(".json"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotesImportError("Ficheiro JSON com encoding inválido (esperado UTF-8).") from exc
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError, OverflowError, RecursionError) as exc:
            raise NotesImportError("JSON inválido ou demasiado complexo.") from exc

    if lower_name.endswith(".html") or lower_name.endswith(".htm"):
        try:
            html_text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotesImportError("Ficheiro HTML com encoding inválido (esperado UTF-8).") from exc
        extractor = _NotesScriptExtractor()
        try:
            extractor.feed(html_text)
            extractor.close()
        except (ValueError, RecursionError) as exc:
            raise NotesImportError("HTML inválido ou demasiado complexo.") from exc
        if not extractor.captured or not extractor.captured.strip():
            legacy_payload = _extract_legacy_html_payload(html_text)
            if legacy_payload is not None:
                return legacy_payload
            raise NotesImportError(
                "Não foi encontrado o bloco de dados estruturados "
                f'(<script type="application/json" id="{SCRIPT_TAG_ID}">) no HTML. '
                "Confirme que o formulário foi exportado com a versão que inclui esse bloco, "
                "ou envie o JSON em separado."
            )
        try:
            return json.loads(extractor.captured)
        except (json.JSONDecodeError, ValueError, OverflowError, RecursionError) as exc:
            raise NotesImportError("O bloco de dados estruturados não é JSON válido ou é demasiado complexo.") from exc

    raise NotesImportError(f"Extensão de ficheiro não suportada: {filename!r} (use .html, .htm ou .json).")


def sanitize_document_for_read(*, filename: str, raw_document_text: object) -> str:
    """Return deterministic plain JSON for both new and legacy documents.

    Older rows may contain the submitted HTML or an untrusted JSON string.
    Parsing failures deliberately return an omission marker; returning the
    historical bytes would defeat the staging redaction guarantees.
    """
    if not isinstance(raw_document_text, str):
        return DOCUMENT_OMITTED_PLACEHOLDER
    try:
        try:
            payload = extract_payload(filename=filename, content=raw_document_text.encode("utf-8"))
        except NotesImportError:
            payload = json.loads(raw_document_text)
        if not isinstance(payload, dict):
            raise NotesImportError("documento legado não é um objeto JSON")
        return _serialize_safe_payload(payload)
    except (NotesImportError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError, RecursionError):
        return DOCUMENT_OMITTED_PLACEHOLDER


def _extract_legacy_html_payload(html_text: str) -> dict | None:
    """Extrai um export estrutural v10/v11/v12 sem nomes de cliente.

    A versão é lida do rodapé quando existe. Um HTML estrutural sem versão
    explícita fica conservadoramente em v10, mantendo a compatibilidade do
    importador anterior sem presumir que é o formato mais recente.
    """
    parser = _LegacyFieldExtractor()
    try:
        parser.feed(html_text)
        parser.close()
        parser.finalize()
    except (ValueError, RecursionError) as exc:
        raise NotesImportError("HTML inválido ou demasiado complexo.") from exc
    if not parser.fields.get("cliente"):
        return None
    payload = {
        "formVersion": parser.form_version,
        **{key: value for key, value in parser.fields.items() if value not in (None, "")},
    }
    if parser.unknown_fields:
        payload["camposDesconhecidos"] = [
            {
                "label": label if parser.form_version != "10" else label.lower(),
                "value": value,
            }
            for label, value in parser.unknown_fields
        ]
    return payload


_MAX_GENERIC_STRING_LENGTH = 10_000
_MAX_GENERIC_ITEMS = 10_000
_MAX_JSON_DEPTH = 32


def _validation_error(field: str, message: str) -> NotesImportError:
    return NotesImportError(f"Campo '{field}' inválido: {message}.")


def _validate_json_tree(value: object, *, path: str = "$", depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise _validation_error(path, "estrutura demasiado profunda")
    if isinstance(value, float) and not math.isfinite(value):
        raise _validation_error(path, "o número tem de ser finito")
    if isinstance(value, str):
        if len(value) > _MAX_GENERIC_STRING_LENGTH:
            raise _validation_error(path, f"texto demasiado longo (máximo {_MAX_GENERIC_STRING_LENGTH} caracteres)")
        return
    if isinstance(value, dict):
        if len(value) > _MAX_GENERIC_ITEMS:
            raise _validation_error(path, "demasiados campos")
        for key, child in value.items():
            if not isinstance(key, str):
                raise _validation_error(path, "os nomes dos campos têm de ser texto")
            _validate_json_tree(child, path=f"{path}.{key}", depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > _MAX_GENERIC_ITEMS:
            raise _validation_error(path, "demasiados itens")
        for index, child in enumerate(value):
            _validate_json_tree(child, path=f"{path}[{index}]", depth=depth + 1)


def _validate_text_field(payload: dict, key: str, maximum: int) -> None:
    value = payload.get(key)
    if value is None:
        return
    if not isinstance(value, str):
        raise _validation_error(key, "esperado texto")
    if len(value) > maximum:
        raise _validation_error(key, f"texto demasiado longo (máximo {maximum} caracteres)")


def _validate_number_field(
    payload: dict, key: str, *, minimum: float | None = None, maximum: float | None = None
) -> None:
    value = payload.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _validation_error(key, "esperado número")
    try:
        numeric_value = float(value)
    except (ValueError, OverflowError) as exc:
        raise _validation_error(key, "o número é demasiado grande") from exc
    if not math.isfinite(numeric_value):
        raise _validation_error(key, "o número tem de ser finito")
    if minimum is not None and numeric_value < minimum:
        raise _validation_error(key, f"tem de ser >= {minimum}")
    if maximum is not None and numeric_value > maximum:
        raise _validation_error(key, f"tem de ser <= {maximum}")


def _validate_integer(value: object, field: str, *, minimum: int = 0, maximum: int = 1_000_000) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _validation_error(field, "esperado inteiro")
    if value < minimum or value > maximum:
        raise _validation_error(field, f"tem de estar entre {minimum} e {maximum}")


def _validate_payload_types(payload: object) -> None:
    if not isinstance(payload, dict):
        raise NotesImportError("O payload extraído não é um objeto JSON.")
    _validate_json_tree(payload)

    text_limits = {
        "formVersion": 32,
        "cliente": 256,
        "nif": 32,
        "contacto": 256,
        "funcao": 128,
        "telefone": 64,
        "email": 320,
        "morada": 512,
        "distrito": 128,
        "concelho": 128,
        "potenciaKwpRaw": 64,
        "baterias": 10_000,
        "carregadoresVe": 10_000,
        "tipoInstalacao": 128,
        "injecao": 128,
        "om": 10_000,
        "controlador": 10_000,
        "urgencia": 10_000,
        "observacoes": 10_000,
        "divergenciasHelioscope": 10_000,
        "helioscopeIgnorar": 10_000,
        "pressupostosProposta": 10_000,
    }
    for key, maximum in text_limits.items():
        _validate_text_field(payload, key, maximum)

    for key, minimum, maximum in (
        ("lat", -90.0, 90.0),
        ("lon", -180.0, 180.0),
        ("potenciaKwp", 0.0, 1_000_000.0),
        ("potenciaKwpCalculada", 0.0, 1_000_000.0),
        ("potenciaKwpDeclarada", 0.0, 1_000_000.0),
    ):
        _validate_number_field(payload, key, minimum=minimum, maximum=maximum)

    paineis = payload.get("paineis")
    if paineis is not None:
        if isinstance(paineis, str):
            _validate_text_field(payload, "paineis", 10_000)
        elif isinstance(paineis, dict):
            if "descricao" in paineis:
                if not isinstance(paineis["descricao"], str):
                    raise _validation_error("paineis.descricao", "esperado texto")
            for key in ("quantidade", "potenciaWp"):
                if key in paineis and paineis[key] is not None:
                    if key == "quantidade":
                        _validate_integer(paineis[key], f"paineis.{key}")
                    else:
                        numeric_value = paineis[key]
                        if isinstance(numeric_value, bool) or not isinstance(numeric_value, (int, float)):
                            raise _validation_error(f"paineis.{key}", "esperado número")
                        try:
                            numeric_float = float(numeric_value)
                        except (ValueError, OverflowError) as exc:
                            raise _validation_error(f"paineis.{key}", "o número é demasiado grande") from exc
                        if not math.isfinite(numeric_float) or not 0 <= numeric_float <= 100_000:
                            raise _validation_error(f"paineis.{key}", "número fora do intervalo permitido")
        else:
            raise _validation_error("paineis", "esperado texto ou objeto")

    inversores = payload.get("inversores")
    if inversores is not None:
        if isinstance(inversores, str):
            _validate_text_field(payload, "inversores", 10_000)
        elif isinstance(inversores, list):
            for index, item in enumerate(inversores):
                field = f"inversores[{index}]"
                if isinstance(item, str):
                    if len(item) > 256:
                        raise _validation_error(field, "texto demasiado longo")
                elif isinstance(item, dict):
                    if not isinstance(item.get("modelo"), str) or not item.get("modelo", "").strip():
                        raise _validation_error(field, "cada objeto precisa de 'modelo' textual")
                    if len(item["modelo"]) > 256:
                        raise _validation_error(f"{field}.modelo", "texto demasiado longo")
                    if "quantidade" in item and item["quantidade"] is not None:
                        _validate_integer(item["quantidade"], f"{field}.quantidade")
                else:
                    raise _validation_error(field, "esperado texto ou objeto")
        else:
            raise _validation_error("inversores", "esperado texto ou lista")

    contactos = payload.get("contactos")
    if contactos is not None:
        if not isinstance(contactos, list):
            raise _validation_error("contactos", "esperada lista")
        if len(contactos) > 50:
            raise _validation_error("contactos", "demasiadas pessoas de contacto (máximo 50)")
        for index, item in enumerate(contactos):
            field = f"contactos[{index}]"
            if not isinstance(item, dict):
                raise _validation_error(field, "esperado objeto")
            _validate_text_field(item, "nome", 256)
            if not isinstance(item.get("nome"), str) or not item["nome"].strip():
                raise _validation_error(f"{field}.nome", "obrigatório")
            for key, maximum in (("funcao", 128), ("telefone", 64), ("email", 320)):
                try:
                    _validate_text_field(item, key, maximum)
                except NotesImportError as exc:
                    raise _validation_error(f"{field}.{key}", "inválido ou demasiado longo") from exc

    anexos = payload.get("anexos")
    if anexos is not None:
        if not isinstance(anexos, list):
            raise _validation_error("anexos", "esperada lista")
        for index, item in enumerate(anexos):
            field = f"anexos[{index}]"
            if isinstance(item, str):
                if len(item) > 512:
                    raise _validation_error(field, "texto demasiado longo")
            elif isinstance(item, dict):
                for key in ("nome", "name", "filename", "tipo", "mime", "contentType"):
                    if key in item and item[key] is not None and not isinstance(item[key], str):
                        raise _validation_error(f"{field}.{key}", "esperado texto")
                size = item.get("tamanho", item.get("size"))
                if size is not None:
                    _validate_integer(size, f"{field}.tamanho", maximum=100_000_000)
            else:
                raise _validation_error(field, "esperado texto ou objeto")

    unknown_fields = payload.get("camposDesconhecidos")
    if unknown_fields is not None:
        if not isinstance(unknown_fields, list):
            raise _validation_error("camposDesconhecidos", "esperada lista")
        for index, item in enumerate(unknown_fields):
            field = f"camposDesconhecidos[{index}]"
            if not isinstance(item, dict):
                raise _validation_error(field, "esperado objeto")
            if not isinstance(item.get("label"), str) or not item.get("label", "").strip():
                raise _validation_error(f"{field}.label", "esperado texto não vazio")
            if len(item["label"]) > 256:
                raise _validation_error(f"{field}.label", "texto demasiado longo")
            if not isinstance(item.get("value"), str):
                raise _validation_error(f"{field}.value", "esperado texto")
            if len(item["value"]) > 10_000:
                raise _validation_error(f"{field}.value", "texto demasiado longo")

    for key in ("backup", "rgpd"):
        value = payload.get(key)
        if value is not None and not isinstance(value, (bool, str)):
            raise _validation_error(key, "esperado booleano ou texto")
    upac_value = payload.get("upacExistente")
    if upac_value is not None and not isinstance(upac_value, (bool, str)):
        raise _validation_error("upacExistente", "esperado booleano ou texto")


def validate_payload(payload: dict) -> str:
    """Valida tipos, limites e mínimos e devolve a versão do formulário."""
    _validate_payload_types(payload)

    form_version = payload.get("formVersion")
    if not isinstance(form_version, str) or not form_version.strip():
        raise NotesImportError("O payload não indica 'formVersion' — versão do formulário desconhecida.")
    form_version = form_version.strip()
    if form_version not in COMPATIBLE_FORM_VERSIONS:
        raise NotesImportError(
            f"Versão do formulário {form_version!r} não é compatível com este importador "
            f"(versões aceites: {', '.join(sorted(COMPATIBLE_FORM_VERSIONS))})."
        )

    cliente = payload.get("cliente")
    if not isinstance(cliente, str) or not cliente.strip():
        raise NotesImportError("Dados insuficientes para importar: o campo 'cliente' é obrigatório.")
    has_technical_field = any(
        payload.get(key) is not None and payload.get(key) not in ("", [], {})
        for key in ("paineis", "potenciaKwp", "inversores", "baterias")
    )
    if not has_technical_field:
        raise NotesImportError(
            "Dados insuficientes para importar: é preciso pelo menos o nome do cliente e um campo "
            "técnico (painéis, potência, inversores ou baterias). Preencha os campos em falta manualmente."
        )
    return form_version


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NotesImportError("Valor textual inválido durante a normalização.")
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


def _normalize_email(value: str | None) -> str | None:
    return _normalize(value)


def _normalize_phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits or None


def _panel_values(value: object) -> dict:
    if isinstance(value, dict):
        result = dict(value)
        if result.get("quantidade") is not None and result.get("potenciaWp") is not None:
            return result
        description = result.get("descricao")
    else:
        result = {}
        description = value
    if isinstance(description, str):
        values = _numbers(description)
        wp_match = re.search(r"([-+]?\d[\d.,]*)\s*(?:w\s*p|wp)\b", description, re.IGNORECASE)
        if wp_match:
            wp = _parse_number(wp_match.group(1))
            if wp is not None:
                result.setdefault("potenciaWp", wp)
            before = _numbers(description[: wp_match.start()])
            if before:
                result.setdefault("quantidade", _as_int_or_float(before[-1]))
        elif values:
            result.setdefault("quantidade", _as_int_or_float(values[0]))
    return result


def _stringify_schema_value(value: object, *, already_sanitized: bool = False) -> str | None:
    if value in (None, ""):
        return None
    safe_value = value if already_sanitized else _sanitize_payload(value)
    if isinstance(safe_value, (dict, list, tuple)):
        return json.dumps(safe_value, ensure_ascii=False, sort_keys=True)
    return _safe_text(str(safe_value))


def _boolean_schema_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        parsed = _parse_boolean(value)
        return parsed if isinstance(parsed, bool) else None
    return None


def _format_attachment_metadata(value: object) -> str:
    if isinstance(value, dict):
        name = value.get("nome") or value.get("name") or value.get("filename") or "anexo"
        mime = value.get("tipo") or value.get("mime") or value.get("contentType")
        size = value.get("tamanho") or value.get("size")
        details = [str(name)]
        if mime:
            details.append(str(mime))
        if size is not None:
            details.append(f"{size} bytes")
        return f"{details[0]} ({', '.join(details[1:])})" if len(details) > 1 else details[0]
    return _safe_text(str(value))


def map_payload_to_fields(payload: dict, *, already_sanitized: bool = False) -> dict:
    """Traduz notas iniciais para o schema de projeto e dados satélite.

    Valores sem coluna dedicada ficam em `installation.notes`, sempre como
    texto sanitizado. Tabelas de inversores são serializadas como JSON
    determinístico porque a coluna existente é `Text`, e os anexos guardam
    só metadados — nunca o conteúdo de um data URL.
    """
    if not already_sanitized:
        _validate_payload_types(payload)
        sanitized_payload = _sanitize_payload(payload)
    else:
        sanitized_payload = payload
    if not isinstance(sanitized_payload, dict):
        raise NotesImportError("O payload extraído não é um objeto JSON.")
    payload = dict(sanitized_payload)
    # `contactos[0]` é o contacto principal: preenche os campos de topo que
    # faltem (payload JSON/API só com `contactos`), sem sobrepor os explícitos.
    people = payload.get("contactos")
    if isinstance(people, list) and people and isinstance(people[0], dict):
        for source_key, target_key in (
            ("nome", "contacto"),
            ("funcao", "funcao"),
            ("telefone", "telefone"),
            ("email", "email"),
        ):
            if people[0].get(source_key) and not payload.get(target_key):
                payload[target_key] = people[0][source_key]
    paineis = _panel_values(payload.get("paineis"))
    extra_notes_parts: list[str] = []
    for label, key in (
        ("Urgência", "urgencia"),
        ("RGPD", "rgpd"),
        ("Backup", "backup"),
        ("Controlador", "controlador"),
        ("Potência calculada (kWp)", "potenciaKwpCalculada"),
        ("Potência declarada (kWp)", "potenciaKwpDeclarada"),
        ("Outro equipamento", "outroEquipamento"),
        ("UPAC existente", "upacExistente"),
        ("Divergências do Helioscope", "divergenciasHelioscope"),
        ("O que ignorar no Helioscope", "helioscopeIgnorar"),
        ("Pressupostos da proposta", "pressupostosProposta"),
    ):
        value = payload.get(key)
        if value not in (None, ""):
            extra_notes_parts.append(f"{label}: {_safe_text(str(value))}")
    additional_people = []
    for person in (payload.get("contactos") or [])[1:]:
        if not isinstance(person, dict) or not person.get("nome"):
            continue
        details = [
            _safe_text(str(person[key])) for key in ("funcao", "telefone", "email") if person.get(key)
        ]
        label = _safe_text(str(person["nome"]))
        additional_people.append(f"{label} ({'; '.join(details)})" if details else label)
    if additional_people:
        extra_notes_parts.append("Contactos adicionais: " + " | ".join(additional_people))
    anexos = payload.get("anexos") or []
    if anexos:
        if isinstance(anexos, list):
            formatted_attachments = "; ".join(_format_attachment_metadata(item) for item in anexos)
        else:
            formatted_attachments = _format_attachment_metadata(anexos)
        extra_notes_parts.append(f"Anexos: {formatted_attachments}")
    for item in payload.get("camposDesconhecidos") or []:
        if isinstance(item, dict):
            label = _safe_text(str(item.get("label") or "campo desconhecido"))
            value = _safe_text(str(item.get("value") or ""))
            extra_notes_parts.append(f"Campo não mapeado — {label}: {value}")
    observacoes = payload.get("observacoes")
    if observacoes:
        extra_notes_parts.append(_safe_text(str(observacoes)))
    combined_notes = "\n".join(extra_notes_parts)

    project_fields = {
        "client_name": payload.get("cliente"),
        "client_contact": payload.get("contacto"),
        "client_email": _normalize_email(payload.get("email")),
        "address": payload.get("morada"),
        "lat": payload.get("lat"),
        "lon": payload.get("lon"),
        "power_kwp": payload.get("potenciaKwp"),
        "power_raw": payload.get("potenciaKwpRaw"),
        "role": payload.get("funcao"),
        "equipment_notes": payload.get("outroEquipamento"),
        "injection_notes": payload.get("injecao"),
        "om_notes": payload.get("om"),
        "commercial_assumptions": payload.get("pressupostosProposta"),
    }
    installation_fields = {
        "client_nif": payload.get("nif"),
        "contact_person_name": payload.get("contacto"),
        "contact_person_role": payload.get("funcao"),
        "contact_email": _normalize_email(payload.get("email")),
        "contact_phone": _normalize_phone(payload.get("telefone")),
        "address": payload.get("morada"),
        "district": payload.get("distrito"),
        "municipality": payload.get("concelho"),
        "power_kwp": payload.get("potenciaKwp"),
        "panel_count": paineis.get("quantidade"),
        "panel_power_wp": paineis.get("potenciaWp"),
        "inverters": _stringify_schema_value(payload.get("inversores"), already_sanitized=already_sanitized),
        "batteries": _stringify_schema_value(payload.get("baterias"), already_sanitized=already_sanitized),
        "has_backup": _boolean_schema_value(payload.get("backup")),
        "ev_chargers": _stringify_schema_value(payload.get("carregadoresVe"), already_sanitized=already_sanitized),
        "installation_type": payload.get("tipoInstalacao"),
        "injection_type": payload.get("injecao"),
        "om_notes": _stringify_schema_value(payload.get("om"), already_sanitized=already_sanitized),
        "notes": combined_notes,
    }
    licensing_fields = {}
    upac_value = payload.get("upacExistente")
    if isinstance(upac_value, str) and _normalize_label(upac_value) not in {"sim", "nao", "yes", "no"}:
        licensing_fields["upac_number"] = _stringify_schema_value(upac_value, already_sanitized=already_sanitized)

    return {
        "project": {k: v for k, v in project_fields.items() if v not in (None, "")},
        "installation": {k: v for k, v in installation_fields.items() if v not in (None, "")},
        "licensing": {k: v for k, v in licensing_fields.items() if v not in (None, "")},
    }


def find_matching_projects(db: Session, mapped: dict) -> tuple[list[Project], str]:
    """Procura projeto existente por email, depois telefone, depois
    morada normalizada — nunca por nome (D-004). Devolve os candidatos e
    a estratégia usada."""
    email = mapped["project"].get("client_email")
    if email:
        matches = [
            project for project in db.query(Project).filter(Project.client_email.isnot(None)).all()
            if _normalize_email(project.client_email) == _normalize_email(email)
        ]
        if matches:
            return matches, "email"

    phone = mapped["installation"].get("contact_phone")
    if phone:
        matches = [
            project
            for project, installation in db.query(Project, ProjectInstallationData)
            .join(ProjectInstallationData, ProjectInstallationData.project_id == Project.id)
            .all()
            if _normalize_phone(installation.contact_phone) == _normalize_phone(phone)
        ]
        if matches:
            return matches, "phone"

    address = mapped["project"].get("address")
    normalized_address = _normalize(address)
    if normalized_address:
        candidates = db.query(Project).filter(Project.address.isnot(None)).all()
        matches = [p for p in candidates if _normalize(p.address) == normalized_address]
        if matches:
            return matches, "address"

    return [], "none"


def preview_notes_import(
    db: Session, *, filename: str, content: bytes, uploaded_by_person_id: uuid.UUID | None
) -> FieldImportBatch:
    _ensure_clean_import_session(db)
    if len(content) > MAX_UPLOAD_BYTES:
        raise NotesImportError(f"Ficheiro demasiado grande (máximo {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    _validate_filename(filename)
    lower_name = filename.lower()
    if not any(lower_name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise NotesImportError(f"Extensão não permitida — use {', '.join(sorted(ALLOWED_EXTENSIONS))}.")

    file_hash = compute_file_hash(content)
    existing = db.query(FieldImportBatch).filter(FieldImportBatch.source_file_hash == file_hash).one_or_none()
    if existing is not None:
        if existing.status == BATCH_STATUS_APPLIED:
            raise DuplicateImportError(
                f"Este ficheiro já foi importado (lote {existing.id}, aplicado em {existing.applied_at})."
            )
        # Ainda não aplicado (pending_confirmation/rejected): devolve o
        # lote já existente em vez de duplicar — preview é idempotente
        # pelo hash do ficheiro.
        return existing

    payload = extract_payload(filename=filename, content=content)
    try:
        form_version = validate_payload(payload)
        sanitized_payload = _sanitize_payload(payload)
        if not isinstance(sanitized_payload, dict):
            raise NotesImportError("O payload extraído não é um objeto JSON.")
        # Redaction must happen before either normalized representation is stored.
        validate_payload(sanitized_payload)
        mapped = map_payload_to_fields(sanitized_payload, already_sanitized=True)
        if not isinstance(mapped, dict):
            raise NotesImportError("Não foi possível normalizar o payload de importação.")
        raw_document_text = _serialize_safe_payload(sanitized_payload, already_sanitized=True)
        raw_payload_json = raw_document_text
    except NotesImportError:
        raise
    except (ValueError, OverflowError, RecursionError, TypeError) as exc:
        raise NotesImportError("Dados importados inválidos ou demasiado complexos.") from exc
    candidates, strategy = find_matching_projects(db, mapped)

    source_type = SOURCE_TYPE_NOTES_JSON if lower_name.endswith(".json") else SOURCE_TYPE_NOTES_HTML
    batch = FieldImportBatch(
        source_type=source_type,
        source_filename=_redact_text(filename),
        source_file_hash=file_hash,
        form_version=form_version,
        raw_payload_json=raw_payload_json,
        raw_document_text=raw_document_text,
        status=BATCH_STATUS_PENDING_CONFIRMATION,
        started_by_person_id=uploaded_by_person_id,
    )
    try:
        with db.begin_nested():
            db.add(batch)
            db.flush()

        is_new = len(candidates) == 0
        target_project = candidates[0] if len(candidates) == 1 else None
        record = FieldImportRecord(
            batch_id=batch.id,
            target_project_id=target_project.id if target_project else None,
            is_new_project=is_new,
            match_strategy="ambiguous" if len(candidates) > 1 else strategy,
            candidate_project_ids_json=json.dumps([str(p.id) for p in candidates]),
            mapped_fields_json=_serialize_safe_payload(mapped, already_sanitized=True),
        )
        db.add(record)
        db.flush()

        if target_project is not None:
            _create_conflicts_for_record(db, record=record, target_project=target_project, mapped=mapped)

        db.flush()
        db.refresh(batch)
        return batch
    except IntegrityError as exc:
        existing = db.query(FieldImportBatch).filter(FieldImportBatch.source_file_hash == file_hash).one_or_none()
        if existing is None:
            raise NotesImportError("Não foi possível guardar o lote de importação.") from exc
        if existing.status == BATCH_STATUS_APPLIED:
            raise DuplicateImportError(
                f"Este ficheiro já foi importado (lote {existing.id}, aplicado em {existing.applied_at})."
            )
        return existing


def _create_conflicts_for_record(
    db: Session, *, record: FieldImportRecord, target_project: Project, mapped: dict
) -> None:
    existing_keys = {(conflict.target_entity, conflict.field_name) for conflict in record.conflicts}
    for target_entity, fields in _mapped_target_fields(mapped):
        target = _target_entity(db, target_project.id, target_entity)
        for field_name, new_value in fields.items():
            old_value = getattr(target, field_name, None) if target is not None else None
            if not _values_equal(old_value, new_value) and (target_entity, field_name) not in existing_keys:
                db.add(
                    FieldImportConflict(
                        record_id=record.id,
                        target_entity=target_entity,
                        field_name=field_name,
                        old_value=_conflict_value(old_value),
                        new_value=_conflict_value(new_value),
                    )
                )


def _mapped_target_fields(mapped: dict):
    for target_entity in ("project", "installation", "licensing"):
        yield target_entity, mapped.get(target_entity, {})


def _target_entity(db: Session, project_id: uuid.UUID, target_entity: str, *, lock: bool = False):
    model = {
        "installation": ProjectInstallationData,
        "licensing": ProjectLicensingData,
    }.get(target_entity)
    if model is None:
        query = db.query(Project).populate_existing().filter(Project.id == project_id)
        if lock and db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        return query.one_or_none()
    query = db.query(model).populate_existing().filter(model.project_id == project_id)
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    return query.one_or_none()


def _conflict_value(value: object) -> str | None:
    return None if value is None else str(value)


def _values_equal(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, str):
        try:
            return math.isfinite(float(left)) and math.isfinite(float(right)) and float(left) == float(right)
        except (TypeError, ValueError, OverflowError):
            return False
    if isinstance(right, (int, float)) and not isinstance(right, bool) and isinstance(left, str):
        try:
            return math.isfinite(float(left)) and math.isfinite(float(right)) and float(left) == float(right)
        except (TypeError, ValueError, OverflowError):
            return False
    return str(left) == str(right)


class BatchNotFoundError(NotesImportError):
    pass


def _lock_pending_batch(db: Session, batch_id: uuid.UUID) -> FieldImportBatch:
    """Serialize resolve/apply on the batch row on both supported dialects."""
    if db.get_bind().dialect.name == "postgresql":
        batch = db.execute(
            select(FieldImportBatch)
            .where(FieldImportBatch.id == batch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if batch is None:
            raise BatchNotFoundError("Lote de importação não encontrado.")
        if batch.status != BATCH_STATUS_PENDING_CONFIRMATION:
            raise NotesImportError(f"Lote já processado (estado atual: {batch.status!r}).")
        return batch

    # SQLite has no row-level FOR UPDATE. A conditional no-op UPDATE starts a
    # write transaction and therefore serializes the following read/mutation.
    result = db.execute(
        update(FieldImportBatch)
        .where(
            FieldImportBatch.id == batch_id,
            FieldImportBatch.status == BATCH_STATUS_PENDING_CONFIRMATION,
        )
        .values(status=BATCH_STATUS_PENDING_CONFIRMATION)
    )
    db.flush()
    if result.rowcount != 1:
        current = (
            db.query(FieldImportBatch)
            .populate_existing()
            .filter(FieldImportBatch.id == batch_id)
            .one_or_none()
        )
        if current is None:
            raise BatchNotFoundError("Lote de importação não encontrado.")
        raise NotesImportError(f"Lote já processado (estado atual: {current.status!r}).")
    return db.query(FieldImportBatch).populate_existing().filter(FieldImportBatch.id == batch_id).one()


def _revalidate_record_target(
    db: Session, *, record: FieldImportRecord, target_project: Project, mapped: dict
) -> bool:
    """Persist new/stale conflicts and report whether the state changed."""
    conflicts = {
        (c.target_entity, c.field_name): c
        for c in db.query(FieldImportConflict)
        .populate_existing()
        .filter(FieldImportConflict.record_id == record.id)
        .all()
    }
    changed = False
    for target_entity, fields in _mapped_target_fields(mapped):
        target = target_project if target_entity == "project" else _target_entity(
            db, target_project.id, target_entity, lock=True
        )
        for field_name, new_value in fields.items():
            current_value = getattr(target, field_name, None) if target is not None else None
            conflict = conflicts.get((target_entity, field_name))
            if conflict is not None and not _values_equal(current_value, conflict.old_value):
                conflict.old_value = _conflict_value(current_value)
                conflict.new_value = _conflict_value(new_value)
                conflict.resolution = CONFLICT_RESOLUTION_PENDING
                conflict.resolved_by_person_id = None
                conflict.resolved_at = None
                changed = True
            elif conflict is None and not _values_equal(current_value, new_value):
                db.add(
                    FieldImportConflict(
                        record_id=record.id,
                        target_entity=target_entity,
                        field_name=field_name,
                        old_value=_conflict_value(current_value),
                        new_value=_conflict_value(new_value),
                    )
                )
                changed = True
    return changed


def resolve_conflict(
    db: Session, *, conflict: FieldImportConflict, resolution: str, resolved_by_person_id: uuid.UUID | None
) -> FieldImportConflict:
    _ensure_clean_import_session(db)
    if resolution not in (CONFLICT_RESOLUTION_USE_NEW, CONFLICT_RESOLUTION_KEEP_OLD):
        raise NotesImportError(f"Resolução inválida: {resolution!r}.")
    batch_id = db.query(FieldImportRecord.batch_id).filter(FieldImportRecord.id == conflict.record_id).scalar()
    if batch_id is None:
        raise NotesImportError("Conflito sem lote de importação.")
    _lock_pending_batch(db, batch_id)
    conflict_query = db.query(FieldImportConflict).populate_existing().filter(FieldImportConflict.id == conflict.id)
    if db.get_bind().dialect.name == "postgresql":
        conflict_query = conflict_query.with_for_update()
    conflict = conflict_query.one_or_none()
    if conflict is None:
        raise NotesImportError("Conflito não encontrado.")
    # The batch lock makes this check and the decision one transaction: an
    # apply that already committed cannot be followed by a late resolution.
    conflict.resolution = resolution
    conflict.resolved_by_person_id = resolved_by_person_id
    conflict.resolved_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.refresh(conflict)
    return conflict


def apply_notes_import(
    db: Session,
    *,
    batch: FieldImportBatch,
    target_project_id: uuid.UUID | None,
    applied_by_person_id: uuid.UUID | None,
) -> Project:
    """Apply one locked, fully revalidated pending import transactionally."""
    _ensure_clean_import_session(db)
    batch = _lock_pending_batch(db, batch.id)
    record = (
        db.query(FieldImportRecord)
        .populate_existing()
        .filter(FieldImportRecord.batch_id == batch.id)
        .one_or_none()
    )
    if record is None:
        db.flush()
        raise NotesImportError("Lote sem registo — nada para aplicar.")

    try:
        candidate_ids = {uuid.UUID(value) for value in json.loads(record.candidate_project_ids_json or "[]")}
        mapped = json.loads(record.mapped_fields_json)
    except (json.JSONDecodeError, ValueError, OverflowError, RecursionError, TypeError) as exc:
        raise NotesImportError("Dados de staging inválidos — o lote não pode ser aplicado.") from exc
    if not isinstance(mapped, dict):
        raise NotesImportError("Dados de staging inválidos — o mapeamento não é um objeto.")

    if target_project_id is not None and target_project_id not in candidate_ids:
        db.flush()
        raise NotesImportError("target_project_id não pertence aos candidatos da correspondência")

    selected_target = target_project_id or record.target_project_id
    conflict_resolutions: dict[tuple[str, str], str] = {}
    if record.match_strategy == "ambiguous":
        if selected_target is None:
            db.flush()
            raise NotesImportError(
                "Vários projetos correspondem a estes dados — indique target_project_id explicitamente."
            )
        if selected_target not in candidate_ids:
            db.flush()
            raise NotesImportError("target_project_id não pertence aos candidatos da correspondência")
        if record.target_project_id is not None and selected_target != record.target_project_id:
            db.flush()
            raise NotesImportError("O alvo desta importação ambígua já foi selecionado explicitamente.")
        if record.target_project_id is None:
            record.target_project_id = selected_target
            target_project = db.query(Project).filter(Project.id == selected_target).one_or_none()
            if target_project is None:
                raise NotesImportError("Projeto alvo não encontrado.")
            _create_conflicts_for_record(db, record=record, target_project=target_project, mapped=mapped)
            db.flush()
            db.flush()
            raise ImportPendingStateError(
                "Alvo selecionado; foram gerados conflitos específicos desse projeto. "
                "Resolva-os antes de aplicar."
            )

    if record.is_new_project and selected_target is None:
        project = Project(name=mapped["project"].get("client_name") or "Projeto sem nome (importação)")
        for field_name, value in mapped["project"].items():
            setattr(project, field_name, value)
        db.add(project)
        db.flush()
    else:
        if selected_target is None:
            db.flush()
            raise NotesImportError("Projeto alvo não encontrado.")
        project_query = db.query(Project).populate_existing().filter(Project.id == selected_target)
        if db.get_bind().dialect.name == "postgresql":
            project_query = project_query.with_for_update()
        project = project_query.one_or_none()
        if project is None:
            db.flush()
            raise NotesImportError("Projeto alvo não encontrado.")

        _revalidate_record_target(db, record=record, target_project=project, mapped=mapped)
        db.flush()
        pending = (
            db.query(FieldImportConflict)
            .filter(
                FieldImportConflict.record_id == record.id,
                FieldImportConflict.resolution == CONFLICT_RESOLUTION_PENDING,
            )
            .all()
        )
        if pending:
            db.flush()
            raise ImportPendingStateError(
                f"Existem {len(pending)} conflito(s) por resolver contra o estado atual — resolva-os antes de aplicar."
            )

        conflict_resolutions = {
            (c.target_entity, c.field_name): c.resolution
            for c in db.query(FieldImportConflict)
            .populate_existing()
            .filter(FieldImportConflict.record_id == record.id)
            .all()
        }
        for field_name, new_value in mapped.get("project", {}).items():
            if conflict_resolutions.get(("project", field_name)) == CONFLICT_RESOLUTION_KEEP_OLD:
                continue
            old_value = getattr(project, field_name, None)
            if _values_equal(old_value, new_value):
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=_conflict_value(old_value),
                new_value=_conflict_value(new_value),
                source="import_notes",
                changed_by_person_id=applied_by_person_id,
                note=f"Importação de notas iniciais (lote {batch.id}).",
            )
            setattr(project, field_name, new_value)

    db.flush()
    installation_changes = {
        field_name: value
        for field_name, value in mapped.get("installation", {}).items()
        if conflict_resolutions.get(("installation", field_name)) != CONFLICT_RESOLUTION_KEEP_OLD
    } if not (record.is_new_project and selected_target is None) else dict(mapped.get("installation", {}))
    if installation_changes:
        upsert_installation_data(
            db,
            project_id=project.id,
            changes=installation_changes,
            changed_by_person_id=applied_by_person_id,
            source="import_notes",
            commit=False,
        )

    licensing_changes = {
        field_name: value
        for field_name, value in mapped.get("licensing", {}).items()
        if conflict_resolutions.get(("licensing", field_name)) != CONFLICT_RESOLUTION_KEEP_OLD
    } if not (record.is_new_project and selected_target is None) else dict(mapped.get("licensing", {}))
    if licensing_changes:
        upsert_licensing_data(
            db,
            project_id=project.id,
            changes=licensing_changes,
            changed_by_person_id=applied_by_person_id,
            source="import_notes",
            commit=False,
        )

    record.status = RECORD_STATUS_APPLIED
    record.promoted_project_id = project.id
    batch.status = BATCH_STATUS_APPLIED
    batch.applied_by_person_id = applied_by_person_id
    batch.applied_at = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.refresh(project)
    return project
