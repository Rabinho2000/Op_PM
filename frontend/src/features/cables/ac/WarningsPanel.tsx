import { Card, EmptyState } from "../../../components/ui";
import type { Result, State } from "../engine";
import { numberPt } from "./utils";

interface WarningsPanelProps {
  state: State;
  result: Result;
}

interface WarningItem {
  key: string;
  title: string;
  text: string;
}

export default function WarningsPanel({ state, result }: WarningsPanelProps) {
  const warnings: WarningItem[] = [];
  const circuits = [
    ...(Array.isArray(result.invC) ? result.invC : []),
    ...(Array.isArray(result.pC) ? result.pC : []),
  ];
  circuits.forEach((circuit, index) => {
    const label = circuit.code || `C${index + 1}`;
    if (circuit.kind === "inv" && circuit.acc > state.lim && state.lim > 0) {
      warnings.push({
        key: `${label}-acc`,
        title: `${label}: ΔU acumulada`,
        text: `A queda acumulada até à injeção é ${numberPt(circuit.acc, " %", 2)}, acima do aviso de ${numberPt(state.lim, " %", 2)}. Confirme o limite de sobretensão do inversor ou reforce um troço.`,
      });
    }
    if (circuit.sel) {
      warnings.push({
        key: `${label}-sel`,
        title: `${label}: seletividade a confirmar`,
        text: `Seletividade a confirmar: ${numberPt(circuit.sel.In, " A", 0)} a montante < ${numberPt(circuit.sel.k, " ×", 2)} ${numberPt(circuit.sel.dn, " A", 0)} a jusante (${circuit.sel.code}).`,
      });
    }
    if (circuit.res?.ikmax !== undefined && circuit.res.icuOk === false) {
      warnings.push({
        key: `${label}-icu`,
        title: `${label}: poder de corte`,
        text: `Poder de corte insuficiente no local: Icc máxima ${numberPt(circuit.res.ikmax, " kA", 1)}. O veredicto do circuito fica a rever.`,
      });
    }
  });

  return (
    <Card title="Avisos" icon="alert">
      {warnings.length === 0 ? (
        <EmptyState compact icon="checkCircle" title="Sem avisos adicionais" text="As quedas acumuladas, a seletividade e o poder de corte não têm avisos adicionais neste resultado." />
      ) : (
        <ul className="list" aria-label="Avisos do cálculo">
          {warnings.map((warning) => <li key={warning.key} className="list__item"><div className="list__main"><strong className="list__title">{warning.title}</strong><span className="list__meta">{warning.text}</span></div></li>)}
        </ul>
      )}
    </Card>
  );
}
