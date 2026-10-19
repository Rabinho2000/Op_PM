import { useEffect, useMemo, useState } from "react";
import {
  BoardColumn,
  BoardResponse,
  getBoard,
  injectIntoOpPm,
  SalesItem,
  syncClickUp,
} from "./api";

const COLUMNS: { id: BoardColumn; label: string; hint: string }[] = [
  { id: "todo", label: "Por fazer", hint: "Ainda sem execução activa" },
  { id: "in_progress", label: "A executar", hint: "Trabalho comercial / técnico em curso" },
  { id: "done", label: "Feito", hint: "Pronto ou já entregue a Operações" },
];

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function formatTime(iso: string) {
  return new Intl.DateTimeFormat("pt-PT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

function ItemCard({ item, onOpen }: { item: SalesItem; onOpen: (item: SalesItem) => void }) {
  return (
    <button className="deal-card" type="button" onClick={() => onOpen(item)}>
      <div className="deal-card__top">
        <span className={`priority priority--${item.priority}`}>{item.priority === "normal" ? "normal" : item.priority}</span>
        {item.op_pm_project_id && <span className="op-tag">OP-PM</span>}
      </div>
      <h3>{item.title}</h3>
      <p className="client">{item.client}</p>
      <div className="deal-card__data">
        <span>{item.power_kwp ? `${item.power_kwp.toLocaleString("pt-PT")} kWp` : "Potência em falta"}</span>
        <span>{item.location}</span>
      </div>
      <div className="deal-card__status">{item.clickup_status}</div>
      <div className="deal-card__footer">
        <span className="avatar" title={item.owner}>{initials(item.owner)}</span>
        <span className="muted">{item.due_date ? `Prazo ${item.due_date}` : "Sem prazo"}</span>
      </div>
      {item.missing_fields.length > 0 && (
        <div className="missing">{item.missing_fields.length} campo{item.missing_fields.length > 1 ? "s" : ""} em falta</div>
      )}
    </button>
  );
}

function DetailDrawer({
  item,
  onClose,
  onInjected,
}: {
  item: SalesItem | null;
  onClose: () => void;
  onInjected: (taskId: string, projectId: string) => void;
}) {
  const [injecting, setInjecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!item) return null;

  async function handleInject() {
    setInjecting(true);
    setError(null);
    try {
      const result = await injectIntoOpPm(item);
      onInjected(item.clickup_task_id, result.project_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível criar o projecto no OP-PM.");
    } finally {
      setInjecting(false);
    }
  }

  const canInject = item.ready_for_op_pm && !item.op_pm_project_id && item.missing_fields.length === 0;

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" aria-label="Detalhe do projecto comercial">
        <div className="drawer__header">
          <div>
            <span className="eyebrow">ClickUp · {item.clickup_task_id}</span>
            <h2>{item.title}</h2>
            <p>{item.client}</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Fechar">×</button>
        </div>

        <div className="drawer__section">
          <h4>Resumo para Operações</h4>
          <dl className="detail-grid">
            <div><dt>Estado ClickUp</dt><dd>{item.clickup_status}</dd></div>
            <div><dt>Potência</dt><dd>{item.power_kwp ? `${item.power_kwp} kWp` : "—"}</dd></div>
            <div><dt>Local</dt><dd>{item.location || "—"}</dd></div>
            <div><dt>Responsável</dt><dd>{item.owner}</dd></div>
            <div><dt>Prazo</dt><dd>{item.due_date || "—"}</dd></div>
            <div><dt>Última alteração</dt><dd>{formatTime(item.updated_at)}</dd></div>
          </dl>
        </div>

        <div className="drawer__section">
          <h4>Validação antes da injecção</h4>
          {item.missing_fields.length === 0 ? (
            <div className="validation validation--ok">Campos mínimos completos.</div>
          ) : (
            <div className="validation validation--warn">
              <strong>Falta completar:</strong>
              <ul>{item.missing_fields.map((field) => <li key={field}>{field}</li>)}</ul>
            </div>
          )}
        </div>

        <div className="drawer__section flow-box">
          <div className="flow-step"><span>1</span><div><strong>ClickUp</strong><small>Fonte comercial</small></div></div>
          <div className="flow-arrow">→</div>
          <div className="flow-step"><span>2</span><div><strong>Sales Support</strong><small>Validação</small></div></div>
          <div className="flow-arrow">→</div>
          <div className="flow-step"><span>3</span><div><strong>OP-PM</strong><small>Project + external ID</small></div></div>
        </div>

        {item.op_pm_project_id ? (
          <div className="already-injected">
            <strong>Já está no OP-PM</strong>
            <code>{item.op_pm_project_id}</code>
          </div>
        ) : (
          <button className="primary-button primary-button--wide" type="button" disabled={!canInject || injecting} onClick={handleInject}>
            {injecting ? "A criar no OP-PM…" : "Injectar projecto no OP-PM"}
          </button>
        )}
        {!item.ready_for_op_pm && !item.op_pm_project_id && (
          <p className="helper">Este item ainda não está marcado como pronto para entrega a Operações.</p>
        )}
        {error && <div className="error-box">{error}</div>}
      </aside>
    </>
  );
}

export default function App() {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [selected, setSelected] = useState<SalesItem | null>(null);
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBoard().then(setBoard).catch((e) => setError(e instanceof Error ? e.message : "Erro a carregar dados."));
  }, []);

  const owners = useMemo(
    () => Array.from(new Set(board?.items.map((item) => item.owner) ?? [])).sort(),
    [board],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("pt-PT");
    return (board?.items ?? []).filter((item) => {
      if (owner && item.owner !== owner) return false;
      if (!q) return true;
      return [item.title, item.client, item.location, item.clickup_status]
        .join(" ")
        .toLocaleLowerCase("pt-PT")
        .includes(q);
    });
  }, [board, query, owner]);

  const metrics = useMemo(() => {
    const items = board?.items ?? [];
    return {
      open: items.filter((item) => item.column !== "done").length,
      executing: items.filter((item) => item.column === "in_progress").length,
      ready: items.filter((item) => item.ready_for_op_pm && !item.op_pm_project_id && item.missing_fields.length === 0).length,
      injected: items.filter((item) => item.op_pm_project_id).length,
    };
  }, [board]);

  async function handleSync() {
    setSyncing(true);
    setError(null);
    try {
      setBoard(await syncClickUp());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro a sincronizar ClickUp.");
    } finally {
      setSyncing(false);
    }
  }

  function handleInjected(taskId: string, projectId: string) {
    setBoard((current) => current ? {
      ...current,
      items: current.items.map((item) => item.clickup_task_id === taskId
        ? { ...item, op_pm_project_id: projectId, ready_for_op_pm: false }
        : item),
    } : current);
    setSelected((current) => current?.clickup_task_id === taskId
      ? { ...current, op_pm_project_id: projectId, ready_for_op_pm: false }
      : current);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div><strong>Sales Support</strong><span>Pré-Operações</span></div>
        </div>
        <nav>
          <a className="nav-link nav-link--active" href="#board"><span>▦</span> Pipeline</a>
          <a className="nav-link" href="#ready"><span>↗</span> Prontos para OP-PM <b>{metrics.ready}</b></a>
          <a className="nav-link" href="#sync"><span>↻</span> Sincronização</a>
          <div className="nav-section">Ligações</div>
          <a className="nav-link" href="#clickup"><span>CU</span> ClickUp</a>
          <a className="nav-link" href="#oppm"><span>OP</span> OP-PM</a>
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" /> Mesmo servidor · mesma BD
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span className="eyebrow">Comercial → Operações</span>
            <h1>Sales Support</h1>
          </div>
          <div className="topbar-actions">
            <div className="sync-info">
              <span className={`source-pill ${board?.source === "clickup" ? "source-pill--live" : ""}`}>
                {board?.source === "clickup" ? "ClickUp live" : "Mock data"}
              </span>
              <small>{board ? `Sincronizado ${formatTime(board.synced_at)}` : "A carregar…"}</small>
            </div>
            <button className="secondary-button" type="button" onClick={handleSync} disabled={syncing}>
              {syncing ? "A sincronizar…" : "Sincronizar ClickUp"}
            </button>
          </div>
        </header>

        <section className="metric-grid">
          <article><span>Em aberto</span><strong>{metrics.open}</strong><small>projectos comerciais activos</small></article>
          <article><span>A executar</span><strong>{metrics.executing}</strong><small>trabalho em curso</small></article>
          <article className="metric-card--accent"><span>Prontos para OP-PM</span><strong>{metrics.ready}</strong><small>sem campos bloqueantes</small></article>
          <article><span>Já injectados</span><strong>{metrics.injected}</strong><small>ligação ClickUp ↔ OP-PM</small></article>
        </section>

        <section className="toolbar">
          <div className="search-wrap">
            <span>⌕</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Pesquisar projecto, cliente, local ou estado…" />
          </div>
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Todos os responsáveis</option>
            {owners.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <span className="result-count">{filtered.length} itens</span>
        </section>

        {error && <div className="error-box">{error}</div>}

        <section className="kanban" id="board">
          {COLUMNS.map((column) => {
            const items = filtered.filter((item) => item.column === column.id);
            return (
              <div className="kanban-column" key={column.id}>
                <div className="column-header">
                  <div><h2>{column.label}</h2><p>{column.hint}</p></div>
                  <span>{items.length}</span>
                </div>
                <div className="column-body">
                  {items.map((item) => <ItemCard key={item.clickup_task_id} item={item} onOpen={setSelected} />)}
                  {items.length === 0 && <div className="empty-column">Sem itens nesta coluna.</div>}
                </div>
              </div>
            );
          })}
        </section>
      </main>

      <DetailDrawer item={selected} onClose={() => setSelected(null)} onInjected={handleInjected} />
    </div>
  );
}
