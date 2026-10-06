// Notificações breves ("Tarefa concluída", erros de gravação) — região
// aria-live para leitores de ecrã.
import { createContext, ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";
import Icon from "./Icon";

type ToastTone = "success" | "error" | "info";

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
  action?: ToastAction;
}

interface ToastApi {
  notify: (message: string, tone?: ToastTone, action?: ToastAction) => void;
}

const ToastContext = createContext<ToastApi>({ notify: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((current) => current.filter((t) => t.id !== id)), []);

  const notify = useCallback(
    (message: string, tone: ToastTone = "success", action?: ToastAction) => {
      const id = nextId.current++;
      setItems((current) => [...current, { id, tone, message, action }]);
      // Com ação (ex. "Anular") fica mais tempo visível.
      window.setTimeout(() => dismiss(id), action ? 9000 : 4500);
    },
    [dismiss]
  );

  const api = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite" role="status">
        {items.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            <Icon name={t.tone === "error" ? "alert" : t.tone === "success" ? "checkCircle" : "info"} size={18} />
            <span>{t.message}</span>
            {t.action && (
              <button
                type="button"
                className="btn btn--sm btn--ghost toast__action"
                onClick={() => {
                  dismiss(t.id);
                  t.action?.onClick();
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
