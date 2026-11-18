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

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`Regra CSS não encontrada: ${selector}`);
  const opening = css.indexOf("{", start);
  const closing = css.indexOf("}", opening);
  if (closing < 0) throw new Error(`Regra CSS sem fecho: ${selector}`);
  return css.slice(opening + 1, closing);
}

function referencedToken(block: string, property: string): string {
  const declaration = block.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${property}:`));
  const value = declaration?.slice(property.length + 1).trim();
  if (!value?.startsWith("var(--") || !value.endsWith(")")) {
    throw new Error(`Declaração ${property} não referencia um token CSS.`);
  }
  return value.slice(4, -1);
}

function luminance(hex: string): number {
  const channels = [0, 2, 4].map((offset) => {
    const value = parseInt(hex.slice(offset + 1, offset + 3), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
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
  "--brand-identity",
  "--brand-fill",
  "--brand-text",
  "--brand-strong",
  "--brand-fill-strong",
  "--brand-soft",
  "--link",
  "--link-hover",
  "--focus-color",
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

  it("mantém contraste de marca nos consumidores reais durante impressão", () => {
    const linkToken = referencedToken(rule("a"), "color");
    const linkColor = resolveToken(linkToken, printTokens);
    const printedSurface = resolveToken("--surface", printTokens);
    expect(contrastRatio(linkColor, printedSurface), "link impresso sobre superfície branca").toBeGreaterThanOrEqual(4.5);

    const planningStyle = rule(".planning-chip");
    const planningText = resolveToken(referencedToken(planningStyle, "color"), printTokens);
    const planningBackground = resolveToken(referencedToken(planningStyle, "background"), printTokens);
    expect(contrastRatio(planningText, planningBackground), "texto do planning chip impresso").toBeGreaterThanOrEqual(4.5);
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
