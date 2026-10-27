import { useState } from "react";
import { Card, EmptyState } from "../../../components/ui";
import type { CabosEngine, CircuitRow, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import ModelPicker from "./ModelPicker";
import NumericField from "./NumericField";
import RouteGroupsDialog from "../dialogs/RouteGroupsDialog";
import { boardOptions, numberPt, rowForInverter, sectionLabel, sectionOptions } from "./utils";

interface InvertersTableProps {
  state: State;
  rows: readonly CircuitRow[];
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
}

export default function InvertersTable({ state, rows, engine, readOnly, apply }: InvertersTableProps) {
  const catalogs = engine.catalogs;
  const boards = boardOptions(state);
  const inverterCatalogs = catalogs.inverters ?? [];
  const routeGroups = state.rts ?? [];
  const [manageRoutesOpen, setManageRoutesOpen] = useState(false);

  function applyAction(updater: CableStudyUpdater, debounce = false) {
    apply(updater, debounce ? { debounce: true } : undefined);
  }

  return (
    <>
      <Card
      title="Inversores"
      icon="activity"
      flush
      actions={!readOnly ? (
        <div className="cable-tab__actions">
          <button type="button" className="btn btn--sm" onClick={() => setManageRoutesOpen(true)}>Gerir passagens</button>
          <button type="button" className="btn btn--sm btn--primary" onClick={() => applyAction((current) => engine.actions.addInverter(current))}>Adicionar inversor</button>
        </div>
      ) : undefined}
    >
      {state.invs.length === 0 ? (
        <EmptyState
          icon="activity"
          title="Sem inversores"
          text="Adicione um inversor para iniciar o dimensionamento dos cabos AC."
          compact
          action={!readOnly ? <button type="button" className="btn btn--primary" onClick={() => applyAction((current) => engine.actions.addInverter(current))}>Adicionar inversor</button> : undefined}
        />
      ) : (
        <>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Inversores do estudo</caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Modelo</th>
                  <th scope="col">Pnom (kW)</th>
                  <th scope="col">Iac máx. (A)</th>
                  <th scope="col">Cabo</th>
                  <th scope="col">Passagem</th>
                  <th scope="col">Quadro</th>
                  <th scope="col">Distância (m)</th>
                  <th scope="col">Secção</th>
                  {!readOnly && <th scope="col">Ações</th>}
                </tr>
              </thead>
              <tbody>
                {state.invs.map((inverter, index) => {
                  const id = inverter.id;
                  const circuit = rowForInverter(rows, index);
                  const catalog = inverterCatalogs.find((item) => item.modelo === inverter.modelo);
                  const currentBoards = boards.includes(inverter.q) ? boards : [...boards, inverter.q];
                  const assignedRoute = routeGroups.find((route) => route.id === inverter.rtId);
                  const routeValue = assignedRoute ? String(assignedRoute.id) : "";
                  const key = id ?? `inverter-${index}`;
                  return (
                    <tr key={key}>
                      <td data-label="#">{index + 1}</td>
                      <td data-label="Modelo">
                        {id === undefined || readOnly ? (
                          <span>{inverter.modelo}</span>
                        ) : (
                          <ModelPicker
                            value={inverter.modelo}
                            catalogs={inverterCatalogs}
                            onSelect={(modelo) => applyAction((current) => engine.actions.setInverterModel(current, { id, field: "modelo", value: modelo }))}
                          />
                        )}
                        {inverter.modelo === "__outro" && (
                          readOnly ? <span className="cell-sub">Potência manual: {numberPt(inverter.pman, " kW")}</span> : (
                            <NumericField
                              label={`Potência manual do inversor ${id ?? index + 1} (kW)`}
                              value={inverter.pman}
                              min={0}
                              max={100000}
                              step={0.1}
                              onValid={(value) => {
                                if (id !== undefined && value !== null) applyAction((current) => engine.actions.setInverterPman(current, { id, value }), true);
                              }}
                            />
                          )
                        )}
                      </td>
                      <td data-label="Pnom (kW)" className="nowrap">{numberPt(catalog?.pnom ?? (inverter.modelo === "__outro" ? inverter.pman : null), " kW")}</td>
                      <td data-label="Iac máx. (A)" className="nowrap">{numberPt(catalog?.iacmax ?? catalog?.iac, " A")}{catalog && <span className="cell-sub">{catalog.fases === 1 ? "1F · 230 V" : "3F · 400 V"}</span>}</td>
                      <td data-label="Cabo">
                        {id === undefined || readOnly ? (
                          <span>{inverter.cons === "multi" ? "Multicondutor" : inverter.cons === "mono" ? "Monocondutores" : "Como a passagem"}</span>
                        ) : (
                          <select
                            className="select select--compact"
                            aria-label={`Constituição do cabo do inversor ${id}`}
                            value={inverter.cons ?? "rota"}
                            onChange={(event) => applyAction((current) => engine.actions.setInverterField(current, { id, field: "cons", value: event.target.value }))}
                          >
                            <option value="rota">Como a passagem</option>
                            <option value="mono">Monocondutores</option>
                            <option value="multi">Multicondutor</option>
                          </select>
                        )}
                      </td>
                      <td data-label="Passagem">
                        {id === undefined || readOnly ? <span>{assignedRoute?.nome ?? "Sem passagem"}</span> : (
                          <select
                            className="select select--compact"
                            aria-label={`Passagem do inversor ${id}`}
                            value={routeValue}
                            onChange={(event) => applyAction((current) => engine.actions.assignInverterRoute(current, {
                              id,
                              routeId: event.target.value ? Number(event.target.value) : null,
                            }))}
                          >
                            <option value="">Sem passagem</option>
                            {routeGroups.map((route) => <option key={route.id} value={route.id}>{route.nome}</option>)}
                          </select>
                        )}
                      </td>
                      <td data-label="Quadro">
                        {id === undefined || readOnly ? <span>{inverter.q}</span> : (
                          <select className="select select--compact" aria-label={`Quadro do inversor ${id}`} value={inverter.q} onChange={(event) => applyAction((current) => engine.actions.setInverterBoard(current, { id, value: event.target.value }))}>
                            {currentBoards.map((board) => <option key={board} value={board}>{board}</option>)}
                          </select>
                        )}
                      </td>
                      <td data-label="Distância (m)">
                        {id === undefined || readOnly ? <span>{numberPt(inverter.L, " m")}</span> : (
                          <NumericField
                            label={`Distância do inversor ${id} (m)`}
                            value={inverter.L}
                            min={0}
                            max={10000}
                            step={1}
                            onValid={(value) => {
                              if (value !== null) applyAction((current) => engine.actions.setInverterLength(current, { id, value }), true);
                            }}
                          />
                        )}
                      </td>
                      <td data-label="Secção">
                        {id === undefined || readOnly ? <span>{circuit?.section ? sectionLabel(inverter.S === "auto" ? circuit.section : inverter.S) : sectionLabel(inverter.S)}</span> : (
                          <select className="select select--compact" aria-label={`Secção do inversor ${id}`} value={inverter.S} onChange={(event) => applyAction((current) => engine.actions.setInverterSection(current, { id, value: event.target.value }))}>
                            {sectionOptions(inverter.S).map((value) => <option key={value} value={value}>{sectionLabel(value)}</option>)}
                          </select>
                        )}
                      </td>
                      {!readOnly && (
                        <td data-label="Ações">
                          {id !== undefined && <div className="button-row">
                            <button type="button" className="btn btn--sm btn--ghost" aria-label={`Duplicar inversor ${id}`} onClick={() => applyAction((current) => engine.actions.duplicateInverter(current, { id }))}>Duplicar</button>
                            <button type="button" className="btn btn--sm btn--ghost" aria-label={`Remover inversor ${id}`} onClick={() => applyAction((current) => engine.actions.removeInverter(current, { id }))}>Remover</button>
                          </div>}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
    {manageRoutesOpen && (
      <RouteGroupsDialog
        engine={engine}
        state={state}
        readOnly={readOnly}
        apply={(updater) => apply(updater)}
        onClose={() => setManageRoutesOpen(false)}
      />
    )}
    </>
  );
}
