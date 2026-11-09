import { useState } from "react";
import { ApiError, PaymentMilestoneCode, Project, ProjectPayments, updateProjectPayment } from "../api/client";
import { Alert, Card } from "./ui";
import { PAYMENT_MILESTONE_LABELS, PAYMENT_MILESTONE_ORDER } from "../utils/labels";

export default function ProjectPaymentsCard({
  project,
  onPaymentsChanged,
}: {
  project: Project;
  onPaymentsChanged: (payments: ProjectPayments) => void;
}) {
  const [busyMilestone, setBusyMilestone] = useState<PaymentMilestoneCode | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function changeMilestone(milestone: PaymentMilestoneCode, received: boolean) {
    if (busyMilestone) return;
    const previous = project.payments?.[milestone] ?? false;
    if (previous === received) return;

    const currentPayments = project.payments ?? {
      adjudicacao: false,
      entrada_obra: false,
      fim_obra: false,
      certificado_final: false,
    };
    setBusyMilestone(milestone);
    setError(null);
    onPaymentsChanged({ ...currentPayments, [milestone]: received });
    try {
      const saved = await updateProjectPayment(project.id, milestone, received);
      onPaymentsChanged({ ...currentPayments, [milestone]: saved.received });
    } catch (reason) {
      onPaymentsChanged({ ...currentPayments, [milestone]: previous });
      setError(
        reason instanceof ApiError
          ? reason.detail
          : reason instanceof Error && reason.message
            ? reason.message
            : "Não foi possível guardar o marco de pagamento."
      );
    } finally {
      setBusyMilestone(null);
    }
  }

  return (
    <Card title="Pagamentos" icon="checkCircle">
      <ul className="list">
        {PAYMENT_MILESTONE_ORDER.map((milestone) => (
          <li key={milestone} className="list__item">
            <div className="list__main">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={project.payments?.[milestone] ?? false}
                  disabled={!project.can_edit_payments || busyMilestone !== null}
                  aria-label={PAYMENT_MILESTONE_LABELS[milestone]}
                  onChange={(event) => void changeMilestone(milestone, event.target.checked)}
                />
                <span className="list__title">{PAYMENT_MILESTONE_LABELS[milestone]}</span>
              </label>
            </div>
          </li>
        ))}
      </ul>
      {error && <Alert tone="danger" title="Pagamento não atualizado">{error}</Alert>}
    </Card>
  );
}
