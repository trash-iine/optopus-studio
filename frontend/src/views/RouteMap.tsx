// Tours and vehicle routes on the plane, drawn in SVG.
import { useMemo } from "react";
import type { RouteMapView } from "../generated/server-event";
import { CHROME, type Mode, slotColor } from "../theme";
import { Legend } from "./Legend";

const SIZE = 600;
const PAD = 28;
const LABEL_LIMIT = 40;

export function RouteMap({ view, mode }: { view: RouteMapView; mode: Mode }) {
  const c = CHROME[mode];
  const { project, byId } = useMemo(() => {
    const xs = view.points.map((p) => p.x);
    const ys = view.points.map((p) => p.y);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const scale = (SIZE - 2 * PAD) / Math.max(maxX - minX, maxY - minY, 1e-9);
    // y grows upward in the data and downward on screen.
    const project = (x: number, y: number): [number, number] => [
      PAD + (x - minX) * scale,
      SIZE - PAD - (y - minY) * scale,
    ];
    return { project, byId: new Map(view.points.map((p) => [String(p.id), p])) };
  }, [view.points]);

  const routes = view.routes.map((route, i) => {
    const coords = route.path
      .map((id) => byId.get(String(id)))
      .filter((p) => p !== undefined)
      .map((p) => project(p.x, p.y));
    if (view.closed && coords.length > 1) coords.push(coords[0]);
    return { label: route.label ?? `route ${i + 1}`, color: slotColor(mode, i), coords };
  });

  return (
    <div>
      <Legend entries={routes.map((r) => [r.label, r.color])} line />
      <svg className="route-map" viewBox={`0 0 ${SIZE} ${SIZE}`} role="img">
        {routes.map((r) => (
          <polyline
            key={r.label}
            points={r.coords.map(([x, y]) => `${x},${y}`).join(" ")}
            fill="none"
            stroke={r.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          >
            <title>{r.label}</title>
          </polyline>
        ))}
        {view.points.map((p) => {
          const [x, y] = project(p.x, p.y);
          const name = p.label ?? String(p.id);
          return (
            <g key={String(p.id)} className="map-point">
              <title>{`${name} (${p.x}, ${p.y})`}</title>
              {/* A larger transparent target than the mark makes hovering easy. */}
              <circle cx={x} cy={y} r={10} fill="transparent" />
              {p.kind === "depot" ? (
                <rect x={x - 6} y={y - 6} width={12} height={12} rx={2} fill={c.ink} stroke={c.surface} strokeWidth={2} />
              ) : (
                <circle cx={x} cy={y} r={4.5} fill={c.ink2} stroke={c.surface} strokeWidth={2} />
              )}
              {view.points.length <= LABEL_LIMIT && (
                <text x={x + 8} y={y - 8} fontSize={11} fill={c.muted}>
                  {name}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
