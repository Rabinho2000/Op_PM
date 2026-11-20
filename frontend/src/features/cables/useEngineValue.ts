import { useEffect, useState, type DependencyList } from "react";

export interface EngineValue<T> {
  /** Último valor calculado (mantém-se enquanto se recalcula, para não piscar). */
  value: T | undefined;
  error: string | null;
  pending: boolean;
}

/**
 * Executa um cálculo do motor (agora assíncrono, no worker) sempre que as
 * dependências mudam e descarta respostas de pedidos já ultrapassados.
 */
export function useEngineValue<T>(
  compute: () => T | PromiseLike<T>,
  deps: DependencyList,
  enabled = true,
): EngineValue<T> {
  const [snapshot, setSnapshot] = useState<EngineValue<T>>({ value: undefined, error: null, pending: enabled });

  useEffect(() => {
    if (!enabled) {
      setSnapshot({ value: undefined, error: null, pending: false });
      return undefined;
    }
    let active = true;
    setSnapshot((current) => ({ ...current, pending: true }));
    Promise.resolve()
      .then(compute)
      .then((value) => {
        if (active) setSnapshot({ value, error: null, pending: false });
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setSnapshot({
          value: undefined,
          error: reason instanceof Error && reason.message ? reason.message : "Não foi possível calcular com a ferramenta de cálculo.",
          pending: false,
        });
      });
    return () => {
      active = false;
    };
    // `compute` é recriado a cada render; só as dependências explícitas contam.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  return snapshot;
}
