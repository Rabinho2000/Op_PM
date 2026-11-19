import { describe, expect, it } from "vitest";
import csp from "../../docker/security-csp.conf?raw";
import frameCsp from "../../docker/security-csp-frame.conf?raw";

function directive(source: string, name: string): string {
  const policy = /add_header Content-Security-Policy "([^"]+)"/.exec(source)?.[1] ?? "";
  return policy.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name} `)) ?? "";
}

describe("CSP do nginx", () => {
  it("os tiles do mapa (OpenStreetMap, carregados como <img> pelo Leaflet) estão em img-src e não em connect-src", () => {
    expect(directive(csp, "img-src")).toContain("https://tile.openstreetmap.org");
    expect(directive(csp, "connect-src")).not.toContain("openstreetmap");
  });

  it("scripts só da própria origem, sem unsafe-*", () => {
    expect(directive(csp, "script-src")).toBe("script-src 'self'");
    expect(directive(csp, "frame-ancestors")).toBe("frame-ancestors 'none'");
  });

  it("a página do motor (iframe sandbox) não tem rede, só aceita ser embebida por nós e tem unsafe-eval só ali", () => {
    expect(directive(frameCsp, "default-src")).toBe("default-src 'none'");
    expect(directive(frameCsp, "connect-src")).toBe("connect-src 'none'");
    expect(directive(frameCsp, "frame-ancestors")).toBe("frame-ancestors 'self'");
    expect(directive(frameCsp, "script-src")).toContain("'unsafe-eval'");
    expect(directive(frameCsp, "img-src")).toBe("img-src data: blob:");
    expect(directive(csp, "script-src")).not.toContain("unsafe");
    expect(frameCsp).toContain('X-Frame-Options "SAMEORIGIN"');
  });
});
