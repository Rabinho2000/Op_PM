import { describe, expect, it } from "vitest";
import { rankInventoryItem, searchInventoryItems } from "./inventorySearch";

const items = [
  { id: "exact", name: "Cabo DC", sku: "X-1", category: "Cabos DC" },
  { id: "prefix", name: "Cabo DC solar 6mm", sku: "X-2", category: "Cabos DC" },
  { id: "contains", name: "Kit para cabo DC", sku: "X-3", category: "Consumíveis" },
  { id: "reference", name: "Condutor solar", sku: "CABO-DC-6", category: "Cabos DC" },
  { id: "typo", name: "Inversor Huawei SUN2000", sku: "INV-5K", category: "Inversores" },
];

describe("pesquisa do inventário", () => {
  it("ignora acentos e maiúsculas", () => {
    expect(searchInventoryItems(items, "PAINEIS").map(({ id }) => id)).toEqual([]);
    expect(searchInventoryItems([{ ...items[0], category: "Painéis" }], "paineis").map(({ id }) => id)).toEqual(["exact"]);
  });

  it("encontra palavras em qualquer ordem e prefixos", () => {
    expect(searchInventoryItems(items, "inv hua").map(({ id }) => id)).toContain("typo");
    expect(searchInventoryItems(items, "cabo 6").map(({ id }) => id)).toContain("prefix");
  });

  it("tolera um erro em palavras com pelo menos cinco letras", () => {
    expect(searchInventoryItems(items, "inversor huawey").map(({ id }) => id)).toContain("typo");
  });

  it("expande os sinónimos mínimos de categoria/produto", () => {
    expect(searchInventoryItems([{ ...items[0], name: "Módulo fotovoltaico", category: "Painéis" }], "painel").map(({ id }) => id)).toEqual(["exact"]);
    expect(searchInventoryItems([items[4]], "inverter").map(({ id }) => id)).toContain("typo");
    expect(searchInventoryItems([{ ...items[0], name: "Fio solar" }], "cabo").map(({ id }) => id)).toContain("exact");
  });

  it("ordena exato, prefixo, contém, referência e aproximação", () => {
    expect(searchInventoryItems(items, "cabo dc").map(({ id }) => id).slice(0, 4)).toEqual([
      "exact", "prefix", "contains", "reference",
    ]);
    expect(rankInventoryItem(items[4], "inversor huawey")).toBeGreaterThan(30);
  });
});
