import { describe, expect, it, vi } from "vitest";
import { removeMapLayers } from "./mapLayerCleanup";

describe("cleanup de layers Leaflet", () => {
  it("desregista marcadores, esvazia clusters e remove os layers", () => {
    const firstMarker = { off: vi.fn(), remove: vi.fn() };
    const secondMarker = { off: vi.fn(), remove: vi.fn() };
    const cluster = {
      eachLayer: (callback: (layer: typeof firstMarker) => void) => {
        callback(firstMarker);
        callback(secondMarker);
      },
      clearLayers: vi.fn(),
      off: vi.fn(),
      remove: vi.fn(),
    };

    removeMapLayers([cluster]);

    expect(firstMarker.off).toHaveBeenCalledOnce();
    expect(secondMarker.off).toHaveBeenCalledOnce();
    expect(cluster.clearLayers).toHaveBeenCalledOnce();
    expect(cluster.off).toHaveBeenCalledOnce();
    expect(cluster.remove).toHaveBeenCalledOnce();
    expect(cluster.clearLayers).toHaveBeenCalledBefore(cluster.remove);
  });
});
