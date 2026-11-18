import { useMemo, useState } from "react";
import { Modal } from "../../../components/ui";
import type { BoardActionArgs, CabosEngine, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";

export interface NewBoardDialogProps {
  engine: CabosEngine;
  state: State;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater) => void;
  onClose: () => void;
}

type BoardType = BoardActionArgs["type"];

const BOARD_TYPES: readonly { id: BoardType; label: string; description: string }[] = [
  { id: "INT", label: "Quadro de interligação", description: "Corte geral, proteção da saída e ligação entre quadros." },
  { id: "CONT", label: "Quadro de contagem", description: "Contagem da produção, direta ou com transformadores de intensidade." },
  { id: "GW", label: "Gateway", description: "Recebe uma entrada por inversor e liga ao quadro seguinte." },
  { id: "CLI", label: "Quadro do cliente", description: "Ponto de ligação no quadro existente do cliente." },
];

const DEFAULT_NAMES: Record<BoardType, string> = {
  INT: "Q. Interligação",
  CONT: "Q. Contagem",
  GW: "Gateway",
  CLI: "Q. Entrada",
};

function nodeNames(state: State): string[] {
  return [...state.percs.flatMap((perc) => [perc.orig, perc.dest]), ...state.gws.map((gateway) => gateway.nome), ...state.invs.map((inverter) => inverter.q), Object.keys(state.btypes ?? {}), "QFV"]
    .flat()
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
}

function uniqueName(state: State, type: BoardType): string {
  const used = new Set(nodeNames(state));
  const base = DEFAULT_NAMES[type];
  if (!used.has(base)) return base;
  let suffix = 2;
  while (used.has(`${base} ${suffix}`)) suffix += 1;
  return `${base} ${suffix}`;
}

function qfvNode(state: State): string {
  const counts = new Map<string, number>();
  for (const inverter of state.invs) {
    const node = String(inverter.q ?? "QFV");
    counts.set(node, (counts.get(node) ?? 0) + 1);
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] ?? state.percs[0]?.orig ?? "QFV";
}

function terminalPercursos(state: State) {
  return state.percs.filter((perc) => !state.percs.some((candidate) => candidate !== perc && candidate.orig === perc.dest));
}

function percId(state: State, index: number): string {
  return String(state.percs[index]?.id ?? index + 1);
}

function suggestedPosition(state: State, type: BoardType): string {
  if (type === "GW") {
    const qfv = qfvNode(state);
    const firstFromQfv = state.percs.find((perc) => perc.orig === qfv);
    if (firstFromQfv) {
      const index = state.percs.indexOf(firstFromQfv);
      return percId(state, index);
    }
  }
  if (type !== "CLI") {
    const ends = terminalPercursos(state);
    const last = ends[ends.length - 1];
    if (last) return String(last.id ?? state.percs.indexOf(last) + 1);
  }
  return "end";
}

function compatibleGatewayModel(engine: CabosEngine, _state: State): string {
  const models = engine.catalogs?.gateways ?? [];
  return models[0]?.modelo ?? "";
}

export default function NewBoardDialog({ engine, state, readOnly, apply, onClose }: NewBoardDialogProps) {
  const [type, setType] = useState<BoardType>("INT");
  const [name, setName] = useState(() => uniqueName(state, "INT"));
  const [position, setPosition] = useState(() => suggestedPosition(state, "INT"));
  const [length, setLength] = useState("5");
  const [model, setModel] = useState(() => compatibleGatewayModel(engine, state));
  const [dimNom, setDimNom] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const positions = useMemo(() => {
    const entries = state.percs.map((perc, index) => ({ value: percId(state, index), label: `Entre ${perc.orig} e ${perc.dest}` }));
    const ends = terminalPercursos(state);
    const endNode = ends[ends.length - 1]?.dest ?? state.invs[0]?.q ?? "QFV";
    return [...entries, { value: "end", label: `No fim, a seguir a ${endNode}` }];
  }, [state]);
  const gatewayModels = engine.catalogs?.gateways ?? [];

  function selectType(nextType: BoardType): void {
    setType(nextType);
    setName(uniqueName(state, nextType));
    setPosition(suggestedPosition(state, nextType));
    if (nextType === "GW") setModel(compatibleGatewayModel(engine, state));
    setError(null);
  }

  function addBoard(): void {
    if (readOnly) return;
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Indica o nome do quadro.");
      return;
    }
    if (nodeNames(state).some((candidate) => candidate === trimmedName)) {
      setError("Já existe um quadro com esse nome.");
      return;
    }
    const parsedLength = Number(length);
    if (!Number.isFinite(parsedLength) || parsedLength < 0) {
      setError("A distância tem de ser um número maior ou igual a zero.");
      return;
    }
    if (!positions.some((option) => option.value === position)) {
      setError("Escolhe uma ligação válida.");
      return;
    }
    const args: BoardActionArgs = { type, name: trimmedName, position, L: parsedLength };
    if (type === "GW") {
      if (model) args.modelo = model;
      args.dimNom = dimNom;
    }
    try {
      apply((current) => engine.actions.addBoard(current, args));
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível adicionar o quadro.");
    }
  }

  return (
    <Modal title="Novo quadro" onClose={onClose}>
      <p className="cable-dialog__intro">Escolha o tipo e a ligação. O motor valida os nomes, a posição e a ligação entre quadros, gateways e cliente.</p>
      {error && <div className="cable-dialog__error" role="alert">{error}</div>}
      <fieldset className="cable-dialog__fieldset">
        <legend>Tipo de quadro</legend>
        <div className="cable-dialog__board-types" role="group" aria-label="Tipo de quadro">
          {BOARD_TYPES.map((boardType) => (
            <button
              key={boardType.id}
              type="button"
              className={`cable-dialog__board-type ${type === boardType.id ? "cable-dialog__board-type--selected" : ""}`}
              aria-pressed={type === boardType.id}
              onClick={() => selectType(boardType.id)}
              disabled={readOnly}
            >
              <strong>{boardType.label}</strong>
              <span>{boardType.description}</span>
            </button>
          ))}
        </div>
      </fieldset>
      <div className="cable-dialog__form-grid">
        <label className="field cable-dialog__field--wide">
          <span>Nome do quadro</span>
          <input className="input" aria-label="Nome do quadro" value={name} onChange={(event) => setName(event.target.value)} disabled={readOnly} />
        </label>
        <label className="field cable-dialog__field--wide">
          <span>Ligação</span>
          <select className="select" aria-label="Ligação" value={position} onChange={(event) => setPosition(event.target.value)} disabled={readOnly}>
            {positions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Distância (m)</span>
          <input className="input" aria-label="Distância do quadro (m)" type="number" min="0" step="1" value={length} onChange={(event) => setLength(event.target.value)} disabled={readOnly} />
        </label>
        {type === "GW" && (
          <>
            <label className="field cable-dialog__field--wide">
              <span>Modelo do gateway</span>
              <select className="select" aria-label="Modelo do gateway" value={model} onChange={(event) => setModel(event.target.value)} disabled={readOnly}>
                <option value="">Manual</option>
                {gatewayModels.map((gateway) => <option key={gateway.modelo} value={gateway.modelo}>{gateway.marca ? `${gateway.marca} · ` : ""}{gateway.modelo}</option>)}
              </select>
            </label>
            <label className="checkbox cable-dialog__checkbox">
              <input type="checkbox" aria-label="Dimensionar saída pela corrente nominal" checked={dimNom} onChange={(event) => setDimNom(event.target.checked)} disabled={readOnly} />
              Dimensionar a saída pela corrente nominal
            </label>
          </>
        )}
      </div>
      <div className="modal__foot cable-dialog__footer">
        <button type="button" className="btn btn--ghost" onClick={onClose}>Cancelar</button>
        <button type="button" className="btn btn--primary" onClick={addBoard} disabled={readOnly}>Adicionar quadro</button>
      </div>
    </Modal>
  );
}
