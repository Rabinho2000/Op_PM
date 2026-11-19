import { DependencyList, useEffect, useRef, useState } from "react";

export interface AuthenticatedBlobOptions {
  /** Com `false` não pede nada e devolve `null` (ex.: o item não tem fotografia). */
  enabled?: boolean;
  /** Chamado se o pedido falhar enquanto o resultado ainda interessa. */
  onError?: (error: unknown) => void;
}

/**
 * Descarrega um ficheiro autenticado (as imagens/PDFs da API não podem ir num
 * `<img src>` direto, porque o token vai em cabeçalho) e devolve um object URL
 * para o mostrar. O URL anterior é revogado sempre que as dependências mudam
 * e no unmount; uma resposta que chega depois disso é descartada sem criar URL
 * (nenhuma fuga de object URLs).
 */
export function useAuthenticatedBlob(
  load: () => Promise<Blob>,
  deps: DependencyList,
  { enabled = true, onError }: AuthenticatedBlobOptions = {},
): string | null {
  const [url, setUrl] = useState<string | null>(null);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  useEffect(() => {
    setUrl(null);
    if (!enabled) return undefined;
    let active = true;
    let createdUrl: string | null = null;
    load()
      .then((blob) => {
        if (!active) return;
        createdUrl = URL.createObjectURL(blob);
        setUrl(createdUrl);
      })
      .catch((error: unknown) => {
        if (active) onErrorRef.current?.(error);
      });
    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
    // `load` é recriado a cada render; só as dependências explícitas contam.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  return url;
}

/** Object URL de um ficheiro local (pré-visualização antes de enviar), revogado ao mudar/desmontar. */
export function useObjectUrl(file: Blob | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setUrl(null);
      return undefined;
    }
    const created = URL.createObjectURL(file);
    setUrl(created);
    return () => URL.revokeObjectURL(created);
  }, [file]);
  return url;
}
