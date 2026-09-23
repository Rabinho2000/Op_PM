// Importação de notas iniciais: arrastar HTML/JSON -> preview -> conflitos
// -> confirmação -> criação/atualização do projeto. Ver
// docs/DATA_IMPORTS.md. Toda a validação/staging acontece no backend —
// esta página só apresenta o que a API já calculou.
import { DragEvent, useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  applyNotesImport,
  FieldImportBatch,
  FieldImportConflict,
  getImportBatch,
  previewNotesImport,
  resolveImportConflict,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, PageHeader } from "../components/ui";

const FIELD_LABELS: Record<string, string> = {
  client_name: "Cliente",
  client_contact: "Contacto",
  client_email: "Email",
  address: "Morada",
  lat: "Latitude",
  lon: "Longitude",
  power_kwp: "Potência (kWp)",
  client_nif: "NIF",
  contact_person_name: "Pessoa de contacto",
  contact_person_role: "Função",
  contact_email: "Email de contacto",
  contact_phone: "Telefone",
  district: "Distrito",
  municipality: "Concelho",
  panel_count: "Nº de painéis",
  panel_power_wp: "Potência dos painéis (Wp)",
  inverters: "Inversores",
  batteries: "Baterias",
  has_backup: "Backup",
  ev_chargers: "Carregadores VE",
  installation_type: "Tipo de instalação",
  injection_type: "Injeção",
  om_notes: "O&M",
  notes: "Notas",
  upac_number: "Nº UPAC",
};

function fieldLabel(name: string): string {
  return FIELD_LABELS[name] ?? name;
}

function MappedFieldsPreview({ mapped }: { mapped: FieldImportBatch["records"][number]["mapped_fields"] }) {
  const sections: [string, Record<string, unknown> | undefined][] = [
    ["Projeto", mapped.project],
    ["Instalação", mapped.installation],
    ["Licenciamento", mapped.licensing],
  ];
  return (
    <div className="grid">
      {sections
        .filter(([, fields]) => fields && Object.keys(fields).length > 0)
        .map(([title, fields]) => (
          <div key={title}>
            <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>{title}</h3>
            <ul className="list">
              {Object.entries(fields ?? {}).map(([key, value]) => (
                <li key={key} className="list__item">
                  <span className="list__main">
                    <span className="list__title">{fieldLabel(key)}</span>
                    <div className="list__meta">{String(value)}</div>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  );
}

function ConflictRow({
  conflict,
  onResolve,
}: {
  conflict: FieldImportConflict;
  onResolve: (conflictId: string, resolution: "use_new" | "keep_old") => void;
}) {
  return (
    <li className="list__item" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span className="list__title">{fieldLabel(conflict.field_name)}</span>
        {conflict.resolution === "pending" ? (
          <Badge tone="warning">Por resolver</Badge>
        ) : (
          <Badge tone="success">{conflict.resolution === "use_new" ? "Usar novo valor" : "Manter valor atual"}</Badge>
        )}
      </div>
      <div className="small muted">
        Valor atual: {conflict.old_value ?? "—"} · Valor novo: {conflict.new_value ?? "—"}
      </div>
      {conflict.resolution === "pending" && (
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn btn--sm" onClick={() => onResolve(conflict.id, "keep_old")}>
            Manter atual
          </button>
          <button
            type="button"
            className="btn btn--sm btn--primary"
            onClick={() => onResolve(conflict.id, "use_new")}
          >
            Usar novo
          </button>
        </div>
      )}
    </li>
  );
}

export default function ImportNotes() {
  const { notify } = useToast();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<FieldImportBatch | null>(null);
  const [applying, setApplying] = useState(false);

  const record = batch?.records[0] ?? null;
  const pendingConflicts = record?.conflicts.filter((c) => c.resolution === "pending") ?? [];
  const allResolved = pendingConflicts.length === 0;

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    setUploading(true);
    try {
      const result = await previewNotesImport(file);
      setBatch(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível processar o ficheiro.");
    } finally {
      setUploading(false);
    }
  }, []);

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  }

  async function refreshBatch() {
    if (!batch) return;
    const updated = await getImportBatch(batch.id);
    setBatch(updated);
  }

  async function handleResolve(conflictId: string, resolution: "use_new" | "keep_old") {
    try {
      await resolveImportConflict(conflictId, resolution);
      await refreshBatch();
    } catch (err) {
      notify(err instanceof ApiError ? err.detail : "Não foi possível resolver o conflito.", "error");
    }
  }

  async function handleApply() {
    if (!batch) return;
    setApplying(true);
    try {
      const result = await applyNotesImport(batch.id);
      notify(
        result.created_new_project ? "Projeto criado a partir das notas iniciais." : "Projeto atualizado a partir das notas iniciais.",
        "success"
      );
      navigate(`/projects/${result.project_id}`);
    } catch (err) {
      notify(err instanceof ApiError ? err.detail : "Não foi possível aplicar a importação.", "error");
    } finally {
      setApplying(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Importar notas iniciais"
        subtitle="Arraste o HTML ou JSON exportado pelo formulário de notas iniciais para pré-visualizar e confirmar a criação/atualização do projeto."
      />

      {!batch && (
        <Card title="1. Carregar ficheiro" icon="database">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            style={{
              border: `2px dashed ${dragging ? "var(--color-brand, #2f7d4f)" : "var(--color-border, #ccc)"}`,
              borderRadius: 12,
              padding: "48px 24px",
              textAlign: "center",
              cursor: "pointer",
              background: dragging ? "rgba(47,125,79,0.06)" : "transparent",
            }}
          >
            <Icon name="database" size={32} />
            <p style={{ margin: "12px 0 4px", fontWeight: 600 }}>
              {uploading ? "A processar…" : "Arraste aqui o ficheiro .html ou .json, ou clique para escolher"}
            </p>
            <p className="small muted" style={{ margin: 0 }}>
              Aceita o HTML exportado pelo formulário (com dados estruturados embutidos) ou o JSON gerado por ele.
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".html,.htm,.json"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleFile(file);
                e.target.value = "";
              }}
            />
          </div>
          {error && (
            <div style={{ marginTop: 16 }}>
              <Alert tone="danger">{error}</Alert>
            </div>
          )}
        </Card>
      )}

      {batch && record && (
        <>
          <Card
            title="2. Pré-visualização"
            icon="database"
            actions={
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => {
                  setBatch(null);
                  setError(null);
                }}
              >
                Escolher outro ficheiro
              </button>
            }
          >
            <p className="small muted">
              Ficheiro: <strong>{batch.source_filename}</strong> · Versão do formulário:{" "}
              <strong>{batch.form_version}</strong>
            </p>
            {record.is_new_project ? (
              <Alert tone="info">Nenhum projeto correspondente encontrado — será criado um novo projeto.</Alert>
            ) : record.match_strategy === "ambiguous" ? (
              <Alert tone="warning">
                Vários projetos correspondem a estes dados ({record.candidate_projects.length}) — escolha manualmente
                antes de confirmar (funcionalidade de seleção de candidato ainda por implementar nesta página;
                resolva os conflitos abaixo e contacte o administrador se precisar de escolher outro projeto).
              </Alert>
            ) : (
              <Alert tone="info">
                Projeto existente encontrado (correspondência por {record.match_strategy}) — os dados serão
                atualizados.
              </Alert>
            )}
            <MappedFieldsPreview mapped={record.mapped_fields} />
          </Card>

          {record.conflicts.length > 0 && (
            <div className="section-gap">
              <Card title="3. Conflitos a resolver" icon="alert" tone="warning" flush>
                <ul className="list">
                  {record.conflicts.map((c) => (
                    <ConflictRow key={c.id} conflict={c} onResolve={handleResolve} />
                  ))}
                </ul>
              </Card>
            </div>
          )}

          <div className="section-gap card" style={{ padding: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}>
            {!allResolved && <span className="small muted" style={{ alignSelf: "center" }}>Resolva todos os conflitos para poder confirmar.</span>}
            <button
              type="button"
              className="btn btn--primary"
              disabled={!allResolved || applying || batch.status !== "pending_confirmation"}
              onClick={handleApply}
            >
              {applying ? "A confirmar…" : "Confirmar e importar"}
            </button>
          </div>
        </>
      )}
    </>
  );
}
