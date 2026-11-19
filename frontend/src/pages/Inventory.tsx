// Inventário central e catálogo — os saldos vêm sempre do livro de movimentos da API.
import { FormEvent, KeyboardEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  createCentralMovement,
  createInventoryItem,
  createInventoryLocation,
  createOpeningStock,
  deactivateInventoryItem,
  deactivateInventoryLocation,
  InventoryItem,
  InventoryLocation,
  InventoryMovement,
  InventoryOwner,
  InventoryCategoryImageInfo,
  getStoredInventoryOwner,
  INVENTORY_OWNER_STORAGE_KEY,
  listInventoryCategoryDetails,
  listInventoryItems,
  listInventoryLocations,
  listInventoryMovements,
  reactivateInventoryItem,
  updateInventoryItem,
  updateInventoryLocation,
  errorMessage,
} from "../api/client";
import Icon from "../components/Icon";
import InventoryItemDocuments from "../components/InventoryItemDocuments";
import { InventoryCategoryImage, InventoryItemPhoto } from "../components/InventoryVisuals";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { formatQuantity } from "../utils/quantities";
import CategoryIllustration from "./CategoryIllustration";
import { searchInventoryItems } from "./inventorySearch";
import { normalizeSearchText } from "../utils/text";

const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  entrada: "Entrada",
  saida: "Saída",
  reserva: "Reserva",
  liberta_reserva: "Libertação de reserva",
  consumo: "Consumo",
  devolucao: "Devolução",
  ajuste: "Ajuste",
  transito_entrada: "Trânsito (entrada)",
  transito_saida: "Transferência",
};

const LOCATION_TYPE_LABELS: Record<string, string> = {
  central: "Central",
  project: "Projeto",
  vehicle: "Viatura",
  supplier: "Fornecedor",
  office: "Escritório",
};

type LocationType = "central" | "project" | "vehicle" | "supplier" | "office";

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `opening-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function RegisterMovementModal({
  items,
  locations,
  onClose,
  onDone,
}: {
  items: InventoryItem[];
  locations: InventoryLocation[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [itemId, setItemId] = useState(items[0]?.id ?? "");
  const [movementType, setMovementType] = useState<"entrada" | "ajuste" | "transito_saida">("entrada");
  const initialLocationId = locations.find((location) => location.location_type === "central")?.id ?? locations[0]?.id ?? "";
  const [locationId, setLocationId] = useState(initialLocationId);
  const [destinationLocationId, setDestinationLocationId] = useState(
    locations.find((location) => location.id !== initialLocationId)?.id ?? initialLocationId,
  );
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const isTransfer = movementType === "transito_saida";
    if (!itemId || !quantity || !locationId || (isTransfer && !destinationLocationId)) {
      setError("Indique o artigo, as localizações e a quantidade.");
      return;
    }
    setSaving(true);
    try {
      await createCentralMovement({
        item_id: itemId,
        movement_type: movementType,
        quantity,
        location_id: locationId,
        ...(isTransfer ? { destination_location_id: destinationLocationId } : {}),
        reference,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Não foi possível registar o movimento."));
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
          <button type="submit" form="movement-form" className="btn btn--primary" disabled={saving || !locations.length}>
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
            onChange={(e) => setMovementType(e.target.value as "entrada" | "ajuste" | "transito_saida")}
          >
            <option value="entrada">Entrada</option>
            <option value="ajuste">Ajuste (+/-)</option>
            <option value="transito_saida">Transferência</option>
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
          <label htmlFor="m-location">{movementType === "transito_saida" ? "Origem" : "Localização"}</label>
          <select id="m-location" className="select" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
            <option value="">— escolha —</option>
            {locations.map((location) => (
              <option key={location.id} value={location.id}>{location.name}</option>
            ))}
          </select>
        </div>
        {movementType === "transito_saida" && (
          <div className="field span-2">
            <label htmlFor="m-destination">Destino</label>
            <select
              id="m-destination"
              className="select"
              value={destinationLocationId}
              onChange={(e) => setDestinationLocationId(e.target.value)}
            >
              <option value="">— escolha —</option>
              {locations.map((location) => (
                <option key={location.id} value={location.id}>{location.name}</option>
              ))}
            </select>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="m-ref">Referência</label>
          <input id="m-ref" className="input" value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

export const LEGACY_INVENTORY_CATEGORY_ALIASES: Readonly<Record<string, string>> = {
  "Cabo AC": "Cabos AC",
  "Cabo DC": "Cabos DC",
  Painel: "Painéis",
  "Painéis solares": "Painéis",
  Inversor: "Inversores",
  Bateria: "Baterias",
  Estrutura: "Estruturas",
  Conector: "Conectores",
  Consumível: "Consumíveis",
};

const INVENTORY_CATEGORY_ORDER = [
  "Painéis",
  "Inversores",
  "Baterias",
  "Estruturas",
  "Cabos DC",
  "Cabos AC",
  "Proteções/Quadros",
  "Conectores",
  "Monitorização/Comunicação",
  "Consumíveis",
  "Outros/Sem categoria",
] as const;

function inventoryCategoryKey(value: string): string {
  return normalizeSearchText(value).replace(/[^a-z0-9]/g, "");
}

const LEGACY_CATEGORY_BY_KEY = new Map(
  Object.entries(LEGACY_INVENTORY_CATEGORY_ALIASES).map(([alias, canonical]) => [
    inventoryCategoryKey(alias),
    canonical,
  ]),
);

function canonicalInventoryCategory(category: string | null | undefined): string {
  if (!category) return "Outros/Sem categoria";
  const key = inventoryCategoryKey(category);
  if (key === "outros") return "Outros/Sem categoria";
  return LEGACY_CATEGORY_BY_KEY.get(key) ?? category;
}

function inventoryCategorySlug(category: string): string {
  return normalizeSearchText(category).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function highlightSearchTerm(text: string, query: string) {
  const normalizedChars: string[] = [];
  const sourceIndexes: number[] = [];
  Array.from(text).forEach((character, index) => {
    const normalized = normalizeSearchText(character);
    for (const normalizedCharacter of normalized) {
      normalizedChars.push(normalizedCharacter);
      sourceIndexes.push(index);
    }
  });
  const normalizedText = normalizedChars.join("");
  const markedIndexes = new Set<number>();
  const queryWords = normalizeSearchText(query).split(/\s+/).filter(Boolean);
  for (const word of queryWords) {
    let from = 0;
    while (from < normalizedText.length) {
      const index = normalizedText.indexOf(word, from);
      if (index < 0) break;
      for (let i = index; i < index + word.length; i += 1) markedIndexes.add(sourceIndexes[i]);
      from = index + Math.max(1, word.length);
    }
  }
  if (markedIndexes.size === 0) return text;
  const parts: React.ReactNode[] = [];
  let current = "";
  let marked = markedIndexes.has(0);
  Array.from(text).forEach((character, index) => {
    const nextMarked = markedIndexes.has(index);
    if (nextMarked !== marked && current) {
      parts.push(marked ? <mark key={`mark-${index}`}>{current}</mark> : current);
      current = "";
    }
    current += character;
    marked = nextMarked;
  });
  if (current) parts.push(marked ? <mark key="mark-end">{current}</mark> : current);
  return parts;
}

function sumStockByUnit(items: InventoryItem[], field: "physical_stock" | "total_reserved" | "available_stock"): string {
  const sums = new Map<string, number>();
  for (const item of items) {
    sums.set(item.unit, (sums.get(item.unit) ?? 0) + Number(item[field] ?? 0));
  }
  return Array.from(sums.entries())
    .map(([unit, value]) => `${formatQuantity(value.toFixed(3), unit)} ${unit}`)
    .join(" · ") || "—";
}

type InventoryCategoryGroup = { label: string; items: InventoryItem[] };
type InventorySort = "name" | "stock";

function sectionedInventoryGroups(items: InventoryItem[]): Array<{ section: string | null; items: InventoryItem[] }> {
  const groups = new Map<string, InventoryItem[]>();
  for (const item of items) {
    const label = item.section_label?.trim() || "Sem secção";
    groups.set(label, [...(groups.get(label) ?? []), item]);
  }
  const hasSectionData = items.some((item) => Boolean(item.section_label?.trim()));
  if (!hasSectionData) return [{ section: null, items }];
  return Array.from(groups, ([section, sectionItems]) => ({ section, items: sectionItems }))
    .sort((left, right) => left.section!.localeCompare(right.section!, "pt-PT"));
}

function InventoryArticleList({
  group,
  sort,
  canManageCatalog,
  canManageCentral,
  onEdit,
  onDetail,
  onOpeningStock,
  onDeactivate,
  onReactivate,
}: {
  group: InventoryCategoryGroup;
  sort: InventorySort;
  canManageCatalog: boolean;
  canManageCentral: boolean;
  onEdit: (item: InventoryItem) => void;
  onDetail: (item: InventoryItem) => void;
  onOpeningStock: (item: InventoryItem) => void;
  onDeactivate: (item: InventoryItem) => void;
  onReactivate: (item: InventoryItem) => void;
}) {
  const sortedItems = [...group.items].sort((left, right) => sort === "stock"
    ? Number(right.physical_stock) - Number(left.physical_stock) || left.name.localeCompare(right.name, "pt-PT")
    : left.name.localeCompare(right.name, "pt-PT"));
  const panelTable = group.label === "Painéis";
  const actions = (item: InventoryItem) => (canManageCatalog || canManageCentral) ? (
    <div className="cluster inventory-item-actions">
      {canManageCatalog && <>
        <button type="button" className="btn btn--sm" onClick={() => onEdit(item)} aria-label={`Editar ${item.name}`}>Editar</button>
        {item.is_active
          ? <button type="button" className="btn btn--sm btn--ghost" onClick={() => onDeactivate(item)}>Desativar</button>
          : <button type="button" className="btn btn--sm btn--ghost" onClick={() => onReactivate(item)}>Reativar</button>}
      </>}
      {canManageCentral && item.is_active && <button type="button" className="btn btn--sm btn--ghost" onClick={() => onOpeningStock(item)}>Stock inicial</button>}
    </div>
  ) : null;

  if (panelTable) {
    return <>
      <div className="inventory-panel-note">Abra um artigo para consultar os metadados disponíveis.</div>
      <div className="table-wrap">
        <table className="table">
          <caption className="sr-only">Stock de painéis</caption>
          <thead><tr>
            <th scope="col">Artigo</th><th scope="col">SKU</th><th scope="col">Físico</th><th scope="col">Reservado</th><th scope="col">Disponível</th><th scope="col">Mínimo</th><th scope="col">Estado</th><th scope="col">Stock por localização</th>
            {(canManageCatalog || canManageCentral) && <th scope="col">Ações</th>}
          </tr></thead>
          <tbody>{sortedItems.map((item) => <tr key={item.id}>
            <td><button type="button" className="btn btn--sm btn--ghost cell-title" aria-label={`Ver artigo ${item.name}`} onClick={() => onDetail(item)}>{item.name}</button>{!item.is_active && <span className="cell-sub">Inativo</span>}</td>
            <td className="nowrap muted">{item.sku}</td>
            <td className="nowrap">{formatQuantity(item.physical_stock, item.unit)} {item.unit}</td>
            <td className="nowrap">{formatQuantity(item.total_reserved, item.unit)} {item.unit}</td>
            <td className="nowrap">{formatQuantity(item.available_stock, item.unit)} {item.unit}</td>
            <td className="nowrap muted">{formatQuantity(item.min_stock, item.unit)} {item.unit}</td>
            <td>{!item.is_active ? <Badge tone="neutral">Inativo</Badge> : item.below_min_stock ? <Badge tone="danger" dot>Abaixo do mínimo</Badge> : <Badge tone="success" dot>OK</Badge>}</td>
            <td>{(item.location_stocks ?? []).length ? <ul className="inventory-location-stock">{item.location_stocks?.map((stock) => <li key={`${item.id}-${stock.location_id ?? "legacy"}`}>{stock.location_name}: {formatQuantity(stock.physical_stock, item.unit)} {item.unit}</li>)}</ul> : <span className="muted">—</span>}</td>
            {(canManageCatalog || canManageCentral) && <td>{actions(item)}</td>}
          </tr>)}</tbody>
        </table>
      </div>
    </>;
  }

  return <ul className="inventory-article-list">{sortedItems.map((item) => <li className="inventory-article" key={item.id}>
    <CategoryIllustration category={group.label} />
    <div className="inventory-article__main">
      <div className="inventory-article__heading"><button type="button" className="btn btn--sm btn--ghost cell-title" aria-label={`Ver artigo ${item.name}`} onClick={() => onDetail(item)}>{item.name}</button>{!item.is_active ? <Badge tone="neutral">Inativo</Badge> : item.below_min_stock ? <Badge tone="danger" dot>Abaixo do mínimo</Badge> : null}</div>
      <div className="inventory-article__meta"><span>Referência: <strong>{item.sku}</strong></span><span>Unidade: <strong>{item.unit}</strong></span>{group.label === "Outros/Sem categoria" && <span>Categoria: <strong>{item.category ?? "Sem categoria"}</strong></span>}</div>
      <div className="inventory-article__stock">
        <span>Stock: <strong>{formatQuantity(item.physical_stock, item.unit)} {item.unit}</strong></span>
        <span>Disponível: <strong>{formatQuantity(item.available_stock, item.unit)} {item.unit}</strong></span>
        <span>Reservado: <strong>{formatQuantity(item.total_reserved, item.unit)} {item.unit}</strong></span>
      </div>
      {(item.location_stocks ?? []).length > 0 && <ul className="inventory-location-stock inventory-article__locations">{item.location_stocks?.map((stock) => <li key={`${item.id}-${stock.location_id ?? "legacy"}`}>{stock.location_name}: {formatQuantity(stock.physical_stock, item.unit)} {item.unit}</li>)}</ul>}
    </div>
    {actions(item)}
  </li>)}</ul>;
}

function ItemFormModal({
  item,
  categories,
  onClose,
  onSaved,
}: {
  item: InventoryItem | null;
  categories: string[];
  onClose: () => void;
  onSaved: (saved: InventoryItem, created: boolean) => void;
}) {
  const [sku, setSku] = useState(item?.sku ?? "");
  const [name, setName] = useState(item?.name ?? "");
  const [unit, setUnit] = useState(item?.unit ?? "un");
  const [category, setCategory] = useState(item?.category ?? "");
  const [manufacturer, setManufacturer] = useState(item?.manufacturer ?? "");
  const [model, setModel] = useState(item?.model ?? "");
  const [subcategory, setSubcategory] = useState(item?.subcategory ?? "");
  const [powerW, setPowerW] = useState(item?.power_w ?? "");
  const [crossSectionMm2, setCrossSectionMm2] = useState(item?.cross_section_mm2 ?? "");
  const [minStock, setMinStock] = useState(item?.min_stock ?? "0");
  const [leadTime, setLeadTime] = useState(item?.lead_time_days === null || item?.lead_time_days === undefined ? "" : String(item.lead_time_days));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const canonicalCategory = canonicalInventoryCategory(category);
  const equipmentCategory = ["Painéis", "Inversores", "Baterias"].includes(canonicalCategory);
  const showManufacturerModel = equipmentCategory || Boolean(item?.manufacturer || item?.model);
  const showPower = ["Painéis", "Inversores"].includes(canonicalCategory) || Boolean(item?.power_w);
  const showCrossSection = ["Cabos AC", "Cabos DC"].includes(canonicalCategory) || Boolean(item?.cross_section_mm2);

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
        manufacturer: showManufacturerModel ? manufacturer.trim() || null : null,
        model: showManufacturerModel ? model.trim() || null : null,
        subcategory: subcategory.trim() || null,
        power_w: showPower ? powerW.trim() || null : null,
        cross_section_mm2: showCrossSection ? crossSectionMm2.trim() || null : null,
        min_stock: minStock.trim(),
        lead_time_days: leadTime.trim() ? Number(leadTime) : null,
      };
      const saved = item ? await updateInventoryItem(item.id, payload) : await createInventoryItem(payload);
      onSaved(saved, item === null);
    } catch (err) {
      setError(errorMessage(err, "Não foi possível guardar o artigo."));
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
            {categories.map((categoryOption) => (
              <option key={categoryOption} value={categoryOption} />
            ))}
          </datalist>
        </div>
        <div className="field span-2">
          <label htmlFor="item-name">Nome</label>
          <input id="item-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={256} />
        </div>
        {showManufacturerModel && <>
          <div className="field">
            <label htmlFor="item-manufacturer">Fabricante</label>
            <input id="item-manufacturer" className="input" value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} maxLength={128} />
          </div>
          <div className="field">
            <label htmlFor="item-model">Modelo</label>
            <input id="item-model" className="input" value={model} onChange={(e) => setModel(e.target.value)} maxLength={128} />
          </div>
        </>}
        <div className="field span-2">
          <label htmlFor="item-subcategory">Subsecção</label>
          <input id="item-subcategory" className="input" value={subcategory} onChange={(e) => setSubcategory(e.target.value)} maxLength={128} />
        </div>
        {showPower && <div className="field">
          <label htmlFor="item-power-w">Potência (W)</label>
          <input id="item-power-w" className="input" type="number" min="0" step="0.001" value={powerW} onChange={(e) => setPowerW(e.target.value)} />
        </div>}
        {showCrossSection && <div className="field">
          <label htmlFor="item-cross-section">Secção (mm²)</label>
          <input id="item-cross-section" className="input" type="number" min="0" step="0.001" value={crossSectionMm2} onChange={(e) => setCrossSectionMm2(e.target.value)} />
        </div>}
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

function OpeningStockModal({ item, owner, locations, onClose, onDone }: {
  item: InventoryItem;
  owner: InventoryOwner;
  locations: InventoryLocation[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState("");
  const [locationId, setLocationId] = useState(
    locations.find((location) => location.location_type === "central")?.id ?? locations[0]?.id ?? "",
  );
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
        ...(locationId ? { location_id: locationId } : {}),
      }, owner);
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Não foi possível registar o stock inicial."));
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
        {locations.length > 0 && (
          <div className="field span-2">
            <label htmlFor="opening-location">Localização</label>
            <select id="opening-location" className="select" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
              <option value="">— escolha —</option>
              {locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
            </select>
          </div>
        )}
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
  activeOwner,
  onClose,
  onSaved,
}: {
  location: InventoryLocation | null;
  centralOnly: boolean;
  activeOwner: InventoryOwner;
  onClose: () => void;
  onSaved: (saved: InventoryLocation, created: boolean) => void;
}) {
  const initialType = (location?.location_type ?? (centralOnly ? "central" : "vehicle")) as LocationType;
  const [code, setCode] = useState(location?.code ?? "");
  const [name, setName] = useState(location?.name ?? "");
  const [locationType, setLocationType] = useState<LocationType>(initialType);
  const [projectId, setProjectId] = useState(location?.project_id ?? "");
  const [locationOwner, setLocationOwner] = useState<InventoryOwner>(location?.owner ?? activeOwner);
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
        owner: locationOwner,
        ...(editing ? { is_active: isActive } : {}),
      };
      const saved = location ? await updateInventoryLocation(location.id, payload) : await createInventoryLocation(payload);
      onSaved(saved, !editing);
    } catch (err) {
      setError(errorMessage(err, "Não foi possível guardar a localização."));
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
        <div className="field">
          <label htmlFor="location-owner">Proprietário</label>
          <select id="location-owner" className="select" value={locationOwner} onChange={(e) => setLocationOwner(e.target.value as InventoryOwner)}>
            <option value="solcor">Solcor</option>
            <option value="verde_milenar">Verde Milenar</option>
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
      setError(errorMessage(err, "Não foi possível desativar o registo."));
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
  const { me, can } = useSession();
  const { notify } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [owner, setOwner] = useState<InventoryOwner>(getStoredInventoryOwner);
  const [isDesktopInspector, setIsDesktopInspector] = useState(
    () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1100px)").matches,
  );
  const sectionHash = location.hash.slice(1);
  const activeInventorySection = ["inventory-categories", "inventory-locations", "inventory-movements"].includes(sectionHash)
    ? sectionHash
    : "inventory-categories";
  const accountKey = me?.user_id ?? me?.person_id ?? "anonymous";
  const currentOwnerRef = useRef(owner);
  const currentAccountKeyRef = useRef(accountKey);
  currentOwnerRef.current = owner;
  currentAccountKeyRef.current = accountKey;
  const [items, setItems] = useState<InventoryItem[] | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [categoryImages, setCategoryImages] = useState<InventoryCategoryImageInfo[]>([]);
  const [locations, setLocations] = useState<InventoryLocation[] | null>(null);
  const [movements, setMovements] = useState<InventoryMovement[] | null>(null);
  const [hideEmptyCategories, setHideEmptyCategories] = useState(false);
  const [searchInput, setSearchInput] = useState(() => searchParams.get("q") ?? "");
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get("q") ?? "");
  const [searchFocused, setSearchFocused] = useState(false);
  const [activeSearchOption, setActiveSearchOption] = useState(-1);
  const [sort, setSort] = useState<InventorySort>("name");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const inspectorHeadingRef = useRef<HTMLHeadingElement>(null);
  const inspectorTriggerRef = useRef<HTMLElement | null>(null);
  const focusInspectorAfterOpenRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [creatingItem, setCreatingItem] = useState(false);
  const [editingItem, setEditingItem] = useState<InventoryItem | null>(null);
  const [viewingItem, setViewingItem] = useState<{ item: InventoryItem; owner: InventoryOwner; accountKey: string } | null>(null);
  const [openingStockItem, setOpeningStockItem] = useState<InventoryItem | null>(null);
  const [deactivatingItem, setDeactivatingItem] = useState<InventoryItem | null>(null);
  const [locationForm, setLocationForm] = useState<{ location: InventoryLocation | null; centralOnly: boolean } | null>(null);
  const [locationManagementOpen, setLocationManagementOpen] = useState(false);
  const [deactivatingLocation, setDeactivatingLocation] = useState<InventoryLocation | null>(null);

  const canManageCentral = can("inventory.manage_central");
  const canManageCatalog = can("inventory.manage_catalog");
  const activeItems = useMemo(() => (items ?? []).filter((item) => item.is_active), [items]);
  const activeLocations = useMemo(
    () => (locations ?? []).filter((location) => location.owner === owner && location.is_active),
    [locations, owner],
  );
  const activeCentralLocations = useMemo(
    () => activeLocations.filter((location) => location.location_type === "central"),
    [activeLocations],
  );
  const itemUnits = useMemo(() => new Map((items ?? []).map((item) => [item.id, item.unit])), [items]);
  const centralLocation = activeCentralLocations.length === 1 ? activeCentralLocations[0] : null;
  const selectedCategorySlug = searchParams.get("categoria");
  const selectedCategory = INVENTORY_CATEGORY_ORDER.find((label) => inventoryCategorySlug(label) === selectedCategorySlug) ?? null;
  const resultsMode = Boolean(searchParams.get("q")) && !selectedCategory;
  const categoryImageByLabel = useMemo(
    () => new Map(categoryImages.map((detail) => [canonicalInventoryCategory(detail.name), detail])),
    [categoryImages],
  );
  const categoryForItem = useCallback((item: InventoryItem) => {
    const category = canonicalInventoryCategory(item.category);
    return INVENTORY_CATEGORY_ORDER.includes(category as typeof INVENTORY_CATEGORY_ORDER[number])
      ? category
      : "Outros/Sem categoria";
  }, []);
  const catalogGroups = useMemo(() => {
    const groups: InventoryCategoryGroup[] = INVENTORY_CATEGORY_ORDER.map((label) => ({ label, items: [] }));
    const groupsByLabel = new Map(groups.map((group) => [group.label, group]));
    for (const item of items ?? []) groupsByLabel.get(categoryForItem(item))?.items.push(item);
    return groups.sort((left, right) => Number(left.items.length === 0) - Number(right.items.length === 0));
  }, [items, categoryForItem]);
  const visibleGroups = useMemo(
    () => hideEmptyCategories ? catalogGroups.filter((group) => group.items.length > 0) : catalogGroups,
    [catalogGroups, hideEmptyCategories],
  );
  const searchResults = useMemo(
    () => searchInventoryItems(items ?? [], searchQuery, categoryForItem),
    [items, searchQuery, categoryForItem],
  );
  const searchOptions = searchResults.slice(0, 8);
  const showSearchSuggestions = searchFocused && searchInput.trim().length > 0 && !resultsMode;
  const resultGroups = useMemo(() => {
    const groups: InventoryCategoryGroup[] = INVENTORY_CATEGORY_ORDER.map((label) => ({ label, items: [] }));
    const groupsByLabel = new Map(groups.map((group) => [group.label, group]));
    for (const item of searchResults) groupsByLabel.get(categoryForItem(item))?.items.push(item);
    return groups.filter((group) => group.items.length > 0);
  }, [searchResults, categoryForItem]);

  const load = useCallback(() => {
    setError(null);
    setItems(null);
    setLocations(null);
    setMovements(null);
    setViewingItem(null);
    inspectorTriggerRef.current = null;
    focusInspectorAfterOpenRef.current = false;
    Promise.all([
      listInventoryItems(owner),
      listInventoryLocations(owner),
      listInventoryMovements({ owner }),
      listInventoryCategoryDetails(),
    ])
      .then(([loadedItems, loadedLocations, loadedMovements, loadedCategoryDetails]) => {
        setItems(loadedItems);
        setLocations(loadedLocations);
        setMovements(loadedMovements);
        setCategoryImages(loadedCategoryDetails);
        setCategories(loadedCategoryDetails.map((detail) => detail.name));
      })
      .catch((err) => setError(errorMessage(err, "Não foi possível contactar o servidor.")));
  }, [owner]);

  useEffect(load, [load]);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(min-width: 1100px)");
    const update = () => setIsDesktopInspector(query.matches);
    update();
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", update);
      return () => query.removeEventListener("change", update);
    }
    query.addListener(update);
    return () => query.removeListener(update);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(searchInput.trim()), 150);
    return () => window.clearTimeout(timer);
  }, [searchInput]);
  useEffect(() => {
    const urlQuery = searchParams.get("q") ?? "";
    setSearchInput(urlQuery);
    setSearchQuery(urlQuery);
    setActiveSearchOption(-1);
    setSearchFocused(false);
  }, [searchParams]);
  useEffect(() => {
    function focusSearch(event: globalThis.KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping = target?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName ?? "");
      if (event.key === "/" && !event.altKey && !event.ctrlKey && !event.metaKey && !isTyping) {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(INVENTORY_OWNER_STORAGE_KEY, owner);
    } catch {
      // LocalStorage pode estar indisponível em modo privado.
    }
  }, [owner]);
  async function reactivateItem(item: InventoryItem) {
    try {
      const saved = await reactivateInventoryItem(item.id);
      notify(`Artigo «${saved.name}» reativado.`, "success");
      load();
    } catch (err) {
      notify(errorMessage(err, "Não foi possível reativar o artigo."), "error");
    }
  }

  function openCategory(category: string) {
    setViewingItem(null);
    inspectorTriggerRef.current = null;
    focusInspectorAfterOpenRef.current = false;
    setSearchParams({ categoria: inventoryCategorySlug(category) });
    setSearchInput("");
    setSearchQuery("");
    setActiveSearchOption(-1);
    setSearchFocused(false);
    setSort("name");
  }

  function showSearchResults() {
    const query = searchInput.trim();
    setSearchParams(query ? { q: query } : {});
    setSearchQuery(query);
    setActiveSearchOption(-1);
    setSearchFocused(false);
  }

  function navigateToInventorySection(event: ReactMouseEvent<HTMLAnchorElement>, section: string) {
    if (event.defaultPrevented || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    navigate({ pathname: location.pathname, search: location.search, hash: `#${section}` });
    document.getElementById(section)?.scrollIntoView?.({ block: "start" });
  }

  function openItemDetail(item: InventoryItem) {
    const useDesktopInspector = isDesktopInspector && Boolean(selectedCategory);
    const trigger = document.activeElement;
    inspectorTriggerRef.current = useDesktopInspector && trigger instanceof HTMLElement ? trigger : null;
    focusInspectorAfterOpenRef.current = useDesktopInspector;
    setViewingItem({ item, owner, accountKey });
  }

  function closeDesktopInspector() {
    setViewingItem(null);
    const trigger = inspectorTriggerRef.current;
    inspectorTriggerRef.current = null;
    focusInspectorAfterOpenRef.current = false;
    if (trigger?.isConnected) trigger.focus();
  }

  function showAllCategories() {
    setViewingItem(null);
    inspectorTriggerRef.current = null;
    focusInspectorAfterOpenRef.current = false;
    setSearchParams({});
    setSearchInput("");
    setSearchQuery("");
    setActiveSearchOption(-1);
    setSearchFocused(false);
    searchInputRef.current?.focus();
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" && searchOptions.length > 0) {
      event.preventDefault();
      setActiveSearchOption((current) => current < searchOptions.length - 1 ? current + 1 : 0);
    } else if (event.key === "ArrowUp" && searchOptions.length > 0) {
      event.preventDefault();
      setActiveSearchOption((current) => current > 0 ? current - 1 : searchOptions.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (activeSearchOption >= 0 && searchOptions[activeSearchOption]) {
        openCategory(categoryForItem(searchOptions[activeSearchOption]));
      } else {
        showSearchResults();
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      showAllCategories();
    }
  }

  const ownerSelector = (
    <div className="inventory-owner-toggle" role="group" aria-label="Inventário por proprietário">
      <button type="button" className="inventory-owner-toggle__button" aria-pressed={owner === "solcor"} onClick={() => setOwner("solcor")}>
        Solcor
      </button>
      <button type="button" className="inventory-owner-toggle__button" aria-pressed={owner === "verde_milenar"} onClick={() => setOwner("verde_milenar")}>
        Verde Milenar
      </button>
    </div>
  );

  const currentViewingItem = viewingItem && viewingItem.owner === owner && viewingItem.accountKey === accountKey
    ? viewingItem
    : null;
  useEffect(() => {
    if (!currentViewingItem) {
      focusInspectorAfterOpenRef.current = false;
      return;
    }
    if (!focusInspectorAfterOpenRef.current) return;
    focusInspectorAfterOpenRef.current = false;
    if (isDesktopInspector && selectedCategory) inspectorHeadingRef.current?.focus();
  }, [currentViewingItem, isDesktopInspector, selectedCategory]);
  const itemDetailContent = currentViewingItem && (
    <div className="inventory-item-detail">
      <InventoryItemPhoto
        itemId={currentViewingItem.item.id}
        itemName={currentViewingItem.item.name}
        category={categoryForItem(currentViewingItem.item)}
        hasPhoto={currentViewingItem.item.has_photo ?? false}
        canManage={canManageCatalog}
        accountKey={accountKey}
        onPhotoChanged={(hasPhoto) => {
          if (currentOwnerRef.current !== currentViewingItem.owner || currentAccountKeyRef.current !== currentViewingItem.accountKey) return;
          setItems((current) => current?.map((entry) => entry.id === currentViewingItem.item.id ? { ...entry, has_photo: hasPhoto } : entry) ?? null);
          setViewingItem((current) => current && current.item.id === currentViewingItem.item.id
            ? { ...current, item: { ...current.item, has_photo: hasPhoto } }
            : current);
        }}
      />
      <dl className="inventory-item-detail__metadata">
        <div><dt>Referência</dt><dd>{currentViewingItem.item.sku}</dd></div>
        <div><dt>Categoria</dt><dd>{currentViewingItem.item.category ?? "Sem categoria"}</dd></div>
        <div><dt>Unidade</dt><dd>{currentViewingItem.item.unit}</dd></div>
        {currentViewingItem.item.manufacturer && <div><dt>Fabricante</dt><dd>{currentViewingItem.item.manufacturer}</dd></div>}
        {currentViewingItem.item.model && <div><dt>Modelo</dt><dd>{currentViewingItem.item.model}</dd></div>}
        {currentViewingItem.item.subcategory && <div><dt>Subsecção</dt><dd>{currentViewingItem.item.subcategory}</dd></div>}
        {currentViewingItem.item.power_w !== null && currentViewingItem.item.power_w !== undefined && <div><dt>Potência</dt><dd>{formatQuantity(currentViewingItem.item.power_w, "un")} W</dd></div>}
        {currentViewingItem.item.cross_section_mm2 !== null && currentViewingItem.item.cross_section_mm2 !== undefined && <div><dt>Secção</dt><dd>{formatQuantity(currentViewingItem.item.cross_section_mm2, "un")} mm²</dd></div>}
      </dl>
      <div className="inventory-item-detail__stock">
        <h3>Stock</h3>
        <p>Físico: <strong>{formatQuantity(currentViewingItem.item.physical_stock, currentViewingItem.item.unit)} {currentViewingItem.item.unit}</strong></p>
        <p>Disponível: <strong>{formatQuantity(currentViewingItem.item.available_stock, currentViewingItem.item.unit)} {currentViewingItem.item.unit}</strong></p>
        <p>Reservado: <strong>{formatQuantity(currentViewingItem.item.total_reserved, currentViewingItem.item.unit)} {currentViewingItem.item.unit}</strong></p>
        <h4>Stock por localização</h4>
        {(currentViewingItem.item.location_stocks ?? []).length ? <ul className="inventory-location-stock">
          {currentViewingItem.item.location_stocks?.map((stock) => <li key={`${currentViewingItem.item.id}-${stock.location_id ?? "legacy"}`}>
            {stock.location_name}: {formatQuantity(stock.physical_stock, currentViewingItem.item.unit)} {currentViewingItem.item.unit}
          </li>)}
        </ul> : <span className="muted">Sem stock por localização.</span>}
      </div>
      <InventoryItemDocuments
        itemId={currentViewingItem.item.id}
        canManage={canManageCatalog}
        accountKey={accountKey}
      />
    </div>
  );

  if (error) {
    return (
      <div className="inventory-page">
        <PageHeader title="Inventário" actions={ownerSelector} />
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      </div>
    );
  }

  return (
    <div className="inventory-page">
      <PageHeader
        title="Inventário"
        subtitle="Catálogo e stock por localização."
        actions={
          <>
            {ownerSelector}
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
        <div className="inventory-catalog-tools" id="inventory-categories">
          <div className="inventory-search">
            <label htmlFor="inventory-search">Pesquisar inventário</label>
            <div className="inventory-search__control">
              <input
                ref={searchInputRef}
                id="inventory-search"
                className="input"
                type="search"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={showSearchSuggestions}
                aria-controls="inventory-search-results"
                aria-activedescendant={showSearchSuggestions && activeSearchOption >= 0 ? `inventory-search-option-${activeSearchOption}` : undefined}
                value={searchInput}
                onChange={(event) => { setSearchInput(event.target.value); setActiveSearchOption(-1); }}
                onKeyDown={handleSearchKeyDown}
                onFocus={() => setSearchFocused(true)}
                onBlur={() => setSearchFocused(false)}
                placeholder="Nome, referência, fabricante, modelo ou categoria"
                autoComplete="off"
              />
              {searchInput && <button type="button" className="btn btn--sm" onClick={showAllCategories} aria-label="Limpar pesquisa">Limpar</button>}
              <span className="inventory-search__shortcut" aria-hidden="true">/</span>
            </div>
            <span className="field__hint" aria-live="polite">
              {searchInput.trim() ? `${searchResults.length} ${searchResults.length === 1 ? "resultado" : "resultados"}` : `${(items ?? []).length} artigos`}
            </span>
            {showSearchSuggestions && <div className="inventory-search__suggestions" id="inventory-search-results">
              {searchOptions.length > 0 ? <div role="listbox" aria-label="Sugestões de artigos">
                {searchOptions.map((item, index) => {
                  const category = categoryForItem(item);
                  return <div
                    id={`inventory-search-option-${index}`}
                    key={item.id}
                    role="option"
                    aria-label={`${item.name}, ${item.sku}, ${category}, ${formatQuantity(item.physical_stock, item.unit)} ${item.unit}`}
                    aria-selected={activeSearchOption === index}
                    className="inventory-search-option"
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setActiveSearchOption(index)}
                    onClick={() => openCategory(category)}
                  >
                    <CategoryIllustration category={category} />
                    <span className="inventory-search-option__main"><strong>{highlightSearchTerm(item.name, searchInput)}</strong><span>{item.sku} · {category}</span></span>
                    <span className="inventory-search-option__stock">{formatQuantity(item.physical_stock, item.unit)} {item.unit}</span>
                  </div>;
                })}
              </div> : <div className="inventory-search-no-results" role="status">
                <span>Sem resultados para «{searchInput}»</span>
                <button type="button" className="btn btn--sm" onMouseDown={(event) => event.preventDefault()} onClick={showAllCategories}>Ver todas as categorias</button>
              </div>}
            </div>}
          </div>
          {!selectedCategory && !resultsMode && <label className="inventory-hide-empty">
            <input type="checkbox" checked={hideEmptyCategories} onChange={(event) => setHideEmptyCategories(event.target.checked)} />
            Esconder categorias vazias
          </label>}
        </div>
        <nav className="inventory-section-links" aria-label="Secções do inventário">
          <a href="#inventory-categories" aria-current={activeInventorySection === "inventory-categories" ? "location" : undefined} onClick={(event) => navigateToInventorySection(event, "inventory-categories")}>Categorias</a>
          <a href="#inventory-locations" aria-current={activeInventorySection === "inventory-locations" ? "location" : undefined} onClick={(event) => navigateToInventorySection(event, "inventory-locations")}>Localizações</a>
          <a href="#inventory-movements" aria-current={activeInventorySection === "inventory-movements" ? "location" : undefined} onClick={(event) => navigateToInventorySection(event, "inventory-movements")}>Movimentos</a>
        </nav>
        {items === null ? <LoadingState rows={4} /> : selectedCategory ? (() => {
          const group = catalogGroups.find((candidate) => candidate.label === selectedCategory) ?? { label: selectedCategory, items: [] };
          const sections = sectionedInventoryGroups(group.items);
          return <section className="inventory-category-detail">
            <nav className="inventory-breadcrumb" aria-label="Trilho de navegação">
              <button type="button" className="btn btn--sm btn--ghost" onClick={showAllCategories}>Inventário</button><span aria-hidden="true">›</span><span aria-current="page">{selectedCategory}</span>
            </nav>
            <div className={`inventory-category-layout${isDesktopInspector && currentViewingItem ? " inventory-category-layout--inspecting" : ""}`}>
              <div className="inventory-category-main">
                <div className="inventory-detail-heading"><div><h2>{selectedCategory}</h2><p>{group.items.length} {group.items.length === 1 ? "artigo" : "artigos"} · {sumStockByUnit(group.items, "physical_stock")} em stock</p></div>
                  <label className="inventory-sort"><span>Ordenar artigos</span><select className="select" value={sort} onChange={(event) => setSort(event.target.value as InventorySort)}><option value="name">Nome</option><option value="stock">Stock</option></select></label>
                </div>
                {(() => {
                  const imageInfo = categoryImages.find((detail) => detail.name === selectedCategory)
                    ?? categoryImageByLabel.get(selectedCategory);
                  const isCanonicalApiCategory = imageInfo?.name === selectedCategory;
                  return <InventoryCategoryImage
                    category={imageInfo?.name ?? selectedCategory}
                    hasCustomImage={imageInfo?.has_custom_image ?? false}
                    imageVersion={imageInfo?.image_version ?? null}
                    accountKey={accountKey}
                    canManage={canManageCatalog && isCanonicalApiCategory}
                    onImageChanged={(updatedImage) => {
                      if (currentOwnerRef.current !== owner || currentAccountKeyRef.current !== accountKey) return;
                      setCategoryImages((current) => current.map((detail) => detail.name === updatedImage.name ? updatedImage : detail));
                    }}
                  />;
                })()}
                {group.items.length === 0 ? <EmptyState icon="database" title={`Ainda não há artigos em ${selectedCategory}.`} /> : <div className="inventory-detail-sections">
                  {sections.map((section) => <section className="inventory-subsection" key={section.section ?? "all"}>
                    {section.section && <h3>{section.section}</h3>}
                    <InventoryArticleList group={{ label: selectedCategory, items: section.items }} sort={sort} canManageCatalog={canManageCatalog} canManageCentral={canManageCentral} onEdit={setEditingItem} onDetail={openItemDetail} onOpeningStock={setOpeningStockItem} onDeactivate={setDeactivatingItem} onReactivate={(item) => void reactivateItem(item)} />
                  </section>)}
                </div>}
              </div>
              {isDesktopInspector && currentViewingItem && itemDetailContent && <aside className="inventory-item-inspector" aria-labelledby="inventory-item-inspector-heading">
                <header className="inventory-item-inspector__header">
                  <h2 ref={inspectorHeadingRef} id="inventory-item-inspector-heading" tabIndex={-1}>Ficha do artigo — {currentViewingItem.item.name}</h2>
                  <button type="button" aria-label="Fechar ficha do artigo" onClick={closeDesktopInspector}>×</button>
                </header>
                {itemDetailContent}
              </aside>}
            </div>
          </section>;
        })() : resultsMode ? <section className="inventory-search-page">
          <h2>Resultados para «{searchParams.get("q") ?? ""}»</h2>
          {resultGroups.length === 0 ? <EmptyState icon="search" title="Sem resultados" text={`Sem resultados para «${searchParams.get("q") ?? ""}» — ver todas as categorias.`} action={<button type="button" className="btn btn--primary" onClick={showAllCategories}>Ver todas as categorias</button>} /> : resultGroups.map((group) => <section className="inventory-result-group" key={group.label}>
            <div className="inventory-result-group__heading"><h3>{group.label}</h3><button type="button" className="btn btn--sm" onClick={() => openCategory(group.label)}>Ver categoria</button></div>
            <InventoryArticleList group={group} sort="name" canManageCatalog={canManageCatalog} canManageCentral={canManageCentral} onEdit={setEditingItem} onDetail={openItemDetail} onOpeningStock={setOpeningStockItem} onDeactivate={setDeactivatingItem} onReactivate={(item) => void reactivateItem(item)} />
          </section>)}
        </section> : items.length === 0 ? <EmptyState icon="database" title="Sem artigos de inventário ainda." text={canManageCatalog ? "Crie o primeiro artigo para poder registar stock inicial." : "Um utilizador autorizado pode criar o catálogo."} action={canManageCatalog ? <button type="button" className="btn btn--primary" onClick={() => setCreatingItem(true)}><Icon name="plus" size={16} /> Criar artigo</button> : undefined} /> : <div className="inventory-category-grid">
          {visibleGroups.map((group) => {
            const itemCountLabel = `${group.items.length} ${group.items.length === 1 ? "artigo" : "artigos"}`;
            const imageInfo = categoryImageByLabel.get(group.label);
            return <button type="button" className={`inventory-category-card${group.items.length === 0 ? " inventory-category-card--empty" : ""}`} key={group.label} onClick={() => openCategory(group.label)}>
              <InventoryCategoryImage
                category={group.label}
                hasCustomImage={imageInfo?.has_custom_image ?? false}
                imageVersion={imageInfo?.image_version ?? null}
                accountKey={accountKey}
              />
              <span className="inventory-category-card__name">{group.label}</span>
              <span className="inventory-category-card__count">{itemCountLabel}</span>
              <span className="inventory-category-card__stock">{sumStockByUnit(group.items, "physical_stock")} em stock</span>
              <span className="inventory-category-card__action">Ver artigos <span aria-hidden="true">→</span></span>
            </button>;
          })}
        </div>}
      </Card>

      <div className="section-gap" id="inventory-locations">
        <Card
          title="Localizações"
          icon="mapPin"
          actions={
            canManageCatalog && (
              <button type="button" className="btn" onClick={() => setLocationManagementOpen(true)}>
                Gerir localizações
              </button>
            )
          }
        >
          <div style={{ padding: 16 }}>
            {locations === null ? (
              <LoadingState label="A carregar localizações…" rows={1} />
            ) : (
              <>
                <p className="small muted">
                  {centralLocation ? (
                    <>Localização central de {owner === "solcor" ? "Solcor" : "Verde Milenar"}: <strong>{centralLocation.name}</strong> · {activeLocations.length} localizações ativas.</>
                  ) : (
                    <>Sem localização central única ativa para {owner === "solcor" ? "Solcor" : "Verde Milenar"} · {activeLocations.length} localizações ativas.</>
                  )}
                </p>
                {!centralLocation && (
                  <Alert tone="danger">
                    Não existe exatamente uma localização central ativa para este proprietário. O stock inicial fica bloqueado até esta situação ser corrigida.
                  </Alert>
                )}
              </>
            )}
          </div>
        </Card>
      </div>

      <div className="section-gap" id="inventory-movements">
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
                      <td className="nowrap">{formatQuantity(movement.quantity, itemUnits.get(movement.item_id))} {itemUnits.get(movement.item_id) ?? ""}</td>
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

      {currentViewingItem && (!isDesktopInspector || !selectedCategory) && itemDetailContent && (
        <Modal
          title={`Ficha do artigo — ${currentViewingItem.item.name}`}
          onClose={() => setViewingItem(null)}
          footer={<button type="button" className="btn" onClick={() => setViewingItem(null)}>Fechar</button>}
        >
          {itemDetailContent}
        </Modal>
      )}
      {creatingItem && (
        <ItemFormModal
          item={null}
          categories={categories}
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
          categories={categories}
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
          owner={owner}
          locations={activeLocations}
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
          locations={activeLocations}
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
      {canManageCatalog && locationManagementOpen && (
        <Modal
          title="Gerir localizações"
          onClose={() => setLocationManagementOpen(false)}
          footer={<button type="button" className="btn" onClick={() => setLocationManagementOpen(false)}>Fechar</button>}
        >
          <div className="cluster" style={{ justifyContent: "space-between", marginBottom: 16 }}>
            <p className="small muted">Cada proprietário (Solcor e Verde Milenar) mantém a sua localização central ativa.</p>
            <button type="button" className="btn" onClick={() => setLocationForm({ location: null, centralOnly: false })}>
              <Icon name="plus" size={16} /> Nova localização
            </button>
          </div>
          {locations === null ? (
            <LoadingState label="A carregar localizações…" rows={3} />
          ) : locations.length === 0 ? (
            <EmptyState
              icon="mapPin"
              title="Nenhuma localização registada"
              text={`Crie a localização central de ${owner === "solcor" ? "Solcor" : "Verde Milenar"} antes de registar stock.`}
              action={<button type="button" className="btn" onClick={() => setLocationForm({ location: null, centralOnly: true })}>Criar localização central</button>}
            />
          ) : (
            <>
              {!centralLocation && (
                <Alert
                  tone="danger"
                  action={<button type="button" className="btn btn--sm" onClick={() => setLocationForm({ location: null, centralOnly: true })}>Criar central para {owner === "solcor" ? "Solcor" : "Verde Milenar"}</button>}
                >
                  Não existe exatamente uma localização central ativa para {owner === "solcor" ? "Solcor" : "Verde Milenar"}. O stock inicial fica bloqueado até esta situação ser corrigida.
                </Alert>
              )}
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Localizações de inventário</caption>
                  <thead>
                    <tr>
                      <th scope="col">Localização</th>
                      <th scope="col">Código</th>
                      <th scope="col">Tipo</th>
                      <th scope="col">Proprietário</th>
                      <th scope="col">Estado</th>
                      <th scope="col">Ações</th>
                    </tr>
                  </thead>
                  <tbody>
                    {locations.map((location) => (
                      <tr key={location.id}>
                        <td>{location.name}</td>
                        <td className="nowrap muted">{location.code}</td>
                        <td>{LOCATION_TYPE_LABELS[location.location_type] ?? location.location_type}</td>
                        <td>{location.owner === "solcor" ? "Solcor" : "Verde Milenar"}</td>
                        <td>{location.is_active ? <Badge tone="success">Ativa</Badge> : <Badge>Inativa</Badge>}</td>
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
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Modal>
      )}
      {locationForm && (
        <LocationFormModal
          location={locationForm.location}
          centralOnly={locationForm.centralOnly}
          activeOwner={owner}
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
    </div>
  );
}
