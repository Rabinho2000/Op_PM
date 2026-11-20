import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import {
  deleteInventoryItemDocument,
  getInventoryItemDocumentBlob,
  InventoryItemDocument,
  InventoryItemDocumentKind,
  listInventoryItemDocuments,
  uploadInventoryItemDocument,
  errorMessage,
} from "../api/client";
import { Alert } from "./ui";
import { formatNumberPt } from "../utils/numbers";

const MAX_DOCUMENT_BYTES = 25 * 1024 * 1024;
const ACCEPTED_DOCUMENT_TYPES = new Set(["application/pdf", "image/jpeg", "image/png", "image/webp"]);
const DOCUMENT_KIND_LABELS: Record<InventoryItemDocumentKind, string> = {
  datasheet: "Datasheets",
  manual: "Manuais",
  guia: "Guias",
  outro: "Outros documentos",
};
const DOCUMENT_KIND_ORDER: InventoryItemDocumentKind[] = ["datasheet", "manual", "guia", "outro"];

function formatDocumentSize(size: number): string {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${formatNumberPt(value, { max: 1 })} ${units[unitIndex]}`;
}

export default function InventoryItemDocuments({
  itemId,
  canManage,
  accountKey,
}: {
  itemId: string;
  canManage: boolean;
  accountKey: string;
}) {
  const [documents, setDocuments] = useState<InventoryItemDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [kind, setKind] = useState<InventoryItemDocumentKind>("datasheet");
  const [title, setTitle] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(false);
  const downloadUrlsRef = useRef(new Map<string, number>());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      for (const [url, timer] of downloadUrlsRef.current) {
        window.clearTimeout(timer);
        URL.revokeObjectURL(url);
      }
      downloadUrlsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(null);
    listInventoryItemDocuments(itemId)
      .then((result) => {
        if (active) setDocuments(result);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(errorMessage(error, "Não foi possível carregar os documentos do artigo."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [itemId, accountKey, refreshToken]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    setOperationError(null);
    setSelectedFile(null);
    if (!file) return;
    if (file.size > MAX_DOCUMENT_BYTES) {
      setOperationError("O documento excede o limite de 25 MB.");
      return;
    }
    if (!ACCEPTED_DOCUMENT_TYPES.has(file.type)) {
      setOperationError("Formato inválido. Utilize PDF, JPEG, PNG ou WebP.");
      return;
    }
    setSelectedFile(file);
  }

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !selectedFile) return;
    if (!title.trim()) {
      setOperationError("Indique um título para o documento.");
      return;
    }
    setBusy(true);
    setOperationError(null);
    try {
      await uploadInventoryItemDocument(itemId, kind, title.trim(), selectedFile);
      if (!mountedRef.current) return;
      setTitle("");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setRefreshToken((value) => value + 1);
    } catch (error) {
      if (mountedRef.current) {
        setOperationError(errorMessage(error, "Não foi possível guardar o documento."));
      }
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }

  async function downloadDocument(document: InventoryItemDocument) {
    setOperationError(null);
    setDownloadingId(document.id);
    try {
      const blob = await getInventoryItemDocumentBlob(itemId, document.id);
      if (!mountedRef.current) return;
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = document.filename || document.title;
      anchor.rel = "noopener";
      anchor.style.display = "none";
      window.document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      const timer = window.setTimeout(() => {
        const activeTimer = downloadUrlsRef.current.get(url);
        if (activeTimer !== undefined) {
          downloadUrlsRef.current.delete(url);
          URL.revokeObjectURL(url);
        }
      }, 1000);
      downloadUrlsRef.current.set(url, timer);
    } catch (error) {
      if (mountedRef.current) {
        setOperationError(errorMessage(error, "Não foi possível descarregar o documento."));
      }
    } finally {
      if (mountedRef.current) setDownloadingId(null);
    }
  }

  async function removeDocument(document: InventoryItemDocument) {
    if (!canManage || !window.confirm(`Remover «${document.title}» da lista de documentos?`)) return;
    setOperationError(null);
    setRemovingId(document.id);
    try {
      await deleteInventoryItemDocument(itemId, document.id);
      if (!mountedRef.current) return;
      setDocuments((current) => current.filter((entry) => entry.id !== document.id));
      setRefreshToken((value) => value + 1);
    } catch (error) {
      if (mountedRef.current) {
        setOperationError(errorMessage(error, "Não foi possível remover o documento."));
      }
    } finally {
      if (mountedRef.current) setRemovingId(null);
    }
  }

  const groupedDocuments = DOCUMENT_KIND_ORDER
    .map((documentKind) => ({
      kind: documentKind,
      entries: documents.filter((document) => document.kind === documentKind),
    }))
    .filter((group) => group.entries.length > 0);

  return <section className="inventory-item-documents" aria-labelledby="inventory-item-documents-title">
    <h3 id="inventory-item-documents-title">Documentos</h3>
    {operationError && <Alert tone="danger">{operationError}</Alert>}
    {loadError && <Alert tone="danger">{loadError}</Alert>}
    {loading && documents.length === 0 && !loadError && <p role="status">A carregar documentos…</p>}
    {loading && documents.length > 0 && <p role="status">A atualizar documentos…</p>}
    {!loading && !loadError && documents.length === 0 && (
      <p className="muted">Ainda não há documentos associados a este artigo.</p>
    )}
    {groupedDocuments.map((group) => <section key={group.kind} className="inventory-item-documents__group">
      <h4>{DOCUMENT_KIND_LABELS[group.kind]}</h4>
      <ul>
        {group.entries.map((document) => <li key={document.id} className="inventory-item-documents__entry">
          <div className="inventory-item-documents__meta">
            <strong>{document.title}</strong>
            <span className="muted">{document.filename} · {formatDocumentSize(document.size)}</span>
            <time className="small muted" dateTime={document.created_at}>
              {new Date(document.created_at).toLocaleDateString("pt-PT")}
            </time>
          </div>
          <div className="cluster">
            <button
              type="button"
              className="btn btn--sm"
              style={{ minHeight: 44 }}
              onClick={() => void downloadDocument(document)}
              disabled={downloadingId === document.id}
            >
              {downloadingId === document.id ? "A preparar…" : `Descarregar ${document.title}`}
            </button>
            {canManage && <button
              type="button"
              className="btn btn--sm btn--danger"
              style={{ minHeight: 44 }}
              onClick={() => void removeDocument(document)}
              disabled={removingId === document.id}
            >
              {removingId === document.id ? "A remover…" : `Remover ${document.title}`}
            </button>}
          </div>
        </li>)}
      </ul>
    </section>)}
    {canManage && <form className="inventory-item-documents__form" onSubmit={uploadDocument}>
      <h4>Adicionar documento</h4>
      <div className="form-grid">
        <div className="field">
          <label htmlFor={`inventory-document-kind-${itemId}`}>Tipo de documento</label>
          <select
            id={`inventory-document-kind-${itemId}`}
            className="select"
            style={{ minHeight: 44 }}
            value={kind}
            onChange={(event) => setKind(event.target.value as InventoryItemDocumentKind)}
            disabled={busy}
          >
            <option value="datasheet">Datasheet</option>
            <option value="manual">Manual</option>
            <option value="guia">Guia</option>
            <option value="outro">Outro</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`inventory-document-title-${itemId}`}>Título do documento</label>
          <input
            id={`inventory-document-title-${itemId}`}
            className="input"
            style={{ minHeight: 44 }}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={256}
            required
            disabled={busy}
          />
        </div>
        <div className="field span-2">
          <label htmlFor={`inventory-document-file-${itemId}`}>Ficheiro do documento</label>
          <input
            ref={fileInputRef}
            id={`inventory-document-file-${itemId}`}
            className="input"
            style={{ minHeight: 44 }}
            type="file"
            accept="application/pdf,image/jpeg,image/png,image/webp,.pdf"
            onChange={handleFileChange}
            disabled={busy}
          />
          <span className="field__hint">PDF, JPEG, PNG ou WebP · máximo 25 MB</span>
        </div>
      </div>
      <button
        type="submit"
        className="btn btn--primary"
        style={{ minHeight: 44 }}
        disabled={busy || !selectedFile || !title.trim()}
      >
        {busy ? "A guardar…" : "Adicionar documento"}
      </button>
    </form>}
  </section>;
}
