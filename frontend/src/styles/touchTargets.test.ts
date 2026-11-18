import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/app.css", "utf8");

function mediaBlock(source: string, prelude: string): string {
  const start = source.lastIndexOf(prelude);
  if (start < 0) return "";
  const opening = source.indexOf("{", start);
  let depth = 0;
  for (let index = opening; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(opening + 1, index);
    }
  }
  return "";
}

function ruleForSelectors(source: string, expectedSelectors: string[]): string {
  for (const match of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = match[1].split(",").map((selector) => selector.trim());
    if (expectedSelectors.every((selector) => selectors.includes(selector))) return match[2];
  }
  return "";
}

describe("alvos tácteis globais", () => {
  it("define 44px para controlos e segmentos em mobile ou pointer coarse", () => {
    const mobileTargets = mediaBlock(css, "@media (max-width: 760px), (pointer: coarse)");
    const declarations = ruleForSelectors(mobileTargets, [
      "main button:not(.works__bar)",
      "main .btn",
      "main .btn--sm",
      "main .select",
      "main .input",
      "main .tab",
      'main [role="tab"]',
      "main .segmented button",
      "main .inventory-owner-toggle__button",
      "main .link-button.cell-title",
    ]);

    expect(mobileTargets).not.toBe("");
    expect(declarations).toMatch(/min-height:\s*44px(?:\s*!important)?\s*;/);
    expect(css).toMatch(/\.btn--sm\s*\{[^}]*min-height:\s*36px/s);
  });

  it("mantém largura mínima de 44px nos botões só-ícone", () => {
    const mobileTargets = mediaBlock(css, "@media (max-width: 760px), (pointer: coarse)");
    const declarations = ruleForSelectors(mobileTargets, ["main .btn--icon", "main .planning-day-add"]);

    expect(declarations).toMatch(/min-width:\s*44px(?:\s*!important)?\s*;/);
  });

  it("dá 44px aos links autónomos de listas, tabelas, cartões e contactos", () => {
    const mobileTargets = mediaBlock(css, "@media (max-width: 760px), (pointer: coarse)");
    const linkSelectors = [
      "main a.list__title",
      "main .list-more a",
      "main .dashboard-works-panel .list a",
      "main .home-dashboard__indicators + .alert a",
      "main .projects-page .table td a.cell-title",
      "main .tasks-page .table td a:not(.works__bar)",
      "main .works-page .table td a:not(.works__bar)",
      "main .works__unscheduled a",
      "main .suppliers-page .table td a",
    ];
    const declarations = ruleForSelectors(mobileTargets, linkSelectors);

    expect(declarations).toMatch(/min-height:\s*44px\s*;/);
    expect(declarations).toMatch(/display:\s*inline-flex\s*;/);
    expect(declarations).toMatch(/align-items:\s*center\s*;/);
    expect(declarations).toMatch(/padding-block:\s*\d+px\s*;/);
    expect(mobileTargets).not.toMatch(/main\s+p\s+a\s*\{/);
    expect(mobileTargets).not.toMatch(/main\s+a\s*\{/);
  });
});
