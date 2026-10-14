import type { RunSummary } from "../generated/server-event";
import { heuristicParts } from "../heuristic";

/** How a solve searched: each heuristic with its arguments, stop condition and nested ones. */
export function Search({ summary }: { summary: RunSummary }) {
  const { heuristics } = summary;
  if (heuristics.length === 0) return null;
  const runs = summary.runs.filter((r) => r.variant === 0).length;
  const facts = [
    `${summary.worker} worker`,
    summary.seed != null ? `seed ${summary.seed}` : "unseeded",
    runs > 0 ? `${runs} run${runs === 1 ? "" : "s"}${heuristics.length > 1 ? " each" : ""}` : null,
  ].filter(Boolean);
  return (
    <section className="card search">
      <h3>
        {heuristics.length > 1 ? "Heuristics" : "Heuristic"} <span className="sub">{facts.join(" · ")}</span>
      </h3>
      {heuristics.map((v) => (
        <div key={v.label} className="variant">
          {heuristics.length > 1 && <div className="variant-label">{v.label}</div>}
          <Heuristic spec={v.heuristic} />
        </div>
      ))}
    </section>
  );
}

function Heuristic({ spec }: { spec: Record<string, unknown> }) {
  const { kind, summary, params, stop, children } = heuristicParts(spec);
  return (
    <div className="heuristic">
      <div className="heuristic-head">
        <code>{kind}</code>
        {stop && <span className="muted">stops at {stop}</span>}
      </div>
      {summary && <p className="heuristic-summary">{summary}</p>}
      {params.length > 0 && (
        <dl>
          {params.map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {children.map((child) => (
        <div key={child.role} className="heuristic-child">
          <div className="heuristic-role">{child.role}</div>
          <Heuristic spec={child.spec} />
        </div>
      ))}
    </div>
  );
}
