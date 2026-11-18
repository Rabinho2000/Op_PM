import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, errorMessage, getProject, listPeople, Project } from "../api/client";
import {
  CableDesign,
  CableDesignHistoryEntry,
  CableDesignRevision,
  approveCableDesign,
  deactivateCableDesign,
  getCableDesign,
  listCableHistory,
  listCableRevisions,
  newCableRevision,
  saveCableRevision,
} from "../api/cableDesigns";
import { Alert, Badge, Card, ErrorState, LoadingState, Modal } from "../components/ui";
import { useToast } from "../components/Toast";
import { useSession } from "../session/SessionContext";
import { formatDateTimePt } from "../utils/dates";
import { useCableEngine } from "../features/cables/useCableEngine";
import { useExportRunner } from "../features/cables/download";
import { buildCablePresentationState, buildCableSavePayload, useCableStudy } from "../features/cables/useCableStudy";
import type { CabosEngine, Result, State } from "../features/cables/engine";
import CabosACTab from "../features/cables/tabs/CabosACTab";
import EquipamentosTab from "../features/cables/tabs/EquipamentosTab";
import EsquemaUnifilarTab from "../features/cables/tabs/EsquemaUnifilarTab";
import QuadrosTab from "../features/cables/tabs/QuadrosTab";
import "./CableDesignEditor.css";

function isApprovedStatus(status: string): boolean {
  return status === "aprovado" || status === "aprovada";
}

function statusLabel(status: string): string {
  if (status === "rascunho") return "Rascunho";
  if (status === "em_analise" || status === "em análise") return "Em análise";
  if (isApprovedStatus(status)) return "Aprovado";
  return status;
}

function statusTone(status: string): "neutral" | "warning" | "success" {
  if (isApprovedStatus(status)) return "success";
  if (status === "em_analise" || status === "em análise") return "warning";
  return "neutral";
}

interface HistoricalCircuit {
  code: string;
  name: string;
  review: boolean;
  note?: string;
}

interface HistoricalResultData {
  circuits: HistoricalCircuit[];
  totals: { circuits: number; review: number; inverters: number; kw_ac?: number };
}

function recordOf(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function readHistoricalResult(value: unknown): HistoricalResultData | null {
  const envelope = recordOf(value);
  const totals = recordOf(envelope?.totals);
  if (envelope?.format !== 1 || !Array.isArray(envelope.circuits) || !totals) return null;
  if (!isCount(totals.circuits) || !isCount(totals.review) || !isCount(totals.inverters)) return null;
  if (totals.kw_ac !== undefined && (typeof totals.kw_ac !== "number" || !Number.isFinite(totals.kw_ac))) return null;

  const circuits: HistoricalCircuit[] = [];
  for (const value of envelope.circuits) {
    const circuit = recordOf(value);
    if (!circuit || typeof circuit.code !== "string" || typeof circuit.name !== "string" || typeof circuit.review !== "boolean") return null;
    if (circuit.note !== undefined && typeof circuit.note !== "string") return null;
    circuits.push({
      code: circuit.code,
      name: circuit.name,
      review: circuit.review,
      ...(typeof circuit.note === "string" ? { note: circuit.note } : {}),
    });
  }

  return {
    circuits,
    totals: {
      circuits: totals.circuits,
      review: totals.review,
      inverters: totals.inverters,
      ...(typeof totals.kw_ac === "number" ? { kw_ac: totals.kw_ac } : {}),
    },
  };
}

function formatHistoricalNumber(value: number): string {
  return new Intl.NumberFormat("pt-PT", { maximumFractionDigits: 2 }).format(value);
}

function HistoricalResultPanel({ revision }: { revision: CableDesignRevision }) {
  const historical = readHistoricalResult(revision.result_json);
  if (!historical) {
    return (
      <main className="cable-editor__summary">
        <Alert tone="warning" title="Resultado histórico indisponível">
          O resultado persistido desta revisão está ausente ou ilegível. Não será substituído por um cálculo atual; crie uma nova revisão para recalcular com o motor atual.
        </Alert>
      </main>
    );
  }

  return (
    <main className="cable-editor__summary">
      <Card title={`Resultado histórico aprovado · Rev. ${revision.rev}`} icon="activity">
        <p className="muted">Vista só de leitura dos dados persistidos da revisão aprovada; não foi recalculada com o motor atual.</p>
        <dl className="kv">
          <dt>Versão do motor</dt><dd>{revision.engine_version || "—"}</dd>
          <dt>Circuitos</dt><dd>{historical.totals.circuits}</dd>
          <dt>Circuitos a rever</dt><dd>{historical.totals.review}</dd>
          <dt>Inversores</dt><dd>{historical.totals.inverters}</dd>
          {historical.totals.kw_ac !== undefined && <><dt>Potência AC total</dt><dd>{formatHistoricalNumber(historical.totals.kw_ac)} kW</dd></>}
        </dl>
        {historical.circuits.length > 0 ? (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Circuitos do resultado histórico aprovado</caption>
              <thead><tr><th scope="col">Código</th><th scope="col">Circuito</th><th scope="col">Estado</th><th scope="col">Nota</th></tr></thead>
              <tbody>
                {historical.circuits.map((circuit, index) => (
                  <tr key={`${circuit.code}-${index}`}>
                    <td>{circuit.code}</td><td>{circuit.name}</td><td>{circuit.review ? "A rever" : "OK"}</td><td>{circuit.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="muted small">O resultado histórico não contém circuitos.</p>}
        <p className="muted small">Nova revisão recalcula com o motor atual e permite editar sem alterar esta revisão aprovada.</p>
      </Card>
    </main>
  );
}

function apiErrorMessage(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (reason.status === 403) return "Não tem permissão para abrir este estudo de cabos.";
    if (reason.status === 404) return "O estudo de cabos não existe ou não está no seu âmbito.";
    return reason.detail;
  }
  return reason instanceof Error ? reason.message : "Não foi possível contactar o servidor.";
}

function actorLabel(value: string | null | undefined, peopleById: ReadonlyMap<string, string>): string {
  const label = value ? peopleById.get(value) : undefined;
  return label && label.trim() ? label : "—";
}

function RevisionList({
  revisions,
  error,
  onRetry,
  peopleById,
}: {
  revisions: CableDesignRevision[] | null;
  error: string | null;
  onRetry: () => void;
  peopleById: ReadonlyMap<string, string>;
}) {
  if (revisions === null && error) return <ErrorState message={error} onRetry={onRetry} />;
  if (revisions === null) return <LoadingState label="A carregar revisões…" rows={3} />;
  if (revisions.length === 0) return <p className="muted small">Sem revisões registadas.</p>;
  return (
    <ul className="cable-editor__audit-list">
      {revisions.map((revision) => (
        <li key={revision.id}>
          <div className="cable-editor__audit-main">
            <strong>Rev. {revision.rev}</strong>
            <Badge tone={statusTone(revision.status)}>{statusLabel(revision.status)}</Badge>
          </div>
          <div className="small muted">
            {actorLabel(revision.approved_by_person_id ?? revision.created_by_person_id, peopleById)} · {formatDateTimePt(revision.updated_at)}
          </div>
        </li>
      ))}
    </ul>
  );
}

function HistoryList({
  history,
  error,
  onRetry,
  peopleById,
}: {
  history: CableDesignHistoryEntry[] | null;
  error: string | null;
  onRetry: () => void;
  peopleById: ReadonlyMap<string, string>;
}) {
  if (history === null && error) return <ErrorState message={error} onRetry={onRetry} />;
  if (history === null) return <LoadingState label="A carregar histórico…" rows={3} />;
  if (history.length === 0) return <p className="muted small">Sem histórico registado.</p>;
  return (
    <ul className="cable-editor__audit-list">
      {history.map((entry) => (
        <li key={entry.id}>
          <div className="cable-editor__audit-main">
            <strong>{entry.action}</strong>
            <span className="small muted">Rev. {entry.rev}</span>
          </div>
          <div className="small muted">{actorLabel(entry.actor_person_id, peopleById)} · {formatDateTimePt(entry.created_at)}</div>
        </li>
      ))}
    </ul>
  );
}

function AuditDrawer({
  revisions,
  revisionsError,
  onRetryRevisions,
  history,
  historyError,
  onRetryHistory,
  peopleById,
  onClose,
}: {
  revisions: CableDesignRevision[] | null;
  revisionsError: string | null;
  onRetryRevisions: () => void;
  history: CableDesignHistoryEntry[] | null;
  historyError: string | null;
  onRetryHistory: () => void;
  peopleById: ReadonlyMap<string, string>;
  onClose: () => void;
}) {
  return (
    <div className="cable-editor__drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="cable-editor__drawer" role="dialog" aria-modal="true" aria-label="Revisões e histórico">
        <header className="cable-editor__drawer-head">
          <h2>Revisões e histórico</h2>
          <button type="button" className="btn btn--ghost btn--icon" aria-label="Fechar" onClick={onClose}>×</button>
        </header>
        <div className="cable-editor__drawer-body">
          <Card title="Revisões" icon="activity"><RevisionList revisions={revisions} error={revisionsError} onRetry={onRetryRevisions} peopleById={peopleById} /></Card>
          <Card title="Histórico" icon="activity"><HistoryList history={history} error={historyError} onRetry={onRetryHistory} peopleById={peopleById} /></Card>
        </div>
      </aside>
    </div>
  );
}

function ConflictDialog({ state, onReload, onCopy, onClose }: { state: State; onReload: () => void; onCopy: () => void; onClose: () => void }) {
  return (
    <Modal title="Outra pessoa gravou este estudo" onClose={onClose}>
      <p>O estudo foi alterado por outra pessoa desde que o carregou.</p>
      <p>Escolha se quer descartar as suas alterações ou copiar o estado local para comparação.</p>
      <pre className="cable-editor__state-preview">{JSON.stringify(state, null, 2)}</pre>
      <div className="cable-editor__conflict-actions">
        <button type="button" className="btn" onClick={onReload}>Recarregar (descarta as minhas alterações)</button>
        <button type="button" className="btn btn--primary" onClick={onCopy}>Copiar o meu estado</button>
      </div>
    </Modal>
  );
}

const TABS = [
  ["ac", "Cabos AC"],
  ["sld", "Esquema unifilar"],
  ["boards", "Quadros"],
  ["equipment", "Equipamentos"],
] as const;

type TabId = typeof TABS[number][0];
type FileExporter = (engine: CabosEngine, state: State, result: Result) => unknown;

export default function CableDesignEditor() {
  const { projectId, designId } = useParams<{ projectId: string; designId: string }>();
  const navigate = useNavigate();
  const { can } = useSession();
  const canView = can("cable_design.view");
  const canEdit = can("cable_design.edit");
  const canViewCosts = can("cable_design.view_costs");
  const exportRunner = useExportRunner();
  const { notify } = useToast();
  const [design, setDesign] = useState<CableDesign | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [revisions, setRevisions] = useState<CableDesignRevision[] | null>(null);
  const [history, setHistory] = useState<CableDesignHistoryEntry[] | null>(null);
  // Falhas em secções auxiliares ficam visíveis: não se confundem com "sem dados".
  const [projectError, setProjectError] = useState<string | null>(null);
  const [revisionsError, setRevisionsError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [readOnlyOverride, setReadOnlyOverride] = useState(false);
  const [lockedMessage, setLockedMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [action, setAction] = useState<"approve" | "revision" | "deactivate" | null>(null);
  const [conflictState, setConflictState] = useState<State | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabId>("ac");
  const [peopleById, setPeopleById] = useState<ReadonlyMap<string, string>>(() => new Map());

  const approved = Boolean(design && (isApprovedStatus(design.status) || isApprovedStatus(design.revision.status)));
  const engineState = useCableEngine(canViewCosts && Boolean(design) && !approved);
  const study = useCableStudy(engineState.engine, design, project);
  const presentationState = useMemo(
    () => engineState.engine && study.state && design
      ? buildCablePresentationState(engineState.engine, study.state, design, peopleById)
      : null,
    [design, engineState.engine, peopleById, study.state],
  );
  const readOnly = useMemo(
    () => !design || readOnlyOverride || !canEdit || !design.is_active || isApprovedStatus(design.status) || isApprovedStatus(design.revision.status),
    [canEdit, design, readOnlyOverride],
  );
  const mutationLocked = readOnly || saving || action !== null;

  useEffect(() => {
    let mounted = true;
    void listPeople()
      .then((people) => {
        if (mounted) setPeopleById(new Map(people.map((person) => [person.id, person.display_name] as const)));
      })
      .catch(() => undefined);
    return () => { mounted = false; };
  }, []);

  const loadProject = useCallback(async (): Promise<Project | null> => {
    if (!projectId) return null;
    try {
      const loaded = await getProject(projectId);
      setProjectError(null);
      return loaded;
    } catch (reason) {
      setProjectError(errorMessage(reason));
      return null;
    }
  }, [projectId]);

  const loadRevisions = useCallback(async () => {
    if (!designId) return;
    setRevisionsError(null);
    try {
      setRevisions(await listCableRevisions(designId));
    } catch (reason) {
      setRevisions(null);
      setRevisionsError(errorMessage(reason));
    }
  }, [designId]);

  const loadHistory = useCallback(async () => {
    if (!designId) return;
    setHistoryError(null);
    try {
      setHistory(await listCableHistory(designId));
    } catch (reason) {
      setHistory(null);
      setHistoryError(errorMessage(reason));
    }
  }, [designId]);

  const load = useCallback(async () => {
    if (!designId) return;
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const loadedDesign = await getCableDesign(designId);
      const [loadedProject] = await Promise.all([loadProject(), loadRevisions(), loadHistory()]);
      setDesign(loadedDesign);
      setProject(loadedProject);
    } catch (reason) {
      setDesign(null);
      setProject(null);
      setError(apiErrorMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [designId, loadProject, loadRevisions, loadHistory]);

  useEffect(() => {
    if (!canView) {
      setLoading(false);
      setError("Não tem permissão para ver este estudo de cabos.");
      return;
    }
    void load();
  }, [canView, load]);

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!study.flush()?.dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [study.flush]);

  const refreshAudit = useCallback(async () => {
    if (!designId) return;
    await Promise.all([loadRevisions(), loadHistory()]);
  }, [designId, loadRevisions, loadHistory]);

  const retryProject = useCallback(async () => {
    // O projeto fornece os valores iniciais do estudo: recarregá-lo reinicia o estudo e
    // descartaria alterações por gravar.
    if (study.flush()?.dirty) {
      setActionError("Grave as alterações antes de voltar a carregar os dados do projeto.");
      return;
    }
    setActionError(null);
    const loaded = await loadProject();
    if (loaded) setProject(loaded);
  }, [loadProject, study.flush]);

  const saveCurrent = useCallback(async (force = false): Promise<CableDesign | null> => {
    if (!design || !designId || readOnly || !engineState.engine || !study.store) return design;
    const currentStore = study.flush() ?? study.store;
    if (!force && !currentStore.dirty) return design;
    setSaving(true);
    setActionError(null);
    try {
      const payload = buildCableSavePayload(engineState.engine, currentStore);
      const updated = await saveCableRevision(designId, {
        expected_version: design.version,
        title: design.title,
        ...payload,
      });
      setDesign(updated);
      await study.markSaved(currentStore.state);
      await refreshAudit();
      return updated;
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) setConflictState(currentStore.state);
      else if (reason instanceof ApiError && reason.status === 423) {
        setReadOnlyOverride(true);
        setLockedMessage("Este estudo foi bloqueado. Foi recarregado em modo só leitura.");
        await load();
      } else {
        setActionError(apiErrorMessage(reason));
      }
      return null;
    } finally {
      setSaving(false);
    }
  }, [design, designId, engineState.engine, load, readOnly, refreshAudit, study]);

  async function approve() {
    if (!design || !designId || readOnly || !canEdit || action || saving || !engineState.engine) return;
    setAction("approve");
    setActionError(null);
    try {
      const saved = await saveCurrent(true);
      if (!saved) return;
      const updated = await approveCableDesign(designId, saved.version);
      setDesign(updated);
      await refreshAudit();
    } catch (reason) {
      setActionError(apiErrorMessage(reason));
    } finally {
      setAction(null);
    }
  }

  async function createRevision() {
    if (!design || !designId || !canEdit || !approved || action || saving) return;
    setAction("revision");
    setActionError(null);
    try {
      const updated = await newCableRevision(designId, design.version);
      setDesign(updated);
      setReadOnlyOverride(false);
      setLockedMessage(null);
      await refreshAudit();
    } catch (reason) {
      setActionError(apiErrorMessage(reason));
    } finally {
      setAction(null);
    }
  }

  async function deactivate() {
    if (!design || !designId || !canEdit || action || saving || !window.confirm("Tens a certeza?")) return;
    setAction("deactivate");
    setActionError(null);
    try {
      await deactivateCableDesign(designId, design.version);
      navigate(`/projects/${encodeURIComponent(projectId ?? design.project_id)}?tab=cabos`);
    } catch (reason) {
      setActionError(apiErrorMessage(reason));
    } finally {
      setAction(null);
    }
  }

  function goBack() {
    if (study.flush()?.dirty && !window.confirm("Tem alterações por guardar. Sair sem guardar?")) return;
    navigate(`/projects/${encodeURIComponent(projectId ?? design?.project_id ?? "")}?tab=cabos`);
  }

  const exportDisabled = approved || !engineState.engine || !presentationState || !study.result || exportRunner.isGenerating;

  function startExport(exporter: FileExporter): void {
    const engine = engineState.engine;
    const state = presentationState;
    const result = study.result;
    if (approved || !engine || !state || !result || exportRunner.isGenerating) return;
    setMoreOpen(false);
    void exportRunner.run(() => Promise.resolve(exporter(engine, state, result)) as Promise<{ blob: Blob; filename: string }>);
  }

  async function copyTable(): Promise<void> {
    const engine = engineState.engine;
    const state = presentationState;
    const result = study.result;
    setMoreOpen(false);
    if (approved || !engine || !state || !result || exportRunner.isGenerating) return;
    try {
      const text = String(engine.exports.copyTable(state, result));
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        throw new Error("clipboard-indisponível");
      }
      await navigator.clipboard.writeText(text);
      notify("Tabela copiada", "success");
    } catch {
      notify("Não foi possível copiar a tabela: a área de transferência não está disponível ou recusou o acesso.", "error");
    }
  }

  function exportMenuItem(
    label: string,
    exporter: (engine: NonNullable<typeof engineState.engine>, state: State, result: NonNullable<typeof study.result>) => ReturnType<NonNullable<typeof engineState.engine>["exports"][keyof NonNullable<typeof engineState.engine>["exports"]]>,
  ) {
    return (
      <button type="button" role="menuitem" onClick={() => startExport(exporter)} disabled={exportDisabled}>
        {exportRunner.isGenerating ? exportRunner.label : label}
      </button>
    );
  }

  async function reloadAfterConflict() {
    setConflictState(null);
    await load();
  }

  async function copyStateAndReload() {
    if (!conflictState) return;
    const text = JSON.stringify(conflictState, null, 2);
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "true");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      setConflictState(null);
      await load();
    } catch {
      setActionError("Não foi possível copiar o estado do estudo.");
    }
  }

  if (loading || (!approved && canViewCosts && engineState.status === "loading")) {
    return <div className="cable-editor cable-editor--state"><LoadingState label="A carregar o estudo de cabos…" rows={5} /></div>;
  }

  if (error || !design) {
    return <div className="cable-editor cable-editor--state"><ErrorState message={error ?? "Estudo de cabos indisponível."} onRetry={() => void load()} /></div>;
  }

  if (!approved && canViewCosts && engineState.status === "error") {
    return <div className="cable-editor cable-editor--state"><ErrorState message={engineState.error ?? "Ferramenta de cálculo indisponível"} onRetry={engineState.retry} /></div>;
  }

  const projectPath = `/projects/${encodeURIComponent(projectId ?? design.project_id)}?tab=cabos`;
  const displayedStatus = approved
    ? isApprovedStatus(design.status) ? design.status : design.revision.status
    : design.status;
  const renderTab = () => {
    if (!engineState.engine || !presentationState || !study.result) return null;
    const props = { state: presentationState, result: study.result, engine: engineState.engine, readOnly: mutationLocked, apply: study.apply };
    if (activeTab === "sld") return <EsquemaUnifilarTab {...props} />;
    if (activeTab === "boards") return <QuadrosTab {...props} />;
    if (activeTab === "equipment") return <EquipamentosTab {...props} />;
    return <CabosACTab {...props} />;
  };

  return (
    <div className="cable-editor">
      <header className="cable-editor__toolbar">
        <button type="button" className="btn btn--ghost cable-editor__back" onClick={goBack}>← Voltar</button>
        <div className="cable-editor__identity">
          <h1>{design.title}</h1>
          <div className="cable-editor__meta">
            <Badge tone={statusTone(displayedStatus)}>{statusLabel(displayedStatus)}</Badge>
            <span>Rev. {design.current_revision} · versão {design.version}</span>
            {study.dirty && <span className="cable-editor__dirty">Alterações por guardar</span>}
          </div>
        </div>
        <div className="cable-editor__actions">
          {!approved && <button type="button" className="btn btn--primary" onClick={() => void saveCurrent()} disabled={!study.dirty || mutationLocked || !engineState.engine}>
            {saving ? "A guardar…" : "Guardar"}
          </button>}
          {!approved && canEdit && design.is_active && (
            <button type="button" className="btn" onClick={() => void approve()} disabled={readOnly || saving || action !== null || !engineState.engine}>
              {action === "approve" ? "A aprovar…" : "Aprovar"}
            </button>
          )}
          {approved && canEdit && (
            <button type="button" className="btn" onClick={() => void createRevision()} disabled={saving || action !== null}>
              {action === "revision" ? "A criar…" : "Nova revisão"}
            </button>
          )}
          <div className="cable-editor__more">
            <button type="button" className="btn btn--ghost" aria-haspopup="menu" aria-expanded={moreOpen} onClick={() => setMoreOpen((open) => !open)}>⋯ Mais</button>
            {moreOpen && (
              <div className="cable-editor__more-menu" role="menu">
                <button type="button" role="menuitem" onClick={() => { setDrawerOpen(true); setMoreOpen(false); }}>Revisões e histórico</button>
                {!approved && <div className="cable-editor__export-group">
                  <span>Exportar</span>
                  {exportMenuItem("Relatório de cálculo (PDF)", (engine, state, result) => engine.exports.reportPdf(state, result))}
                  {exportMenuItem("Relatório (Word)", (engine, state, result) => engine.exports.reportDocx(state, result))}
                  {exportMenuItem("Orçamento (PDF)", (engine, state, result) => engine.exports.bomPdf(state, result))}
                  {exportMenuItem("Esquema unifilar (PDF)", (engine, state, result) => engine.exports.sldPdf(state, result))}
                  {exportMenuItem("Esquema unifilar (SVG)", (engine, state, result) => engine.exports.sldSvg(state, result))}
                  {exportMenuItem("Esquema unifilar (PNG)", (engine, state, result) => engine.exports.sldPng(state, result))}
                  {exportMenuItem("Esquema unifilar (DXF)", (engine, state, result) => engine.exports.sldDxf(state, result))}
                  <button type="button" role="menuitem" onClick={() => void copyTable()} disabled={exportDisabled}>
                    Copiar tabela
                  </button>
                </div>}
                {canEdit && design.is_active && <button type="button" role="menuitem" className="cable-editor__danger-action" disabled={saving || action !== null} onClick={() => { setMoreOpen(false); void deactivate(); }}>Desativar</button>}
              </div>
            )}
          </div>
        </div>
      </header>

      {actionError && <Alert tone="danger">{actionError}</Alert>}
      {projectError && (
        <Alert
          tone="warning"
          title="Não foi possível carregar os dados do projeto."
          action={<button type="button" className="btn btn--sm" onClick={() => void retryProject()}>Tentar novamente</button>}
        >
          O nome, o cliente e a morada da obra podem ficar por preencher. {projectError}
        </Alert>
      )}
      {lockedMessage && <Alert tone="warning">{lockedMessage}</Alert>}

      {approved ? (
        <HistoricalResultPanel revision={design.revision} />
      ) : !canViewCosts ? (
        <main className="cable-editor__summary">
          <Card title="Resumo do estudo" icon="activity">
            <dl className="kv">
              <dt>Estado</dt><dd><Badge tone={statusTone(design.status)}>{statusLabel(design.status)}</Badge></dd>
              <dt>Revisão</dt><dd>{design.current_revision}</dd>
              <dt>Circuitos a rever</dt><dd>{design.unresolved_circuits}</dd>
            </dl>
            <p className="cable-editor__no-costs">Não tem acesso à ferramenta de cálculo (custos e catálogos comerciais).</p>
            <button type="button" className="btn" onClick={() => setDrawerOpen(true)}>Revisões e histórico</button>
          </Card>
        </main>
      ) : engineState.engine && presentationState && study.result ? (
        <main className="cable-editor__workspace">
          <nav className="tabs cable-editor__tabs" role="tablist" aria-label="Secções do estudo">
            {TABS.map(([id, label]) => (
              <button key={id} type="button" role="tab" className="tab" aria-selected={activeTab === id} aria-controls={`cable-panel-${id}`} onClick={() => setActiveTab(id)}>{label}</button>
            ))}
          </nav>
          <section id={`cable-panel-${activeTab}`} className="cable-editor__content" role="tabpanel">
            {renderTab()}
          </section>
        </main>
      ) : (
        <main className="cable-editor__summary"><ErrorState message="O estudo de cabos ainda não está pronto." /></main>
      )}

      {drawerOpen && <AuditDrawer revisions={revisions} revisionsError={revisionsError} onRetryRevisions={() => void loadRevisions()} history={history} historyError={historyError} onRetryHistory={() => void loadHistory()} peopleById={peopleById} onClose={() => setDrawerOpen(false)} />}
      {conflictState && <ConflictDialog state={conflictState} onReload={() => void reloadAfterConflict()} onCopy={() => void copyStateAndReload()} onClose={() => setConflictState(null)} />}
      <a className="sr-only" href={projectPath}>Voltar ao projeto</a>
    </div>
  );
}
