import type { Enclosure, JsonValue } from "../engine";

interface Plate { width: number; height: number; }

function finitePositive(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function record(value: JsonValue): Record<string, JsonValue> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, JsonValue> : null;
}

function numberValue(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function platesFromRow(value: JsonValue): Plate[] {
  if (Array.isArray(value)) {
    const width = numberValue(value[0]);
    const height = numberValue(value[1]);
    return width && height ? [{ width, height }] : [];
  }
  const item = record(value);
  if (!item || !Array.isArray(item.items)) return [];
  return item.items.flatMap((entry) => platesFromRow(entry));
}

function rowHeight(value: JsonValue): number {
  const item = record(value);
  const declared = item ? numberValue(item.h) : null;
  if (declared && declared > 0) return declared;
  return Math.max(40, ...platesFromRow(value).map((plate) => plate.height));
}

export interface BoardSpaceSvgProps {
  enclosure: Enclosure;
  freeCableZoneMm: number;
  maxRadiusMm: number;
}

/** React-native equivalent of the original boardSVG geometry. */
export function BoardSpaceSvg({ enclosure, freeCableZoneMm, maxRadiusMm }: BoardSpaceSvgProps) {
  const enclosureWidth = finitePositive(enclosure.widthMm, 1);
  const enclosureHeight = finitePositive(enclosure.heightMm, 1);
  const scale = Math.min(240 / enclosureWidth, 300 / enclosureHeight);
  const width = enclosureWidth * scale;
  const height = enclosureHeight * scale;
  const canvasWidth = width + 60;
  const canvasHeight = height + 26;
  let y = 10 + 40 * scale;
  const rows = Array.isArray(enclosure.rows) ? enclosure.rows : [];
  const safeZone = Math.min(enclosureHeight, Math.max(0, finitePositive(freeCableZoneMm, 0)));
  const radius = Math.min(
    Math.max(0, finitePositive(maxRadiusMm, 0)) * scale,
    Math.max(0, width / 2 - 12),
    Math.max(0, safeZone * scale - 10),
  );
  const zoneTop = 10 + height - (safeZone + 40) * scale;
  const moduleRows = Math.max(0, Math.floor(enclosure.mountingRows || 0));
  const stroke = "var(--text)";
  const mutedStroke = "var(--text-muted)";

  return (
    <svg
      className="cable-board-space"
      data-testid="board-space-svg"
      width="100%"
      height={canvasHeight}
      viewBox={`0 0 ${canvasWidth} ${canvasHeight}`}
      role="img"
      aria-label={`Esboço da envolvente ${enclosure.ref}`}
      preserveAspectRatio="xMinYMin meet"
    >
      <rect x="10" y="10" width={width} height={height} rx="4" fill="var(--document-surface)" stroke={stroke} strokeWidth="1.5" />
      {rows.map((row, rowIndex) => {
        const rowItems = platesFromRow(row);
        const rowY = y;
        const nextY = y + rowHeight(row) * scale;
        let x = 10 + 50 * scale;
        y = nextY;
        return (
          <g key={`plate-row-${rowIndex}`} aria-label={`Fila de platinas ${rowIndex + 1}`}>
            {rowItems.map((plate, itemIndex) => {
              const plateX = x;
              x += (plate.width + 20) * scale;
              return <rect key={`plate-${rowIndex}-${itemIndex}`} x={plateX} y={rowY} width={plate.width * scale} height={Math.max(8, plate.height - 20) * scale} fill="var(--surface-2)" stroke={mutedStroke} />;
            })}
          </g>
        );
      })}
      {Array.from({ length: moduleRows }).map((_, index) => {
        const moduleY = y + 40 * scale;
        y += 150 * scale;
        return <rect key={`module-row-${index}`} x={10 + 50 * scale} y={moduleY} width={Math.max(1, enclosureWidth - 100) * scale} height={70 * scale} fill="var(--brand-soft)" stroke="var(--brand)" />;
      })}
      {safeZone > 0 && (
        <>
          <rect x="16" y={zoneTop} width={Math.max(1, width - 12)} height={safeZone * scale} fill="none" stroke="var(--accent)" strokeDasharray="4 3" />
          {radius > 0 && (
            <path d={`M${30} ${10 + height} L30 ${zoneTop + radius + 4} A${radius} ${radius} 0 0 1 ${30 + radius} ${zoneTop + 4}`} fill="none" stroke="var(--brand)" strokeWidth="2.5" />
          )}
          <text x={10 + width / 2} y={zoneTop + safeZone * scale + 12} fontSize="9" textAnchor="middle" fill="var(--accent)">zona de cabos {Math.round(safeZone)} mm</text>
        </>
      )}
      <text x={10 + width / 2} y={10 + height + 16} fontSize="10" textAnchor="middle" fill={mutedStroke}>{Math.round(enclosureWidth)} mm</text>
      <text x={10 + width + 6} y={10 + height / 2} fontSize="10" fill={mutedStroke}>{Math.round(enclosureHeight)} mm</text>
    </svg>
  );
}
