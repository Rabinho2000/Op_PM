import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Installer } from "../api/client";
import { makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import WorkPlanCard from "./WorkPlan";

const { listInstallers, updateProjectWorkPlan } = vi.hoisted(() => ({
  listInstallers: vi.fn(),
  updateProjectWorkPlan: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listInstallers, updateProjectWorkPlan };
});

const INSTALLERS: Installer[] = [
  {
    id: "i-vm",
    name: "Instalador A",
    is_active: true,
    project_count: 3,
    teams: [
      { id: "t-1", name: "Equipa 1", leader_name: "Chefe Um", leader_phone: null, is_active: true, project_count: 1 },
      { id: "t-2", name: "Equipa 2", leader_name: null, leader_phone: null, is_active: true, project_count: 1 },
      { id: "t-old", name: "Equipa antiga", leader_name: null, leader_phone: null, is_active: false, project_count: 0 },
    ],
  },
  { id: "i-x", name: "Outro Instalador", is_active: true, project_count: 0, teams: [] },
  { id: "i-off", name: "Instalador parado", is_active: false, project_count: 0, teams: [] },
];

const planned = () =>
  makeProject({
    can_plan_work: true,
    installer_id: "i-vm",
    installer_name: "Instalador A",
    installer_team_id: "t-1",
    installer_team_name: "Equipa 1",
    installer_team_leader_name: "Chefe Um",
    work_start_date: "2026-10-05",
    work_end_date: "2026-10-16",
  });

describe("WorkPlanCard", () => {
  beforeEach(() => {
    listInstallers.mockReset();
    updateProjectWorkPlan.mockReset();
    listInstallers.mockResolvedValue(INSTALLERS);
  });

  it("mostra instalador, equipa com o chefe e as datas", () => {
    renderWithProviders(<WorkPlanCard project={planned()} onChanged={vi.fn()} />);
    expect(screen.getByText("Instalador A")).toBeInTheDocument();
    expect(screen.getByText("Equipa 1")).toBeInTheDocument();
    expect(screen.getByText(/chefe Chefe Um/)).toBeInTheDocument();
    expect(screen.getByText("05/10/2026")).toBeInTheDocument();
    expect(screen.getByText("16/10/2026")).toBeInTheDocument();
    expect(screen.queryByText("Datas estimadas")).not.toBeInTheDocument();
  });

  it("assinala a ausência de plano e assinala datas estimadas", () => {
    const project = makeProject({ can_plan_work: true, work_start_date: "2026-05-12", work_end_date: "2026-05-22", work_dates_estimated: true });
    renderWithProviders(<WorkPlanCard project={project} onChanged={vi.fn()} />);
    expect(screen.getByText("Por atribuir")).toBeInTheDocument();
    expect(screen.getByText("Datas estimadas")).toBeInTheDocument();
    expect(screen.getByText(/não refletem a realidade/)).toBeInTheDocument();
  });

  it("só oferece a edição quando o servidor o permite", () => {
    renderWithProviders(<WorkPlanCard project={makeProject({ can_plan_work: false })} onChanged={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /plano|Planear/ })).not.toBeInTheDocument();
  });

  it("escolher outro instalador limpa a equipa e só mostra equipas ativas desse instalador", async () => {
    renderWithProviders(<WorkPlanCard project={planned()} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: "Outro Instalador" });

    // Instalador atual: equipas ativas (a antiga, inativa, não é oferecida), com o chefe.
    const teamSelect = within(dialog).getByLabelText("Equipa") as HTMLSelectElement;
    expect([...teamSelect.options].map((o) => o.text)).toEqual(["— sem equipa —", "Equipa 1 (chefe Chefe Um)", "Equipa 2"]);
    // Instalador inativo não é oferecido a novas atribuições.
    expect(within(dialog).queryByRole("option", { name: /Instalador parado/ })).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Instalador"), { target: { value: "i-x" } });
    expect((within(dialog).getByLabelText("Equipa") as HTMLSelectElement).value).toBe("");
    expect(within(dialog).getByRole("option", { name: "— este instalador não tem equipas —" })).toBeInTheDocument();
  });

  it("guarda o plano completo", async () => {
    const updated = { ...planned(), installer_team_id: "t-2", installer_team_name: "Equipa 2", installer_team_leader_name: null };
    updateProjectWorkPlan.mockResolvedValue(updated);
    const onChanged = vi.fn();
    renderWithProviders(<WorkPlanCard project={planned()} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: /Equipa 2/ });
    fireEvent.change(within(dialog).getByLabelText("Equipa"), { target: { value: "t-2" } });
    fireEvent.change(within(dialog).getByLabelText("Fim da obra"), { target: { value: "2026-10-20" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar plano" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(updated));
    expect(updateProjectWorkPlan).toHaveBeenCalledWith(planned().id, {
      installer_id: "i-vm",
      installer_team_id: "t-2",
      work_start_date: "2026-10-05",
      work_end_date: "2026-10-20",
    });
    expect(await screen.findByText("Plano da obra atualizado.")).toBeInTheDocument();
  });

  it("valida no cliente que o fim não é anterior ao início", async () => {
    renderWithProviders(<WorkPlanCard project={planned()} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: /Equipa 2/ });
    fireEvent.change(within(dialog).getByLabelText("Fim da obra"), { target: { value: "2026-10-01" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar plano" }));
    expect(within(dialog).getByText("O fim da obra não pode ser anterior ao início.")).toBeInTheDocument();
    expect(updateProjectWorkPlan).not.toHaveBeenCalled();
  });

  it("confirma datas estimadas sem as alterar", async () => {
    const project = makeProject({
      can_plan_work: true,
      installer_id: "i-vm",
      installer_name: "Instalador A",
      work_start_date: "2026-05-12",
      work_end_date: "2026-05-22",
      work_dates_estimated: true,
    });
    updateProjectWorkPlan.mockResolvedValue({ ...project, work_dates_estimated: false });
    renderWithProviders(<WorkPlanCard project={project} onChanged={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: /Equipa 1/ });
    fireEvent.click(within(dialog).getByLabelText("Confirmar as datas como corretas"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar plano" }));

    await waitFor(() => expect(updateProjectWorkPlan).toHaveBeenCalled());
    expect(updateProjectWorkPlan.mock.calls[0][1]).toMatchObject({ work_dates_estimated: false, work_start_date: "2026-05-12" });
  });

  it("mostra o erro do servidor e mantém o diálogo aberto", async () => {
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    updateProjectWorkPlan.mockImplementation(() => {
      throw new actual.ApiError(422, "A equipa não pertence a este instalador.");
    });
    renderWithProviders(<WorkPlanCard project={planned()} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Editar plano" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("option", { name: /Equipa 2/ });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar plano" }));
    expect(await within(dialog).findByText("A equipa não pertence a este instalador.")).toBeInTheDocument();
  });
});
