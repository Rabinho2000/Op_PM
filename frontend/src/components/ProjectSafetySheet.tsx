import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  getSafetySheet,
  getSafetySheetPrintHtml,
  prefillSafetySheetWorkers,
  SafetySheetAccessMethod,
  SafetySheetMeasure,
  SafetySheetPrefillRead,
  SafetySheetRead,
  SafetySheetRisk,
  SafetySheetRoofType,
  SafetySheetUpdate,
  SafetySheetWorker,
  updateSafetySheet,
} from "../api/client";
import { Alert, Card, LoadingState } from "./ui";
import "./ProjectSafetySheet.css";

type SafetySheetFields = Omit<SafetySheetUpdate, "expected_version">;
type ChecklistOption<T extends string> = { value: T; label: string };

const ROOF_OPTIONS: ChecklistOption<SafetySheetRoofType>[] = [
  { value: "telha_ceramica", label: "Telha cerâmica" },
  { value: "chapa_sandwich", label: "Chapa sandwich" },
  { value: "chapa_simples_fibrocimento", label: "Chapa simples / fibrocimento" },
  { value: "laje_terraco", label: "Laje / terraço" },
  { value: "solo", label: "Solo" },
  { value: "outro", label: "Outro" },
];

const ACCESS_OPTIONS: ChecklistOption<SafetySheetAccessMethod>[] = [
  { value: "escada", label: "Escada" },
  { value: "andaime", label: "Andaime" },
  { value: "plataforma_elevatoria", label: "Plataforma elevatória" },
  { value: "outro", label: "Outro" },
];

const RISK_OPTIONS: ChecklistOption<SafetySheetRisk>[] = [
  { value: "queda_altura", label: "Queda em altura" },
  { value: "eletrico_dc_ac", label: "Risco elétrico DC/AC" },
  { value: "fragil_claraboias", label: "Cobertura frágil / claraboias" },
  { value: "condicoes_meteorologicas", label: "Condições meteorológicas" },
  { value: "outro", label: "Outro" },
];

const MEASURE_OPTIONS: ChecklistOption<SafetySheetMeasure>[] = [
  { value: "linha_vida", label: "Linha de vida" },
  { value: "arnes", label: "Arnês" },
  { value: "capacete", label: "Capacete" },
  { value: "luvas_dieleticas", label: "Luvas dielétricas" },
  { value: "calcado", label: "Calçado de segurança" },
  { value: "guarda_corpos", label: "Guarda-corpos" },
  { value: "outro", label: "Outro" },
];

function toFields(sheet: SafetySheetRead): SafetySheetFields {
  return {
    roof_type: sheet.roof_type,
    roof_other: sheet.roof_other,
    approximate_height_m: sheet.approximate_height_m,
    access_method: sheet.access_method,
    access_other: sheet.access_other,
    risks: [...sheet.risks],
    risk_other: sheet.risk_other,
    safety_measures: [...sheet.safety_measures],
    measure_other: sheet.measure_other,
    workers: sheet.workers.map((worker) => ({ ...worker })),
    safety_responsible: sheet.safety_responsible,
    emergency_contacts: sheet.emergency_contacts,
    observations: sheet.observations,
    work_start_date: sheet.work_start_date,
    work_end_date: sheet.work_end_date,
  };
}

function textValue(value: string | null): string {
  return value ?? "";
}

function toggleValue<T extends string>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.detail : fallback;
}

export default function ProjectSafetySheet({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const [sheet, setSheet] = useState<SafetySheetRead | null>(null);
  const [draft, setDraft] = useState<SafetySheetFields | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [prefilling, setPrefilling] = useState(false);
  const [printLoading, setPrintLoading] = useState(false);
  const [suggestion, setSuggestion] = useState<SafetySheetPrefillRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const loadSheet = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSaved(false);
    try {
      const result = await getSafetySheet(projectId);
      setSheet(result);
      setDraft(toFields(result));
      setSuggestion(null);
    } catch (err) {
      setError(errorMessage(err, "Não foi possível carregar a ficha de segurança."));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadSheet();
  }, [loadSheet]);

  function setField<K extends keyof SafetySheetFields>(key: K, value: SafetySheetFields[K]) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setSaved(false);
    setError(null);
  }

  function updateWorker(index: number, change: Partial<SafetySheetWorker>) {
    setDraft((current) =>
      current
        ? {
            ...current,
            workers: current.workers.map((worker, row) => {
              if (row !== index) return worker;
              const renamingLinkedPerson = change.name !== undefined && change.name !== worker.name && worker.person_id !== null;
              return {
                ...worker,
                ...change,
                ...(renamingLinkedPerson ? { person_id: null, installer_id: null, team_id: null } : {}),
              };
            }),
          }
        : current,
    );
    setSaved(false);
    setError(null);
  }

  function addWorker() {
    if (!draft) return;
    setField("workers", [...draft.workers, { person_id: null, name: "", installer_id: null, team_id: null }]);
  }

  function removeWorker(index: number) {
    if (!draft) return;
    setField("workers", draft.workers.filter((_, row) => row !== index));
  }

  async function handlePrefill() {
    setPrefilling(true);
    setError(null);
    setSuggestion(null);
    try {
      setSuggestion(await prefillSafetySheetWorkers(projectId));
    } catch (err) {
      setError(errorMessage(err, "Não foi possível sugerir os trabalhadores das equipas da obra."));
    } finally {
      setPrefilling(false);
    }
  }

  function applySuggestion() {
    if (!suggestion) return;
    setField("workers", suggestion.workers.map((worker) => ({ ...worker })));
    setSuggestion(null);
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sheet || !draft) return;
    if (draft.work_start_date && draft.work_end_date && draft.work_end_date < draft.work_start_date) {
      setError("A data de fim não pode ser anterior à data de início.");
      return;
    }
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await updateSafetySheet(projectId, { expected_version: sheet.version, ...draft });
      setSheet(updated);
      setDraft(toFields(updated));
      setSaved(true);
      setSuggestion(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("A ficha foi alterada por outra pessoa — recarregar");
      } else {
        setError(errorMessage(err, "Não foi possível guardar a ficha de segurança."));
      }
    } finally {
      setSaving(false);
    }
  }

  async function handlePrint() {
    // Abrir a janela durante o gesto do utilizador evita o bloqueio de pop-ups.
    const popup = window.open("", "_blank");
    if (!popup) {
      setError("Não foi possível abrir uma nova janela. Permita pop-ups para imprimir a ficha.");
      return;
    }
    setPrintLoading(true);
    setError(null);
    try {
      const html = await getSafetySheetPrintHtml(projectId);
      popup.document.open();
      popup.document.write(html);
      popup.document.close();
      popup.focus();
    } catch (err) {
      popup.close();
      setError(errorMessage(err, "Não foi possível gerar a ficha para impressão."));
    } finally {
      setPrintLoading(false);
    }
  }

  if (loading) {
    return (
      <Card title="Ficha de segurança da obra">
        <LoadingState rows={4} />
      </Card>
    );
  }

  return (
    <Card
      title="Ficha de segurança da obra"
      actions={
        <button type="button" className="btn btn--sm" onClick={handlePrint} disabled={printLoading}>
          {printLoading ? "A gerar…" : "Gerar ficha (imprimir)"}
        </button>
      }
    >
      {error && (
        <div className="safety-sheet__notice">
          <Alert
            tone="danger"
            action={error === "A ficha foi alterada por outra pessoa — recarregar" ? (
              <button type="button" className="btn btn--sm" onClick={() => void loadSheet()} disabled={loading}>
                Recarregar ficha
              </button>
            ) : undefined}
          >
            {error}
          </Alert>
        </div>
      )}
      {saved && <div className="safety-sheet__notice"><Alert tone="success">Ficha de segurança guardada.</Alert></div>}
      {!sheet || !draft ? (
        <p className="muted">A ficha de segurança não está disponível.</p>
      ) : (
        <form className="safety-sheet__form" onSubmit={handleSave}>
          <fieldset className="form-grid safety-sheet__fields" disabled={!canEdit || saving}>
            <div className="field">
              <label htmlFor="safety-roof-type">Tipo de telhado</label>
              <select
                id="safety-roof-type"
                className="select"
                value={draft.roof_type ?? ""}
                onChange={(event) => setField("roof_type", (event.target.value || null) as SafetySheetRoofType | null)}
              >
                <option value="">— escolha —</option>
                {ROOF_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </div>
            {draft.roof_type === "outro" && (
              <div className="field">
                <label htmlFor="safety-roof-other">Outro tipo de telhado</label>
                <input id="safety-roof-other" className="input" maxLength={2000} value={textValue(draft.roof_other)} onChange={(event) => setField("roof_other", event.target.value || null)} />
              </div>
            )}
            <div className="field">
              <label htmlFor="safety-height">Altura aproximada (m)</label>
              <input id="safety-height" className="input" type="number" min="0" max="1000" step="0.1" value={draft.approximate_height_m ?? ""} onChange={(event) => setField("approximate_height_m", event.target.value === "" ? null : Number(event.target.value))} />
            </div>
            <div className="field">
              <label htmlFor="safety-access">Acesso</label>
              <select
                id="safety-access"
                className="select"
                value={draft.access_method ?? ""}
                onChange={(event) => setField("access_method", (event.target.value || null) as SafetySheetAccessMethod | null)}
              >
                <option value="">— escolha —</option>
                {ACCESS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </div>
            {draft.access_method === "outro" && (
              <div className="field">
                <label htmlFor="safety-access-other">Outro método de acesso</label>
                <input id="safety-access-other" className="input" maxLength={2000} value={textValue(draft.access_other)} onChange={(event) => setField("access_other", event.target.value || null)} />
              </div>
            )}

            <fieldset className="safety-sheet__checklist field span-2">
              <legend>Riscos</legend>
              <div className="safety-sheet__options">
                {RISK_OPTIONS.map((option) => (
                  <label className="safety-sheet__option" key={option.value}>
                    <input type="checkbox" checked={draft.risks.includes(option.value)} onChange={() => setField("risks", toggleValue(draft.risks, option.value))} />
                    {option.label}
                  </label>
                ))}
              </div>
              {draft.risks.includes("outro") && (
                <div className="field safety-sheet__other">
                  <label htmlFor="safety-risk-other">Descrever outro risco</label>
                  <textarea id="safety-risk-other" className="textarea" rows={2} maxLength={2000} value={textValue(draft.risk_other)} onChange={(event) => setField("risk_other", event.target.value || null)} />
                </div>
              )}
            </fieldset>

            <fieldset className="safety-sheet__checklist field span-2">
              <legend>Medidas de segurança / EPI</legend>
              <div className="safety-sheet__options">
                {MEASURE_OPTIONS.map((option) => (
                  <label className="safety-sheet__option" key={option.value}>
                    <input type="checkbox" checked={draft.safety_measures.includes(option.value)} onChange={() => setField("safety_measures", toggleValue(draft.safety_measures, option.value))} />
                    {option.label}
                  </label>
                ))}
              </div>
              {draft.safety_measures.includes("outro") && (
                <div className="field safety-sheet__other">
                  <label htmlFor="safety-measure-other">Descrever outra medida / EPI</label>
                  <textarea id="safety-measure-other" className="textarea" rows={2} maxLength={2000} value={textValue(draft.measure_other)} onChange={(event) => setField("measure_other", event.target.value || null)} />
                </div>
              )}
            </fieldset>

            <fieldset className="safety-sheet__workers field span-2">
              <legend>Trabalhadores</legend>
              {draft.workers.length === 0 && <p className="small muted">Ainda não foram adicionados trabalhadores.</p>}
              {draft.workers.map((worker, index) => (
                <div className="safety-sheet__worker" key={`${worker.person_id ?? "external"}-${worker.team_id ?? "team"}-${index}`}>
                  <div className="field">
                    <label htmlFor={`safety-worker-${index}`}>Nome do trabalhador {index + 1}</label>
                    <input id={`safety-worker-${index}`} className="input" value={worker.name} maxLength={256} required onChange={(event) => updateWorker(index, { name: event.target.value })} />
                  </div>
                  {canEdit && <button type="button" className="btn btn--sm safety-sheet__remove" aria-label={`Remover trabalhador ${index + 1}`} onClick={() => removeWorker(index)}>Remover</button>}
                </div>
              ))}
              {canEdit && (
                <div className="safety-sheet__worker-actions">
                  <button type="button" className="btn btn--sm" onClick={addWorker}>Adicionar trabalhador</button>
                  <button type="button" className="btn btn--sm" onClick={() => void handlePrefill()} disabled={prefilling}>
                    {prefilling ? "A consultar equipas…" : "Preencher a partir das equipas da obra"}
                  </button>
                </div>
              )}
            </fieldset>

            <div className="field">
              <label htmlFor="safety-responsible">Responsável de segurança</label>
              <input id="safety-responsible" className="input" maxLength={256} value={textValue(draft.safety_responsible)} onChange={(event) => setField("safety_responsible", event.target.value || null)} />
            </div>
            <div className="field span-2">
              <label htmlFor="safety-emergency">Contactos de emergência / hospital mais próximo</label>
              <textarea id="safety-emergency" className="textarea" rows={3} maxLength={4000} value={textValue(draft.emergency_contacts)} onChange={(event) => setField("emergency_contacts", event.target.value || null)} />
            </div>
            <div className="field">
              <label htmlFor="safety-start-date">Data de início dos trabalhos</label>
              <input id="safety-start-date" className="input" type="date" max={draft.work_end_date ?? undefined} value={textValue(draft.work_start_date)} onChange={(event) => setField("work_start_date", event.target.value || null)} />
            </div>
            <div className="field">
              <label htmlFor="safety-end-date">Data de fim dos trabalhos</label>
              <input id="safety-end-date" className="input" type="date" min={draft.work_start_date ?? undefined} value={textValue(draft.work_end_date)} onChange={(event) => setField("work_end_date", event.target.value || null)} />
            </div>
            <div className="field span-2">
              <label htmlFor="safety-observations">Observações</label>
              <textarea id="safety-observations" className="textarea" rows={4} maxLength={10000} value={textValue(draft.observations)} onChange={(event) => setField("observations", event.target.value || null)} />
            </div>
          </fieldset>

          {suggestion && (
            <section className="safety-sheet__suggestion" role="region" aria-label="Sugestão de trabalhadores">
              <div>
                <h3>Confirmar trabalhadores sugeridos</h3>
                {suggestion.workers.length === 0 ? (
                  <p className="small muted">Não foram encontrados trabalhadores nas equipas atribuídas.</p>
                ) : (
                  <ul className="list">
                    {suggestion.workers.map((worker, index) => <li className="list__item" key={`${worker.person_id ?? "external"}-${worker.team_id ?? "team"}-${index}`}>{worker.name}</li>)}
                  </ul>
                )}
              </div>
              <div className="cluster">
                <button type="button" className="btn btn--sm" onClick={() => setSuggestion(null)}>Descartar sugestão</button>
                <button type="button" className="btn btn--primary btn--sm" onClick={applySuggestion} disabled={suggestion.workers.length === 0}>Aplicar sugestão à ficha</button>
              </div>
            </section>
          )}

          {!canEdit && <p className="small muted">Sem permissão para editar a ficha; os dados estão em modo de leitura.</p>}
          {canEdit && (
            <div className="safety-sheet__save">
              <button type="submit" className="btn btn--primary" disabled={saving}>
                {saving ? "A guardar…" : "Guardar ficha"}
              </button>
            </div>
          )}
        </form>
      )}
    </Card>
  );
}
