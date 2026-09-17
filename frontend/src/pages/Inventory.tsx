// Inventário central da IdealMinde — livro de movimentos, nunca um total
// editável diretamente (ver docs/INVENTORY_RULES.md). Reservas/consumo por
// projeto vivem em /api/projects/{id}/inventory; esta página cobre o stock
// central e o histórico de movimentos (a UI por projeto fica para uma fase
// seguinte — ver docs/OPEN_QUESTIONS.md).
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createCentralMovement,
  InventoryItem,
  InventoryMovement,
  listInventoryItems,
  listInventoryMovements,
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

function RegisterMovementModal({ items, onClose, onDone }: { items: InventoryItem[]; onClose: () => void; onDone: () => void }) {
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
      setError("Indique o item e a quantidade.");
      return;
    }
    setSaving(true);
    try {
      await createCentralMovement({ item_id: itemId, movement_type: movementType, quantity, reference });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível registar o movimento.");
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
          <label htmlFor="m-item">Item</label>
          <select id="m-item" className="select" value={itemId} onChange={(e) => setItemId(e.target.value)}>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} ({i.sku}) — {i.unit}
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

export default function Inventory() {
  const { can } = useSession();
  const { notify } = useToast();
  const [items, setItems] = useState<InventoryItem[] | null>(null);
  const [movements, setMovements] = useState<InventoryMovement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);

  const canManageCentral = can("inventory.manage_central");

  const load = useCallback(() => {
    setError(null);
    listInventoryItems()
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    listInventoryMovements()
      .then(setMovements)
      .catch(() => setMovements([]));
  }, []);

  useEffect(load, [load]);

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
        subtitle="Stock central da IdealMinde, calculado a partir do livro de movimentos — reservas e consumo por projeto ficam no detalhe de cada projeto."
        actions={
          canManageCentral && (
            <button type="button" className="btn btn--primary" onClick={() => setRegistering(true)} disabled={!items?.length}>
              <Icon name="plus" size={16} /> Registar movimento
            </button>
          )
        }
      />

      <Card title="Stock central" icon="database" flush>
        {items === null ? (
          <LoadingState rows={4} />
        ) : items.length === 0 ? (
          <EmptyState icon="database" title="Sem itens de inventário ainda." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Stock central por item</caption>
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">SKU</th>
                  <th scope="col">Físico</th>
                  <th scope="col">Reservado</th>
                  <th scope="col">Disponível</th>
                  <th scope="col">Mínimo</th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}</td>
                    <td className="nowrap muted">{item.sku}</td>
                    <td className="nowrap">
                      {item.physical_stock} {item.unit}
                    </td>
                    <td className="nowrap">
                      {item.total_reserved} {item.unit}
                    </td>
                    <td className="nowrap">
                      {item.available_stock} {item.unit}
                    </td>
                    <td className="nowrap muted">
                      {item.min_stock} {item.unit}
                    </td>
                    <td>
                      {item.below_min_stock ? (
                        <Badge tone="danger" dot>
                          Abaixo do mínimo
                        </Badge>
                      ) : (
                        <Badge tone="success" dot>
                          OK
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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
                    <th scope="col">Item</th>
                    <th scope="col">Tipo</th>
                    <th scope="col">Quantidade</th>
                    <th scope="col">Projeto</th>
                    <th scope="col">Referência</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.slice(0, 30).map((m) => (
                    <tr key={m.id}>
                      <td className="nowrap muted">{new Date(m.created_at).toLocaleString("pt-PT")}</td>
                      <td>{m.item_name ?? "—"}</td>
                      <td>
                        <Badge tone="neutral">{MOVEMENT_TYPE_LABELS[m.movement_type] ?? m.movement_type}</Badge>
                      </td>
                      <td className="nowrap">{m.quantity}</td>
                      <td>{m.project_name ?? <span className="muted">—</span>}</td>
                      <td>{m.reference || <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {registering && items && (
        <RegisterMovementModal
          items={items}
          onClose={() => setRegistering(false)}
          onDone={() => {
            setRegistering(false);
            notify("Movimento registado.", "success");
            load();
          }}
        />
      )}
    </>
  );
}
