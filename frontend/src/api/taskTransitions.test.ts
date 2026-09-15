import { describe, expect, it } from "vitest";
import { TASK_ALLOWED_NEXT_STATUSES, TaskStatus } from "./client";

// Espelha a máquina de estados do backend (app/services/tasks.py) só para
// desenhar a UI — o servidor continua a ser a fonte de verdade (ver
// backend/tests/test_tasks_api.py para os testes de contrato reais).
describe("TASK_ALLOWED_NEXT_STATUSES", () => {
  const allStatuses: TaskStatus[] = ["todo", "in_progress", "blocked", "done", "cancelled"];

  it("always allows staying in the same status (no-op)", () => {
    for (const status of allStatuses) {
      expect(TASK_ALLOWED_NEXT_STATUSES[status]).toContain(status);
    }
  });

  it("never allows a direct jump from blocked to done", () => {
    expect(TASK_ALLOWED_NEXT_STATUSES.blocked).not.toContain("done");
  });

  it("only allows cancelled to reopen to todo", () => {
    expect(TASK_ALLOWED_NEXT_STATUSES.cancelled.sort()).toEqual(["cancelled", "todo"]);
  });

  it("only allows done to reopen to todo or in_progress", () => {
    expect(TASK_ALLOWED_NEXT_STATUSES.done.sort()).toEqual(["done", "in_progress", "todo"]);
  });

  it("covers every known status as a source", () => {
    expect(Object.keys(TASK_ALLOWED_NEXT_STATUSES).sort()).toEqual([...allStatuses].sort());
  });
});
