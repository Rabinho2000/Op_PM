// Telemóvel (D-079): as tabelas `.table` passam a cartões em ecrãs estreitos
// só com CSS. Para cada célula mostrar o nome da coluna, copiamos o texto
// do <th> correspondente para `data-label` no <td>. Feito uma vez no
// Layout (com MutationObserver), sem tocar em cada página.

export function applyTableCardLabels(root: ParentNode): void {
  root.querySelectorAll<HTMLTableElement>("table.table").forEach((table) => {
    const headers = Array.from(table.querySelectorAll<HTMLTableCellElement>("thead th")).map((th) =>
      (th.textContent ?? "").trim(),
    );
    if (headers.length === 0) return;
    table.querySelectorAll<HTMLTableRowElement>("tbody tr").forEach((row) => {
      let col = 0;
      Array.from(row.cells).forEach((cell) => {
        const label = headers[col] ?? "";
        if (cell.getAttribute("data-label") !== label) cell.setAttribute("data-label", label);
        col += cell.colSpan || 1;
      });
    });
  });
}

export function observeTableCardLabels(root: HTMLElement): () => void {
  applyTableCardLabels(root);
  if (typeof MutationObserver === "undefined") return () => undefined;
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      applyTableCardLabels(root);
    });
  });
  observer.observe(root, { childList: true, subtree: true, characterData: true });
  return () => observer.disconnect();
}
