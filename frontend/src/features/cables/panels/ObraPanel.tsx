import { Card } from "../../../components/ui";
import type { CabosEngine } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import type { State } from "../engine";

interface ObraPanelProps {
  state: State;
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
}

function updateWorkData(engine: CabosEngine, field: string, value: string): CableStudyUpdater {
  return (current) => engine.actions.setWorkData(current, { field, value });
}

export default function ObraPanel({ state, engine, readOnly, apply }: ObraPanelProps) {
  const obra = state.obra;
  return (
    <details className="cable-collapsible" open>
      <summary>Dados da obra</summary>
      <Card className="cable-form-card" title="Dados da obra" icon="folder">
        <p className="cable-panel__hint">Do projeto aberto. Aparecem na legenda do esquema unifilar, no relatório de cálculo e no orçamento.</p>
        <div className="cable-form-grid">
          <div className="field">
            <label htmlFor="cable-proj">Nome do projeto</label>
            <input
              id="cable-proj"
              className="input"
              value={state.proj}
              maxLength={160}
              disabled={readOnly}
              onChange={(event) => apply(updateWorkData(engine, "proj", event.target.value), { debounce: true })}
            />
          </div>
          <div className="field">
            <label htmlFor="cable-cliente">Cliente / dono de obra</label>
            <input
              id="cable-cliente"
              className="input"
              value={obra.cliente ?? ""}
              maxLength={120}
              disabled={readOnly}
              onChange={(event) => apply(updateWorkData(engine, "cliente", event.target.value), { debounce: true })}
            />
          </div>
          <div className="field cable-form-grid__wide">
            <label htmlFor="cable-morada">Morada da instalação</label>
            <input
              id="cable-morada"
              className="input"
              value={obra.morada ?? ""}
              maxLength={160}
              disabled={readOnly}
              onChange={(event) => apply(updateWorkData(engine, "morada", event.target.value), { debounce: true })}
            />
          </div>
          <div className="field">
            <label htmlFor="cable-desenho">N.º do desenho</label>
            <input
              id="cable-desenho"
              className="input"
              value={obra.desenho ?? ""}
              maxLength={40}
              disabled={readOnly}
              onChange={(event) => apply(updateWorkData(engine, "desenho", event.target.value), { debounce: true })}
            />
          </div>
        </div>
      </Card>
    </details>
  );
}
