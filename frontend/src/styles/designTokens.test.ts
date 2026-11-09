import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/app.css", "utf8");
const lightBlock = css.match(/:root\s*\{([^}]*)\}/)?.[1];
const darkBlock = css.match(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/)?.[1];
const printCss = css.slice(css.lastIndexOf("@media print"));
const printBlock = printCss.match(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/)?.[1];

if (!lightBlock || !darkBlock || !printBlock) {
  throw new Error("Não foram encontrados os blocos de tokens claro, escuro e impressão em app.css.");
}

function token(block: string, name: string): string {
  const value = block.match(new RegExp(`--${name}:\\s*(#[\\da-fA-F]{6})`))?.[1];
  if (!value) throw new Error(`Token --${name} não encontrado como cor hexadecimal.`);
  return value;
}

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`Regra CSS não encontrada: ${selector}`);
  const opening = css.indexOf("{", start);
  const closing = css.indexOf("}", opening);
  if (closing < 0) throw new Error(`Regra CSS sem fecho: ${selector}`);
  return css.slice(opening + 1, closing);
}

function componentRule(source: string, selector: string): string {
  const start = source.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`Regra CSS não encontrada: ${selector}`);
  const opening = source.indexOf("{", start);
  const closing = source.indexOf("}", opening);
  if (closing < 0) throw new Error(`Regra CSS sem fecho: ${selector}`);
  return source.slice(opening + 1, closing);
}

async function cssFilesUnder(directory: string): Promise<string[]> {
  const fs = (await import("node:fs")) as unknown as {
    readdirSync: (
      path: string,
      options: { withFileTypes: true },
    ) => Array<{ name: string; isDirectory(): boolean; isFile(): boolean }>;
  };
  const files: string[] = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) files.push(...(await cssFilesUnder(path)));
    else if (entry.isFile() && path.endsWith(".css")) files.push(path);
  }
  return files;
}

function colorDeclaration(block: string, property: string, themeBlock: string): string {
  const declaration = block.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${property}:`));
  const value = declaration?.slice(property.length + 1).trim();
  if (!value?.startsWith("var(--") || !value.endsWith(")")) {
    throw new Error(`Declaração ${property} não referencia um token CSS.`);
  }
  return token(themeBlock, value.slice(6, -1));
}

function propertyValue(block: string, property: string): string {
  const declaration = block.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${property}:`));
  const value = declaration?.slice(property.length + 1).trim();
  if (!value) throw new Error(`Declaração ${property} não encontrada.`);
  return value;
}

function resolvedColor(block: string, property: string, themeBlock: string): string {
  const value = propertyValue(block, property);
  const tokenName = /^var\(--([\w-]+)(?:\s*,[^)]*)?\)$/.exec(value)?.[1];
  if (tokenName) return token(themeBlock, tokenName);
  if (/^white$/i.test(value)) return "#ffffff";
  if (/^#[\da-fA-F]{6}$/.test(value)) return value;
  if (/^#[\da-fA-F]{3}$/.test(value)) {
    return `#${[...value.slice(1)].map((channel) => `${channel}${channel}`).join("")}`;
  }
  throw new Error(`Declaração ${property} não pôde ser resolvida como cor: ${value}`);
}

function channels(hex: string): [number, number, number] {
  const values = hex.match(/[\da-fA-F]{2}/g)?.map((channel) => parseInt(channel, 16));
  if (!values || values.length !== 3) throw new Error(`Cor hexadecimal inválida: ${hex}`);
  return [values[0], values[1], values[2]];
}

function linearChannel(value: number): number {
  const channel = value / 255;
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const [red, green, blue] = channels(hex).map(linearChannel);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

const themes = [
  { name: "claro", block: lightBlock },
  { name: "escuro", block: darkBlock },
] as const;

const componentThemes = [
  ...themes,
  { name: "impressão", block: printBlock },
] as const;

const textPairs = [
  ["text", "bg"],
  ["text", "surface"],
  ["text", "surface-2"],
  ["text", "surface-3"],
  ["text-muted", "bg"],
  ["text-muted", "surface"],
  ["text-subtle", "bg"],
  ["text-subtle", "surface"],
  ["sidebar-text", "sidebar-bg"],
  ["brand", "brand-soft"],
  ["brand-text", "brand-soft"],
  ["brand-text", "bg"],
  ["brand-text", "surface"],
  ["brand-strong", "brand-soft"],
  ["brand-strong", "bg"],
  ["brand-strong", "surface"],
  ["link", "bg"],
  ["link", "surface"],
  ["success", "success-soft"],
  ["warning", "warning-soft"],
  ["danger", "danger-soft"],
  ["info", "info-soft"],
  ["violet", "violet-soft"],
  ["neutral", "neutral-soft"],
  ["on-brand", "brand-identity"],
  ["on-brand", "brand-fill"],
  ["on-brand", "brand-fill-strong"],
] as const;

const focusSurfaces = ["bg", "surface", "surface-2", "surface-3", "sidebar-bg"] as const;

describe("fundação visual dos temas", () => {
  it.each(themes)("mantém neutros sem dominante cromática no tema $name", ({ block }) => {
    const neutralTokens = [
      "bg",
      "surface",
      "surface-2",
      "surface-3",
      "sidebar-bg",
      "sidebar-bg-2",
      "border",
      "border-strong",
      "text",
      "text-muted",
      "text-subtle",
    ];

    for (const name of neutralTokens) {
      const [red, green, blue] = channels(token(block, name));
      expect(Math.max(red, green, blue) - Math.min(red, green, blue), `--${name}`).toBeLessThanOrEqual(6);
    }
  });

  it.each(themes)("preserva a identidade Solcor e os papéis de texto do tema ($name)", ({ name, block }) => {
    const readableBrand = name === "escuro" ? "#83cba4" : "#125c37";
    expect(token(block, "brand-identity")).toBe("#1e7a4b");
    expect(token(block, "brand-fill")).toBe("#1e7a4b");
    expect(token(block, "brand-fill-strong")).toBe("#125c37");
    expect(token(block, "brand-strong")).toBe(readableBrand);
    expect(token(block, "brand-text")).toBe(readableBrand);
  });

  it.each(themes)("mantém contraste de texto normal >= 4.5:1 no tema $name", ({ block }) => {
    for (const [foreground, background] of textPairs) {
      const ratio = contrastRatio(token(block, foreground), token(block, background));
      expect(ratio, `--${foreground} sobre --${background}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(themes)("mantém contraste dos consumidores reais de marca no tema $name", ({ name, block }) => {
    const softBackgroundConsumers = [
      ".avatar",
      '.segmented button[aria-pressed="true"]',
      ".planning-chip",
      ".works__bar--brand",
    ];

    for (const selector of softBackgroundConsumers) {
      const style = rule(selector);
      const foreground = colorDeclaration(style, "color", block);
      const background = colorDeclaration(style, "background", block);
      expect(
        contrastRatio(foreground, background),
        `${selector}: texto sobre fundo de marca`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    for (const selector of [".brand-mark", ".calendar__cell--today .calendar__num"]) {
      const style = rule(selector);
      const foreground = colorDeclaration(style, "color", block);
      const background = colorDeclaration(style, "background", block);
      expect(
        contrastRatio(foreground, background),
        `${selector}: texto sobre preenchimento de marca`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    const selectedTabColor = colorDeclaration(rule('.tab[aria-selected="true"]'), "color", block);
    for (const backgroundName of ["bg", "surface", "surface-2"]) {
      expect(
        contrastRatio(selectedTabColor, token(block, backgroundName)),
        `.tab selecionada sobre --${backgroundName}`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    const linkColor = colorDeclaration(rule("a"), "color", block);
    for (const backgroundName of ["bg", "surface"]) {
      expect(
        contrastRatio(linkColor, token(block, backgroundName)),
        `link sobre --${backgroundName}`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    if (name === "escuro") {
      for (const selector of [
        ':root[data-theme="dark"] .requests-widget__trigger',
        ':root[data-theme="dark"] .requests-widget__trigger:hover',
      ]) {
        const style = rule(selector);
        const foreground = colorDeclaration(style, "color", block);
        const background = colorDeclaration(style, "background", block);
        expect(contrastRatio(foreground, background), `${selector}: texto do botão de marca`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it.each(themes)("mantém foco visível >= 3:1 contra superfícies no tema $name", ({ block }) => {
    for (const background of focusSurfaces) {
      const ratio = contrastRatio(token(block, "focus-color"), token(block, background));
      expect(ratio, `--focus-color sobre --${background}`).toBeGreaterThanOrEqual(3);
    }
  });

  it.each(componentThemes.map(({ name, block }) => ({
    name,
    block,
    expectedForeground: name === "escuro" ? "#1c1c1e" : "#ffffff",
  })))("mantém contraste dos clusters do mapa >= 4.5:1 no tema $name", ({ block, expectedForeground }) => {
    const clusterColor = propertyValue(rule(".map-cluster"), "color");
    const colorToken = /^var\(--([\w-]+)\)$/.exec(clusterColor)?.[1];
    if (!colorToken) throw new Error("A cor do texto .map-cluster não referencia um token CSS.");
    expect(colorToken).toBe("on-status-fill");

    const foreground = token(block, colorToken);
    expect(foreground).toBe(expectedForeground);
    const variants = [
      { selector: ".map-cluster--attention-green", backgrounds: ["success"] },
      { selector: ".map-cluster--attention-yellow", backgrounds: ["warning"] },
      { selector: ".map-cluster--attention-red", backgrounds: ["danger"] },
      { selector: ".map-cluster--lifecycle-construcao", backgrounds: ["info"] },
      { selector: ".map-cluster--lifecycle-preparacao", backgrounds: ["accent"] },
      { selector: ".map-cluster--lifecycle-mixed", backgrounds: ["info", "accent"] },
    ] as const;

    for (const { selector, backgrounds } of variants) {
      const background = propertyValue(rule(selector), "background");
      const backgroundTokens = [...background.matchAll(/var\(--([\w-]+)\)/g)].map((match) => match[1]);
      expect(backgroundTokens, `${selector}: tokens de fundo reais`).toEqual(backgrounds);

      for (const backgroundToken of backgrounds) {
        const ratio = contrastRatio(foreground, token(block, backgroundToken));
        expect(ratio, `${selector}: texto sobre --${backgroundToken}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});

function lightTextViolations(source: string): string[] {
  const violations: string[] = [];
  const dangerousBackground = /var\(\s*--(?:danger|success|warning|info|accent)(?:\s*,|\s*\))/i;
  const lightText = /^(?:var\(\s*--on-brand(?:\s*,[^)]*)?\s*\)|#(?:fff|ffffff)(?![\da-f])|white\b|rgba?\(\s*255(?:\s*,\s*|\s+)255(?:\s*,\s*|\s+)255(?:\s*(?:,\s*(?:1(?:\.0*)?|100%)|\/\s*(?:1(?:\.0*)?|100%)))?\s*\))(?:\s|!|$)/i;
  const uncommented = source.replace(/\/\*[\s\S]*?\*\//g, "");

  for (const match of uncommented.matchAll(/\{([^{}]*)\}/g)) {
    const declarations = match[1].split(";").map((part) => part.trim());
    const background = declarations.find((part) => /^(?:background|background-color)\s*:/i.test(part));
    const foreground = declarations.find((part) => /^color\s*:/i.test(part));
    if (!background || !foreground) continue;
    const backgroundValue = background.slice(background.indexOf(":") + 1).trim();
    const foregroundValue = foreground.slice(foreground.indexOf(":") + 1).trim();
    if (dangerousBackground.test(backgroundValue) && lightText.test(foregroundValue)) {
      violations.push(`${background}; ${foreground}`);
    }
  }

  return violations;
}

describe("contraste dos componentes com fundo de perigo", () => {
  const consumers = [
    { file: "src/pages/IsolatedTimeBank.css", selector: ".btn--danger" },
    { file: "src/pages/IsolatedTimeBank.css", selector: ".btn--danger:hover" },
    { file: "src/components/ProcessAlertBell.css", selector: ".process-alert-bell__count" },
  ] as const;

  it.each(componentThemes)("mantém texto >= 4.5:1 nos componentes reais no tema $name", ({ block }) => {
    for (const { file, selector } of consumers) {
      const style = componentRule(readFileSync(file, "utf8"), selector);
      const foreground = resolvedColor(style, "color", block);
      const background = resolvedColor(style, "background", block);
      expect(
        contrastRatio(foreground, background),
        `${file} ${selector}: texto sobre fundo no tema testado`,
      ).toBeGreaterThanOrEqual(4.5);
    }

    for (const { file, selector } of [consumers[0], consumers[2]]) {
      const style = componentRule(readFileSync(file, "utf8"), selector);
      expect(propertyValue(style, "color")).toBe("var(--on-status-fill)");
    }

    const badge = componentRule(readFileSync(consumers[2].file, "utf8"), consumers[2].selector);
    expect(propertyValue(badge, "font-size")).toBe("11px");
    expect(propertyValue(badge, "font-weight")).toBe("700");
  });

  it("deteta fallback branco e literais claros em CSS sintético", () => {
    const sampleCss = [
      ".fallback { background: var(--danger); color: var(--on-brand, #fff); }",
      ".named { background: var(--success); color: white; }",
      ".short { background: var(--warning); color: #fff; }",
      ".full { background: var(--info); color: #ffffff; }",
      ".rgb { background: var(--accent); color: rgb(255, 255, 255); }",
    ].join("\n");

    expect(lightTextViolations(sampleCss)).toHaveLength(5);
    expect(lightTextViolations(sampleCss)[0]).toContain("var(--on-brand, #fff)");
  });

  it("impede texto branco ou --on-brand sobre preenchimentos de estado em todo o CSS", async () => {
    const violations: string[] = [];

    for (const file of await cssFilesUnder("src")) {
      const source = readFileSync(file, "utf8");
      violations.push(...lightTextViolations(source).map((violation) => `${file}: ${violation}`));
    }

    expect(violations).toEqual([]);
  });
});
