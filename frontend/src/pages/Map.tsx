// Mapa operacional: instalações, fornecedores, pontos de recolha e
// pendências. Sem provider de tiles configurado (MAP_TILE_URL), mostra
// sempre a lista funcional dos locais em vez de deixar a página quebrada
// — nunca depende de um serviço externo para o resto da app funcionar
// (ver docs/MAP_AND_PLANNING.md). Sem otimização automática de rotas, por
// pedido explícito — só seleção manual + link para uma rota externa.
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import "leaflet.markercluster/dist/MarkerCluster.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  createPickupPoint,
  createCalendarEvent,
  createSupplier,
  createTask,
  getMapData,
  MapAttention,
  MapData,
  MapPickupPoint,
  MapProject,
  MapSupplier,
  optimizeRoute,
  planTrip,
  ProjectIssue,
  RouteOptimization,
  RouteStopKind,
  TripPlan,
  TASK_CATEGORY_LABELS,
  TASK_PRIORITY_LABELS,
  TaskCategory,
  TaskPriority,
  updateProject,
} from "../api/client";
import Icon, { IconName } from "../components/Icon";
import TripPlanModal from "../components/TripPlanModal";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader, Tone } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { PROJECT_STATUS_LABELS } from "../api/client";
import { PROJECT_STATUS_TONES } from "../utils/labels";
import { formatDatePt, formatDateTimePt, lisbonWallClockToIso } from "../utils/dates";
import { canFilterByMaterial, EMPTY_MAP_FILTERS, filterMapProjects, MapFilters } from "../utils/mapFilters";

type LayerKey = "projects" | "suppliers" | "pickups" | "issues";

type SelectedItem =
  | { kind: "project"; item: MapProject }
  | { kind: "supplier"; item: MapSupplier }
  | { kind: "pickup"; item: MapPickupPoint }
  | { kind: "issue"; item: ProjectIssue };

const MARKER_COLORS: Record<LayerKey, string> = {
  projects: "#2f7d4f",
  suppliers: "#2563eb",
  pickups: "#d97706",
  issues: "#dc2626",
};

// `attention` (green|yellow|red) vem sempre calculado do servidor — o
// frontend só apresenta, nunca recalcula a regra (ver docs/DECISIONS.md
// D-058). Cores/tons/labels alinhados com o resto da app (var(--success)/
// var(--warning)/var(--danger), ver src/styles/app.css).
const ATTENTION_COLORS: Record<MapAttention, string> = {
  green: "var(--success)",
  yellow: "var(--warning)",
  red: "var(--danger)",
};

const ATTENTION_TONES: Record<MapAttention, Tone> = {
  green: "success",
  yellow: "warning",
  red: "danger",
};

const ATTENTION_LABELS: Record<MapAttention, string> = {
  green: "Sem pendências operacionais",
  yellow: "Atenção",
  red: "Crítico",
};

function AttentionDot({ attention }: { attention: MapAttention }) {
  return (
    <span
      aria-hidden="true"
      title={ATTENTION_LABELS[attention]}
      style={{
        display: "inline-block",
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: ATTENTION_COLORS[attention],
        flexShrink: 0,
      }}
    />
  );
}

function makeDivIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<span style="display:block;width:16px;height:16px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 2px rgba(0,0,0,0.5);"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function EditCoordinatesModal({
  project,
  onClose,
  onSaved,
}: {
  project: MapProject;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!lat || !lon) {
      setError("Indique latitude e longitude.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateProject(project.id, { lat: Number(lat), lon: Number(lon) });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar as coordenadas.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Coordenadas — ${project.name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="button" className="btn btn--primary" onClick={handleSave} disabled={saving}>
            {saving ? "A guardar…" : "Guardar"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="form-grid">
        <div className="field">
          <label htmlFor="m-lat">Latitude</label>
          <input id="m-lat" className="input" type="number" step="0.000001" value={lat} onChange={(e) => setLat(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="m-lon">Longitude</label>
          <input id="m-lon" className="input" type="number" step="0.000001" value={lon} onChange={(e) => setLon(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
}

// Cria uma tarefa no projeto selecionado (Fase F). Reaproveita POST /api/tasks:
// o servidor valida sempre permissões (um PM só cria no seu projeto e só
// atribuída a si — nunca confiado à UI), a categoria e a prioridade.
function CreateTaskModal({
  project,
  onClose,
  onDone,
}: {
  project: MapProject;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState<{ title: string; category: TaskCategory; priority: TaskPriority; due_date: string }>({
    title: "",
    category: "field",
    priority: "medium",
    due_date: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!form.title.trim()) {
      setError("Indique o título da tarefa.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createTask({
        project_id: project.id,
        title: form.title.trim(),
        category: form.category,
        priority: form.priority,
        due_date: form.due_date || null,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar a tarefa.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Nova tarefa — ${project.name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="button" className="btn btn--primary" onClick={handleSave} disabled={saving}>
            {saving ? "A criar…" : "Criar tarefa"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="form-grid">
        <div className="field span-2">
          <label htmlFor="t-title">Título *</label>
          <input id="t-title" className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="t-category">Categoria</label>
          <select id="t-category" className="select" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as TaskCategory })}>
            {(Object.keys(TASK_CATEGORY_LABELS) as TaskCategory[]).map((c) => (
              <option key={c} value={c}>
                {TASK_CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="t-priority">Prioridade</label>
          <select id="t-priority" className="select" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as TaskPriority })}>
            {(Object.keys(TASK_PRIORITY_LABELS) as TaskPriority[]).map((p) => (
              <option key={p} value={p}>
                {TASK_PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="t-due">Prazo</label>
          <input id="t-due" className="input" type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
        </div>
      </div>
      <p className="small muted">
        Só as categorias Campo e Material contam para o estado de atenção do mapa.
      </p>
    </Modal>
  );
}

// Agenda uma visita (Fase F) como evento de calendário do projeto, via o
// POST /api/planning/events existente — o servidor valida `calendar.manage` e
// o âmbito do projeto. As horas são de Lisboa e convertidas para um instante
// com offset (lisbonWallClockToIso), nunca enviadas como string "nua".
function ScheduleVisitModal({
  project,
  onClose,
  onDone,
}: {
  project: MapProject;
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({ title: "Visita técnica", starts_at: "", ends_at: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!form.title.trim() || !form.starts_at || !form.ends_at) {
      setError("Indique título, início e fim.");
      return;
    }
    const startsAt = lisbonWallClockToIso(form.starts_at);
    const endsAt = lisbonWallClockToIso(form.ends_at);
    if (endsAt <= startsAt) {
      setError("O fim tem de ser depois do início.");
      return;
    }
    if (new Date(startsAt).getTime() < Date.now()) {
      setError("Uma visita futura tem de começar no futuro.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createCalendarEvent({
        title: form.title.trim(),
        starts_at: startsAt,
        ends_at: endsAt,
        project_id: project.id,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível agendar a visita.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Agendar visita — ${project.name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="button" className="btn btn--primary" onClick={handleSave} disabled={saving}>
            {saving ? "A agendar…" : "Agendar visita"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="form-grid">
        <div className="field span-2">
          <label htmlFor="v-title">Título *</label>
          <input id="v-title" className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="v-start">Início *</label>
          <input id="v-start" className="input" type="datetime-local" value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="v-end">Fim *</label>
          <input id="v-end" className="input" type="datetime-local" value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
        </div>
      </div>
      <p className="small muted">Horas de Lisboa. A visita fica como rascunho local no calendário (sem Outlook).</p>
    </Modal>
  );
}

function CreateSupplierModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ name: "", category: "", contact: "", email: "", address: "", lat: "", lon: "", materials: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!form.name) {
      setError("Indique o nome do fornecedor.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createSupplier({
        name: form.name,
        category: form.category || undefined,
        contact: form.contact || undefined,
        email: form.email || undefined,
        address: form.address || undefined,
        lat: form.lat ? Number(form.lat) : undefined,
        lon: form.lon ? Number(form.lon) : undefined,
        materials: form.materials,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar o fornecedor.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Novo fornecedor"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="button" className="btn btn--primary" onClick={handleSave} disabled={saving}>
            {saving ? "A criar…" : "Criar"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="form-grid">
        <div className="field span-2">
          <label htmlFor="s-name">Nome *</label>
          <input id="s-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="s-category">Categoria</label>
          <input id="s-category" className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="s-contact">Contacto</label>
          <input id="s-contact" className="input" value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="s-address">Morada</label>
          <input id="s-address" className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="s-lat">Latitude</label>
          <input id="s-lat" className="input" type="number" step="0.000001" value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="s-lon">Longitude</label>
          <input id="s-lon" className="input" type="number" step="0.000001" value={form.lon} onChange={(e) => setForm({ ...form, lon: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="s-materials">Materiais</label>
          <textarea id="s-materials" className="textarea" rows={2} value={form.materials} onChange={(e) => setForm({ ...form, materials: e.target.value })} />
        </div>
      </div>
    </Modal>
  );
}

function CreatePickupPointModal({
  suppliers,
  onClose,
  onDone,
}: {
  suppliers: MapSupplier[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({ name: "", supplier_id: "", address: "", lat: "", lon: "", schedule: "", materials: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!form.name) {
      setError("Indique o nome do ponto de recolha.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createPickupPoint({
        name: form.name,
        supplier_id: form.supplier_id || undefined,
        address: form.address || undefined,
        lat: form.lat ? Number(form.lat) : undefined,
        lon: form.lon ? Number(form.lon) : undefined,
        schedule: form.schedule || undefined,
        materials: form.materials,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar o ponto de recolha.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Novo ponto de recolha"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="button" className="btn btn--primary" onClick={handleSave} disabled={saving}>
            {saving ? "A criar…" : "Criar"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="form-grid">
        <div className="field span-2">
          <label htmlFor="p-name">Nome *</label>
          <input id="p-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="p-supplier">Fornecedor</label>
          <select id="p-supplier" className="select" value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}>
            <option value="">— nenhum —</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor="p-address">Morada</label>
          <input id="p-address" className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="p-lat">Latitude</label>
          <input id="p-lat" className="input" type="number" step="0.000001" value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="p-lon">Longitude</label>
          <input id="p-lon" className="input" type="number" step="0.000001" value={form.lon} onChange={(e) => setForm({ ...form, lon: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="p-schedule">Horário</label>
          <input id="p-schedule" className="input" value={form.schedule} onChange={(e) => setForm({ ...form, schedule: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="p-materials">Materiais</label>
          <textarea id="p-materials" className="textarea" rows={2} value={form.materials} onChange={(e) => setForm({ ...form, materials: e.target.value })} />
        </div>
      </div>
    </Modal>
  );
}

type MapItem = {
  key: string;
  layer: LayerKey;
  lat: number;
  lon: number;
  title: string;
  onClick: () => void;
  // Só definido para projetos — sobrepõe a cor por omissão da camada com
  // a cor do `attention` (ver ATTENTION_COLORS acima).
  color?: string;
  // Só definido para projetos — usado para colorir os clusters pela pior
  // attention dos pins agrupados (ver clusterIcon).
  attention?: MapAttention;
};

const ATTENTION_RANK: Record<MapAttention, number> = { green: 0, yellow: 1, red: 2 };

// Ícone do cluster de instalações: cor pela PIOR attention dos filhos (nunca
// pelas cores por omissão do plugin, que se confundiriam com o semáforo).
function clusterIcon(cluster: L.MarkerCluster): L.DivIcon {
  let worst: MapAttention = "green";
  for (const marker of cluster.getAllChildMarkers()) {
    const a = (marker.options as { attention?: MapAttention }).attention ?? "green";
    if (ATTENTION_RANK[a] > ATTENTION_RANK[worst]) worst = a;
  }
  return L.divIcon({
    className: "",
    html: `<span style="display:flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:50%;background:${ATTENTION_COLORS[worst]};color:#fff;font-weight:700;border:3px solid white;box-shadow:0 0 3px rgba(0,0,0,0.5);">${cluster.getChildCount()}</span>`,
    iconSize: [34, 34],
  });
}

function LeafletMap({ items }: { items: MapItem[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<L.Layer[]>([]);
  const { config } = useMapConfigContext();

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, { scrollWheelZoom: true }).setView([39.6, -8.0], 7);
    L.tileLayer(config.tile_url, { attribution: config.tile_attribution, maxZoom: 19 }).addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    layersRef.current.forEach((l) => l.remove());
    layersRef.current = [];
    // Só as instalações são agrupadas; fornecedores/recolhas/pendências
    // ficam soltos (significados diferentes, poucos pontos).
    const clusters = L.markerClusterGroup({ iconCreateFunction: clusterIcon, maxClusterRadius: 50 });
    const bounds: L.LatLngExpression[] = [];
    for (const item of items) {
      const marker = L.marker([item.lat, item.lon], {
        icon: makeDivIcon(item.color ?? MARKER_COLORS[item.layer]),
        attention: item.attention,
      } as L.MarkerOptions)
        .bindTooltip(item.title)
        .on("click", item.onClick);
      if (item.layer === "projects") clusters.addLayer(marker);
      else {
        marker.addTo(map);
        layersRef.current.push(marker);
      }
      bounds.push([item.lat, item.lon]);
    }
    clusters.addTo(map);
    layersRef.current.push(clusters);
    if (bounds.length > 0) {
      map.fitBounds(bounds as L.LatLngBoundsExpression, { padding: [30, 30], maxZoom: 14 });
    }
  }, [items]);

  return <div ref={containerRef} style={{ height: 480, borderRadius: 12, overflow: "hidden" }} />;
}

// Barra de resumo do mapa — sempre a partir de `data.summary`, nunca
// recalculada no frontend a partir das listas (mesma regra do dashboard,
// D-041). `map_coverage_percent` (cobertura de coordenadas) e
// `operational_clean_percent` (estado operacional) ficam deliberadamente
// separadas — nunca uma métrica de "limpeza" só (ver D-058).
function MapSummaryStat({ label, value, icon, tone }: { label: string; value: string; icon: IconName; tone: Tone }) {
  return (
    <div className="card stat">
      <span className={`stat__icon tone-${tone}`}>
        <Icon name={icon} size={20} />
      </span>
      <span>
        <span className="stat__value">{value}</span>
        <span className="stat__label" style={{ display: "block" }}>
          {label}
        </span>
      </span>
    </div>
  );
}

function MapSummaryBar({ summary }: { summary: MapData["summary"] }) {
  return (
    <div className="grid grid--stats" aria-label="Resumo do mapa operacional">
      <MapSummaryStat
        label={`Cobertura de coordenadas (${summary.mapped_projects}/${summary.visible_active_projects})`}
        value={`${summary.map_coverage_percent}%`}
        icon="mapPin"
        tone="info"
      />
      <MapSummaryStat
        label="Estado operacional limpo"
        value={`${summary.operational_clean_percent}%`}
        icon="checkCircle"
        tone="success"
      />
      <MapSummaryStat label="Em atenção" value={String(summary.yellow_projects)} icon="alert" tone="warning" />
      <MapSummaryStat label="Críticos" value={String(summary.red_projects)} icon="flame" tone="danger" />
    </div>
  );
}

// Contexto mínimo só para passar a config de tiles ao LeafletMap sem prop
// drilling excessivo — evita puxar uma dependência de estado global só
// para isto.
import { createContext, useContext } from "react";
const MapConfigContext = createContext<{ config: MapData["config"] }>({
  config: { provider_enabled: false, tile_url: "", tile_attribution: "" },
});
const useMapConfigContext = () => useContext(MapConfigContext);

export default function MapPage() {
  const { can } = useSession();
  const { notify } = useToast();
  const [data, setData] = useState<MapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<MapFilters>(EMPTY_MAP_FILTERS);
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    projects: true,
    suppliers: true,
    pickups: true,
    issues: true,
  });
  const [selected, setSelected] = useState<SelectedItem | null>(null);
  const [selectedForRoute, setSelectedForRoute] = useState<Set<string>>(new Set());
  const [routeRoundTrip, setRouteRoundTrip] = useState(false);
  const [optimizedRoute, setOptimizedRoute] = useState<RouteOptimization | null>(null);
  const [optimizingRoute, setOptimizingRoute] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [tripPlan, setTripPlan] = useState<TripPlan | null>(null);
  const [planningTrip, setPlanningTrip] = useState(false);

  // Uma rota otimizada só vale para a seleção e a opção com que foi calculada.
  useEffect(() => {
    setOptimizedRoute(null);
    setRouteError(null);
  }, [selectedForRoute, routeRoundTrip]);
  const [editingCoordinates, setEditingCoordinates] = useState<MapProject | null>(null);
  const [creatingTaskFor, setCreatingTaskFor] = useState<MapProject | null>(null);
  const [schedulingFor, setSchedulingFor] = useState<MapProject | null>(null);
  const [creatingSupplier, setCreatingSupplier] = useState(false);
  const [creatingPickup, setCreatingPickup] = useState(false);

  const canManageSuppliers = can("supplier.manage");
  const canManagePickups = can("pickup_point.manage");
  const canCreateTasks = can("task.edit_all") || can("task.edit_own");
  const canScheduleVisits = can("calendar.manage");

  function load() {
    setError(null);
    getMapData()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }

  useEffect(load, []);

  const filteredProjects = useMemo(
    () => (data ? filterMapProjects(data.projects, filters) : []),
    [data, filters]
  );

  const showMaterialFilter = useMemo(() => (data ? canFilterByMaterial(data.projects) : false), [data]);

  const pmOptions = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.projects.map((p) => p.pm_display_name).filter((x): x is string => Boolean(x))));
  }, [data]);

  const clientOptions = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.projects.map((p) => p.client_name).filter((x): x is string => Boolean(x)))).sort();
  }, [data]);

  const mapItems = useMemo(() => {
    if (!data) return [];
    const items: MapItem[] = [];
    if (layers.projects) {
      for (const p of filteredProjects) {
        if (p.lat !== null && p.lon !== null) {
          items.push({
            key: `p-${p.id}`,
            layer: "projects",
            lat: p.lat,
            lon: p.lon,
            title: `${p.name} — ${ATTENTION_LABELS[p.attention]}`,
            onClick: () => setSelected({ kind: "project", item: p }),
            color: ATTENTION_COLORS[p.attention],
            attention: p.attention,
          });
        }
      }
    }
    if (layers.suppliers) {
      for (const s of data.suppliers) {
        if (s.lat !== null && s.lon !== null) {
          items.push({ key: `s-${s.id}`, layer: "suppliers", lat: s.lat, lon: s.lon, title: s.name, onClick: () => setSelected({ kind: "supplier", item: s }) });
        }
      }
    }
    if (layers.pickups) {
      for (const pk of data.pickup_points) {
        if (pk.lat !== null && pk.lon !== null) {
          items.push({ key: `pk-${pk.id}`, layer: "pickups", lat: pk.lat, lon: pk.lon, title: pk.name, onClick: () => setSelected({ kind: "pickup", item: pk }) });
        }
      }
    }
    if (layers.issues) {
      for (const i of data.issues) {
        if (i.lat !== null && i.lon !== null) {
          items.push({ key: `i-${i.id}`, layer: "issues", lat: i.lat, lon: i.lon, title: i.description, onClick: () => setSelected({ kind: "issue", item: i }) });
        }
      }
    }
    return items;
  }, [data, filteredProjects, layers]);

  function toggleRouteSelection(key: string, lat: number | null, lon: number | null) {
    if (lat === null || lon === null) return;
    setSelectedForRoute((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleOptimizeRoute() {
    setOptimizingRoute(true);
    setRouteError(null);
    try {
      // A ordem de seleção é a ordem pedida; a primeira paragem é a partida.
      const stops = Array.from(selectedForRoute).map((key) => {
        const [kind, id] = key.split(":");
        return { kind: kind as RouteStopKind, id };
      });
      setOptimizedRoute(await optimizeRoute(stops, routeRoundTrip));
    } catch (err) {
      setRouteError(err instanceof ApiError ? err.detail : "Não foi possível otimizar a rota.");
    } finally {
      setOptimizingRoute(false);
    }
  }

  function openInMaps(coords: string[], roundTrip: boolean = routeRoundTrip) {
    // Com regresso, a rota fecha no ponto de partida.
    const all = roundTrip ? [...coords, coords[0]] : coords;
    const destination = all[all.length - 1];
    const waypoints = all.slice(0, -1).join("|");
    const url = `https://www.google.com/maps/dir/?api=1&destination=${destination}&waypoints=${encodeURIComponent(waypoints)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  async function handlePlanTrip() {
    setPlanningTrip(true);
    setRouteError(null);
    try {
      const stops = Array.from(selectedForRoute).map((key) => {
        const [kind, id] = key.split(":");
        return { kind: kind as RouteStopKind, id };
      });
      setTripPlan(await planTrip(stops, routeRoundTrip));
    } catch (err) {
      setRouteError(err instanceof ApiError ? err.detail : "Não foi possível planear a deslocação.");
    } finally {
      setPlanningTrip(false);
    }
  }

  function openExternalRoute() {
    const coords: string[] = [];
    if (optimizedRoute) {
      // Usa exatamente a ordem calculada pelo servidor.
      for (const stop of optimizedRoute.stops) coords.push(`${stop.lat},${stop.lon}`);
    }
    for (const key of optimizedRoute ? [] : selectedForRoute) {
      const [type, id] = key.split(":");
      if (type === "project") {
        const p = data?.projects.find((x) => x.id === id);
        if (p?.lat != null && p?.lon != null) coords.push(`${p.lat},${p.lon}`);
      } else if (type === "supplier") {
        const s = data?.suppliers.find((x) => x.id === id);
        if (s?.lat != null && s?.lon != null) coords.push(`${s.lat},${s.lon}`);
      } else if (type === "pickup") {
        const pk = data?.pickup_points.find((x) => x.id === id);
        if (pk?.lat != null && pk?.lon != null) coords.push(`${pk.lat},${pk.lon}`);
      }
    }
    if (coords.length < 2) {
      notify("Selecione pelo menos dois locais para abrir uma rota.", "error");
      return;
    }
    openInMaps(coords);
  }

  if (error) {
    return (
      <>
        <PageHeader title="Mapa" />
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      </>
    );
  }

  if (data === null) {
    return (
      <>
        <PageHeader title="Mapa" />
        <div className="card">
          <LoadingState rows={8} />
        </div>
      </>
    );
  }

  return (
    <MapConfigContext.Provider value={{ config: data.config }}>
      <PageHeader
        title="Mapa operacional"
        subtitle="Instalações, fornecedores, pontos de recolha e pendências."
        actions={
          <div style={{ display: "flex", gap: 8 }}>
            {canManageSuppliers && (
              <button type="button" className="btn btn--sm" onClick={() => setCreatingSupplier(true)}>
                <Icon name="plus" size={14} /> Fornecedor
              </button>
            )}
            {canManagePickups && (
              <button type="button" className="btn btn--sm" onClick={() => setCreatingPickup(true)}>
                <Icon name="plus" size={14} /> Ponto de recolha
              </button>
            )}
          </div>
        }
      />

      {!data.config.provider_enabled && (
        <Alert tone="info">
          Sem provider de mapa configurado (<code>MAP_TILE_URL</code>) — a mostrar a lista funcional dos locais em vez
          de um mapa visual. O resto da aplicação funciona normalmente sem esta configuração.
        </Alert>
      )}

      <div className="section-gap">
        <MapSummaryBar summary={data.summary} />
      </div>

      <form className="toolbar" role="search" aria-label="Filtros do mapa" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--wide">
          <label htmlFor="map-search">Pesquisar</label>
          <input id="map-search" className="input" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} placeholder="Projeto ou cliente…" />
        </div>
        <div className="field">
          <label htmlFor="map-pm">PM</label>
          <select id="map-pm" className="select" value={filters.pm} onChange={(e) => setFilters({ ...filters, pm: e.target.value })}>
            <option value="">Todos</option>
            {pmOptions.map((pm) => (
              <option key={pm} value={pm}>
                {pm}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="map-client">Cliente</label>
          <select id="map-client" className="select" value={filters.client} onChange={(e) => setFilters({ ...filters, client: e.target.value })}>
            <option value="">Todos</option>
            {clientOptions.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="map-status">Estado</label>
          <select id="map-status" className="select" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            <option value="">Todos</option>
            {Object.entries(PROJECT_STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="map-attention">Atenção</label>
          <select
            id="map-attention"
            className="select"
            value={filters.attention}
            onChange={(e) => setFilters({ ...filters, attention: e.target.value as MapFilters["attention"] })}
          >
            <option value="">Todas</option>
            <option value="red">Crítico</option>
            <option value="yellow">Atenção</option>
            <option value="green">Sem pendências operacionais</option>
          </select>
        </div>
        <div className="field">
          <span>Mostrar só</span>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <label className="checkbox small">
              <input
                type="checkbox"
                checked={filters.onlyWithPending}
                onChange={(e) => setFilters({ ...filters, onlyWithPending: e.target.checked })}
              />
              Com pendências
            </label>
            {showMaterialFilter && (
              <label className="checkbox small">
                <input
                  type="checkbox"
                  checked={filters.onlyWithMaterial}
                  onChange={(e) => setFilters({ ...filters, onlyWithMaterial: e.target.checked })}
                />
                Material no local
              </label>
            )}
          </div>
        </div>
        <div className="field">
          <span>Camadas</span>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {(Object.keys(layers) as LayerKey[]).map((key) => (
              <label key={key} className="checkbox small">
                <input
                  type="checkbox"
                  checked={layers[key]}
                  onChange={(e) => setLayers({ ...layers, [key]: e.target.checked })}
                />
                {key === "projects" ? "Instalações" : key === "suppliers" ? "Fornecedores" : key === "pickups" ? "Recolhas" : "Pendências"}
              </label>
            ))}
          </div>
        </div>
      </form>

      {data.config.provider_enabled && (
        <div className="section-gap">
          <LeafletMap items={mapItems} />
        </div>
      )}

      <div className="section-gap grid grid--main-side">
        <Card title={`Instalações (${filteredProjects.length})`} icon="folder" flush>
          {filteredProjects.length === 0 ? (
            <EmptyState compact icon="folder" title="Sem instalações a mostrar com estes filtros." />
          ) : (
            <ul className="list">
              {filteredProjects.map((p) => (
                <li key={p.id} className="list__item">
                  {p.lat !== null && (
                    <input
                      type="checkbox"
                      aria-label={`Selecionar ${p.name} para rota`}
                      checked={selectedForRoute.has(`project:${p.id}`)}
                      onChange={() => toggleRouteSelection(`project:${p.id}`, p.lat, p.lon)}
                    />
                  )}
                  <div className="list__main">
                    <button
                      type="button"
                      className="list__title"
                      style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
                      onClick={() => setSelected({ kind: "project", item: p })}
                    >
                      <AttentionDot attention={p.attention} />
                      {p.name}
                    </button>
                    <div className="list__meta">
                      {p.client_name ?? "sem cliente"} · PM: {p.pm_display_name ?? "sem PM"}
                      {p.issues_count > 0 && ` · ${p.issues_count} pendência(s)`}
                      {p.operational_tasks_count > 0 && ` · ${p.operational_tasks_count} tarefa(s) operacional(is)`}
                      {p.material_visible && p.has_material_on_site && " · material no local"}
                      {p.next_visit && ` · próxima visita ${formatDateTimePt(p.next_visit.starts_at)}`}
                    </div>
                  </div>
                  <Badge tone={PROJECT_STATUS_TONES[p.status as keyof typeof PROJECT_STATUS_TONES] ?? "neutral"}>
                    {PROJECT_STATUS_LABELS[p.status as keyof typeof PROJECT_STATUS_LABELS] ?? p.status}
                  </Badge>
                  <Badge tone={ATTENTION_TONES[p.attention]}>{ATTENTION_LABELS[p.attention]}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="grid">
          <Card title={`Sem coordenadas (${data.projects_without_coordinates.length})`} icon="mapPin" tone="warning" flush>
            {data.projects_without_coordinates.length === 0 ? (
              <EmptyState compact icon="mapPin" title="Todos os projetos visíveis têm coordenadas." />
            ) : (
              <ul className="list">
                {data.projects_without_coordinates.map((p) => (
                  <li key={p.id} className="list__item">
                    <span className="list__main">
                      <span className="list__title">{p.name}</span>
                    </span>
                    <button type="button" className="btn btn--sm" onClick={() => setEditingCoordinates(p)}>
                      Definir coordenadas
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Rota externa" icon="mapPin" tone="violet" flush>
            <div style={{ padding: 16 }}>
              <p className="small muted" style={{ marginTop: 0 }}>
                Selecione locais na lista (caixas de verificação). A <strong>primeira</strong> paragem selecionada é o
                ponto de partida. Pode abrir a rota num serviço externo pela ordem escolhida, ou otimizar a ordem primeiro.
              </p>
              <label className="checkbox small" style={{ marginBottom: 8 }}>
                <input type="checkbox" checked={routeRoundTrip} onChange={(e) => setRouteRoundTrip(e.target.checked)} />
                Voltar ao ponto de partida
              </label>
              {routeError && <Alert tone="danger">{routeError}</Alert>}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn btn--sm"
                  onClick={handleOptimizeRoute}
                  disabled={selectedForRoute.size < 2 || optimizingRoute}
                >
                  <Icon name="refresh" size={14} /> {optimizingRoute ? "A otimizar…" : "Otimizar ordem"}
                </button>
                <button
                  type="button"
                  className="btn btn--sm"
                  onClick={handlePlanTrip}
                  disabled={selectedForRoute.size < 2 || planningTrip}
                >
                  <Icon name="list" size={14} /> {planningTrip ? "A planear…" : "Planear deslocação"}
                </button>
                <button type="button" className="btn btn--sm" onClick={openExternalRoute} disabled={selectedForRoute.size < 2}>
                  <Icon name="mapPin" size={14} /> Abrir rota ({selectedForRoute.size})
                </button>
              </div>
              {optimizedRoute && (
                <div style={{ marginTop: 12 }} aria-label="Rota otimizada">
                  <p className="small" style={{ margin: "0 0 6px" }}>
                    <strong>{optimizedRoute.total_km} km</strong> em linha reta
                    {optimizedRoute.saved_km > 0
                      ? ` — menos ${optimizedRoute.saved_km} km do que a ordem escolhida (${optimizedRoute.requested_order_km} km).`
                      : " — a ordem escolhida já era a mais curta."}{" "}
                    {optimizedRoute.method === "exact" ? "Ordem ótima." : "Boa ordem, mas não garantidamente a ótima."}
                  </p>
                  <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
                    {optimizedRoute.stops.map((stop, index) => (
                      <li key={`${stop.kind}:${stop.id}`}>
                        {stop.name}
                        {index === 0 ? " (partida)" : ` — +${stop.leg_km} km`}
                      </li>
                    ))}
                    {optimizedRoute.return_leg_km !== null && <li>Regresso à partida — +{optimizedRoute.return_leg_km} km</li>}
                  </ol>
                  <p className="small muted" style={{ margin: "6px 0 0" }}>
                    Distâncias em linha reta (aproximação) — não são quilómetros de condução.
                  </p>
                </div>
              )}
            </div>
          </Card>

          <Card title={`Fornecedores (${data.suppliers.length})`} icon="folder" tone="info" flush>
            {data.suppliers.length === 0 ? (
              <EmptyState compact icon="folder" title="Sem fornecedores ativos." />
            ) : (
              <ul className="list">
                {data.suppliers.map((s) => (
                  <li key={s.id} className="list__item">
                    {s.lat !== null && (
                      <input
                        type="checkbox"
                        aria-label={`Selecionar ${s.name} para rota`}
                        checked={selectedForRoute.has(`supplier:${s.id}`)}
                        onChange={() => toggleRouteSelection(`supplier:${s.id}`, s.lat, s.lon)}
                      />
                    )}
                    <button type="button" className="list__main" style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer" }} onClick={() => setSelected({ kind: "supplier", item: s })}>
                      <span className="list__title">{s.name}</span>
                      <div className="list__meta">{s.category ?? "—"}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title={`Pontos de recolha (${data.pickup_points.length})`} icon="mapPin" tone="brand" flush>
            {data.pickup_points.length === 0 ? (
              <EmptyState compact icon="mapPin" title="Sem pontos de recolha ativos." />
            ) : (
              <ul className="list">
                {data.pickup_points.map((pk) => (
                  <li key={pk.id} className="list__item">
                    {pk.lat !== null && (
                      <input
                        type="checkbox"
                        aria-label={`Selecionar ${pk.name} para rota`}
                        checked={selectedForRoute.has(`pickup:${pk.id}`)}
                        onChange={() => toggleRouteSelection(`pickup:${pk.id}`, pk.lat, pk.lon)}
                      />
                    )}
                    <button type="button" className="list__main" style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer" }} onClick={() => setSelected({ kind: "pickup", item: pk })}>
                      <span className="list__title">{pk.name}</span>
                      <div className="list__meta">{pk.address ?? "—"}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title={`Pendências (${data.issues.length})`} icon="alert" tone="danger" flush>
            {data.issues.length === 0 ? (
              <EmptyState compact icon="alert" title="Sem pendências visíveis no mapa." />
            ) : (
              <ul className="list">
                {data.issues.map((i) => (
                  <li key={i.id} className="list__item">
                    <button type="button" className="list__main" style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer" }} onClick={() => setSelected({ kind: "issue", item: i })}>
                      <span className="list__title">{i.description}</span>
                      <div className="list__meta">{i.project_name}</div>
                    </button>
                    <Badge tone={i.status === "resolvida" ? "success" : "warning"}>{i.status}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {selected && (
        <Modal
          title="Detalhe"
          onClose={() => setSelected(null)}
          footer={
            selected.kind === "project" && (canCreateTasks || canScheduleVisits) ? (
              <>
                {canScheduleVisits && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setSchedulingFor(selected.item);
                      setSelected(null);
                    }}
                  >
                    <Icon name="calendar" size={14} /> Agendar visita
                  </button>
                )}
                {canCreateTasks && (
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() => {
                      setCreatingTaskFor(selected.item);
                      setSelected(null);
                    }}
                  >
                    <Icon name="plus" size={14} /> Criar tarefa
                  </button>
                )}
              </>
            ) : undefined
          }
        >
          {selected.kind === "project" && (
            <dl className="kv">
              <dt>Nome</dt>
              <dd>
                <Link to={`/projects/${selected.item.id}`}>{selected.item.name}</Link>
              </dd>
              <dt>Cliente</dt>
              <dd>{selected.item.client_name ?? "—"}</dd>
              <dt>PM</dt>
              <dd>{selected.item.pm_display_name ?? "—"}</dd>
              <dt>Estado</dt>
              <dd>{PROJECT_STATUS_LABELS[selected.item.status as keyof typeof PROJECT_STATUS_LABELS] ?? selected.item.status}</dd>
              <dt>Potência</dt>
              <dd>{selected.item.power_kwp ?? "—"} kWp</dd>
              <dt>Atenção</dt>
              <dd>
                <Badge tone={ATTENTION_TONES[selected.item.attention]}>{ATTENTION_LABELS[selected.item.attention]}</Badge>
              </dd>
              <dt>Tarefas operacionais abertas</dt>
              <dd>
                {selected.item.operational_tasks_count}
                {selected.item.overdue_operational_tasks_count > 0 && ` (${selected.item.overdue_operational_tasks_count} atrasada(s))`}
                {selected.item.blocked_operational_tasks_count > 0 && ` · ${selected.item.blocked_operational_tasks_count} bloqueada(s)`}
                {selected.item.urgent_operational_tasks_count > 0 && ` · ${selected.item.urgent_operational_tasks_count} urgente(s)`}
              </dd>
              {selected.item.next_operational_task && (
                <>
                  <dt>Próxima ação</dt>
                  <dd>
                    {selected.item.next_operational_task.title}
                    {selected.item.next_operational_task.due_date &&
                      ` — ${formatDatePt(selected.item.next_operational_task.due_date)}`}
                  </dd>
                </>
              )}
              <dt>Material</dt>
              <dd>
                {selected.item.material_visible
                  ? selected.item.has_material_on_site
                    ? `Sim (${selected.item.material_sku_count} item(ns))`
                    : "Não"
                  : "Sem permissão para ver inventário"}
              </dd>
              <dt>Próxima visita</dt>
              <dd>
                {!selected.item.visits_visible
                  ? "Sem permissão para ver o calendário"
                  : selected.item.next_visit
                    ? `${selected.item.next_visit.title} — ${formatDateTimePt(selected.item.next_visit.starts_at)}${
                        selected.item.next_visit.assigned_to_display_name
                          ? ` (${selected.item.next_visit.assigned_to_display_name})`
                          : ""
                      } · ${selected.item.upcoming_visits_count} agendada(s)`
                    : "Nenhuma agendada"}
              </dd>
              <dt>Tarefas abertas (total)</dt>
              <dd>{selected.item.open_tasks_count}</dd>
              <dt>Pendências</dt>
              <dd>{selected.item.issues_count}</dd>
            </dl>
          )}
          {selected.kind === "supplier" && (
            <dl className="kv">
              <dt>Nome</dt>
              <dd>{selected.item.name}</dd>
              <dt>Categoria</dt>
              <dd>{selected.item.category ?? "—"}</dd>
              <dt>Contacto</dt>
              <dd>{selected.item.contact ?? "—"}</dd>
              <dt>Morada</dt>
              <dd>{selected.item.address ?? "—"}</dd>
              <dt>Materiais</dt>
              <dd style={{ whiteSpace: "pre-wrap" }}>{selected.item.materials || "—"}</dd>
            </dl>
          )}
          {selected.kind === "pickup" && (
            <dl className="kv">
              <dt>Nome</dt>
              <dd>{selected.item.name}</dd>
              <dt>Morada</dt>
              <dd>{selected.item.address ?? "—"}</dd>
              <dt>Horário</dt>
              <dd>{selected.item.schedule ?? "—"}</dd>
              <dt>Materiais</dt>
              <dd style={{ whiteSpace: "pre-wrap" }}>{selected.item.materials || "—"}</dd>
            </dl>
          )}
          {selected.kind === "issue" && (
            <dl className="kv">
              <dt>Descrição</dt>
              <dd>{selected.item.description}</dd>
              <dt>Projeto</dt>
              <dd>
                <Link to={`/projects/${selected.item.project_id}`}>{selected.item.project_name}</Link>
              </dd>
              <dt>Categoria</dt>
              <dd>{selected.item.category}</dd>
              <dt>Prioridade</dt>
              <dd>{selected.item.priority}</dd>
              <dt>Estado</dt>
              <dd>{selected.item.status}</dd>
            </dl>
          )}
        </Modal>
      )}

      {editingCoordinates && (
        <EditCoordinatesModal
          project={editingCoordinates}
          onClose={() => setEditingCoordinates(null)}
          onSaved={() => {
            setEditingCoordinates(null);
            notify("Coordenadas atualizadas.", "success");
            load();
          }}
        />
      )}

      {creatingTaskFor && (
        <CreateTaskModal
          project={creatingTaskFor}
          onClose={() => setCreatingTaskFor(null)}
          onDone={() => {
            setCreatingTaskFor(null);
            notify("Tarefa criada.", "success");
            load(); // o attention do projeto pode ter mudado
          }}
        />
      )}

      {tripPlan && (
        <TripPlanModal
          plan={tripPlan}
          onClose={() => setTripPlan(null)}
          onOpenRoute={() => openInMaps(tripPlan.stops.map((stop) => `${stop.lat},${stop.lon}`), tripPlan.round_trip)}
          onCopied={(ok) => notify(ok ? "Resumo copiado." : "Não foi possível copiar o resumo.", ok ? "success" : "error")}
        />
      )}

      {schedulingFor && (
        <ScheduleVisitModal
          project={schedulingFor}
          onClose={() => setSchedulingFor(null)}
          onDone={() => {
            setSchedulingFor(null);
            notify("Visita agendada.", "success");
            load(); // a próxima visita do projeto pode ter mudado
          }}
        />
      )}

      {creatingSupplier && (
        <CreateSupplierModal
          onClose={() => setCreatingSupplier(false)}
          onDone={() => {
            setCreatingSupplier(false);
            notify("Fornecedor criado.", "success");
            load();
          }}
        />
      )}

      {creatingPickup && (
        <CreatePickupPointModal
          suppliers={data.suppliers}
          onClose={() => setCreatingPickup(false)}
          onDone={() => {
            setCreatingPickup(false);
            notify("Ponto de recolha criado.", "success");
            load();
          }}
        />
      )}
    </MapConfigContext.Provider>
  );
}
