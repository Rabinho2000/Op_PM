import type { LifecycleStatus } from "../api/client";
import { IN_PROGRESS_LIFECYCLE, lifecycleView } from "../utils/projectFilters";

// Filtro de estado do projeto: dropdown com caixas de seleção. Lista vazia = todos os estados.
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
  const view = lifecycleView(value);
  const summary =
    view === "in_progress"
      ? "Em curso"
      : view === "all"
        ? "Todos"
        : value.length === 1
          ? (statuses.find((s) => s.code === value[0])?.label ?? value[0])
          : `${value.length} estados`;
  return (
    <div className="field">
      <span id={`${id}-label`} className="field__label">
        {label}
      </span>
      <details className="multiselect">
        <summary className="select" aria-labelledby={`${id}-label`}>
          {summary}
        </summary>
        <div className="multiselect__panel" role="group" aria-labelledby={`${id}-label`}>
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
      </details>
    </div>
  );
}
