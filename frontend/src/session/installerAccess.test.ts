import { describe, expect, it } from "vitest";
import { makeMe } from "../test/fixtures";
import { isInstallerCollaborator } from "./installerAccess";

describe("installer access capability guard", () => {
  it("recognizes the external six-capability scope without granting global access", () => {
    expect(isInstallerCollaborator(makeMe({
      roles: ["instalador_colaborador"],
      permissions: [
        "project.view_assigned_installer",
        "task.view_assigned_installer",
        "works_calendar.view_assigned_installer",
        "installer_team.view_assigned_installer",
        "inventory.view_assigned_installer",
        "time_bank.view_own",
      ],
    }))).toBe(true);
  });

  it("keeps a combined staff grant on the existing staff UI branch", () => {
    expect(isInstallerCollaborator(makeMe({ permissions: ["project.view_assigned_installer", "project.view_all"] }))).toBe(false);
  });
});
