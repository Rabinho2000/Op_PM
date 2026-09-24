import { FormEvent, useState } from "react";
import { ApiError, createSupplier, Supplier, SupplierInput, updateSupplier } from "../api/client";
import { Alert, Modal } from "./ui";

// Mesmas regras do servidor (app/schemas/suppliers.py) — só para dar resposta
// imediata; o servidor volta sempre a validar.
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
const PHONE_RE = /^\+?[\d\s().-]+$/;

export function validateSupplierFields(v: { name: string; email: string; phone: string; website: string }): string | null {
  if (!v.name.trim()) return "Indique o nome do fornecedor.";
  if (v.email.trim() && !EMAIL_RE.test(v.email.trim())) return "O email não parece válido.";
  if (v.phone.trim()) {
    const digits = (v.phone.match(/\d/g) ?? []).length;
    if (!PHONE_RE.test(v.phone.trim()) || digits < 6 || digits > 15) {
      return "Telefone inválido: use só números, espaços, +, ( ) . e -, com 6 a 15 dígitos.";
    }
  }
  if (v.website.trim() && (/\s/.test(v.website.trim()) || !v.website.includes("."))) return "O endereço do site não parece válido.";
  return null;
}

// Criação e edição de um fornecedor. `knownTypes` alimenta as sugestões de
// tipo de material; um tipo novo escreve-se e cria-se ao guardar.
export default function SupplierFormModal({
  supplier,
  knownTypes,
  onClose,
  onSaved,
}: {
  supplier: Supplier | null;
  knownTypes: string[];
  onClose: () => void;
  onSaved: (supplier: Supplier) => void;
}) {
  const editing = supplier !== null;
  const [form, setForm] = useState({
    name: supplier?.name ?? "",
    phone: supplier?.phone ?? "",
    email: supplier?.email ?? "",
    address: supplier?.address ?? "",
    website: supplier?.website ?? "",
    contact: supplier?.contact ?? "",
    notes: supplier?.notes ?? "",
    is_active: supplier?.is_active ?? true,
  });
  const [types, setTypes] = useState<string[]>(supplier?.material_types ?? []);
  const [typeDraft, setTypeDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function addType(raw: string) {
    const name = raw.trim().replace(/\s+/g, " ");
    if (!name) return;
    if (!types.some((t) => t.toLowerCase() === name.toLowerCase())) setTypes([...types, name]);
    setTypeDraft("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const problem = validateSupplierFields(form);
    if (problem) {
      setError(problem);
      return;
    }
    // Um tipo escrito e ainda não confirmado com Enter também conta.
    const finalTypes = typeDraft.trim() ? [...types, typeDraft.trim()] : types;
    const payload: Partial<SupplierInput> = {
      name: form.name.trim(),
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      address: form.address.trim() || null,
      website: form.website.trim() || null,
      contact: form.contact.trim() || null,
      notes: form.notes.trim(),
      material_types: finalTypes,
    };
    setSaving(true);
    setError(null);
    try {
      const saved = editing
        ? await updateSupplier(supplier.id, { ...payload, is_active: form.is_active })
        : await createSupplier({ ...payload, name: payload.name as string });
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar o fornecedor.");
    } finally {
      setSaving(false);
    }
  }

  const suggestions = knownTypes.filter((t) => !types.some((x) => x.toLowerCase() === t.toLowerCase()));

  return (
    <Modal
      title={editing ? "Editar fornecedor" : "Novo fornecedor"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="supplier-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar fornecedor"}
          </button>
        </>
      }
    >
      <form id="supplier-form" className="form-grid" onSubmit={handleSubmit} noValidate>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="sf-name">Nome *</label>
          <input id="sf-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>

        <div className="field span-2">
          <label htmlFor="sf-type">Tipos de material</label>
          {types.length > 0 && (
            <div className="chips" aria-label="Tipos de material escolhidos">
              {types.map((t) => (
                <span key={t} className="chip chip--on">
                  {t}
                  <button
                    type="button"
                    className="chip__remove"
                    aria-label={`Remover ${t}`}
                    onClick={() => setTypes(types.filter((x) => x !== t))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <input
              id="sf-type"
              className="input"
              list="sf-type-options"
              placeholder="Escreva ou escolha um tipo e prima Enter"
              value={typeDraft}
              onChange={(e) => setTypeDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addType(typeDraft);
                }
              }}
            />
            <button type="button" className="btn" onClick={() => addType(typeDraft)}>
              Adicionar
            </button>
          </div>
          <datalist id="sf-type-options">
            {suggestions.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </div>

        <div className="field">
          <label htmlFor="sf-phone">Telefone</label>
          <input id="sf-phone" className="input" type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="sf-email">Email</label>
          <input id="sf-email" className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="sf-address">Localização (morada)</label>
          <input id="sf-address" className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="sf-website">Site</label>
          <input id="sf-website" className="input" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="sf-contact">Pessoa de contacto</label>
          <input id="sf-contact" className="input" value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} />
        </div>
        <div className="field span-2">
          <label htmlFor="sf-notes">Notas (outros contactos, lojas…)</label>
          <textarea id="sf-notes" className="textarea" rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        {editing && (
          <div className="field span-2">
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 500 }}>
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              />
              Fornecedor ativo (desative em vez de apagar: pode haver pedidos de material ligados)
            </label>
          </div>
        )}
      </form>
    </Modal>
  );
}
