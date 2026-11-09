import { useState } from "react";
import { Card } from "../../../components/ui";
import type { CabosEngine, JsonValue, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";

interface CriteriaPanelProps {
  state: State;
  engine: CabosEngine;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
}

function numericValue(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function updateCriteria(engine: CabosEngine, field: string, value: JsonValue): CableStudyUpdater {
  return (current) => engine.actions.setCriteria(current, { field, value });
}

export default function CriteriaPanel({ state, engine, readOnly, apply }: CriteriaPanelProps) {
  const [invalid, setInvalid] = useState<string | null>(null);
  const regions = engine.catalogs.regions ?? [];
  const materials = engine.catalogs.materials ?? [];
  const soilResistivities = engine.catalogs.soilResistivities ?? [];

  function setNumber(
    field: string,
    value: string,
    min: number,
    max: number,
  ) {
    const next = numericValue(value);
    if (next === null || next < min || next > max) {
      setInvalid(field);
      return;
    }
    setInvalid(null);
    apply(updateCriteria(engine, field, next), { debounce: true });
  }

  function numberError(field: string) {
    return invalid === field ? <span className="cable-field-error" role="alert">Indique um valor entre os limites permitidos.</span> : null;
  }

  return (
    <details className="cable-collapsible" open>
      <summary>Critérios</summary>
      <Card className="cable-form-card" title="Critérios" icon="list">
        <div className="cable-form-grid">
          <div className="field">
            <label htmlFor="cable-regiao">Região</label>
            <select
              id="cable-regiao"
              className="select"
              value={state.loc}
              disabled={readOnly}
              onChange={(event) => apply(updateCriteria(engine, "loc", event.target.value))}
            >
              {regions.map((region) => <option key={region.id} value={region.id}>{region.label}</option>)}
            </select>
            <span className="cable-field-hint">As temperaturas vêm da tabela da região escolhida e não se editam.</span>
          </div>
          <div className="field">
            <label htmlFor="cable-tair">Temperatura ambiente (°C)</label>
            <input id="cable-tair" className="input" type="number" value={state.tair} readOnly aria-readonly="true" />
          </div>
          <div className="field">
            <label htmlFor="cable-tsoil">Temperatura do solo (°C)</label>
            <input id="cable-tsoil" className="input" type="number" value={state.tsoil} readOnly aria-readonly="true" />
          </div>
          <div className="field">
            <label htmlFor="cable-rsolo">Resistividade térmica do solo (52-E6)</label>
            <select
              id="cable-rsolo"
              className="select"
              value={state.rsolo}
              disabled={readOnly}
              onChange={(event) => {
                const next = numericValue(event.target.value);
                if (next !== null) apply(updateCriteria(engine, "rsolo", next));
              }}
            >
              {soilResistivities.map((option) => <option key={String(option[0])} value={option[0]}>{option[2] ?? `${option[0]} K·m/W`}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="cable-mat">Material</label>
            <select
              id="cable-mat"
              className="select"
              value={state.mat}
              disabled={readOnly}
              onChange={(event) => apply(updateCriteria(engine, "mat", event.target.value))}
            >
              <option value="auto">Auto pela distância e potência</option>
              {materials.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              {!materials.some((option) => option.id === "Cu") && <option value="Cu">Sempre cobre</option>}
              {!materials.some((option) => option.id === "Al") && <option value="Al">Sempre alumínio</option>}
            </select>
          </div>
          <div className="field">
            <label htmlFor="cable-althr">Alumínio acima de (m)</label>
            <input id="cable-althr" className="input" type="number" min={0} max={10000} step={1} value={state.alThr} disabled={readOnly} aria-invalid={invalid === "alThr"} onChange={(event) => setNumber("alThr", event.target.value, 0, 10000)} />
            {numberError("alThr")}
          </div>
          <div className="field">
            <label htmlFor="cable-alpmin">Alumínio acima de (kW)</label>
            <input id="cable-alpmin" className="input" type="number" min={0} max={100000} step={1} value={state.alPmin} disabled={readOnly} aria-invalid={invalid === "alPmin"} onChange={(event) => setNumber("alPmin", event.target.value, 0, 100000)} />
            {numberError("alPmin")}
          </div>
          <div className="field cable-checkbox-field">
            <label htmlFor="cable-folga"><input id="cable-folga" type="checkbox" checked={state.folga} disabled={readOnly} onChange={(event) => apply(updateCriteria(engine, "folga", event.target.checked))} /> Folga no comprimento</label>
            <span className="cable-field-hint">+20% abaixo de 30 m; +10% a partir de 30 m.</span>
          </div>
          <div className="field">
            <label htmlFor="cable-limt">ΔU máx. por troço (%)</label>
            <input id="cable-limt" className="input" type="number" min={0.1} max={100} step={0.1} value={state.limT} disabled={readOnly} aria-invalid={invalid === "limT"} onChange={(event) => setNumber("limT", event.target.value, 0.1, 100)} />
            {numberError("limT")}
          </div>
          <div className="field">
            <label htmlFor="cable-lim">Aviso de ΔU acumulada (%)</label>
            <input id="cable-lim" className="input" type="number" min={0.1} max={100} step={0.1} value={state.lim} disabled={readOnly} aria-invalid={invalid === "lim"} onChange={(event) => setNumber("lim", event.target.value, 0.1, 100)} />
            {numberError("lim")}
          </div>
          <div className="field">
            <label htmlFor="cable-deschager">Desconto Hager (% s/ PVP)</label>
            <input id="cable-deschager" className="input" type="number" min={0} max={90} step={1} value={state.descHager} disabled={readOnly} aria-invalid={invalid === "descHager"} onChange={(event) => setNumber("descHager", event.target.value, 0, 90)} />
            {numberError("descHager")}
          </div>
        </div>
        <p className="cable-panel__hint">Cabos com isolamento XLPE e cos φ 1. Material automático: alumínio quando o circuito tem mais de 15 m e mais de 30 kW; nos restantes, cobre. A queda de tensão é verificada em cada troço.</p>
      </Card>
    </details>
  );
}
