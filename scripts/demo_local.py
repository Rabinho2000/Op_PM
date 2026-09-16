#!/usr/bin/env python3
"""Arranque da demonstração Op_PM sem Docker (Windows, Linux e macOS).

    python scripts/demo_local.py            # instala o necessário e arranca
    python scripts/demo_local.py --reset    # repõe os dados sintéticos antes de arrancar

Faz, por esta ordem:
  1. cria `backend/.venv` e instala `backend/requirements.txt` (se faltar);
  2. corre `npm install` em `frontend/` (se faltar `node_modules`);
  3. aplica migrações + seed sintético (`python -m app.cli.demo setup`)
     numa base SQLite própria (`backend/data/op_pm_demo.db`);
  4. arranca o backend (http://localhost:8000) e o frontend
     (http://localhost:5173) até carregar em Ctrl+C.

Força sempre APP_ENV=local, AUTH_ENABLED=false e DEMO_MODE=true só para os
processos que lança — não altera nenhum `.env` nem usa credenciais reais.
Nunca usar isto para staging/produção (ver docs/MVP_DEMO.md).
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WINDOWS = os.name == "nt"
VENV_PYTHON = BACKEND / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def info(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def fail(message: str) -> None:
    print(f"\nERRO: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        fail(f"o comando falhou ({result.returncode}): {' '.join(cmd)}")


def ensure_backend(force_install: bool) -> None:
    if sys.version_info < (3, 12):
        fail(f"é necessário Python 3.12 ou superior (encontrado {sys.version.split()[0]}).")
    if not VENV_PYTHON.exists():
        info("A criar o ambiente virtual do backend (backend/.venv)…")
        venv.create(BACKEND / ".venv", with_pip=True)
        force_install = True
    if force_install:
        info("A instalar as dependências do backend…")
        run([str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt"], BACKEND)


def npm_executable() -> str:
    npm = shutil.which("npm")
    if not npm:
        fail("Node.js 20+ (com npm) não encontrado no PATH — instale-o a partir de https://nodejs.org/.")
    return npm


def ensure_frontend(force_install: bool) -> str:
    npm = npm_executable()
    if force_install or not (FRONTEND / "node_modules").exists():
        info("A instalar as dependências do frontend (npm install)…")
        run([npm, "install", "--no-audit", "--no-fund"], FRONTEND)
    return npm


def demo_env(backend_port: int, frontend_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "APP_ENV": "local",
            "AUTH_ENABLED": "false",
            "DEMO_MODE": "true",
            "DATABASE_URL": "sqlite:///./data/op_pm_demo.db",
            "CORS_ALLOWED_ORIGINS": f"http://localhost:{frontend_port},http://127.0.0.1:{frontend_port}",
            "DEMO_APP_URL": f"http://localhost:{frontend_port}",
            "PYTHONUTF8": "1",
            # Frontend (Vite)
            "VITE_API_BASE_URL": f"http://localhost:{backend_port}",
            "VITE_ENABLE_DEV_LOGIN": "true",
        }
    )
    return env


def wait_for(url: str, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Arranca a demonstração local da Op_PM (dados sintéticos).")
    parser.add_argument("--reset", action="store_true", help="apaga e volta a criar os dados de demonstração")
    parser.add_argument("--install", action="store_true", help="força a reinstalação das dependências")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()

    ensure_backend(args.install)
    npm = ensure_frontend(args.install)
    env = demo_env(args.backend_port, args.frontend_port)
    (BACKEND / "data").mkdir(exist_ok=True)

    if args.reset:
        info("A repor os dados sintéticos…")
        run([str(VENV_PYTHON), "-m", "app.cli.demo", "reset", "--yes"], BACKEND, env)
    else:
        info("A aplicar migrações e dados sintéticos…")
        run([str(VENV_PYTHON), "-m", "app.cli.demo", "setup"], BACKEND, env)

    info("A arrancar o backend e o frontend (Ctrl+C para parar)…")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    processes = [
        subprocess.Popen(
            [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.backend_port)],
            cwd=BACKEND,
            env=env,
            creationflags=creationflags,
        ),
        subprocess.Popen(
            [npm, "run", "dev", "--", "--port", str(args.frontend_port), "--strictPort"],
            cwd=FRONTEND,
            env=env,
            creationflags=creationflags,
        ),
    ]

    try:
        backend_ok = wait_for(f"http://127.0.0.1:{args.backend_port}/health")
        frontend_ok = wait_for(f"http://localhost:{args.frontend_port}/")
        if backend_ok and frontend_ok:
            print("\n" + "=" * 64)
            print(" Demonstração Op_PM a correr (dados 100% sintéticos)")
            print(f"   Aplicação:  http://localhost:{args.frontend_port}")
            print(f"   API/Swagger: http://localhost:{args.backend_port}/docs")
            print("   Entrar: escolher um utilizador de demonstração no ecrã inicial")
            print("   Parar:  Ctrl+C")
            print("=" * 64, flush=True)
        else:
            print("\nAVISO: um dos serviços não respondeu a tempo — ver as mensagens acima.", file=sys.stderr)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        info("A parar os serviços…")
        for p in processes:
            if p.poll() is None:
                if IS_WINDOWS:
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
