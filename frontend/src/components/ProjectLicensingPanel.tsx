// Separador "Licenciamento e comunicações" do detalhe do projeto (D-105).
// Só apresentação e chamadas à API. As permissões de credenciais, SIM e excedente
// são as flags `can_*` do ProjectRead (já combinadas com permissão + âmbito no servidor);
// o servidor valida cada escrita e cada revelação.
import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createProjectCredential,
  createProjectSimCard,
  createSurplusContract,
  deleteProjectCredential,
  deleteProjectSimCard,
  deleteSurplusContract,
  listProjectCredentials,
  listProjectSimCards,
  listSurplusContracts,
  PortalCredential,
  PortalCredentialReveal,
  PortalCredentialUpdate,
  ProjectCommunicationData,
  ProjectLicensingData,
  LicensingState,
  revealProjectCredential,
  revealProjectSimCard,
  SimCard,
  SimCardCreate,
  SimCardReveal,
  SimCardUpdate,
  SimPurpose,
  SurplusContract,
  SurplusContractInput,
  updateProjectCommunicationData,
  updateProjectCredential,
  updateProjectLicensingData,
  updateProjectSimCard,
  updateSurplusContract,
  errorMessage,
} from "../api/client";
import { formatDatePt } from "../utils/dates";
import Icon from "./Icon";
import { Alert, Badge, Card, EmptyState, LoadingState, Modal, ProgressBar, Tone } from "./ui";
import { useToast } from "./Toast";
import "./ProjectLicensingPanel.css";

export const CIPHER_UNAVAILABLE_MESSAGE = "Cifra de credenciais não configurada.";
export const REVEAL_TTL_MS = 30_000;

const OPERATORS = ["NOS", "Vodafone", "MEO", "Outro"] as const;
const PORTAL_LABELS: Record<string, string> = {
  dgeg_login_geral: "DGEG / Login Geral",
  mastervantagem: "Mastervantagem",
  outro: "Outro",
};
const SIM_PURPOSE_LABELS: Record<SimPurpose, string> = {
  comunicacoes: "Comunicações",
  dados_moveis: "Dados móveis",
  outro: "Outro",
};
const INSPECTING_ENTITY_SUGGESTIONS = ["IEP", "LVT", "LIQ", "ISQ"];
const LICENSING_STATE_LABELS: Record<LicensingState, string> = {
  sem_registo: "Sem registo",
  cadastrado: "Cadastrado",
  certificacao_pedida: "Certificação pedida",
  inspecionado: "Inspecionado",
  certificado_provisorio: "Certificado provisório",
  certificado_definitivo: "Certificado definitivo",
};
const LICENSING_STEPS: { state: Exclude<LicensingState, "sem_registo">; label: string; field: keyof ProjectLicensingData }[] = [
  { state: "cadastrado", label: "Cadastro", field: "registration_date" },
  { state: "certificacao_pedida", label: "Pedido de certificação", field: "certification_request_date" },
  { state: "inspecionado", label: "Inspeção", field: "inspection_date" },
  { state: "certificado_provisorio", label: "Certificado provisório", field: "provisional_certificate_date" },
  { state: "certificado_definitivo", label: "Certificado definitivo", field: "certificate_date" },
];
const STATE_TONES: Record<LicensingState, Tone> = {
  sem_registo: "neutral",
  cadastrado: "info",
  certificacao_pedida: "info",
  inspecionado: "violet",
  certificado_provisorio: "warning",
  certificado_definitivo: "success",
};

export interface ProjectLicensingPanelProps {
  projectId: string;
  licensing: ProjectLicensingData | null;
  communication: ProjectCommunicationData | null;
  canViewLicensing: boolean;
  canEditLicensing: boolean;
  canViewCommunication: boolean;
  canEditCommunication: boolean;
  // Flags `can_*` do ProjectRead (servidor): permissão + âmbito do projeto.
  canEditCredentials: boolean;
  canRevealCredentials: boolean;
  canEditSimCards: boolean;
  canRevealSimSecrets: boolean;
  canEditSurplusContracts: boolean;
  onLicensingSaved: (data: ProjectLicensingData) => void;
  onCommunicationSaved: (data: ProjectCommunicationData) => void;
}

function nullable(value: string): string | null {
  return value === "" ? null : value;
}

// 503 = cifra de segredos indisponível no servidor; o resto é a mensagem geral.
function licensingErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.status === 503) return CIPHER_UNAVAILABLE_MESSAGE;
  return errorMessage(err, fallback);
}

function KvRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function ValueOrDash({ value }: { value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return <span className="muted">—</span>;
  return <>{String(value)}</>;
}

function DateOrDash({ value }: { value: string | null }) {
  return value ? <>{formatDatePt(value)}</> : <span className="muted">—</span>;
}

function ReadOnlyNotice() {
  return <EmptyState compact icon="lock" title="Sem permissão para ver estes dados." />;
}

// --- Licenciamento --------------------------------------------------------

type LicensingDraft = {
  upac_number: string;
  upac_registration_date: string;
  dgeg_number: string;
  cadastro_number: string;
  licensing_status: string;
  registration_date: string;
  certification_request_date: string;
  inspecting_entity: string;
  inspection_date: string;
  provisional_certificate_date: string;
  certificate_date: string;
  installer: string;
  commercializer: string;
  annual_production_kwh: string;
  comments: string;
};

function toLicensingDraft(d: ProjectLicensingData): LicensingDraft {
  return {
    upac_number: d.upac_number ?? "",
    upac_registration_date: d.upac_registration_date ?? "",
    dgeg_number: d.dgeg_number ?? "",
    cadastro_number: d.cadastro_number ?? "",
    licensing_status: d.licensing_status ?? "",
    registration_date: d.registration_date ?? "",
    certification_request_date: d.certification_request_date ?? "",
    inspecting_entity: d.inspecting_entity ?? "",
    inspection_date: d.inspection_date ?? "",
    provisional_certificate_date: d.provisional_certificate_date ?? "",
    certificate_date: d.certificate_date ?? "",
    installer: d.installer ?? "",
    commercializer: d.commercializer ?? "",
    annual_production_kwh: d.annual_production_kwh === null ? "" : String(d.annual_production_kwh),
    comments: d.comments,
  };
}

// Só envia os campos alterados (PATCH parcial). `null` limpa.
function licensingChanges(draft: LicensingDraft, current: ProjectLicensingData): Partial<ProjectLicensingData> {
  const changes: Partial<ProjectLicensingData> = {};
  const text = (key: keyof Omit<LicensingDraft, "annual_production_kwh" | "comments">) => {
    const next = nullable(draft[key]);
    if (next !== current[key]) (changes as Record<string, unknown>)[key] = next;
  };
  text("upac_number");
  text("upac_registration_date");
  text("dgeg_number");
  text("cadastro_number");
  text("licensing_status");
  text("registration_date");
  text("certification_request_date");
  text("inspecting_entity");
  text("inspection_date");
  text("provisional_certificate_date");
  text("certificate_date");
  text("installer");
  text("commercializer");
  const production = nullable(draft.annual_production_kwh);
  const productionNumber = production === null ? null : Number(production);
  if (productionNumber !== current.annual_production_kwh) changes.annual_production_kwh = productionNumber;
  if (draft.comments !== current.comments) changes.comments = draft.comments;
  return changes;
}

function LicensingStateProgress({ state, data }: { state: LicensingState; data: ProjectLicensingData }) {
  const index = LICENSING_STEPS.findIndex((s) => s.state === state);
  const percent = index < 0 ? 0 : ((index + 1) / LICENSING_STEPS.length) * 100;
  return (
    <div className="licensing-state">
      <div className="licensing-state__header">
        <span className="muted">Estado derivado das datas</span>
        <Badge tone={STATE_TONES[state]} dot>
          {LICENSING_STATE_LABELS[state]}
        </Badge>
      </div>
      <ProgressBar value={percent} label={`Progresso do licenciamento: ${LICENSING_STATE_LABELS[state]}`} />
      <ol className="licensing-steps">
        {LICENSING_STEPS.map((step, i) => {
          const date = data[step.field] as string | null;
          const reached = index >= i;
          return (
            <li key={step.state} className={reached ? "licensing-steps__item licensing-steps__item--done" : "licensing-steps__item"}>
              <span className="licensing-steps__label">{step.label}</span>
              <span className="licensing-steps__date">{date ? formatDatePt(date) : "—"}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function LicensingCard({
  data,
  canView,
  canEdit,
  onSaved,
  projectId,
}: {
  data: ProjectLicensingData | null;
  canView: boolean;
  canEdit: boolean;
  onSaved: (d: ProjectLicensingData) => void;
  projectId: string;
}) {
  const { notify } = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<LicensingDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canView) {
    return (
      <Card title="Licenciamento" icon="checkCircle">
        <ReadOnlyNotice />
      </Card>
    );
  }
  if (data === null) {
    return (
      <Card title="Licenciamento" icon="checkCircle">
        <LoadingState rows={4} />
      </Card>
    );
  }

  const current = data;

  function startEditing() {
    setDraft(toLicensingDraft(current));
    setError(null);
    setEditing(true);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!draft) return;
    const changes = licensingChanges(draft, current);
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProjectLicensingData(projectId, changes);
      onSaved(updated);
      setEditing(false);
      notify("Dados de licenciamento atualizados.", "success");
    } catch (err) {
      setError(licensingErrorMessage(err, "Não foi possível guardar as alterações."));
    } finally {
      setSaving(false);
    }
  }

  const setField = (key: keyof LicensingDraft, value: string) => setDraft((d) => (d ? { ...d, [key]: value } : d));

  return (
    <Card
      title="Licenciamento"
      icon="checkCircle"
      actions={
        canEdit && !editing ? (
          <button type="button" className="btn btn--sm" onClick={startEditing}>
            <Icon name="wrench" size={14} /> Editar
          </button>
        ) : undefined
      }
    >
      {error && (
        <div style={{ marginBottom: 12 }}>
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {!editing ? (
        <>
          <LicensingStateProgress state={current.licensing_state} data={current} />
          <dl className="kv licensing-kv">
            <KvRow label="Nº UPAC">
              <ValueOrDash value={current.upac_number} />
            </KvRow>
            <KvRow label="Data de registo UPAC">
              <DateOrDash value={current.upac_registration_date} />
            </KvRow>
            <KvRow label="Nº DGEG">
              <ValueOrDash value={current.dgeg_number} />
            </KvRow>
            <KvRow label="Nº de cadastro">
              <ValueOrDash value={current.cadastro_number} />
            </KvRow>
            <KvRow label="Estado do licenciamento (texto)">
              <ValueOrDash value={current.licensing_status} />
            </KvRow>
            <KvRow label="Entidade inspetora">
              <ValueOrDash value={current.inspecting_entity} />
            </KvRow>
            <KvRow label="Instalador">
              <ValueOrDash value={current.installer} />
            </KvRow>
            <KvRow label="Comercializador">
              <ValueOrDash value={current.commercializer} />
            </KvRow>
            <KvRow label="Produção anual (kWh)">
              <ValueOrDash value={current.annual_production_kwh} />
            </KvRow>
            <KvRow label="Observações">
              {current.comments ? <span style={{ whiteSpace: "pre-wrap" }}>{current.comments}</span> : <span className="muted">—</span>}
            </KvRow>
          </dl>
        </>
      ) : (
        draft && (
          <form className="form-grid" onSubmit={handleSave}>
            <div className="field">
              <label htmlFor="lic-upac">Nº UPAC</label>
              <input id="lic-upac" className="input" value={draft.upac_number} onChange={(e) => setField("upac_number", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-upac-date">Data de registo UPAC</label>
              <input
                id="lic-upac-date"
                className="input"
                type="date"
                value={draft.upac_registration_date}
                onChange={(e) => setField("upac_registration_date", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="lic-dgeg">Nº DGEG</label>
              <input id="lic-dgeg" className="input" value={draft.dgeg_number} onChange={(e) => setField("dgeg_number", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-cadastro">Nº de cadastro</label>
              <input id="lic-cadastro" className="input" value={draft.cadastro_number} onChange={(e) => setField("cadastro_number", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-status">Estado do licenciamento (texto)</label>
              <input id="lic-status" className="input" value={draft.licensing_status} onChange={(e) => setField("licensing_status", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-registration">Data de cadastro</label>
              <input id="lic-registration" className="input" type="date" value={draft.registration_date} onChange={(e) => setField("registration_date", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-cert-request">Data de pedido de certificação</label>
              <input
                id="lic-cert-request"
                className="input"
                type="date"
                value={draft.certification_request_date}
                onChange={(e) => setField("certification_request_date", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="lic-inspecting">Entidade inspetora</label>
              <input
                id="lic-inspecting"
                className="input"
                list="lic-inspecting-suggestions"
                value={draft.inspecting_entity}
                onChange={(e) => setField("inspecting_entity", e.target.value)}
              />
              <datalist id="lic-inspecting-suggestions">
                {INSPECTING_ENTITY_SUGGESTIONS.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </div>
            <div className="field">
              <label htmlFor="lic-inspection">Data de inspeção</label>
              <input id="lic-inspection" className="input" type="date" value={draft.inspection_date} onChange={(e) => setField("inspection_date", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-provisional">Data de certificado provisório</label>
              <input
                id="lic-provisional"
                className="input"
                type="date"
                value={draft.provisional_certificate_date}
                onChange={(e) => setField("provisional_certificate_date", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="lic-certificate">Data de certificado definitivo</label>
              <input id="lic-certificate" className="input" type="date" value={draft.certificate_date} onChange={(e) => setField("certificate_date", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-installer">Instalador</label>
              <input id="lic-installer" className="input" value={draft.installer} onChange={(e) => setField("installer", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-commercializer">Comercializador</label>
              <input id="lic-commercializer" className="input" value={draft.commercializer} onChange={(e) => setField("commercializer", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="lic-production">Produção anual (kWh)</label>
              <input
                id="lic-production"
                className="input"
                type="number"
                min="0"
                step="any"
                value={draft.annual_production_kwh}
                onChange={(e) => setField("annual_production_kwh", e.target.value)}
              />
            </div>
            <div className="field span-2">
              <label htmlFor="lic-comments">Observações</label>
              <textarea id="lic-comments" className="textarea" rows={3} value={draft.comments} onChange={(e) => setField("comments", e.target.value)} />
            </div>
            <div className="span-2" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setEditing(false)} disabled={saving}>
                Cancelar
              </button>
              <button type="submit" className="btn btn--primary" disabled={saving}>
                {saving ? "A guardar…" : "Guardar"}
              </button>
            </div>
          </form>
        )
      )}
    </Card>
  );
}

// --- Comunicações ---------------------------------------------------------
// Os cartões SIM têm bloco próprio (SimCardsCard). Aqui ficam só os dados gerais.

type CommunicationDraft = {
  whereversim_login: string;
  communication_status: string;
  notes: string;
};

function toCommunicationDraft(d: ProjectCommunicationData): CommunicationDraft {
  return {
    whereversim_login: d.whereversim_login ?? "",
    communication_status: d.communication_status ?? "",
    notes: d.notes,
  };
}

function communicationChanges(draft: CommunicationDraft, current: ProjectCommunicationData): Partial<ProjectCommunicationData> {
  const changes: Partial<ProjectCommunicationData> = {};
  if (nullable(draft.whereversim_login) !== current.whereversim_login) changes.whereversim_login = nullable(draft.whereversim_login);
  if (nullable(draft.communication_status) !== current.communication_status) changes.communication_status = nullable(draft.communication_status);
  if (draft.notes !== current.notes) changes.notes = draft.notes;
  return changes;
}

function CommunicationCard({
  data,
  canView,
  canEdit,
  projectId,
  onSaved,
}: {
  data: ProjectCommunicationData | null;
  canView: boolean;
  canEdit: boolean;
  projectId: string;
  onSaved: (d: ProjectCommunicationData) => void;
}) {
  const { notify } = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<CommunicationDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canView) {
    return (
      <Card title="Comunicações" icon="lock" tone="violet">
        <ReadOnlyNotice />
      </Card>
    );
  }
  if (data === null) {
    return (
      <Card title="Comunicações" icon="lock" tone="violet">
        <LoadingState rows={3} />
      </Card>
    );
  }

  const current = data;

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!draft) return;
    const changes = communicationChanges(draft, current);
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProjectCommunicationData(projectId, changes);
      onSaved(updated);
      setEditing(false);
      notify("Dados de comunicação atualizados.", "success");
    } catch (err) {
      setError(licensingErrorMessage(err, "Não foi possível guardar as alterações."));
    } finally {
      setSaving(false);
    }
  }

  const setField = <K extends keyof CommunicationDraft>(key: K, value: CommunicationDraft[K]) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d));

  return (
    <Card
      title="Comunicações"
      icon="lock"
      tone="violet"
      actions={
        canEdit && !editing ? (
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => {
              setDraft(toCommunicationDraft(current));
              setError(null);
              setEditing(true);
            }}
          >
            <Icon name="wrench" size={14} /> Editar
          </button>
        ) : undefined
      }
    >
      {error && (
        <div style={{ marginBottom: 12 }}>
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {!editing ? (
        <dl className="kv">
          <KvRow label="Login WhereverSIM">
            <ValueOrDash value={current.whereversim_login} />
          </KvRow>
          <KvRow label="Estado da comunicação">
            <ValueOrDash value={current.communication_status} />
          </KvRow>
          <KvRow label="Notas">
            {current.notes ? <span style={{ whiteSpace: "pre-wrap" }}>{current.notes}</span> : <span className="muted">—</span>}
          </KvRow>
        </dl>
      ) : (
        draft && (
          <form className="form-grid" onSubmit={handleSave}>
            <div className="field span-2">
              <label htmlFor="com-whereversim">Login WhereverSIM</label>
              <input id="com-whereversim" className="input" value={draft.whereversim_login} onChange={(e) => setField("whereversim_login", e.target.value)} />
            </div>
            <div className="field span-2">
              <label htmlFor="com-status">Estado da comunicação</label>
              <input id="com-status" className="input" value={draft.communication_status} onChange={(e) => setField("communication_status", e.target.value)} />
            </div>
            <div className="field span-2">
              <label htmlFor="com-notes">Notas</label>
              <textarea id="com-notes" className="textarea" rows={3} value={draft.notes} onChange={(e) => setField("notes", e.target.value)} />
            </div>
            <div className="span-2" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" className="btn" onClick={() => setEditing(false)} disabled={saving}>
                Cancelar
              </button>
              <button type="submit" className="btn btn--primary" disabled={saving}>
                {saving ? "A guardar…" : "Guardar"}
              </button>
            </div>
          </form>
        )
      )}
    </Card>
  );
}

// --- Cartões SIM (0..n por projeto) ---------------------------------------
// PIN/PUK: nunca na leitura. Só aparecem após "Ver PIN/PUK" (com `can_reveal_sim_secrets`),
// em estado local deste componente, e somem ao fechar ou após REVEAL_TTL_MS.

type RevealedSim = { simId: string; title: string; pin: string | null; puk: string | null };

function simTitle(sim: SimCard): string {
  const purpose = SIM_PURPOSE_LABELS[sim.purpose] ?? sim.purpose;
  return sim.operator ? `${purpose} · ${sim.operator}` : purpose;
}

function SimCardsCard({
  projectId,
  canView,
  canEdit,
  canReveal,
}: {
  projectId: string;
  canView: boolean;
  canEdit: boolean;
  canReveal: boolean;
}) {
  const { notify } = useToast();
  const [sims, setSims] = useState<SimCard[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [formTarget, setFormTarget] = useState<SimCard | "new" | null>(null);
  const [confirmingRemoval, setConfirmingRemoval] = useState<string | null>(null);
  const [revealing, setRevealing] = useState<string | null>(null);
  // Só em memória, neste componente: nunca em estado global, localStorage ou logs.
  const [revealed, setRevealed] = useState<RevealedSim | null>(null);
  const [showRevealed, setShowRevealed] = useState(false);
  const [copied, setCopied] = useState<"pin" | "puk" | null>(null);

  const load = useCallback(async () => {
    try {
      setSims(await listProjectSimCards(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(licensingErrorMessage(err, "Não foi possível carregar os cartões SIM."));
    }
  }, [projectId]);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  // O PIN/PUK desaparece sozinho ao fim de REVEAL_TTL_MS.
  useEffect(() => {
    if (!revealed) return undefined;
    const timer = window.setTimeout(() => {
      setRevealed(null);
      setShowRevealed(false);
      setCopied(null);
    }, REVEAL_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [revealed]);

  function hideRevealed() {
    setRevealed(null);
    setShowRevealed(false);
    setCopied(null);
  }

  async function handleReveal(sim: SimCard) {
    setActionError(null);
    setRevealing(sim.id);
    try {
      const value: SimCardReveal = await revealProjectSimCard(projectId, sim.id);
      setRevealed({ simId: sim.id, title: simTitle(sim), pin: value.pin, puk: value.puk });
      setShowRevealed(false);
      setCopied(null);
    } catch (err) {
      setActionError(licensingErrorMessage(err, "Não foi possível revelar o PIN/PUK."));
    } finally {
      setRevealing(null);
    }
  }

  async function handleCopy(kind: "pin" | "puk") {
    const value = revealed?.[kind];
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(kind);
    } catch {
      setActionError("Não foi possível copiar. Copie manualmente.");
    }
  }

  async function handleRemove(sim: SimCard) {
    setActionError(null);
    try {
      await deleteProjectSimCard(projectId, sim.id);
      if (revealed?.simId === sim.id) hideRevealed();
      setConfirmingRemoval(null);
      notify("Cartão SIM removido.", "success");
      await load();
    } catch (err) {
      setActionError(licensingErrorMessage(err, "Não foi possível remover o cartão SIM."));
    }
  }

  if (!canView) {
    return (
      <Card title="Cartões SIM" icon="lock" tone="violet">
        <ReadOnlyNotice />
      </Card>
    );
  }

  return (
    <Card
      title="Cartões SIM"
      icon="lock"
      tone="violet"
      flush
      actions={
        canEdit ? (
          <button type="button" className="btn btn--sm" onClick={() => setFormTarget("new")}>
            <Icon name="plus" size={14} /> Novo cartão SIM
          </button>
        ) : undefined
      }
    >
      {actionError && (
        <div style={{ margin: 12 }}>
          <Alert tone="danger">{actionError}</Alert>
        </div>
      )}
      {loadError && (
        <div style={{ margin: 12 }}>
          <Alert tone="danger">{loadError}</Alert>
        </div>
      )}
      {revealed && (
        <div className="secret-reveal" role="region" aria-label="PIN/PUK revelados">
          <div className="secret-reveal__head">
            <strong>{revealed.title}</strong>
          </div>
          <div className="secret-reveal__row">
            {revealed.pin !== null && (
              <>
                <span>PIN</span>
                <input className="input" aria-label="PIN" type={showRevealed ? "text" : "password"} value={revealed.pin} readOnly autoComplete="off" />
                <button type="button" className="btn btn--sm" onClick={() => handleCopy("pin")}>
                  Copiar PIN
                </button>
              </>
            )}
            {revealed.puk !== null && (
              <>
                <span>PUK</span>
                <input className="input" aria-label="PUK" type={showRevealed ? "text" : "password"} value={revealed.puk} readOnly autoComplete="off" />
                <button type="button" className="btn btn--sm" onClick={() => handleCopy("puk")}>
                  Copiar PUK
                </button>
              </>
            )}
          </div>
          <div className="secret-reveal__row">
            <button type="button" className="btn btn--sm" onClick={() => setShowRevealed((v) => !v)}>
              {showRevealed ? "Ocultar" : "Mostrar"}
            </button>
            <button type="button" className="btn btn--sm" onClick={hideRevealed}>
              Fechar
            </button>
          </div>
          <p className="muted secret-reveal__hint">
            {copied ? `Copiado (${copied.toUpperCase()}). ` : ""}Ocultado automaticamente após 30 segundos.
          </p>
        </div>
      )}
      {sims === null && !loadError ? (
        <div style={{ padding: 12 }}>
          <LoadingState rows={2} />
        </div>
      ) : sims && sims.length === 0 ? (
        <div style={{ padding: 12 }}>
          <EmptyState compact title="Sem cartões SIM." />
        </div>
      ) : sims ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Finalidade</th>
                <th>Operador</th>
                <th>Nº / M2M</th>
                <th>ICCID</th>
                <th>Verificado</th>
                <th>Notas</th>
                <th>PIN / PUK definidos</th>
                <th aria-label="Ações" />
              </tr>
            </thead>
            <tbody>
              {sims.map((s) => (
                <tr key={s.id}>
                  <td>{SIM_PURPOSE_LABELS[s.purpose] ?? s.purpose}</td>
                  <td>
                    <ValueOrDash value={s.operator} />
                  </td>
                  <td>
                    <ValueOrDash value={s.phone_number} />
                  </td>
                  <td>
                    <ValueOrDash value={s.iccid} />
                  </td>
                  <td>
                    {s.verified_on_portal === null ? (
                      <span className="muted">—</span>
                    ) : (
                      <>
                        {s.verified_on_portal ? "Sim" : "Não"}
                        {s.verified_date && (
                          <>
                            {" "}
                            · <DateOrDash value={s.verified_date} />
                          </>
                        )}
                      </>
                    )}
                  </td>
                  <td>{s.notes ? <span style={{ whiteSpace: "pre-wrap" }}>{s.notes}</span> : <span className="muted">—</span>}</td>
                  <td>
                    PIN: {s.has_pin ? "sim" : "não"} · PUK: {s.has_puk ? "sim" : "não"}
                  </td>
                  <td className="secret-actions">
                    {canReveal && (s.has_pin || s.has_puk) && (
                      <button type="button" className="btn btn--sm" disabled={revealing === s.id} onClick={() => handleReveal(s)}>
                        {revealing === s.id ? "A abrir…" : "Ver PIN/PUK"}
                      </button>
                    )}
                    {canEdit && (
                      <>
                        <button type="button" className="btn btn--sm" onClick={() => setFormTarget(s)}>
                          Editar
                        </button>
                        {confirmingRemoval === s.id ? (
                          <>
                            <button type="button" className="btn btn--sm btn--danger" onClick={() => handleRemove(s)}>
                              Confirmar remoção
                            </button>
                            <button type="button" className="btn btn--sm" onClick={() => setConfirmingRemoval(null)}>
                              Cancelar
                            </button>
                          </>
                        ) : (
                          <button type="button" className="btn btn--sm btn--danger" onClick={() => setConfirmingRemoval(s.id)}>
                            Remover
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {formTarget !== null && (
        <SimFormModal
          projectId={projectId}
          target={formTarget}
          onClose={() => setFormTarget(null)}
          onSaved={async () => {
            setFormTarget(null);
            notify("Cartão SIM guardado.", "success");
            await load();
          }}
        />
      )}
    </Card>
  );
}

type SimDraft = {
  purpose: SimPurpose;
  operator: string;
  phone_number: string;
  iccid: string;
  verified_on_portal: boolean;
  verified_date: string;
  notes: string;
  // PIN/PUK: vazio = manter; `remove_*` = remover o valor guardado.
  pin: string;
  puk: string;
  remove_pin: boolean;
  remove_puk: boolean;
};

const EMPTY_SIM_DRAFT: SimDraft = {
  purpose: "comunicacoes",
  operator: "",
  phone_number: "",
  iccid: "",
  verified_on_portal: false,
  verified_date: "",
  notes: "",
  pin: "",
  puk: "",
  remove_pin: false,
  remove_puk: false,
};

// Os campos de PIN/PUK nunca são pré-preenchidos: a leitura não os tem.
function toSimDraft(s: SimCard): SimDraft {
  return {
    purpose: s.purpose,
    operator: s.operator ?? "",
    phone_number: s.phone_number ?? "",
    iccid: s.iccid ?? "",
    verified_on_portal: s.verified_on_portal === true,
    verified_date: s.verified_date ?? "",
    notes: s.notes,
    pin: "",
    puk: "",
    remove_pin: false,
    remove_puk: false,
  };
}

// Criação: envia todos os campos. Edição (PATCH): só os alterados.
// PIN/PUK: omitidos = manter; `null` = remover; string não vazia = definir.
function simBody(draft: SimDraft, current: SimCard | null): SimCardUpdate {
  const next = {
    purpose: draft.purpose,
    operator: nullable(draft.operator),
    phone_number: nullable(draft.phone_number),
    iccid: nullable(draft.iccid),
    verified_on_portal: draft.verified_on_portal,
    verified_date: nullable(draft.verified_date),
    notes: nullable(draft.notes),
  };
  const prev = current
    ? {
        purpose: current.purpose,
        operator: current.operator,
        phone_number: current.phone_number,
        iccid: current.iccid,
        verified_on_portal: current.verified_on_portal === true,
        verified_date: current.verified_date,
        notes: current.notes === "" ? null : current.notes,
      }
    : null;
  const body: Record<string, unknown> = {};
  (Object.keys(next) as (keyof typeof next)[]).forEach((key) => {
    if (prev === null || next[key] !== prev[key]) body[key] = next[key];
  });
  if (draft.remove_pin) body.pin = null;
  else if (draft.pin !== "") body.pin = draft.pin;
  if (draft.remove_puk) body.puk = null;
  else if (draft.puk !== "") body.puk = draft.puk;
  return body as SimCardUpdate;
}

function SimFormModal({
  projectId,
  target,
  onClose,
  onSaved,
}: {
  projectId: string;
  target: SimCard | "new";
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const editing = target !== "new";
  const [draft, setDraft] = useState<SimDraft>(editing ? toSimDraft(target) : EMPTY_SIM_DRAFT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setField = <K extends keyof SimDraft>(key: K, value: SimDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      if (target === "new") {
        // Criação: `purpose` é sempre enviado, por isso o corpo cumpre SimCardCreate.
        await createProjectSimCard(projectId, simBody(draft, null) as SimCardCreate);
      } else {
        await updateProjectSimCard(projectId, target.id, simBody(draft, target));
      }
      setDraft((d) => ({ ...d, pin: "", puk: "" }));
      await onSaved();
    } catch (err) {
      setError(licensingErrorMessage(err, "Não foi possível guardar o cartão SIM."));
    } finally {
      setSaving(false);
    }
  }

  const operatorOptions = draft.operator && !(OPERATORS as readonly string[]).includes(draft.operator) ? [draft.operator, ...OPERATORS] : [...OPERATORS];

  return (
    <Modal title={editing ? "Editar cartão SIM" : "Novo cartão SIM"} onClose={onClose}>
      <form className="form-grid" onSubmit={handleSubmit} autoComplete="off">
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field">
          <label htmlFor="sim-purpose">Finalidade</label>
          <select id="sim-purpose" className="select" value={draft.purpose} onChange={(e) => setField("purpose", e.target.value as SimPurpose)}>
            {Object.entries(SIM_PURPOSE_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="sim-operator">Operador</label>
          <select id="sim-operator" className="select" value={draft.operator} onChange={(e) => setField("operator", e.target.value)}>
            <option value="">—</option>
            {operatorOptions.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="sim-phone">Nº / M2M</label>
          <input id="sim-phone" className="input" maxLength={64} value={draft.phone_number} onChange={(e) => setField("phone_number", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sim-iccid">ICCID</label>
          <input id="sim-iccid" className="input" maxLength={128} value={draft.iccid} onChange={(e) => setField("iccid", e.target.value)} />
        </div>
        <div className="field span-2">
          <label htmlFor="sim-verified">
            <input id="sim-verified" type="checkbox" checked={draft.verified_on_portal} onChange={(e) => setField("verified_on_portal", e.target.checked)} /> Verificado
            no portal do operador
          </label>
        </div>
        <div className="field">
          <label htmlFor="sim-verified-date">Data de verificação</label>
          <input id="sim-verified-date" className="input" type="date" value={draft.verified_date} onChange={(e) => setField("verified_date", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sim-pin">{editing ? "Novo PIN (vazio = manter)" : "PIN (opcional)"}</label>
          <input
            id="sim-pin"
            className="input"
            type="password"
            autoComplete="off"
            maxLength={32}
            value={draft.pin}
            disabled={draft.remove_pin}
            onChange={(e) => setField("pin", e.target.value)}
          />
          {editing && target.has_pin && (
            <label htmlFor="sim-remove-pin">
              <input id="sim-remove-pin" type="checkbox" checked={draft.remove_pin} onChange={(e) => setField("remove_pin", e.target.checked)} /> Remover o PIN
              guardado
            </label>
          )}
        </div>
        <div className="field">
          <label htmlFor="sim-puk">{editing ? "Novo PUK (vazio = manter)" : "PUK (opcional)"}</label>
          <input
            id="sim-puk"
            className="input"
            type="password"
            autoComplete="off"
            maxLength={32}
            value={draft.puk}
            disabled={draft.remove_puk}
            onChange={(e) => setField("puk", e.target.value)}
          />
          {editing && target.has_puk && (
            <label htmlFor="sim-remove-puk">
              <input id="sim-remove-puk" type="checkbox" checked={draft.remove_puk} onChange={(e) => setField("remove_puk", e.target.checked)} /> Remover o PUK
              guardado
            </label>
          )}
        </div>
        <div className="field span-2">
          <label htmlFor="sim-notes">Notas</label>
          <textarea id="sim-notes" className="textarea" rows={3} value={draft.notes} onChange={(e) => setField("notes", e.target.value)} />
        </div>
        <div className="span-2" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- Credenciais de portais -----------------------------------------------

type RevealedPassword = PortalCredentialReveal;

function CredentialsCard({
  projectId,
  canView,
  canEdit,
  canReveal,
}: {
  projectId: string;
  canView: boolean;
  canEdit: boolean;
  canReveal: boolean;
}) {
  const { notify } = useToast();
  const [credentials, setCredentials] = useState<PortalCredential[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [formTarget, setFormTarget] = useState<PortalCredential | "new" | null>(null);
  const [confirmingRemoval, setConfirmingRemoval] = useState<string | null>(null);
  const [revealing, setRevealing] = useState<string | null>(null);
  // Só em memória, neste componente: nunca em estado global, localStorage ou logs.
  const [revealed, setRevealed] = useState<RevealedPassword | null>(null);
  const [showRevealed, setShowRevealed] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      setCredentials(await listProjectCredentials(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(licensingErrorMessage(err, "Não foi possível carregar as credenciais."));
    }
  }, [projectId]);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  // A password desaparece sozinha ao fim de REVEAL_TTL_MS.
  useEffect(() => {
    if (!revealed) return undefined;
    const timer = window.setTimeout(() => {
      setRevealed(null);
      setShowRevealed(false);
      setCopied(false);
    }, REVEAL_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [revealed]);

  function hideRevealed() {
    setRevealed(null);
    setShowRevealed(false);
    setCopied(false);
  }

  async function handleReveal(credential: PortalCredential) {
    setActionError(null);
    setRevealing(credential.id);
    try {
      const value = await revealProjectCredential(projectId, credential.id);
      setRevealed(value);
      setShowRevealed(false);
      setCopied(false);
    } catch (err) {
      setActionError(licensingErrorMessage(err, "Não foi possível revelar a palavra-passe."));
    } finally {
      setRevealing(null);
    }
  }

  async function handleCopy() {
    if (!revealed) return;
    try {
      await navigator.clipboard.writeText(revealed.password);
      setCopied(true);
    } catch {
      setActionError("Não foi possível copiar. Copie manualmente.");
    }
  }

  async function handleRemove(credential: PortalCredential) {
    setActionError(null);
    try {
      await deleteProjectCredential(projectId, credential.id);
      if (revealed?.id === credential.id) hideRevealed();
      setConfirmingRemoval(null);
      notify("Credencial removida.", "success");
      await load();
    } catch (err) {
      setActionError(licensingErrorMessage(err, "Não foi possível remover a credencial."));
    }
  }

  if (!canView) return null;

  return (
    <Card
      title="Credenciais de portais"
      icon="lock"
      tone="violet"
      flush
      actions={
        canEdit ? (
          <button type="button" className="btn btn--sm" onClick={() => setFormTarget("new")}>
            <Icon name="plus" size={14} /> Adicionar
          </button>
        ) : undefined
      }
    >
      {actionError && (
        <div style={{ margin: 12 }}>
          <Alert tone="danger">{actionError}</Alert>
        </div>
      )}
      {loadError && (
        <div style={{ margin: 12 }}>
          <Alert tone="danger">{loadError}</Alert>
        </div>
      )}
      {revealed && (
        <div className="secret-reveal" role="region" aria-label="Palavra-passe revelada">
          <div className="secret-reveal__head">
            <strong>{PORTAL_LABELS[revealed.portal] ?? revealed.portal}</strong> · {revealed.username}
          </div>
          <div className="secret-reveal__row">
            <input
              className="input"
              aria-label="Palavra-passe"
              type={showRevealed ? "text" : "password"}
              value={revealed.password}
              readOnly
              autoComplete="off"
            />
            <button type="button" className="btn btn--sm" onClick={() => setShowRevealed((v) => !v)}>
              {showRevealed ? "Ocultar" : "Mostrar"}
            </button>
            <button type="button" className="btn btn--sm" onClick={handleCopy}>
              Copiar
            </button>
            <button type="button" className="btn btn--sm" onClick={hideRevealed}>
              Fechar
            </button>
          </div>
          <p className="muted secret-reveal__hint">
            {copied ? "Copiada. " : ""}Ocultada automaticamente após 30 segundos.
          </p>
        </div>
      )}
      {credentials === null && !loadError ? (
        <div style={{ padding: 12 }}>
          <LoadingState rows={2} />
        </div>
      ) : credentials && credentials.length === 0 ? (
        <div style={{ padding: 12 }}>
          <EmptyState compact title="Sem credenciais de portais." />
        </div>
      ) : credentials ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Portal</th>
                <th>Utilizador</th>
                <th>Email</th>
                <th>Palavra-passe</th>
                <th aria-label="Ações" />
              </tr>
            </thead>
            <tbody>
              {credentials.map((c) => (
                <tr key={c.id}>
                  <td>{PORTAL_LABELS[c.portal] ?? c.portal}</td>
                  <td>{c.username}</td>
                  <td>
                    <ValueOrDash value={c.email} />
                  </td>
                  <td>{c.has_password ? "definida" : <span className="muted">não</span>}</td>
                  <td className="secret-actions">
                    {canReveal && c.has_password && (
                      <button type="button" className="btn btn--sm" disabled={revealing === c.id} onClick={() => handleReveal(c)}>
                        {revealing === c.id ? "A abrir…" : "Ver"}
                      </button>
                    )}
                    {canEdit && (
                      <>
                        <button type="button" className="btn btn--sm" onClick={() => setFormTarget(c)}>
                          Editar
                        </button>
                        {confirmingRemoval === c.id ? (
                          <>
                            <button type="button" className="btn btn--sm btn--danger" onClick={() => handleRemove(c)}>
                              Confirmar remoção
                            </button>
                            <button type="button" className="btn btn--sm" onClick={() => setConfirmingRemoval(null)}>
                              Cancelar
                            </button>
                          </>
                        ) : (
                          <button type="button" className="btn btn--sm btn--danger" onClick={() => setConfirmingRemoval(c.id)}>
                            Remover
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {formTarget !== null && (
        <CredentialFormModal
          projectId={projectId}
          target={formTarget}
          onClose={() => setFormTarget(null)}
          onSaved={async () => {
            setFormTarget(null);
            notify("Credencial guardada.", "success");
            await load();
          }}
        />
      )}
    </Card>
  );
}

function CredentialFormModal({
  projectId,
  target,
  onClose,
  onSaved,
}: {
  projectId: string;
  target: PortalCredential | "new";
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const editing = target !== "new";
  const [portal, setPortal] = useState<string>(editing ? target.portal : "dgeg_login_geral");
  const [username, setUsername] = useState(editing ? target.username : "");
  const [email, setEmail] = useState(editing ? (target.email ?? "") : "");
  // Campo de password sempre vazio ao abrir: a API nunca devolve a password atual.
  const [password, setPassword] = useState("");
  const [removePassword, setRemovePassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (username.trim() === "") {
      setError("Indique o utilizador.");
      return;
    }
    setSaving(true);
    try {
      if (target === "new") {
        await createProjectCredential(projectId, {
          portal: portal as "dgeg_login_geral" | "mastervantagem" | "outro",
          username,
          email: nullable(email.trim()),
          ...(password !== "" ? { password } : {}),
        });
      } else {
        // Omitido = mantém; null = remove; string não vazia = substitui.
        const body: PortalCredentialUpdate = { portal: portal as PortalCredentialUpdate["portal"], username };
        if (nullable(email.trim()) !== (target.email ?? null)) body.email = nullable(email.trim());
        if (removePassword) body.password = null;
        else if (password !== "") body.password = password;
        await updateProjectCredential(projectId, target.id, body);
      }
      setPassword("");
      await onSaved();
    } catch (err) {
      setError(licensingErrorMessage(err, "Não foi possível guardar a credencial."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={editing ? "Editar credencial" : "Nova credencial de portal"} onClose={onClose}>
      <form className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="cred-portal">Portal</label>
          <select id="cred-portal" className="select" value={portal} onChange={(e) => setPortal(e.target.value)}>
            {Object.entries(PORTAL_LABELS).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor="cred-username">Utilizador</label>
          <input id="cred-username" className="input" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={256} />
        </div>
        <div className="field span-2">
          <label htmlFor="cred-email">Email (opcional)</label>
          <input id="cred-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={320} />
        </div>
        {!removePassword && (
          <div className="field span-2">
            <label htmlFor="cred-password">{editing ? "Nova palavra-passe (vazio = manter a atual)" : "Palavra-passe (opcional)"}</label>
            <input
              id="cred-password"
              className="input"
              type="password"
              autoComplete="new-password"
              maxLength={512}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        )}
        {editing && target.has_password && (
          <div className="field span-2">
            <label htmlFor="cred-remove-password">
              <input id="cred-remove-password" type="checkbox" checked={removePassword} onChange={(e) => setRemovePassword(e.target.checked)} /> Remover a palavra-passe guardada
            </label>
          </div>
        )}
        <div className="span-2" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- Contratos de venda de excedente --------------------------------------

type SurplusDraft = {
  commercializer: string;
  contract_type: string;
  status: string;
  duration_months: string;
  contract_sent_date: string;
  sent_to_commercializer_date: string;
  signed_received_date: string;
  start_date: string;
  end_date: string;
  notes: string;
};

const EMPTY_SURPLUS_DRAFT: SurplusDraft = {
  commercializer: "",
  contract_type: "",
  status: "",
  duration_months: "",
  contract_sent_date: "",
  sent_to_commercializer_date: "",
  signed_received_date: "",
  start_date: "",
  end_date: "",
  notes: "",
};

function toSurplusDraft(c: SurplusContract): SurplusDraft {
  return {
    commercializer: c.commercializer ?? "",
    contract_type: c.contract_type ?? "",
    status: c.status ?? "",
    duration_months: c.duration_months === null ? "" : String(c.duration_months),
    contract_sent_date: c.contract_sent_date ?? "",
    sent_to_commercializer_date: c.sent_to_commercializer_date ?? "",
    signed_received_date: c.signed_received_date ?? "",
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? "",
    notes: c.notes,
  };
}

function surplusPayload(draft: SurplusDraft): Partial<SurplusContractInput> {
  return {
    commercializer: nullable(draft.commercializer),
    contract_type: nullable(draft.contract_type),
    status: nullable(draft.status),
    duration_months: draft.duration_months === "" ? null : Number(draft.duration_months),
    contract_sent_date: nullable(draft.contract_sent_date),
    sent_to_commercializer_date: nullable(draft.sent_to_commercializer_date),
    signed_received_date: nullable(draft.signed_received_date),
    start_date: nullable(draft.start_date),
    end_date: nullable(draft.end_date),
    notes: nullable(draft.notes),
  };
}

function SurplusCard({
  projectId,
  canView,
  canEdit,
}: {
  projectId: string;
  canView: boolean;
  canEdit: boolean;
}) {
  const { notify } = useToast();
  const [contracts, setContracts] = useState<SurplusContract[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [formTarget, setFormTarget] = useState<SurplusContract | "new" | null>(null);
  const [confirmingRemoval, setConfirmingRemoval] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setContracts(await listSurplusContracts(projectId));
      setLoadError(null);
    } catch (err) {
      setLoadError(licensingErrorMessage(err, "Não foi possível carregar os contratos de excedente."));
    }
  }, [projectId]);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  if (!canView) {
    return (
      <Card title="Contratos de venda de excedente" icon="zap">
        <ReadOnlyNotice />
      </Card>
    );
  }

  async function handleRemove(contract: SurplusContract) {
    setActionError(null);
    try {
      await deleteSurplusContract(projectId, contract.id);
      setConfirmingRemoval(null);
      notify("Contrato removido.", "success");
      await load();
    } catch (err) {
      setActionError(licensingErrorMessage(err, "Não foi possível remover o contrato."));
    }
  }

  return (
    <Card
      title="Contratos de venda de excedente"
      icon="zap"
      flush
      actions={
        canEdit ? (
          <button type="button" className="btn btn--sm" onClick={() => setFormTarget("new")}>
            <Icon name="plus" size={14} /> Novo contrato
          </button>
        ) : undefined
      }
    >
      {actionError && (
        <div style={{ margin: 12 }}>
          <Alert tone="danger">{actionError}</Alert>
        </div>
      )}
      {loadError && (
        <div style={{ margin: 12 }}>
          <Alert tone="danger">{loadError}</Alert>
        </div>
      )}
      {contracts === null && !loadError ? (
        <div style={{ padding: 12 }}>
          <LoadingState rows={2} />
        </div>
      ) : contracts && contracts.length === 0 ? (
        <div style={{ padding: 12 }}>
          <EmptyState compact title="Sem contratos de excedente." />
        </div>
      ) : contracts ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Comercializador</th>
                <th>Tipo</th>
                <th>Situação</th>
                <th>Duração (meses)</th>
                <th>Início</th>
                <th>Fim</th>
                <th aria-label="Ações" />
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <tr key={c.id}>
                  <td>
                    <ValueOrDash value={c.commercializer} />
                  </td>
                  <td>
                    <ValueOrDash value={c.contract_type} />
                  </td>
                  <td>
                    <ValueOrDash value={c.status} />
                  </td>
                  <td>
                    <ValueOrDash value={c.duration_months} />
                  </td>
                  <td>
                    <DateOrDash value={c.start_date} />
                  </td>
                  <td>
                    <DateOrDash value={c.end_date} />
                  </td>
                  <td className="secret-actions">
                    {canEdit && (
                      <>
                        <button type="button" className="btn btn--sm" onClick={() => setFormTarget(c)}>
                          Editar
                        </button>
                        {confirmingRemoval === c.id ? (
                          <>
                            <button type="button" className="btn btn--sm btn--danger" onClick={() => handleRemove(c)}>
                              Confirmar remoção
                            </button>
                            <button type="button" className="btn btn--sm" onClick={() => setConfirmingRemoval(null)}>
                              Cancelar
                            </button>
                          </>
                        ) : (
                          <button type="button" className="btn btn--sm btn--danger" onClick={() => setConfirmingRemoval(c.id)}>
                            Remover
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {formTarget !== null && (
        <SurplusFormModal
          projectId={projectId}
          target={formTarget}
          onClose={() => setFormTarget(null)}
          onSaved={async () => {
            setFormTarget(null);
            notify("Contrato guardado.", "success");
            await load();
          }}
        />
      )}
    </Card>
  );
}

function SurplusFormModal({
  projectId,
  target,
  onClose,
  onSaved,
}: {
  projectId: string;
  target: SurplusContract | "new";
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<SurplusDraft>(target === "new" ? EMPTY_SURPLUS_DRAFT : toSurplusDraft(target));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setField = (key: keyof SurplusDraft, value: string) => setDraft((d) => ({ ...d, [key]: value }));

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const duration = draft.duration_months === "" ? null : Number(draft.duration_months);
    if (duration !== null && (!Number.isInteger(duration) || duration < 0 || duration > 600)) {
      setError("A duração tem de ser um número inteiro de meses entre 0 e 600.");
      return;
    }
    setSaving(true);
    try {
      const payload = surplusPayload(draft);
      if (target === "new") await createSurplusContract(projectId, payload);
      else await updateSurplusContract(projectId, target.id, payload);
      await onSaved();
    } catch (err) {
      setError(licensingErrorMessage(err, "Não foi possível guardar o contrato."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={target === "new" ? "Novo contrato de excedente" : "Editar contrato de excedente"} onClose={onClose}>
      {/* noValidate: a validação de intervalo é feita aqui, com mensagem em português. */}
      <form className="form-grid" noValidate onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field">
          <label htmlFor="sur-commercializer">Comercializador</label>
          <input id="sur-commercializer" className="input" maxLength={256} value={draft.commercializer} onChange={(e) => setField("commercializer", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-type">Tipo</label>
          <input id="sur-type" className="input" maxLength={128} value={draft.contract_type} onChange={(e) => setField("contract_type", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-status">Situação</label>
          <input id="sur-status" className="input" maxLength={64} value={draft.status} onChange={(e) => setField("status", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-duration">Duração (meses)</label>
          <input id="sur-duration" className="input" type="number" min={0} max={600} step={1} value={draft.duration_months} onChange={(e) => setField("duration_months", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-sent">Data de envio do contrato</label>
          <input id="sur-sent" className="input" type="date" value={draft.contract_sent_date} onChange={(e) => setField("contract_sent_date", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-to-commercializer">Data de envio ao comercializador</label>
          <input
            id="sur-to-commercializer"
            className="input"
            type="date"
            value={draft.sent_to_commercializer_date}
            onChange={(e) => setField("sent_to_commercializer_date", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="sur-signed">Data de receção (assinado)</label>
          <input id="sur-signed" className="input" type="date" value={draft.signed_received_date} onChange={(e) => setField("signed_received_date", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-start">Início</label>
          <input id="sur-start" className="input" type="date" value={draft.start_date} onChange={(e) => setField("start_date", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sur-end">Fim</label>
          <input id="sur-end" className="input" type="date" value={draft.end_date} onChange={(e) => setField("end_date", e.target.value)} />
        </div>
        <div className="field span-2">
          <label htmlFor="sur-notes">Observação</label>
          <textarea id="sur-notes" className="textarea" rows={3} value={draft.notes} onChange={(e) => setField("notes", e.target.value)} />
        </div>
        <div className="span-2" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// --- Separador ------------------------------------------------------------

export default function ProjectLicensingPanel({
  projectId,
  licensing,
  communication,
  canViewLicensing,
  canEditLicensing,
  canViewCommunication,
  canEditCommunication,
  canEditCredentials,
  canRevealCredentials,
  canEditSimCards,
  canRevealSimSecrets,
  canEditSurplusContracts,
  onLicensingSaved,
  onCommunicationSaved,
}: ProjectLicensingPanelProps) {
  return (
    <div className="grid grid--main-side licensing-panel">
      <div className="licensing-panel__main">
        <LicensingCard projectId={projectId} data={licensing} canView={canViewLicensing} canEdit={canEditLicensing} onSaved={onLicensingSaved} />
        <SimCardsCard projectId={projectId} canView={canViewCommunication} canEdit={canEditSimCards} canReveal={canRevealSimSecrets} />
        <SurplusCard projectId={projectId} canView={canViewLicensing} canEdit={canEditSurplusContracts} />
      </div>
      <div className="licensing-panel__side">
        <CommunicationCard
          projectId={projectId}
          data={communication}
          canView={canViewCommunication}
          canEdit={canEditCommunication}
          onSaved={onCommunicationSaved}
        />
        <CredentialsCard projectId={projectId} canView={canViewCommunication} canEdit={canEditCredentials} canReveal={canRevealCredentials} />
      </div>
    </div>
  );
}
