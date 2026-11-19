import { ChangeEvent, useEffect, useRef, useState } from "react";
import {
  deleteInventoryCategoryImage,
  deleteInventoryItemPhoto,
  getInventoryCategoryImageBlob,
  getInventoryItemPhotoBlob,
  InventoryCategoryImageInfo,
  uploadInventoryCategoryImage,
  uploadInventoryItemPhoto,
  errorMessage,
} from "../api/client";
import { Alert } from "./ui";
import CategoryIllustration from "../pages/CategoryIllustration";

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

type CategoryUploadResult = InventoryCategoryImageInfo & { content_type: string };

export function InventoryCategoryImage({
  category,
  hasCustomImage,
  imageVersion,
  accountKey,
  canManage = false,
  onImageChanged,
}: {
  category: string;
  hasCustomImage: boolean;
  imageVersion: string | null;
  accountKey: string;
  canManage?: boolean;
  onImageChanged?: (result: InventoryCategoryImageInfo) => void;
}) {
  const [hasCustomImageLocal, setHasCustomImageLocal] = useState(hasCustomImage);
  const [imageVersionLocal, setImageVersionLocal] = useState(imageVersion);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setHasCustomImageLocal(hasCustomImage);
    setImageVersionLocal(imageVersion);
  }, [hasCustomImage, imageVersion]);

  useEffect(() => {
    let active = true;
    let createdUrl: string | null = null;
    setImageUrl(null);
    if (!hasCustomImageLocal) {
      return () => { active = false; };
    }
    getInventoryCategoryImageBlob(category, imageVersionLocal)
      .then((blob) => {
        if (!active) return;
        createdUrl = URL.createObjectURL(blob);
        setImageUrl(createdUrl);
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause, "Não foi possível carregar a imagem da categoria."));
      });
    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [category, hasCustomImageLocal, imageVersionLocal, accountKey]);

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
    if (file.size > MAX_IMAGE_BYTES) {
      setError("A imagem excede o limite de 10 MB.");
      return;
    }
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
      setError("Formato inválido. Utilize JPEG, PNG ou WebP.");
      return;
    }
    setSelectedFile(file);
  }

  async function saveImage() {
    if (!selectedFile) return;
    setBusy(true);
    setError(null);
    try {
      const result: CategoryUploadResult = await uploadInventoryCategoryImage(category, selectedFile);
      setSelectedFile(null);
      setHasCustomImageLocal(true);
      setImageVersionLocal(result.image_version);
      onImageChanged?.(result);
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível guardar a imagem da categoria."));
    } finally {
      setBusy(false);
    }
  }

  async function removeImage() {
    setBusy(true);
    setError(null);
    try {
      await deleteInventoryCategoryImage(category);
      setSelectedFile(null);
      setHasCustomImageLocal(false);
      setImageVersionLocal(null);
      onImageChanged?.({ name: category, has_custom_image: false, image_version: null });
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível remover a imagem da categoria."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inventory-category-visual">
      <CategoryIllustration category={category} imageUrl={previewUrl ?? (hasCustomImageLocal ? imageUrl : null)} />
      {canManage && <div className="inventory-image-controls">
        {error && <Alert tone="danger">{error}</Alert>}
        <input
          ref={inputRef}
          aria-label="Selecionar imagem de categoria"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={handleFileChange}
          hidden
        />
        <div className="cluster">
          <button type="button" className="btn btn--sm" onClick={() => inputRef.current?.click()} disabled={busy}>
            {hasCustomImageLocal ? "Substituir imagem de categoria" : "Imagem de categoria"}
          </button>
          {selectedFile && <button type="button" className="btn btn--sm btn--primary" onClick={saveImage} disabled={busy}>
            {busy ? "A guardar…" : "Guardar imagem de categoria"}
          </button>}
          {hasCustomImageLocal && <button type="button" className="btn btn--sm btn--danger" onClick={removeImage} disabled={busy}>
            Remover imagem de categoria
          </button>}
          <span className="small muted">JPEG, PNG ou WebP · máximo 10 MB</span>
        </div>
      </div>}
    </div>
  );
}

export function InventoryItemPhoto({
  itemId,
  itemName,
  category,
  hasPhoto,
  canManage,
  accountKey,
  onPhotoChanged,
}: {
  itemId: string;
  itemName: string;
  category: string;
  hasPhoto: boolean;
  canManage: boolean;
  accountKey: string;
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

  useEffect(() => setHasPhotoLocal(hasPhoto), [hasPhoto]);

  useEffect(() => {
    let active = true;
    let createdUrl: string | null = null;
    setPhotoUrl(null);
    if (!hasPhotoLocal) return () => { active = false; };
    getInventoryItemPhotoBlob(itemId)
      .then((blob) => {
        if (!active) return;
        createdUrl = URL.createObjectURL(blob);
        setPhotoUrl(createdUrl);
      })
      .catch((cause: unknown) => {
        if (active) setError(errorMessage(cause, "Não foi possível carregar a fotografia do artigo."));
      });
    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [itemId, hasPhotoLocal, refreshToken, accountKey]);

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
    if (file.size > MAX_IMAGE_BYTES) {
      setError("A fotografia excede o limite de 10 MB.");
      return;
    }
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
      setError("Formato inválido. Utilize JPEG, PNG ou WebP.");
      return;
    }
    setSelectedFile(file);
  }

  async function savePhoto() {
    if (!selectedFile) return;
    setBusy(true);
    setError(null);
    try {
      await uploadInventoryItemPhoto(itemId, selectedFile);
      setSelectedFile(null);
      setHasPhotoLocal(true);
      setRefreshToken((value) => value + 1);
      onPhotoChanged?.(true);
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível guardar a fotografia do artigo."));
    } finally {
      setBusy(false);
    }
  }

  async function removePhoto() {
    setBusy(true);
    setError(null);
    try {
      await deleteInventoryItemPhoto(itemId);
      setSelectedFile(null);
      setHasPhotoLocal(false);
      onPhotoChanged?.(false);
    } catch (cause) {
      setError(errorMessage(cause, "Não foi possível remover a fotografia do artigo."));
    } finally {
      setBusy(false);
    }
  }

  const visiblePhotoUrl = previewUrl ?? (hasPhotoLocal ? photoUrl : null);
  return <div className="inventory-item-photo">
    {error && canManage && <Alert tone="danger">{error}</Alert>}
    {visiblePhotoUrl ? <img className="inventory-item-photo__image" src={visiblePhotoUrl} alt={previewUrl ? `Pré-visualização da fotografia de ${itemName}` : `Fotografia de ${itemName}`} /> : (
      <div className="inventory-item-photo__fallback">
        <CategoryIllustration category={category} />
        <span>{hasPhotoLocal ? "A carregar fotografia…" : "Sem fotografia do artigo."}</span>
      </div>
    )}
    {canManage && <div className="cluster inventory-image-controls">
      <input
        ref={inputRef}
        aria-label="Selecionar fotografia do artigo"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        onChange={handleFileChange}
        hidden
      />
      <button type="button" className="btn btn--sm" onClick={() => inputRef.current?.click()} disabled={busy}>
        {hasPhotoLocal ? "Substituir fotografia" : "Carregar fotografia"}
      </button>
      {selectedFile && <button type="button" className="btn btn--sm btn--primary" onClick={savePhoto} disabled={busy}>
        {busy ? "A guardar…" : "Guardar fotografia"}
      </button>}
      {hasPhotoLocal && <button type="button" className="btn btn--sm btn--danger" onClick={removePhoto} disabled={busy}>
        Remover fotografia
      </button>}
      <span className="small muted">JPEG, PNG ou WebP · máximo 10 MB</span>
    </div>}
  </div>;
}
