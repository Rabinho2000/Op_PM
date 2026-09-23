// Notificações breves ("Tarefa concluída", erros de gravação) — região
// aria-live para leitores de ecrã.
import { createContext, ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";
import Icon from "./Icon";

type ToastTone = "success" | "error" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastApi {
  notify: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastApi>({ notify: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const notify = useCallback((message: string, tone: ToastTone = "success") => {
    const id = nextId.current++;
    setItems((current) => [...current, { id, tone, message }]);
    window.setTimeout(() => setItems((current) => current.filter((t) => t.id !== id)), 4500);
  }, []);

  const api = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite" role="status">
        {items.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            <Icon name={t.tone === "error" ? "alert" : t.tone === "success" ? "checkCircle" : "info"} size={18} />
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
