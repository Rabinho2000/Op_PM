import { useState, type FormEvent } from "react";
import { Modal } from "../../../components/ui";
import type { CabosEngine, RouteGroup, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import RouteCard from "../ac/RouteCard";
import type { RoutePatch } from "../ac/utils";

interface RouteGroupsDialogProps {
  engine: CabosEngine;
  state: State;
  readOnly: boolean;
  apply: (updater: CableStudyUpdater) => void;
  onClose: () => void;
}

export default function RouteGroupsDialog({ engine, state, readOnly, apply, onClose }: RouteGroupsDialogProps) {
  const [newName, setNewName] = useState("");
  const [nameDrafts, setNameDrafts] = useState<Record<number, string>>({});
  const routeGroups = state.rts ?? [];

  function addRoute(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const name = newName.trim();
    if (readOnly || !name) return;
    apply((current) => engine.actions.addRoute(current, { name }));
    setNewName("");
  }

  function saveName(group: RouteGroup): void {
    if (readOnly) return;
    const name = (nameDrafts[group.id] ?? group.nome).trim();
    if (!name || name === group.nome) {
      setNameDrafts((current) => ({ ...current, [group.id]: group.nome }));
      return;
    }
    apply((current) => engine.actions.setRouteField(current, { id: group.id, field: "nome", value: name }));
    setNameDrafts((current) => ({ ...current, [group.id]: name }));
  }

  function updateRoute(group: RouteGroup, patch: RoutePatch): void {
    if (readOnly) return;
    apply((current) => engine.actions.updateRoute(current, { id: group.id, patch }));
  }

  function removeRoute(group: RouteGroup): void {
    if (readOnly) return;
    const assigned = state.invs.filter((inverter) => inverter.rtId === group.id).length;
    const membersMessage = assigned === 1
      ? "1 inversor ficará sem passagem atribuída"
      : `${assigned} inversores ficarão sem passagem atribuída`;
    const accepted = window.confirm(`Remover a passagem “${group.nome}”? ${membersMessage}; os inversores não serão removidos.`);
    if (!accepted || readOnly) return;
    apply((current) => engine.actions.removeRoute(current, { id: group.id }));
  }

  return (
    <Modal title="Gerir passagens dos inversores" onClose={onClose}>
      <p className="cable-dialog__intro">
        Atribua uma passagem a cada inversor na tabela. Um inversor sem grupo mantém-se sem passagem atribuída.
      </p>
      <form className="cable-route-groups__new" onSubmit={addRoute}>
        <label className="field" htmlFor="cable-new-route-name">
          <span>Nome da nova passagem</span>
          <input
            id="cable-new-route-name"
            className="input"
            value={newName}
            maxLength={80}
            onChange={(event) => setNewName(event.target.value)}
            disabled={readOnly}
          />
        </label>
        <button type="submit" className="btn btn--sm" disabled={readOnly || !newName.trim()}>Adicionar passagem</button>
      </form>

      {routeGroups.length === 0 ? (
        <p className="muted small">Ainda não há passagens agrupadas. Crie uma passagem para a poder atribuir aos inversores.</p>
      ) : (
        <div className="cable-route-groups" aria-label="Passagens agrupadas">
          {routeGroups.map((group) => {
            const assigned = state.invs.filter((inverter) => inverter.rtId === group.id).length;
            const draftName = nameDrafts[group.id] ?? group.nome;
            return (
              <article className="cable-route-group" key={group.id}>
                <div className="cable-route-group__content">
                  <form
                    className="cable-route-group__name"
                    onSubmit={(event) => { event.preventDefault(); saveName(group); }}
                  >
                    <label className="field" htmlFor={`cable-route-name-${group.id}`}>
                      <span>Nome da passagem {group.id}</span>
                      <input
                        id={`cable-route-name-${group.id}`}
                        className="input"
                        value={draftName}
                        maxLength={80}
                        onChange={(event) => setNameDrafts((current) => ({ ...current, [group.id]: event.target.value }))}
                        disabled={readOnly}
                      />
                    </label>
                    {!readOnly && (
                      <button type="submit" className="btn btn--sm btn--ghost" aria-label={`Guardar nome da passagem ${group.id}`}>
                        Guardar nome
                      </button>
                    )}
                  </form>
                  <p className="cable-route-group__members">
                    {assigned} {assigned === 1 ? "inversor atribuído" : "inversores atribuídos"}
                  </p>
                  <RouteCard
                    route={group}
                    catalogs={engine.catalogs}
                    label={`Passagem ${group.id}`}
                    disabled={readOnly}
                    onChange={(patch) => updateRoute(group, patch)}
                  />
                </div>
                {!readOnly && (
                  <button
                    type="button"
                    className="btn btn--sm btn--ghost"
                    aria-label={`Remover passagem ${group.nome}`}
                    onClick={() => removeRoute(group)}
                  >
                    Remover
                  </button>
                )}
              </article>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
