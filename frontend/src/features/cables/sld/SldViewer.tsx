import { useCallback, useMemo, useRef, useState } from "react";
import { sanitizeSvg } from "./sanitizeSvg";

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.1;

export function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(value * 100) / 100));
}

function svgWidth(markup: string): number {
  const viewBox = /viewBox\s*=\s*["']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)/i.exec(markup)?.[1];
  const width = /(?:^|\s)width\s*=\s*["']\s*([\d.]+)/i.exec(markup)?.[1];
  const value = Number(viewBox ?? width);
  return Number.isFinite(value) && value > 0 ? value : 1;
}

function svgHeight(markup: string): number {
  const viewBox = /viewBox\s*=\s*["']\s*[-\d.]+\s+[-\d.]+\s+[\d.]+\s+([\d.]+)/i.exec(markup)?.[1];
  const height = /(?:^|\s)height\s*=\s*["']\s*([\d.]+)/i.exec(markup)?.[1];
  const value = Number(viewBox ?? height);
  return Number.isFinite(value) && value > 0 ? value : 1;
}

interface DragEventLike {
  button?: number;
  clientX?: number;
  clientY?: number;
}

function coordinate(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isFinite(value) ? value : fallback;
}

export interface SldViewerProps {
  rawSvg: string;
}

export function SldViewer({ rawSvg }: SldViewerProps) {
  const safeSvg = useMemo(() => sanitizeSvg(rawSvg), [rawSvg]);
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragging = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });

  const resetPosition = useCallback((nextZoom: number) => {
    setZoom(clampZoom(nextZoom));
    setPan({ x: 0, y: 0 });
  }, []);

  const fitWidth = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const available = viewport.clientWidth - 32;
    const width = svgWidth(safeSvg);
    resetPosition(available > 0 ? available / width : 1);
  }, [resetPosition, safeSvg]);

  const beginDragging = (event: DragEventLike) => {
    if (event.button !== undefined && event.button !== 0) return;
    dragging.current = {
      x: coordinate(event.clientX, 0),
      y: coordinate(event.clientY, 0),
      panX: pan.x,
      panY: pan.y,
    };
  };

  const moveDragging = (event: DragEventLike) => {
    const start = dragging.current;
    if (!start) return;
    const x = coordinate(event.clientX, start.x);
    const y = coordinate(event.clientY, start.y);
    setPan({ x: start.panX + x - start.x, y: start.panY + y - start.y });
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    beginDragging(event);
    if (dragging.current && Number.isInteger(event.pointerId)) event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => moveDragging(event);
  const onMouseDown = (event: React.MouseEvent<HTMLDivElement>) => beginDragging(event);
  const onMouseMove = (event: React.MouseEvent<HTMLDivElement>) => moveDragging(event);

  const stopDragging = (event?: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = null;
    if (event && Number.isInteger(event.pointerId)) event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const width = svgWidth(safeSvg);
  const height = svgHeight(safeSvg);
  return (
    <div className="cable-sld-viewer">
      <div className="cable-sld-viewer__controls" role="toolbar" aria-label="Controlos do esquema">
        <button type="button" className="btn btn--sm" aria-label="Reduzir zoom" onClick={() => setZoom((value) => clampZoom(value - ZOOM_STEP))}>−</button>
        <output className="cable-sld-viewer__zoom" aria-label="Zoom" data-testid="sld-zoom">{Math.round(zoom * 100)}%</output>
        <button type="button" className="btn btn--sm" aria-label="Aumentar zoom" onClick={() => setZoom((value) => clampZoom(value + ZOOM_STEP))}>+</button>
        <button type="button" className="btn btn--sm" onClick={fitWidth}>Ajustar à largura</button>
        <button type="button" className="btn btn--sm" aria-label="100%" onClick={() => resetPosition(1)}>100%</button>
        <span className="muted small">Arraste para mover · role para ampliar</span>
      </div>
      <div
        ref={viewportRef}
        className="cable-sld-viewer__viewport"
        data-testid="sld-viewport"
        data-zoom={String(zoom)}
        data-pan={`${pan.x},${pan.y}`}
        role="application"
        aria-label="Área do esquema unifilar"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={stopDragging}
        onPointerCancel={stopDragging}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={() => stopDragging()}
        onPointerLeave={() => { if (dragging.current) dragging.current = null; }}
        onMouseLeave={() => { if (dragging.current) dragging.current = null; }}
      >
        <div
          className="cable-sld-viewer__canvas"
          data-testid="sld-svg"
          style={{
            width: `${width}px`,
            minHeight: `${height}px`,
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          }}
          dangerouslySetInnerHTML={{ __html: safeSvg }}
        />
      </div>
    </div>
  );
}
