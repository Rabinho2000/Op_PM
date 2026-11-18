"""Importação do Excel de licenciamento — layout "SIM card Numbers Projects" (`sim_v1`).

Folha "Dados gerais": notas soltas nas linhas 1-7, cabeçalho na linha 8, dados a
partir da linha 9, colunas POSICIONAIS; folha "Venda do excedente": cabeçalho na
linha 1, ligação ao projeto por nome normalizado. Ver
app/services/imports_licensing.py (secção "Layout SIM card Numbers Projects") e
app/cli/import_licensing.py.

Tudo aqui é sintético: os ficheiros .xlsx são gerados com openpyxl em `tmp_path`
(nunca o Excel real) e os segredos são valores fictícios inconfundíveis
(`FAKEPWD-…`, `FAKEPUK-…`, `XX-0000000NN`, PIN `99NN`). A chave Fernet também é
gerada em `tmp_path`. As verificações de "nada vaza" usam sempre esse conjunto de
valores fictícios (`FAKE_VALUES`, construído a partir das constantes do módulo).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from openpyxl import Workbook
from sqlalchemy import event

from app.cli import import_licensing as cli
from app.config import Settings
from app.db import engine
from app.models.imports import FieldImportBatch, FieldImportConflict, FieldImportRecord
from app.models.project import Project, ProjectExternalId, ProjectHistory
from app.models.project_data import (
    ProjectDataHistory,
    ProjectLicensingData,
    ProjectPortalCredential,
    ProjectSimCard,
    ProjectSurplusContract,
)
from app.security.secret_box import encrypt_secret
import app.services.imports_licensing as imports_licensing_service
from app.services.imports_licensing import (
    LicensingImportError,
    _sim_identifier,
    apply_sim_import,
    compute_file_hash,
    detect_layout,
    dry_run_sim_import,
    parse_sim_layout,
    rollback_licensing_batch,
)
from app.services.project_data import derive_licensing_state, update_sim_card

LEGACY_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_licensing.xlsx"

# `ProjectExternalId.source_system` que liga o nº de projeto do Excel (prefixo numérico da nomenclatura
# Solcor) ao projeto, e o do layout legado (fallback só se a nomenclatura não casar de todo).
NOMENCLATURE_SOURCE = "solcor_nomenclatura_xlsx"
LEGACY_SOURCE = "legacy_excel_licensing"

# --- dados fictícios -----------------------------------------------------------------------------
# Convenção: PHONE_/ICCID_/PIN_/PUK_/USERNAME_/PASSWORD_/EMAIL_ — todos entram em
# FAKE_VALUES (ver abaixo) e NUNCA podem aparecer em stdout/stderr/relatório/logs.

NUM_A, NUM_B, NUM_ORPHAN = "5001", "5002", "5999"
NAME_A, NAME_B = "Projeto Sintético SIM A", "Projeto Sintético SIM B"

PHONE_A1, ICCID_A1, PIN_A1, PUK_A1 = "910000001", "8935100000000001001", "9911", "FAKEPUK-A1"
PHONE_A2, ICCID_A2, PIN_A2, PUK_A2 = "910000002", "8935100000000001002", "9922", "FAKEPUK-A2"
USERNAME_A, PASSWORD_A, EMAIL_A = "XX-000000001", "FAKEPWD-123", "fake.login.a@example.invalid"

PHONE_B1, ICCID_B1, PIN_B1, PUK_B1 = "910000003", "8935100000000001003", "9933", "FAKEPUK-B1"
USERNAME_B, PASSWORD_B, EMAIL_B = "XX-000000002", "FAKEPWD-456", "fake.login.b@example.invalid"

PHONE_X1, ICCID_X1, PIN_X1, PUK_X1 = "910000009", "8935100000000001009", "9944", "FAKEPUK-X1"
USERNAME_X, PASSWORD_X, EMAIL_X = "XX-000000009", "FAKEPWD-999", "fake.login.x@example.invalid"

# valores só usados nos cenários de conflito / células numéricas
OLD_PIN, OLD_PASSWORD, OLD_USERNAME = "FAKEOLDPIN-1", "FAKEPWD-OLD", "XX-000000007"
OLD_EMAIL = "fake.antigo@example.invalid"
PIN_NUM, PUK_NUM, PASSWORD_NUM, PHONE_NUM = 7733, 55667788, 246810, 910000004

_FAKE_PREFIXES = ("PHONE_", "ICCID_", "PIN_", "PUK_", "USERNAME_", "PASSWORD_", "EMAIL_", "OLD_")
FAKE_VALUES: dict[str, str] = {
    name: str(value) for name, value in globals().items() if name.startswith(_FAKE_PREFIXES) and not callable(value)
}

# Só os segredos propriamente ditos (PIN/PUK/password): são os únicos que NUNCA podem estar em claro
# na base (histórico, payload do lote). Telefone/ICCID/email não são segredos e o histórico
# regista-os legitimamente quando preenche um campo.
SECRET_VALUES: dict[str, str] = {
    name: value
    for name, value in FAKE_VALUES.items()
    if name.startswith(("PIN_", "PUK_", "PASSWORD_", "OLD_PIN", "OLD_PASSWORD"))
}

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
# Digests hexadecimais (ex.: SHA-256 do ficheiro no histórico): como os UUIDs, podem conter por
# acaso os 4 dígitos de um PIN fictício sem que isso seja uma fuga.
_HEX_DIGEST = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)

# --- construção do .xlsx sintético ---------------------------------------------------------------

# coluna 0-based -> cabeçalho (linha 8). As colunas 0, 1, 2, 7 e 12 não têm texto fixo no
# mapeamento (são "(nº projeto)", "(nome)", "(operador SIM 1)", "(operador SIM 2)", "(notas)").
HEADERS: dict[int, str] = {
    0: "Nº Projeto",
    1: "Nome do projeto",
    2: "Operador",
    3: "Numero",
    4: "Card (conferido com site NOS)",
    5: "PIN",
    6: "PUK",
    7: "Dados Móveis (Card Verde)",
    8: "Numero",
    9: "Cod. Barras",
    10: "PIN",
    11: "PUK",
    12: "Notas registo",
    13: "Login Geral",
    14: "Password",
    15: "UPAC - Registo",
    16: "DATA - Registo",
    17: "UPAC - Cadastro",
    18: "DATA cadastro",
    19: "DATA pedido certificação",
    20: "Entidade Inspetora",
    21: "Data Inspeção",
    22: "Data Certificado",
    23: "E-mail",
    25: "kWp",
}
FIELD_COLUMN: dict[str, int] = {
    "numero_projeto": 0,
    "nome": 1,
    "operador_1": 2,
    "telefone_1": 3,
    "iccid_1": 4,
    "pin_1": 5,
    "puk_1": 6,
    "operador_2": 7,
    "telefone_2": 8,
    "iccid_2": 9,
    "pin_2": 10,
    "puk_2": 11,
    "notas_registo": 12,
    "login": 13,
    "password": 14,
    "upac_registo": 15,
    "data_registo": 16,
    "upac_cadastro": 17,
    "data_cadastro": 18,
    "data_pedido": 19,
    "entidade": 20,
    "data_inspecao": 21,
    "certificado": 22,
    "email": 23,
    "kwp": 25,
}
SURPLUS_HEADERS = [
    "PROJECT",
    "Comercializador",
    "Tipo de Contrato",
    "Envio do Contrato",
    "Ass. do Contrato",
    "Envio p/ Comercializador",
    "Situação",
    "Duração (Mês)",
    "Data Inicio",
    "Data Final",
    "Observação",
]


def row(**fields) -> dict[int, object]:
    """Linha de dados da folha 'Dados gerais' por nome de campo -> {coluna 0-based: valor}."""
    return {FIELD_COLUMN[name]: value for name, value in fields.items()}


def surplus_row(
    project,
    *,
    commercializer="Comercializador Fictício",
    contract_type="Venda de excedente",
    sent=dt.datetime(2021, 5, 1),
    signed="10/05/2021",
    sent_to_commercializer=dt.datetime(2021, 5, 12),
    status="Em vigor",
    months=24,
    start: object = dt.datetime(2021, 6, 1),
    end: object = dt.datetime(2023, 6, 1),
    notes="Observação fictícia",
) -> list:
    return [project, commercializer, contract_type, sent, signed, sent_to_commercializer, status, months, start, end, notes]


def build_workbook(
    path: Path,
    rows: list[dict[int, object]],
    *,
    surplus: list[list] | None = None,
    header_overrides: dict[int, str | None] | None = None,
    header_row: int = 8,
    sheet1: bool = False,
    surplus_header: list[str] | None = None,
) -> Path:
    """Reproduz o layout real: notas soltas nas linhas 1-7 (com linhas em branco no meio,
    para provar que a numeração de linhas não desalinha), cabeçalho na linha `header_row`,
    dados logo abaixo; 'Venda do excedente' com cabeçalho na linha 1."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados gerais"
    for note_row in (1, 3, 6):
        ws.cell(row=note_row, column=1, value=f"Nota solta fictícia (linha {note_row}) — a ignorar")
    ws.cell(row=5, column=4, value="outra nota solta fictícia")
    headers = {**HEADERS, **(header_overrides or {})}
    for column, text in headers.items():
        if text is not None:
            ws.cell(row=header_row, column=column + 1, value=text)
    for offset, data in enumerate(rows):
        for column, value in data.items():
            if value is not None:
                ws.cell(row=header_row + 1 + offset, column=column + 1, value=value)
    if surplus is not None:
        sheet = wb.create_sheet("Venda do excedente")
        sheet.append(surplus_header if surplus_header is not None else SURPLUS_HEADERS)
        for srow in surplus:
            sheet.append(srow)
    if sheet1:
        sheet = wb.create_sheet("Sheet1")
        sheet.append(["Project_number", "Project_name", "Internal_reference"])
        sheet.append([NUM_A, NAME_A, "REF-SIM-A"])
    wb.save(path)
    return path


def std_rows() -> list[dict[int, object]]:
    return [
        # linha 9 — projeto A: 2 SIM, login geral, licenciamento completo, certificado definitivo
        row(
            numero_projeto=NUM_A,
            nome="Nome A (só conferência)",
            operador_1="NOS",
            telefone_1=PHONE_A1,
            iccid_1=ICCID_A1,
            pin_1=PIN_A1,
            puk_1=PUK_A1,
            operador_2="Vodafone",
            telefone_2=PHONE_A2,
            iccid_2=ICCID_A2,
            pin_2=PIN_A2,
            puk_2=PUK_A2,
            login=USERNAME_A,
            password=PASSWORD_A,
            email=EMAIL_A,
            upac_registo="UPAC-REG-0001",
            data_registo=dt.datetime(2021, 3, 10),
            upac_cadastro="CAD-0001",
            data_cadastro="15/03/2021",
            data_pedido="01/04/2021",
            entidade="Entidade Inspetora Fictícia",
            data_inspecao=dt.datetime(2021, 4, 20),
            certificado="Cert. 03/05/2021",
            kwp=9.5,
        ),
        # linha 10 — projeto B: só SIM 1, sem login, certificado provisório (sem data)
        row(
            numero_projeto=NUM_B,
            nome="Nome B (só conferência)",
            operador_1="NOS",
            telefone_1=PHONE_B1,
            iccid_1=ICCID_B1,
            pin_1=PIN_B1,
            puk_1=PUK_B1,
            upac_registo="UPAC-REG-0002",
            certificado="Certificado provisorio",
        ),
        # linha 11 — nº de projeto que não existe na plataforma
        row(
            numero_projeto=NUM_ORPHAN,
            operador_1="Vodafone",
            telefone_1=PHONE_X1,
            iccid_1=ICCID_X1,
            pin_1=PIN_X1,
            puk_1=PUK_X1,
            login=USERNAME_X,
            password=PASSWORD_X,
            email=EMAIL_X,
        ),
    ]


def std_surplus() -> list[list]:
    return [
        surplus_row("  PROJETO SINTETICO   sim a "),  # linha 2: igual a NAME_A depois de normalizar
        surplus_row("Projeto Inexistente Sintético"),  # linha 3: sem correspondência
    ]


# --- helpers de plataforma / execução ------------------------------------------------------------


def nomenclature(number: str, client: str = "Cliente Fictício", suffix: str = "") -> str:
    """`external_id` da nomenclatura Solcor, como nos projetos reais:
    '<nº>_<nome>_<tipo>_<empresa>_PV' (às vezes com sufixo ' - UPAC 2'). Nomes fictícios."""
    return f"{number}_{client}_ESCO_Empresa Fictícia_PV{suffix}"


def make_project(
    db,
    name: str,
    number: str | None = None,
    *,
    active: bool = True,
    external_id: str | None = None,
    source: str = NOMENCLATURE_SOURCE,
) -> Project:
    """Projeto fictício + ligação como nos projetos reais: `ProjectExternalId` da nomenclatura
    (`solcor_nomenclatura_xlsx`, `external_id` = '<nº>_<nome>_<tipo>_<empresa>_PV'). Com `number`
    gera a nomenclatura; com `external_id`/`source` escolhe-se o registo exato (cenários especiais).
    `commit()` porque o dry-run do CLI faz `rollback()` à sessão."""
    project = Project(name=name, is_active=active)
    db.add(project)
    db.flush()
    if external_id is None and number is not None:
        external_id = nomenclature(number, name)
    if external_id is not None:
        db.add(ProjectExternalId(project_id=project.id, source_system=source, external_id=external_id))
    db.commit()
    return project


def apply(db, settings, path: Path, **kwargs):
    return apply_sim_import(
        db, filename=path.name, content=path.read_bytes(), settings=settings, applied_by_person_id=None, **kwargs
    )


def dry_run(db, settings, path: Path):
    return dry_run_sim_import(db, content=path.read_bytes(), settings=settings)


def active_sims(db, project) -> list[ProjectSimCard]:
    return (
        db.query(ProjectSimCard)
        .filter(ProjectSimCard.project_id == project.id, ProjectSimCard.deleted_at.is_(None))
        .order_by(ProjectSimCard.purpose)
        .all()
    )


def active_credentials(db, project) -> list[ProjectPortalCredential]:
    return (
        db.query(ProjectPortalCredential)
        .filter(ProjectPortalCredential.project_id == project.id, ProjectPortalCredential.deleted_at.is_(None))
        .all()
    )


def active_surplus(db, project) -> list[ProjectSurplusContract]:
    return (
        db.query(ProjectSurplusContract)
        .filter(ProjectSurplusContract.project_id == project.id, ProjectSurplusContract.deleted_at.is_(None))
        .all()
    )


def licensing_of(db, project) -> ProjectLicensingData | None:
    return db.query(ProjectLicensingData).filter(ProjectLicensingData.project_id == project.id).one_or_none()


_COUNTED_MODELS = (
    ProjectSimCard,
    ProjectPortalCredential,
    ProjectLicensingData,
    ProjectSurplusContract,
    ProjectDataHistory,
    ProjectHistory,
    FieldImportBatch,
    FieldImportRecord,
    FieldImportConflict,
)


def table_counts(db) -> dict[str, int]:
    return {model.__name__: db.query(model).count() for model in _COUNTED_MODELS}


@contextlib.contextmanager
def capture_dml():
    """Regista todo o INSERT/UPDATE/DELETE emitido contra a base (só o tipo e a tabela — nunca
    parâmetros). Prova mais forte do que comparar contagens: apanha também escritas desfeitas."""
    statements: list[str] = []
    pattern = re.compile(r"^\s*(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+(\w+)", re.IGNORECASE)

    def _listener(conn, cursor, statement, parameters, context, executemany):
        match = pattern.match(statement)
        if match:
            statements.append(f"{' '.join(match.group(1).upper().split())} {match.group(2)}")

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


def assert_no_fake_values(*texts: str, tmp_path: Path | None = None, only_secrets: bool = False) -> None:
    """Nenhum valor fictício (segredo, username, email, telefone, ICCID) em `texts` — ou só os
    segredos, com `only_secrets=True` (para dados que a base guarda legitimamente, como o
    histórico). Os UUIDs (nº de lote) e o caminho de `tmp_path` são retirados antes: um PIN de 4
    dígitos pode coincidir por acaso com 4 hex de um UUID, e isso não é uma fuga."""
    forbidden = SECRET_VALUES if only_secrets else FAKE_VALUES
    for text in texts:
        scrubbed = _HEX_DIGEST.sub("<digest>", _UUID.sub("<uuid>", text))
        if tmp_path is not None:
            scrubbed = scrubbed.replace(str(tmp_path), "<tmp>")
        leaked = sorted(name for name, value in forbidden.items() if value in scrubbed)
        assert not leaked, f"valores fictícios apareceram na saída: {leaked}"


def run_cli(capsys, *args) -> tuple[int, str, str]:
    code = cli.main([str(arg) for arg in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- fixtures ------------------------------------------------------------------------------------


@pytest.fixture()
def fernet_key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture()
def key_file(tmp_path: Path, fernet_key: bytes) -> Path:
    path = tmp_path / "secrets.key"
    path.write_text(fernet_key.decode("ascii") + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def settings(key_file: Path) -> Settings:
    return Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=str(key_file))


@pytest.fixture()
def no_key_settings() -> Settings:
    return Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file="")


@pytest.fixture()
def decrypt(fernet_key: bytes):
    fernet = Fernet(fernet_key)
    return lambda token: fernet.decrypt(token.encode("ascii")).decode("utf-8")


@pytest.fixture()
def projects(db_session) -> SimpleNamespace:
    return SimpleNamespace(
        a=make_project(db_session, NAME_A, NUM_A),
        b=make_project(db_session, NAME_B, NUM_B),
    )


@pytest.fixture()
def std_file(tmp_path: Path) -> Path:
    # Pasta chamada "fixtures": o CLI não aplica a barreira anti-git a fixtures sintéticas.
    return build_workbook(tmp_path / "fixtures" / "sim.xlsx", std_rows(), surplus=std_surplus())


@pytest.fixture()
def cli_env(monkeypatch, db_session, settings):
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)


def preexisting_conflicting_state(db, settings, project) -> SimpleNamespace:
    """Estado prévio do projeto A que diverge do Excel standard em campos já preenchidos."""
    db.add(
        ProjectLicensingData(
            project_id=project.id,
            upac_number="UPAC-PRE-EXISTENTE",  # difere do Excel -> conflito
            inspecting_entity="Entidade Inspetora Fictícia",  # igual -> nada a fazer
        )
    )
    sim_1 = ProjectSimCard(
        project_id=project.id,
        purpose="comunicacoes",
        operator="Operador Antigo",  # difere -> conflito
        phone_number=None,  # vazio -> preenche
        iccid=ICCID_A1,
        notes="",
        pin_encrypted=encrypt_secret(settings, OLD_PIN),  # difere -> conflito
        puk_encrypted=None,  # vazio -> preenche
    )
    sim_2 = ProjectSimCard(  # igual ao Excel -> já existente
        project_id=project.id,
        purpose="dados_moveis",
        operator="Vodafone",
        phone_number=PHONE_A2,
        iccid=ICCID_A2,
        notes="",
        pin_encrypted=encrypt_secret(settings, PIN_A2),
        puk_encrypted=encrypt_secret(settings, PUK_A2),
    )
    credential = ProjectPortalCredential(
        project_id=project.id,
        portal="dgeg_login_geral",
        username=USERNAME_A,
        email=OLD_EMAIL,  # difere -> conflito
        password_encrypted=encrypt_secret(settings, OLD_PASSWORD),  # difere -> conflito
    )
    db.add_all([sim_1, sim_2, credential])
    db.commit()
    return SimpleNamespace(sim_1=sim_1, sim_2=sim_2, credential=credential)


# ===============================================================================================
# 1) dry-run não escreve nada na BD
# ===============================================================================================


@pytest.mark.parametrize("with_key", [True, False], ids=["com-chave", "sem-chave"])
def test_dry_run_writes_nothing_and_does_not_need_the_key(
    db_session, projects, std_file, settings, no_key_settings, with_key
):
    active = settings if with_key else no_key_settings
    before = table_counts(db_session)
    with capture_dml() as statements:
        report = dry_run(db_session, active, std_file)
    assert statements == []
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert table_counts(db_session) == before

    db_session.rollback()  # e continua igual depois de qualquer rollback
    assert table_counts(db_session) == before

    data = report.to_dict()
    assert data["modo"] == "dry-run" and data["layout"] == "sim_v1"
    assert data["lote"] is None and data["ja_importado"] is False
    # prevê o que o apply faria
    assert data["contagens"]["sim_1"] == {"criados": 2}
    assert data["contagens"]["sim_2"] == {"criados": 1}
    assert data["contagens"]["credencial_login_geral"] == {"criados": 1}
    assert data["contagens"]["licenciamento"] == {"criados": 2}
    assert data["contagens"]["excedente"] == {"criados": 1, "por_ligar": 1}


def test_cli_dry_run_writes_nothing_and_exits_zero(db_session, projects, std_file, cli_env, capsys):
    before = table_counts(db_session)
    with capture_dml() as statements:
        code, out, err = run_cli(capsys, "--file", std_file, "--dry-run")
    assert code == 0, err
    assert statements == []
    assert table_counts(db_session) == before
    assert "Dry-run (layout SIM)" in out and "nada foi escrito" in out
    assert "Projetos encontrados: 2" in out and "Projetos não encontrados: 1" in out
    assert "Lote:" not in out  # dry-run nunca cria lote


def test_dry_run_report_matches_what_apply_then_does(db_session, projects, std_file, settings):
    """O dry-run tem de prever exatamente o que o apply faz sobre o mesmo estado."""
    preexisting_conflicting_state(db_session, settings, projects.a)
    predicted = dry_run(db_session, settings, std_file).to_dict()
    applied = apply(db_session, settings, std_file).to_dict()
    for key in (
        "contagens",
        "conflitos",
        "avisos",
        "linhas_invalidas",
        "excedente_por_ligar",
        "projetos_encontrados",
        "projetos_nao_encontrados",
        "projetos_ambiguos",
        "colunas_ignoradas",
    ):
        assert predicted[key] == applied[key], key


# ===============================================================================================
# 2) stdout + relatório JSON (e logs) sem segredos, usernames, emails
# ===============================================================================================


def _rich_file(tmp_path: Path) -> Path:
    """Ficheiro com todos os caminhos de reporte: conflito, avisos, linhas inválidas, projeto
    não encontrado, excedente por ligar, células numéricas, identificador com perda de precisão."""
    rows = [
        row(  # linha 9 — A: PIN/PUK/password como números (aviso), data inválida, certificado ilegível
            numero_projeto=NUM_A,
            operador_1="NOS",
            telefone_1=PHONE_A1,
            iccid_1=ICCID_A1,
            pin_1=PIN_NUM,
            puk_1=PUK_NUM,
            login=USERNAME_A,
            password=PASSWORD_NUM,
            email=EMAIL_A,
            upac_registo="UPAC-REG-0001",
            data_registo="31/02/2021",
            certificado="pendente",
        ),
        row(  # linha 10 — B: telefone numérico, ICCID numérico com perda de precisão
            numero_projeto=NUM_B,
            operador_1="Vodafone",
            telefone_1=PHONE_NUM,
            iccid_1=8.935100000000001e18,
            pin_1=PIN_B1,
            puk_1=PUK_B1,
            certificado="Certificado provisorio",
        ),
        row(  # linha 11 — sem nº de projeto mas com segredos
            operador_1="NOS", telefone_1=PHONE_X1, pin_1=PIN_X1, puk_1=PUK_X1, login=USERNAME_X, password=PASSWORD_X
        ),
        row(  # linha 12 — projeto inexistente
            numero_projeto=NUM_ORPHAN, login=USERNAME_X, password=PASSWORD_X, email=EMAIL_X, telefone_1=PHONE_X1
        ),
        row(  # linha 13 — login em falta mas com password e email
            numero_projeto=NUM_A, password=PASSWORD_B, email=EMAIL_B
        ),
    ]
    return build_workbook(tmp_path / "fixtures" / "rica.xlsx", rows, surplus=std_surplus(), sheet1=True)


def test_cli_output_and_report_never_contain_secrets_usernames_or_emails(
    db_session, projects, settings, cli_env, capsys, caplog, tmp_path
):
    caplog.set_level(logging.DEBUG)
    preexisting_conflicting_state(db_session, settings, projects.a)
    path = _rich_file(tmp_path)

    outputs: list[str] = []
    for mode in ("--dry-run", "--apply", "--apply"):  # o 2.º --apply cai em "já importado"
        report_path = tmp_path / f"relatorio{len(outputs)}.json"
        code, out, err = run_cli(capsys, "--file", path, mode, "--report", report_path)
        assert code == 0, err
        outputs += [out, err, report_path.read_text(encoding="utf-8")]
        json.loads(outputs[-1])  # relatório é JSON válido
    assert_no_fake_values(*outputs, caplog.text, tmp_path=tmp_path)

    # o relatório sem valores ainda diz o essencial: onde (linha/coluna/campo) e quantos
    report = json.loads(outputs[2])
    assert report["linhas_invalidas"], "esperava linhas inválidas no ficheiro rico"
    assert report["avisos"] and report["conflitos"] and report["projetos_nao_encontrados"] == [NUM_ORPHAN]
    for conflict in report["conflitos"]:
        assert set(conflict) == {"linha", "bloco", "campo"}
    for invalid in report["linhas_invalidas"]:
        assert set(invalid) == {"linha", "coluna", "motivo"}
    assert report["colunas_ignoradas"] == [] or all(re.fullmatch(r"[A-Z]{1,3}", c) for c in report["colunas_ignoradas"])


def test_error_paths_do_not_echo_cell_values(db_session, projects, no_key_settings, monkeypatch, capsys, tmp_path):
    # aborta por falta de chave (há segredos) e por layout/folha inválidos: mensagem sem valores
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: no_key_settings)
    good = build_workbook(tmp_path / "fixtures" / "ok.xlsx", std_rows(), surplus=std_surplus())
    bad_header = build_workbook(
        tmp_path / "fixtures" / "cabecalho.xlsx", std_rows(), header_overrides={14: "Senha", 3: "Num"}
    )
    bad_surplus = build_workbook(
        tmp_path / "fixtures" / "excedente.xlsx", std_rows(), surplus=[["x"]], surplus_header=["foo", "bar"]
    )
    bad_surplus_sheet = tmp_path / "fixtures" / "excedente2.xlsx"
    bad_surplus_sheet.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.active.title = "Dados gerais"
    wb.save(bad_surplus_sheet)

    collected: list[str] = []
    for path in (good, bad_header, bad_surplus, bad_surplus_sheet):
        for mode in ("--dry-run", "--apply"):
            code, out, err = run_cli(capsys, "--file", path, mode)
            collected += [out, err]
            assert "Traceback" not in out + err
    assert_no_fake_values(*collected, tmp_path=tmp_path)


# ===============================================================================================
# 3) apply cria SIMs (2 por linha), PIN/PUK cifrados, credencial cifrada, datas de licenciamento/UPAC
# ===============================================================================================


def test_apply_creates_sims_credential_and_licensing(db_session, projects, std_file, settings, decrypt):
    content = std_file.read_bytes()
    before = table_counts(db_session)
    report = apply(db_session, settings, std_file)
    a, b = projects.a, projects.b

    # --- SIMs: 2 na linha A (ambos os blocos preenchidos), 1 na linha B (só SIM 1)
    sims_a = active_sims(db_session, a)
    assert [(s.purpose, s.operator, s.phone_number, s.iccid) for s in sims_a] == [
        ("comunicacoes", "NOS", PHONE_A1, ICCID_A1),
        ("dados_moveis", "Vodafone", PHONE_A2, ICCID_A2),
    ]
    sims_b = active_sims(db_session, b)
    assert [(s.purpose, s.operator, s.phone_number, s.iccid) for s in sims_b] == [
        ("comunicacoes", "NOS", PHONE_B1, ICCID_B1)
    ]

    # --- PIN/PUK cifrados em repouso (Fernet): nunca em claro, decifram para o valor original
    expected = {
        (a.id, "comunicacoes"): (PIN_A1, PUK_A1),
        (a.id, "dados_moveis"): (PIN_A2, PUK_A2),
        (b.id, "comunicacoes"): (PIN_B1, PUK_B1),
    }
    for sim in sims_a + sims_b:
        pin, puk = expected[(sim.project_id, sim.purpose)]
        for token, clear in ((sim.pin_encrypted, pin), (sim.puk_encrypted, puk)):
            assert token and token != clear and clear not in token
            assert decrypt(token) == clear
        assert sim.notes == "" and sim.deleted_at is None

    # --- credencial Login Geral (DGEG) só no projeto A; password cifrada
    credentials = active_credentials(db_session, a)
    assert len(credentials) == 1
    credential = credentials[0]
    assert (credential.portal, credential.username, credential.email) == ("dgeg_login_geral", USERNAME_A, EMAIL_A)
    assert credential.password_encrypted and credential.password_encrypted != PASSWORD_A
    assert PASSWORD_A not in credential.password_encrypted
    assert decrypt(credential.password_encrypted) == PASSWORD_A
    assert active_credentials(db_session, b) == []

    # --- licenciamento/UPAC (datas lidas como data do Excel e como texto dd/mm/aaaa)
    lic_a = licensing_of(db_session, a)
    assert lic_a.upac_number == "UPAC-REG-0001"
    assert lic_a.upac_registration_date == dt.date(2021, 3, 10)
    assert lic_a.cadastro_number == "CAD-0001"
    assert lic_a.registration_date == dt.date(2021, 3, 15)
    assert lic_a.certification_request_date == dt.date(2021, 4, 1)
    assert lic_a.inspecting_entity == "Entidade Inspetora Fictícia"
    assert lic_a.inspection_date == dt.date(2021, 4, 20)
    assert lic_a.certificate_date == dt.date(2021, 5, 3)
    assert derive_licensing_state(lic_a) == "certificado_definitivo"
    lic_b = licensing_of(db_session, b)
    assert lic_b.upac_number == "UPAC-REG-0002"

    # --- nada para o projeto que não existe; nenhuma escrita em Project
    after = table_counts(db_session)
    assert after["ProjectSimCard"] - before["ProjectSimCard"] == 3
    assert after["ProjectPortalCredential"] - before["ProjectPortalCredential"] == 1
    assert after["ProjectLicensingData"] - before["ProjectLicensingData"] == 2
    assert after["ProjectSurplusContract"] - before["ProjectSurplusContract"] == 1
    assert after["ProjectHistory"] == before["ProjectHistory"]
    assert after["FieldImportBatch"] - before["FieldImportBatch"] == 1

    # --- lote + relatório
    batch = db_session.get(FieldImportBatch, report.batch_id)
    assert (batch.status, batch.source_type, batch.source_filename) == ("applied", "licensing_excel", "sim.xlsx")
    assert batch.source_file_hash == compute_file_hash(content)
    assert json.loads(batch.raw_payload_json) == {"layout": "sim_v1", "ignored_columns": ["B", "Z"]}

    data = report.to_dict()
    assert data["modo"] == "apply" and data["lote"] == str(batch.id) and data["ja_importado"] is False
    assert data["projetos_encontrados"] == 2 and data["projetos_nao_encontrados"] == [NUM_ORPHAN]
    assert data["contagens"] == {
        "sim_1": {"criados": 2},
        "sim_2": {"criados": 1},
        "credencial_login_geral": {"criados": 1},
        "licenciamento": {"criados": 2},
        "excedente": {"criados": 1, "por_ligar": 1},
    }
    assert data["conflitos"] == [] and data["linhas_invalidas"] == []
    assert data["colunas_ignoradas"] == ["B", "Z"]  # nome (só conferência) e kWp (fora de âmbito)


def test_apply_history_and_batch_never_hold_plaintext_secrets(db_session, projects, std_file, settings):
    report = apply(db_session, settings, std_file)
    batch = db_session.get(FieldImportBatch, report.batch_id)
    history = db_session.query(ProjectDataHistory).filter(ProjectDataHistory.source == "import_licensing").all()
    assert history, "o apply tem de auditar o que cria"
    assert all(h.note == f"Importação do Excel de licenciamento (lote {batch.id})." for h in history)
    dump = json.dumps(
        [[h.entity_type, h.field_name, h.old_value, h.new_value, h.note] for h in history]
        + [batch.raw_payload_json, batch.raw_document_text],
        ensure_ascii=False,
    )
    assert_no_fake_values(dump, only_secrets=True)
    # o histórico só diz que os segredos foram definidos
    markers = {(h.entity_type, h.field_name, h.new_value) for h in history}
    assert ("sim", "secrets", "[definido]") in markers
    assert ("credential", "password", "[definida]") in markers


# ===============================================================================================
# 4) 2.º apply não duplica
# ===============================================================================================


def test_second_apply_of_same_file_does_not_duplicate(db_session, projects, std_file, settings, cli_env, capsys):
    first = apply(db_session, settings, std_file)
    after_first = table_counts(db_session)

    with capture_dml() as statements:
        second = apply(db_session, settings, std_file)
    assert statements == []
    assert second.already_imported is True and second.batch_id == first.batch_id
    assert table_counts(db_session) == after_first

    # igual pelo CLI: sai com 0, diz que já foi aplicado e não escreve
    code, out, err = run_cli(capsys, "--file", std_file, "--apply")
    assert code == 0, err
    assert "já foi aplicado" in out
    assert table_counts(db_session) == after_first


def test_second_apply_of_a_different_file_with_same_data_does_not_duplicate(
    db_session, projects, tmp_path, settings
):
    first_file = build_workbook(tmp_path / "fixtures" / "v1.xlsx", std_rows(), surplus=std_surplus())
    apply(db_session, settings, first_file)
    after_first = table_counts(db_session)

    # outro ficheiro (hash diferente: muda só uma nota solta e o nome de conferência) com os mesmos dados
    rows = std_rows()
    rows[0][FIELD_COLUMN["nome"]] = "Nome A alterado (só conferência)"
    second_file = build_workbook(tmp_path / "fixtures" / "v2.xlsx", rows, surplus=std_surplus())
    assert compute_file_hash(first_file.read_bytes()) != compute_file_hash(second_file.read_bytes())

    second = apply(db_session, settings, second_file)
    after_second = table_counts(db_session)
    for model in ("ProjectSimCard", "ProjectPortalCredential", "ProjectLicensingData", "ProjectSurplusContract"):
        assert after_second[model] == after_first[model], model
    assert after_second["ProjectDataHistory"] == after_first["ProjectDataHistory"]
    assert after_second["FieldImportBatch"] == after_first["FieldImportBatch"] + 1

    counts = second.to_dict()["contagens"]
    assert counts["sim_1"] == {"ja_existentes": 2}
    assert counts["sim_2"] == {"ja_existentes": 1}
    assert counts["credencial_login_geral"] == {"ja_existentes": 1}
    assert counts["licenciamento"] == {"ja_existentes": 2}
    assert counts["excedente"] == {"ja_existentes": 1, "por_ligar": 1}
    assert second.to_dict()["conflitos"] == []


# ===============================================================================================
# 5) campo já preenchido com valor diferente: não sobrescreve, aparece como conflito
# ===============================================================================================


def test_conflicting_fields_are_reported_and_never_overwritten(db_session, projects, std_file, settings, decrypt):
    state = preexisting_conflicting_state(db_session, settings, projects.a)
    report = apply(db_session, settings, std_file)
    data = report.to_dict()

    # --- relatório: só (linha, bloco, campo) — nenhum valor
    assert {(c["linha"], c["bloco"], c["campo"]) for c in data["conflitos"]} == {
        (9, "sim_1", "operator"),
        (9, "sim_1", "pin"),
        (9, "credencial_login_geral", "email"),
        (9, "credencial_login_geral", "password"),
        (9, "licenciamento", "upac_number"),
    }
    assert all(set(c) == {"linha", "bloco", "campo"} for c in data["conflitos"])
    assert data["contagens"]["sim_1"]["conflitos"] == 2
    assert data["contagens"]["sim_2"] == {"ja_existentes": 1}
    assert data["contagens"]["credencial_login_geral"]["conflitos"] == 2
    assert data["contagens"]["licenciamento"]["conflitos"] == 1

    # --- nada foi sobrescrito
    db_session.refresh(state.sim_1)
    assert state.sim_1.operator == "Operador Antigo"
    assert decrypt(state.sim_1.pin_encrypted) == OLD_PIN
    db_session.refresh(state.credential)
    assert state.credential.email == OLD_EMAIL
    assert decrypt(state.credential.password_encrypted) == OLD_PASSWORD
    lic = licensing_of(db_session, projects.a)
    assert lic.upac_number == "UPAC-PRE-EXISTENTE"

    # --- campos vazios continuam a ser preenchidos (conflito num campo não bloqueia os outros)
    assert state.sim_1.phone_number == PHONE_A1
    assert decrypt(state.sim_1.puk_encrypted) == PUK_A1
    assert lic.upac_registration_date == dt.date(2021, 3, 10) and lic.certificate_date == dt.date(2021, 5, 3)
    assert lic.inspecting_entity == "Entidade Inspetora Fictícia"

    # --- sem duplicados: continua a haver exatamente 2 SIMs e 1 credencial em A
    assert len(active_sims(db_session, projects.a)) == 2
    assert len(active_credentials(db_session, projects.a)) == 1


def test_conflicts_are_reported_by_dry_run_without_writing(db_session, projects, std_file, settings):
    preexisting_conflicting_state(db_session, settings, projects.a)
    before = table_counts(db_session)
    with capture_dml() as statements:
        data = dry_run(db_session, settings, std_file).to_dict()
    assert statements == [] and table_counts(db_session) == before
    assert (9, "sim_1", "pin") in {(c["linha"], c["bloco"], c["campo"]) for c in data["conflitos"]}


def test_other_username_in_dgeg_is_a_conflict_not_a_second_credential(db_session, projects, settings, tmp_path, decrypt):
    other = ProjectPortalCredential(
        project_id=projects.b.id,
        portal="dgeg_login_geral",
        username=OLD_USERNAME,
        email=None,
        password_encrypted=encrypt_secret(settings, OLD_PASSWORD),
    )
    db_session.add(other)
    db_session.commit()
    rows = [row(numero_projeto=NUM_B, login=USERNAME_B, password=PASSWORD_B, email=EMAIL_B)]
    path = build_workbook(tmp_path / "fixtures" / "login.xlsx", rows)

    data = apply(db_session, settings, path).to_dict()

    assert [(c["linha"], c["bloco"], c["campo"]) for c in data["conflitos"]] == [(9, "credencial_login_geral", "username")]
    credentials = active_credentials(db_session, projects.b)
    assert [c.username for c in credentials] == [OLD_USERNAME]
    assert decrypt(credentials[0].password_encrypted) == OLD_PASSWORD
    assert credentials[0].email is None


# ===============================================================================================
# 6) sem chave de cifra e com segredos -> aborta sem escrever nada
# ===============================================================================================


def _key_variants(tmp_path: Path) -> dict[str, Settings]:
    garbage = tmp_path / "lixo.key"
    garbage.write_text("isto-nao-e-uma-chave-fernet\n", encoding="utf-8")
    return {
        "sem-chave-configurada": Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=""),
        "ficheiro-inexistente": Settings(
            app_env="test", auth_enabled=False, oppm_secrets_key_file=str(tmp_path / "nao-existe.key")
        ),
        "chave-invalida": Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=str(garbage)),
    }


@pytest.mark.parametrize("variant", ["sem-chave-configurada", "ficheiro-inexistente", "chave-invalida"])
def test_apply_without_usable_key_and_with_secrets_aborts_without_writing(
    db_session, projects, std_file, tmp_path, variant
):
    broken = _key_variants(tmp_path)[variant]
    before = table_counts(db_session)
    with capture_dml() as statements:
        with pytest.raises(LicensingImportError) as raised:
            apply(db_session, broken, std_file)
    message = str(raised.value)
    assert "OPPM_SECRETS_KEY_FILE" in message and "Nada foi gravado" in message
    assert statements == []
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert table_counts(db_session) == before
    assert db_session.query(FieldImportBatch).filter_by(source_file_hash=compute_file_hash(std_file.read_bytes())).count() == 0
    assert_no_fake_values(message, tmp_path=tmp_path)


def test_cli_apply_without_key_exits_1_and_writes_nothing(
    db_session, projects, std_file, no_key_settings, monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: no_key_settings)
    before = table_counts(db_session)
    report_path = tmp_path / "relatorio.json"
    with capture_dml() as statements:
        code, out, err = run_cli(capsys, "--file", std_file, "--apply", "--report", report_path)
    assert code == 1
    assert err.startswith("ERRO:") and "OPPM_SECRETS_KEY_FILE" in err and "Nada foi gravado" in err
    assert statements == [] and table_counts(db_session) == before
    assert not report_path.exists()
    assert_no_fake_values(out, err, tmp_path=tmp_path)


def test_apply_without_key_is_fine_when_the_file_has_no_secrets(db_session, projects, no_key_settings, tmp_path):
    rows = [row(numero_projeto=NUM_A, operador_1="NOS", telefone_1=PHONE_A1, iccid_1=ICCID_A1, upac_registo="UPAC-REG-0001")]
    path = build_workbook(tmp_path / "fixtures" / "sem_segredos.xlsx", rows)
    apply(db_session, no_key_settings, path)
    (sim,) = active_sims(db_session, projects.a)
    assert (sim.phone_number, sim.iccid) == (PHONE_A1, ICCID_A1)
    assert sim.pin_encrypted is None and sim.puk_encrypted is None


def test_secrets_of_projects_not_on_the_platform_do_not_require_the_key(db_session, no_key_settings, tmp_path):
    # só há segredos numa linha cujo projeto não existe -> nada a gravar -> não exige chave
    path = build_workbook(tmp_path / "fixtures" / "orfao.xlsx", [std_rows()[2]])
    report = apply(db_session, no_key_settings, path)
    assert report.to_dict()["projetos_nao_encontrados"] == [NUM_ORPHAN]


# ===============================================================================================
# 7) certificado: 'Cert. dd/mm/aaaa' -> definitivo com data; 'Certificado provisorio' -> sem data + aviso
# ===============================================================================================


@pytest.mark.parametrize(
    ("cell", "expected_date", "outcome"),
    [
        ("Cert. 03/05/2021", dt.date(2021, 5, 3), "ok"),
        ("  cert.   3/5/2021 ", dt.date(2021, 5, 3), "ok"),
        (dt.datetime(2021, 5, 3), dt.date(2021, 5, 3), "ok"),
        ("Certificado provisorio", None, "aviso"),
        ("Certificado provisório", None, "aviso"),
        ("Cert. 31/02/2021", None, "invalida"),
        ("pendente", None, "invalida"),
        ("-", None, "vazio"),
        (None, None, "vazio"),
    ],
)
def test_certificate_cell_parsing(tmp_path, cell, expected_date, outcome):
    path = build_workbook(
        tmp_path / "fixtures" / "cert.xlsx", [row(numero_projeto=NUM_A, upac_registo="UPAC-REG-0001", certificado=cell)]
    )
    parsed = parse_sim_layout(path.read_bytes())
    (sim_row,) = parsed.rows
    assert sim_row.licensing.get("certificate_date") == expected_date
    assert "provisional_certificate_date" not in sim_row.licensing
    at_cert_cell = lambda items: [i for i in items if i.get("linha") == 9 and i.get("coluna") == "W"]  # noqa: E731
    assert bool(at_cert_cell(parsed.warnings)) == (outcome == "aviso")
    assert bool(at_cert_cell(parsed.invalid)) == (outcome == "invalida")
    if outcome == "aviso":
        assert "provis" in at_cert_cell(parsed.warnings)[0]["aviso"]


def test_certificate_definitive_gets_a_date_and_provisional_gets_none_plus_warning(
    db_session, projects, std_file, settings
):
    report = apply(db_session, settings, std_file)
    definitive = licensing_of(db_session, projects.a)
    provisional = licensing_of(db_session, projects.b)
    assert definitive.certificate_date == dt.date(2021, 5, 3)
    assert derive_licensing_state(definitive) == "certificado_definitivo"
    assert provisional.certificate_date is None and provisional.provisional_certificate_date is None
    warnings = report.to_dict()["avisos"]
    assert [(w["linha"], w["coluna"]) for w in warnings] == [(10, "W")]
    assert "provis" in warnings[0]["aviso"]
    assert report.to_dict()["linhas_invalidas"] == []


# ===============================================================================================
# 8) excedente: sem correspondência -> 'por ligar' (não grava); correspondência exata normalizada -> grava
# ===============================================================================================


def _surplus_scenario(db) -> None:
    make_project(db, NAME_A, NUM_A)
    make_project(db, "Projeto Sintético SIM Inativo", "5003", active=False)
    make_project(db, "Projeto Sintético SIM Repetido", "5004")
    make_project(db, "projeto sintetico  sim REPETIDO", "5005")


def _surplus_workbook(tmp_path: Path) -> Path:
    return build_workbook(
        tmp_path / "fixtures" / "excedente.xlsx",
        [row(numero_projeto=NUM_A)],
        surplus=[
            surplus_row("  PROJETO SINTETICO   sim a "),  # linha 2: igual depois de normalizar -> grava
            surplus_row("Projeto Inexistente Sintético"),  # linha 3: sem correspondência
            surplus_row("Projeto Sintético SIM A (extra)"),  # linha 4: só parte do nome -> não é exato
            surplus_row("Projeto Sintético SIM Inativo"),  # linha 5: projeto inativo
            surplus_row("Projeto Sintético SIM Repetido"),  # linha 6: dois projetos com o mesmo nome
            surplus_row(None),  # linha 7: sem nome
            surplus_row("Projeto Sintético SIM A", start="amanhã"),  # linha 8: data inválida
            surplus_row("projeto sintético sim a"),  # linha 9: repete a linha 2 no ficheiro
        ],
    )


def test_surplus_writes_only_exact_normalized_matches_and_leaves_the_rest_unlinked(db_session, settings, tmp_path):
    _surplus_scenario(db_session)
    project = db_session.query(Project).filter(Project.name == NAME_A).one()
    path = _surplus_workbook(tmp_path)
    before = table_counts(db_session)

    report = apply(db_session, settings, path)
    data = report.to_dict()

    # grava só a correspondência exata normalizada, com todos os campos
    assert table_counts(db_session)["ProjectSurplusContract"] - before["ProjectSurplusContract"] == 1
    (contract,) = active_surplus(db_session, project)
    assert contract.commercializer == "Comercializador Fictício"
    assert contract.contract_type == "Venda de excedente"
    assert contract.contract_sent_date == dt.date(2021, 5, 1)
    assert contract.signed_received_date == dt.date(2021, 5, 10)
    assert contract.sent_to_commercializer_date == dt.date(2021, 5, 12)
    assert contract.status == "Em vigor"
    assert contract.duration_months == 24
    assert contract.start_date == dt.date(2021, 6, 1) and contract.end_date == dt.date(2023, 6, 1)
    assert contract.notes == "Observação fictícia"
    history = (
        db_session.query(ProjectDataHistory)
        .filter(ProjectDataHistory.entity_type == "surplus", ProjectDataHistory.record_id == contract.id)
        .all()
    )
    assert {(h.field_name, h.source) for h in history} == {
        ("created", "import_licensing"),
        ("__rollback_guard__", "import_licensing"),
    }

    # as restantes ficam 'por ligar' — reportadas por linha, sem gravar nada
    unlinked = {item["linha"]: item["motivo"] for item in data["excedente_por_ligar"]}
    assert sorted(unlinked) == [3, 4, 5, 6]
    assert "sem projeto" in unlinked[3] and "sem projeto" in unlinked[4] and "sem projeto" in unlinked[5]
    assert "ambíguo" in unlinked[6]
    assert data["contagens"]["excedente"] == {"criados": 1, "por_ligar": 4, "duplicado_no_ficheiro": 1}
    # linhas 7 (sem nome) e 8 (data inválida) são inválidas e não se gravam
    assert {(i["linha"], i["coluna"]) for i in data["linhas_invalidas"]} == {(7, "A"), (8, "I")}
    # nenhum outro projeto recebeu contratos
    assert (
        db_session.query(ProjectSurplusContract).filter(ProjectSurplusContract.project_id != project.id).count()
        == before["ProjectSurplusContract"]
    )


def test_surplus_dry_run_reports_the_same_and_writes_nothing(db_session, settings, tmp_path):
    _surplus_scenario(db_session)
    path = _surplus_workbook(tmp_path)
    before = table_counts(db_session)
    with capture_dml() as statements:
        data = dry_run(db_session, settings, path).to_dict()
    assert statements == [] and table_counts(db_session) == before
    assert data["contagens"]["excedente"] == {"criados": 1, "por_ligar": 4, "duplicado_no_ficheiro": 1}
    assert [item["linha"] for item in data["excedente_por_ligar"]] == [3, 4, 5, 6]


# ===============================================================================================
# 9) layout desconhecido -> erro claro (e nada gravado)
# ===============================================================================================


def _unrecognized_workbooks(tmp_path: Path) -> dict[str, tuple[Path, str]]:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    unrelated = fixtures / "outro.xlsx"
    wb = Workbook()
    wb.active.title = "Folha qualquer"
    wb.active.append(["a", "b", "c"])
    wb.save(unrelated)
    not_excel = fixtures / "nao_e_excel.xlsx"
    not_excel.write_bytes(b"isto nao e um zip nem um xlsx")
    empty_data = build_workbook(fixtures / "sem_dados.xlsx", [])
    return {
        # cabeçalho SIM com colunas que não batem (>=2 sinais do layout SIM, mas O e D falham)
        "coluna-nao-bate": (
            build_workbook(fixtures / "coluna.xlsx", std_rows(), header_overrides={14: "Senha", 3: "Num"}),
            "Layout SIM não reconhecido",
        ),
        # cabeçalho uma linha acima do esperado (linha 7 em vez de 8)
        "cabecalho-deslocado": (
            build_workbook(fixtures / "deslocado.xlsx", std_rows(), header_row=7),
            "linha 8",
        ),
        "folha-excedente-sem-cabecalho": (
            build_workbook(fixtures / "exc.xlsx", std_rows(), surplus=[["x", "y"]], surplus_header=["foo", "bar"]),
            "Venda do excedente",
        ),
        "outro-ficheiro-excel": (unrelated, "layout"),
        "nao-e-excel": (not_excel, "Não foi possível ler o ficheiro Excel"),
        "sem-linhas-de-dados": (empty_data, "nenhuma linha"),
    }


@pytest.mark.parametrize(
    "variant",
    [
        "coluna-nao-bate",
        "cabecalho-deslocado",
        "folha-excedente-sem-cabecalho",
        "outro-ficheiro-excel",
        "nao-e-excel",
        "sem-linhas-de-dados",
    ],
)
@pytest.mark.parametrize("mode", ["--dry-run", "--apply"])
def test_unknown_layout_is_a_clear_error_and_writes_nothing(
    db_session, projects, cli_env, capsys, tmp_path, variant, mode
):
    path, expected_fragment = _unrecognized_workbooks(tmp_path)[variant]
    before = table_counts(db_session)
    with capture_dml() as statements:
        code, out, err = run_cli(capsys, "--file", path, mode)
    assert code == 1
    assert err.startswith("ERRO:") and expected_fragment.lower() in err.lower()
    assert "Traceback" not in out + err and "Importação aplicada" not in out
    assert statements == [] and table_counts(db_session) == before
    assert_no_fake_values(out, err, tmp_path=tmp_path)


def test_unrecognized_sim_header_names_the_offending_columns(tmp_path):
    path = build_workbook(tmp_path / "fixtures" / "c.xlsx", std_rows(), header_overrides={14: "Senha", 3: "Num"})
    with pytest.raises(LicensingImportError) as raised:
        parse_sim_layout(path.read_bytes())
    assert "colunas D, O" in str(raised.value) and "linha 8" in str(raised.value)


# ===============================================================================================
# 10) rollback do lote remove o que criou (e só isso)
# ===============================================================================================


def _visible_state(db, *projects) -> dict:
    """Tudo o que a plataforma 'vê' (registos ativos, valores de licenciamento) dos projetos dados."""
    ids = [p.id for p in projects]
    sims = sorted(
        (str(s.id), s.purpose, s.operator, s.phone_number, s.iccid, s.pin_encrypted, s.puk_encrypted)
        for s in db.query(ProjectSimCard).filter(ProjectSimCard.project_id.in_(ids), ProjectSimCard.deleted_at.is_(None))
    )
    credentials = sorted(
        (str(c.id), c.portal, c.username, c.email, c.password_encrypted)
        for c in db.query(ProjectPortalCredential).filter(
            ProjectPortalCredential.project_id.in_(ids), ProjectPortalCredential.deleted_at.is_(None)
        )
    )
    surplus = sorted(
        (str(c.id), c.commercializer, str(c.start_date))
        for c in db.query(ProjectSurplusContract).filter(
            ProjectSurplusContract.project_id.in_(ids), ProjectSurplusContract.deleted_at.is_(None)
        )
    )
    licensing = {}
    for lic in db.query(ProjectLicensingData).filter(ProjectLicensingData.project_id.in_(ids)):
        values = {
            column.name: getattr(lic, column.name)
            for column in ProjectLicensingData.__table__.columns
            if column.name not in ("id", "project_id", "created_at", "updated_at")
            and getattr(lic, column.name) not in (None, "")
        }
        if values:
            licensing[str(lic.project_id)] = values
    return {"sims": sims, "credentials": credentials, "surplus": surplus, "licensing": licensing}


def _rollback_scenario(db, settings, tmp_path) -> tuple[SimpleNamespace, Path]:
    a = make_project(db, NAME_A, NUM_A)
    b = make_project(db, NAME_B, NUM_B)
    # B já tem um SIM (mesmo ICCID) com operador mas sem PIN/PUK: o lote só os preenche
    pre_sim = ProjectSimCard(
        project_id=b.id, purpose="comunicacoes", operator="NOS", phone_number=None, iccid=ICCID_B1, notes=""
    )
    db.add(pre_sim)
    db.commit()
    path = build_workbook(tmp_path / "fixtures" / "sim.xlsx", std_rows(), surplus=std_surplus())
    return SimpleNamespace(a=a, b=b, pre_sim=pre_sim), path


def test_rollback_removes_what_the_batch_created_and_keeps_the_rest(db_session, settings, tmp_path):
    ns, path = _rollback_scenario(db_session, settings, tmp_path)
    state_before = _visible_state(db_session, ns.a, ns.b)
    assert state_before["sims"][0][5] is None  # o SIM pré-existente de B ainda sem PIN

    report = apply(db_session, settings, path)
    state_applied = _visible_state(db_session, ns.a, ns.b)
    assert state_applied != state_before
    assert len(active_sims(db_session, ns.a)) == 2 and len(active_surplus(db_session, ns.a)) == 1
    db_session.refresh(ns.pre_sim)
    assert ns.pre_sim.pin_encrypted and ns.pre_sim.puk_encrypted and ns.pre_sim.phone_number == PHONE_B1

    history_ids_before_rollback = {h.id for h in db_session.query(ProjectDataHistory).all()}
    batch = db_session.get(FieldImportBatch, report.batch_id)
    reverted = rollback_licensing_batch(db_session, batch=batch)
    assert reverted > 0

    assert batch.status == "rejected"
    # o que o lote criou desapareceu; o que já existia ficou como estava antes do lote
    assert _visible_state(db_session, ns.a, ns.b) == state_before
    db_session.refresh(ns.pre_sim)
    assert (ns.pre_sim.operator, ns.pre_sim.iccid, ns.pre_sim.deleted_at) == ("NOS", ICCID_B1, None)
    assert ns.pre_sim.pin_encrypted is None and ns.pre_sim.puk_encrypted is None and ns.pre_sim.phone_number is None

    # SIMs/credencial criados ficam removidos logicamente e SEM segredos guardados
    removed_sims = db_session.query(ProjectSimCard).filter(
        ProjectSimCard.project_id == ns.a.id, ProjectSimCard.deleted_at.is_not(None)
    )
    assert removed_sims.count() == 2
    assert all(s.pin_encrypted is None and s.puk_encrypted is None for s in removed_sims)
    removed_credentials = db_session.query(ProjectPortalCredential).filter(
        ProjectPortalCredential.project_id == ns.a.id, ProjectPortalCredential.deleted_at.is_not(None)
    )
    assert removed_credentials.count() == 1 and removed_credentials[0].password_encrypted is None
    assert db_session.query(ProjectSurplusContract).filter(
        ProjectSurplusContract.project_id == ns.a.id, ProjectSurplusContract.deleted_at.is_not(None)
    ).count() == 1

    # histórico só cresce (append-only) e o rollback fica registado
    history_after = db_session.query(ProjectDataHistory).all()
    assert history_ids_before_rollback <= {h.id for h in history_after}
    assert any((h.note or "").startswith(f"Rollback do lote {batch.id}") for h in history_after)
    assert_no_fake_values(
        json.dumps([[h.old_value, h.new_value, h.note] for h in history_after], ensure_ascii=False), only_secrets=True
    )


def test_rollback_twice_and_reapplying_a_rolled_back_file_fail_with_clear_errors(db_session, settings, tmp_path):
    ns, path = _rollback_scenario(db_session, settings, tmp_path)
    report = apply(db_session, settings, path)
    batch = db_session.get(FieldImportBatch, report.batch_id)
    rollback_licensing_batch(db_session, batch=batch)

    with pytest.raises(LicensingImportError, match="aplicado"):
        rollback_licensing_batch(db_session, batch=batch)
    with pytest.raises(LicensingImportError, match="rejected"):
        apply(db_session, settings, path)


def test_cli_rollback_of_a_sim_batch(db_session, settings, tmp_path, cli_env, capsys):
    ns, path = _rollback_scenario(db_session, settings, tmp_path)
    state_before = _visible_state(db_session, ns.a, ns.b)
    code, out, err = run_cli(capsys, "--file", path, "--apply")
    assert code == 0, err
    batch_id = re.search(r"Lote: (\S+)", out).group(1)

    code, out, err = run_cli(capsys, "--rollback", batch_id)
    assert code == 0, err
    assert "revertido" in out
    assert _visible_state(db_session, ns.a, ns.b) == state_before
    assert db_session.get(FieldImportBatch, uuid.UUID(batch_id)).status == "rejected"


# ===============================================================================================
# 11) o layout legado continua a funcionar (test_import_licensing_cli.py) + deteção de layout
# ===============================================================================================


def test_detect_layout_distinguishes_sim_from_legacy(std_file):
    assert detect_layout(std_file.read_bytes()) == "sim_v1"
    assert detect_layout(LEGACY_FIXTURE.read_bytes()) == "legacy"


def test_confirmed_real_sim_headers_are_detected_and_keep_their_column_meanings(tmp_path):
    path = build_workbook(
        tmp_path / "fixtures" / "cabecalho_real_sintetico.xlsx",
        std_rows(),
        header_overrides={4: "Cod. Barras", 13: "Username", 22: "Data Cetificado"},
    )
    content = path.read_bytes()

    assert detect_layout(content) == "sim_v1"
    parsed = parse_sim_layout(content)
    first = parsed.rows[0]
    assert first.sims[0]["iccid"] == ICCID_A1
    assert first.credential["username"] == USERNAME_A
    assert first.licensing["certificate_date"] == dt.date(2021, 5, 3)


@pytest.mark.parametrize(
    ("column", "header", "column_letter"),
    [
        (4, "Barcode", "E"),
        (13, "User name", "N"),
        (22, "Data Cetificad", "W"),
    ],
)
def test_sim_header_aliases_reject_unknown_near_matches(tmp_path, column, header, column_letter):
    path = build_workbook(
        tmp_path / "fixtures" / f"cabecalho_desconhecido_{column}.xlsx",
        std_rows(),
        header_overrides={column: header},
    )

    with pytest.raises(LicensingImportError) as raised:
        parse_sim_layout(path.read_bytes())

    assert f"colunas {column_letter}" in str(raised.value)


def test_legacy_fixture_still_goes_through_the_legacy_importer(db_session, capsys):
    code, out, err = run_cli(capsys, "--file", LEGACY_FIXTURE, "--dry-run")
    assert code == 0, err
    assert "Dry-run" in out and "layout SIM" not in out
    code, out, err = run_cli(capsys, "--file", LEGACY_FIXTURE, "--dry-run", "--report", "/nao/importa.json")
    assert code == 1 and "só é suportado no layout SIM" in err


# ===============================================================================================
# extras de robustez do layout SIM
# ===============================================================================================


def test_numeric_cells_are_imported_with_a_warning_and_never_leaked(db_session, projects, settings, tmp_path, decrypt):
    rows = [
        row(
            numero_projeto=NUM_A,
            operador_1="NOS",
            telefone_1=PHONE_NUM,  # número no Excel: aceite como nº de telefone
            iccid_1=ICCID_A1,
            pin_1=PIN_NUM,  # PIN/PUK/password como número: aceites, com aviso (zeros à esquerda perdidos)
            puk_1=PUK_NUM,
            login=USERNAME_A,
            password=PASSWORD_NUM,
        )
    ]
    path = build_workbook(tmp_path / "fixtures" / "numeros.xlsx", rows)
    data = apply(db_session, settings, path).to_dict()
    (sim,) = active_sims(db_session, projects.a)
    assert sim.phone_number == str(PHONE_NUM)
    assert decrypt(sim.pin_encrypted) == str(PIN_NUM) and decrypt(sim.puk_encrypted) == str(PUK_NUM)
    assert decrypt(active_credentials(db_session, projects.a)[0].password_encrypted) == str(PASSWORD_NUM)
    assert {(w["linha"], w["coluna"]) for w in data["avisos"] if "linha" in w} == {(9, "F"), (9, "G"), (9, "O")}
    assert_no_fake_values(json.dumps(data, ensure_ascii=False))


def test_numeric_iccid_with_precision_loss_is_flagged_and_never_imported_truncated(
    db_session, projects, settings, tmp_path
):
    rows = [row(numero_projeto=NUM_A, operador_1="NOS", telefone_1=PHONE_A1, iccid_1=8.935100000000001e18)]
    path = build_workbook(tmp_path / "fixtures" / "iccid.xlsx", rows)
    data = apply(db_session, settings, path).to_dict()
    assert [(i["linha"], i["coluna"]) for i in data["linhas_invalidas"]] == [(9, "E")]
    assert "texto" in data["linhas_invalidas"][0]["motivo"]
    assert all(s.iccid is None for s in active_sims(db_session, projects.a))  # nunca um ICCID truncado


def test_repeated_project_number_and_sheet1_are_warned_about(tmp_path):
    rows = [row(numero_projeto=NUM_A, upac_registo="UPAC-1"), row(numero_projeto=NUM_A, upac_registo="UPAC-2")]
    path = build_workbook(tmp_path / "fixtures" / "rep.xlsx", rows, sheet1=True)
    warnings = parse_sim_layout(path.read_bytes()).warnings
    assert {"linhas": [9, 10], "aviso": "nº de projeto repetido no ficheiro"} in warnings
    assert any("Sheet1" in w.get("aviso", "") for w in warnings)


def test_blank_tokens_and_rows_are_skipped(tmp_path):
    rows = [
        row(numero_projeto=NUM_A, operador_1="NOS", telefone_1="-", iccid_1="Por confirmar", pin_1="–"),
        {},  # linha vazia no meio
        row(nome="só o nome (não conta como linha de dados)"),
        row(numero_projeto=NUM_B, upac_registo="UPAC-2"),
    ]
    path = build_workbook(tmp_path / "fixtures" / "vazios.xlsx", rows)
    parsed = parse_sim_layout(path.read_bytes())
    assert [(r.row_number, r.project_number) for r in parsed.rows] == [(9, NUM_A), (12, NUM_B)]
    assert parsed.rows[0].sims == [] and parsed.rows[0].credential is None
    # o operador sozinho (sem nº nem cartão) é reportado como inválido, nunca vira um SIM vazio
    assert [(i["linha"], i["coluna"]) for i in parsed.invalid] == [(9, "D")]


# --- SIM já existente na plataforma (criado na UI): o nº de telefone identifica o cartão ----------


def _std_sim_1_only(tmp_path: Path) -> Path:
    rows = [
        row(
            numero_projeto=NUM_A,
            operador_1="NOS",
            telefone_1=PHONE_A1,
            iccid_1=ICCID_A1,
            pin_1=PIN_A1,
            puk_1=PUK_A1,
        )
    ]
    return build_workbook(tmp_path / "fixtures" / "um_sim.xlsx", rows)


def test_existing_sim_without_iccid_is_matched_by_phone_and_filled_not_duplicated(
    db_session, projects, settings, tmp_path, decrypt
):
    existing = ProjectSimCard(
        project_id=projects.a.id, purpose="comunicacoes", operator="NOS", phone_number=PHONE_A1, iccid=None, notes=""
    )
    db_session.add(existing)
    db_session.commit()

    data = apply(db_session, settings, _std_sim_1_only(tmp_path)).to_dict()

    (sim,) = active_sims(db_session, projects.a)  # continua a haver um só SIM
    assert sim.id == existing.id and sim.iccid == ICCID_A1
    assert decrypt(sim.pin_encrypted) == PIN_A1 and decrypt(sim.puk_encrypted) == PUK_A1
    assert data["contagens"]["sim_1"] == {"preenchidos": 1} and data["conflitos"] == []


def test_same_phone_with_another_iccid_is_a_conflict_not_a_new_sim(db_session, projects, settings, tmp_path):
    existing = ProjectSimCard(
        project_id=projects.a.id,
        purpose="comunicacoes",
        operator="NOS",
        phone_number=PHONE_A1,
        iccid="8935100000000009999",  # outro cartão para o mesmo nº
        notes="",
    )
    db_session.add(existing)
    db_session.commit()

    data = apply(db_session, settings, _std_sim_1_only(tmp_path)).to_dict()

    (sim,) = active_sims(db_session, projects.a)
    assert sim.iccid == "8935100000000009999"  # não sobrescrito
    assert [(c["linha"], c["bloco"], c["campo"]) for c in data["conflitos"]] == [(9, "sim_1", "iccid")]


def test_excel_sim_with_phone_only_matches_an_existing_sim_that_has_an_iccid(db_session, projects, settings, tmp_path):
    existing = ProjectSimCard(
        project_id=projects.a.id,
        purpose="comunicacoes",
        operator="NOS",
        phone_number=PHONE_A1,
        iccid=ICCID_A1,
        notes="",
    )
    db_session.add(existing)
    db_session.commit()
    rows = [row(numero_projeto=NUM_A, operador_1="NOS", telefone_1=PHONE_A1)]
    path = build_workbook(tmp_path / "fixtures" / "so_telefone.xlsx", rows)

    data = apply(db_session, settings, path).to_dict()

    assert [s.id for s in active_sims(db_session, projects.a)] == [existing.id]
    assert data["contagens"]["sim_1"] == {"ja_existentes": 1}


def test_rollback_clears_an_iccid_that_the_batch_filled_on_an_existing_sim(db_session, projects, settings, tmp_path):
    existing = ProjectSimCard(
        project_id=projects.a.id, purpose="comunicacoes", operator="NOS", phone_number=PHONE_A1, iccid=None, notes=""
    )
    db_session.add(existing)
    db_session.commit()
    report = apply(db_session, settings, _std_sim_1_only(tmp_path))
    db_session.refresh(existing)
    assert existing.iccid == ICCID_A1

    rollback_licensing_batch(db_session, batch=db_session.get(FieldImportBatch, report.batch_id))

    db_session.refresh(existing)
    assert (existing.operator, existing.phone_number, existing.deleted_at) == ("NOS", PHONE_A1, None)
    assert existing.iccid is None and existing.pin_encrypted is None and existing.puk_encrypted is None


# ===============================================================================================
# 12) ligação ao projeto: prefixo numérico da nomenclatura (`solcor_nomenclatura_xlsx`)
#     1 projeto ativo -> ligado | 0 -> "não encontrado" | >1 -> "ambíguo" (reportado, não grava)
# ===============================================================================================


def link_phone(n: int) -> str:
    return f"91000{n:04d}"


def link_row(number: str, n: int) -> dict[int, object]:
    """Linha mínima (nº de projeto + 1 SIM com telefone/ICCID próprios + UPAC) para provar A QUEM
    o importador liga os dados. `n` torna o telefone/ICCID/UPAC únicos por linha."""
    return row(
        numero_projeto=number,
        operador_1="NOS",
        telefone_1=link_phone(n),
        iccid_1=f"89351000000000{n:05d}",
        upac_registo=f"UPAC-LINK-{n}",
    )


def link_workbook(tmp_path: Path, numbers: list[str], name: str = "ligacao.xlsx") -> Path:
    """Uma linha por nº (a linha `i` tem o telefone `link_phone(i)`, com `i` a partir de 1)."""
    return build_workbook(tmp_path / "fixtures" / name, [link_row(number, i) for i, number in enumerate(numbers, 1)])


def phones_of(db, project) -> list[str | None]:
    return [sim.phone_number for sim in active_sims(db, project)]


@contextlib.contextmanager
def capture_selects(table: str):
    """SELECTs emitidos contra `table` (só o texto da consulta — nunca parâmetros)."""
    statements: list[str] = []
    pattern = re.compile(rf"\b{re.escape(table)}\b")

    def _listener(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and pattern.search(statement):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


@pytest.mark.parametrize(
    "external_id",
    [
        "7001_Cliente Prefixo_ESCO_Empresa Fictícia_PV",
        "7001_Cliente Prefixo_ESCO_Empresa Fictícia_PV - UPAC 2",
        "  7001_Cliente Prefixo_ESCO_Empresa Fictícia_PV",
    ],
    ids=["nomenclatura", "sufixo-upac", "espacos-a-esquerda"],
)
def test_project_is_linked_by_the_numeric_prefix_of_the_nomenclature(db_session, settings, tmp_path, external_id):
    project = make_project(db_session, "Projeto Sintético Prefixo", external_id=external_id)

    data = apply(db_session, settings, link_workbook(tmp_path, ["7001"])).to_dict()

    assert (data["projetos_encontrados"], data["projetos_nao_encontrados"], data["projetos_ambiguos"]) == (1, [], [])
    assert phones_of(db_session, project) == [link_phone(1)]
    assert licensing_of(db_session, project).upac_number == "UPAC-LINK-1"
    # só a nomenclatura liga: o projeto não tem nenhum ProjectExternalId do layout legado
    legacy_ids = db_session.query(ProjectExternalId).filter_by(project_id=project.id, source_system=LEGACY_SOURCE)
    assert legacy_ids.count() == 0


def test_a_shorter_number_never_matches_a_longer_prefix(db_session, settings, tmp_path):
    """12 não casa com '123_…' (o prefixo acaba no '_'); nem 1, nem 23 (que está no meio), nem 1234."""
    longer = make_project(db_session, "Projeto Sintético Longo", external_id=nomenclature("123", "Cliente Longo"))
    before = table_counts(db_session)

    data = apply(db_session, settings, link_workbook(tmp_path, ["12", "1", "23", "1234", "123"])).to_dict()

    assert data["projetos_nao_encontrados"] == ["1", "12", "1234", "23"]
    assert data["projetos_encontrados"] == 1 and data["projetos_ambiguos"] == []
    assert phones_of(db_session, longer) == [link_phone(5)]  # só a linha do nº 123
    after = table_counts(db_session)
    assert after["ProjectSimCard"] - before["ProjectSimCard"] == 1
    assert after["ProjectLicensingData"] - before["ProjectLicensingData"] == 1


def test_numbers_that_are_prefixes_of_each_other_are_linked_to_their_own_project(db_session, settings, tmp_path):
    short = make_project(db_session, "Projeto Sintético Curto", external_id=nomenclature("12", "Cliente Curto"))
    longer = make_project(db_session, "Projeto Sintético Longo", external_id=nomenclature("123", "Cliente Longo"))

    data = apply(db_session, settings, link_workbook(tmp_path, ["12", "123"])).to_dict()

    assert data["projetos_encontrados"] == 2
    assert data["projetos_nao_encontrados"] == [] and data["projetos_ambiguos"] == []
    assert phones_of(db_session, short) == [link_phone(1)]
    assert phones_of(db_session, longer) == [link_phone(2)]


# --- nº com mais de um projeto ativo (várias UPAC): reportado como ambíguo e nunca grava ----------

AMBIGUOUS_NUMBER = "7002"
# nada disto pode aparecer num relatório/saída: o relatório diz só o nº e a quantidade
AMBIGUOUS_NAME_TOKENS = ("Cliente Ambíguo", "UPAC Um", "UPAC Dois", "Empresa Fictícia")


def _ambiguous_scenario(db) -> tuple[Project, Project]:
    """O nº 7002 corresponde a duas UPAC (dois projetos ativos com o mesmo prefixo)."""
    first = make_project(db, "Projeto Sintético UPAC Um", external_id=nomenclature("7002", "Cliente Ambíguo"))
    second = make_project(
        db, "Projeto Sintético UPAC Dois", external_id=nomenclature("7002", "Cliente Ambíguo", " - UPAC 2")
    )
    return first, second


def _ambiguous_row() -> dict[int, object]:
    return row(
        numero_projeto=AMBIGUOUS_NUMBER,
        operador_1="NOS",
        telefone_1=PHONE_X1,
        iccid_1=ICCID_X1,
        pin_1=PIN_X1,
        puk_1=PUK_X1,
        login=USERNAME_X,
        password=PASSWORD_X,
        email=EMAIL_X,
        upac_registo="UPAC-AMBIGUO",
    )


def _ambiguous_file(tmp_path: Path) -> Path:
    """O ficheiro standard (A e B ligados, um nº órfão) + uma linha com segredos para o nº ambíguo."""
    return build_workbook(tmp_path / "fixtures" / "ambiguo.xlsx", [*std_rows(), _ambiguous_row()], surplus=std_surplus())


def assert_no_project_names(*texts: str) -> None:
    for text in texts:
        leaked = [token for token in AMBIGUOUS_NAME_TOKENS if token in text]
        assert not leaked, f"nomes de projeto/nomenclatura apareceram na saída: {leaked}"


def test_number_matching_two_active_projects_is_ambiguous_and_nothing_is_written(
    db_session, projects, settings, tmp_path
):
    first, second = _ambiguous_scenario(db_session)
    before = table_counts(db_session)

    data = apply(db_session, settings, _ambiguous_file(tmp_path)).to_dict()

    # reportado só com o nº e a quantidade — sem nomes; não conta como ligado nem como não encontrado
    assert data["projetos_ambiguos"] == [{"numero": AMBIGUOUS_NUMBER, "quantidade": 2}]
    assert data["projetos_encontrados"] == 2  # A e B
    assert data["projetos_nao_encontrados"] == [NUM_ORPHAN]
    assert_no_project_names(json.dumps(data, ensure_ascii=False), json.dumps(data))

    # a linha ambígua não grava em nenhum dos dois projetos (SIM, credencial, licenciamento, histórico)
    for project in (first, second):
        assert active_sims(db_session, project) == [] and active_credentials(db_session, project) == []
        assert licensing_of(db_session, project) is None
        assert db_session.query(ProjectDataHistory).filter_by(project_id=project.id).count() == 0

    # o resto do ficheiro corre normalmente: só o que o ficheiro standard cria para A e B
    after = table_counts(db_session)
    assert after["ProjectSimCard"] - before["ProjectSimCard"] == 3
    assert after["ProjectPortalCredential"] - before["ProjectPortalCredential"] == 1
    assert after["ProjectLicensingData"] - before["ProjectLicensingData"] == 2
    assert data["contagens"] == {
        "sim_1": {"criados": 2},
        "sim_2": {"criados": 1},
        "credencial_login_geral": {"criados": 1},
        "licenciamento": {"criados": 2},
        "excedente": {"criados": 1, "por_ligar": 1},
    }


def test_ambiguous_numbers_are_predicted_by_dry_run_without_writing(db_session, projects, settings, tmp_path):
    _ambiguous_scenario(db_session)
    path = _ambiguous_file(tmp_path)
    before = table_counts(db_session)

    with capture_dml() as statements:
        predicted = dry_run(db_session, settings, path).to_dict()
    assert statements == [] and table_counts(db_session) == before
    assert predicted["projetos_ambiguos"] == [{"numero": AMBIGUOUS_NUMBER, "quantidade": 2}]

    applied = apply(db_session, settings, path).to_dict()
    for key in ("projetos_ambiguos", "projetos_encontrados", "projetos_nao_encontrados", "contagens"):
        assert predicted[key] == applied[key], key


def test_an_ambiguous_number_repeated_in_the_file_is_reported_once(db_session, settings, tmp_path):
    _ambiguous_scenario(db_session)
    path = build_workbook(tmp_path / "fixtures" / "repetido.xlsx", [_ambiguous_row(), _ambiguous_row()])
    assert dry_run(db_session, settings, path).to_dict()["projetos_ambiguos"] == [
        {"numero": AMBIGUOUS_NUMBER, "quantidade": 2}
    ]


def test_secrets_of_an_ambiguous_number_do_not_require_the_key(db_session, no_key_settings, tmp_path):
    # só há segredos numa linha ambígua -> nada a gravar -> não exige chave (como um projeto inexistente)
    first, second = _ambiguous_scenario(db_session)
    path = build_workbook(tmp_path / "fixtures" / "so_ambiguo.xlsx", [_ambiguous_row()])

    report = apply(db_session, no_key_settings, path)

    assert report.to_dict()["projetos_ambiguos"] == [{"numero": AMBIGUOUS_NUMBER, "quantidade": 2}]
    assert active_sims(db_session, first) == [] and active_sims(db_session, second) == []


@pytest.mark.parametrize("mode", ["--dry-run", "--apply"])
def test_cli_reports_ambiguous_numbers_without_names(db_session, projects, settings, cli_env, capsys, tmp_path, mode):
    _ambiguous_scenario(db_session)
    report_path = tmp_path / "relatorio.json"

    code, out, err = run_cli(capsys, "--file", _ambiguous_file(tmp_path), mode, "--report", report_path)

    assert code == 0, err
    assert "Projetos não encontrados: 1" in out and "Projetos ambíguos: 1" in out
    report_text = report_path.read_text(encoding="utf-8")
    assert json.loads(report_text)["projetos_ambiguos"] == [{"numero": AMBIGUOUS_NUMBER, "quantidade": 2}]
    assert_no_project_names(out, err, report_text)
    assert_no_fake_values(out, err, report_text, tmp_path=tmp_path)


# --- sem correspondência utilizável: "não encontrado" e nada gravado --------------------------------


def test_number_without_a_usable_match_is_not_found_and_nothing_is_written(db_session, settings, tmp_path):
    # nomenclatura de OUTRA origem, nomenclatura de um projeto inativo, e nº sem nenhum registo
    make_project(
        db_session, "Projeto Sintético Outra Origem", external_id=nomenclature("7003", "Cliente Outra"), source="clickup"
    )
    make_project(
        db_session, "Projeto Sintético Inativo", external_id=nomenclature("7004", "Cliente Inativo"), active=False
    )
    before = table_counts(db_session)

    data = apply(db_session, settings, link_workbook(tmp_path, ["7003", "7004", "7005"])).to_dict()

    assert data["projetos_nao_encontrados"] == ["7003", "7004", "7005"]
    assert data["projetos_encontrados"] == 0 and data["projetos_ambiguos"] == []
    after = table_counts(db_session)
    for model in ("ProjectSimCard", "ProjectPortalCredential", "ProjectLicensingData", "ProjectDataHistory"):
        assert after[model] == before[model], model


def test_deleted_nomenclature_is_not_an_import_target_or_legacy_fallback_and_restore_is_eligible(
    db_session, settings, no_key_settings, tmp_path
):
    number = "7014"
    deleted = make_project(
        db_session,
        "Projeto Sintético Apagado SIM",
        external_id=nomenclature(number, "Cliente Apagado"),
    )
    deleted.deleted_at = dt.datetime.now(dt.timezone.utc)
    db_session.commit()
    legacy = make_project(
        db_session,
        "Projeto Sintético Legado Rival Apagado SIM",
        external_id=number,
        source=LEGACY_SOURCE,
    )

    def import_row(notes: str) -> dict[int, object]:
        return row(
            numero_projeto=number,
            operador_1="NOS",
            telefone_1=PHONE_X1,
            iccid_1=ICCID_X1,
            pin_1=PIN_X1,
            puk_1=PUK_X1,
            login=USERNAME_X,
            password=PASSWORD_X,
            email=EMAIL_X,
            upac_registo="UPAC-DELETED-SIM",
            notas_registo=notes,
        )

    path = build_workbook(tmp_path / "fixtures" / "deleted-project.xlsx", [import_row("primeiro")])
    before = table_counts(db_session)
    preview = dry_run_sim_import(db_session, content=path.read_bytes(), settings=no_key_settings).to_dict()
    assert preview["projetos_nao_encontrados"] == [number]
    assert preview["projetos_encontrados"] == 0
    assert table_counts(db_session) == before

    applied = apply(db_session, no_key_settings, path).to_dict()
    assert applied["projetos_nao_encontrados"] == [number]
    assert applied["projetos_encontrados"] == 0
    assert active_sims(db_session, deleted) == []
    assert active_credentials(db_session, deleted) == []
    assert licensing_of(db_session, deleted) is None
    assert active_sims(db_session, legacy) == []
    assert active_credentials(db_session, legacy) == []
    assert licensing_of(db_session, legacy) is None
    assert db_session.query(ProjectDataHistory).filter(ProjectDataHistory.project_id.in_((deleted.id, legacy.id))).count() == 0

    deleted.deleted_at = None
    db_session.commit()
    restored_path = build_workbook(
        tmp_path / "fixtures" / "restored-project.xlsx",
        [import_row("conteúdo alterado depois do restauro")],
    )
    restored = apply(db_session, settings, restored_path).to_dict()
    assert restored["projetos_encontrados"] == 1
    assert restored["projetos_nao_encontrados"] == []
    assert len(active_sims(db_session, deleted)) == 1
    assert len(active_credentials(db_session, deleted)) == 1
    assert licensing_of(db_session, deleted).upac_number == "UPAC-DELETED-SIM"
    assert active_sims(db_session, legacy) == []


def test_sim_apply_revalidates_project_deleted_after_resolver_was_built(
    db_session, settings, tmp_path, monkeypatch
):
    number = "7015"
    project = make_project(
        db_session,
        "Projeto Sintético Apagado Entre Plano e Apply",
        external_id=nomenclature(number, "Cliente Revalidação"),
    )
    path = build_workbook(
        tmp_path / "fixtures" / "stale-resolver.xlsx",
        [
            row(
                numero_projeto=number,
                operador_1="NOS",
                telefone_1=PHONE_X1,
                iccid_1=ICCID_X1,
                pin_1=PIN_X1,
                puk_1=PUK_X1,
                login=USERNAME_X,
                password=PASSWORD_X,
                email=EMAIL_X,
                upac_registo="UPAC-STALE-RESOLVER",
            )
        ],
    )
    original_loader = imports_licensing_service._load_sim_project_resolver

    def resolver_then_delete(db):
        resolver = original_loader(db)
        project.deleted_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        return resolver

    monkeypatch.setattr(imports_licensing_service, "_load_sim_project_resolver", resolver_then_delete)
    report = apply(db_session, settings, path).to_dict()

    assert report["projetos_nao_encontrados"] == [number]
    assert report["projetos_encontrados"] == 0
    assert active_sims(db_session, project) == []
    assert active_credentials(db_session, project) == []
    assert licensing_of(db_session, project) is None
    assert db_session.query(ProjectDataHistory).filter_by(project_id=project.id).count() == 0


def test_inactive_projects_and_repeated_ids_of_one_project_do_not_make_a_number_ambiguous(
    db_session, settings, tmp_path
):
    active = make_project(db_session, "Projeto Sintético Ativo", external_id=nomenclature("7006", "Cliente Ativo"))
    make_project(  # mesmo nº, mas desativado: não conta para a ambiguidade
        db_session, "Projeto Sintético Desativado", external_id=nomenclature("7006", "Cliente Ativo", " - UPAC 2"), active=False
    )
    twice = make_project(db_session, "Projeto Sintético Duas", external_id=nomenclature("7007", "Cliente Duas"))
    db_session.add(  # o MESMO projeto com duas nomenclaturas do mesmo nº: é um só projeto
        ProjectExternalId(
            project_id=twice.id, source_system=NOMENCLATURE_SOURCE, external_id=nomenclature("7007", "Cliente Duas", " - UPAC 2")
        )
    )
    db_session.commit()

    data = apply(db_session, settings, link_workbook(tmp_path, ["7006", "7007"])).to_dict()

    assert data["projetos_encontrados"] == 2
    assert data["projetos_nao_encontrados"] == [] and data["projetos_ambiguos"] == []
    assert phones_of(db_session, active) == [link_phone(1)]
    assert phones_of(db_session, twice) == [link_phone(2)]


# --- fallback legado: só quando a nomenclatura não casa de todo ----------------------------------


def test_legacy_external_id_still_links_when_there_is_no_nomenclature_match(db_session, settings, tmp_path):
    legacy = make_project(db_session, "Projeto Sintético Só Legado", external_id="7010", source=LEGACY_SOURCE)

    data = apply(db_session, settings, link_workbook(tmp_path, ["7010"])).to_dict()

    assert data["projetos_encontrados"] == 1
    assert data["projetos_nao_encontrados"] == [] and data["projetos_ambiguos"] == []
    assert phones_of(db_session, legacy) == [link_phone(1)]


def test_nomenclature_wins_over_a_legacy_external_id_of_the_same_number(db_session, settings, tmp_path):
    by_nomenclature = make_project(db_session, "Projeto Sintético Nomenclatura", external_id=nomenclature("7011", "Cliente Nova"))
    by_legacy = make_project(db_session, "Projeto Sintético Legado Rival", external_id="7011", source=LEGACY_SOURCE)

    data = apply(db_session, settings, link_workbook(tmp_path, ["7011"])).to_dict()

    assert data["projetos_encontrados"] == 1
    assert phones_of(db_session, by_nomenclature) == [link_phone(1)]
    assert phones_of(db_session, by_legacy) == []


def test_legacy_fallback_never_links_an_inactive_project(db_session, settings, tmp_path):
    inactive = make_project(
        db_session, "Projeto Sintético Legado Inativo", external_id="7012", source=LEGACY_SOURCE, active=False
    )

    data = apply(db_session, settings, link_workbook(tmp_path, ["7012"])).to_dict()

    assert data["projetos_nao_encontrados"] == ["7012"] and data["projetos_encontrados"] == 0
    assert phones_of(db_session, inactive) == []


@pytest.mark.parametrize("case", ["ambiguo", "so-inativo"])
def test_legacy_fallback_is_not_used_when_the_nomenclature_matched_but_cannot_link(
    db_session, settings, tmp_path, case
):
    """Houve correspondência por nomenclatura (ambígua, ou só em projetos inativos): o resultado
    fica como está, em vez de ligar em silêncio ao projeto do id legado do mesmo nº."""
    legacy = make_project(db_session, "Projeto Sintético Legado Vizinho", external_id="7013", source=LEGACY_SOURCE)
    if case == "ambiguo":
        make_project(db_session, "Projeto Sintético Um", external_id=nomenclature("7013", "Cliente Um"))
        make_project(db_session, "Projeto Sintético Dois", external_id=nomenclature("7013", "Cliente Um", " - UPAC 2"))
    else:
        make_project(db_session, "Projeto Sintético Um", external_id=nomenclature("7013", "Cliente Um"), active=False)

    data = apply(db_session, settings, link_workbook(tmp_path, ["7013"])).to_dict()

    assert phones_of(db_session, legacy) == [] and data["projetos_encontrados"] == 0
    if case == "ambiguo":
        assert data["projetos_ambiguos"] == [{"numero": "7013", "quantidade": 2}]
        assert data["projetos_nao_encontrados"] == []
    else:
        assert data["projetos_ambiguos"] == [] and data["projetos_nao_encontrados"] == ["7013"]


# --- eficiência: os mapas carregam-se uma vez por execução, não uma vez por linha -----------------


def test_project_maps_are_loaded_once_per_run_not_once_per_row(db_session, settings, tmp_path):
    numbers = [str(8000 + i) for i in range(12)]
    for number in numbers[:8]:  # 8 ligados + 4 por encontrar (esses passam também pelo fallback legado)
        make_project(db_session, f"Projeto Sintético Lote {number}", external_id=nomenclature(number, f"Cliente Lote {number}"))
    many = link_workbook(tmp_path, numbers, "muitas.xlsx")
    one = link_workbook(tmp_path, numbers[:1], "uma.xlsx")

    queries: dict[str, int] = {}
    for label, action, path in (("dry-run-1", dry_run, one), ("dry-run-12", dry_run, many), ("apply-12", apply, many)):
        with capture_selects("project_external_ids") as selects:
            action(db_session, settings, path)
        queries[label] = len(selects)

    assert queries["dry-run-1"] == queries["dry-run-12"] == queries["apply-12"], queries
    assert 1 <= queries["apply-12"] <= 2, queries


# --- safe-only: exclui só campos duvidosos e mantém paridade dry-run/apply ------------------------


def _numeric_secret_workbook(tmp_path: Path) -> Path:
    return build_workbook(
        tmp_path / "fixtures" / "segredos_numericos.xlsx",
        [
            row(
                numero_projeto=NUM_A,
                operador_1="NOS",
                telefone_1=PHONE_A1,
                iccid_1=ICCID_A1,
                pin_1=PIN_NUM,
                puk_1=PUK_NUM,
                login=USERNAME_A,
                password=PASSWORD_NUM,
                email=EMAIL_A,
                upac_registo="UPAC-SAFE-1",
            )
        ],
    )


def test_safe_only_keeps_unlinked_surplus_with_a_coincident_data_sheet_issue(
    db_session, projects, settings, tmp_path
):
    """A field issue on Dados gerais row 9 must not hide Venda do excedente row 9."""
    data_rows = [
        row(numero_projeto=NUM_A, operador_1="NOS", telefone_1=PHONE_A1, pin_1=PIN_NUM),
        row(numero_projeto=NUM_A, operador_1="NOS", telefone_1=PHONE_A2, pin_1=PIN_NUM),
    ]
    surplus_rows = [surplus_row(NAME_A, commercializer=f"Comercializador Fictício {index}") for index in range(7)]
    surplus_rows.extend(
        [
            surplus_row("Projeto Excedente sem Correspondência", commercializer="Comercializador Órfão Fictício", start=None),
            surplus_row(
                "Outro Excedente sem Correspondência",
                commercializer="Comercializador Inválido Fictício",
                end="amanhã",
            ),
        ]
    )
    path = build_workbook(
        tmp_path / "fixtures" / "safe_excedente_colisao_linha.xlsx",
        data_rows,
        surplus=surplus_rows,
    )
    content = path.read_bytes()

    normal = dry_run_sim_import(db_session, content=content, settings=settings).to_dict()
    safe = dry_run_sim_import(db_session, content=content, settings=settings, safe_only=True).to_dict()

    assert {item["linha"] for item in normal["excedente_por_ligar"]} == {9}
    assert {item["linha"] for item in safe["excedente_por_ligar"]} == {9, 10}
    assert safe["exclusoes_safe_only"] == [
        {
            "folha": "Dados gerais",
            "linha": 9,
            "bloco": "sim_1",
            "campo": "pin",
            "motivo": "valor guardado como número no Excel — confirmar zeros à esquerda",
        },
        {
            "folha": "Venda do excedente",
            "linha": 10,
            "bloco": "excedente",
            "campo": "end_date",
            "motivo": "data não reconhecida (esperado dd/mm/aaaa)",
        },
        {
            "folha": "Dados gerais",
            "linha": 10,
            "bloco": "sim_1",
            "campo": "pin",
            "motivo": "valor guardado como número no Excel — confirmar zeros à esquerda",
        },
    ]

    applied = apply(db_session, settings, path, safe_only=True).to_dict()
    assert applied["excedente_por_ligar"] == safe["excedente_por_ligar"]
    assert applied["contagens"]["excedente"]["por_ligar"] == 2
    assert (
        db_session.query(ProjectSurplusContract)
        .filter(
            ProjectSurplusContract.commercializer.in_(
                ("Comercializador Órfão Fictício", "Comercializador Inválido Fictício")
            )
        )
        .count()
        == 0
    )


def _sorted_exclusions(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: (item["linha"], item["bloco"], item["campo"], item["motivo"]))


def test_safe_only_dry_run_has_no_dml_and_predicts_apply_field_by_field(
    db_session, projects, settings, tmp_path, capsys
):
    path = _numeric_secret_workbook(tmp_path)
    before = table_counts(db_session)

    with capture_dml() as statements:
        predicted = dry_run_sim_import(
            db_session, content=path.read_bytes(), settings=settings, safe_only=True
        ).to_dict()

    assert statements == [] and table_counts(db_session) == before
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert predicted["safe_only"] is True
    assert _sorted_exclusions(predicted["exclusoes_safe_only"]) == [
        {"folha": "Dados gerais", "linha": 9, "bloco": "credencial_login_geral", "campo": "password", "motivo": "valor guardado como número no Excel — confirmar zeros à esquerda"},
        {"folha": "Dados gerais", "linha": 9, "bloco": "sim_1", "campo": "pin", "motivo": "valor guardado como número no Excel — confirmar zeros à esquerda"},
        {"folha": "Dados gerais", "linha": 9, "bloco": "sim_1", "campo": "puk", "motivo": "valor guardado como número no Excel — confirmar zeros à esquerda"},
    ]
    assert all(set(item) == {"folha", "linha", "bloco", "campo", "motivo"} for item in predicted["exclusoes_safe_only"])
    assert_no_fake_values(json.dumps(predicted, ensure_ascii=False), capsys.readouterr().out)

    applied = apply(db_session, settings, path, safe_only=True).to_dict()
    for key in (
        "safe_only",
        "exclusoes_safe_only",
        "projetos_encontrados",
        "projetos_nao_encontrados",
        "projetos_ambiguos",
        "contagens",
        "linhas_invalidas",
        "conflitos",
        "avisos",
        "excedente_por_ligar",
        "colunas_ignoradas",
    ):
        assert predicted[key] == applied[key], key
    (sim,) = active_sims(db_session, projects.a)
    assert (sim.operator, sim.phone_number, sim.iccid) == ("NOS", PHONE_A1, ICCID_A1)
    assert sim.pin_encrypted is None and sim.puk_encrypted is None
    (credential,) = active_credentials(db_session, projects.a)
    assert (credential.username, credential.email, credential.password_encrypted) == (USERNAME_A, EMAIL_A, None)
    licensing = licensing_of(db_session, projects.a)
    assert licensing is not None and licensing.upac_number == "UPAC-SAFE-1"
    assert_no_fake_values(json.dumps(applied, ensure_ascii=False))


@pytest.mark.parametrize("value", [10**14, float(10**14), 10**15, float(10**15)])
def test_15_digit_integer_or_float_identifier_is_rejected(value):
    parsed, reason = _sim_identifier(value)
    assert parsed is None
    assert reason and "15+ dígitos" in reason


def test_safe_only_excludes_long_numeric_identifier_but_keeps_other_fields(db_session, projects, settings, tmp_path):
    path = build_workbook(
        tmp_path / "fixtures" / "identificador_longo.xlsx",
        [
            row(
                numero_projeto=NUM_A,
                operador_1="NOS",
                telefone_1=PHONE_A1,
                iccid_1=10**14,
                upac_registo="UPAC-LIMPO",
            )
        ],
    )

    report = apply(db_session, settings, path, safe_only=True).to_dict()

    assert report["exclusoes_safe_only"] == [
        {"folha": "Dados gerais", "linha": 9, "bloco": "sim_1", "campo": "iccid", "motivo": "número com 15+ dígitos guardado como valor numérico (perda de precisão) — gravar como texto"}
    ]
    (sim,) = active_sims(db_session, projects.a)
    assert sim.operator == "NOS" and sim.phone_number == PHONE_A1 and sim.iccid is None
    licensing = licensing_of(db_session, projects.a)
    assert licensing is not None and licensing.upac_number == "UPAC-LIMPO"


def test_safe_only_excludes_invalid_date_and_numeric_secret_without_cipher_key(
    db_session, projects, no_key_settings, tmp_path
):
    path = build_workbook(
        tmp_path / "fixtures" / "safe_sem_chave.xlsx",
        [
            row(
                numero_projeto=NUM_A,
                operador_1="NOS",
                telefone_1=PHONE_A1,
                pin_1=PIN_NUM,
                upac_registo="UPAC-SAFE-DATE",
                data_registo="31/02/2024",
            )
        ],
    )

    report = apply(db_session, no_key_settings, path, safe_only=True).to_dict()

    assert _sorted_exclusions(report["exclusoes_safe_only"]) == [
        {"folha": "Dados gerais", "linha": 9, "bloco": "licenciamento", "campo": "upac_registration_date", "motivo": "data inválida"},
        {"folha": "Dados gerais", "linha": 9, "bloco": "sim_1", "campo": "pin", "motivo": "valor guardado como número no Excel — confirmar zeros à esquerda"},
    ]
    (sim,) = active_sims(db_session, projects.a)
    assert sim.operator == "NOS" and sim.phone_number == PHONE_A1 and sim.pin_encrypted is None
    licensing = licensing_of(db_session, projects.a)
    assert licensing is not None and licensing.upac_number == "UPAC-SAFE-DATE"
    assert licensing.upac_registration_date is None


def test_safe_only_never_writes_ambiguous_or_unmatched_projects_or_unlinked_contracts(
    db_session, settings, tmp_path
):
    ambiguous_a = make_project(db_session, "Projeto Ambíguo Seguro A", external_id=nomenclature("7001", "Cliente Ambíguo"))
    ambiguous_b = make_project(db_session, "Projeto Ambíguo Seguro B", external_id=nomenclature("7001", "Cliente Ambíguo", " - UPAC 2"))
    same_name_a = make_project(db_session, "Projeto Contrato Ambíguo", external_id=nomenclature("7002", "Cliente Contrato A"))
    same_name_b = make_project(db_session, "Projeto Contrato Ambíguo", external_id=nomenclature("7003", "Cliente Contrato B"))
    path = build_workbook(
        tmp_path / "fixtures" / "safe_sem_ligacao.xlsx",
        [
            row(numero_projeto="7001", operador_1="NOS", telefone_1=PHONE_A1, upac_registo="UPAC-AMBIGUO"),
            row(numero_projeto=NUM_ORPHAN, operador_1="NOS", telefone_1=PHONE_X1, upac_registo="UPAC-ORFAO"),
        ],
        surplus=[surplus_row("Projeto Sem Correspondência"), surplus_row("Projeto Contrato Ambíguo")],
    )

    report = apply(db_session, settings, path, safe_only=True).to_dict()

    assert report["projetos_ambiguos"] == [{"numero": "7001", "quantidade": 2}]
    assert report["projetos_nao_encontrados"] == [NUM_ORPHAN]
    assert report["projetos_encontrados"] == 0
    assert sorted(report["excedente_por_ligar"], key=lambda item: item["linha"]) == [
        {"linha": 2, "motivo": "sem projeto com nome igual (normalizado)"},
        {"linha": 3, "motivo": "nome ambíguo: mais de um projeto"},
    ]
    for project in (ambiguous_a, ambiguous_b, same_name_a, same_name_b):
        assert active_sims(db_session, project) == []
        assert licensing_of(db_session, project) is None
        assert active_surplus(db_session, project) == []
    assert db_session.query(ProjectSimCard).filter(ProjectSimCard.phone_number == PHONE_X1).count() == 0


def test_safe_only_cli_flag_works_for_dry_run(db_session, projects, settings, cli_env, capsys, tmp_path):
    path = _numeric_secret_workbook(tmp_path)
    report_path = tmp_path / "safe-report.json"

    code, out, err = run_cli(
        capsys, "--file", path, "--dry-run", "--safe-only", "--report", report_path
    )

    assert code == 0, err
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["safe_only"] is True and len(report["exclusoes_safe_only"]) == 3
    assert "safe-only" in out.lower()
    assert_no_fake_values(out, err, report_path.read_text(encoding="utf-8"))

    code, out, err = run_cli(
        capsys, "--file", path, "--apply", "--safe-only", "--report", report_path
    )
    assert code == 0, err
    applied_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert applied_report["safe_only"] is True and len(applied_report["exclusoes_safe_only"]) == 3
    assert "Importação aplicada" in out and "safe-only" in out.lower()
    assert_no_fake_values(out, err, report_path.read_text(encoding="utf-8"))


def test_safe_and_normal_modes_have_separate_idempotency_keys_without_duplicate_records(
    db_session, projects, settings, tmp_path
):
    path = _numeric_secret_workbook(tmp_path)
    original_hash = compute_file_hash(path.read_bytes())
    safe = apply(db_session, settings, path, safe_only=True)
    safe_batch = db_session.get(FieldImportBatch, safe.batch_id)
    assert safe_batch.source_file_hash != original_hash
    assert json.loads(safe_batch.raw_payload_json)["original_file_hash"] == original_hash
    after_safe = table_counts(db_session)

    normal = apply(db_session, settings, path)

    assert normal.already_imported is False and normal.batch_id != safe.batch_id
    after_normal = table_counts(db_session)
    for model in ("ProjectSimCard", "ProjectPortalCredential", "ProjectLicensingData", "ProjectSurplusContract"):
        assert after_normal[model] == after_safe[model], model
    (sim,) = active_sims(db_session, projects.a)
    assert sim.pin_encrypted is not None and sim.puk_encrypted is not None
    (credential,) = active_credentials(db_session, projects.a)
    assert credential.password_encrypted is not None

    with capture_dml() as statements:
        again_safe = apply(db_session, settings, path, safe_only=True)
        again_normal = apply(db_session, settings, path)
    assert statements == []
    assert again_safe.already_imported and again_safe.batch_id == safe.batch_id
    assert again_safe.to_dict()["safe_only"] is True and len(again_safe.to_dict()["exclusoes_safe_only"]) == 3
    assert again_normal.already_imported and again_normal.batch_id == normal.batch_id
    assert table_counts(db_session) == after_normal


def _assert_rollback_refused_without_mutation(db_session, batch, projects, expected_state):
    history_ids = {entry.id for entry in db_session.query(ProjectDataHistory).all()}
    project_history_ids = {entry.id for entry in db_session.query(ProjectHistory).all()}

    with pytest.raises(LicensingImportError, match="alterações posteriores") as raised:
        rollback_licensing_batch(db_session, batch=batch)

    assert "PIN" not in str(raised.value) and "password" not in str(raised.value).lower()
    assert batch.status == "applied"
    assert _visible_state(db_session, *projects) == expected_state
    assert history_ids == {entry.id for entry in db_session.query(ProjectDataHistory).all()}
    assert project_history_ids == {entry.id for entry in db_session.query(ProjectHistory).all()}


@pytest.mark.parametrize("target", ["licensing", "filled_sim", "created_sim", "created_credential", "created_contract"])
def test_rollback_refuses_post_import_edits_atomically(db_session, settings, tmp_path, target):
    ns, path = _rollback_scenario(db_session, settings, tmp_path)
    report = apply(db_session, settings, path)
    batch = db_session.get(FieldImportBatch, report.batch_id)

    if target == "licensing":
        license_data = db_session.query(ProjectLicensingData).filter_by(project_id=ns.a.id).one()
        license_data.upac_number = "UPAC-EDITADO-MANUALMENTE"
    elif target == "filled_sim":
        ns.pre_sim.phone_number = "910009999"
    elif target == "created_sim":
        created_sim = active_sims(db_session, ns.a)[0]
        created_sim.operator = "Operador Editado Manualmente"
    elif target == "created_credential":
        credential = active_credentials(db_session, ns.a)[0]
        credential.email = "edited@example.invalid"
    else:
        contract = active_surplus(db_session, ns.a)[0]
        contract.notes = "Contrato editado manualmente"
    db_session.commit()
    state_after_edit = _visible_state(db_session, ns.a, ns.b)

    _assert_rollback_refused_without_mutation(db_session, batch, (ns.a, ns.b), state_after_edit)


def test_rollback_refuses_a_secret_changed_and_restored_after_import(db_session, settings, tmp_path):
    ns, path = _rollback_scenario(db_session, settings, tmp_path)
    report = apply(db_session, settings, path)
    batch = db_session.get(FieldImportBatch, report.batch_id)
    db_session.refresh(ns.pre_sim)
    imported_token = ns.pre_sim.pin_encrypted
    assert imported_token is not None

    update_sim_card(
        db_session,
        sim=ns.pre_sim,
        changes={},
        secret_changes={"pin": encrypt_secret(settings, "POST-IMPORT-SECRET")},
        changed_by_person_id=None,
    )
    db_session.refresh(ns.pre_sim)
    update_sim_card(
        db_session,
        sim=ns.pre_sim,
        changes={},
        secret_changes={"pin": imported_token},
        changed_by_person_id=None,
    )
    db_session.refresh(ns.pre_sim)
    assert ns.pre_sim.pin_encrypted == imported_token
    state_after_edit = _visible_state(db_session, ns.a, ns.b)

    _assert_rollback_refused_without_mutation(db_session, batch, (ns.a, ns.b), state_after_edit)
    histories = db_session.query(ProjectDataHistory).filter_by(record_id=ns.pre_sim.id).all()
    assert all("POST-IMPORT-SECRET" not in f"{entry.old_value} {entry.new_value} {entry.note}" for entry in histories)

