import { useEffect, useId, useRef, useState } from "react";
import type { Installer } from "../api/client";
import "./InstallerMultiSelect.css";

type InstallerOption = Pick<Installer, "id" | "name" | "is_active">;

export default function InstallerMultiSelect({
  id,
  label,
  value,
  onChange,
  installers,
}: {
  id: string;
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  installers: InstallerOption[];
}) {
  const summary = value.length === 0
    ? "Todos"
    : value.length === 1
      ? installers.find((installer) => installer.id === value[0])?.name ?? value[0]
      : `${value.length} instaladores`;
  const accessibleSummary = value.length > 1 ? `${value.length} instaladores selecionados` : summary;
  const [open, setOpen] = useState(false);
  const [initialFocus, setInitialFocus] = useState<"first" | "last" | null>(null);
  const containerRef = useRef<HTMLDetailsElement>(null);
  const triggerRef = useRef<HTMLElement>(null);
  const optionRefs = useRef<Array<HTMLInputElement | null>>([]);
  const panelId = useId();

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open || !initialFocus) return;
    const index = initialFocus === "first" ? 0 : installers.length - 1;
    optionRefs.current[index]?.focus();
    setInitialFocus(null);
  }, [initialFocus, installers.length, open]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && containerRef.current?.contains(event.target as Node)) {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function toggle(installerId: string) {
    onChange(value.includes(installerId)
      ? value.filter((selectedId) => selectedId !== installerId)
      : [...value, installerId]);
  }

  return (
    <div className="field installer-multiselect">
      <span id={`${id}-label`} className="field__label">{label}</span>
      <details ref={containerRef} className="multiselect" open={open}>
        <summary
          ref={triggerRef}
          className="select"
          role="button"
          aria-label={`${label}: ${accessibleSummary}`}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={(event) => {
            event.preventDefault();
            setOpen((current) => !current);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setInitialFocus(event.key === "ArrowDown" ? "first" : "last");
              setOpen(true);
              return;
            }
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setOpen((current) => !current);
            }
          }}
        >
          {summary}
        </summary>
        {open && (
          <div id={panelId} className="multiselect__panel installer-multiselect__panel" role="group" aria-label={label}>
            <div className="multiselect__quick">
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => onChange([])}>Todos</button>
            </div>
            {installers.map((installer, index) => (
              <label key={installer.id} className="multiselect__option installer-multiselect__option">
                <input
                  ref={(option) => { optionRefs.current[index] = option; }}
                  type="checkbox"
                  checked={value.includes(installer.id)}
                  onChange={() => toggle(installer.id)}
                  onKeyDown={(event) => {
                    let nextIndex: number;
                    switch (event.key) {
                      case "ArrowDown":
                        nextIndex = Math.min(index + 1, installers.length - 1);
                        break;
                      case "ArrowUp":
                        nextIndex = Math.max(index - 1, 0);
                        break;
                      case "Home":
                        nextIndex = 0;
                        break;
                      case "End":
                        nextIndex = installers.length - 1;
                        break;
                      default:
                        return;
                    }
                    event.preventDefault();
                    optionRefs.current[nextIndex]?.focus();
                  }}
                />
                {installer.name}{installer.is_active ? "" : " (inativo)"}
              </label>
            ))}
          </div>
        )}
      </details>
    </div>
  );
}
