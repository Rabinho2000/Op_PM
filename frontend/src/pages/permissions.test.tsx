// Permissões básicas na interface: a UI só oferece o que o servidor
// indica como permitido (editable_fields, can_manage_tasks, can_edit,
// can_cancel, permissões de /me). O servidor continua a validar tudo.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Absence } from "../api/client";
import { COMERCIAL_ME, makeMe, makeProject, makeSummary, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Login from "./Login";
import ProjectDetail from "./ProjectDetail";
import Vacations from "./Vacations";

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  updateTask: vi.fn(),
  listAbsences: vi.fn(),
  getDashboardSummary: vi.fn(),
  getHealth: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

const PM_FIELDS = ["equipment_notes", "injection_notes", "notes", "om_notes", "role"];

function absence(overrides: Partial<Absence> = {}): Absence {
  return {
    id: "abs-1",
    person_id: "p-comercial",
    start_date: "2099-01-10",
    end_date: "2099-01-12",
    type: "ferias",
    note: "",
    status: "aprovada",
    created_by_person_id: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    person_display_name: "Comercial Sintético",
    can_cancel: false,
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getProjectHistory.mockResolvedValue([]);
  api.listPeople.mockResolvedValue([]);
  api.listTasks.mockResolvedValue([makeTask()]);
  api.getDashboardSummary.mockResolvedValue(makeSummary());
});

describe("Detalhe do projeto — permissões", () => {
  it("perfil só de leitura não vê edição nem criação de tarefas", async () => {
    api.getProject.mockResolvedValue(makeProject({ editable_fields: [], can_manage_tasks: false }));
    api.listTasks.mockResolvedValue([makeTask({ can_edit: false })]);
    renderWithProviders(<ProjectDetail />, { me: COMERCIAL_ME, route: "/projects/proj-1", path: "/projects/:projectId" });

    expect(await screen.findByRole("heading", { name: "Instalação Sintética de Teste" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Editar projeto/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Tarefas/ }));
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /Nova tarefa/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Estado da tarefa Visita técnica")).not.toBeInTheDocument();
  });

  it("PM só pode editar os campos de acompanhamento indicados pelo servidor", async () => {
    api.getProject.mockResolvedValue(makeProject({ editable_fields: PM_FIELDS, can_manage_tasks: true }));
    renderWithProviders(<ProjectDetail />, { me: makeMe(), route: "/projects/proj-1", path: "/projects/:projectId" });

    fireEvent.click(await screen.findByRole("button", { name: /Editar projeto/ }));
    const dialog = screen.getByRole("dialog", { name: "Editar projeto" });
    expect(within(dialog).getByLabelText("Notas")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Nome")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Email")).not.toBeInTheDocument();
    expect(within(dialog).getByText(/Como PM deste projeto/)).toBeInTheDocument();
  });

  it("mostra o aviso de fotografias e permite concluir a tarefa das fotos", async () => {
    api.getProject.mockResolvedValue(makeProject({ photos_pending_warning: true, editable_fields: [] }));
    api.listTasks.mockResolvedValue([
      makeTask({ id: "t-fotos", title: "Colocar fotos na Drive", task_type: "fotos_drive" }),
    ]);
    api.updateTask.mockResolvedValue(makeTask({ id: "t-fotos", title: "Colocar fotos na Drive", status: "done" }));
    renderWithProviders(<ProjectDetail />, { me: makeMe(), route: "/projects/proj-1", path: "/projects/:projectId" });

    expect(await screen.findByText("Fotografias por colocar na Drive")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Marcar como colocadas/ }));
    await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith("t-fotos", { status: "done" }));
    expect(await screen.findByText("Tarefa concluída: Colocar fotos na Drive")).toBeInTheDocument();
  });

  it("sem permissão sobre a tarefa das fotos, o aviso não oferece a ação", async () => {
    api.getProject.mockResolvedValue(makeProject({ photos_pending_warning: true }));
    api.listTasks.mockResolvedValue([makeTask({ task_type: "fotos_drive", can_edit: false })]);
    renderWithProviders(<ProjectDetail />, { me: COMERCIAL_ME, route: "/projects/proj-1", path: "/projects/:projectId" });

    expect(await screen.findByText("Fotografias por colocar na Drive")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Marcar como colocadas/ })).not.toBeInTheDocument();
  });
});

describe("Férias — permissões", () => {
  it("perfil com gestão própria regista só para si e não escolhe pessoa", async () => {
    api.listAbsences.mockResolvedValue([absence({ can_cancel: true })]);
    renderWithProviders(<Vacations />, { me: COMERCIAL_ME });

    expect(await screen.findByText(/não tem acesso às ausências de outras pessoas/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Registar ausência/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText("Pessoa")).toBeDisabled();
    expect(within(dialog).getByLabelText("Pessoa")).toHaveValue("Comercial Sintético");
    expect(api.listPeople).not.toHaveBeenCalled(); // não pede a lista de pessoas sem absence.manage_all
  });

  it("só mostra 'Cancelar' quando o servidor o permite", async () => {
    api.listAbsences.mockResolvedValue([
      absence({ id: "a1", can_cancel: true, person_display_name: "Pessoa Com Permissão" }),
      absence({ id: "a2", can_cancel: false, person_display_name: "Outra Pessoa" }),
    ]);
    renderWithProviders(<Vacations />, { me: makeMe() });

    const allowedRow = (await screen.findByText("Pessoa Com Permissão", { selector: "td span" })).closest("tr")!;
    const deniedRow = screen.getByText("Outra Pessoa", { selector: "td span" }).closest("tr")!;
    expect(within(allowedRow).getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
    expect(within(deniedRow).queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });

  it("sem permissão de gestão não oferece registo de ausências", async () => {
    api.listAbsences.mockResolvedValue([]);
    renderWithProviders(<Vacations />, { me: makeMe({ permissions: ["absence.view_own"] }) });
    expect(await screen.findByText("Sem ausências registadas.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Registar ausência/ })).not.toBeInTheDocument();
  });
});

describe("Login — separação entre demo e login Microsoft", () => {
  it("mostra os utilizadores de demonstração só quando o servidor aceita o modo demo", async () => {
    api.getHealth.mockResolvedValue({
      status: "ok",
      app_env: "local",
      database_dialect: "sqlite",
      integrations: {},
      dev_login_available: true,
    });
    renderWithProviders(<Login />);
    expect(screen.getByRole("button", { name: /Entrar com Microsoft/ })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Chefe de Operações/ })).toBeInTheDocument();
    expect(screen.getByText("Modo demonstração (apenas local)")).toBeInTheDocument();
  });

  it("esconde o modo demo quando o servidor o recusa (staging/produção)", async () => {
    api.getHealth.mockResolvedValue({
      status: "ok",
      app_env: "staging",
      database_dialect: "postgresql",
      integrations: {},
      dev_login_available: false,
    });
    renderWithProviders(<Login />);
    expect(await screen.findByText("Este servidor não aceita o modo demonstração.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Chefe de Operações/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Entrar com Microsoft/ })).toBeInTheDocument();
  });
});
