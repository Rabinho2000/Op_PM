import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  checkProjectName,
  createProject,
  LifecycleStatus,
  EligibleProjectManager,
  listEligibleProjectManagers,
  ProjectCreateInput,
  ProjectNameCandidate,
} from "../api/client";
import { Modal } from "./ui";
import { ApiError } from "../api/client";
import { errorDetail } from "../utils/errors";

type Draft = Record<
  | "name"
  | "client_name"
  | "client_contact"
  | "client_email"
  | "address"
  | "lat"
  | "lon"
  | "power_kwp"
  | "power_raw"
  | "pm_person_id"
  | "start_date"
  | "lifecycle_status"
  | "role"
  | "equipment_notes"
  | "injection_notes"
  | "om_notes"
  | "commercial_assumptions"
  | "award_year_raw"
  | "notes",
  string
>;

const EMPTY_DRAFT: Draft = {
  name: "",
  client_name: "",
  client_contact: "",
  client_email: "",
  address: "",
  lat: "",
  lon: "",
  power_kwp: "",
  power_raw: "",
  pm_person_id: "",
  start_date: "",
  lifecycle_status: "on_hold_cliente",
  role: "",
  equipment_notes: "",
  injection_notes: "",
  om_notes: "",
  commercial_assumptions: "",
  award_year_raw: "",
  notes: "",
};

type NameCheck = {
  name: string;
  status: "loading" | "ready" | "error";
  candidates: ProjectNameCandidate[];
};

function normalizeName(value: string): string {
  return value.normalize("NFKD").replace(/\p{M}/gu, "").trim().split(/\s+/).filter(Boolean).join(" ").toLowerCase();
}

function projectNumericPrefix(value: string): string | null {
  return value.match(/^\s*(\d+)_/)?.[1] ?? null;
}

function queryNumericPrefix(value: string): string | null {
  return value.match(/^\s*(\d+)(?:_|\s+)/)?.[1] ?? null;
}

export default function CreateProjectModal({
  statuses,
  onClose,
  onCreated,
}: {
  statuses: LifecycleStatus[];
  onClose: () => void;
  onCreated: (projectId: string) => void;
}) {
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [nameCheck, setNameCheck] = useState<NameCheck | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [numericErrors, setNumericErrors] = useState<Partial<Record<"lat" | "lon" | "power_kwp", string>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [eligibleManagers, setEligibleManagers] = useState<EligibleProjectManager[]>([]);
  const [managersLoading, setManagersLoading] = useState(true);
  const [managersError, setManagersError] = useState<string | null>(null);
  const trimmedName = draft.name.trim();

  useEffect(() => {
    let cancelled = false;
    listEligibleProjectManagers()
      .then((managers) => {
        if (!cancelled) setEligibleManagers(managers);
      })
      .catch((error) => {
        if (!cancelled) setManagersError(errorDetail(error, "Não foi possível criar o projeto."));
      })
      .finally(() => {
        if (!cancelled) setManagersLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!trimmedName || trimmedName.length > 512) {
      setNameCheck(null);
      return undefined;
    }
    let cancelled = false;
    const name = trimmedName;
    setNameCheck({ name, status: "loading", candidates: [] });
    const timer = window.setTimeout(() => {
      checkProjectName(name)
        .then((candidates) => {
          if (!cancelled) setNameCheck({ name, status: "ready", candidates });
        })
        .catch(() => {
          if (!cancelled) setNameCheck({ name, status: "error", candidates: [] });
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [trimmedName]);

  const currentCandidates = nameCheck?.name === trimmedName && nameCheck.status === "ready"
    ? nameCheck.candidates
    : [];
  const duplicateCandidates = useMemo(
    () => currentCandidates.filter((candidate) => normalizeName(candidate.name) === normalizeName(trimmedName)),
    [currentCandidates, trimmedName],
  );
  const prefix = queryNumericPrefix(trimmedName);
  const repeatedPrefixCandidates = useMemo(
    () => currentCandidates.filter((candidate) => projectNumericPrefix(candidate.name) === prefix
      && normalizeName(candidate.name) !== normalizeName(trimmedName)),
    [currentCandidates, prefix, trimmedName],
  );
  const nameChecking = Boolean(trimmedName)
    && nameCheck?.name !== trimmedName;
  const nameCheckPending = nameCheck?.name === trimmedName && nameCheck.status === "loading";

  function update<K extends keyof Draft>(field: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
    if (field === "name") setNameError(null);
    setSubmitError(null);
    setNumericErrors({});
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedName) {
      setNameError("Indique o nome do projeto.");
      return;
    }
    if (trimmedName.length > 512) {
      setNameError("O nome pode ter no máximo 512 caracteres.");
      return;
    }
    if (duplicateCandidates.length > 0) {
      setNameError("Já existe um projeto com este nome. Escolha outro nome.");
      return;
    }

    const limits = {
      lat: { min: -90, max: 90, label: "Latitude" },
      lon: { min: -180, max: 180, label: "Longitude" },
      power_kwp: { min: 0, max: Number.POSITIVE_INFINITY, label: "Potência" },
    } as const;
    const nextNumericErrors: typeof numericErrors = {};
    for (const field of ["lat", "lon", "power_kwp"] as const) {
      if (!draft[field].trim()) continue;
      const value = Number(draft[field]);
      const { min, max, label } = limits[field];
      if (!Number.isFinite(value) || value < min || value > max) {
        nextNumericErrors[field] = field === "power_kwp"
          ? `${label} deve ser um número igual ou superior a ${min}.`
          : `${label} deve estar entre ${min} e ${max}.`;
      }
    }
    if (Object.keys(nextNumericErrors).length > 0) {
      setNumericErrors(nextNumericErrors);
      return;
    }

    const payload: ProjectCreateInput = { name: trimmedName };
    const textFields = [
      "client_name", "client_contact", "client_email", "address", "power_raw", "role",
      "equipment_notes", "injection_notes", "om_notes", "commercial_assumptions", "award_year_raw", "notes",
    ] as const;
    for (const field of textFields) {
      const value = draft[field].trim();
      if (value) payload[field] = value;
    }
    if (draft.pm_person_id) payload.pm_person_id = draft.pm_person_id;
    if (draft.start_date) payload.start_date = draft.start_date;
    payload.lifecycle_status = draft.lifecycle_status || null;
    for (const field of ["lat", "lon", "power_kwp"] as const) {
      if (!draft[field].trim()) continue;
      const value = Number(draft[field]);
      payload[field] = value;
    }

    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await createProject(payload);
      onCreated(created.id);
    } catch (error) {
      setSubmitError(errorDetail(error, "Não foi possível criar o projeto."));
    } finally {
      setSubmitting(false);
    }
  }

  function requestClose() {
    if (!submitting) onClose();
  }

  const describedBy = [
    nameError && "create-project-name-error",
    (nameChecking || nameCheckPending) && "create-project-name-checking",
    duplicateCandidates.length > 0 && "create-project-name-duplicate",
    repeatedPrefixCandidates.length > 0 && duplicateCandidates.length === 0 && "create-project-name-prefix",
    nameCheck?.name === trimmedName && nameCheck.status === "error" && "create-project-name-check-error",
  ].filter(Boolean).join(" ") || undefined;

  return (
    <Modal
      title="Novo projeto"
      onClose={requestClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={requestClose} disabled={submitting}>Cancelar</button>
          <button
            type="submit"
            form="create-project-form"
            className="btn btn--primary"
            disabled={submitting || nameChecking || nameCheckPending || duplicateCandidates.length > 0}
          >
            {submitting ? "A criar…" : "Criar projeto"}
          </button>
        </>
      }
    >
      <form id="create-project-form" className="projects-create" noValidate onSubmit={(event) => void submit(event)}>
        <fieldset className="projects-create__section">
          <legend>Identificação</legend>
          <div className="projects-create__grid">
            <div className="field projects-create__wide">
              <label htmlFor="create-project-name">Nome do projeto *</label>
              <input
                id="create-project-name"
                className="input"
                value={draft.name}
                maxLength={512}
                aria-required="true"
                aria-invalid={Boolean(nameError || duplicateCandidates.length > 0)}
                aria-describedby={describedBy}
                onChange={(event) => update("name", event.target.value)}
              />
              {nameError && <span id="create-project-name-error" className="small text-danger" role="alert">{nameError}</span>}
              {(nameChecking || nameCheckPending) && <span id="create-project-name-checking" className="small muted" role="status">A verificar nome…</span>}
              {duplicateCandidates.length > 0 && (
                <span id="create-project-name-duplicate" className="small text-danger" role="alert">
                  Já existe um projeto com este nome: {duplicateCandidates.map((candidate) => candidate.name).join(", ")}.
                </span>
              )}
              {repeatedPrefixCandidates.length > 0 && duplicateCandidates.length === 0 && (
                <span id="create-project-name-prefix" className="small" role="status">
                  Este número já aparece noutro projeto ({repeatedPrefixCandidates.map((candidate) => candidate.name).join(", ")}). Pode continuar se for outra fase.
                </span>
              )}
              {nameCheck?.name === trimmedName && nameCheck.status === "error" && (
                <span id="create-project-name-check-error" className="small muted" role="status">Não foi possível verificar duplicados; o servidor valida o nome ao criar.</span>
              )}
            </div>
            <div className="field"><label htmlFor="create-project-client">Cliente</label><input id="create-project-client" className="input" value={draft.client_name} onChange={(event) => update("client_name", event.target.value)} /></div>
            <div className="field"><label htmlFor="create-project-contact">Contacto</label><input id="create-project-contact" className="input" value={draft.client_contact} onChange={(event) => update("client_contact", event.target.value)} /></div>
            <div className="field"><label htmlFor="create-project-email">Email</label><input id="create-project-email" className="input" type="email" value={draft.client_email} onChange={(event) => update("client_email", event.target.value)} /></div>
            <div className="field projects-create__wide"><label htmlFor="create-project-address">Morada</label><input id="create-project-address" className="input" value={draft.address} onChange={(event) => update("address", event.target.value)} /></div>
            <div className="field"><label htmlFor="create-project-lat">Latitude</label><input id="create-project-lat" className="input" type="number" step="any" value={draft.lat} aria-invalid={Boolean(numericErrors.lat)} aria-describedby={numericErrors.lat ? "create-project-lat-error" : undefined} onChange={(event) => update("lat", event.target.value)} />{numericErrors.lat && <span id="create-project-lat-error" className="small text-danger" role="alert">{numericErrors.lat}</span>}</div>
            <div className="field"><label htmlFor="create-project-lon">Longitude</label><input id="create-project-lon" className="input" type="number" step="any" value={draft.lon} aria-invalid={Boolean(numericErrors.lon)} aria-describedby={numericErrors.lon ? "create-project-lon-error" : undefined} onChange={(event) => update("lon", event.target.value)} />{numericErrors.lon && <span id="create-project-lon-error" className="small text-danger" role="alert">{numericErrors.lon}</span>}</div>
          </div>
        </fieldset>

        <fieldset className="projects-create__section">
          <legend>Projeto</legend>
          <div className="projects-create__grid">
            <div className="field"><label htmlFor="create-project-power">Potência (kWp)</label><input id="create-project-power" className="input" type="number" step="any" value={draft.power_kwp} aria-invalid={Boolean(numericErrors.power_kwp)} aria-describedby={numericErrors.power_kwp ? "create-project-power-error" : undefined} onChange={(event) => update("power_kwp", event.target.value)} />{numericErrors.power_kwp && <span id="create-project-power-error" className="small text-danger" role="alert">{numericErrors.power_kwp}</span>}</div>
            <div className="field"><label htmlFor="create-project-power-raw">Potência original</label><input id="create-project-power-raw" className="input" value={draft.power_raw} onChange={(event) => update("power_raw", event.target.value)} /></div>
            <div className="field"><label htmlFor="create-project-pm">PM</label><select id="create-project-pm" className="select" value={draft.pm_person_id} onChange={(event) => update("pm_person_id", event.target.value)} disabled={managersLoading || Boolean(managersError)}><option value="">Sem PM</option>{eligibleManagers.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select>{managersLoading && <span className="small" role="status">A carregar gestores de projeto…</span>}{managersError && <span className="small text-danger" role="alert">Não foi possível carregar os gestores de projeto.</span>}</div>
            <div className="field"><label htmlFor="create-project-start">Data de início</label><input id="create-project-start" className="input" type="date" value={draft.start_date} onChange={(event) => update("start_date", event.target.value)} /></div>
            <div className="field"><label htmlFor="create-project-lifecycle">Estado do projeto</label><select id="create-project-lifecycle" className="select" value={draft.lifecycle_status} onChange={(event) => update("lifecycle_status", event.target.value)}><option value="">Sem estado</option>{statuses.map((status) => <option key={status.code} value={status.code}>{status.label}</option>)}</select></div>
            <div className="field"><label htmlFor="create-project-role">Função</label><input id="create-project-role" className="input" value={draft.role} onChange={(event) => update("role", event.target.value)} /></div>
          </div>
        </fieldset>

        <fieldset className="projects-create__section">
          <legend>Notas</legend>
          <div className="projects-create__grid">
            <div className="field projects-create__wide"><label htmlFor="create-project-equipment">Equipamento</label><textarea id="create-project-equipment" className="textarea" rows={2} value={draft.equipment_notes} onChange={(event) => update("equipment_notes", event.target.value)} /></div>
            <div className="field projects-create__wide"><label htmlFor="create-project-injection">Injeção</label><textarea id="create-project-injection" className="textarea" rows={2} value={draft.injection_notes} onChange={(event) => update("injection_notes", event.target.value)} /></div>
            <div className="field projects-create__wide"><label htmlFor="create-project-om">Operação e manutenção</label><textarea id="create-project-om" className="textarea" rows={2} value={draft.om_notes} onChange={(event) => update("om_notes", event.target.value)} /></div>
            <div className="field projects-create__wide"><label htmlFor="create-project-commercial">Pressupostos comerciais</label><textarea id="create-project-commercial" className="textarea" rows={2} value={draft.commercial_assumptions} onChange={(event) => update("commercial_assumptions", event.target.value)} /></div>
            <div className="field"><label htmlFor="create-project-award-year">Ano de adjudicação</label><input id="create-project-award-year" className="input" value={draft.award_year_raw} onChange={(event) => update("award_year_raw", event.target.value)} /></div>
            <div className="field projects-create__wide"><label htmlFor="create-project-notes">Notas gerais</label><textarea id="create-project-notes" className="textarea" rows={3} value={draft.notes} onChange={(event) => update("notes", event.target.value)} /></div>
          </div>
        </fieldset>
        {submitError && <p className="small text-danger" role="alert">{submitError}</p>}
      </form>
    </Modal>
  );
}
