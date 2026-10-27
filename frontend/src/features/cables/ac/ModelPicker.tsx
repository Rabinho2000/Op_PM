import { useEffect, useMemo, useRef, useState } from "react";
import type { InverterCatalog } from "../engine";

interface ModelPickerProps {
  value: string;
  catalogs: readonly InverterCatalog[];
  disabled?: boolean;
  onSelect: (model: string) => void;
}

function modelLabel(model: string, catalogs: readonly InverterCatalog[]): string {
  const selected = catalogs.find((item) => item.modelo === model);
  if (!selected) return model === "__outro" ? "Outro (potência manual)" : model || "Escolher modelo";
  return `${selected.modelo} · ${selected.pnom} kW${selected.fases === 1 ? " · 1F" : ""}`;
}

export default function ModelPicker({ value, catalogs, disabled = false, onSelect }: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("pt-PT");
    if (!normalized) return catalogs;
    return catalogs.filter((item) => `${item.marca} ${item.modelo}`.toLocaleLowerCase("pt-PT").includes(normalized));
  }, [catalogs, query]);

  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  function choose(model: string) {
    onSelect(model);
    setOpen(false);
    setQuery("");
  }

  if (disabled) return <span>{modelLabel(value, catalogs)}</span>;

  return (
    <div style={{ position: "relative", minWidth: 190 }}>
      <button
        type="button"
        className="btn btn--sm"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Escolher modelo do inversor ${value || "novo"}`}
        onClick={() => setOpen((current) => !current)}
      >
        {modelLabel(value, catalogs)}
      </button>
      {open && (
        <div
          className="card"
          role="dialog"
          aria-label="Escolher modelo de inversor"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              return;
            }
            if (event.key === "Enter" && event.target === searchRef.current && filtered.length === 1) {
              event.preventDefault();
              choose(filtered[0].modelo);
            }
          }}
          style={{ position: "absolute", zIndex: 20, left: 0, top: "calc(100% + 4px)", width: "min(360px, 82vw)", padding: 12 }}
        >
          <div className="field">
            <label htmlFor="cable-model-search">Pesquisar modelo de inversor</label>
            <input
              ref={searchRef}
              id="cable-model-search"
              className="input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Marca ou modelo"
              autoComplete="off"
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8, maxHeight: 260, overflowY: "auto" }}>
            {filtered.map((item) => (
              <button key={item.modelo} type="button" className="btn btn--ghost" style={{ justifyContent: "flex-start", whiteSpace: "normal" }} onClick={() => choose(item.modelo)}>
                <span><strong>{item.modelo}</strong> · {item.marca} · {item.pnom} kW{item.fases === 1 ? " · 1F" : ""}</span>
              </button>
            ))}
            <button type="button" className="btn btn--ghost" style={{ justifyContent: "flex-start" }} onClick={() => choose("__outro")}>
              Outro (potência manual)
            </button>
            {filtered.length === 0 && <span className="muted small">Nenhum modelo encontrado.</span>}
          </div>
          <p className="muted small" style={{ margin: "8px 0 0" }}>Enter escolhe o único resultado; Esc fecha.</p>
        </div>
      )}
    </div>
  );
}
