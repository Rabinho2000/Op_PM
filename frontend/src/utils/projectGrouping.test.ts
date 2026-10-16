import { describe, expect, it } from "vitest";
import { makeProject } from "../test/fixtures";
import { NO_LIFECYCLE_STATUS_KEY, groupProjectsByLifecycle } from "./projectGrouping";

const statuses = [
  { code: "preparacao", label: "Preparação", flow_position: 1 },
  { code: "construcao", label: "Construção", flow_position: 2 },
];

describe("groupProjectsByLifecycle", () => {
  it("agrupa null e estados desconhecidos num grupo explícito sem estado", () => {
    const groups = groupProjectsByLifecycle(
      [
        makeProject({ id: "sem-estado", lifecycle_status: null }),
        makeProject({ id: "legado", lifecycle_status: "estado_que_ja_nao_existe" }),
      ],
      statuses
    );

    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ key: NO_LIFECYCLE_STATUS_KEY, label: "Sem estado", status: null });
    expect(groups[0].projects.map((project) => project.id)).toEqual(["sem-estado", "legado"]);
  });

  it("segue a ordem do catálogo e preserva a ordem da API dentro de cada estado", () => {
    const groups = groupProjectsByLifecycle(
      [
        makeProject({ id: "c-mais-antigo", lifecycle_status: "construcao" }),
        makeProject({ id: "p-mais-antigo", lifecycle_status: "preparacao" }),
        makeProject({ id: "c-mais-recente", lifecycle_status: "construcao" }),
      ],
      statuses
    );

    expect(groups.map((group) => [group.label, group.projects.length])).toEqual([
      ["Preparação", 1],
      ["Construção", 2],
    ]);
    expect(groups[1].projects.map((project) => project.id)).toEqual(["c-mais-antigo", "c-mais-recente"]);
  });
});
