// Rótulos e tons visuais — só apresentação (os estados vêm da API).
import type { AbsenceType, ProjectStatus, TaskPriority, TaskStatus } from "../api/client";
import type { IconName } from "../components/Icon";
import type { Tone } from "../components/ui";

export const PROJECT_STATUS_TONES: Record<ProjectStatus, Tone> = {
  nao_iniciado: "neutral",
  em_curso: "info",
  concluido: "success",
};

// Estado do ciclo de vida do projeto (D-069): só apresentação; os códigos vêm da API.
export const LIFECYCLE_STATUS_TONES: Record<string, Tone> = {
  on_hold_cliente: "warning",
  preparacao: "info",
  construcao: "brand",
  construido: "violet",
  entregue_cliente: "success",
  certificado_final: "neutral",
};

export const TASK_STATUS_TONES: Record<TaskStatus, Tone> = {
  todo: "neutral",
  in_progress: "info",
  blocked: "danger",
  done: "success",
  cancelled: "neutral",
};

export const TASK_PRIORITY_TONES: Record<TaskPriority, Tone> = {
  low: "neutral",
  medium: "brand",
  high: "warning",
  urgent: "danger",
};

export const ABSENCE_TYPE_TONES: Record<AbsenceType, Tone> = {
  ferias: "violet",
  baixa_medica: "danger",
  outro: "info",
};

export const TASK_TYPE_ICONS: Record<string, IconName> = {
  visita_tecnica: "mapPin",
  preparacao_instalacao: "wrench",
  instalacao: "zap",
  comissionamento: "checkCircle",
  fotos_drive: "camera",
  custom: "tasks",
};

// Nomes legíveis dos campos de projeto (histórico e formulário de edição).
export const PROJECT_FIELD_LABELS: Record<string, string> = {
  name: "Nome",
  client_name: "Cliente",
  client_contact: "Contacto",
  client_email: "Email",
  address: "Morada",
  lat: "Latitude",
  lon: "Longitude",
  power_kwp: "Potência (kWp)",
  power_raw: "Potência (texto original)",
  pm_person_id: "PM",
  start_date: "Data de início",
  role: "Papel / observação",
  equipment_notes: "Notas de equipamento",
  injection_notes: "Notas de injeção",
  om_notes: "Notas de O&M",
  commercial_assumptions: "Pressupostos comerciais",
  upac_registration: "Registo UPAC",
  m2m_card: "Cartão M2M",
  upac_connection_date_raw: "Data de ligação UPAC",
  award_year_raw: "Ano de adjudicação",
  notes: "Notas",
  is_active: "Ativo",
  status: "Estado",
  priority: "Prioridade",
  assigned_to_person_id: "Responsável",
  due_date: "Prazo",
  title: "Título",
  description: "Descrição",
};

export const MISSING_FIELD_LABELS: Record<string, string> = {
  email: "email",
  contacto: "contacto",
  coordenadas: "coordenadas",
};
