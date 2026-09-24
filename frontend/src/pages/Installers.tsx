import { FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  createInstaller,
  createInstallerTeam,
  Installer,
  InstallerTeam,
  listInstallers,
  updateInstaller,
  updateInstallerTeam,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";

const PHONE_RE = /^\+?[\d\s().-]+$/;

type Dialog =
  | { kind: "installer" }
  | { kind: "team-new"; installer: Installer }
  | { kind: "team-edit"; installer: Installer; team: InstallerTeam }
  | null;

// Gestão de instaladores e das suas equipas (com o chefe de equipa, uma pessoa
// externa à Solcor: só nome e telefone). Nada se apaga: desativa-se.
export default function Installers() {
  const { can } = useSession();
  const { notify } = useToast();
  const canManage = can("installer.manage");
  const [installers, setInstallers] = useState<Installer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    listInstallers()
      .then((r) => !cancelled && setInstallers(r))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  async function toggleInstaller(i: Installer) {
    try {
      await updateInstaller(i.id, { is_active: !i.is_active });
      notify(i.is_active ? `«${i.name}» desativado.` : `«${i.name}» reativado.`);
      reload();
    } catch (e) {
      notify(e instanceof ApiError ? e.detail : "Não foi possível alterar o instalador.", "error");
    }
  }

  return (
    <>
      <PageHeader
        title="Instaladores"
        subtitle="Subempreiteiros, as suas equipas e os respetivos chefes de equipa."
        actions={
          canManage && (
            <button type="button" className="btn btn--primary" onClick={() => setDialog({ kind: "installer" })}>
              <Icon name="plus" size={16} /> Novo instalador
            </button>
          )
        }
      />
      {error && <ErrorState message={error} onRetry={reload} />}
      {!error && installers === null && <LoadingState label="A carregar instaladores…" rows={4} />}
      {!error && installers?.length === 0 && (
        <div className="card">
          <EmptyState icon="wrench" title="Ainda não há instaladores" text="Crie o primeiro para poder atribuí-lo às obras." />
        </div>
      )}
      {!error && installers && installers.length > 0 && (
        <div className="grid">
          {installers.map((i) => (
            <Card
              key={i.id}
              title={
                <>
                  {i.name} {!i.is_active && <Badge>Inativo</Badge>}
                </>
              }
              icon="wrench"
              actions={
                canManage && (
                  <span style={{ display: "inline-flex", gap: 8 }}>
                    <button type="button" className="btn btn--sm" onClick={() => setDialog({ kind: "team-new", installer: i })}>
                      Nova equipa
                    </button>
                    <button type="button" className="btn btn--sm btn--ghost" onClick={() => toggleInstaller(i)}>
                      {i.is_active ? "Desativar" : "Reativar"}
                    </button>
                  </span>
                )
              }
            >
              <p className="small muted" style={{ marginBottom: 8 }}>
                {i.project_count} obra{i.project_count === 1 ? "" : "s"} ativa{i.project_count === 1 ? "" : "s"}
              </p>
              {i.teams.length === 0 ? (
                <EmptyState compact title="Sem equipas registadas." />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">Equipas de {i.name}</caption>
                    <thead>
                      <tr>
                        <th scope="col">Equipa</th>
                        <th scope="col">Chefe de equipa</th>
                        <th scope="col">Telefone</th>
                        <th scope="col">Obras</th>
                        {canManage && <th scope="col">Ações</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {i.teams.map((t) => (
                        <tr key={t.id}>
                          <td>
                            {t.name} {!t.is_active && <Badge>Inativa</Badge>}
                          </td>
                          <td>{t.leader_name ?? <span className="muted">—</span>}</td>
                          <td className="nowrap">
                            {t.leader_phone ? <a href={`tel:${t.leader_phone.replace(/[^\d+]/g, "")}`}>{t.leader_phone}</a> : <span className="muted">—</span>}
                          </td>
                          <td>{t.project_count}</td>
                          {canManage && (
                            <td>
                              <button
                                type="button"
                                className="btn btn--sm"
                                aria-label={`Editar ${t.name} de ${i.name}`}
                                onClick={() => setDialog({ kind: "team-edit", installer: i, team: t })}
                              >
                                Editar
                              </button>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {dialog?.kind === "installer" && (
        <InstallerModal
          onClose={() => setDialog(null)}
          onSaved={(name) => {
            notify(`Instalador «${name}» criado.`);
            setDialog(null);
            reload();
          }}
        />
      )}
      {(dialog?.kind === "team-new" || dialog?.kind === "team-edit") && (
        <TeamModal
          installer={dialog.installer}
          team={dialog.kind === "team-edit" ? dialog.team : null}
          onClose={() => setDialog(null)}
          onSaved={(name, created) => {
            notify(created ? `Equipa «${name}» criada.` : `Equipa «${name}» atualizada.`);
            setDialog(null);
            reload();
          }}
        />
      )}
    </>
  );
}

function InstallerModal({ onClose, onSaved }: { onClose: () => void; onSaved: (name: string) => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Indique o nome do instalador.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createInstaller(name.trim());
      onSaved(created.name);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar o instalador.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Novo instalador"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="installer-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Criar instalador"}
          </button>
        </>
      }
    >
      <form id="installer-form" className="form-grid" onSubmit={submit} noValidate>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="inst-name">Nome *</label>
          <input id="inst-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

function TeamModal({
  installer,
  team,
  onClose,
  onSaved,
}: {
  installer: Installer;
  team: InstallerTeam | null;
  onClose: () => void;
  onSaved: (name: string, created: boolean) => void;
}) {
  const [name, setName] = useState(team?.name ?? "");
  const [leader, setLeader] = useState(team?.leader_name ?? "");
  const [phone, setPhone] = useState(team?.leader_phone ?? "");
  const [active, setActive] = useState(team?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Indique o nome da equipa.");
      return;
    }
    if (phone.trim()) {
      const digits = (phone.match(/\d/g) ?? []).length;
      if (!PHONE_RE.test(phone.trim()) || digits < 6 || digits > 15) {
        setError("Telefone inválido: use só números, espaços, +, ( ) . e -, com 6 a 15 dígitos.");
        return;
      }
    }
    setSaving(true);
    setError(null);
    const payload = { name: name.trim(), leader_name: leader.trim() || null, leader_phone: phone.trim() || null };
    try {
      if (team) await updateInstallerTeam(installer.id, team.id, { ...payload, is_active: active });
      else await createInstallerTeam(installer.id, payload);
      onSaved(payload.name, team === null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar a equipa.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={team ? `Editar equipa — ${installer.name}` : `Nova equipa — ${installer.name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="team-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar equipa"}
          </button>
        </>
      }
    >
      <form id="team-form" className="form-grid" onSubmit={submit} noValidate>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="team-name">Nome da equipa *</label>
          <input id="team-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="team-leader">Chefe de equipa</label>
          <input id="team-leader" className="input" value={leader} onChange={(e) => setLeader(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="team-phone">Telefone do chefe</label>
          <input id="team-phone" className="input" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        {team && (
          <div className="field span-2">
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 500 }}>
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Equipa ativa (desative em vez de apagar: pode haver obras atribuídas)
            </label>
          </div>
        )}
      </form>
    </Modal>
  );
}
