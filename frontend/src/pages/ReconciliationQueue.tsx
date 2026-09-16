import { useEffect, useState } from "react";
import {
  ApiError,
  listPeople,
  listReconciliationItems,
  Person,
  PersonReconciliationItem,
  resolveReconciliationItem,
} from "../api/client";
import { useToast } from "../components/Toast";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";

export default function ReconciliationQueue() {
  const [items, setItems] = useState<PersonReconciliationItem[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [linkTarget, setLinkTarget] = useState<Record<string, string>>({});
  const { notify } = useToast();

  function load() {
    setError(null);
    listReconciliationItems("pending")
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
  }

  useEffect(load, []);
  useEffect(() => {
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
  }, []);

  async function handleResolve(
    id: string,
    action: "link_existing" | "create_new" | "ignore"
  ) {
    setBusyId(id);
    try {
      if (action === "link_existing") {
        const targetId = linkTarget[id];
        if (!targetId) {
          notify("Escolha uma pessoa para ligar.", "error");
          return;
        }
        await resolveReconciliationItem(id, { action, target_person_id: targetId });
      } else {
        await resolveReconciliationItem(id, { action });
      }
      notify("Item resolvido.", "success");
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.detail : String(e), "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Reconciliação de PM"
        subtitle="Nomes de PM do export legado que não correspondem, sem ambiguidade, a uma pessoa conhecida. Nenhum projeto com um destes nomes é promovido enquanto o item não for resolvido (D-023)."
      />

      <div className="card">
        {error && <ErrorState message={error} onRetry={load} />}
        {items === null && !error && <LoadingState />}
        {items && items.length === 0 && (
          <EmptyState title="Sem itens pendentes" text="Todos os nomes de PM importados estão reconciliados." />
        )}
        {items && items.length > 0 && (
          <ul className="list">
            {items.map((item) => (
              <li key={item.id} className="list__item" style={{ flexWrap: "wrap" }}>
                <div className="list__main">
                  <span className="list__title">{item.raw_name}</span>
                  <Badge tone="warning">{item.reason === "ambiguous" ? "nome ambíguo" : "nome desconhecido"}</Badge>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <label htmlFor={`link-${item.id}`} className="sr-only">
                    Pessoa a ligar a {item.raw_name}
                  </label>
                  <select
                    id={`link-${item.id}`}
                    className="select select--compact"
                    value={linkTarget[item.id] ?? ""}
                    onChange={(e) => setLinkTarget({ ...linkTarget, [item.id]: e.target.value })}
                  >
                    <option value="">Ligar a pessoa existente…</option>
                    {people.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.display_name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn--sm btn--primary"
                    disabled={busyId === item.id}
                    onClick={() => handleResolve(item.id, "link_existing")}
                  >
                    Ligar
                  </button>
                  <button
                    type="button"
                    className="btn btn--sm"
                    disabled={busyId === item.id}
                    onClick={() => handleResolve(item.id, "create_new")}
                  >
                    Criar pessoa (sem login)
                  </button>
                  <button
                    type="button"
                    className="btn btn--sm btn--ghost"
                    disabled={busyId === item.id}
                    onClick={() => handleResolve(item.id, "ignore")}
                  >
                    Ignorar (sem PM)
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
