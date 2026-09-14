import { useEffect, useState } from "react";
import {
  ApiError,
  listPeople,
  listReconciliationItems,
  Person,
  PersonReconciliationItem,
  resolveReconciliationItem,
} from "../api/client";

export default function ReconciliationQueue() {
  const [items, setItems] = useState<PersonReconciliationItem[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [linkTarget, setLinkTarget] = useState<Record<string, string>>({});

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
          window.alert("Escolha uma pessoa para ligar.");
          return;
        }
        await resolveReconciliationItem(id, { action, target_person_id: targetId });
      } else {
        await resolveReconciliationItem(id, { action });
      }
      load();
    } catch (e) {
      window.alert(e instanceof ApiError ? `${e.status}: ${e.detail}` : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem", maxWidth: 900 }}>
      <h1>Reconciliação de PM</h1>
      <p style={{ color: "#666" }}>
        Nomes de PM do export legado que não correspondem, sem ambiguidade, a
        uma pessoa já conhecida. Nenhum projeto com um destes nomes é
        promovido enquanto o item correspondente aqui não for resolvido (ver
        docs/DECISIONS.md D-023).
      </p>

      {error && <p style={{ color: "crimson" }}>Erro: {error}</p>}
      {items === null && !error && <p>A carregar…</p>}
      {items && items.length === 0 && <p>Sem itens pendentes.</p>}

      {items &&
        items.map((item) => (
          <div
            key={item.id}
            style={{ border: "1px solid #ddd", borderRadius: 6, padding: "1rem", marginBottom: "1rem" }}
          >
            <strong>{item.raw_name}</strong>{" "}
            <span style={{ color: "#888", fontSize: "0.85rem" }}>
              ({item.reason === "ambiguous" ? "nome ambíguo" : "nome desconhecido"})
            </span>

            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.6rem", flexWrap: "wrap" }}>
              <select
                value={linkTarget[item.id] ?? ""}
                onChange={(e) => setLinkTarget({ ...linkTarget, [item.id]: e.target.value })}
                style={{ padding: "0.35rem" }}
              >
                <option value="">Ligar a pessoa existente…</option>
                {people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
              <button disabled={busyId === item.id} onClick={() => handleResolve(item.id, "link_existing")}>
                Ligar
              </button>
              <button disabled={busyId === item.id} onClick={() => handleResolve(item.id, "create_new")}>
                Criar pessoa nova (sem login)
              </button>
              <button disabled={busyId === item.id} onClick={() => handleResolve(item.id, "ignore")}>
                Ignorar (sem PM)
              </button>
            </div>
          </div>
        ))}
    </div>
  );
}
