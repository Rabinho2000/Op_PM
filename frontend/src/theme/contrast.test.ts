import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/app.css", "utf8");
const lightBlock = css.match(/:root\s*\{([^}]*)\}/)?.[1];
const darkBlock = css.match(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/)?.[1];

if (!lightBlock || !darkBlock) {
  throw new Error(`Não foram encontrados os blocos de tokens claro e escuro. Conteúdo importado: ${String(css).slice(0, 160)}`);
}

function token(block: string, name: string): string {
  const value = block.match(new RegExp(`--${name}:\\s*(#[\\da-fA-F]{6})`))?.[1];
  if (!value) throw new Error(`Token --${name} não encontrado como cor hexadecimal.`);
  return value;
}

function linearChannel(value: number): number {
  const channel = value / 255;
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const channels = hex.match(/[\da-fA-F]{2}/g)?.map((channel) => linearChannel(parseInt(channel, 16)));
  if (!channels || channels.length !== 3) throw new Error(`Cor hexadecimal inválida: ${hex}`);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

const contrastPairs = [
  { foreground: "text", background: "bg", minimum: 4.5 },
  { foreground: "text", background: "surface", minimum: 4.5 },
  { foreground: "text", background: "surface-2", minimum: 4.5 },
  { foreground: "text-muted", background: "bg", minimum: 4.5 },
  { foreground: "text-muted", background: "surface", minimum: 4.5 },
  { foreground: "text-subtle", background: "bg", minimum: 4.5 },
  { foreground: "text-subtle", background: "surface", minimum: 4.5 },
  { foreground: "sidebar-text", background: "sidebar-bg", minimum: 4.5 },
  { foreground: "brand", background: "brand-soft", minimum: 4.5 },
  { foreground: "success", background: "success-soft", minimum: 4.5 },
  { foreground: "warning", background: "warning-soft", minimum: 4.5 },
  { foreground: "danger", background: "danger-soft", minimum: 4.5 },
  { foreground: "info", background: "info-soft", minimum: 4.5 },
  { foreground: "violet", background: "violet-soft", minimum: 4.5 },
  { foreground: "neutral", background: "neutral-soft", minimum: 4.5 },
] as const;

describe("contraste WCAG dos tokens", () => {
  it.each(["light", "dark"] as const)("mede os pares principais no tema %s", (theme) => {
    const block = theme === "dark" ? darkBlock : lightBlock;
    const ratios = contrastPairs.map((pair) => ({
      ...pair,
      ratio: contrastRatio(token(block, pair.foreground), token(block, pair.background)),
    }));

    if (theme === "dark") {
      console.info(
        [
          "Rácios de contraste dark (WCAG):",
          ...ratios.map((pair) => `${pair.foreground}/${pair.background}: ${pair.ratio.toFixed(2)}:1`),
        ].join(String.fromCharCode(10)),
      );
    } else {
      const violet = ratios.find((pair) => pair.foreground === "violet");
      if (violet) console.info(`Rácio violet/violet-soft claro: ${violet.ratio.toFixed(4)}:1`);
    }

    for (const pair of ratios) {
      const key = `${pair.foreground}/${pair.background}`;
      expect(pair.ratio, `${theme}: ${key}`).toBeGreaterThanOrEqual(pair.minimum);
    }
  });
});
