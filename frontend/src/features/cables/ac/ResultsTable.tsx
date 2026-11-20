import { Badge, Card, EmptyState } from "../../../components/ui";
import type { CabosEngine, CircuitRow, Result, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import { useEngineValue } from "../useEngineValue";
import { moneyPt, numberPt, resultCircuitForRow } from "./utils";

interface ResultsTableProps {
  state: State;
  result: Result;
  rows: readonly CircuitRow[];
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
}

function cableCell(row: CircuitRow) {
  if (!row.cable) return "—";
  return (
    <div>
      <div><strong>Fases:</strong> {row.cable.phase ?? row.cable.text ?? "—"}</div>
      <div><strong>Neutro:</strong> {row.cable.neutral ?? "—"}</div>
      <div><strong>Terra:</strong> {row.cable.earth ?? "—"}</div>
      <span className="cell-sub">{row.cable.conductors} × {row.cable.sectionMm2} mm² {row.cable.material} · {row.cable.constitution === "mono" ? "monocondutores" : "multicondutor"}</span>
    </div>
  );
}

function breakerCell(row: CircuitRow) {
  const breaker = row.breaker ?? row.disjuntor;
  if (!breaker) return "—";
  return (
    <div>
      <strong>{numberPt(breaker.ratingA, " A", 0)}</strong>{breaker.name && <span className="cell-sub">{breaker.name}</span>}
      {breaker.ref && <span className="cell-sub">{breaker.ref}{breaker.icuKA === undefined ? "" : ` · Icu ${numberPt(breaker.icuKA, " kA", 1)}`}</span>}
      {breaker.differential && <span className="cell-sub">Diferencial: {breaker.differential.name}</span>}
    </div>
  );
}

export default function ResultsTable({ state, result, rows, engine, readOnly, apply }: ResultsTableProps) {
  const resultRows = rows.filter((row) => row.kind === "inv" || row.kind === "perc");
  const manualOptions = useEngineValue(
    async () => (await engine.views.manualCableOptions?.(state, result))?.circuits ?? [],
    [engine, state, result],
  );
  const manualCableCircuits = manualOptions.value ?? [];
  const reviewCount = resultRows.filter((row) => row.verdict === "a rever").length;

  return (
    <Card title="Cabos e resultados" icon="activity" flush>
      {resultRows.length === 0 ? (
        <EmptyState icon="activity" title="Sem resultados de circuitos" text="Os resultados aparecem quando existem inversores ou percursos calculáveis." compact />
      ) : (
        <>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Resultados dos circuitos AC</caption>
              <thead>
                <tr>
                  <th scope="col">Circuito</th>
                  <th scope="col">Origem / destino</th>
                  <th scope="col">Cabo escolhido</th>
                  <th scope="col">Iz</th>
                  <th scope="col">In</th>
                  <th scope="col">I2</th>
                  <th scope="col">ΔU</th>
                  <th scope="col">Disjuntor</th>
                  <th scope="col">Custo</th>
                  <th scope="col">Veredicto</th>
                </tr>
              </thead>
              <tbody>
                {resultRows.map((row, index) => {
                  const circuit = resultCircuitForRow(result, row);
                  const review = row.verdict === "a rever";
                  const manualCircuit = manualCableCircuits.find((item) => item.kind === row.kind && item.code !== null && item.code === row.code)
                    ?? (manualCableCircuits[index]?.kind === row.kind ? manualCableCircuits[index] : undefined);
                  const selectedOption = manualCircuit?.options.find((option) => option.value === manualCircuit.selected);
                  const selectionLabel = manualCircuit?.selected === "auto"
                    ? "Automático (motor)"
                    : selectedOption?.label ?? "Seleção manual atual não disponível";
                  const displayedSelection = manualCircuit && (manualCircuit.selected === "auto" || selectedOption) ? manualCircuit.selected : "";
                  return (
                    <tr key={`${row.code ?? "circuit"}-${index}`} className={review ? "row--danger" : undefined}>
                      <td data-label="Circuito">
                        <strong>{row.code ?? `C${index + 1}`}</strong>
                        <span className="cell-sub">{row.designation || `${row.origin} → ${row.destination}`}</span>
                      </td>
                      <td data-label="Origem / destino">
                        <span>{row.origin} → {row.destination}</span>
                        <span className="cell-sub">{numberPt(row.lengthM, " m", 1)}{row.calculationLengthM !== row.lengthM ? ` · cálculo ${numberPt(row.calculationLengthM, " m", 1)}` : ""}</span>
                      </td>
                      <td data-label="Cabo escolhido">
                        {cableCell(row)}
                        {manualCircuit && (
                          <select
                            className="select"
                            aria-label={`Selecionar cabo do circuito ${row.code ?? `C${index + 1}`} — estado atual: ${selectionLabel}`}
                            value={displayedSelection}
                            disabled={readOnly}
                            onChange={(event) => {
                              if (readOnly) return;
                              apply((current) => engine.actions.setManualCable(current, {
                                kind: manualCircuit.kind,
                                id: manualCircuit.id,
                                value: event.target.value,
                              }));
                            }}
                          >
                            {displayedSelection === "" && <option value="" disabled>Seleção atual não disponível</option>}
                            <option value="auto">Automático (motor)</option>
                            {manualCircuit.options.filter((option) => option.value !== "auto").map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}{option.meetsRequirements ? "" : " · Não cumpre requisitos"}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td data-label="Iz" className="nowrap">{numberPt(row.Iz, " A", 1)}</td>
                      <td data-label="In" className="nowrap">{numberPt(row.In, " A", 1)}</td>
                      <td data-label="I2" className="nowrap">{numberPt(row.I2, " A", 1)}</td>
                      <td data-label="ΔU" className="nowrap">
                        {numberPt(row.voltageDropV ?? row.deltaU, " V", 2)}
                        <span className="cell-sub">{numberPt(row.voltageDropPct ?? row.deltaU, " %", 2)}</span>
                      </td>
                      <td data-label="Disjuntor">{breakerCell(row)}</td>
                      <td data-label="Custo" className="nowrap">
                        {circuit?.cost ? moneyPt(circuit.cost.v) : "—"}
                        {circuit?.cost?.est && <span className="cell-sub">estimado</span>}
                      </td>
                      <td data-label="Veredicto">
                        <div aria-label={`${row.verdict}: ${row.message}`}>
                          <Badge tone={review ? "warning" : "success"} dot>{row.verdict}</Badge>
                          <span className="cell-sub">{row.message || row.reason || "—"}</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <span className="sr-only" aria-live="polite" aria-atomic="true">{reviewCount ? `${reviewCount} circuitos a rever` : "Todos os circuitos estão verificados"}</span>
        </>
      )}
    </Card>
  );
}
