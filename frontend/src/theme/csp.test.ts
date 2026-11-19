import { describe, expect, it } from "vitest";
import csp from "../../docker/security-csp.conf?raw";
import workerCsp from "../../docker/security-csp-worker.conf?raw";

function directive(source: string, name: string): string {
  const policy = /add_header Content-Security-Policy "([^"]+)"/.exec(source)?.[1] ?? "";
  return policy.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name} `)) ?? "";
}

describe("CSP do nginx", () => {
  it("os tiles do mapa (OpenStreetMap, carregados como <img> pelo Leaflet) estão em img-src e não em connect-src", () => {
    expect(directive(csp, "img-src")).toContain("https://tile.openstreetmap.org");
    expect(directive(csp, "connect-src")).not.toContain("openstreetmap");
  });

  it("scripts só da própria origem, sem unsafe-*; worker da própria origem", () => {
    expect(directive(csp, "script-src")).toBe("script-src 'self'");
    expect(directive(csp, "worker-src")).toBe("worker-src 'self'");
    expect(directive(csp, "frame-ancestors")).toBe("frame-ancestors 'none'");
  });

  it("o worker do motor não tem rede", () => {
    expect(directive(workerCsp, "connect-src")).toBe("connect-src 'none'");
  });
});
