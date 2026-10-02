import { describe, expect, it } from "vitest";
import { applyTableCardLabels, observeTableCardLabels } from "./tableCardLabels";

function makeTable(body: string): HTMLDivElement {
  const root = document.createElement("div");
  root.innerHTML = `<table class="table"><thead><tr><th>Projeto</th><th>PM</th><th>Estado</th></tr></thead><tbody>${body}</tbody></table>`;
  document.body.appendChild(root);
  return root;
}

describe("tableCardLabels (D-079)", () => {
  it("copia o nome da coluna para data-label de cada célula", () => {
    const root = makeTable("<tr><td>A</td><td>B</td><td>C</td></tr>");
    applyTableCardLabels(root);
    const labels = Array.from(root.querySelectorAll("td")).map((td) => td.getAttribute("data-label"));
    expect(labels).toEqual(["Projeto", "PM", "Estado"]);
  });

  it("respeita colspan", () => {
    const root = makeTable('<tr><td colspan="2">A</td><td>C</td></tr>');
    applyTableCardLabels(root);
    const labels = Array.from(root.querySelectorAll("td")).map((td) => td.getAttribute("data-label"));
    expect(labels).toEqual(["Projeto", "Estado"]);
  });

  it("ignora tabelas sem a classe .table", () => {
    const root = document.createElement("div");
    root.innerHTML = "<table><thead><tr><th>X</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>";
    applyTableCardLabels(root);
    expect(root.querySelector("td")?.hasAttribute("data-label")).toBe(false);
  });

  it("rotula linhas acrescentadas depois (render assíncrono)", async () => {
    const root = makeTable("");
    const stop = observeTableCardLabels(root);
    const row = document.createElement("tr");
    row.innerHTML = "<td>A</td><td>B</td><td>C</td>";
    root.querySelector("tbody")!.appendChild(row);
    await new Promise((r) => setTimeout(r, 0));
    expect(row.cells[1].getAttribute("data-label")).toBe("PM");
    stop();
  });
});
