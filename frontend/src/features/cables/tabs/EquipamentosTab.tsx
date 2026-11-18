import { useMemo, useState } from "react";
import { Card, EmptyState } from "../../../components/ui";
import type { CabosEngine } from "../engine";
import { equipmentMatches, GatewayCatalogTable, InverterCatalogTable, PanelCatalogTable, type EquipmentKind } from "../equipment/CatalogTable";
import type { CableTabProps } from "./types";

const LABELS: Record<EquipmentKind, string> = {
  inverters: "Inversores",
  gateways: "Gateways",
  panels: "Painéis",
};

function catalogRows(engine: CabosEngine, kind: EquipmentKind) {
  const catalogs = engine.catalogs as Partial<CabosEngine["catalogs"]> | undefined;
  const rows = catalogs?.[kind];
  return Array.isArray(rows) ? rows : [];
}

export default function EquipamentosTab({ engine }: CableTabProps) {
  const [active, setActive] = useState<EquipmentKind>("inverters");
  const [query, setQuery] = useState("");
  const available = (Object.keys(LABELS) as EquipmentKind[]).filter((kind) => Array.isArray((engine.catalogs as Partial<CabosEngine["catalogs"]> | undefined)?.[kind]));
  const selected = available.includes(active) ? active : available[0] ?? null;
  const rows = useMemo(() => {
    if (!selected) return [];
    return catalogRows(engine, selected).filter((row) => equipmentMatches(row as { marca: string; modelo: string }, query));
  }, [engine, query, selected]);

  return (
    <div className="cable-tab cable-tab--equipment">
      <Card title="Base de equipamentos" icon="database">
        <p className="muted cable-tab__hint">Base embutida — não editável nesta versão</p>
        <div className="cable-equipment__tools">
          <label htmlFor="cable-equipment-search">Pesquisar equipamento</label>
          <input id="cable-equipment-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Modelo ou fabricante" />
        </div>
        {available.length > 0 && (
          <div className="tabs cable-equipment__tabs" role="tablist" aria-label="Tipos de equipamento">
            {available.map((kind) => <button key={kind} type="button" role="tab" className="tab" aria-selected={selected === kind} aria-controls={`equipment-panel-${kind}`} onClick={() => setActive(kind)}>{LABELS[kind]}</button>)}
          </div>
        )}
        <section id={selected ? `equipment-panel-${selected}` : "equipment-panel-empty"} role="tabpanel" className="cable-equipment__panel">
          {!selected ? (
            <EmptyState title="Base de equipamentos indisponível" text="O motor não expôs nenhum catálogo nesta versão." icon="database" />
          ) : rows.length === 0 ? (
            <EmptyState title="Sem equipamentos" text={query ? "Nenhum registo corresponde à pesquisa." : "O catálogo selecionado não tem registos."} icon="database" />
          ) : selected === "inverters" ? (
            <InverterCatalogTable rows={rows} />
          ) : selected === "gateways" ? (
            <GatewayCatalogTable rows={rows} />
          ) : (
            <PanelCatalogTable rows={rows} />
          )}
        </section>
      </Card>
    </div>
  );
}
