import { Alert } from "../../../components/ui";
import type { BoardCable, BoardDevice, BoardView, Enclosure } from "../engine";
import { BoardSpaceSvg } from "./BoardSpaceSvg";

function number(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: digits }).format(value);
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("pt-PT", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)} €`;
}

function roleLabel(role: string | undefined): string {
  const labels: Record<string, string> = {
    QFV: "Quadro fotovoltaico",
    INT: "Quadro de interligação",
    CONT: "Quadro de contagem",
    CLI: "Quadro do cliente",
    GW: "Gateway",
  };
  return labels[role ?? ""] ?? role ?? "Quadro";
}

function deviceRows(devices: BoardDevice[]): Array<{ reference: string; description: string; quantity: number }> {
  const grouped = new Map<string, { reference: string; description: string; quantity: number }>();
  for (const device of devices) {
    const reference = device.nome || "—";
    const description = [device.txt, device.dif].filter(Boolean).join(" · ") || "—";
    const key = `${reference}\u0000${description}`;
    const current = grouped.get(key);
    if (current) current.quantity += 1;
    else grouped.set(key, { reference, description, quantity: 1 });
  }
  return [...grouped.values()];
}

interface ComponentItem {
  category: string;
  reference: string;
  description: string;
  quantity: number;
  unitPrice: number | null;
  subtotal: number | null;
}

function componentItems(value: unknown): ComponentItem[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const items = (value as { items?: unknown }).items;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const row = item as Record<string, unknown>;
    const quantity = typeof row.q === "number" && Number.isFinite(row.q) ? row.q : 1;
    const unitPrice = typeof row.pu === "number" && Number.isFinite(row.pu) ? row.pu : null;
    const subtotal = typeof row.total === "number" && Number.isFinite(row.total) ? row.total : null;
    return [{
      category: typeof row.papel === "string" ? row.papel : "",
      reference: typeof row.ref === "string" ? row.ref : "",
      description: typeof row.des === "string" ? row.des : "",
      quantity,
      unitPrice,
      subtotal,
    }];
  });
}

function componentSubtotal(value: unknown, items: ComponentItem[]): number | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const sub = (value as { sub?: unknown }).sub;
    if (typeof sub === "number" && Number.isFinite(sub)) return sub;
  }
  const total = items.reduce((sum, item) => sum + (item.subtotal ?? 0), 0);
  return items.some((item) => item.subtotal !== null) ? total : null;
}

export interface BoardCardProps {
  board: BoardView;
}

export function BoardCard({ board }: BoardCardProps) {
  const devices = board.aparelhagem?.length ? board.aparelhagem : board.devices ?? [];
  const cables = board.cabos?.length ? board.cabos : board.cables ?? [];
  const enclosure: Enclosure | null = board.envolventeMinima ?? board.minimumEnclosure ?? null;
  const maxRadius = Math.max(0, ...cables.map((cable) => Number.isFinite(cable.r) ? cable.r : 0));
  const deviceTable = deviceRows(devices);
  const items = componentItems(board.components);
  const subtotal = componentSubtotal(board.components, items);
  const hasPrices = items.some((item) => item.unitPrice !== null || item.subtotal !== null) || subtotal !== null;

  return (
    <article className="cable-board card" data-testid={`board-${board.node}`}>
      <header className="cable-board__header">
        <div>
          <h3>{board.node}{board.isEnd ? " · ponto de injeção" : ""}</h3>
          <p className="muted small">{roleLabel(board.role)} · {board.inputs?.length ?? 0} entrada{(board.inputs?.length ?? 0) === 1 ? "" : "s"} · {number(board.currentA)} A</p>
        </div>
      </header>

      <div className="cable-board__grid">
        <div className="cable-board__space">
          {enclosure ? (
            <>
              <BoardSpaceSvg enclosure={enclosure} freeCableZoneMm={board.freeCableZoneMm} maxRadiusMm={maxRadius} />
              <p className="muted small"><strong>{number(enclosure.heightMm, 0)} × {number(enclosure.widthMm, 0)} × {number(enclosure.depthMm, 0)} mm</strong> · {enclosure.ref}<br />Envolvente mínima · {board.isEnd ? "quadro existente" : "tipo mural"}</p>
            </>
          ) : (
            <>
              <Alert tone="warning" title="Não cabe num quadro de parede">A aparelhagem ou os cabos requerem um armário de chão, ou confirmação de uma solução equivalente.</Alert>
              <p className="muted small">Envolvente mínima não disponível para esta composição.</p>
            </>
          )}
        </div>

        <div className="cable-board__details">
          <h4>Aparelhagem</h4>
          <div className="table-wrap">
            <table className="table cable-board__table">
              <thead><tr><th>Referência</th><th>Descrição</th><th>Qtd.</th></tr></thead>
              <tbody>
                {deviceTable.length ? deviceTable.map((device) => <tr key={`${device.reference}-${device.description}`}><td>{device.reference}</td><td>{device.description}</td><td>{device.quantity}</td></tr>) : <tr><td colSpan={3} className="muted">Sem aparelhagem registada.</td></tr>}
              </tbody>
            </table>
          </div>

          <h4>Cabos que entram</h4>
          <div className="table-wrap">
            <table className="table cable-board__table">
              <thead><tr><th>Circuito</th><th>Cabo</th><th>Ø aprox.</th><th>Raio mín.</th><th>Condutores</th></tr></thead>
              <tbody>
                {cables.length ? cables.map((cable: BoardCable, index) => <tr key={`${cable.nome}-${index}`}><td>{cable.nome}</td><td>{cable.cabo}</td><td>{number(cable.D, 0)} mm</td><td>{number(cable.r, 0)} mm</td><td>{number(cable.nCond, 0)}</td></tr>) : <tr><td colSpan={5} className="muted">Sem cabos registados.</td></tr>}
              </tbody>
            </table>
          </div>

          <p className="muted small cable-board__radius">Zona livre por baixo da aparelhagem: <strong>{number(board.freeCableZoneMm, 0)} mm</strong> · Bucins: {number(board.glandWidthMm, 0)} mm. Raio de curvatura usado: ≈ 10 × Ø (cabos rígidos; os flexíveis admitem cerca de metade).</p>
          {board.notes?.length > 0 && <ul className="cable-board__notes">{board.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
        </div>
      </div>

      {items.length > 0 && (
        <section className="cable-board__components">
          <h4>Componentes do orçamento{hasPrices ? "" : " (sem preços fornecidos)"}</h4>
          <div className="table-wrap">
            <table className="table cable-board__table">
              <thead><tr><th>Função</th><th>Referência</th><th>Descrição</th><th>Qtd.</th>{hasPrices && <><th>Preço unitário</th><th>Subtotal</th></>}</tr></thead>
              <tbody>
                {items.map((item, index) => <tr key={`${item.reference}-${item.description}-${index}`}><td>{item.category}</td><td>{item.reference}</td><td>{item.description}</td><td>{number(item.quantity, 2)}</td>{hasPrices && <><td>{money(item.unitPrice)}</td><td>{money(item.subtotal)}</td></>}</tr>)}
                {subtotal !== null && <tr><td colSpan={hasPrices ? 5 : 4}><strong>Subtotal do quadro</strong></td><td><strong>{money(subtotal)}</strong></td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <footer className="cable-board__totals" aria-label={`Totais de ${board.node}`}>
        <span>Totais</span><strong>{number(board.currentA)} A</strong><span>{number(board.modules, 0)} módulos</span>{subtotal !== null && <strong>{money(subtotal)}</strong>}
      </footer>
    </article>
  );
}
