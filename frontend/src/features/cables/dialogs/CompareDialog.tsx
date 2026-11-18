import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, EmptyState, LoadingState, Modal } from "../../../components/ui";
import type { CabosEngine, State, Variant } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import { moneyPt, numberPt } from "../ac/utils";

export interface CompareDialogProps {
  engine: CabosEngine;
  state: State;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater) => void;
  onClose: () => void;
  confirm?: (message: string) => boolean;
}

type VariantResult = Variant[] | PromiseLike<Variant[]>;

function confirmChange(confirm: ((message: string) => boolean) | undefined, message: string): boolean {
  if (confirm) return confirm(message);
  return typeof window !== "undefined" && typeof window.confirm === "function" ? window.confirm(message) : false;
}

function validTotal(variant: Variant): number | null {
  const total = variant.summary?.total;
  return typeof total === "number" && Number.isFinite(total) ? total : null;
}

function isCompliant(variant: Variant): boolean {
  return Boolean(variant.summary && !variant.error && variant.summary.review === 0);
}

export default function CompareDialog({ engine, state, readOnly, apply, onClose, confirm }: CompareDialogProps) {
  const [variants, setVariants] = useState<Variant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setVariants([]);
    const timer = window.setTimeout(() => {
      let source: VariantResult;
      try {
        source = engine.compare.variants(state) as VariantResult;
      } catch (reason) {
        if (active) {
          setLoading(false);
          setError(reason instanceof Error ? reason.message : "Não foi possível calcular as alternativas.");
        }
        return;
      }
      Promise.resolve(source)
        .then((items) => {
          if (!active) return;
          setVariants(Array.isArray(items) ? items : []);
          setLoading(false);
        })
        .catch((reason: unknown) => {
          if (!active) return;
          setLoading(false);
          setError(reason instanceof Error ? reason.message : "Não foi possível calcular as alternativas.");
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [engine, state]);

  const cheapestCompliantId = useMemo(() => {
    const candidates = variants.filter(isCompliant).filter((variant) => validTotal(variant) !== null);
    if (candidates.length === 0) return null;
    return candidates.reduce((best, candidate) => {
      if (!best) return candidate;
      return (validTotal(candidate) ?? Number.POSITIVE_INFINITY) < (validTotal(best) ?? Number.POSITIVE_INFINITY) ? candidate : best;
    }, null as Variant | null)?.id ?? null;
  }, [variants]);

  function applyVariant(variant: Variant): void {
    if (readOnly || !variant.summary || variant.error) return;
    const accepted = confirmChange(
      confirm,
      "Isto substitui as secções e materiais do estudo atual. Só pode anular guardando por cima se ainda não tiver guardado. Continuar?",
    );
    if (!accepted) return;
    apply((current) => engine.compare.apply(current, variant.id));
    onClose();
  }

  return (
    <Modal title="Comparar alternativas" onClose={onClose}>
      <p className="cable-dialog__intro">
        Compare as opções calculadas pelo motor antes de substituir as secções e materiais do estudo atual.
      </p>
      {loading && <LoadingState label="A calcular alternativas…" rows={4} />}
      {!loading && error && <Alert tone="danger">{error}</Alert>}
      {!loading && !error && variants.length === 0 && <EmptyState title="Sem alternativas" text="O motor não devolveu alternativas para este estudo." compact />}
      {!loading && !error && variants.length > 0 && (
        <div className="table-wrap cable-dialog__table-wrap">
          <table className="table cable-dialog__table">
            <caption className="sr-only">Alternativas de dimensionamento</caption>
            <thead>
              <tr>
                <th scope="col">Nome</th>
                <th scope="col">Cabos + terminais</th>
                <th scope="col">Proteções</th>
                <th scope="col">Total</th>
                <th scope="col">ΔU máx.</th>
                <th scope="col">Cabos diferentes</th>
                <th scope="col">Circuitos a rever</th>
                <th scope="col"><span className="sr-only">Ação</span></th>
              </tr>
            </thead>
            <tbody>
              {variants.map((variant) => {
                const summary = variant.summary;
                const cheapest = variant.id === cheapestCompliantId;
                const compliant = isCompliant(variant);
                return (
                  <tr key={variant.id} className={cheapest ? "cable-dialog__highlight" : undefined}>
                    <td data-label="Nome">
                      <strong>{variant.label}</strong>
                      {compliant && <Badge tone="success">Cumpre</Badge>}
                      {cheapest && <Badge tone="brand">Mais barata</Badge>}
                      {variant.note && <span className="cell-sub">{variant.note}</span>}
                      {variant.error && <span className="cell-sub">{variant.error}</span>}
                    </td>
                    <td data-label="Cabos + terminais">{summary && Number.isFinite(summary.cablesAndTerminals) ? moneyPt(summary.cablesAndTerminals) : "—"}</td>
                    <td data-label="Proteções">{summary && Number.isFinite(summary.protection) ? moneyPt(summary.protection) : "—"}</td>
                    <td data-label="Total">
                      {validTotal(variant) === null ? "—" : <>{moneyPt(validTotal(variant))}{summary?.estimated && <span className="cell-sub">estimado</span>}</>}
                    </td>
                    <td data-label="ΔU máx.">{summary ? numberPt(summary.maxVoltageDropPct, " %", 2) : "—"}</td>
                    <td data-label="Cabos diferentes">{summary && Number.isFinite(summary.differentCables) ? numberPt(summary.differentCables, "", 0) : "—"}</td>
                    <td data-label="Circuitos a rever">{summary && Number.isFinite(summary.review) ? numberPt(summary.review, "", 0) : "—"}</td>
                    <td data-label="Ação">
                      <button
                        type="button"
                        className="btn btn--sm btn--primary"
                        aria-label={`Aplicar alternativa ${variant.label}`}
                        onClick={() => applyVariant(variant)}
                        disabled={readOnly || !summary || Boolean(variant.error)}
                      >
                        Aplicar
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="cable-dialog__hint">Os custos só são apresentados quando o motor os fornece.</p>
    </Modal>
  );
}
