import { EMPTY_VALUE, formatNumberPt } from "../../../utils/numbers";
import type { Catalogs, CircuitRow, Result, Route, State } from "../engine";

export const DEFAULT_CONSTITUTIONS = [
  { id: "mono", label: "Monocondutores" },
  { id: "multi", label: "Multicondutor" },
] as const;

export const DEFAULT_DISPOSITIONS = [
  { id: "trevo", label: "Em trevo (triângulo)" },
  { id: "esteira", label: "Em esteira, sem afastamento" },
  { id: "afh", label: "Com afastamento, horizontal" },
  { id: "afv", label: "Com afastamento, vertical" },
] as const;

const SECTION_SIZES = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300];

export type RoutePatch = Partial<Pick<Route, "ref" | "cons" | "disp" | "trays" | "sol">>;

export function numberPt(value: number | null | undefined, suffix = "", digits = 2): string {
  const text = formatNumberPt(value, { max: digits });
  return text === EMPTY_VALUE ? text : `${text}${suffix}`;
}

export function moneyPt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}

export function catalogConstitutions(catalogs: Catalogs): readonly { id: string; label: string }[] {
  return catalogs.constitutions.length > 0 ? catalogs.constitutions : DEFAULT_CONSTITUTIONS;
}

export function catalogDispositions(catalogs: Catalogs): readonly { id: string; label: string }[] {
  return catalogs.dispositions.length > 0 ? catalogs.dispositions : DEFAULT_DISPOSITIONS;
}

export function catalogModes(catalogs: Catalogs) {
  return catalogs.installModes.length > 0
    ? catalogs.installModes
    : [{ id: "13", label: "Ref. 13", description: "Modo de instalação", method: "", group: "", imageId: "13" }];
}

export function sectionOptions(current: string | undefined): string[] {
  const options = new Set<string>(["auto"]);
  for (const size of SECTION_SIZES) {
    for (const material of ["Cu", "Al"] as const) {
      for (const constitution of material === "Al" ? ["mono"] : ["mono", "multi"] as const) {
        options.add(`1x${size}|${material}|${constitution}`);
        if (size >= 70) {
          options.add(`2x${size}|${material}|${constitution}`);
          options.add(`3x${size}|${material}|${constitution}`);
        }
      }
    }
  }
  if (current && current !== "auto") options.add(current);
  return [...options];
}

export function sectionLabel(value: string): string {
  if (value === "auto") return "Auto pelo motor";
  const match = /^(\d+)x([\d.]+)\|(Cu|Al)\|(mono|multi)$/.exec(value);
  if (!match) return value;
  const constitution = match[4] === "mono" ? "monocondutores" : "multicondutor";
  return `${match[1]}×${match[2]} mm² ${match[3]} · ${constitution}`;
}

export function boardOptions(state: State): string[] {
  const values = [
    ...state.percs.flatMap((item) => [item.orig, item.dest]),
    ...state.gws.map((item) => item.nome),
    ...state.invs.map((item) => item.q),
    "QFV",
  ];
  return [...new Set(values.map((value) => String(value ?? "").trim()).filter(Boolean))];
}

export function rowForInverter(rows: readonly CircuitRow[], index: number): CircuitRow | undefined {
  return rows.filter((row) => row.kind === "inv")[index];
}

export function resultCircuitForRow(result: Result, row: CircuitRow): Result["invC"][number] | undefined {
  const invC = Array.isArray(result.invC) ? result.invC : [];
  const pC = Array.isArray(result.pC) ? result.pC : [];
  return [...invC, ...pC].find((circuit) => circuit.code === row.code);
}

export function routeLabel(route: Route | null | undefined, catalogs: Catalogs): string {
  if (!route) return "Sem passagem";
  const mode = catalogModes(catalogs).find((item) => item.id === route.ref);
  return mode ? `Ref. ${mode.id} · ${mode.label}` : `Ref. ${route.ref}`;
}

export function gatewayFor(state: State, node: string): boolean {
  return state.gws.some((gateway) => gateway.nome === node);
}
