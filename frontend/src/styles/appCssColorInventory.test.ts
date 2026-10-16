import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/app.css", "utf8");
const withoutTokenBlocks = css
  .replace(/:root\[data-theme="dark"\]\s*\{[^}]*\}|:root\s*\{[^}]*\}/g, "")
  .replace(/\/\*[\s\S]*?\*\//g, "");
const colorLiteral = /#[\da-f]{3,8}\b|(?:rgba?|hsla?)\([^)]*\)|\b(?:white|black|transparent|currentcolor)\b(?![-\w])/gi;
const occurrences = withoutTokenBlocks.split("\n").flatMap((line, index) =>
  [...line.matchAll(colorLiteral)].map((match) => ({ line: index + 1, value: match[0] })),
);

// `transparent` and `currentColor` are retained CSS semantics, not fixed colors;
// allow them explicitly while requiring every chromatic literal to use tokens.
const allowedColorLiterals = new Set(["transparent", "currentcolor"]);
const unexpectedOccurrences = occurrences.filter(
  ({ value }) => !allowedColorLiterals.has(value.toLowerCase()),
);

describe("inventário de literais de cor do app.css", () => {
  it("permite apenas palavras-chave CSS explicitamente justificadas", () => {
    console.info(
      `Inventário: ${occurrences.length} ocorrências permitidas em ${new Set(occurrences.map(({ line }) => line)).size} linhas; ${unexpectedOccurrences.length} não autorizadas`,
    );
    expect(unexpectedOccurrences).toEqual([]);
  });
});
