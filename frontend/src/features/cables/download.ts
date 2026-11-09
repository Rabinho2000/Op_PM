import { useCallback, useRef, useState } from "react";
import { useToast } from "../../components/Toast";
import type { ExportFile } from "./engine";

export type ExportSource = ExportFile | PromiseLike<ExportFile> | (() => ExportFile | PromiseLike<ExportFile>);
export type ExportToastTone = "success" | "error" | "info";
export type ExportNotifier = (message: string, tone?: ExportToastTone) => void;

export interface DownloadExportOptions {
  notify?: ExportNotifier;
  document?: Document;
  url?: {
    createObjectURL: (object: Blob) => string;
    revokeObjectURL: (url: string) => void;
  };
  successMessage?: string;
  errorMessage?: string;
}

const DOWNLOAD_OK = "Ficheiro descarregado.";
const DOWNLOAD_ERROR = "Não foi possível gerar o ficheiro.";

function notifySafely(notify: ExportNotifier | undefined, message: string, tone: ExportToastTone): void {
  try {
    notify?.(message, tone);
  } catch {
    // A notificação não deve transformar um download concluído numa falha.
  }
}

function resolveSource(source: ExportSource): ExportFile | PromiseLike<ExportFile> {
  return typeof source === "function" ? source() : source;
}

function isExportFile(value: unknown): value is ExportFile {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ExportFile>;
  return typeof candidate.filename === "string" && candidate.filename.trim().length > 0 && Boolean(candidate.blob);
}

/**
 * Runs one engine export and starts a browser download with a temporary anchor.
 * The notifier is injected so this helper remains usable outside React; the hook
 * below wires it to the platform ToastProvider.
 */
export async function downloadExport(source: ExportSource, options: DownloadExportOptions = {}): Promise<ExportFile | null> {
  const notify = options.notify;
  try {
    const file = await resolveSource(source);
    if (!isExportFile(file)) throw new Error("O motor devolveu um ficheiro inválido.");

    const doc = options.document ?? (typeof document !== "undefined" ? document : undefined);
    const urlApi = options.url ?? (typeof URL !== "undefined" ? URL : undefined);
    if (!doc || !urlApi?.createObjectURL || !urlApi.revokeObjectURL) {
      throw new Error("Este browser não suporta descargas.");
    }

    const objectUrl = urlApi.createObjectURL(file.blob);
    const anchor = doc.createElement("a");
    anchor.href = objectUrl;
    anchor.download = file.filename;
    anchor.rel = "noopener";
    anchor.className = "cable-export-download";
    anchor.setAttribute("data-cable-export-download", "true");
    anchor.setAttribute("aria-hidden", "true");
    anchor.style.position = "fixed";
    anchor.style.left = "-10000px";
    anchor.style.top = "-10000px";

    try {
      (doc.body ?? doc.documentElement).appendChild(anchor);
      anchor.click();
    } finally {
      anchor.remove();
      urlApi.revokeObjectURL(objectUrl);
    }

    notifySafely(notify, options.successMessage ?? DOWNLOAD_OK, "success");
    return file;
  } catch {
    notifySafely(notify, options.errorMessage ?? DOWNLOAD_ERROR, "error");
    return null;
  }
}

export interface ExportRunner {
  run: (source: ExportSource, options?: Omit<DownloadExportOptions, "notify">) => Promise<ExportFile | null>;
  isGenerating: boolean;
  busy: boolean;
  label: "A gerar…" | null;
}

/** Shared export state for U3/U4 buttons. Concurrent exports are ignored. */
export function useExportRunner(): ExportRunner {
  const { notify } = useToast();
  const [isGenerating, setIsGenerating] = useState(false);
  const running = useRef(false);

  const run = useCallback<ExportRunner["run"]>(async (source, options = {}) => {
    if (running.current) return null;
    running.current = true;
    setIsGenerating(true);
    try {
      return await downloadExport(source, { ...options, notify });
    } finally {
      running.current = false;
      setIsGenerating(false);
    }
  }, [notify]);

  return { run, isGenerating, busy: isGenerating, label: isGenerating ? "A gerar…" : null };
}
