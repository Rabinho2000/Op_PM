import { useCallback, useState } from "react";
import {
  ApiError,
  Task,
  TASK_ALLOWED_NEXT_STATUSES,
  TASK_STATUS_LABELS,
  TaskStatus,
  updateTask,
} from "../api/client";
import { TASK_STATUS_TONES } from "../utils/labels";
import { useToast } from "./Toast";
import { Badge } from "./ui";

// Alteração de estado com confirmação visual. As transições oferecidas
// espelham a máquina de estados do servidor (TASK_ALLOWED_NEXT_STATUSES);
// o servidor continua a ser quem decide (D-040).
export function useTaskStatusChange(onChanged: (task: Task) => void) {
  const { notify } = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);

  const change = useCallback(
    async (task: Task, status: TaskStatus) => {
      if (status === task.status) return;
      setBusyId(task.id);
      try {
        const updated = await updateTask(task.id, { status });
        if (status === "done") {
          notify(`Tarefa concluída: ${task.title}`, "success");
        } else {
          notify(`“${task.title}” passou para ${TASK_STATUS_LABELS[status].toLowerCase()}.`, "info");
        }
        onChanged(updated);
      } catch (e) {
        notify(e instanceof ApiError ? e.detail : "Não foi possível alterar o estado da tarefa.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [notify, onChanged]
  );

  return { change, busyId };
}

export default function TaskStatusControl({
  task,
  busy,
  onChange,
}: {
  task: Task;
  busy?: boolean;
  onChange: (task: Task, status: TaskStatus) => void;
}) {
  if (!task.can_edit) {
    return (
      <Badge tone={TASK_STATUS_TONES[task.status]} dot>
        {TASK_STATUS_LABELS[task.status]}
      </Badge>
    );
  }
  return (
    <select
      className="select select--compact"
      aria-label={`Estado da tarefa ${task.title}`}
      value={task.status}
      disabled={busy}
      onChange={(e) => onChange(task, e.target.value as TaskStatus)}
    >
      {TASK_ALLOWED_NEXT_STATUSES[task.status].map((s) => (
        <option key={s} value={s}>
          {TASK_STATUS_LABELS[s]}
        </option>
      ))}
    </select>
  );
}
