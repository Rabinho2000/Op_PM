import { ChangeEvent, useEffect, useRef, useState } from "react";
import { ApiError, deleteProjectPhoto, getProjectPhotoBlob, uploadProjectPhoto } from "../api/client";
import { Alert, Card, EmptyState } from "./ui";

const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
const ACCEPTED_PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export default function ProjectPrimaryPhoto({
  projectId,
  hasPhoto,
  canEdit,
  onPhotoChanged,
}: {
  projectId: string;
  hasPhoto: boolean;
  canEdit: boolean;
  onPhotoChanged?: (hasPhoto: boolean) => void;
}) {
  const [hasPhotoLocal, setHasPhotoLocal] = useState(hasPhoto);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setHasPhotoLocal(hasPhoto);
  }, [hasPhoto]);

  useEffect(() => {
    let active = true;
    let createdUrl: string | null = null;
    if (!hasPhotoLocal) {
      setPhotoUrl(null);
      return () => {
        active = false;
      };
    }
    getProjectPhotoBlob(projectId)
      .then((blob) => {
        if (!active) return;
        createdUrl = URL.createObjectURL(blob);
        setPhotoUrl(createdUrl);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof ApiError ? err.detail : "Não foi possível carregar a fotografia.");
      });
    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [projectId, hasPhotoLocal, refreshToken]);

  useEffect(() => {
    if (!selectedFile) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(selectedFile);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [selectedFile]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    setError(null);
    setSelectedFile(null);
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      setError("A fotografia excede o limite de 10 MB.");
      return;
    }
    if (!ACCEPTED_PHOTO_TYPES.has(file.type)) {
      setError("Formato inválido. Utilize JPEG, PNG ou WebP.");
      return;
    }
    setSelectedFile(file);
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setBusy(true);
    setError(null);
    try {
      await uploadProjectPhoto(projectId, selectedFile);
      setSelectedFile(null);
      setHasPhotoLocal(true);
      setRefreshToken((value) => value + 1);
      onPhotoChanged?.(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar a fotografia.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    setError(null);
    try {
      await deleteProjectPhoto(projectId);
      setSelectedFile(null);
      setHasPhotoLocal(false);
      onPhotoChanged?.(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível remover a fotografia.");
    } finally {
      setBusy(false);
    }
  }

  const visiblePhotoUrl = previewUrl ?? photoUrl;

  return (
    <Card title="Fotografia principal" icon="camera">
      {error && <Alert tone="danger">{error}</Alert>}
      {visiblePhotoUrl ? (
        <img
          src={visiblePhotoUrl}
          alt={previewUrl ? "Pré-visualização da fotografia principal" : "Fotografia principal da instalação"}
          style={{ display: "block", width: "100%", maxHeight: 420, objectFit: "contain", borderRadius: 8 }}
        />
      ) : (
        <EmptyState compact icon="camera" title={hasPhotoLocal ? "A carregar fotografia…" : "Sem fotografia principal."} />
      )}
      {canEdit && (
        <div className="cluster" style={{ marginTop: 12 }}>
          <input
            ref={inputRef}
            aria-label="Selecionar fotografia"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleFileChange}
            style={{ display: "none" }}
          />
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            {hasPhotoLocal ? "Substituir fotografia" : "Carregar fotografia"}
          </button>
          {selectedFile && (
            <button type="button" className="btn btn--sm btn--primary" onClick={handleUpload} disabled={busy}>
              {busy ? "A guardar…" : "Guardar fotografia"}
            </button>
          )}
          {hasPhotoLocal && (
            <button type="button" className="btn btn--sm btn--danger" onClick={handleDelete} disabled={busy}>
              Remover fotografia
            </button>
          )}
          <span className="small muted">JPEG, PNG ou WebP · máximo 10 MB</span>
        </div>
      )}
    </Card>
  );
}
