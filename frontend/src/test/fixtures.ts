// Dados sintéticos para testes de componentes (nunca dados reais).
import type { DashboardSummary, MeResponse, Project, Task } from "../api/client";

export function makeMe(overrides: Partial<MeResponse> = {}): MeResponse {
  return {
    user_id: "u-chefe",
    email: "chefe.sintetico@example.invalid",
    person_id: "p-chefe",
    display_name: "Chefe Sintético",
    roles: ["chefe_operacoes"],
    role_labels: ["Chefe de Operações"],
    permissions: ["project.view_all", "project.edit_all", "task.view_all", "task.edit_all", "absence.view_all", "absence.manage_all", "migration.view"],
    ...overrides,
  };
}

export const COMERCIAL_ME = makeMe({
  user_id: "u-comercial",
  email: "comercial.sintetico@example.invalid",
  person_id: "p-comercial",
  display_name: "Comercial Sintético",
  roles: ["comercial"],
  role_labels: ["Comercial"],
  permissions: ["project.view_all", "task.view_all", "absence.view_own", "absence.manage_own"],
});

export function makeSummary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    generated_at: "2026-09-16T10:00:00Z",
    scope: "all",
    week_start: "2026-09-14",
    week_end: "2026-09-20",
    active_projects_count: 0,
    projects_starting_next_30_days: [],
    overdue_tasks: [],
    tasks_due_this_week: [],
    pending_technical_visits: [],
    pending_commissioning: [],
    projects_without_pm: [],
    projects_missing_data: [],
    current_absences: [],
    upcoming_absences: [],
    upcoming_birthdays: [],
    urgent_tasks: [],
    projects_photos_pending: [],
    week_overview: [],
    ...overrides,
  };
}

export function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj-1",
    name: "Instalação Sintética de Teste",
    client_name: "Cliente Sintético",
    client_contact: "Contacto Sintético",
    client_email: "cliente@example.invalid",
    address: "Morada sintética",
    lat: 38.7,
    lon: -9.1,
    power_kwp: 10,
    power_raw: null,
    pm_person_id: "p-pm",
    pm_display_name: "PM Sintético Um",
    start_date: "2026-09-01",
    clickup_status_mirror: null,
    role: null,
    equipment_notes: null,
    injection_notes: null,
    om_notes: null,
    commercial_assumptions: null,
    upac_registration: null,
    m2m_card: null,
    upac_connection_date_raw: null,
    award_year_raw: null,
    is_active: true,
    notes: "",
    has_pm: true,
    has_email: true,
    has_coordinates: true,
    has_contact: true,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    status: "em_curso",
    next_task_title: "Instalação",
    next_task_due_date: "2026-09-18",
    overdue_tasks_count: 0,
    workflow_progress_percent: 40,
    photos_pending_warning: false,
    editable_fields: [],
    can_manage_tasks: false,
    ...overrides,
  };
}

export function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    project_id: "proj-1",
    title: "Visita técnica",
    task_type: "visita_tecnica",
    description: "",
    status: "todo",
    priority: "medium",
    assigned_to_person_id: null,
    due_date: "2026-09-18",
    completed_at: null,
    notes: "",
    created_by_person_id: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    project_name: "Instalação Sintética de Teste",
    assigned_to_display_name: null,
    is_overdue: false,
    can_edit: true,
    ...overrides,
  };
}
