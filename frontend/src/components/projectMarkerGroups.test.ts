import { describe, expect, it } from "vitest";
import {
  buildProjectLocationPopup,
  groupCoincidentProjects,
  PROJECT_CLUSTER_OPTIONS,
  type LocatedProject,
} from "./projectMarkerGroups";

function project(overrides: Partial<LocatedProject> = {}): LocatedProject {
  return {
    key: "project-1",
    projectId: "project-1",
    name: "Projeto Um",
    status: "Construção",
    lat: 38.7,
    lon: -9.1,
    ...overrides,
  };
}

describe("marcadores de projetos coincidentes", () => {
  it("agrupa todos os projetos na mesma posição sem alterar as coordenadas", () => {
    const projects = [
      project(),
      project({ key: "project-2", projectId: "project-2", name: "Projeto Dois", status: "Preparação" }),
      project({ key: "project-3", projectId: "project-3", name: "Projeto Três" }),
    ];

    const groups = groupCoincidentProjects(projects);

    expect(groups).toHaveLength(1);
    expect(groups[0]).toEqual(projects);
    expect(groups[0].map(({ lat, lon }) => [lat, lon])).toEqual([
      [38.7, -9.1],
      [38.7, -9.1],
      [38.7, -9.1],
    ]);
  });

  it("não agrupa projetos em posições distintas, mesmo quando próximas", () => {
    const projects = [
      project(),
      project({ key: "project-2", projectId: "project-2", lat: 38.700001 }),
    ];

    expect(groupCoincidentProjects(projects)).toEqual([]);
  });

  it("gera um popup com nome, estado e ligação para cada projeto coincidente", () => {
    const popup = buildProjectLocationPopup([
      project(),
      project({ key: "project-2", projectId: "project-2", name: "Projeto Dois", status: "Preparação" }),
      project({ key: "project-3", projectId: "project-3", name: "Projeto Três", status: "Concluído" }),
    ]);

    expect(popup).toContain('href="/projects/project-1"');
    expect(popup).toContain("Projeto Um");
    expect(popup).toContain("Construção");
    expect(popup).toContain('href="/projects/project-2"');
    expect(popup).toContain("Projeto Dois");
    expect(popup).toContain("Preparação");
    expect(popup).toContain('href="/projects/project-3"');
    expect(popup).toContain("Projeto Três");
    expect(popup).toContain("Concluído");
  });

  it("escapa conteúdo variável inserido no popup", () => {
    const popup = buildProjectLocationPopup([
      project({ projectId: "id&1", name: '<img src=x onerror="alert(1)">', status: "A&B" }),
    ]);

    expect(popup).toContain("/projects/id%261");
    expect(popup).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
    expect(popup).toContain("A&amp;B");
    expect(popup).not.toContain('<img src=x');
  });

  it("mantém o spiderfy e zoom-to-bounds do agrupamento sem desativar clusters", () => {
    expect(PROJECT_CLUSTER_OPTIONS).toMatchObject({
      spiderfyOnMaxZoom: true,
      zoomToBoundsOnClick: true,
      maxClusterRadius: 50,
    });
    expect("disableClusteringAtZoom" in PROJECT_CLUSTER_OPTIONS).toBe(false);
  });
});
