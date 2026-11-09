// Painel "Licenciamento e comunicações": render por bloco, permissões (flags can_* do servidor),
// cartões SIM com Ver PIN/PUK (mascarado, 30 s, 503), credenciais com email, excedente.
// Dados sintéticos apenas.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, ProjectCommunicationData, ProjectLicensingData } from "../api/client";
import { ToastProvider } from "./Toast";
import ProjectLicensingPanel, { REVEAL_TTL_MS } from "./ProjectLicensingPanel";

const api = vi.hoisted(() => ({
  listProjectCredentials: vi.fn(),
  createProjectCredential: vi.fn(),
  updateProjectCredential: vi.fn(),
  deleteProjectCredential: vi.fn(),
  revealProjectCredential: vi.fn(),
  listProjectSimCards: vi.fn(),
  createProjectSimCard: vi.fn(),
  updateProjectSimCard: vi.fn(),
  deleteProjectSimCard: vi.fn(),
  revealProjectSimCard: vi.fn(),
  listSurplusContracts: vi.fn(),
  createSurplusContract: vi.fn(),
  updateSurplusContract: vi.fn(),
  deleteSurplusContract: vi.fn(),
  updateProjectLicensingData: vi.fn(),
  updateProjectCommunicationData: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

const SECRET = "Sup3r-Segredo-Teste";
const SIM_PIN = "7391-SIM-TESTE";
const SIM_PUK = "84620175-SIM-TESTE";

function licensing(overrides: Partial<ProjectLicensingData> = {}): ProjectLicensingData {
  return {
    project_id: "proj-1",
    upac_number: "UPAC-001",
    upac_registration_date: "2026-02-10",
    dgeg_number: null,
    cadastro_number: null,
    licensing_status: null,
    registration_date: "2026-03-01",
    certification_request_date: null,
    inspecting_entity: null,
    inspection_date: null,
    provisional_certificate_date: null,
    certificate_date: null,
    installer: null,
    commercializer: null,
    annual_production_kwh: null,
    comments: "",
    licensing_state: "cadastrado",
    updated_at: null,
    ...overrides,
  };
}

function communication(overrides: Partial<ProjectCommunicationData> = {}): ProjectCommunicationData {
  return {
    project_id: "proj-1",
    communication_status: null,
    whereversim_login: "wsim-user",
    notes: "",
    updated_at: null,
    ...overrides,
  };
}

const credential = (overrides: Record<string, unknown> = {}) => ({
  id: "cred-1",
  project_id: "proj-1",
  portal: "dgeg_login_geral",
  username: "utilizador-teste",
  email: "portal.sintetico@example.invalid",
  has_password: true,
  updated_at: null,
  ...overrides,
});

const sim = (overrides: Record<string, unknown> = {}) => ({
  id: "sim-1",
  project_id: "proj-1",
  purpose: "comunicacoes",
  operator: "NOS",
  phone_number: "911000000",
  iccid: "8935-TESTE",
  verified_on_portal: true,
  verified_date: "2026-04-02",
  notes: "",
  has_pin: true,
  has_puk: true,
  updated_at: null,
  ...overrides,
});

const surplus = (overrides: Record<string, unknown> = {}) => ({
  id: "sur-1",
  project_id: "proj-1",
  commercializer: "Comercial Teste",
  contract_type: "Venda excedente",
  contract_sent_date: null,
  signed_received_date: null,
  sent_to_commercializer_date: null,
  status: "enviado",
  duration_months: 12,
  start_date: "2026-05-01",
  end_date: null,
  notes: "",
  updated_at: null,
  ...overrides,
});

type Flags = Partial<{
  canViewLicensing: boolean;
  canEditLicensing: boolean;
  canViewCommunication: boolean;
  canEditCommunication: boolean;
  canEditCredentials: boolean;
  canRevealCredentials: boolean;
  canEditSimCards: boolean;
  canRevealSimSecrets: boolean;
  canEditSurplusContracts: boolean;
}>;

function renderPanel(flags: Flags = {}, data: { lic?: ProjectLicensingData; com?: ProjectCommunicationData } = {}) {
  const onLicensingSaved = vi.fn();
  const onCommunicationSaved = vi.fn();
  render(
    <ToastProvider>
      <ProjectLicensingPanel
        projectId="proj-1"
        licensing={data.lic ?? licensing()}
        communication={data.com ?? communication()}
        canViewLicensing={flags.canViewLicensing ?? true}
        canEditLicensing={flags.canEditLicensing ?? false}
        canViewCommunication={flags.canViewCommunication ?? true}
        canEditCommunication={flags.canEditCommunication ?? false}
        canEditCredentials={flags.canEditCredentials ?? false}
        canRevealCredentials={flags.canRevealCredentials ?? false}
        canEditSimCards={flags.canEditSimCards ?? false}
        canRevealSimSecrets={flags.canRevealSimSecrets ?? false}
        canEditSurplusContracts={flags.canEditSurplusContracts ?? false}
        onLicensingSaved={onLicensingSaved}
        onCommunicationSaved={onCommunicationSaved}
      />
    </ToastProvider>
  );
  return { onLicensingSaved, onCommunicationSaved };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listProjectCredentials.mockResolvedValue([credential()]);
  api.listProjectSimCards.mockResolvedValue([sim()]);
  api.listSurplusContracts.mockResolvedValue([surplus()]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Licenciamento — render", () => {
  it("mostra o estado derivado, as etapas com data e a data de registo UPAC", () => {
    renderPanel({ canViewLicensing: true });
    expect(screen.getByText("Cadastrado")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /progresso do licenciamento: cadastrado/i })).toBeInTheDocument();
    expect(screen.getByText("UPAC-001")).toBeInTheDocument();
    expect(screen.getByText("Data de registo UPAC")).toBeInTheDocument();
  });

  it("mostra o aviso e não renderiza dados sem permissão de visualização", () => {
    renderPanel({ canViewLicensing: false });
    expect(screen.getAllByText(/sem permiss.o para ver estes dados/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("UPAC-001")).not.toBeInTheDocument();
    expect(api.listSurplusContracts).not.toHaveBeenCalled();
  });

  it("sem flags de escrita não mostra botões de edição, adição, remoção nem revelação", async () => {
    renderPanel({ canViewLicensing: true, canViewCommunication: true });
    await screen.findByText("utilizador-teste");
    await screen.findByText("8935-TESTE");
    expect(screen.queryByRole("button", { name: /^editar$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^adicionar$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /novo contrato/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /novo cartão sim/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^remover$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^ver$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ver pin\/puk/i })).not.toBeInTheDocument();
  });

  it("entrada de Entidade inspetora sugere IEP/LVT/LIQ/ISQ", () => {
    renderPanel({ canViewLicensing: true, canEditLicensing: true });
    fireEvent.click(screen.getByRole("button", { name: /^editar$/i }));
    const input = screen.getByLabelText("Entidade inspetora");
    expect(input).toHaveAttribute("list", "lic-inspecting-suggestions");
    const options = Array.from(document.querySelectorAll("#lic-inspecting-suggestions option")).map((o) => o.getAttribute("value"));
    expect(options).toEqual(["IEP", "LVT", "LIQ", "ISQ"]);
  });

  it("guarda a data de registo UPAC quando alterada", async () => {
    api.updateProjectLicensingData.mockResolvedValue(licensing({ upac_registration_date: "2026-02-20" }));
    renderPanel({ canViewLicensing: true, canEditLicensing: true });
    fireEvent.click(screen.getByRole("button", { name: /^editar$/i }));
    fireEvent.change(screen.getByLabelText("Data de registo UPAC"), { target: { value: "2026-02-20" } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.updateProjectLicensingData).toHaveBeenCalledWith("proj-1", { upac_registration_date: "2026-02-20" }));
  });
});

describe("Comunicações", () => {
  it("mostra login WhereverSIM, estado e notas, sem os campos SIM antigos do projeto", () => {
    renderPanel({ canViewCommunication: true });
    expect(screen.getByText("wsim-user")).toBeInTheDocument();
    expect(screen.queryByText("Operador")).not.toBeInTheDocument();
    expect(screen.queryByText("Nº M2M")).not.toBeInTheDocument();
  });

  it("não mostra o login sem permissão dedicada", () => {
    renderPanel({ canViewCommunication: false, canViewLicensing: true });
    expect(screen.queryByText("wsim-user")).not.toBeInTheDocument();
    expect(screen.getAllByText(/sem permiss.o para ver estes dados/i).length).toBeGreaterThan(0);
  });

  it("guarda só os campos alterados", async () => {
    api.updateProjectCommunicationData.mockResolvedValue(communication({ whereversim_login: "novo-login" }));
    const { onCommunicationSaved } = renderPanel({ canViewCommunication: true, canEditCommunication: true });
    fireEvent.click(screen.getByRole("button", { name: /^editar$/i }));
    fireEvent.change(screen.getByLabelText("Login WhereverSIM"), { target: { value: "novo-login" } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.updateProjectCommunicationData).toHaveBeenCalled());
    expect(api.updateProjectCommunicationData).toHaveBeenCalledWith("proj-1", { whereversim_login: "novo-login" });
    await waitFor(() => expect(onCommunicationSaved).toHaveBeenCalled());
  });
});

describe("Cartões SIM", () => {
  it("lista em tabela com finalidade, operador, nº, ICCID, verificação e PIN/PUK definidos — nunca o valor", async () => {
    renderPanel({ canViewCommunication: true });
    await screen.findByText("8935-TESTE");
    expect(screen.getByRole("columnheader", { name: /finalidade/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /iccid/i })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Comunicações" })).toBeInTheDocument();
    expect(screen.getByText("NOS")).toBeInTheDocument();
    expect(screen.getByText("911000000")).toBeInTheDocument();
    expect(screen.getByText("PIN: sim · PUK: sim")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SIM_PIN);
    expect(document.body.innerHTML).not.toContain(SIM_PUK);
  });

  it("sem flags de escrita e revelação não mostra botões", async () => {
    renderPanel({ canViewCommunication: true, canEditSimCards: false, canRevealSimSecrets: false });
    await screen.findByText("8935-TESTE");
    expect(screen.queryByRole("button", { name: /ver pin\/puk/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /novo cartão sim/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^remover$/i })).not.toBeInTheDocument();
  });

  it("'Ver PIN/PUK' só aparece com can_reveal_sim_secrets e só se houver PIN/PUK definidos", async () => {
    api.listProjectSimCards.mockResolvedValue([sim({ has_pin: false, has_puk: false })]);
    renderPanel({ canViewCommunication: true, canRevealSimSecrets: true });
    await screen.findByText("8935-TESTE");
    expect(screen.queryByRole("button", { name: /ver pin\/puk/i })).not.toBeInTheDocument();
  });

  it("PIN/PUK nunca estão no DOM antes do reveal", async () => {
    renderPanel({ canViewCommunication: true, canRevealSimSecrets: true });
    await screen.findByText("8935-TESTE");
    expect(screen.getByRole("button", { name: /ver pin\/puk/i })).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SIM_PIN);
    expect(document.body.innerHTML).not.toContain(SIM_PUK);
    expect(api.revealProjectSimCard).not.toHaveBeenCalled();
  });

  it("reveal mostra PIN/PUK mascarados, mostrar/ocultar alterna, e somem após 30 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.revealProjectSimCard.mockResolvedValue({ id: "sim-1", pin: SIM_PIN, puk: SIM_PUK });
    renderPanel({ canViewCommunication: true, canRevealSimSecrets: true });
    await screen.findByText("8935-TESTE");

    fireEvent.click(screen.getByRole("button", { name: /ver pin\/puk/i }));
    await waitFor(() => expect(api.revealProjectSimCard).toHaveBeenCalledWith("proj-1", "sim-1"));

    const pin = await screen.findByLabelText("PIN");
    const puk = screen.getByLabelText("PUK");
    expect(pin).toHaveAttribute("type", "password");
    expect(puk).toHaveAttribute("type", "password");
    expect((pin as HTMLInputElement).value).toBe(SIM_PIN);
    expect((puk as HTMLInputElement).value).toBe(SIM_PUK);

    fireEvent.click(screen.getByRole("button", { name: /^mostrar$/i }));
    expect(screen.getByLabelText("PIN")).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: /^ocultar$/i }));
    expect(screen.getByLabelText("PIN")).toHaveAttribute("type", "password");

    act(() => {
      vi.advanceTimersByTime(REVEAL_TTL_MS + 100);
    });
    expect(screen.queryByLabelText("PIN")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("PUK")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SIM_PIN);
    expect(document.body.innerHTML).not.toContain(SIM_PUK);
  });

  it("'Fechar' esconde o PIN de imediato", async () => {
    api.revealProjectSimCard.mockResolvedValue({ id: "sim-1", pin: SIM_PIN, puk: null });
    renderPanel({ canViewCommunication: true, canRevealSimSecrets: true });
    await screen.findByText("8935-TESTE");
    fireEvent.click(screen.getByRole("button", { name: /ver pin\/puk/i }));
    await screen.findByLabelText("PIN");
    expect(screen.queryByLabelText("PUK")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^fechar$/i }));
    expect(screen.queryByLabelText("PIN")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SIM_PIN);
  });

  it("503 ao revelar mostra 'Cifra de credenciais não configurada.' e não mostra o PIN", async () => {
    api.revealProjectSimCard.mockRejectedValue(new ApiError(503, "Chave indisponível"));
    renderPanel({ canViewCommunication: true, canRevealSimSecrets: true });
    await screen.findByText("8935-TESTE");
    fireEvent.click(screen.getByRole("button", { name: /ver pin\/puk/i }));
    expect(await screen.findByText("Cifra de credenciais não configurada.")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SIM_PIN);
  });

  it("campos PIN/PUK do formulário: type=password e autocomplete=off", async () => {
    renderPanel({ canViewCommunication: true, canEditSimCards: true });
    await screen.findByText("8935-TESTE");
    fireEvent.click(screen.getByRole("button", { name: /novo cartão sim/i }));
    for (const label of ["PIN (opcional)", "PUK (opcional)"]) {
      const field = screen.getByLabelText(label);
      expect(field).toHaveAttribute("type", "password");
      expect(field).toHaveAttribute("autocomplete", "off");
    }
  });

  it("criar SIM envia os campos e o PIN quando preenchido, sem PUK", async () => {
    api.createProjectSimCard.mockResolvedValue(sim({ id: "sim-2" }));
    renderPanel({ canViewCommunication: true, canEditSimCards: true });
    await screen.findByText("8935-TESTE");
    fireEvent.click(screen.getByRole("button", { name: /novo cartão sim/i }));
    fireEvent.change(screen.getByLabelText("Finalidade"), { target: { value: "dados_moveis" } });
    fireEvent.change(screen.getByLabelText("Operador"), { target: { value: "MEO" } });
    fireEvent.change(screen.getByLabelText("ICCID"), { target: { value: "8935-NOVO" } });
    fireEvent.change(screen.getByLabelText("PIN (opcional)"), { target: { value: SIM_PIN } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.createProjectSimCard).toHaveBeenCalled());
    const [projectId, body] = api.createProjectSimCard.mock.calls[0];
    expect(projectId).toBe("proj-1");
    expect(body).toMatchObject({ purpose: "dados_moveis", operator: "MEO", iccid: "8935-NOVO", pin: SIM_PIN });
    expect(body).not.toHaveProperty("puk");
  });

  it("editar SIM sem tocar no PIN/PUK não os envia (mantém)", async () => {
    api.updateProjectSimCard.mockResolvedValue(sim({ operator: "MEO" }));
    renderPanel({ canViewCommunication: true, canEditSimCards: true });
    const row = (await screen.findByText("8935-TESTE")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /^editar$/i }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Operador"), { target: { value: "MEO" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.updateProjectSimCard).toHaveBeenCalled());
    expect(api.updateProjectSimCard).toHaveBeenCalledWith("proj-1", "sim-1", { operator: "MEO" });
  });

  it("opção explícita remove o PIN guardado (envia pin: null)", async () => {
    api.updateProjectSimCard.mockResolvedValue(sim({ has_pin: false }));
    renderPanel({ canViewCommunication: true, canEditSimCards: true });
    const row = (await screen.findByText("8935-TESTE")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /^editar$/i }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(/remover o pin guardado/i));
    fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.updateProjectSimCard).toHaveBeenCalled());
    expect(api.updateProjectSimCard).toHaveBeenCalledWith("proj-1", "sim-1", { pin: null });
  });

  it("remover SIM pede confirmação e chama DELETE", async () => {
    api.deleteProjectSimCard.mockResolvedValue(undefined);
    renderPanel({ canViewCommunication: true, canEditSimCards: true });
    await screen.findByText("8935-TESTE");
    fireEvent.click(screen.getByRole("button", { name: /^remover$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirmar remoção/i }));
    await waitFor(() => expect(api.deleteProjectSimCard).toHaveBeenCalledWith("proj-1", "sim-1"));
  });
});

describe("Credenciais de portais", () => {
  it("lista portal, utilizador, email e se a password está definida, sem a mostrar", async () => {
    renderPanel({ canViewCommunication: true });
    await screen.findByText("utilizador-teste");
    expect(screen.getByText("DGEG / Login Geral")).toBeInTheDocument();
    expect(screen.getByText("portal.sintetico@example.invalid")).toBeInTheDocument();
    expect(screen.getByText("definida")).toBeInTheDocument();
  });

  it("não chama a API de credenciais sem permissão de visualização", async () => {
    renderPanel({ canViewCommunication: false, canViewLicensing: true });
    await screen.findAllByText(/sem permiss.o para ver estes dados/i);
    expect(api.listProjectCredentials).not.toHaveBeenCalled();
    expect(screen.queryByText("Credenciais de portais")).not.toBeInTheDocument();
  });

  it("'Ver' só aparece com permissão de reveal, e a password nunca está no DOM antes de revelar", async () => {
    renderPanel({ canViewCommunication: true, canRevealCredentials: false, canEditCredentials: false });
    await screen.findByText("utilizador-teste");
    expect(screen.queryByRole("button", { name: /^ver$/i })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("reveal mostra a password mascarada, mostrar/ocultar alterna, e a password desaparece após 30 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.revealProjectCredential.mockResolvedValue({ id: "cred-1", portal: "dgeg_login_geral", username: "utilizador-teste", password: SECRET });
    renderPanel({ canViewCommunication: true, canRevealCredentials: true });
    await screen.findByText("utilizador-teste");

    // Antes do reveal: sem password no DOM.
    expect(document.body.innerHTML).not.toContain(SECRET);

    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));
    await waitFor(() => expect(api.revealProjectCredential).toHaveBeenCalledWith("proj-1", "cred-1"));

    const field = await screen.findByLabelText("Palavra-passe");
    expect(field).toHaveAttribute("type", "password");
    expect((field as HTMLInputElement).value).toBe(SECRET);

    fireEvent.click(screen.getByRole("button", { name: /^mostrar$/i }));
    expect(screen.getByLabelText("Palavra-passe")).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: /^ocultar$/i }));
    expect(screen.getByLabelText("Palavra-passe")).toHaveAttribute("type", "password");

    // Passados 30 s, desaparece sozinha.
    act(() => {
      vi.advanceTimersByTime(REVEAL_TTL_MS + 100);
    });
    expect(screen.queryByLabelText("Palavra-passe")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("'Fechar' esconde a password de imediato", async () => {
    api.revealProjectCredential.mockResolvedValue({ id: "cred-1", portal: "dgeg_login_geral", username: "utilizador-teste", password: SECRET });
    renderPanel({ canViewCommunication: true, canRevealCredentials: true });
    await screen.findByText("utilizador-teste");
    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));
    await screen.findByLabelText("Palavra-passe");
    fireEvent.click(screen.getByRole("button", { name: /^fechar$/i }));
    expect(screen.queryByLabelText("Palavra-passe")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("503 ao revelar mostra 'Cifra de credenciais não configurada.'", async () => {
    api.revealProjectCredential.mockRejectedValue(new ApiError(503, "Chave indisponível"));
    renderPanel({ canViewCommunication: true, canRevealCredentials: true });
    await screen.findByText("utilizador-teste");
    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));
    expect(await screen.findByText("Cifra de credenciais não configurada.")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(SECRET);
  });

  it("503 ao criar credencial com password mostra erro claro", async () => {
    api.createProjectCredential.mockRejectedValue(new ApiError(503, "x"));
    renderPanel({ canViewCommunication: true, canEditCredentials: true });
    await screen.findByText("utilizador-teste");
    fireEvent.click(screen.getByRole("button", { name: /adicionar/i }));
    fireEvent.change(screen.getByLabelText("Utilizador"), { target: { value: "novo" } });
    fireEvent.change(screen.getByLabelText(/palavra-passe \(opcional\)/i), { target: { value: SECRET } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    expect(await screen.findByText("Cifra de credenciais não configurada.")).toBeInTheDocument();
  });

  it("campo de password: type=password e autocomplete=new-password", async () => {
    renderPanel({ canViewCommunication: true, canEditCredentials: true });
    await screen.findByText("utilizador-teste");
    fireEvent.click(screen.getByRole("button", { name: /adicionar/i }));
    const pwd = screen.getByLabelText(/palavra-passe \(opcional\)/i);
    expect(pwd).toHaveAttribute("type", "password");
    expect(pwd).toHaveAttribute("autocomplete", "new-password");
  });

  it("editar com password vazia não envia 'password' e envia o email alterado", async () => {
    api.updateProjectCredential.mockResolvedValue(credential({ username: "novo-nome" }));
    renderPanel({ canViewCommunication: true, canEditCredentials: true });
    await screen.findByText("utilizador-teste");
    fireEvent.click(screen.getByRole("button", { name: /^editar$/i }));
    expect((screen.getByLabelText("Email (opcional)") as HTMLInputElement).value).toBe("portal.sintetico@example.invalid");
    fireEvent.change(screen.getByLabelText("Utilizador"), { target: { value: "novo-nome" } });
    fireEvent.change(screen.getByLabelText("Email (opcional)"), { target: { value: "outro.sintetico@example.invalid" } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.updateProjectCredential).toHaveBeenCalled());
    const body = api.updateProjectCredential.mock.calls[0][2];
    expect(body).toEqual({ portal: "dgeg_login_geral", username: "novo-nome", email: "outro.sintetico@example.invalid" });
    expect(body).not.toHaveProperty("password");
  });

  it("remover pede confirmação e chama DELETE", async () => {
    api.deleteProjectCredential.mockResolvedValue(undefined);
    renderPanel({ canViewCommunication: true, canEditCredentials: true });
    await screen.findByText("utilizador-teste");
    fireEvent.click(screen.getByRole("button", { name: /^remover$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirmar remoção/i }));
    await waitFor(() => expect(api.deleteProjectCredential).toHaveBeenCalledWith("proj-1", "cred-1"));
  });
});

describe("Contratos de venda de excedente", () => {
  it("lista contratos e não mostra ações sem permissão de escrita", async () => {
    renderPanel({ canViewLicensing: true });
    await screen.findByText("Comercial Teste");
    expect(screen.queryByRole("button", { name: /novo contrato/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^editar$/i })).not.toBeInTheDocument();
  });

  it("cria contrato com os campos do formulário", async () => {
    api.createSurplusContract.mockResolvedValue(surplus({ id: "sur-2", commercializer: "Novo Comercial" }));
    renderPanel({ canViewLicensing: true, canEditSurplusContracts: true });
    await screen.findByText("Comercial Teste");
    fireEvent.click(screen.getByRole("button", { name: /novo contrato/i }));
    fireEvent.change(screen.getByLabelText("Comercializador"), { target: { value: "Novo Comercial" } });
    fireEvent.change(screen.getByLabelText("Duração (meses)"), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-06-01" } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.createSurplusContract).toHaveBeenCalled());
    expect(api.createSurplusContract).toHaveBeenCalledWith(
      "proj-1",
      expect.objectContaining({ commercializer: "Novo Comercial", duration_months: 24, start_date: "2026-06-01", end_date: null })
    );
  });

  it("rejeita duração fora de 0..600 sem chamar a API", async () => {
    renderPanel({ canViewLicensing: true, canEditSurplusContracts: true });
    await screen.findByText("Comercial Teste");
    fireEvent.click(screen.getByRole("button", { name: /novo contrato/i }));
    fireEvent.change(screen.getByLabelText("Duração (meses)"), { target: { value: "700" } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));
    expect(await screen.findByText(/entre 0 e 600/i)).toBeInTheDocument();
    expect(api.createSurplusContract).not.toHaveBeenCalled();
  });

  it("edita um contrato existente", async () => {
    api.updateSurplusContract.mockResolvedValue(surplus({ status: "assinado" }));
    renderPanel({ canViewLicensing: true, canEditSurplusContracts: true });
    await screen.findByText("Comercial Teste");
    const row = screen.getByText("Comercial Teste").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: /^editar$/i }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Situação"), { target: { value: "assinado" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));
    await waitFor(() => expect(api.updateSurplusContract).toHaveBeenCalled());
    expect(api.updateSurplusContract.mock.calls[0][1]).toBe("sur-1");
    expect(api.updateSurplusContract.mock.calls[0][2]).toMatchObject({ status: "assinado" });
  });

  it("remover é remoção lógica pedida à API, com confirmação", async () => {
    api.deleteSurplusContract.mockResolvedValue(undefined);
    renderPanel({ canViewLicensing: true, canEditSurplusContracts: true });
    await screen.findByText("Comercial Teste");
    fireEvent.click(screen.getByRole("button", { name: /^remover$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirmar remoção/i }));
    await waitFor(() => expect(api.deleteSurplusContract).toHaveBeenCalledWith("proj-1", "sur-1"));
  });
});
