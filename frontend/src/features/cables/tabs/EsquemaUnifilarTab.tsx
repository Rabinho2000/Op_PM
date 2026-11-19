import { Alert, Card, EmptyState, LoadingState } from "../../../components/ui";
import { useExportRunner } from "../download";
import { SldViewer } from "../sld/SldViewer";
import "../cableU3.css";
import type { CableTabProps } from "./types";
import { useEngineValue } from "../useEngineValue";

export default function EsquemaUnifilarTab({ state, result, engine }: CableTabProps) {
  const runner = useExportRunner();
  const hasInverters = (state.invs?.length ?? 0) > 0 || (result.invC?.length ?? 0) > 0;
  const sld = useEngineValue(() => engine.views.sld(state, result), [engine, result, state], hasInverters);
  const rawSvg = sld.value ?? "";

  const exportButton = (label: string, exporter: () => ReturnType<typeof engine.exports.sldSvg>) => (
    <button
      type="button"
      className="btn btn--sm"
      onClick={() => void runner.run(exporter)}
      disabled={runner.isGenerating}
    >
      {runner.isGenerating ? runner.label : label}
    </button>
  );

  return (
    <div className="cable-tab cable-tab--sld">
      <Card
        title="Esquema unifilar"
        icon="activity"
        actions={hasInverters ? (
          <div className="cable-tab__actions">
            {exportButton("Descarregar PDF", () => engine.exports.sldPdf(state, result))}
            {exportButton("Descarregar SVG", () => engine.exports.sldSvg(state, result))}
            {exportButton("Descarregar PNG", () => engine.exports.sldPng(state, result))}
            {exportButton("Descarregar DXF", () => engine.exports.sldDxf(state, result))}
          </div>
        ) : undefined}
      >
        <p className="muted cable-tab__hint">
          Gerado a partir dos inversores, gateways e percursos do separador Cabos AC. Em cada ligação: disjuntor, diferencial, cabo e queda de tensão. Atualiza-se sozinho.
        </p>
        {!hasInverters ? (
          <EmptyState title="Sem inversores para desenhar" text="Adicione um inversor no separador Cabos AC para gerar o esquema unifilar." icon="activity" />
        ) : rawSvg ? (
          <SldViewer rawSvg={rawSvg} />
        ) : sld.pending ? (
          <LoadingState label="A gerar o esquema…" rows={3} />
        ) : (
          <Alert tone="warning">Não foi possível gerar o esquema unifilar.</Alert>
        )}
      </Card>
    </div>
  );
}
