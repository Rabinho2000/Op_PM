// Mapa operacional: instalações, fornecedores, pontos de recolha e
// pendências. Sem provider de tiles configurado (MAP_TILE_URL), mostra
// sempre a lista funcional dos locais em vez de deixar a página quebrada
// — nunca depende de um serviço externo para o resto da app funcionar
// (ver docs/MAP_AND_PLANNING.md). Sem otimização automática de rotas, por
// pedido explícito — só seleção manual + link para uma rota externa.
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  createPickupPoint,
  createSupplier,
  getMapData,
  MapData,
  MapPickupPoint,
  MapProject,
  MapSupplier,
  ProjectIssue,
  updateProject,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { PROJECT_STATUS_LABELS } from "../api/client";
import { PROJECT_STATUS_TONES } from "../utils/labels";

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

function LeafletMap({
  items,
}: {
  items: { key: string; layer: LayerKey; lat: number; lon: number; title: string; onClick: () => void }[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersRef = useRef<L.Marker[]>([]);
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
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    const bounds: L.LatLngExpression[] = [];
    for (const item of items) {
      const marker = L.marker([item.lat, item.lon], { icon: makeDivIcon(MARKER_COLORS[item.layer]) })
        .addTo(map)
        .bindTooltip(item.title)
        .on("click", item.onClick);
      markersRef.current.push(marker);
      bounds.push([item.lat, item.lon]);
    }
    if (bounds.length > 0) {
      map.fitBounds(bounds as L.LatLngBoundsExpression, { padding: [30, 30], maxZoom: 14 });
    }
  }, [items]);

  return <div ref={containerRef} style={{ height: 480, borderRadius: 12, overflow: "hidden" }} />;
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
  const [search, setSearch] = useState("");
  const [pmFilter, setPmFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    projects: true,
    suppliers: true,
    pickups: true,
    issues: true,
  });
  const [selected, setSelected] = useState<SelectedItem | null>(null);
  const [selectedForRoute, setSelectedForRoute] = useState<Set<string>>(new Set());
  const [editingCoordinates, setEditingCoordinates] = useState<MapProject | null>(null);
  const [creatingSupplier, setCreatingSupplier] = useState(false);
  const [creatingPickup, setCreatingPickup] = useState(false);

  const canManageSuppliers = can("supplier.manage");
  const canManagePickups = can("pickup_point.manage");

  function load() {
    setError(null);
    getMapData()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }

  useEffect(load, []);

  const filteredProjects = useMemo(() => {
    if (!data) return [];
    const term = search.trim().toLowerCase();
    return data.projects.filter((p) => {
      if (term && !p.name.toLowerCase().includes(term) && !(p.client_name ?? "").toLowerCase().includes(term)) return false;
      if (pmFilter && p.pm_display_name !== pmFilter) return false;
      if (statusFilter && p.status !== statusFilter) return false;
      return true;
    });
  }, [data, search, pmFilter, statusFilter]);

  const pmOptions = useMemo(() => {
    if (!data) return [];
    return Array.from(new Set(data.projects.map((p) => p.pm_display_name).filter((x): x is string => Boolean(x))));
  }, [data]);

  const mapItems = useMemo(() => {
    if (!data) return [];
    const items: { key: string; layer: LayerKey; lat: number; lon: number; title: string; onClick: () => void }[] = [];
    if (layers.projects) {
      for (const p of filteredProjects) {
        if (p.lat !== null && p.lon !== null) {
          items.push({ key: `p-${p.id}`, layer: "projects", lat: p.lat, lon: p.lon, title: p.name, onClick: () => setSelected({ kind: "project", item: p }) });
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

  function openExternalRoute() {
    const coords: string[] = [];
    for (const key of selectedForRoute) {
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
    const destination = coords[coords.length - 1];
    const waypoints = coords.slice(0, -1).join("|");
    const url = `https://www.google.com/maps/dir/?api=1&destination=${destination}&waypoints=${encodeURIComponent(waypoints)}`;
    window.open(url, "_blank", "noopener,noreferrer");
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

      <form className="toolbar" role="search" aria-label="Filtros do mapa" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--wide">
          <label htmlFor="map-search">Pesquisar</label>
          <input id="map-search" className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Projeto ou cliente…" />
        </div>
        <div className="field">
          <label htmlFor="map-pm">PM</label>
          <select id="map-pm" className="select" value={pmFilter} onChange={(e) => setPmFilter(e.target.value)}>
            <option value="">Todos</option>
            {pmOptions.map((pm) => (
              <option key={pm} value={pm}>
                {pm}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="map-status">Estado</label>
          <select id="map-status" className="select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">Todos</option>
            {Object.entries(PROJECT_STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
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
                    <button type="button" className="list__title" style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer" }} onClick={() => setSelected({ kind: "project", item: p })}>
                      {p.name}
                    </button>
                    <div className="list__meta">
                      {p.client_name ?? "sem cliente"} · PM: {p.pm_display_name ?? "sem PM"}
                      {p.issues_count > 0 && ` · ${p.issues_count} pendência(s)`}
                    </div>
                  </div>
                  <Badge tone={PROJECT_STATUS_TONES[p.status as keyof typeof PROJECT_STATUS_TONES] ?? "neutral"}>
                    {PROJECT_STATUS_LABELS[p.status as keyof typeof PROJECT_STATUS_LABELS] ?? p.status}
                  </Badge>
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
                Selecione locais na lista (caixas de verificação) e abra a rota num serviço externo. Sem otimização
                automática — a ordem escolhida é a ordem de seleção.
              </p>
              <button type="button" className="btn btn--sm" onClick={openExternalRoute} disabled={selectedForRoute.size < 2}>
                <Icon name="mapPin" size={14} /> Abrir rota ({selectedForRoute.size})
              </button>
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
        <Modal title="Detalhe" onClose={() => setSelected(null)}>
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
              <dt>Tarefas abertas</dt>
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
