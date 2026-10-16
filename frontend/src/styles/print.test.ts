import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/app.css", "utf8");

function findBlock(source: string, selector: string, startAt = 0): string {
  const selectorStart = source.indexOf(selector, startAt);
  if (selectorStart < 0) throw new Error(`Bloco CSS em falta: ${selector}`);
  const opening = source.indexOf("{", selectorStart);
  if (opening < 0) throw new Error(`Bloco CSS sem abertura: ${selector}`);

  let depth = 0;
  for (let index = opening; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(opening + 1, index);
  }
  throw new Error(`Bloco CSS sem fecho: ${selector}`);
}

function declarations(block: string): Map<string, string> {
  return new Map(
    [...block.matchAll(/^\s*(--[\w-]+)\s*:\s*([^;]+);/gm)].map(([, name, value]) => [name, value.trim()]),
  );
}

function resolveToken(name: string, values: Map<string, string>, visiting = new Set<string>()): string {
  if (visiting.has(name)) throw new Error(`Ciclo de token CSS: ${name}`);
  const value = values.get(name);
  if (!value) throw new Error(`Token CSS sem valor: ${name}`);
  const reference = /^var\(\s*(--[\w-]+)\s*\)$/.exec(value);
  if (!reference) return value.toLowerCase();
  visiting.add(name);
  return resolveToken(reference[1], values, visiting);
}

const lightTokens = declarations(findBlock(css, ":root"));
const darkThemeStart = css.indexOf(':root[data-theme="dark"]');
const darkTokens = declarations(findBlock(css, ':root[data-theme="dark"]', darkThemeStart));
const printStart = css.lastIndexOf("@media print");
const printCss = findBlock(css, "@media print", printStart);
const printDarkStart = printCss.indexOf(':root[data-theme="dark"]');
const printTokens = declarations(findBlock(printCss, ':root[data-theme="dark"]', printDarkStart));

const printColorTokens = [
  "--bg",
  "--surface",
  "--surface-2",
  "--border",
  "--border-strong",
  "--text",
  "--text-muted",
  "--text-subtle",
  "--brand",
  "--brand-strong",
  "--brand-soft",
  "--on-brand",
  "--accent",
  "--accent-soft",
  "--warning",
  "--warning-soft",
  "--warning-border",
  "--warning-alert-border",
  "--warning-text",
  "--danger",
  "--danger-soft",
  "--danger-border",
  "--danger-text",
  "--danger-row-bg",
  "--info",
  "--info-soft",
  "--info-border",
  "--info-text",
  "--success",
  "--success-soft",
  "--success-border",
  "--violet",
  "--violet-soft",
  "--neutral",
  "--neutral-soft",
];

describe("tokens de impressão", () => {
  it("sobrepõe o tema escuro com os valores claros efetivos", () => {
    expect(printStart).toBeGreaterThan(darkThemeStart);
    expect(printCss).toContain(':root[data-theme="dark"]');
    expect(printCss).toMatch(/color-scheme:\s*light\s*;/);

    for (const token of printColorTokens) {
      expect(darkTokens.has(token), `o tema escuro define ${token}`).toBe(true);
      expect(printTokens.has(token), `a impressão redefine ${token}`).toBe(true);
      const expectedLightToken = token === "--bg" ? "--surface" : token;
      expect(resolveToken(token, printTokens), `${token} na impressão`).toBe(
        resolveToken(expectedLightToken, lightTokens),
      );
    }
  });

  it("remove navegação e permite fluxo e paginação sem cortes artificiais", () => {
    expect(printCss).toMatch(/\.sidebar[\s\S]*\.topbar[\s\S]*\.bottom-nav[\s\S]*\.theme-toggle[\s\S]*\.backdrop[\s\S]*\.modal-backdrop[\s\S]*display:\s*none\s*!important/);
    expect(printCss).toContain("nav {");
    expect(printCss).toMatch(/height:\s*auto\s*!important/);
    expect(printCss).toMatch(/overflow:\s*visible\s*!important/);
    expect(printCss).toMatch(/break-inside:\s*avoid/);
    expect(printCss).toContain(".client-report__preview");
  });
});
