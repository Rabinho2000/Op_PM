import { ChangeEvent, ReactNode, useEffect, useRef, useState } from "react";
import { deleteProjectPhoto, getProjectPhotoBlob, uploadProjectPhoto, errorMessage } from "../api/client";
import { Alert, EmptyState } from "./ui";
import { useAuthenticatedBlob, useObjectUrl } from "../utils/useAuthenticatedBlob";

const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
const ACCEPTED_PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

export default function ProjectPrimaryPhoto({
  projectId,
  hasPhoto,
  canEdit,
  onPhotoChanged,
  children,
}: {
  projectId: string;
  hasPhoto: boolean;
  canEdit: boolean;
  onPhotoChanged?: (hasPhoto: boolean) => void;
  children?: ReactNode;
}) {
  const [hasPhotoLocal, setHasPhotoLocal] = useState(hasPhoto);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestGeneration = useRef(0);
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGeneration.current += 1;
    };
  }, []);

  useEffect(() => {
    requestGeneration.current += 1;
    setSelectedFile(null);
    setError(null);
    setBusy(false);
  }, [projectId]);

  useEffect(() => {
    setHasPhotoLocal(hasPhoto);
  }, [hasPhoto]);

  const photoUrl = useAuthenticatedBlob(
    () => getProjectPhotoBlob(projectId),
    [projectId, refreshToken],
    {
      enabled: hasPhotoLocal,
      onError: (err) => {
        if (mountedRef.current) setError(errorMessage(err, "Não foi possível carregar a fotografia."));
      },
    },
  );
  const previewUrl = useObjectUrl(selectedFile);

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
    const generation = requestGeneration.current;
    setBusy(true);
    setError(null);
    try {
      await uploadProjectPhoto(projectId, selectedFile);
      if (!mountedRef.current || generation !== requestGeneration.current) return;
      setSelectedFile(null);
      setHasPhotoLocal(true);
      setRefreshToken((value) => value + 1);
      onPhotoChanged?.(true);
    } catch (err) {
      if (mountedRef.current && generation === requestGeneration.current) {
        setError(errorMessage(err, "Não foi possível guardar a fotografia."));
      }
    } finally {
      if (mountedRef.current && generation === requestGeneration.current) setBusy(false);
    }
  }

  async function handleDelete() {
    const generation = requestGeneration.current;
    setBusy(true);
    setError(null);
    try {
      await deleteProjectPhoto(projectId);
      if (!mountedRef.current || generation !== requestGeneration.current) return;
      setSelectedFile(null);
      setHasPhotoLocal(false);
      onPhotoChanged?.(false);
    } catch (err) {
      if (mountedRef.current && generation === requestGeneration.current) {
        setError(errorMessage(err, "Não foi possível remover a fotografia."));
      }
    } finally {
      if (mountedRef.current && generation === requestGeneration.current) setBusy(false);
    }
  }

  const visiblePhotoUrl = previewUrl ?? photoUrl;
  const previewing = Boolean(previewUrl);

  return (
    <>
    <section
      className={`project-primary-photo${visiblePhotoUrl ? " project-primary-photo--has-image" : ""}`}
      role="region"
      aria-label="Cabeçalho do projeto"
      style={visiblePhotoUrl ? { backgroundImage: `url("${visiblePhotoUrl}")` } : undefined}
    >
      <div className="project-primary-photo__overlay" aria-hidden="true" />
      <div className="project-primary-photo__content">
        {children}
        {!visiblePhotoUrl && <EmptyState compact icon="camera" title={hasPhotoLocal ? "A carregar fotografia…" : "Sem fotografia principal."} />}
        {previewing && <span className="project-primary-photo__preview-label">Pré-visualização — por guardar</span>}
        {error && <Alert tone="danger">{error}</Alert>}
      </div>
    </section>
    {canEdit && (
      <div className="cluster project-primary-photo__controls">
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
    </>
  );
}
