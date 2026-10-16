import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Installer, type WorkItem, type WorksCalendar } from "../api/client";
import { ToastProvider } from "../components/Toast";
import { StaticSessionProvider } from "../session/SessionContext";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { todayIsoLisbon } from "../utils/dates";
import { addDays, defaultWindow, shiftWindow, totalDays, windowFrom } from "../utils/worksTimeline";
import Works from "./Works";

const {
  getWorksCalendar,
  listInstallers,
  listPeople,
  getLifecycleStatuses,
  updateProjectWorkPlan,
  getWorksPreferences,
  updateWorksPreferences,
  listSavedWorksViews,
  createSavedWorksView,
  applySavedWorksView,
  updateSavedWorksView,
  deleteSavedWorksView,
} = vi.hoisted(() => ({
  updateProjectWorkPlan: vi.fn(),
  getWorksCalendar: vi.fn(),
  listInstallers: vi.fn(),
  listPeople: vi.fn(),
  getLifecycleStatuses: vi.fn(),
  getWorksPreferences: vi.fn(),
  updateWorksPreferences: vi.fn(),
  listSavedWorksViews: vi.fn(),
  createSavedWorksView: vi.fn(),
  applySavedWorksView: vi.fn(),
  updateSavedWorksView: vi.fn(),
  deleteSavedWorksView: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getWorksCalendar,
    listInstallers,
    listPeople,
    getLifecycleStatuses,
    updateProjectWorkPlan,
    getWorksPreferences,
    updateWorksPreferences,
    listSavedWorksViews,
    createSavedWorksView,
    applySavedWorksView,
    updateSavedWorksView,
    deleteSavedWorksView,
  };
});

// O jsdom não implementa PointerEvent: sem isto o clientX/clientY dos eventos perdia-se.
if (typeof window.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  (window as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill;
}

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderWorksForAccount(me: ReturnType<typeof makeMe>) {
  return render(
    <MemoryRouter initialEntries={["/works"]}>
      <StaticSessionProvider me={me}>
        <ToastProvider>
          <Routes>
            <Route path="/works" element={<Works />} />
          </Routes>
        </ToastProvider>
      </StaticSessionProvider>
    </MemoryRouter>
  );
}

describe("Works (calendário de obras)", () => {
  it("aplica uma vista nomeada, atualiza filtros e recarrega sem perder a data escolhida", async () => {
    listSavedWorksViews.mockResolvedValue([
      {
        id: "view-team",
        name: "A minha equipa",
        zoom: "quarters",
        lifecycle_status: ["construcao"],
        pm_person_id: "p-pm",
        installer_id: "i-vm",
        team_id: "t-1",
        show_idle: true,
        created_at: "2026-10-15T09:00:00Z",
        updated_at: "2026-10-15T09:00:00Z",
      },
    ]);
    applySavedWorksView.mockResolvedValue({
      zoom: "quarters",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
    });

    renderWithProviders(<Works />, { me: manager(), route: "/works?zoom=weeks&from=2026-10-05", path: "/works" });
    await screen.findByRole("option", { name: "A minha equipa" });
    const callsBeforeApply = getWorksCalendar.mock.calls.length;
    fireEvent.change(screen.getByLabelText("Vistas guardadas"), { target: { value: "view-team" } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar vista" }));

    await waitFor(() => expect(applySavedWorksView).toHaveBeenCalledWith("view-team"));
    expect(await screen.findByRole("button", { name: "Trimestres" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("PM")).toHaveValue("p-pm");
    expect(screen.getByLabelText("Mostrar equipas sem obras")).toBeChecked();
    await waitFor(() => expect(getWorksCalendar.mock.calls.length).toBeGreaterThan(callsBeforeApply));
    expect(lastParams()).toMatchObject({
      from: windowFrom("quarters", "2026-10-05").from,
      pm_person_id: "p-pm",
      lifecycle_status: ["construcao"],
      installer_id: "i-vm",
      team_id: "t-1",
    });
  });

  it("carrega e mostra as vistas pessoais nomeadas", async () => {
    listSavedWorksViews.mockResolvedValue([
      {
        id: "view-team",
        name: "A minha equipa",
        zoom: "months",
        lifecycle_status: ["construcao"],
        pm_person_id: null,
        installer_id: "i-vm",
        team_id: "t-1",
        show_idle: false,
        created_at: "2026-10-15T09:00:00Z",
        updated_at: "2026-10-15T09:00:00Z",
      },
      {
        id: "view-month",
        name: "Obras deste mês",
        zoom: "month_days",
        lifecycle_status: [],
        pm_person_id: null,
        installer_id: null,
        team_id: null,
        show_idle: true,
        created_at: "2026-10-14T09:00:00Z",
        updated_at: "2026-10-14T09:00:00Z",
      },
    ]);

    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });

    expect(await screen.findByRole("option", { name: "A minha equipa" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Obras deste mês" })).toBeInTheDocument();
    expect(listSavedWorksViews).toHaveBeenCalledTimes(1);
  });

  it("guarda a vista atual como nomeada sem alterar a preferência ativa", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "month_days",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
    });
    createSavedWorksView.mockResolvedValue({
      id: "view-new",
      name: "A minha equipa",
      zoom: "month_days",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
      created_at: "2026-10-15T09:00:00Z",
      updated_at: "2026-10-15T09:00:00Z",
    });
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("A minha equipa");

    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    fireEvent.click(screen.getByRole("button", { name: /Guardar vista atual como/ }));

    await waitFor(() =>
      expect(createSavedWorksView).toHaveBeenCalledWith({
        name: "A minha equipa",
        zoom: "month_days",
        lifecycle_status: ["construcao"],
        pm_person_id: "p-pm",
        installer_id: "i-vm",
        team_id: "t-1",
        show_idle: true,
      })
    );
    expect(updateWorksPreferences).not.toHaveBeenCalled();
    expect(await screen.findByRole("option", { name: "A minha equipa" })).toBeInTheDocument();
    expect(prompt).toHaveBeenCalledWith("Nome da vista:");
    prompt.mockRestore();
  });

  it("renomeia uma vista nomeada apenas depois da confirmação do PATCH", async () => {
    const existing = {
      id: "view-team",
      name: "A minha equipa",
      zoom: "months" as const,
      lifecycle_status: ["construcao"],
      pm_person_id: null,
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: false,
      created_at: "2026-10-15T09:00:00Z",
      updated_at: "2026-10-15T09:00:00Z",
    };
    listSavedWorksViews.mockResolvedValue([existing]);
    updateSavedWorksView.mockResolvedValue({ ...existing, name: "Equipa de campo" });
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Equipa de campo");

    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByRole("option", { name: "A minha equipa" });
    fireEvent.change(screen.getByLabelText("Vistas guardadas"), { target: { value: "view-team" } });
    fireEvent.click(screen.getByRole("button", { name: "Renomear vista" }));

    await waitFor(() => expect(updateSavedWorksView).toHaveBeenCalledWith("view-team", { name: "Equipa de campo" }));
    expect(await screen.findByRole("option", { name: "Equipa de campo" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "A minha equipa" })).not.toBeInTheDocument();
    expect(prompt).toHaveBeenCalledWith("Novo nome da vista:", "A minha equipa");
    prompt.mockRestore();
  });

  it("elimina uma vista nomeada apenas depois do DELETE confirmado", async () => {
    const existing = {
      id: "view-team",
      name: "A minha equipa",
      zoom: "months" as const,
      lifecycle_status: ["construcao"],
      pm_person_id: null,
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: false,
      created_at: "2026-10-15T09:00:00Z",
      updated_at: "2026-10-15T09:00:00Z",
    };
    listSavedWorksViews.mockResolvedValue([existing]);
    deleteSavedWorksView.mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByRole("option", { name: "A minha equipa" });
    fireEvent.change(screen.getByLabelText("Vistas guardadas"), { target: { value: "view-team" } });
    fireEvent.click(screen.getByRole("button", { name: "Eliminar vista" }));

    await waitFor(() => expect(deleteSavedWorksView).toHaveBeenCalledWith("view-team"));
    expect(screen.queryByRole("option", { name: "A minha equipa" })).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledWith("Eliminar a vista «A minha equipa»?");
    confirm.mockRestore();
  });

  it("mostra erro ao guardar uma vista nomeada e não altera a lista sem resposta confirmada", async () => {
    createSavedWorksView.mockRejectedValue(new ApiError(503, "Vistas nomeadas indisponíveis."));
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Obras deste mês");

    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    fireEvent.click(screen.getByRole("button", { name: /Guardar vista atual como/ }));

    expect(await screen.findByText("Vistas nomeadas indisponíveis.")).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Obras deste mês" })).not.toBeInTheDocument();
    prompt.mockRestore();
  });

  beforeEach(() => {
    [
      getWorksCalendar,
      listInstallers,
      listPeople,
      getLifecycleStatuses,
      updateProjectWorkPlan,
      getWorksPreferences,
      updateWorksPreferences,
      listSavedWorksViews,
      createSavedWorksView,
      applySavedWorksView,
      updateSavedWorksView,
      deleteSavedWorksView,
    ].forEach((m) => m.mockReset());
    listSavedWorksViews.mockResolvedValue([]);
    listInstallers.mockResolvedValue(INSTALLERS);
    listPeople.mockResolvedValue([{ id: "p-pm", display_name: "PM Um", email: null, is_active: true }]);
    getLifecycleStatuses.mockResolvedValue(STATUSES);
    // O fixture legado não tem o endpoint de preferências; a falha explícita
    // exercita o fallback local sem iniciar um fetch real nos testes antigos.
    getWorksPreferences.mockRejectedValue(new ApiError(404, "Preferências indisponíveis"));
    updateWorksPreferences.mockResolvedValue({
      zoom: "months",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
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

    fireEvent.click(screen.getByText("Todos", { selector: "summary" }));
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
    fireEvent.click(await screen.findByText("2 estados", { selector: "summary" }));
    expect(screen.getByLabelText("Construção")).toBeChecked();
  });

  it("aplica a vista guardada quando não há parâmetros e mantém a data no mês atual", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "month_days",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
    });
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    fireEvent.click(await screen.findByText("Construção", { selector: "summary" }));
    expect(screen.getByRole("button", { name: "Mês — dias" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("PM")).toHaveValue("p-pm");
    expect(screen.getByLabelText("Construção")).toBeChecked();
    expect(screen.getByLabelText("Mostrar equipas sem obras")).toBeChecked();
    expect(lastParams().lifecycle_status).toEqual(["construcao"]);
    expect(lastParams().from).toBe(defaultWindow("month_days", todayIsoLisbon()).from);
    expect(lastParams().to).toBe(defaultWindow("month_days", todayIsoLisbon()).to);
  });

  it("dá precedência aos parâmetros partilhados sobre a vista guardada", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "month_days",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
    });
    renderWithProviders(<Works />, {
      me: manager(),
      route: "/works?zoom=weeks&from=2026-09-09&pm=&estado=preparacao&idle=0",
      path: "/works",
    });
    await screen.findByText("Obra Alfa");
    fireEvent.click(await screen.findByText("Preparação", { selector: "summary" }));
    expect(screen.getByRole("button", { name: "Semanas" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Construção")).not.toBeChecked();
    expect(screen.getByLabelText("Preparação")).toBeChecked();
    expect(screen.getByLabelText("Mostrar equipas sem obras")).not.toBeChecked();
  });

  it("só mostra sucesso ao fixar depois do PATCH confirmado e envia o DTO completo", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "month_days",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    let resolveSave: ((value: unknown) => void) | undefined;
    updateWorksPreferences.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSave = resolve;
        })
    );
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    await waitFor(() => expect(screen.getByRole("button", { name: "Mês — dias" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.change(screen.getByLabelText("PM"), { target: { value: "p-pm" } });
    fireEvent.click(screen.getByRole("button", { name: "Fixar vista" }));
    expect(updateWorksPreferences).toHaveBeenCalledWith({
      zoom: "month_days",
      lifecycle_status: [],
      pm_person_id: "p-pm",
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    expect(screen.queryByText("Vista guardada.")).not.toBeInTheDocument();
    resolveSave?.({
      zoom: "month_days",
      lifecycle_status: [],
      pm_person_id: "p-pm",
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    expect(await screen.findByText("Vista guardada.")).toBeInTheDocument();
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

  it.each([401, 503])("mostra o detalhe real e permite retry num GET %s do calendário", async (status) => {
    getWorksPreferences.mockResolvedValue({
      zoom: "months",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    getWorksCalendar.mockReset();
    getWorksCalendar.mockRejectedValueOnce(new ApiError(status, `GET ${status} — indisponível`)).mockResolvedValueOnce(calendar([work("retry", todayIsoLisbon(), todayIsoLisbon())]));
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });

    expect(await screen.findByText(`GET ${status} — indisponível`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByText("Obra retry")).toBeInTheDocument();
    expect(getWorksCalendar).toHaveBeenCalledTimes(2);
  });

  it.each([401, 503])("mostra o detalhe real e só confirma um PATCH %s depois do retry", async (status) => {
    getWorksPreferences.mockResolvedValue({
      zoom: "months",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    updateWorksPreferences.mockRejectedValueOnce(new ApiError(status, `PATCH ${status} — vista recusada`)).mockResolvedValueOnce({
      zoom: "months",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");

    fireEvent.click(screen.getByRole("button", { name: "Fixar vista" }));
    expect(await screen.findByText(`PATCH ${status} — vista recusada`)).toBeInTheDocument();
    expect(screen.queryByText("Vista guardada.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tentar guardar" }));
    await waitFor(() => expect(screen.getByText("Vista guardada.")).toBeInTheDocument());
    expect(updateWorksPreferences).toHaveBeenCalledTimes(2);
  });

  it("não deixa a preferência atrasada substituir uma interação feita antes do GET terminar", async () => {
    const preference = deferred<Parameters<typeof getWorksPreferences.mockResolvedValue>[0]>();
    getWorksPreferences.mockReturnValue(preference.promise);
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });

    await screen.findByRole("option", { name: "PM Um" });
    fireEvent.change(screen.getByLabelText("PM"), { target: { value: "p-pm" } });
    await waitFor(() => expect(lastParams().pm_person_id).toBe("p-pm"));
    preference.resolve({
      zoom: "weeks",
      lifecycle_status: ["preparacao"],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });

    await waitFor(() => expect(screen.getByLabelText("PM")).toHaveValue("p-pm"));
    expect(screen.getByRole("button", { name: "Meses" })).toHaveAttribute("aria-pressed", "true");
    expect(lastParams().pm_person_id).toBe("p-pm");
  });

  it("isola a conta nova e ignora uma resposta em voo da conta anterior", async () => {
    const userA = makeMe({ user_id: "u-a", email: "a@example.invalid", person_id: "p-a" });
    const userB = makeMe({ user_id: "u-b", email: "b@example.invalid", person_id: "p-b" });
    const preferenceA = deferred<Awaited<ReturnType<typeof getWorksPreferences>>>();
    const preferenceB = deferred<Awaited<ReturnType<typeof getWorksPreferences>>>();
    getWorksPreferences.mockReset();
    getWorksPreferences.mockReturnValueOnce(preferenceA.promise).mockReturnValueOnce(preferenceB.promise);

    const view = renderWorksForAccount(userA);
    view.rerender(
      <MemoryRouter initialEntries={["/works"]}>
        <StaticSessionProvider me={userB}>
          <ToastProvider>
            <Routes>
              <Route path="/works" element={<Works />} />
            </Routes>
          </ToastProvider>
        </StaticSessionProvider>
      </MemoryRouter>
    );

    preferenceA.resolve({
      zoom: "weeks",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
    });
    await Promise.resolve();
    expect(getWorksCalendar).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Meses" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("PM")).toHaveValue("");

    preferenceB.resolve({
      zoom: "quarters",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    expect(await screen.findByText("Obra Alfa")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Trimestres" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("PM")).toHaveValue("");
  });

  it("mantém uma referência guardada inativa limpável e com reset explícito", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "month_days",
      lifecycle_status: [],
      pm_person_id: "inactive-uuid",
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");

    expect(screen.getByRole("button", { name: "Limpar filtros" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Repor vista" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    await waitFor(() => expect(lastParams().pm_person_id).toBeUndefined());
    fireEvent.click(screen.getByRole("button", { name: "Repor vista" }));
    await waitFor(() => expect(updateWorksPreferences).toHaveBeenCalledWith({
      zoom: "month_days",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    }));
  });

  it("mantém o calendário visível quando guardar uma referência inativa dá 422", async () => {
    updateWorksPreferences.mockRejectedValueOnce(new ApiError(422, "A referência guardada deixou de estar ativa."));
    renderWithProviders(<Works />, { me: manager(), route: "/works?pm=inactive-uuid", path: "/works" });
    expect(await screen.findByText("Obra Alfa")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fixar vista" }));
    expect(await screen.findByText("A referência guardada deixou de estar ativa.")).toBeInTheDocument();
    expect(screen.getByText("Obra Alfa")).toBeInTheDocument();
  });

  it("trata qualquer chave de vista explícita no URL como vista completa, com defaults documentados", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "month_days",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: "i-vm",
      team_id: "t-1",
      show_idle: true,
    });
    renderWithProviders(<Works />, { me: manager(), route: "/works?pm=p-pm", path: "/works" });
    await screen.findByText("Obra Alfa");

    // A URL parcial é autoritativa: as chaves ausentes usam os defaults de
    // viewFromParams (meses, sem filtros), não a preferência guardada.
    expect(screen.getByRole("button", { name: "Meses" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("PM")).toHaveValue("p-pm");
    expect(lastParams().lifecycle_status).toBeUndefined();
    expect(lastParams().from).toBe(defaultWindow("months", todayIsoLisbon()).from);
  });

  it("só limpa a vista guardada localmente depois do PATCH de reset ser confirmado", async () => {
    getWorksPreferences.mockResolvedValue({
      zoom: "weeks",
      lifecycle_status: ["construcao"],
      pm_person_id: "p-pm",
      installer_id: null,
      team_id: null,
      show_idle: true,
    });
    const reset = deferred<Awaited<ReturnType<typeof updateWorksPreferences>>>();
    updateWorksPreferences.mockReturnValue(reset.promise);
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra Alfa");
    fireEvent.click(screen.getByRole("button", { name: "Repor vista" }));
    expect(screen.getByRole("button", { name: "Semanas" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Vista reposta.")).not.toBeInTheDocument();

    reset.resolve({
      zoom: "month_days",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    await waitFor(() => expect(screen.getByText("Vista reposta.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Mês — dias" })).toHaveAttribute("aria-pressed", "true");
  });

  it("mantém linhas antigas, indicador de refresh e fallback stale durante refresh tardio", async () => {
    const refresh = deferred<WorksCalendar>();
    getWorksPreferences.mockResolvedValue({
      zoom: "months",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    getWorksCalendar.mockReset();
    getWorksCalendar.mockResolvedValueOnce(calendar([work("old", todayIsoLisbon(), todayIsoLisbon(), { name: "Obra antiga" })]));
    getWorksCalendar.mockReturnValueOnce(refresh.promise);
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    expect(await screen.findByText("Obra antiga")).toBeInTheDocument();

    window.dispatchEvent(new CustomEvent("op:works-project-refresh"));
    expect(await screen.findByRole("status", { name: "A atualizar obras…" })).toBeInTheDocument();
    expect(screen.getByText("Obra antiga")).toBeInTheDocument();
    refresh.reject(new ApiError(503, "Refresh indisponível"));
    expect(await screen.findByText("Refresh indisponível")).toBeInTheDocument();
    expect(screen.getByText("Obra antiga")).toBeInTheDocument();
    expect(screen.getByText(/versão confirmada/i)).toBeInTheDocument();
  });

  it("restaura scroll vertical e horizontal capturados só se o utilizador não os mudou", async () => {
    const refresh = deferred<WorksCalendar>();
    getWorksPreferences.mockResolvedValue({
      zoom: "months",
      lifecycle_status: [],
      pm_person_id: null,
      installer_id: null,
      team_id: null,
      show_idle: false,
    });
    getWorksCalendar.mockReset();
    getWorksCalendar.mockResolvedValueOnce(calendar([work("old", todayIsoLisbon(), todayIsoLisbon(), { name: "Obra antiga" })]));
    getWorksCalendar.mockReturnValueOnce(refresh.promise);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    let currentY = 240;
    Object.defineProperty(window, "scrollY", { configurable: true, get: () => currentY });
    renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
    await screen.findByText("Obra antiga");
    const scroller = document.querySelector<HTMLElement>(".works__scroll");
    expect(scroller).toBeTruthy();
    scroller!.scrollLeft = 37;

    window.dispatchEvent(new CustomEvent("op:works-project-refresh"));
    currentY = 92;
    scroller!.scrollLeft = 0;
    refresh.resolve(calendar([work("new", todayIsoLisbon(), todayIsoLisbon(), { name: "Obra nova" })]));
    await screen.findByText("Obra nova");
    expect(scrollTo).toHaveBeenCalledWith({ left: 0, top: 240, behavior: "auto" });
    expect(scroller!.scrollLeft).toBe(37);

    scrollTo.mockClear();
    const second = deferred<WorksCalendar>();
    getWorksCalendar.mockReturnValueOnce(second.promise);
    currentY = 240;
    scroller!.scrollLeft = 37;
    window.dispatchEvent(new CustomEvent("op:works-project-refresh"));
    fireEvent.wheel(window);
    currentY = 400;
    scroller!.scrollLeft = 80;
    second.resolve(calendar([work("newer", todayIsoLisbon(), todayIsoLisbon(), { name: "Obra mais nova" })]));
    await screen.findByText("Obra mais nova");
    expect(scrollTo).not.toHaveBeenCalled();
    expect(scroller!.scrollLeft).toBe(80);
    scrollTo.mockRestore();
  });

  describe("arrastar para replanear", () => {
    const dragBar = (name: string, dx: number) => {
      const bar = screen.getByRole("link", { name: new RegExp(name) });
      fireEvent.pointerDown(bar, { button: 0, clientX: 100, clientY: 0, pointerId: 1 });
      fireEvent.pointerMove(bar, { clientX: 100 + dx, clientY: 0, pointerId: 1 });
      fireEvent.pointerUp(bar, { clientX: 100 + dx, clientY: 0, pointerId: 1 });
      return bar;
    };
    const withRights = (can: boolean) => {
      const today = todayIsoLisbon();
      getWorksCalendar.mockResolvedValue(calendar([work("a", today, today, { name: "Obra Alfa", can_plan_work: can })]));
    };

    it("grava as novas datas ao largar e oferece Anular", async () => {
      withRights(true);
      updateProjectWorkPlan.mockResolvedValue({});
      renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
      await screen.findByText("Obra Alfa");
      dragBar("Obra Alfa", 12); // 12 px = 2 dias na escala de meses (6 px/dia)
      await waitFor(() => expect(updateProjectWorkPlan).toHaveBeenCalledTimes(1));
      const today = todayIsoLisbon();
      const [id, body] = updateProjectWorkPlan.mock.calls[0];
      expect(id).toBe("a");
      expect(body.work_start_date).toBe(addDays(today, 2));
      expect(body.work_end_date).toBe(addDays(today, 2));
      expect(body).not.toHaveProperty("installer_id");

      fireEvent.click(await screen.findByRole("button", { name: "Anular" }));
      await waitFor(() => expect(updateProjectWorkPlan).toHaveBeenCalledTimes(2));
      expect(updateProjectWorkPlan.mock.calls[1]).toEqual(["a", { work_start_date: today, work_end_date: today }]);
    });

    it("um clique sem arrastar não grava nada", async () => {
      withRights(true);
      renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
      await screen.findByText("Obra Alfa");
      dragBar("Obra Alfa", 1);
      expect(updateProjectWorkPlan).not.toHaveBeenCalled();
    });

    it("sem permissão para planear a barra não é arrastável", async () => {
      withRights(false);
      renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
      await screen.findByText("Obra Alfa");
      dragBar("Obra Alfa", 30);
      expect(updateProjectWorkPlan).not.toHaveBeenCalled();
    });

    it("mostra o erro do servidor e não oferece Anular", async () => {
      withRights(true);
      updateProjectWorkPlan.mockRejectedValue(new ApiError(422, "O fim da obra não pode ser anterior ao início."));
      renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
      await screen.findByText("Obra Alfa");
      dragBar("Obra Alfa", 30);
      expect(await screen.findByText("O fim da obra não pode ser anterior ao início.")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Anular" })).toBeNull();
    });

    it("mostra uma barra por afectação sem enviar a edição legada da obra", async () => {
      const today = todayIsoLisbon();
      getWorksCalendar.mockResolvedValue(
        calendar([
          work("same-project", today, addDays(today, 4), {
            name: "Obra com duas equipas",
            assignment_id: "assignment-a",
            assignment_start_date: today,
            assignment_end_date: addDays(today, 1),
            team_id: "t-1",
            team_name: "Equipa 1",
            can_plan_work: true,
          }),
          work("same-project", today, addDays(today, 4), {
            name: "Obra com duas equipas",
            assignment_id: "assignment-b",
            assignment_start_date: addDays(today, 3),
            assignment_end_date: addDays(today, 4),
            team_id: "t-2",
            team_name: "Equipa 2",
            can_plan_work: true,
          }),
        ])
      );
      renderWithProviders(<Works />, { me: manager(), route: "/works", path: "/works" });
      const bars = await screen.findAllByRole("link", { name: /Obra com duas equipas/ });
      expect(bars).toHaveLength(2);
      expect(new Set(bars.map((bar) => bar.getAttribute("data-entry-key")))).toEqual(new Set(["assignment-a", "assignment-b"]));
      expect(bars[0]).not.toHaveClass("works__bar--draggable");

      fireEvent.pointerDown(bars[0], { button: 0, clientX: 100, clientY: 0, pointerId: 1 });
      fireEvent.pointerMove(bars[0], { clientX: 130, clientY: 0, pointerId: 1 });
      fireEvent.pointerUp(bars[0], { clientX: 130, clientY: 0, pointerId: 1 });
      expect(updateProjectWorkPlan).not.toHaveBeenCalled();
    });
  });
});
