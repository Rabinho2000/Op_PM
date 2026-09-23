// Resumo em texto de um plano de deslocação (D-066) — para copiar e partilhar
// (mensagem, email, nota). Lógica pura, testável sem React. Só apresenta o que
// o servidor devolveu: uma secção `null` (sem permissão) é dita como tal, nunca
// como "nada a fazer".
import type { TripPlan } from "../api/client";
import { formatDatePt, formatDateTimePt } from "./dates";

const PRIORITY_LABELS: Record<string, string> = { low: "baixa", medium: "média", high: "alta", urgent: "urgente" };

function priority(value: string): string {
  return PRIORITY_LABELS[value] ?? value;
}

export function buildTripSummaryText(plan: TripPlan): string {
  const lines: string[] = [];
  const kmNote = "(distância em linha reta, aproximação)";
  lines.push(
    `Deslocação — ${plan.stops.length} paragens, ${plan.total_km} km ${kmNote}${plan.round_trip ? ", com regresso" : ""}`
  );
  const s = plan.summary;
  const totals = [`${s.projects} instalação(ões)`];
  if (s.suppliers) totals.push(`${s.suppliers} fornecedor(es)`);
  if (s.pickup_points) totals.push(`${s.pickup_points} ponto(s) de recolha`);
  if (s.operational_tasks !== null) {
    totals.push(`${s.operational_tasks} tarefa(s) operacional(is)${s.overdue_tasks ? ` (${s.overdue_tasks} atrasada(s))` : ""}`);
  }
  if (s.issues !== null) totals.push(`${s.issues} pendência(s)`);
  if (s.items_to_collect !== null) totals.push(`${s.items_to_collect} material(is) a recolher`);
  lines.push(totals.join(" · "));
  lines.push("");

  plan.stops.forEach((stop, index) => {
    lines.push(`${index + 1}. ${stop.name}${index === 0 ? " (partida)" : ` — +${stop.leg_km} km`}`);
    if (stop.info) lines.push(`   Materiais: ${stop.info}`);
    const jobs = stop.jobs;
    if (!jobs) return;
    for (const task of jobs.tasks ?? []) {
      const due = task.due_date ? `, prazo ${formatDatePt(task.due_date)}` : "";
      lines.push(`   - Tarefa: ${task.title}${task.is_overdue ? " (atrasada)" : ""}${due} [${priority(task.priority)}]`);
    }
    for (const issue of jobs.issues ?? []) lines.push(`   - Pendência: ${issue.description} [${priority(issue.priority)}]`);
    for (const item of jobs.collect ?? []) lines.push(`   - Recolher: ${item.quantity} ${item.item_unit ?? ""} ${item.item_name ?? ""}`.replace(/\s+/g, " ").trimEnd());
    if (jobs.next_visit) lines.push(`   - Visita agendada: ${jobs.next_visit.title} (${formatDateTimePt(jobs.next_visit.starts_at)})`);
    if (jobs.tasks === null || jobs.issues === null || jobs.collect === null) {
      lines.push("   (algumas secções não visíveis com as suas permissões)");
    }
  });
  if (plan.return_leg_km !== null) lines.push(`${plan.stops.length + 1}. Regresso à partida — +${plan.return_leg_km} km`);
  return lines.join("\n");
}
