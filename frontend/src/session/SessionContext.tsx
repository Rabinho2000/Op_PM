// Sessão atual: utilizador (/me) e estado do servidor (/health),
// carregados uma vez por sessão e partilhados pelo layout e pelas páginas.
// As permissões vêm sempre do servidor — `can()` só serve para decidir o
// que mostrar; cada escrita continua validada no backend.
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, getHealth, getMe, HealthResponse, MeResponse } from "../api/client";

export interface SessionState {
  me: MeResponse | null;
  health: HealthResponse | null;
  loading: boolean;
  error: string | null;
  can: (permission: string) => boolean;
  reload: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getHealth()
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setHealth(null));
    getMe()
      .then((m) => !cancelled && setMe(m))
      .catch((e) => {
        if (cancelled) return;
        setMe(null);
        setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const value = useMemo<SessionState>(
    () => ({
      me,
      health,
      loading,
      error,
      can: (permission: string) => Boolean(me?.permissions.includes(permission)),
      reload,
    }),
    [me, health, loading, error, reload]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession tem de ser usado dentro de <SessionProvider>.");
  }
  return ctx;
}

// Para testes: fornece uma sessão fixa sem pedidos HTTP.
export function StaticSessionProvider({
  me,
  health = null,
  children,
}: {
  me: MeResponse | null;
  health?: HealthResponse | null;
  children: ReactNode;
}) {
  const value: SessionState = {
    me,
    health,
    loading: false,
    error: null,
    can: (permission) => Boolean(me?.permissions.includes(permission)),
    reload: () => undefined,
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
