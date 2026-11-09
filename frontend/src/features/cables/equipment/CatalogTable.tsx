import type { ReactNode } from "react";
import type { GatewayCatalog, InverterCatalog, PanelCatalog } from "../engine";

export type EquipmentKind = "inverters" | "gateways" | "panels";

export function formatCatalogValue(value: number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 2 }).format(value)}${suffix}`;
}

export function equipmentMatches(value: { marca: string; modelo: string }, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase("pt-PT");
  return !needle || `${value.marca} ${value.modelo}`.toLocaleLowerCase("pt-PT").includes(needle);
}

function Table({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="table-wrap" data-testid="equipment-table">
      <table className="table cable-equipment__table">
        <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function InverterCatalogTable({ rows }: { rows: readonly InverterCatalog[] }) {
  return (
    <Table headers={["Marca", "Modelo", "Pnom", "Smax", "Iac nom.", "Iac máx.", "Fases", "MPPT", "Entradas/MPPT", "Imax MPPT", "Isc MPPT", "Vmax DC", "V arranque", "MPP mín.", "MPP máx."]}>
      {rows.map((row) => <tr key={`${row.marca}-${row.modelo}`}><td>{row.marca}</td><td><strong>{row.modelo}</strong>{row.conf && <span className="muted small"> · a confirmar</span>}</td><td>{formatCatalogValue(row.pnom, " kW")}</td><td>{formatCatalogValue(row.pmax, " kVA")}</td><td>{formatCatalogValue(row.iac, " A")}</td><td>{formatCatalogValue(row.iacmax, " A")}</td><td>{row.fases === 1 ? "1F" : row.fases === 3 ? "3F" : formatCatalogValue(row.fases)}</td><td>{formatCatalogValue(row.mppt)}</td><td>{formatCatalogValue(row.cc)}</td><td>{formatCatalogValue(row.imax, " A")}</td><td>{formatCatalogValue(row.isc, " A")}</td><td>{formatCatalogValue(row.vmax, " V")}</td><td>{formatCatalogValue(row.vstart, " V")}</td><td>{formatCatalogValue(row.vmppmin, " V")}</td><td>{formatCatalogValue(row.vmppmax, " V")}</td></tr>)}
    </Table>
  );
}

export function GatewayCatalogTable({ rows }: { rows: readonly GatewayCatalog[] }) {
  return (
    <Table headers={["Marca", "Modelo", "Gama", "Fases", "In", "Potência", "Entradas", "In por entrada", "Base"]}>
      {rows.map((row) => <tr key={`${row.marca}-${row.modelo}`}><td>{row.marca}</td><td><strong>{row.modelo}</strong></td><td>{row.gama || "—"}</td><td>{row.fases === 1 ? "1F" : row.fases === 3 ? "3F" : formatCatalogValue(row.fases)}</td><td>{formatCatalogValue(row.In, " A")}</td><td>{formatCatalogValue(row.P, " kW")}</td><td>{formatCatalogValue(row.ports)}</td><td>{formatCatalogValue(row.portI, " A")}</td><td>{row.base ? "Sim" : "Não"}</td></tr>)}
    </Table>
  );
}

export function PanelCatalogTable({ rows }: { rows: readonly PanelCatalog[] }) {
  return (
    <Table headers={["Marca", "Modelo", "Pmax", "Células", "Vmp", "Imp", "Voc", "Isc", "kVoc", "kIsc", "kP", "Eficiência"]}>
      {rows.map((row) => <tr key={`${row.marca}-${row.modelo}`}><td>{row.marca}</td><td><strong>{row.modelo}</strong></td><td>{formatCatalogValue(row.pmax, " W")}</td><td>{formatCatalogValue(row.cel)}</td><td>{formatCatalogValue(row.vmp, " V")}</td><td>{formatCatalogValue(row.imp, " A")}</td><td>{formatCatalogValue(row.voc, " V")}</td><td>{formatCatalogValue(row.isc, " A")}</td><td>{formatCatalogValue(row.kvoc, " %/°C")}</td><td>{formatCatalogValue(row.kisc, " %/°C")}</td><td>{formatCatalogValue(row.kp, " %/°C")}</td><td>{formatCatalogValue(row.ef, " %")}</td></tr>)}
    </Table>
  );
}
