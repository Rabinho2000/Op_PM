import { describe, expect, it } from "vitest";
import type { Installer, WorkItem } from "../api/client";
import {
  addDays,
  addMonths,
  barGeometry,
  buildRows,
  dayPosition,
  daysBetween,
  defaultWindow,
  endOfMonth,
  formatIsoPt,
  monthTicks,
  packLanes,
  shiftWindow,
  startOfWeek,
  totalDays,
  weekTicks,
  windowFrom,
} from "./worksTimeline";

function work(id: string, start: string, end: string, extra: Partial<WorkItem> = {}): WorkItem {
  return {
    project_id: id,
    name: `Obra ${id}`,
    client_name: null,
    pm_person_id: null,
    pm_display_name: null,
    lifecycle_status: "construcao",
    installer_id: null,
    installer_name: null,
    installer_team_id: null,
    installer_team_name: null,
    work_start_date: start,
    work_end_date: end,
    work_dates_estimated: false,
    conflict: false,
    ...extra,
  };
}

describe("datas (UTC, sem deslocar dias)", () => {
  it("soma dias e meses atravessando fins de mês, anos e mudanças de hora", () => {
    expect(addDays("2026-03-28", 3)).toBe("2026-03-31"); // mudança para a hora de verão em PT
    expect(addDays("2026-10-25", 1)).toBe("2026-10-26"); // e de volta
    expect(addDays("2026-12-30", 3)).toBe("2027-01-02");
    expect(addMonths("2026-11-15", 3)).toBe("2027-02-01");
    expect(addMonths("2026-02-01", -3)).toBe("2025-11-01");
    expect(endOfMonth("2028-02-01")).toBe("2028-02-29");
    expect(daysBetween("2026-03-01", "2026-04-01")).toBe(31);
  });

  it("a semana começa à segunda-feira", () => {
    expect(startOfWeek("2026-09-24")).toBe("2026-09-21"); // quinta
    expect(startOfWeek("2026-09-27")).toBe("2026-09-21"); // domingo
    expect(startOfWeek("2026-09-21")).toBe("2026-09-21"); // segunda
  });

  it("formata como dia/mês/ano", () => {
    expect(formatIsoPt("2026-05-12")).toBe("12/05/2026");
  });
});

describe("janelas", () => {
  it("meses: 10 meses inteiros, de -3 a +6 meses à volta de hoje (D10)", () => {
    const w = defaultWindow("months", "2026-09-24");
    expect(w).toEqual({ from: "2026-06-01", to: "2027-03-31" });
    expect(totalDays(w)).toBe(304);
  });

  it("semanas: 10 semanas a começar numa segunda-feira, 2 semanas antes de hoje", () => {
    const w = defaultWindow("weeks", "2026-09-24");
    expect(w.from).toBe("2026-09-07");
    expect(totalDays(w)).toBe(70);
    expect(new Date(`${w.from}T00:00:00Z`).getUTCDay()).toBe(1);
  });

  it("trimestres: 19 meses", () => {
    expect(defaultWindow("quarters", "2026-09-24")).toEqual({ from: "2026-03-01", to: "2027-09-30" });
  });

  it("deslocar para a frente e para trás mantém a duração e é reversível", () => {
    const months = (w: { from: string; to: string }) =>
      (Number(w.to.slice(0, 4)) - Number(w.from.slice(0, 4))) * 12 + Number(w.to.slice(5, 7)) - Number(w.from.slice(5, 7)) + 1;
    for (const zoom of ["weeks", "months", "quarters"] as const) {
      const w = defaultWindow(zoom, "2026-09-24");
      const next = shiftWindow(zoom, w.from, 1);
      // Semanas: mesma duração em dias; meses/trimestres: mesmo número de meses (os dias variam).
      if (zoom === "weeks") expect(totalDays(next)).toBe(totalDays(w));
      else expect(months(next)).toBe(months(w));
      expect(next.from > w.from).toBe(true);
      expect(shiftWindow(zoom, next.from, -1)).toEqual(w);
    }
    expect(shiftWindow("months", "2026-06-01", 1).from).toBe("2026-09-01");
    expect(shiftWindow("weeks", "2026-09-07", -1).from).toBe("2026-08-10");
  });

  it("windowFrom arredonda ao início do mês/semana", () => {
    expect(windowFrom("months", "2026-06-17").from).toBe("2026-06-01");
    expect(windowFrom("weeks", "2026-09-24").from).toBe("2026-09-21");
  });
});

describe("barGeometry", () => {
  const w = { from: "2026-06-01", to: "2026-06-30" }; // 30 dias

  it("posiciona pelo dia e inclui os dois extremos", () => {
    expect(barGeometry("2026-06-03", "2026-06-05", w, 10)).toEqual({ left: 20, width: 30, clippedStart: false, clippedEnd: false });
    expect(barGeometry("2026-06-01", "2026-06-01", w, 10).width).toBe(10); // um dia
  });

  it("corta ao que está dentro da janela e assinala os cortes", () => {
    expect(barGeometry("2026-05-20", "2026-06-03", w, 10)).toEqual({ left: 0, width: 30, clippedStart: true, clippedEnd: false });
    expect(barGeometry("2026-06-28", "2026-07-10", w, 10)).toEqual({ left: 270, width: 30, clippedStart: false, clippedEnd: true });
    expect(barGeometry("2026-05-01", "2026-08-01", w, 10)).toMatchObject({ left: 0, width: 300, clippedStart: true, clippedEnd: true });
  });

  it("dayPosition devolve null fora da janela", () => {
    expect(dayPosition("2026-06-10", w, 10)).toBe(90);
    expect(dayPosition("2026-05-31", w, 10)).toBeNull();
    expect(dayPosition("2026-07-01", w, 10)).toBeNull();
  });
});

describe("packLanes", () => {
  it("obras que partilham um dia ficam em faixas diferentes; encostadas reaproveitam a faixa", () => {
    const a = work("a", "2026-06-01", "2026-06-05");
    const b = work("b", "2026-06-05", "2026-06-08"); // partilha o dia 5
    const c = work("c", "2026-06-06", "2026-06-10"); // a faixa de A já está livre
    const { lanes, count } = packLanes([c, a, b]);
    expect(lanes.get("a")).toBe(0);
    expect(lanes.get("b")).toBe(1);
    expect(lanes.get("c")).toBe(0);
    expect(count).toBe(2);
  });

  it("uma cadeia sobreposta usa o número mínimo de faixas", () => {
    const works = [work("1", "2026-06-01", "2026-06-10"), work("2", "2026-06-02", "2026-06-03"), work("3", "2026-06-02", "2026-06-04"), work("4", "2026-06-11", "2026-06-12")];
    expect(packLanes(works).count).toBe(3);
  });

  it("sem obras não há faixas", () => {
    expect(packLanes([]).count).toBe(0);
  });
});

describe("buildRows", () => {
  const installers: Installer[] = [
    {
      id: "vm",
      name: "Instalador A",
      is_active: true,
      project_count: 0,
      teams: [
        { id: "t1", name: "Equipa 1", leader_name: null, leader_phone: null, is_active: true, project_count: 0 },
        { id: "t2", name: "Equipa 2", leader_name: null, leader_phone: null, is_active: true, project_count: 0 },
        { id: "t3", name: "Equipa 3", leader_name: null, leader_phone: null, is_active: false, project_count: 0 },
      ],
    },
    { id: "gps", name: "Instalador B", is_active: true, project_count: 0, teams: [] },
    { id: "off", name: "Parado", is_active: false, project_count: 0, teams: [] },
  ];

  it("cabeçalho do instalador + uma linha por equipa com obras + 'Sem equipa'", () => {
    const works = [
      work("a", "2026-06-01", "2026-06-05", { installer_id: "vm", installer_team_id: "t1" }),
      work("b", "2026-06-03", "2026-06-08", { installer_id: "vm", installer_team_id: "t1" }),
      work("c", "2026-06-01", "2026-06-05", { installer_id: "vm", installer_team_id: null }),
    ];
    const rows = buildRows(works, installers);
    expect(rows.map((r) => `${r.kind}:${r.label}`)).toEqual(["header:Instalador A", "lane:Equipa 1", "lane:Sem equipa"]);
    expect(rows[1].laneCount).toBe(2); // A e B sobrepõem-se
    expect(rows[1].indent).toBe(true);
    expect(rows[0].works).toEqual([]);
  });

  it("instalador sem equipas: uma só linha; sem instalador: no fim", () => {
    const works = [
      work("g", "2026-06-01", "2026-06-05", { installer_id: "gps" }),
      work("x", "2026-06-01", "2026-06-05"),
    ];
    const rows = buildRows(works, installers);
    expect(rows.map((r) => r.label)).toEqual(["Instalador B", "Sem instalador"]);
    expect(rows.every((r) => r.kind === "lane")).toBe(true);
  });

  it("por omissão esconde instaladores e equipas sem obras; showIdle mostra as ativas", () => {
    expect(buildRows([], installers)).toEqual([]);
    const idle = buildRows([], installers, true);
    expect(idle.map((r) => `${r.kind}:${r.label}`)).toEqual([
      "header:Instalador A",
      "lane:Equipa 1",
      "lane:Equipa 2", // a Equipa 3 está inativa
      "lane:Instalador B", // o instalador inativo 'Parado' não aparece
    ]);
    expect(idle.filter((r) => r.kind === "lane").every((r) => r.muted)).toBe(true);
  });

  it("uma equipa inativa com obras continua a aparecer", () => {
    const rows = buildRows([work("z", "2026-06-01", "2026-06-02", { installer_id: "vm", installer_team_id: "t3" })], installers);
    expect(rows.map((r) => r.label)).toEqual(["Instalador A", "Equipa 3"]);
  });
});

describe("cabeçalho", () => {
  it("uma marca por mês com a largura certa (meses parciais no fim incluídos)", () => {
    const ticks = monthTicks({ from: "2026-06-01", to: "2026-08-15" }, 2);
    expect(ticks.map((t) => t.label)).toEqual(["jun 2026", "jul 2026", "ago 2026"]);
    expect(ticks[0]).toMatchObject({ left: 0, width: 60 });
    expect(ticks[1]).toMatchObject({ left: 60, width: 62 });
    expect(ticks[2].width).toBe(30); // até 15 de agosto
  });

  it("uma marca por segunda-feira dentro da janela", () => {
    const ticks = weekTicks({ from: "2026-09-09", to: "2026-09-30" }, 10); // quarta
    expect(ticks.map((t) => t.iso)).toEqual(["2026-09-14", "2026-09-21", "2026-09-28"]);
    expect(ticks[0]).toMatchObject({ left: 50, day: 14 });
  });
});
