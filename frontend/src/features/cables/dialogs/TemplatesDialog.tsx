import { useState } from "react";
import { EmptyState, Modal } from "../../../components/ui";
import type { CabosEngine, State, Template } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";

export interface TemplatesDialogProps {
  engine: CabosEngine;
  state: State;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater) => void;
  onClose: () => void;
  confirm?: (message: string) => boolean;
}

function confirmChange(confirm: ((message: string) => boolean) | undefined, message: string): boolean {
  if (confirm) return confirm(message);
  return typeof window !== "undefined" && typeof window.confirm === "function" ? window.confirm(message) : false;
}

async function applyTemplate(engine: CabosEngine, current: State, templateId: string): Promise<State> {
  const actions = engine.actions as Partial<CabosEngine["actions"]>;
  const next = typeof actions.applyTemplate === "function"
    ? await actions.applyTemplate(current, templateId)
    : await engine.newState(templateId);
  if (!next || typeof next !== "object") throw new Error("O motor não devolveu um estado válido para o modelo.");
  return {
    ...next,
    proj: current.proj,
    obra: {
      ...next.obra,
      cliente: current.obra.cliente,
      morada: current.obra.morada,
    },
  };
}

export default function TemplatesDialog({ engine, state, readOnly, apply, onClose, confirm }: TemplatesDialogProps) {
  const templates = Array.from(engine.templates ?? []) as Template[];
  const [actionError, setActionError] = useState<string | null>(null);

  function chooseTemplate(template: Template): void {
    if (readOnly) return;
    const accepted = confirmChange(
      confirm,
      "Aplicar este modelo substitui o estado atual do estudo, mantendo o projeto, o cliente e a morada. Continuar?",
    );
    if (!accepted) return;
    try {
      apply((current) => applyTemplate(engine, current, template.id));
      onClose();
    } catch {
      setActionError("Não foi possível aplicar este modelo.");
    }
  }

  return (
    <Modal title="Modelos / Novo projeto" onClose={onClose}>
      <p className="cable-dialog__intro">
        Escolha uma estrutura inicial. Os dados do projeto, cliente e morada deste estudo são mantidos.
      </p>
      {templates.length === 0 ? (
        <EmptyState title="Sem modelos disponíveis" text="O motor não publicou modelos para este estudo." compact />
      ) : (
        <div className="cable-dialog__template-list">
          {templates.map((template) => (
            <article className="cable-dialog__template" key={template.id}>
              <div>
                <h3>{template.label}</h3>
                <p>{template.description}</p>
              </div>
              <button
                type="button"
                className="btn btn--sm btn--primary"
                aria-label={`Aplicar modelo ${template.label}`}
                onClick={() => chooseTemplate(template)}
                disabled={readOnly}
              >
                Aplicar
              </button>
            </article>
          ))}
        </div>
      )}
      {actionError && <div className="cable-dialog__error" role="alert">{actionError}</div>}
    </Modal>
  );
}
