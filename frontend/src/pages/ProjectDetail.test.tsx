import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Link, MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ToastProvider } from "../components/Toast";
import { StaticSessionProvider } from "../session/SessionContext";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  updateProjectPayment: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getProject.mockResolvedValue(makeProject());
  api.getProjectHistory.mockResolvedValue([]);
  api.listTasks.mockResolvedValue([]);
  api.listPeople.mockResolvedValue([]);
  api.updateProjectPayment.mockResolvedValue({
    milestone: "adjudicacao",
    label: "Adjudicação",
    received: true,
    marked_at: "2026-11-09T12:00:00Z",
    marked_by: "Financeiro Sintético",
  });
});

function CurrentLocation() {
  const location = useLocation();
  return (
    <output data-testid="current-location" data-state={JSON.stringify(location.state)}>
      {`${location.pathname}${location.search}${location.hash}`}
    </output>
  );
}

function FilteredProjectsPage() {
  const { pathname, search, hash } = useLocation();
  return (
    <>
      <p>Lista filtrada</p>
      <Link
        to="/projects/proj-1?context=detail#project"
        state={{ from: { pathname, search, hash } }}
      >
        Abrir projeto
      </Link>
    </>
  );
}

function GoBackOneEntry() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate(-1)}>Voltar no histórico</button>;
}

describe("Detalhe do projeto — cabeçalho e navegação externa", () => {
  it("mantém fotografia só atrás da identificação e coloca workflow e ações em fundo neutro", async () => {
    api.getProject.mockResolvedValue(makeProject({
      has_project_photo: true,
      can_edit_project_photo: true,
      can_delete: true,
      editable_fields: ["name"],
    }));
    const { container } = renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });

    const photo = container.querySelector(".project-primary-photo") as HTMLElement;
    expect(within(photo).getByRole("heading", { level: 1, name: makeProject().name })).toBeInTheDocument();
    expect(within(photo).getByText("Cliente: Cliente Sintético")).toBeInTheDocument();
    expect(within(photo).queryByLabelText("Checklist padrão")).not.toBeInTheDocument();
    expect(within(photo).queryByText("Progresso do workflow")).not.toBeInTheDocument();
    expect(within(photo).queryByRole("button", { name: "Editar projeto" })).not.toBeInTheDocument();
    expect(within(photo).queryByRole("button", { name: "Apagar projeto" })).not.toBeInTheDocument();
    expect(container.querySelector(".project-detail-page__steps")).toBeInTheDocument();
    expect(container.querySelector(".project-detail-page__actions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar projeto" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apagar projeto" })).toBeInTheDocument();
  });
  it("mantém o cabeçalho do projeto e abre a secção indicada pelo deep link", async () => {
    const project = makeProject();
    const { container } = renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all"] }),
      route: "/projects/proj-1?tab=cliente",
      path: "/projects/:projectId",
    });

    await screen.findByRole("heading", { level: 1, name: project.name });

    const page = container.querySelector(".project-detail-page");
    expect(page).toBeInTheDocument();
    expect(within(page as HTMLElement).getByText("Cliente: Cliente Sintético")).toBeInTheDocument();
    expect(within(page as HTMLElement).getByRole("link", { name: /projetos/i })).toHaveAttribute("href", "/projects");

    const tabs = within(page as HTMLElement).getByRole("tablist", { name: "Secções do projeto" });
    await waitFor(() => expect(within(tabs).getByRole("tab", { name: "Cliente" })).toHaveAttribute("aria-selected", "true"));
    expect(within(tabs).getAllByRole("tab")).toHaveLength(7);
    expect(within(page as HTMLElement).getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-cliente");
  });

  it("grava a tab escolhida no URL e o link Projetos restaura a lista filtrada", async () => {
    const origin = "/projects?search=Fotos+Pendentes&status=em_curso&sort_direction=desc#results";
    renderWithProviders(
      <>
        <Routes>
          <Route path="/projects" element={<FilteredProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
        </Routes>
        <CurrentLocation />
      </>,
      { me: makeMe({ permissions: ["project.view_all"] }), route: origin },
    );

    fireEvent.click(await screen.findByRole("link", { name: "Abrir projeto" }));
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("tab", { name: "Cliente" }));

    await waitFor(() =>
      expect(screen.getByTestId("current-location")).toHaveTextContent(
        "/projects/proj-1?context=detail&tab=cliente#project"
      )
    );
    expect(screen.getByRole("link", { name: /projetos/i })).toHaveAttribute("href", origin);

    fireEvent.click(screen.getByRole("link", { name: /projetos/i }));
    await waitFor(() => expect(screen.getByTestId("current-location")).toHaveTextContent(origin));
    expect(screen.getByText("Lista filtrada")).toBeInTheDocument();
  });

  it("mantém a tab escolhida ao abrir novamente o URL, como num refresh", async () => {
    const firstMount = renderWithProviders(
      <>
        <ProjectDetail />
        <CurrentLocation />
      </>,
      {
        me: makeMe({ permissions: ["project.view_all"] }),
        route: "/projects/proj-1?filter=ativos",
        path: "/projects/:projectId",
      }
    );
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("tab", { name: "Cliente" }));
    await waitFor(() =>
      expect(screen.getByTestId("current-location")).toHaveTextContent("/projects/proj-1?filter=ativos&tab=cliente")
    );
    const reloadUrl = screen.getByTestId("current-location").textContent as string;
    firstMount.unmount();

    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all"] }),
      route: reloadUrl,
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    await waitFor(() => expect(screen.getByRole("tab", { name: "Cliente" })).toHaveAttribute("aria-selected", "true"));
  });

  it("substitui o histórico ao trocar de tab em vez de criar uma entrada por tab", async () => {
    const origin = { pathname: "/projects", search: "?search=Fotos+Pendentes", hash: "#results" };
    render(
      <MemoryRouter
        initialEntries={[
          { ...origin },
          { pathname: "/projects/proj-1", search: "?source=lista", hash: "#detalhe", state: { from: origin } },
        ]}
        initialIndex={1}
      >
        <StaticSessionProvider me={makeMe({ permissions: ["project.view_all"] })}>
          <ToastProvider>
            <Routes>
              <Route path="/projects" element={<p>Lista filtrada anterior</p>} />
              <Route path="/projects/:projectId" element={<ProjectDetail />} />
            </Routes>
            <CurrentLocation />
            <GoBackOneEntry />
          </ToastProvider>
        </StaticSessionProvider>
      </MemoryRouter>
    );

    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("tab", { name: "Cliente" }));
    await waitFor(() =>
      expect(screen.getByTestId("current-location")).toHaveTextContent(
        "/projects/proj-1?source=lista&tab=cliente#detalhe"
      )
    );
    expect(screen.getByTestId("current-location")).toHaveAttribute("data-state", JSON.stringify({ from: origin }));

    fireEvent.click(screen.getByRole("button", { name: "Voltar no histórico" }));
    expect(await screen.findByText("Lista filtrada anterior")).toBeInTheDocument();
    expect(screen.getByTestId("current-location")).toHaveTextContent("/projects?search=Fotos+Pendentes#results");
  });

  it("mostra Pagamentos como toggles para editor e apenas leitura para leitor", async () => {
    api.getProject.mockResolvedValue(makeProject({
      payments: { adjudicacao: false, entrada_obra: false, fim_obra: false, certificado_final: false },
      can_edit_payments: true,
    }));
    const editor = renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all", "payment.view", "payment.edit"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    const editable = await screen.findByRole("checkbox", { name: "Adjudicação" });
    expect(editable).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Pagamentos" })).toBeInTheDocument();
    fireEvent.click(editable);
    await waitFor(() => expect(editable).toBeChecked());
    expect(api.updateProjectPayment).toHaveBeenCalledWith("proj-1", "adjudicacao", true);
    editor.unmount();

    api.getProject.mockResolvedValue(makeProject({
      payments: { adjudicacao: true, entrada_obra: false, fim_obra: false, certificado_final: false },
      can_edit_payments: false,
    }));
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all", "payment.view"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    expect(await screen.findByRole("checkbox", { name: "Adjudicação" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Adjudicação" })).toBeChecked();
  });

  it("esconde Pagamentos sem payment.view", async () => {
    api.getProject.mockResolvedValue(makeProject({ payments: null, can_edit_payments: false }));
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    expect(screen.queryByRole("heading", { name: "Pagamentos" })).not.toBeInTheDocument();
  });

  it("atualiza o toggle de forma otimista e repõe o valor se o PUT falhar", async () => {
    api.getProject.mockResolvedValue(makeProject({
      payments: { adjudicacao: false, entrada_obra: false, fim_obra: false, certificado_final: false },
      can_edit_payments: true,
    }));
    api.updateProjectPayment.mockRejectedValue(new Error("Falha sintética de gravação"));
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all", "payment.view", "payment.edit"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });

    const checkbox = await screen.findByRole("checkbox", { name: "Adjudicação" });
    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeChecked());
    expect(await screen.findByText("Falha sintética de gravação")).toBeInTheDocument();
    await waitFor(() => expect(checkbox).not.toBeChecked());
    expect(api.updateProjectPayment).toHaveBeenCalledWith("proj-1", "adjudicacao", true);
  });
});
