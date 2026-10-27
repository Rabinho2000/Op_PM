import { useState } from "react";
import { Alert, Badge, Card } from "../../../components/ui";
import ObraPanel from "../panels/ObraPanel";
import CriteriaPanel from "../panels/CriteriaPanel";
import type { CableTabProps } from "./types";
import GatewaysTable from "../ac/GatewaysTable";
import InvertersTable from "../ac/InvertersTable";
import PercursosTable from "../ac/PercursosTable";
import ResultsTable from "../ac/ResultsTable";
import WarningsPanel from "../ac/WarningsPanel";
import { numberPt } from "../ac/utils";
import CompareDialog from "../dialogs/CompareDialog";
import NewBoardDialog from "../dialogs/NewBoardDialog";
import TemplatesDialog from "../dialogs/TemplatesDialog";
import "../cableU4.css";

function SummaryCards({ summary }: { summary: ReturnType<CableTabProps["engine"]["summarize"]> }) {
  return (
    <div className="cable-summary-cards" aria-label="Resumo do cálculo">
      <Card className="cable-summary-card" title="Inversores" icon="activity">
        <strong>{numberPt(summary.inverters)}</strong>
        <span>{numberPt(summary.powerKW, " kW")}</span>
      </Card>
      <Card className="cable-summary-card" title="Corrente total" icon="activity">
        <strong>{numberPt(summary.currentA, " A")}</strong>
        <span>Ligação: {numberPt(summary.connectionBreakerA, " A")}</span>
      </Card>
      <Card className="cable-summary-card" title="Queda de tensão máxima" icon="activity">
        <strong>{numberPt(summary.maxVoltageDropPct, " %")}</strong>
        <span>{numberPt(summary.maxVoltageDrop, " V")}</span>
      </Card>
      <Card className="cable-summary-card" title="Cabos e terminais" icon="link">
        <strong>{numberPt(summary.cablesAndTerminals, " €", 0)}</strong>
        <span>{numberPt(summary.cables, " €", 0)} cabos · {numberPt(summary.terminals, " €", 0)} terminais</span>
      </Card>
      <Card className="cable-summary-card" title="Verificação" icon={summary.reviewCount > 0 ? "alert" : "checkCircle"}>
        <strong><Badge tone={summary.reviewCount > 0 ? "warning" : "success"}>{summary.reviewCount > 0 ? `${summary.reviewCount} a rever` : "Sem alertas"}</Badge></strong>
        <span>{summary.shortCircuit.verified ? "Curto-circuito verificado" : "Curto-circuito não verificado"}{summary.estimated ? " · inclui estimativas" : ""}</span>
      </Card>
    </div>
  );
}

export default function CabosACTab({ state, result, engine, readOnly, apply }: CableTabProps) {
  const [compareOpen, setCompareOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [newBoardOpen, setNewBoardOpen] = useState(false);
  const summary = engine.summarize(result, state);
  const rows = engine.views.circuitRows(state, result) ?? [];

  return (
    <div className="cable-tab cable-tab--ac">
      <header className="cable-tab__header">
        <div>
          <h2>Cabos AC</h2>
          <p className="muted">Dimensionamento, percursos e alternativas do estudo atual.</p>
        </div>
        <div className="cable-tab__actions" aria-label="Ferramentas dos cabos AC">
          <button type="button" className="btn btn--sm" onClick={() => setCompareOpen(true)} disabled={readOnly}>Comparar alternativas</button>
          <button type="button" className="btn btn--sm" onClick={() => setTemplatesOpen(true)} disabled={readOnly}>Modelos</button>
        </div>
      </header>
      <div className="cable-panels-stack">
        <ObraPanel state={state} engine={engine} readOnly={readOnly} apply={apply} />
        <CriteriaPanel state={state} engine={engine} readOnly={readOnly} apply={apply} />
      </div>

      <SummaryCards summary={summary} />

      {summary.reviewCount > 0 && (
        <Alert tone="warning" title={`${summary.reviewCount} circuito${summary.reviewCount === 1 ? "" : "s"} a rever`}>
          O cálculo continua disponível. Consulte o veredicto e a mensagem de cada circuito antes de guardar ou aprovar.
        </Alert>
      )}

      <InvertersTable state={state} rows={rows} engine={engine} readOnly={readOnly} apply={apply} />
      <PercursosTable state={state} rows={rows} engine={engine} readOnly={readOnly} apply={apply} onAddBoard={() => setNewBoardOpen(true)} />
      <ResultsTable state={state} result={result} rows={rows} engine={engine} />
      <GatewaysTable state={state} engine={engine} readOnly={readOnly} apply={apply} />
      <WarningsPanel state={state} result={result} />
      {compareOpen && <CompareDialog engine={engine} state={state} readOnly={readOnly} apply={apply} onClose={() => setCompareOpen(false)} />}
      {templatesOpen && <TemplatesDialog engine={engine} state={state} readOnly={readOnly} apply={apply} onClose={() => setTemplatesOpen(false)} />}
      {newBoardOpen && <NewBoardDialog engine={engine} state={state} readOnly={readOnly} apply={apply} onClose={() => setNewBoardOpen(false)} />}
    </div>
  );
}
