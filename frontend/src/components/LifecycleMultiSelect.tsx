import { useEffect, useId, useRef, useState } from "react";
import type { LifecycleStatus } from "../api/client";
import { IN_PROGRESS_LIFECYCLE } from "../utils/projectFilters";

export default function LifecycleMultiSelect({
  id,
  label,
  value,
  onChange,
  statuses,
}: {
  id: string;
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  statuses: LifecycleStatus[];
}) {
  const summary =
    value.length === 0
      ? "Todos"
      : value.length === IN_PROGRESS_LIFECYCLE.length && IN_PROGRESS_LIFECYCLE.every((code) => value.includes(code))
        ? "Em curso"
        : value.length === 1
          ? (statuses.find((s) => s.code === value[0])?.label ?? value[0])
          : `${value.length} estados`;
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDetailsElement>(null);
  const triggerRef = useRef<HTMLElement>(null);
  const panelId = useId();

  function close() {
    setOpen(false);
    // Focus is restored synchronously so keyboard users can continue from the trigger.
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
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

  return (
    <div className="field">
      <span id={`${id}-label`} className="field__label">
        {label}
      </span>
      <details ref={containerRef} className="multiselect" open={open}>
        <summary
          ref={triggerRef}
          className="select"
          role="button"
          aria-describedby={`${id}-label`}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={(event) => {
            event.preventDefault();
            setOpen((current) => !current);
          }}
        >
          {summary}
        </summary>
        {open && (
          <div id={panelId} className="multiselect__panel" role="group" aria-label={label}>
            <div className="multiselect__quick">
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => onChange([...IN_PROGRESS_LIFECYCLE])}>
                Em curso
              </button>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => onChange([])}>
                Todos
              </button>
            </div>
            {statuses.map((s) => (
              <label key={s.code} className="multiselect__option">
                <input
                  type="checkbox"
                  checked={value.includes(s.code)}
                  onChange={() => onChange(value.includes(s.code) ? value.filter((c) => c !== s.code) : [...value, s.code])}
                />
                {s.label}
              </label>
            ))}
          </div>
        )}
      </details>
      {!open && summary !== "Todos" && (
        <button
          type="button"
          className="sr-only"
          onClick={() => {
            onChange([]);
            setOpen(true);
          }}
        >
          Todos
        </button>
      )}
    </div>
  );
}
