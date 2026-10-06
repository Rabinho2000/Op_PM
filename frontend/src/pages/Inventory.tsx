// Inventário central e catálogo — os saldos vêm sempre do livro de movimentos da API.
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  createCentralMovement,
  createInventoryItem,
  createInventoryLocation,
  createOpeningStock,
  deactivateInventoryItem,
  deactivateInventoryLocation,
  InventoryItem,
  InventoryLocation,
  InventoryMovement,
  listInventoryItems,
  listInventoryLocations,
  listInventoryMovements,
  reactivateInventoryItem,
  updateInventoryItem,
  updateInventoryLocation,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";

const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  entrada: "Entrada",
  saida: "Saída",
  reserva: "Reserva",
  liberta_reserva: "Libertação de reserva",
  consumo: "Consumo",
  devolucao: "Devolução",
  ajuste: "Ajuste",
  transito_entrada: "Trânsito (entrada)",
  transito_saida: "Trânsito (saída)",
};

const LOCATION_TYPE_LABELS: Record<string, string> = {
  central: "Central",
  project: "Projeto",
  vehicle: "Viatura",
  supplier: "Fornecedor",
  office: "Escritório",
};

type LocationType = "central" | "project" | "vehicle" | "supplier" | "office";

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.detail : fallback;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `opening-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function RegisterMovementModal({
  items,
  onClose,
  onDone,
}: {
  items: InventoryItem[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [itemId, setItemId] = useState(items[0]?.id ?? "");
  const [movementType, setMovementType] = useState<"entrada" | "ajuste">("entrada");
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!itemId || !quantity) {
      setError("Indique o artigo e a quantidade.");
      return;
    }
    setSaving(true);
    try {
      await createCentralMovement({ item_id: itemId, movement_type: movementType, quantity, reference });
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Não foi possível registar o movimento."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Registar movimento no stock central"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="movement-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A registar…" : "Registar"}
          </button>
        </>
      }
    >
      <form id="movement-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="m-item">Artigo</label>
          <select id="m-item" className="select" value={itemId} onChange={(e) => setItemId(e.target.value)}>
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.sku}) — {item.unit}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="m-type">Tipo</label>
          <select
            id="m-type"
            className="select"
            value={movementType}
            onChange={(e) => setMovementType(e.target.value as "entrada" | "ajuste")}
          >
            <option value="entrada">Entrada</option>
            <option value="ajuste">Ajuste (+/-)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="m-qty">Quantidade {movementType === "ajuste" && "(negativa para quebra/perda)"}</label>
          <input
            id="m-qty"
            className="input"
            type="number"
            step="0.001"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="m-ref">Referência</label>
          <input id="m-ref" className="input" value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

const SUGGESTED_CATEGORIES = [
  "Inversores",
  "Painéis",
  "Cabo DC",
  "Cabo AC",
  "Contadores de produção",
  "Meters",
  "Estrutura",
  "Comunicação",
];

function ItemFormModal({
  item,
  onClose,
  onSaved,
}: {
  item: InventoryItem | null;
  onClose: () => void;
  onSaved: (saved: InventoryItem, created: boolean) => void;
}) {
  const [sku, setSku] = useState(item?.sku ?? "");
  const [name, setName] = useState(item?.name ?? "");
  const [unit, setUnit] = useState(item?.unit ?? "un");
  const [category, setCategory] = useState(item?.category ?? "");
  const [minStock, setMinStock] = useState(item?.min_stock ?? "0");
  const [leadTime, setLeadTime] = useState(item?.lead_time_days === null || item?.lead_time_days === undefined ? "" : String(item.lead_time_days));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!sku.trim() || !name.trim() || !unit.trim() || !minStock.trim()) {
      setError("Preencha SKU, nome, unidade e stock mínimo.");
      return;
    }
    if (leadTime.trim() && (!Number.isInteger(Number(leadTime)) || Number(leadTime) < 0)) {
      setError("O prazo de fornecimento tem de ser um número inteiro não negativo.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        sku: sku.trim(),
        name: name.trim(),
        unit: unit.trim(),
        category: category.trim() || null,
        min_stock: minStock.trim(),
        lead_time_days: leadTime.trim() ? Number(leadTime) : null,
      };
      const saved = item ? await updateInventoryItem(item.id, payload) : await createInventoryItem(payload);
      onSaved(saved, item === null);
    } catch (err) {
      setError(apiErrorMessage(err, "Não foi possível guardar o artigo."));
    } finally {
      setSaving(false);
    }
  }

  const editing = item !== null;
  return (
    <Modal
      title={editing ? "Editar artigo" : "Criar artigo"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="item-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : editing ? "Guardar alterações" : "Criar artigo"}
          </button>
        </>
      }
    >
      <form id="item-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field">
          <label htmlFor="item-sku">SKU</label>
          <input id="item-sku" className="input" value={sku} onChange={(e) => setSku(e.target.value)} maxLength={64} autoComplete="off" />
        </div>
        <div className="field">
          <label htmlFor="item-unit">Unidade</label>
          <input id="item-unit" className="input" value={unit} onChange={(e) => setUnit(e.target.value)} maxLength={16} />
        </div>
        <div className="field">
          <label htmlFor="item-category">Categoria</label>
          <input
            id="item-category"
            className="input"
            list="item-category-suggestions"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            maxLength={64}
            placeholder="Escolha ou escreva uma categoria nova"
          />
          <datalist id="item-category-suggestions">
            {SUGGESTED_CATEGORIES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>
        <div className="field span-2">
          <label htmlFor="item-name">Nome</label>
          <input id="item-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={256} />
        </div>
        <div className="field">
          <label htmlFor="item-min-stock">Stock mínimo</label>
          <input id="item-min-stock" className="input" type="number" min="0" step="0.001" value={minStock} onChange={(e) => setMinStock(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="item-lead-time">Prazo de fornecimento (dias)</label>
          <input id="item-lead-time" className="input" type="number" min="0" step="1" value={leadTime} onChange={(e) => setLeadTime(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

function OpeningStockModal({ item, onClose, onDone }: { item: InventoryItem; onClose: () => void; onDone: () => void }) {
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [idempotencyKey] = useState(newIdempotencyKey);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!quantity || Number(quantity) <= 0 || !reference.trim()) {
      setError("Indique uma quantidade positiva e uma referência.");
      return;
    }
    setSaving(true);
    try {
      await createOpeningStock({
        item_id: item.id,
        quantity: quantity.trim(),
        reference: reference.trim(),
        idempotency_key: idempotencyKey,
      });
      onDone();
    } catch (err) {
      setError(apiErrorMessage(err, "Não foi possível registar o stock inicial."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Stock inicial — ${item.name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="opening-stock-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A registar…" : "Registar entrada"}
          </button>
        </>
      }
    >
      <form id="opening-stock-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="span-2">
          <Alert tone="info">A entrada é append-only, fica ligada à localização central e é protegida por uma chave de idempotência.</Alert>
        </div>
        <div className="field">
          <label htmlFor="opening-quantity">Quantidade</label>
          <input id="opening-quantity" className="input" type="number" min="0.001" step="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="opening-reference">Referência</label>
          <input id="opening-reference" className="input" value={reference} onChange={(e) => setReference(e.target.value)} maxLength={256} />
        </div>
      </form>
    </Modal>
  );
}

function LocationFormModal({
  location,
  centralOnly,
  onClose,
  onSaved,
}: {
  location: InventoryLocation | null;
  centralOnly: boolean;
  onClose: () => void;
  onSaved: (saved: InventoryLocation, created: boolean) => void;
}) {
  const initialType = (location?.location_type ?? (centralOnly ? "central" : "vehicle")) as LocationType;
  const [code, setCode] = useState(location?.code ?? "");
  const [name, setName] = useState(location?.name ?? "");
  const [locationType, setLocationType] = useState<LocationType>(initialType);
  const [projectId, setProjectId] = useState(location?.project_id ?? "");
  const [isActive, setIsActive] = useState(location?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const editing = location !== null;
  const fixedCentral = centralOnly || location?.location_type === "central";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!code.trim() || !name.trim()) {
      setError("Preencha código e nome.");
      return;
    }
    if (locationType === "project" && !projectId.trim()) {
      setError("Indique o identificador do projeto.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        code: code.trim(),
        name: name.trim(),
        location_type: locationType,
        project_id: locationType === "project" ? projectId.trim() : null,
        ...(editing ? { is_active: isActive } : {}),
      };
      const saved = location ? await updateInventoryLocation(location.id, payload) : await createInventoryLocation(payload);
      onSaved(saved, !editing);
    } catch (err) {
      setError(apiErrorMessage(err, "Não foi possível guardar a localização."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={editing ? "Editar localização" : centralOnly ? "Criar localização central" : "Criar localização"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="location-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : editing ? "Guardar alterações" : "Criar localização"}
          </button>
        </>
      }
    >
      <form id="location-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field">
          <label htmlFor="location-code">Código</label>
          <input id="location-code" className="input" value={code} onChange={(e) => setCode(e.target.value)} maxLength={64} autoComplete="off" />
        </div>
        <div className="field">
          <label htmlFor="location-type">Tipo</label>
          <select
            id="location-type"
            className="select"
            value={locationType}
            disabled={fixedCentral}
            onChange={(e) => setLocationType(e.target.value as LocationType)}
          >
            <option value="central">Central</option>
            <option value="vehicle">Viatura</option>
            <option value="supplier">Fornecedor</option>
            <option value="project">Projeto</option>
            <option value="office">Escritório</option>
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor="location-name">Nome</label>
          <input id="location-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={256} />
        </div>
        {locationType === "project" && (
          <div className="field span-2">
            <label htmlFor="location-project">ID do projeto</label>
            <input id="location-project" className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
            <span className="field__hint">O projeto tem de existir e estar ativo.</span>
          </div>
        )}
        {editing && (
          <label className="field span-2" style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} disabled={locationType === "central" && location?.is_active === true} />
            Localização ativa
          </label>
        )}
        {locationType === "central" && (
          <div className="span-2">
            <Alert tone="info">A aplicação mantém exatamente uma localização central ativa. Esta localização não pode ser desativada enquanto for a central utilizável.</Alert>
          </div>
        )}
      </form>
    </Modal>
  );
}

function ConfirmDeactivateModal({
  label,
  onClose,
  onConfirm,
}: {
  label: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function confirm() {
    setError(null);
    setSaving(true);
    try {
      await onConfirm();
    } catch (err) {
      setError(apiErrorMessage(err, "Não foi possível desativar o registo."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Confirmar desativação"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="button" className="btn btn--danger" onClick={confirm} disabled={saving}>
            {saving ? "A desativar…" : "Desativar"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <p>Desativar «{label}» impede novas referências e movimentos. O histórico existente permanece disponível.</p>
    </Modal>
  );
}

export default function Inventory() {
  const { can } = useSession();
  const { notify } = useToast();
  const [items, setItems] = useState<InventoryItem[] | null>(null);
  const [locations, setLocations] = useState<InventoryLocation[] | null>(null);
  const [movements, setMovements] = useState<InventoryMovement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [creatingItem, setCreatingItem] = useState(false);
  const [editingItem, setEditingItem] = useState<InventoryItem | null>(null);
  const [openingStockItem, setOpeningStockItem] = useState<InventoryItem | null>(null);
  const [deactivatingItem, setDeactivatingItem] = useState<InventoryItem | null>(null);
  const [locationForm, setLocationForm] = useState<{ location: InventoryLocation | null; centralOnly: boolean } | null>(null);
  const [deactivatingLocation, setDeactivatingLocation] = useState<InventoryLocation | null>(null);

  const canManageCentral = can("inventory.manage_central");
  const canManageCatalog = can("inventory.manage_catalog");
  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);
  const centralLocation = useMemo(
    () => (locations ?? []).find((location) => location.location_type === "central" && location.is_active),
    [locations],
  );

  const load = useCallback(() => {
    setError(null);
    setItems(null);
    setLocations(null);
    setMovements(null);
    Promise.all([listInventoryItems(), listInventoryLocations(), listInventoryMovements()])
      .then(([loadedItems, loadedLocations, loadedMovements]) => {
        setItems(loadedItems);
        setLocations(loadedLocations);
        setMovements(loadedMovements);
      })
      .catch((err) => setError(apiErrorMessage(err, "Não foi possível contactar o servidor.")));
  }, []);

  useEffect(load, [load]);

  async function reactivateItem(item: InventoryItem) {
    try {
      const saved = await reactivateInventoryItem(item.id);
      notify(`Artigo «${saved.name}» reativado.`, "success");
      load();
    } catch (err) {
      notify(apiErrorMessage(err, "Não foi possível reativar o artigo."), "error");
    }
  }

  if (error) {
    return (
      <>
        <PageHeader title="Inventário" />
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Inventário"
        subtitle="Catálogo e stock central, calculados a partir do livro append-only de movimentos."
        actions={
          <>
            {canManageCatalog && (
              <button type="button" className="btn" onClick={() => setCreatingItem(true)}>
                <Icon name="plus" size={16} /> Criar artigo
              </button>
            )}
            {canManageCentral && (
              <button type="button" className="btn btn--primary" onClick={() => setRegistering(true)} disabled={!activeItems.length}>
                <Icon name="plus" size={16} /> Registar movimento
              </button>
            )}
          </>
        }
      />

      <Card title="Artigos de inventário" icon="database" flush>
        {items === null ? (
          <LoadingState rows={4} />
        ) : items.length === 0 ? (
          <EmptyState
            icon="database"
            title="Sem artigos de inventário ainda."
            text={canManageCatalog ? "Crie o primeiro artigo para poder registar stock inicial." : "Um utilizador autorizado pode criar o catálogo."}
            action={
              canManageCatalog ? (
                <button type="button" className="btn btn--primary" onClick={() => setCreatingItem(true)}>
                  <Icon name="plus" size={16} /> Criar artigo
                </button>
              ) : undefined
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Stock central por artigo</caption>
              <thead>
                <tr>
                  <th scope="col">Artigo</th>
                  <th scope="col">SKU</th>
                  <th scope="col">Categoria</th>
                  <th scope="col">Físico</th>
                  <th scope="col">Reservado</th>
                  <th scope="col">Disponível</th>
                  <th scope="col">Mínimo</th>
                  <th scope="col">Estado</th>
                  {(canManageCatalog || canManageCentral) && <th scope="col">Ações</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span className="cell-title">{item.name}</span>
                      {!item.is_active && <span className="cell-sub">Inativo</span>}
                    </td>
                    <td className="nowrap muted">{item.sku}</td>
                    <td className="nowrap muted">{item.category ?? "—"}</td>
                    <td className="nowrap">{item.physical_stock} {item.unit}</td>
                    <td className="nowrap">{item.total_reserved} {item.unit}</td>
                    <td className="nowrap">{item.available_stock} {item.unit}</td>
                    <td className="nowrap muted">{item.min_stock} {item.unit}</td>
                    <td>
                      {!item.is_active ? (
                        <Badge tone="neutral">Inativo</Badge>
                      ) : item.below_min_stock ? (
                        <Badge tone="danger" dot>Abaixo do mínimo</Badge>
                      ) : (
                        <Badge tone="success" dot>OK</Badge>
                      )}
                    </td>
                    {(canManageCatalog || canManageCentral) && (
                      <td>
                        <div className="cluster">
                          {canManageCatalog && (
                            <>
                              <button type="button" className="btn btn--sm" onClick={() => setEditingItem(item)} aria-label={`Editar ${item.name}`}>
                                Editar
                              </button>
                              {item.is_active ? (
                                <button type="button" className="btn btn--sm btn--ghost" onClick={() => setDeactivatingItem(item)}>
                                  Desativar
                                </button>
                              ) : (
                                <button type="button" className="btn btn--sm btn--ghost" onClick={() => void reactivateItem(item)}>
                                  Reativar
                                </button>
                              )}
                            </>
                          )}
                          {canManageCentral && item.is_active && (
                            <button type="button" className="btn btn--sm btn--ghost" onClick={() => setOpeningStockItem(item)}>
                              Stock inicial
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="section-gap">
        <Card
          title="Localizações"
          icon="mapPin"
          flush
          actions={
            canManageCatalog && (
              <button type="button" className="btn btn--sm" onClick={() => setLocationForm({ location: null, centralOnly: false })}>
                <Icon name="plus" size={14} /> Nova localização
              </button>
            )
          }
        >
          {locations === null ? (
            <LoadingState label="A carregar localizações…" rows={3} />
          ) : locations.length === 0 ? (
            <EmptyState
              icon="mapPin"
              title="Nenhuma localização registada"
              text={canManageCatalog ? "Crie a localização central antes de registar stock." : "Ainda não existe uma localização disponível."}
              action={
                canManageCatalog ? (
                  <button type="button" className="btn btn--primary" onClick={() => setLocationForm({ location: null, centralOnly: true })}>
                    <Icon name="plus" size={16} /> Criar localização central
                  </button>
                ) : undefined
              }
            />
          ) : (
            <>
              {!centralLocation && (
                <div style={{ padding: 16 }}>
                  <Alert
                    tone="danger"
                    action={canManageCatalog ? <button type="button" className="btn btn--sm" onClick={() => setLocationForm({ location: null, centralOnly: true })}>Criar central</button> : undefined}
                  >
                    Não existe exatamente uma localização central ativa. O stock inicial fica bloqueado até esta situação ser corrigida.
                  </Alert>
                </div>
              )}
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Localizações de inventário</caption>
                  <thead>
                    <tr>
                      <th scope="col">Localização</th>
                      <th scope="col">Código</th>
                      <th scope="col">Tipo</th>
                      <th scope="col">Estado</th>
                      {canManageCatalog && <th scope="col">Ações</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {locations.map((location) => (
                      <tr key={location.id}>
                        <td>{location.name}</td>
                        <td className="nowrap muted">{location.code}</td>
                        <td>{LOCATION_TYPE_LABELS[location.location_type] ?? location.location_type}</td>
                        <td>{location.is_active ? <Badge tone="success">Ativa</Badge> : <Badge>Inativa</Badge>}</td>
                        {canManageCatalog && (
                          <td>
                            <div className="cluster">
                              <button type="button" className="btn btn--sm" onClick={() => setLocationForm({ location, centralOnly: location.location_type === "central" })}>
                                Editar
                              </button>
                              {location.is_active && location.location_type !== "central" && (
                                <button type="button" className="btn btn--sm btn--ghost" onClick={() => setDeactivatingLocation(location)}>
                                  Desativar
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      </div>

      <div className="section-gap">
        <Card title="Movimentos recentes" icon="history" flush>
          {movements === null ? (
            <LoadingState rows={4} />
          ) : movements.length === 0 ? (
            <EmptyState icon="history" title="Sem movimentos registados ainda." />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Movimentos de inventário recentes</caption>
                <thead>
                  <tr>
                    <th scope="col">Data</th>
                    <th scope="col">Artigo</th>
                    <th scope="col">Tipo</th>
                    <th scope="col">Quantidade</th>
                    <th scope="col">Projeto</th>
                    <th scope="col">Referência</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.slice(0, 30).map((movement) => (
                    <tr key={movement.id}>
                      <td className="nowrap muted">{new Date(movement.created_at).toLocaleString("pt-PT")}</td>
                      <td>{movement.item_name ?? "—"}</td>
                      <td><Badge tone="neutral">{MOVEMENT_TYPE_LABELS[movement.movement_type] ?? movement.movement_type}</Badge></td>
                      <td className="nowrap">{movement.quantity}</td>
                      <td>{movement.project_name ?? <span className="muted">—</span>}</td>
                      <td>{movement.reference || <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {creatingItem && (
        <ItemFormModal
          item={null}
          onClose={() => setCreatingItem(false)}
          onSaved={(saved) => {
            setCreatingItem(false);
            notify(`Artigo «${saved.name}» criado.`, "success");
            load();
          }}
        />
      )}
      {editingItem && (
        <ItemFormModal
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSaved={(saved) => {
            setEditingItem(null);
            notify(`Artigo «${saved.name}» atualizado.`, "success");
            load();
          }}
        />
      )}
      {openingStockItem && (
        <OpeningStockModal
          item={openingStockItem}
          onClose={() => setOpeningStockItem(null)}
          onDone={() => {
            setOpeningStockItem(null);
            notify("Stock inicial registado.", "success");
            load();
          }}
        />
      )}
      {registering && activeItems.length > 0 && (
        <RegisterMovementModal
          items={activeItems}
          onClose={() => setRegistering(false)}
          onDone={() => {
            setRegistering(false);
            notify("Movimento registado.", "success");
            load();
          }}
        />
      )}
      {deactivatingItem && (
        <ConfirmDeactivateModal
          label={deactivatingItem.name}
          onClose={() => setDeactivatingItem(null)}
          onConfirm={async () => {
            await deactivateInventoryItem(deactivatingItem.id);
            setDeactivatingItem(null);
            notify("Artigo desativado.", "success");
            load();
          }}
        />
      )}
      {locationForm && (
        <LocationFormModal
          location={locationForm.location}
          centralOnly={locationForm.centralOnly}
          onClose={() => setLocationForm(null)}
          onSaved={(saved, created) => {
            setLocationForm(null);
            notify(created ? `Localização «${saved.name}» criada.` : `Localização «${saved.name}» atualizada.`, "success");
            load();
          }}
        />
      )}
      {deactivatingLocation && (
        <ConfirmDeactivateModal
          label={deactivatingLocation.name}
          onClose={() => setDeactivatingLocation(null)}
          onConfirm={async () => {
            await deactivateInventoryLocation(deactivatingLocation.id);
            setDeactivatingLocation(null);
            notify("Localização desativada.", "success");
            load();
          }}
        />
      )}
    </>
  );
}
