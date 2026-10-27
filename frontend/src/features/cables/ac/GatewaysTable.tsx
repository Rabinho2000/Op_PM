import { Card, EmptyState } from "../../../components/ui";
import type { CabosEngine, GatewayState, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import NumericField from "./NumericField";

interface GatewaysTableProps {
  state: State;
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
}

function modelLabel(gateway: GatewayState, engine: CabosEngine): string {
  const catalog = engine.catalogs.gateways.find((item) => item.modelo === gateway.modelo);
  return catalog ? `${catalog.marca} ${catalog.modelo}` : gateway.modelo || "Manual";
}

export default function GatewaysTable({ state, engine, readOnly, apply }: GatewaysTableProps) {
  const catalogs = engine.catalogs.gateways ?? [];

  return (
    <Card
      title="Gateways"
      icon="database"
      flush
      actions={!readOnly ? <button type="button" className="btn btn--sm btn--primary" onClick={() => apply((current) => engine.actions.addGateway(current))}>Adicionar gateway</button> : undefined}
    >
      {state.gws.length === 0 ? (
        <EmptyState
          icon="database"
          title="Sem gateways"
          text="Se existir um gateway entre os inversores e a rede, adicione-o para criar os percursos e validar a corrente nominal."
          compact
          action={!readOnly ? <button type="button" className="btn btn--primary" onClick={() => apply((current) => engine.actions.addGateway(current))}>Adicionar gateway</button> : undefined}
        />
      ) : (
        <>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Gateways do estudo</caption>
              <thead>
                <tr>
                  <th scope="col">Nome</th>
                  <th scope="col">Modelo</th>
                  <th scope="col">Rede</th>
                  <th scope="col">Corrente nominal (A)</th>
                  <th scope="col">Dimensionamento</th>
                  {!readOnly && <th scope="col">Ações</th>}
                </tr>
              </thead>
              <tbody>
                {state.gws.map((gateway, index) => {
                  const id = gateway.id ?? index + 1;
                  const gatewayModels = catalogs.some((item) => item.modelo === gateway.modelo) || !gateway.modelo
                    ? catalogs
                    : [...catalogs, { marca: "", modelo: gateway.modelo, gama: "", fases: gateway.fases, In: gateway.In, P: 0, ports: 0, portI: 0, base: false }];
                  return (
                    <tr key={id}>
                      <td data-label="Nome">
                        {readOnly ? <span>{gateway.nome}</span> : <input className="input" aria-label="Nome do gateway" value={gateway.nome} onChange={(event) => apply((current) => engine.actions.setGatewayField(current, { id, field: "nome", value: event.target.value }))} />}
                      </td>
                      <td data-label="Modelo">
                        {readOnly ? <span>{modelLabel(gateway, engine)}</span> : (
                          <select className="select" aria-label="Modelo do gateway" value={gateway.modelo} onChange={(event) => apply((current) => engine.actions.configureGateway(current, { id, field: "modelo", value: event.target.value }))}>
                            <option value="">Manual</option>
                            {gatewayModels.map((model) => <option key={model.modelo} value={model.modelo}>{model.marca ? `${model.marca} · ` : ""}{model.modelo}</option>)}
                          </select>
                        )}
                      </td>
                      <td data-label="Rede">
                        {readOnly ? <span>{gateway.fases === 1 ? "Monofásico 230 V" : "Trifásico 400 V"}</span> : (
                          <select className="select" aria-label="Rede do gateway" value={gateway.fases} onChange={(event) => apply((current) => engine.actions.configureGateway(current, { id, field: "fases", value: Number(event.target.value) }))}>
                            <option value={3}>Trifásico 400 V</option>
                            <option value={1}>Monofásico 230 V</option>
                          </select>
                        )}
                      </td>
                      <td data-label="Corrente nominal (A)">
                        {readOnly ? <span>{gateway.In} A</span> : (
                          <NumericField
                            label={`Corrente nominal do gateway ${id} (A)`}
                            value={gateway.In}
                            min={1}
                            max={100000}
                            step={1}
                            onValid={(value) => {
                              if (value !== null) apply((current) => engine.actions.configureGateway(current, { id, field: "In", value }), { debounce: true });
                            }}
                          />
                        )}
                      </td>
                      <td data-label="Dimensionamento">
                        {readOnly ? <span>{gateway.dimNom !== false ? "Pela corrente nominal" : "Pela corrente dos inversores"}</span> : (
                          <label className="checkbox">
                            <input type="checkbox" aria-label="Cabo de saída pela corrente nominal" checked={gateway.dimNom !== false} onChange={(event) => apply((current) => engine.actions.configureGateway(current, { id, field: "dimNom", value: event.target.checked }))} />
                            Pela corrente nominal
                          </label>
                        )}
                      </td>
                      {!readOnly && <td data-label="Ações"><button type="button" className="btn btn--sm btn--ghost" aria-label={`Remover gateway ${id}`} onClick={() => apply((current) => engine.actions.removeGateway(current, { id }))}>Remover</button></td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="cable-panel__hint">A corrente dos inversores ligados ao gateway é verificada contra a corrente nominal configurada. Por defeito, a saída pode ser dimensionada pela corrente nominal do gateway.</p>
        </>
      )}
    </Card>
  );
}
