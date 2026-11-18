import { describe, expect, it } from "vitest";
import { sanitizeSvg } from "./sanitizeSvg";

describe("sanitização do SVG do unifilar", () => {
  it("preserva os elementos do motor e remove elementos, atributos e URLs ativos", () => {
    const unsafe = `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80" onload="alert(0)"><text x="4" y="14" font-size="10" fill="#1A2028">Seguro</text><line x1="0" y1="20" x2="80" y2="20" stroke="#1A2028"/><path d="M0 0h10" fill="none" stroke="#1A2028"/><rect width="10" height="10" onerror="alert(2)"/><circle cx="5" cy="5" r="2"/><ellipse cx="5" cy="5" rx="3" ry="2"/></svg>`;
    const safe = sanitizeSvg(unsafe);

    expect(safe).toContain("Seguro");
    expect(safe).toMatch(/<line\b|<path\b|<rect\b|<circle\b|<ellipse\b/i);
    expect(safe).not.toMatch(/<script|foreignObject|onload|onerror|javascript:/i);
  });

  it("remove image externa, style com import, object, iframe, a data e referências externas", () => {
    const unsafe = `<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/payload.svg"/><style>@import url(https://example.test/payload.css);.x{fill:url(data:image/svg+xml,x)}</style><object data="https://example.test/payload.svg"/><iframe src="https://example.test/payload.html"/><a href="data:text/html,%3Cscript%3Ealert(1)%3C/script%3E">Ligação perigosa</a><rect width="10" height="10" fill="url(https://example.test/fill)" stroke="url(#local)"/></svg>`;
    const safe = sanitizeSvg(unsafe);

    const parsed = new DOMParser().parseFromString(safe, "image/svg+xml");
    const activeElements = [parsed.documentElement, ...Array.from(parsed.documentElement.querySelectorAll("*"))];
    const activeAttributes = activeElements.flatMap((element) => Array.from(element.attributes)
      .filter((attribute) => attribute.name.toLowerCase() !== "xmlns")
      .map((attribute) => attribute.value));

    expect(parsed.documentElement.getAttribute("xmlns")).toBe("http://www.w3.org/2000/svg");
    expect(activeElements.some((element) => /^(image|style|object|iframe|a)$/i.test(element.localName))).toBe(false);
    expect(activeAttributes.some((value) => /https?:|data:|javascript:|url\(\s*https?:/i.test(value))).toBe(false);
    const rect = parsed.querySelector("rect");
    expect(rect).not.toBeNull();
    expect(rect?.getAttribute("stroke")).toBe("url(#local)");
    expect(rect?.hasAttribute("fill")).toBe(false);
  });

  it("mantém referências locais e remove atributos fora da allowlist", () => {
    const markup = `<svg xmlns="http://www.w3.org/2000/svg"><rect id="box" width="10" height="10" fill="url(#local)" stroke="#000" style="fill:red" data-test="x"/><text x="1" y="2" text-anchor="middle">Legenda</text></svg>`;
    const safe = sanitizeSvg(markup);

    expect(safe).toContain('fill="url(#local)"');
    expect(safe).not.toMatch(/style=|data-test=/i);
    expect(safe).toContain("Legenda");
  });

  it("devolve um SVG vazio seguro quando a entrada não é SVG", () => {
    const safe = sanitizeSvg(`<div><img src="x" onerror="alert(1)"></div>`);
    expect(safe).toMatch(/^<svg\b/i);
    expect(safe).not.toMatch(/<script|onerror|foreignObject|image/i);
  });
});
