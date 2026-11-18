import { useEffect, useId, useState } from "react";

interface NumericFieldProps {
  label: string;
  value: number | null | undefined;
  min: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  allowEmpty?: boolean;
  onValid: (value: number | null) => void;
}

export default function NumericField({
  label,
  value,
  min,
  max = Number.POSITIVE_INFINITY,
  step = 1,
  disabled = false,
  allowEmpty = false,
  onValid,
}: NumericFieldProps) {
  const id = useId();
  const [draft, setDraft] = useState(value === null || value === undefined ? "" : String(value));
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    if (!invalid) setDraft(value === null || value === undefined ? "" : String(value));
  }, [invalid, value]);

  const maxLabel = Number.isFinite(max) ? ` e ${max}` : "";
  const validationMessage = `Indique um valor entre ${min}${maxLabel}.`;

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="input"
        type="number"
        inputMode="decimal"
        min={min}
        max={Number.isFinite(max) ? max : undefined}
        step={step}
        value={draft}
        disabled={disabled}
        aria-invalid={invalid}
        onChange={(event) => {
          const nextDraft = event.target.value;
          setDraft(nextDraft);
          if (nextDraft.trim() === "") {
            if (allowEmpty) {
              setInvalid(false);
              onValid(null);
            } else {
              setInvalid(true);
            }
            return;
          }
          const next = Number(nextDraft);
          if (!Number.isFinite(next) || next < min || next > max) {
            setInvalid(true);
            return;
          }
          setInvalid(false);
          onValid(next);
        }}
      />
      {invalid && <span className="cable-field-error" role="alert">{validationMessage}</span>}
    </div>
  );
}
