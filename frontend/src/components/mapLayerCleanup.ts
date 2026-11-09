interface MapLayerCleanupTarget {
  off: () => unknown;
  remove: () => unknown;
  eachLayer?: (callback: (child: MapLayerCleanupTarget) => void) => unknown;
  clearLayers?: () => unknown;
}

export function removeMapLayers<T extends MapLayerCleanupTarget>(layers: readonly T[]): void {
  for (const layer of layers) {
    layer.eachLayer?.((child) => child.off());
    layer.clearLayers?.();
    layer.off();
    layer.remove();
  }
}
