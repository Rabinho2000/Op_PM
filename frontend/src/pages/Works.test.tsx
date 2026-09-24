import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Installer, WorkItem, WorksCalendar } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { todayIsoLisbon } from "../utils/dates";
import { defaultWindow, shiftWindow, totalDays, windowFrom } from "../utils/worksTimeline";
import Works from "./Works";

const { getWorksCalendar, listInstallers, listPeople, getLifecycleStatuses } = vi.hoisted(() => ({
  getWorksCalendar: vi.fn(),
  listInstallers: vi.fn(),
  listPeople: vi.fn(),
  getLifecycleStatuses: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getWorksCalendar, listInstallers, listPeople, getLifecycleStatuses };
});

const STATUSES = [
  { code: "on_hold_cliente", label: "On hold pelo cliente", flow_position: null },
  { code: "preparacao", label: "Preparação", flow_position: 1 },
  { code: "construcao", label: "Construção", flow_position: 2 },
];

const INSTALLERS: Installer[] = [
  {
    id: "i-vm",
    name: "Instalador A",
    is_active: true,
    project_count: 2,
    teams: [
      { id: "t-1", name: "Equipa 1", leader_name: "Chefe Um", leader_phone: null, is_active: true, project_count: 2 },
      { id: "t-2", name: "Equipa 2", leader_name: null, leader_phone: null, is_active: true, project_count: 0 },
    ],
  },
  { id: "i-gps", name: "Instalador B", is_active: true, project_count: 1, teams: [] },
];

function work(id: string, start: string, end: string, extra: Partial<WorkItem> = {}): WorkItem {
  return {
    project_id: id,
    name: `Obra ${id}`,
    client_name: null,
    pm_person_id: "p-pm",
    pm_display_name: "PM Um",
    lifecycle_status: "construcao",
    installer_id: "i-vm",
    installer_name: "Instalador A",
    installer_team_id: "t-1",
    installer_team_name: "Equipa 1",
    work_start_date: start,
    work_end_date: end,
    work_dates_estimated: false,
    conflict: false,
    ...extra,
  };
}

function calendar(works: WorkItem[], extra: Partial<WorksCalendar> = {}): WorksCalendar {
  const today = todayIsoLisbon();
  const w = defaultWindow("months", today);
  return {
    start: w.from,
    end: w.to,
    works,
    unscheduled: [],
    summary: {
      works: works.length,
      conflicts: works.filter((x) => x.conflict).length,
      estimated: works.filter((x) => x.work_dates_estimated).length,
      unscheduled: 0,
    },
    ...extra,
  };
}

const manager = () => makeMe({ permissions: ["project.view_all"] });
const lastParams = () => getWorksCalendar.mock.calls[getWorksCalendar.mock.calls.length - 1][0];

describe("Works (calendário de obras)", () => {
  beforeEach(() => {
    [getWorksCalendar, listInstallers, listPeople, getLifecycleStatuses].forEach((m) => m.mockReset());
    listInstallers.mockResolvedValue(INSTALLERS);
    listPeople.mockResolvedValue([{ id: "p-pm", display_name: "PM Um", email: null, is_active: true }]);
    getLifecycleStatuses.mockResolvedValue(STATUSES);
    const today = todayIsoLisbon();
    getWorksCalendar.mockResolvedValue(
      calendar([
        work("a", today, today, { name: "Obra Alfa", conflict: true }),
        work("b", today, today, { name: "Obra Beta", conflict: true }),
        work("c", today, today, { name: "Obra Gama", installer_id: "i-gps", installer_name: "Instalador B", installer_team_id: null, installer_team_name: null, work_dates_estimated: true, lifecycle_status: "preparacao" }),
        work("d", today, today, { name: "Obra Delta", installer_id: null, installer_name: null, installer_team_id: null, installer_team_name: null, pm_display_name: null }),
      ])
    );
  });

  it("pede a janela por omissão (-3/+6 meses, D10) e mostra o resumo", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    expect(await screen.findByText("Obra Alfa")).toBeInTheDocument();
    const expected = defaultWindow("months", todayIsoLisbon());
    expect(lastParams()).toEqual({
      from: expected.from,
      to: expected.to,
      pm_person_id: undefined,
      lifecycle_status: undefined,
      installer_id: undefined,
      team_id: undefined,
    });
    expect(screen.getByText(/4 obras/)).toBeInTheDocument();
    expect(screen.getByText("2 em conflito")).toBeInTheDocument();
    expect(screen.getByText(/1 com datas estimadas/)).toBeInTheDocument();
  });

  it("agrupa por instalador e equipa, com 'Sem equipa' e 'Sem instalador'", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    const region = screen.getByRole("region", { name: /Calendário de obras por instalador/ });
    const labels = [...region.querySelectorAll(".works__label")].map((el) => el.querySelector("span")?.textContent);
    expect(labels).toEqual(["Instalador A", "Equipa 1", "Instalador B", "Sem instalador"]);
  });

  it("cada obra é uma ligação para o projeto, descrita por extenso, com conflito e estimativa assinalados", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    const alfa = await screen.findByRole("link", { name: /Obra Alfa/ });
    expect(alfa).toHaveAttribute("href", "/projects/a");
    expect(alfa).toHaveClass("works__bar--conflict");
    expect(alfa.getAttribute("aria-label")).toMatch(/Instalador A \/ Equipa 1/);
    expect(alfa.getAttribute("aria-label")).toMatch(/Conflito: a equipa tem outra obra sobreposta/);
    expect(alfa.getAttribute("aria-label")).toMatch(/PM PM Um/);

    const gama = screen.getByRole("link", { name: /Obra Gama/ });
    expect(gama).toHaveClass("works__bar--estimated");
    expect(gama).not.toHaveClass("works__bar--conflict");
    expect(gama.getAttribute("aria-label")).toMatch(/datas estimadas/);

    const delta = screen.getByRole("link", { name: /Obra Delta/ });
    expect(delta.getAttribute("aria-label")).toMatch(/sem instalador/);
    expect(delta.getAttribute("aria-label")).toMatch(/sem PM/);
  });

  it("duas obras sobrepostas na mesma equipa ficam em faixas diferentes", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    const a = (await screen.findByRole("link", { name: /Obra Alfa/ })).style.top;
    const b = screen.getByRole("link", { name: /Obra Beta/ }).style.top;
    expect(a).not.toBe(b);
  });

  it("filtra por PM, instalador e estados (vários) no servidor", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    await screen.findByRole("option", { name: "PM Um" });

    fireEvent.change(screen.getByLabelText("PM"), { target: { value: "p-pm" } });
    await waitFor(() => expect(lastParams().pm_person_id).toBe("p-pm"));

    fireEvent.click(await screen.findByLabelText("Construção"));
    fireEvent.click(screen.getByLabelText("On hold pelo cliente"));
    await waitFor(() => expect(lastParams().lifecycle_status).toEqual(["construcao", "on_hold_cliente"]));

    fireEvent.click(screen.getByLabelText("Construção")); // desmarcar
    await waitFor(() => expect(lastParams().lifecycle_status).toEqual(["on_hold_cliente"]));

    fireEvent.change(screen.getByLabelText("Instalador"), { target: { value: "i-vm" } });
    await waitFor(() => expect(lastParams().installer_id).toBe("i-vm"));
    // Com um instalador escolhido só se oferecem as equipas dele.
    const team = screen.getByLabelText("Equipa") as HTMLSelectElement;
    expect([...team.options].map((o) => o.text)).toEqual(["Todas as equipas", "Equipa 1", "Equipa 2"]);
    fireEvent.change(team, { target: { value: "t-2" } });
    await waitFor(() => expect(lastParams().team_id).toBe("t-2"));

    // Mudar de instalador limpa a equipa.
    fireEvent.change(screen.getByLabelText("Instalador"), { target: { value: "i-gps" } });
    await waitFor(() => expect(lastParams().team_id).toBeUndefined());

    fireEvent.click(screen.getByRole("button", { name: /Limpar filtros/ }));
    await waitFor(() =>
      expect(lastParams()).toMatchObject({ pm_person_id: undefined, lifecycle_status: undefined, installer_id: undefined, team_id: undefined })
    );
  });

  it("lê janela, escala e filtros do URL (vista partilhável)", async () => {
    renderWithProviders(<Works />, {
      me: manager(),
      route: "/works?zoom=weeks&from=2026-09-09&pm=p-pm&estado=construcao&estado=preparacao&inst=i-vm&equipa=t-1",
      path: "/works",
    });
    await screen.findByText("Obra Alfa");
    const w = windowFrom("weeks", "2026-09-09");
    expect(lastParams()).toEqual({
      from: "2026-09-07", // arredondada à segunda-feira
      to: w.to,
      pm_person_id: "p-pm",
      lifecycle_status: ["construcao", "preparacao"],
      installer_id: "i-vm",
      team_id: "t-1",
    });
    expect(totalDays(w)).toBe(70);
    expect(screen.getByRole("button", { name: "Semanas" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("PM")).toHaveValue("p-pm");
    expect(screen.getByLabelText("Construção")).toBeChecked();
  });

  it("ignora valores inválidos no URL", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works?zoom=anos&from=ontem", path: "/works" });
    await screen.findByText("Obra Alfa");
    const expected = defaultWindow("months", todayIsoLisbon());
    expect(lastParams()).toMatchObject({ from: expected.from, to: expected.to });
    expect(screen.getByRole("button", { name: "Meses" })).toHaveAttribute("aria-pressed", "true");
  });

  it("muda de escala e navega entre períodos", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    const start = defaultWindow("months", todayIsoLisbon());

    fireEvent.click(screen.getByRole("button", { name: "Período seguinte" }));
    await waitFor(() => expect(lastParams().from).toBe(shiftWindow("months", start.from, 1).from));
    fireEvent.click(screen.getByRole("button", { name: "Período anterior" }));
    fireEvent.click(screen.getByRole("button", { name: "Período anterior" }));
    await waitFor(() => expect(lastParams().from).toBe(shiftWindow("months", start.from, -1).from));
    fireEvent.click(screen.getByRole("button", { name: "Hoje" }));
    await waitFor(() => expect(lastParams().from).toBe(start.from));

    fireEvent.click(screen.getByRole("button", { name: "Semanas" }));
    await waitFor(() => expect(lastParams().from).toBe(defaultWindow("weeks", todayIsoLisbon()).from));
    fireEvent.click(screen.getByRole("button", { name: "Trimestres" }));
    await waitFor(() => expect(lastParams().to).toBe(defaultWindow("quarters", todayIsoLisbon()).to));
  });

  it("mostra as equipas sem obras quando pedido", async () => {
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    const region = () => screen.getByRole("region", { name: /Calendário de obras por instalador/ });
    expect(within(region()).queryByText("Equipa 2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Mostrar equipas sem obras"));
    expect(await within(region()).findByText("Equipa 2")).toBeInTheDocument();
  });

  it("lista os projetos por planear, com ligação e o estado", async () => {
    getWorksCalendar.mockResolvedValue(
      calendar([], {
        unscheduled: [
          { project_id: "u1", name: "Sem datas", pm_display_name: "PM Um", lifecycle_status: "preparacao", installer_name: "Instalador A", installer_team_name: null, work_start_date: null, work_end_date: null },
          { project_id: "u2", name: "Só início", pm_display_name: null, lifecycle_status: "construcao", installer_name: null, installer_team_name: null, work_start_date: "2026-10-05", work_end_date: null },
        ],
        summary: { works: 0, conflicts: 0, estimated: 0, unscheduled: 2 },
      })
    );
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    expect(await screen.findByText("Por planear (2)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sem datas" })).toHaveAttribute("href", "/projects/u1");
    expect(screen.getByText("só início 05/10/2026")).toBeInTheDocument();
    // Sem obras no período: estado vazio, mas a lista por planear continua visível.
    expect(screen.getByText("Nenhuma obra neste período")).toBeInTheDocument();
  });

  it("estado vazio com filtros oferece limpá-los", async () => {
    getWorksCalendar.mockResolvedValue(calendar([]));
    renderWithProviders(<Works />, { me: manager(), route: "/works?pm=p-pm", path: "/works" });
    expect(await screen.findByText("Nenhuma obra corresponde aos filtros escolhidos neste período.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Limpar filtros/ })[0]);
    await waitFor(() => expect(lastParams().pm_person_id).toBeUndefined());
  });

  it("mostra o erro do servidor e permite tentar de novo", async () => {
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    getWorksCalendar.mockRejectedValueOnce(new actual.ApiError(403, "Sem permissão para ver o calendário de obras."));
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    expect(await screen.findByText("Sem permissão para ver o calendário de obras.")).toBeInTheDocument();
  });
});
