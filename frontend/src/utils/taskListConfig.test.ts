import { describe, expect, it } from "vitest";
import { makeTask } from "../test/fixtures";
import {
  DEFAULT_TASK_LIST_COLUMNS,
  TASK_LIST_COLUMN_LABELS,
  defaultTaskListConfig,
  normalizeTaskListConfig,
  sortTasks,
} from "./taskListConfig";

const defaultConfig = defaultTaskListConfig();

describe("task list config", () => {
  it("has the published default columns and makes task the first required column", () => {
    expect(DEFAULT_TASK_LIST_COLUMNS).toEqual(["task", "project", "assignee", "priority", "due_date", "status"]);
    expect(normalizeTaskListConfig({ columns: ["priority", "task", "priority", "unknown" as never] }).columns).toEqual([
      "task",
      "priority",
    ]);
    expect(TASK_LIST_COLUMN_LABELS.task).toBe("Tarefa");
  });

  it("normalizes invalid config fields without losing the complete filter shape", () => {
    expect(
      normalizeTaskListConfig({
        sort_by: "not-a-sort" as never,
        sort_direction: "sideways" as never,
        view: "grid" as never,
        filters: { ...defaultConfig.filters, priority: "not-a-priority" as never, status: "bad-status" as never, overdue_only: "yes" as never },
      })
    ).toEqual(defaultConfig);
  });

  it("sorts naturally and numerically, stably, with nulls last in both directions", () => {
    const tasks = [
      makeTask({ id: "10", title: "Tarefa 10", due_date: "2026-10-02", priority: "low", project_name: "Projeto 10" }),
      makeTask({ id: "2", title: "Tarefa 2", due_date: null, priority: "urgent", project_name: null }),
      makeTask({ id: "1", title: "Tarefa 1", due_date: "2026-10-01", priority: "high", project_name: "Projeto 2" }),
      makeTask({ id: "1b", title: "Tarefa 1", due_date: "2026-10-01", priority: "medium", project_name: "Projeto 1" }),
    ];

    expect(sortTasks(tasks, "title", "asc").map((task) => task.id)).toEqual(["1", "1b", "2", "10"]);
    expect(sortTasks(tasks, "due_date", "desc").map((task) => task.id)).toEqual(["10", "1", "1b", "2"]);
    expect(sortTasks(tasks, "priority", "asc").map((task) => task.id)).toEqual(["2", "1", "1b", "10"]);
    expect(sortTasks(tasks, "project_name", "asc").map((task) => task.id)).toEqual(["1b", "1", "10", "2"]);
    expect(sortTasks(tasks, "default", "desc").map((task) => task.id)).toEqual(["10", "2", "1", "1b"]);
  });
});
