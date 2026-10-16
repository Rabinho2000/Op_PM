import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/pages/IsolatedTimeBank.css", "utf8");

describe("tabela do Banco de Horas no mobile", () => {
  it("mantém o scroll horizontal no contentor da tabela mesmo com a regra global de cartões", () => {
    const scopedTableWrap = css.match(/\.table-wrap\.time-bank-table-wrap\s*\{([\s\S]*?)\}/)?.[1] ?? "";

    expect(scopedTableWrap).toMatch(/min-width:\s*0/);
    expect(scopedTableWrap).toMatch(/max-width:\s*100%/);
    expect(scopedTableWrap).toMatch(/overflow-x:\s*auto/);
  });
});