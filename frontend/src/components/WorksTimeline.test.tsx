import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Installer, LifecycleStatus, WorkItem } from "../api/client";
import WorksTimeline from "./WorksTimeline";
import { windowFrom } from "../utils/worksTimeline";

const STATUS: LifecycleStatus = { code: "construcao", label: "Construção", flow_position: 1 };

if (typeof window.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  (window as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill;
}

const INSTALLER: Installer = {
  id: "installer-1",
  name: "Instalador 1",
  is_active: true,
  project_count: 1,
  teams: [{ id: "team-1", name: "Equipa 1", leader_name: null, leader_phone: null, is_active: true, project_count: 1 }],
};

function makeWork(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    project_id: "project-1",
    name: "Obra de teste",
    client_name: null,
    pm_person_id: null,
    pm_display_name: null,
    lifecycle_status: "construcao",
    installer_id: "installer-1",
    installer_name: "Instalador 1",
    installer_team_id: "team-1",
    installer_team_name: "Equipa 1",
    work_start_date: "2028-02-05",
    work_end_date: "2028-02-07",
    work_dates_estimated: false,
    conflict: false,
    can_plan_work: false,
    ...overrides,
  };
}

function renderTimeline(work: WorkItem, onOpenProject = vi.fn(), onPlanChange = vi.fn()) {
  return {
    onOpenProject,
    onPlanChange,
    ...render(
      <MemoryRouter>
        <WorksTimeline
          works={[work]}
          installers={[INSTALLER]}
          window={windowFrom("month_days", "2028-02-17")}
          zoom="month_days"
          today="2028-02-17"
          statuses={[STATUS]}
          showIdle={false}
          onOpenProject={onOpenProject}
          onPlanChange={onPlanChange}
        />
      </MemoryRouter>
    ),
  };
}

describe("WorksTimeline project links", () => {
  it("opens a project for a primary click but preserves modified-link semantics", () => {
    const first = renderTimeline(makeWork());
    const link = screen.getByRole("link", { name: /Obra de teste/ });
    fireEvent.click(link);
    expect(first.onOpenProject).toHaveBeenCalledWith("project-1", expect.anything());

    first.onOpenProject.mockClear();
    link.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(link, { ctrlKey: true });
    expect(first.onOpenProject).not.toHaveBeenCalled();
  });

  it("suppresses the click generated after a drag", () => {
    const onOpenProject = vi.fn();
    const onPlanChange = vi.fn();
    renderTimeline(makeWork({ can_plan_work: true }), onOpenProject, onPlanChange);
    const link = screen.getByRole("link", { name: /Obra de teste/ });

    fireEvent.pointerDown(link, { button: 0, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(link, { pointerId: 1, clientX: 80, clientY: 10 });
    fireEvent.pointerUp(link, { pointerId: 1, clientX: 80, clientY: 10 });
    expect(onPlanChange).toHaveBeenCalledTimes(1);

    fireEvent.click(link);
    expect(onOpenProject).not.toHaveBeenCalled();
  });
});
