import { useEffect, useMemo, useRef, useState } from "react";
import type { Catalogs, Route } from "../engine";
import { catalogDispositions, catalogModes, routeLabel, type RoutePatch } from "./utils";

interface RouteCardProps {
  route: Route;
  catalogs: Catalogs;
  label: string;
  disabled?: boolean;
  onChange: (patch: RoutePatch) => void;
}

function RoutePicker({ route, catalogs, label, disabled, onSelect }: { route: Route; catalogs: Catalogs; label: string; disabled: boolean; onSelect: (ref: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const modes = catalogModes(catalogs);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("pt-PT");
    return normalized
      ? modes.filter((item) => `${item.id} ${item.label} ${item.description}`.toLocaleLowerCase("pt-PT").includes(normalized))
      : modes;
  }, [modes, query]);

  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  if (disabled) return <span>{routeLabel(route, catalogs)}</span>;
  return (
    <div style={{ position: "relative", minWidth: 190 }}>
      <button type="button" className="btn btn--sm" aria-haspopup="dialog" aria-expanded={open} aria-label={`Alterar passagem — ${label}`} onClick={() => setOpen((value) => !value)}>
        {routeLabel(route, catalogs)}
      </button>
      {open && (
        <div
          className="card"
          role="dialog"
          aria-label="Escolher tipo de passagem"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
            }
            if (event.key === "Enter" && event.target === searchRef.current && filtered.length === 1) {
              event.preventDefault();
              onSelect(filtered[0].id);
              setOpen(false);
              setQuery("");
            }
          }}
          style={{ position: "absolute", zIndex: 20, left: 0, top: "calc(100% + 4px)", width: "min(380px, 82vw)", padding: 12 }}
        >
          <div className="field">
            <label htmlFor={`cable-route-search-${label}`}>Pesquisar modo de instalação</label>
            <input ref={searchRef} id={`cable-route-search-${label}`} className="input" value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8, maxHeight: 260, overflowY: "auto" }}>
            {filtered.map((mode) => (
              <button key={mode.id} type="button" className="btn btn--ghost" style={{ justifyContent: "flex-start", whiteSpace: "normal" }} onClick={() => { onSelect(mode.id); setOpen(false); setQuery(""); }}>
                <span><strong>Ref. {mode.id}</strong> · {mode.label}<br /><span className="muted small">{mode.description}</span></span>
              </button>
            ))}
            {filtered.length === 0 && <span className="muted small">Nenhum modo encontrado.</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function RouteCard({ route, catalogs, label, disabled = false, onChange }: RouteCardProps) {
  const modes = catalogModes(catalogs);
  const mode = modes.find((item) => item.id === route.ref);
  const constitutions = catalogs.constitutions.length > 0 ? catalogs.constitutions : [{ id: "mono", label: "Monocondutores" }, { id: "multi", label: "Multicondutor" }];
  const dispositions = catalogDispositions(catalogs);
  const showDisposition = (mode?.method ?? "") === "EF" && route.cons === "mono";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="field">
        <span className="field__label">{label}</span>
        <RoutePicker route={route} catalogs={catalogs} label={label} disabled={disabled} onSelect={(ref) => onChange({ ref })} />
        {mode?.description && <span className="cable-field-hint">{mode.description}</span>}
      </div>
      <div className="cable-form-grid">
        <div className="field">
          <label htmlFor={`route-cons-${label}`}>{label}: constituição</label>
          {disabled ? <span>{constitutions.find((item) => item.id === route.cons)?.label ?? route.cons}</span> : (
            <select id={`route-cons-${label}`} className="select" value={route.cons} onChange={(event) => onChange({ cons: event.target.value as Route["cons"] })}>
              {constitutions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          )}
        </div>
        {showDisposition && (
          <div className="field">
            <label htmlFor={`route-disp-${label}`}>{label}: disposição</label>
            {disabled ? <span>{dispositions.find((item) => item.id === route.disp)?.label ?? route.disp}</span> : (
              <select id={`route-disp-${label}`} className="select" value={route.disp} onChange={(event) => onChange({ disp: event.target.value as Route["disp"] })}>
                {dispositions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            )}
          </div>
        )}
        <div className="field">
          <label htmlFor={`route-trays-${label}`}>{label}: esteiras sobrepostas</label>
          {disabled ? <span>{route.trays}</span> : (
            <select id={`route-trays-${label}`} className="select" value={route.trays} onChange={(event) => onChange({ trays: Number(event.target.value) })}>
              {[1, 2, 3].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          )}
        </div>
        <div className="field cable-checkbox-field">
          <label htmlFor={`route-sol-${label}`}>
            <input id={`route-sol-${label}`} type="checkbox" checked={route.sol} disabled={disabled} onChange={(event) => onChange({ sol: event.target.checked })} /> Exposto ao sol (+10 °C)
          </label>
        </div>
      </div>
    </div>
  );
}
