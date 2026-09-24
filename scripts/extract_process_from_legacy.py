"""Extrai o processo (fases, etapas, subtarefas) do `solcor-gestao.html` legado para
um JSON **fora do repositório**, no formato de `app/services/process_catalog.py`.

O texto do processo é interno da Solcor: este script está no Git, o JSON que gera
não (recusa-se a escrever dentro da árvore do Git, a não ser numa pasta ignorada).
Precisa de Node.js (já é requisito do projeto) para ler o objeto JavaScript do
legado sem o executar como página — só se avalia o literal `STAGES`/`PHASES`.

Utilização:
    python scripts/extract_process_from_legacy.py \\
        --html C:/caminho/solcor-gestao.html --out C:/fora/do/repo/processo.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JS = r"""
const fs = require("fs");
const s = fs.readFileSync(process.argv[1], "utf8");
function literal(start, open, close) {
  const a = s.indexOf(start);
  if (a < 0) throw new Error("não encontrei " + start);
  const from = a + start.length; // o literal começa logo a seguir ao "="
  let depth = 0, end = -1;
  for (let i = from; i < s.length; i++) {
    if (s[i] === open) depth++;
    else if (s[i] === close) { depth--; if (depth === 0) { end = i; break; } }
  }
  return eval("(" + s.slice(from, end + 1) + ")");
}
const PHASES = literal("const PHASES=", "{", "}");
const ORDER = eval(s.match(/const PHASE_ORDER=(\[[^\]]*\])/)[1]);
const STAGES = literal("const STAGES=", "[", "]");
const id = (n) => "etapa-" + String(n).padStart(2, "0");
console.log(JSON.stringify({
  phases: ORDER.map((k) => ({ code: k, name: PHASES[k].nm, color: PHASES[k].hex })),
  stages: STAGES.map((st) => ({
    code: id(st.id),
    phase: st.ph,
    title: st.t,
    responsible: st.resp,
    depends_on: st.dep == null ? null : id(st.dep),
    start_day: st.s,
    end_day: st.e,
    contact: st.contact ? { day: st.contact.day, kind: st.contact.type, note: st.contact.note || "" } : null,
    note: st.note || "",
    subtasks: st.subs,
  })),
}));
"""


def _inside_git_and_not_ignored(path: Path) -> bool:
    try:
        top = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True, encoding="utf-8", timeout=5,
        )
        if top.returncode != 0:
            return False
        repo = Path(top.stdout.strip())
        path.resolve().relative_to(repo)
        ignored = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q", "--", str(path.resolve())],
            capture_output=True, timeout=5,
        )
        return ignored.returncode == 1
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.html.exists():
        print(f"Erro: ficheiro não encontrado: {args.html}", file=sys.stderr)
        return 1
    if _inside_git_and_not_ignored(args.out):
        print(
            "Erro: o destino está dentro do repositório e o Git não o ignora — o processo é interno "
            "da Solcor. Escolha uma pasta fora do repositório.",
            file=sys.stderr,
        )
        return 1
    try:
        result = subprocess.run(
            ["node", "-e", JS, str(args.html)], capture_output=True, encoding="utf-8", timeout=30, check=True
        )
    except FileNotFoundError:
        print("Erro: Node.js não encontrado.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Erro ao ler o processo do HTML: {exc.stderr.strip()}", file=sys.stderr)
        return 1
    data = json.loads(result.stdout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subtasks = sum(len(s["subtasks"]) for s in data["stages"])
    print(f"{len(data['phases'])} fases, {len(data['stages'])} etapas, {subtasks} subtarefas -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
