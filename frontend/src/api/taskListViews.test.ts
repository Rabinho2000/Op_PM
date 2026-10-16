import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiGet, apiPut, apiPost, apiPatch, apiDelete } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock("./client", () => ({ apiGet, apiPut, apiPost, apiPatch, apiDelete }));

import {
  createTaskListView,
  deleteTaskListView,
  getTaskListPreferences,
  listTaskListViews,
  updateTaskListPreferences,
  updateTaskListView,
} from "./taskListViews";
import type { TaskListConfig } from "./taskListViews";

const CONFIG: TaskListConfig = {
  columns: ["task", "project", "assignee", "priority", "due_date", "status"],
  sort_by: "default",
  sort_direction: "asc",
  view: "lista",
  filters: { project_id: "", assigned_to_person_id: "", priority: "", status: "", overdue_only: false },
};

describe("task list views API", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the personal preference endpoints with the complete config envelope", async () => {
    await getTaskListPreferences();
    await updateTaskListPreferences(CONFIG);

    expect(apiGet).toHaveBeenCalledWith("/api/me/task-list-preferences");
    expect(apiPut).toHaveBeenCalledWith("/api/me/task-list-preferences", { config: CONFIG });
  });

  it("uses CRUD endpoints for personal saved views without client account identifiers", async () => {
    await listTaskListViews();
    await createTaskListView({ name: "Urgentes", config: CONFIG });
    await updateTaskListView("view-1", { config: CONFIG });
    await updateTaskListView("view-1", { name: "Urgentes 2" });
    await deleteTaskListView("view-1");

    expect(apiGet).toHaveBeenCalledWith("/api/me/task-list-views");
    expect(apiPost).toHaveBeenCalledWith("/api/me/task-list-views", { name: "Urgentes", config: CONFIG });
    expect(apiPatch).toHaveBeenNthCalledWith(1, "/api/me/task-list-views/view-1", { config: CONFIG });
    expect(apiPatch).toHaveBeenNthCalledWith(2, "/api/me/task-list-views/view-1", { name: "Urgentes 2" });
    expect(apiDelete).toHaveBeenCalledWith("/api/me/task-list-views/view-1");
  });
});
