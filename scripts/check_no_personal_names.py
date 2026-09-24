"""Verifica que nenhum nome de pessoa consta dos ficheiros versionados (o repositório é
público). A lista de nomes fica **fora do repositório**: um JSON local com uma lista de
textos (`["Nome Apelido", "Apelido", …]`) passado em `--names-file`.

Cada nome procura-se como palavra inteira, sem distinguir maiúsculas nem acentos. Sai
com código 1 (e lista ficheiro:linha) se encontrar algum; 0 se estiver limpo. Só olha
para os ficheiros que o Git segue (`git ls-files`) — nunca imprime o conteúdo da linha
inteira, só o ficheiro, a linha e o nome encontrado.

Utilização:
    python scripts/check_no_personal_names.py --names-file C:/fora/do/repo/nomes.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = (".png", ".ico", ".woff", ".woff2", ".jpg", ".jpeg", ".gif", ".pdf")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def find_names(files: dict[str, str], names: list[str]) -> list[tuple[str, int, str]]:
    """`files` = {caminho: conteúdo}. Devolve (ficheiro, linha, nome) por ocorrência."""
    patterns = {n: re.compile(r"\b" + re.escape(_fold(n)) + r"\b") for n in names if n.strip()}
    hits: list[tuple[str, int, str]] = []
    for path, content in files.items():
        for number, line in enumerate(content.split("\n"), start=1):
            folded = _fold(line)
            for name, pattern in patterns.items():
                if pattern.search(folded):
                    hits.append((path, number, name))
    return hits


def tracked_files() -> dict[str, str]:
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, encoding="utf-8", check=True
    ).stdout.split("\n")
    files: dict[str, str] = {}
    for rel in listing:
        if not rel or rel.endswith(SKIP_SUFFIXES) or rel.endswith("package-lock.json"):
            continue
        try:
            files[rel] = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binário ou removido no working tree
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--names-file", type=Path, required=True, help="JSON local com a lista de nomes a procurar")
    args = parser.parse_args(argv)
    try:
        names = json.loads(args.names_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Erro ao ler a lista de nomes: {exc}", file=sys.stderr)
        return 2
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        print("Erro: esperada uma lista JSON de textos.", file=sys.stderr)
        return 2
    hits = find_names(tracked_files(), names)
    for path, number, name in hits:
        print(f"{path}:{number}: {name}")
    print(f"{len(hits)} ocorrência(s) em {len({h[0] for h in hits})} ficheiro(s).")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
