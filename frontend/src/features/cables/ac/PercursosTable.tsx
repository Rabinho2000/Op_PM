import { Card, EmptyState } from "../../../components/ui";
import type { CabosEngine, CircuitRow, PercState, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import NumericField from "./NumericField";
import RouteCard from "./RouteCard";
import { gatewayFor, numberPt, sectionLabel, sectionOptions } from "./utils";

interface PercursosTableProps {
  state: State;
  rows: readonly CircuitRow[];
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
  onAddBoard?: () => void;
}

function percId(perc: PercState, index: number): number {
  return perc.id ?? (index + 1);
}

export default function PercursosTable({ state, rows, engine, readOnly, apply, onAddBoard }: PercursosTableProps) {
  const catalogs = engine.catalogs;
  const percRows = rows.filter((row) => row.kind === "perc");

  function applyAction(updater: CableStudyUpdater, debounce = false) {
    apply(updater, debounce ? { debounce: true } : undefined);
  }

  const actions = !readOnly ? (
    <div className="cable-tab__actions">
      {onAddBoard && <button type="button" className="btn btn--sm" onClick={onAddBoard}>Adicionar quadro</button>}
      <button type="button" className="btn btn--sm btn--primary" onClick={() => applyAction((current) => engine.actions.addPerc(current))}>Adicionar percurso</button>
    </div>
  ) : onAddBoard ? (
    <button type="button" className="btn btn--sm" onClick={onAddBoard} disabled aria-disabled="true">Adicionar quadro</button>
  ) : undefined;

  return (
    <Card
      title="Percursos entre quadros"
      icon="link"
      flush
      actions={actions}
    >
      {state.percs.length === 0 ? (
        <EmptyState
          icon="link"
          title="Sem percursos"
          text="Adicione um percurso para ligar o quadro fotovoltaico ao ponto de injeção."
          compact
          action={!readOnly ? <button type="button" className="btn btn--primary" onClick={() => applyAction((current) => engine.actions.addPerc(current))}>Adicionar percurso</button> : undefined}
        />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">Percursos entre quadros</caption>
            <thead>
              <tr>
                <th scope="col">Origem</th>
                <th scope="col">Destino</th>
                <th scope="col">Distância (m)</th>
                <th scope="col">Outros circuitos na esteira</th>
                <th scope="col">Secção</th>
                <th scope="col">Passagem</th>
                {!readOnly && <th scope="col">Ações</th>}
              </tr>
            </thead>
            <tbody>
              {state.percs.map((perc, index) => {
                const id = percId(perc, index);
                const hasGatewayDestination = gatewayFor(state, perc.dest);
                const row = percRows[index];
                return (
                  <tr key={id ?? `perc-${index}`}>
                    <td data-label="Origem">
                      {readOnly || id === undefined ? <span>{perc.orig}</span> : (
                        <input className="input" aria-label={`Origem do percurso ${id}`} value={perc.orig} onChange={(event) => applyAction((current) => engine.actions.setPercOrigin(current, { id, value: event.target.value }), true)} />
                      )}
                    </td>
                    <td data-label="Destino">
                      {readOnly || id === undefined ? <span>{perc.dest}</span> : (
                        <>
                          <input className="input" aria-label={`Destino do percurso ${id}`} value={perc.dest} onChange={(event) => applyAction((current) => engine.actions.setPercDestination(current, { id, value: event.target.value }), true)} />
                          {hasGatewayDestination && <span className="cell-sub">Gateway</span>}
                          {!hasGatewayDestination && <select className="select select--compact" aria-label={`Tipo do quadro de destino ${id}`} value={state.btypes?.[perc.dest] ?? ""} onChange={(event) => applyAction((current) => engine.actions.setBoardType(current, { name: perc.dest, type: event.target.value || null }))}>
                            <option value="">Tipo automático</option>
                            <option value="INT">Quadro de interligação</option>
                            <option value="CONT">Quadro de contagem</option>
                            <option value="CLI">Quadro do cliente</option>
                            <option value="QFV">Quadro fotovoltaico</option>
                          </select>}
                        </>
                      )}
                    </td>
                    <td data-label="Distância (m)">
                      {readOnly || id === undefined ? <span>{numberPt(perc.L, " m")}</span> : (
                        <NumericField
                          label={`Distância do percurso ${id} (m)`}
                          value={perc.L}
                          min={0}
                          max={10000}
                          step={1}
                          onValid={(value) => {
                            if (value !== null) applyAction((current) => engine.actions.setPercField(current, { id, field: "L", value }), true);
                          }}
                        />
                      )}
                    </td>
                    <td data-label="Outros circuitos na esteira">
                      {readOnly || id === undefined ? <span>{numberPt(perc.extra ?? 0)}</span> : (
                        <NumericField
                          label={`Outros circuitos na esteira do percurso ${id}`}
                          value={perc.extra ?? 0}
                          min={0}
                          max={10000}
                          step={1}
                          onValid={(value) => {
                            if (value !== null) applyAction((current) => engine.actions.setPercField(current, { id, field: "extra", value }), true);
                          }}
                        />
                      )}
                      {hasGatewayDestination && (
                        readOnly ? <span className="cell-sub">{perc.split === false ? "Cabo conjunto" : "Um cabo por inversor até ao gateway"}</span> : (
                          <label className="checkbox small">
                            <input type="checkbox" checked={perc.split !== false} aria-label={`Um cabo por inversor no percurso ${id}`} onChange={(event) => applyAction((current) => engine.actions.setPercField(current, { id, field: "split", value: event.target.checked }))} />
                            Um cabo por inversor até ao gateway
                          </label>
                        )
                      )}
                    </td>
                    <td data-label="Secção">
                      {readOnly || id === undefined ? <span>{row?.section ? sectionLabel(row.section) : sectionLabel(perc.S)}</span> : (
                        <select className="select select--compact" aria-label={`Secção do percurso ${id}`} value={perc.S} onChange={(event) => applyAction((current) => engine.actions.setPercSection(current, { id, value: event.target.value }))}>
                          {sectionOptions(perc.S).map((value) => <option key={value} value={value}>{sectionLabel(value)}</option>)}
                        </select>
                      )}
                    </td>
                    <td data-label="Passagem">
                      <RouteCard
                        route={perc}
                        catalogs={catalogs}
                        label={`Passagem do percurso ${id ?? index + 1}`}
                        disabled={readOnly || id === undefined}
                        onChange={(patch) => {
                          if (id !== undefined) applyAction((current) => engine.actions.setPercRoute(current, { id, ...patch }));
                        }}
                      />
                    </td>
                    {!readOnly && (
                      <td data-label="Ações">
                        {id !== undefined && <button type="button" className="btn btn--sm btn--ghost" aria-label={`Remover percurso ${id}`} onClick={() => applyAction((current) => engine.actions.removePerc(current, { id }))}>Remover</button>}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
