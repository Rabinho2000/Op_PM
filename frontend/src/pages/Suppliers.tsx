import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listSupplierMaterialTypes, listSuppliers, Supplier, SupplierFilters, SupplierMaterialType } from "../api/client";
import Icon from "../components/Icon";
import SupplierFormModal from "../components/SupplierForm";
import { useToast } from "../components/Toast";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";

type ActiveFilter = "active" | "inactive" | "all";

interface Filters {
  search: string;
  materialType: string;
  active: ActiveFilter;
}

const EMPTY_FILTERS: Filters = { search: "", materialType: "", active: "active" };

// Os filtros são aplicados pelo servidor (GET /api/suppliers).
export function toApiFilters(f: Filters): SupplierFilters {
  return {
    q: f.search.trim() || undefined,
    material_type: f.materialType || undefined,
    is_active: f.active === "all" ? undefined : f.active === "active",
  };
}

export default function Suppliers() {
  const { can } = useSession();
  const { notify } = useToast();
  const canManage = can("supplier.manage");

  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [suppliers, setSuppliers] = useState<Supplier[] | null>(null);
  const [types, setTypes] = useState<SupplierMaterialType[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState<Supplier | "new" | null>(null);

  useEffect(() => {
    listSupplierMaterialTypes()
      .then(setTypes)
      .catch(() => setTypes([]));
  }, [reloadKey]);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(filters.search), 250);
    return () => window.clearTimeout(handle);
  }, [filters.search]);

  const { materialType, active } = filters;
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setSuppliers(null);
    listSuppliers(toApiFilters({ search: debouncedSearch, materialType, active }))
      .then((result) => !cancelled && setSuppliers(result))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch, materialType, active, reloadKey]);

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const hasFilters = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);
  const knownTypeNames = useMemo(() => types.map((t) => t.name), [types]);

  return (
    <>
      <PageHeader
        title="Fornecedores"
        subtitle="Contactos, materiais e localização dos fornecedores."
        actions={
          canManage && (
            <button type="button" className="btn btn--primary" onClick={() => setEditing("new")}>
              <Icon name="plus" size={16} /> Novo fornecedor
            </button>
          )
        }
      />

      <form className="toolbar" role="search" aria-label="Filtros de fornecedores" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--wide">
          <label htmlFor="s-search">Pesquisar</label>
          <div className="search">
            <Icon name="search" size={16} />
            <input
              id="s-search"
              className="input"
              type="search"
              placeholder="Nome, material, localização ou email…"
              value={filters.search}
              onChange={(e) => set("search", e.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="s-type">Tipo de material</label>
          <select id="s-type" className="select" value={filters.materialType} onChange={(e) => set("materialType", e.target.value)}>
            <option value="">Todos os tipos</option>
            {types.map((t) => (
              <option key={t.id} value={t.name}>
                {t.name} ({t.active_suppliers})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="s-active">Situação</label>
          <select id="s-active" className="select" value={filters.active} onChange={(e) => set("active", e.target.value as ActiveFilter)}>
            <option value="active">Ativos</option>
            <option value="inactive">Inativos</option>
            <option value="all">Todos</option>
          </select>
        </div>
        {hasFilters && (
          <div className="toolbar__end">
            <button type="button" className="btn btn--ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
              <Icon name="x" size={16} /> Limpar filtros
            </button>
          </div>
        )}
      </form>

      <div className="card">
        {error && <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
        {!error && suppliers === null && <LoadingState label="A carregar fornecedores…" rows={5} />}
        {!error && suppliers?.length === 0 && (
          <EmptyState
            icon="folder"
            title="Nenhum fornecedor encontrado"
            text={hasFilters ? "Nenhum fornecedor corresponde aos filtros escolhidos." : "Ainda não há fornecedores registados."}
            action={
              hasFilters ? (
                <button type="button" className="btn btn--sm" onClick={() => setFilters(EMPTY_FILTERS)}>
                  Limpar filtros
                </button>
              ) : undefined
            }
          />
        )}
        {!error && suppliers && suppliers.length > 0 && (
          <>
            <div className="card__header" style={{ paddingBottom: 12 }}>
              <span className="small muted" aria-live="polite">
                {suppliers.length} fornecedor{suppliers.length === 1 ? "" : "es"}
              </span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Lista de fornecedores</caption>
                <thead>
                  <tr>
                    <th scope="col" className="col-main">Fornecedor</th>
                    <th scope="col">Tipos de material</th>
                    <th scope="col">Telefone</th>
                    <th scope="col">Email</th>
                    <th scope="col">Localização</th>
                    {canManage && <th scope="col">Ações</th>}
                  </tr>
                </thead>
                <tbody>
                  {suppliers.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <span className="cell-title">{s.name}</span>
                        <span className="cell-sub">
                          {s.website && (
                            <a href={s.website} target="_blank" rel="noreferrer noopener">
                              {s.website.replace(/^https?:\/\//i, "").replace(/\/$/, "")}
                            </a>
                          )}
                          {s.contact && <> {s.website ? "· " : ""}{s.contact}</>}
                        </span>
                        {!s.is_active && (
                          <div style={{ marginTop: 4 }}>
                            <Badge>Inativo</Badge>
                          </div>
                        )}
                      </td>
                      <td>
                        {s.material_types.length > 0 ? (
                          <div className="badges">
                            {s.material_types.map((t) => (
                              <Badge key={t} tone="info">
                                {t}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="nowrap">
                        {s.phone ? <a href={`tel:${s.phone.replace(/[^\d+]/g, "")}`}>{s.phone}</a> : <span className="muted">—</span>}
                      </td>
                      <td>{s.email ? <a href={`mailto:${s.email}`}>{s.email}</a> : <span className="muted">—</span>}</td>
                      <td>
                        {s.address ? <span>{s.address}</span> : <span className="muted">—</span>}
                        {s.lat !== null && s.lon !== null && (
                          <span className="cell-sub">
                            <Link to="/map">Ver no mapa</Link>
                          </span>
                        )}
                      </td>
                      {canManage && (
                        <td>
                          <button type="button" className="btn btn--sm" onClick={() => setEditing(s)} aria-label={`Editar ${s.name}`}>
                            Editar
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {editing !== null && (
        <SupplierFormModal
          supplier={editing === "new" ? null : editing}
          knownTypes={knownTypeNames}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            notify(editing === "new" ? `Fornecedor «${saved.name}» criado.` : `Fornecedor «${saved.name}» atualizado.`);
            setEditing(null);
            setReloadKey((k) => k + 1);
          }}
        />
      )}
    </>
  );
}
