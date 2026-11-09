import type { Supplier } from "../api/client";
import { Badge, Modal } from "./ui";

function textOrDash(value: string | null | undefined): string {
  return value?.trim() ? value : "—";
}

export default function SupplierDetailModal({ supplier, onClose }: { supplier: Supplier; onClose: () => void }) {
  return (
    <Modal title={`Detalhe do fornecedor: ${supplier.name}`} onClose={onClose}>
      <div className="stack">
        <section aria-labelledby="supplier-detail-general">
          <h3 id="supplier-detail-general">Dados gerais</h3>
          <dl className="kv">
            <dt>Nome</dt>
            <dd>{supplier.name}</dd>
            <dt>Categoria</dt>
            <dd>{textOrDash(supplier.category)}</dd>
            <dt>Contacto geral</dt>
            <dd>{textOrDash(supplier.contact)}</dd>
            <dt>Telefone</dt>
            <dd>
              {supplier.phone ? <a href={`tel:${supplier.phone.replace(/[^\d+]/g, "")}`}>{supplier.phone}</a> : "—"}
            </dd>
            <dt>Email</dt>
            <dd>{supplier.email ? <a href={`mailto:${supplier.email}`}>{supplier.email}</a> : "—"}</dd>
            <dt>Website</dt>
            <dd>
              {supplier.website ? (
                <a href={supplier.website} target="_blank" rel="noreferrer noopener">
                  {supplier.website}
                </a>
              ) : (
                "—"
              )}
            </dd>
            <dt>Localização</dt>
            <dd>{textOrDash(supplier.address)}</dd>
            <dt>Ligação ao mapa</dt>
            <dd>
              {supplier.maps_url ? (
                <a href={supplier.maps_url} target="_blank" rel="noreferrer noopener">
                  Abrir localização
                </a>
              ) : (
                "—"
              )}
            </dd>
            <dt>Prazo habitual</dt>
            <dd>{supplier.lead_time_days === null ? "—" : `${supplier.lead_time_days} dias`}</dd>
            <dt>Situação</dt>
            <dd>{supplier.is_active ? "Ativo" : "Inativo"}</dd>
            <dt>Preferido</dt>
            <dd>{supplier.is_preferred ? "Sim" : "Não"}</dd>
          </dl>
        </section>

        <section aria-labelledby="supplier-detail-types">
          <h3 id="supplier-detail-types">Tipos de material</h3>
          {supplier.material_types.length > 0 ? (
            <div className="badges">
              {supplier.material_types.map((type) => (
                <Badge key={type} tone="info">
                  {type}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="muted">—</p>
          )}
        </section>

        <section aria-labelledby="supplier-detail-materials">
          <h3 id="supplier-detail-materials">Materiais</h3>
          <p style={{ whiteSpace: "pre-wrap" }}>{textOrDash(supplier.materials)}</p>
        </section>

        <section aria-labelledby="supplier-detail-contacts">
          <h3 id="supplier-detail-contacts">Contactos</h3>
          {supplier.contacts.length > 0 ? (
            <div className="stack">
              {supplier.contacts.map((contact) => (
                <div key={contact.id ?? `${contact.name}-${contact.email ?? ""}`} className="card card--compact">
                  <strong>{contact.name}</strong>
                  {contact.department && <span className="cell-sub">{contact.department}</span>}
                  {contact.phone && (
                    <span className="cell-sub">
                      <a href={`tel:${contact.phone.replace(/[^\d+]/g, "")}`}>{contact.phone}</a>
                    </span>
                  )}
                  {contact.email && (
                    <span className="cell-sub">
                      <a href={`mailto:${contact.email}`}>{contact.email}</a>
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">Sem contactos adicionais.</p>
          )}
        </section>

        <section aria-labelledby="supplier-detail-notes">
          <h3 id="supplier-detail-notes">Notas</h3>
          <p style={{ whiteSpace: "pre-wrap" }}>{textOrDash(supplier.notes)}</p>
        </section>
      </div>
    </Modal>
  );
}
