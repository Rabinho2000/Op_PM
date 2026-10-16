import { FormEvent, useState } from "react";
import { ApiError, createSupplier, Supplier, SupplierContact, SupplierInput, updateSupplier } from "../api/client";
import { Alert, Modal } from "./ui";

// Mesmas regras do servidor (app/schemas/suppliers.py) — só para dar resposta
// imediata; o servidor volta sempre a validar.
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
const PHONE_RE = /^\+?[\d\s().-]+$/;

export function validateContact(c: SupplierContact, position: number): string | null {
  const who = `Contacto ${position}`;
  if (!c.name.trim()) return `${who}: indique o nome (ou "Geral").`;
  if (c.email?.trim() && !EMAIL_RE.test(c.email.trim())) return `${who}: o email não parece válido.`;
  if (c.phone?.trim()) {
    const digits = (c.phone.match(/\d/g) ?? []).length;
    if (!PHONE_RE.test(c.phone.trim()) || digits < 6 || digits > 15) return `${who}: telefone inválido.`;
  }
  return null;
}

export function validateSupplierFields(v: { name: string; email: string; phone: string; website: string; maps_url?: string }): string | null {
  if (!v.name.trim()) return "Indique o nome do fornecedor.";
  if (v.email.trim() && !EMAIL_RE.test(v.email.trim())) return "O email não parece válido.";
  if (v.phone.trim()) {
    const digits = (v.phone.match(/\d/g) ?? []).length;
    if (!PHONE_RE.test(v.phone.trim()) || digits < 6 || digits > 15) {
      return "Telefone inválido: use só números, espaços, +, ( ) . e -, com 6 a 15 dígitos.";
    }
  }
  if (v.maps_url?.trim() && !/^https?:\/\/\S+\.\S+$/i.test(v.maps_url.trim())) return "A ligação ao mapa tem de começar por http:// ou https://.";
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
    maps_url: supplier?.maps_url ?? "",
    website: supplier?.website ?? "",
    contact: supplier?.contact ?? "",
    notes: supplier?.notes ?? "",
    is_active: supplier?.is_active ?? true,
  });
  const [types, setTypes] = useState<string[]>(supplier?.material_types ?? []);
  const [contacts, setContacts] = useState<SupplierContact[]>(supplier?.contacts ?? []);
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
    const cleanContacts = contacts
      .filter((c) => c.name.trim() || c.department?.trim() || c.phone?.trim() || c.email?.trim())
      .map((c) => ({
        name: c.name.trim(),
        department: c.department?.trim() || null,
        phone: c.phone?.trim() || null,
        email: c.email?.trim() || null,
      }));
    for (let i = 0; i < cleanContacts.length; i++) {
      const contactProblem = validateContact(cleanContacts[i], i + 1);
      if (contactProblem) {
        setError(contactProblem);
        return;
      }
    }
    // Um tipo escrito e ainda não confirmado com Enter também conta.
    const finalTypes = typeDraft.trim() ? [...types, typeDraft.trim()] : types;
    const payload: Partial<SupplierInput> = {
      name: form.name.trim(),
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      address: form.address.trim() || null,
      maps_url: form.maps_url.trim() || null,
      contacts: cleanContacts,
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
        <div className="field span-2">
          <label htmlFor="sf-maps">Ligação ao mapa (Google Maps…)</label>
          <input id="sf-maps" className="input" placeholder="https://maps.app.goo.gl/…" value={form.maps_url} onChange={(e) => setForm({ ...form, maps_url: e.target.value })} />
        </div>
        <fieldset className="field span-2" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field__label">Contactos (pessoas ou departamentos)</legend>
          {contacts.map((c, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr)) auto", gap: 8, marginBottom: 8 }}>
              <input className="input" aria-label={`Nome do contacto ${i + 1}`} placeholder="Nome" value={c.name} onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input className="input" aria-label={`Departamento do contacto ${i + 1}`} placeholder="Departamento (Comercial…)" value={c.department ?? ""} onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, department: e.target.value } : x)))} />
              <input className="input" type="tel" aria-label={`Telefone do contacto ${i + 1}`} placeholder="Telefone" value={c.phone ?? ""} onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, phone: e.target.value } : x)))} />
              <input className="input" type="email" aria-label={`Email do contacto ${i + 1}`} placeholder="Email" value={c.email ?? ""} onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, email: e.target.value } : x)))} />
              <button type="button" className="btn btn--sm" aria-label={`Remover contacto ${i + 1}`} onClick={() => setContacts(contacts.filter((_, j) => j !== i))}>
                ×
              </button>
            </div>
          ))}
          <div>
            <button type="button" className="btn btn--sm" onClick={() => setContacts([...contacts, { name: "", department: null, phone: null, email: null }])}>
              Adicionar contacto
            </button>
          </div>
        </fieldset>
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
