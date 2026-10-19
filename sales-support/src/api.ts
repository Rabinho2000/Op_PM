export type BoardColumn = "todo" | "in_progress" | "done";

export interface SalesItem {
  clickup_task_id: string;
  title: string;
  client: string;
  power_kwp: number | null;
  location: string;
  owner: string;
  due_date: string | null;
  clickup_status: string;
  column: BoardColumn;
  priority: "urgent" | "high" | "normal" | "low";
  updated_at: string;
  op_pm_project_id: string | null;
  ready_for_op_pm: boolean;
  missing_fields: string[];
}

export interface BoardResponse {
  source: "clickup" | "mock";
  synced_at: string;
  list_name: string;
  items: SalesItem[];
}

const API_BASE = import.meta.env.VITE_SALES_SUPPORT_API_BASE || "/api/sales-support";
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

const MOCK_ITEMS: SalesItem[] = [
  {
    clickup_task_id: "cu_90124",
    title: "UPAC Logística Norte",
    client: "Cliente Atlas",
    power_kwp: 184.8,
    location: "Maia",
    owner: "Comercial A",
    due_date: "2026-10-03",
    clickup_status: "A preparar proposta",
    column: "todo",
    priority: "high",
    updated_at: "2026-10-01T08:42:00Z",
    op_pm_project_id: null,
    ready_for_op_pm: false,
    missing_fields: ["Data prevista de arranque"],
  },
  {
    clickup_task_id: "cu_90131",
    title: "Cobertura Industrial Tejo",
    client: "Cliente Delta",
    power_kwp: 92.4,
    location: "Alverca",
    owner: "Comercial B",
    due_date: "2026-10-02",
    clickup_status: "Engenharia / validação",
    column: "in_progress",
    priority: "urgent",
    updated_at: "2026-10-01T08:51:00Z",
    op_pm_project_id: null,
    ready_for_op_pm: true,
    missing_fields: [],
  },
  {
    clickup_task_id: "cu_90136",
    title: "Autoconsumo Armazém Sul",
    client: "Cliente Lumen",
    power_kwp: 61.6,
    location: "Palmela",
    owner: "Comercial A",
    due_date: null,
    clickup_status: "Contrato assinado",
    column: "done",
    priority: "normal",
    updated_at: "2026-09-30T15:20:00Z",
    op_pm_project_id: null,
    ready_for_op_pm: true,
    missing_fields: [],
  },
  {
    clickup_task_id: "cu_90088",
    title: "Fábrica Centro II",
    client: "Cliente Prisma",
    power_kwp: 248.0,
    location: "Leiria",
    owner: "Comercial C",
    due_date: null,
    clickup_status: "Entregue a Operações",
    column: "done",
    priority: "normal",
    updated_at: "2026-09-29T17:05:00Z",
    op_pm_project_id: "9f2d2c9e-76d0-49ab-9200-demo00000001",
    ready_for_op_pm: false,
    missing_fields: [],
  },
  {
    clickup_task_id: "cu_90140",
    title: "Retail Park Oeste",
    client: "Cliente Horizonte",
    power_kwp: null,
    location: "Torres Vedras",
    owner: "Comercial B",
    due_date: "2026-10-07",
    clickup_status: "Levantamento de dados",
    column: "todo",
    priority: "low",
    updated_at: "2026-10-01T07:55:00Z",
    op_pm_project_id: null,
    ready_for_op_pm: false,
    missing_fields: ["Potência", "Contacto do cliente"],
  },
];

function delay(ms = 180) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export async function getBoard(): Promise<BoardResponse> {
  if (USE_MOCK) {
    await delay();
    return {
      source: "mock",
      synced_at: new Date().toISOString(),
      list_name: "Sales Support — ClickUp",
      items: structuredClone(MOCK_ITEMS),
    };
  }
  const response = await fetch(`${API_BASE}/board`, { credentials: "include" });
  if (!response.ok) throw new Error(`Erro a carregar ClickUp (${response.status})`);
  return response.json();
}

export async function syncClickUp(): Promise<BoardResponse> {
  if (USE_MOCK) {
    await delay(450);
    return getBoard();
  }
  const response = await fetch(`${API_BASE}/sync`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) throw new Error(`Erro na sincronização ClickUp (${response.status})`);
  return response.json();
}

export async function injectIntoOpPm(item: SalesItem): Promise<{ project_id: string }> {
  if (USE_MOCK) {
    await delay(500);
    return { project_id: `mock-${item.clickup_task_id}` };
  }
  const response = await fetch(`${API_BASE}/items/${encodeURIComponent(item.clickup_task_id)}/promote`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Erro ao criar projecto no OP-PM (${response.status})`);
  }
  return response.json();
}
