import type { RunFinished, RunSummary, ViewSpec } from "../generated/server-event";
import { compact, type Mode } from "../theme";
import { Convergence } from "../views/Convergence";
import { ViewCard } from "../views/View";
import { Search } from "./Search";

/** What a BranchAndBound run proved, in a few words; null for every other heuristic. */
export function proof(run: RunFinished | null | undefined): string | null {
  if (run?.proven_optimal == null) return null;
  if (run.proven_optimal) return "proven optimal";
  if (run.dual_bound == null) return "not proven optimal";
  const best = run.best_objective;
  const gap = best !== 0 ? `, gap ${((Math.abs(run.dual_bound - best) / Math.abs(best)) * 100).toFixed(1)}%` : "";
  return `not proven optimal: bound ${compact(run.dual_bound)}${gap}`;
}

/** What a solve gave: its error, the model's views, the convergence and how it searched. */
export function SolveResult({
  summary,
  view,
  viewError,
  mode,
}: {
  summary: RunSummary;
  view: ViewSpec | null;
  viewError: string | null;
  mode: Mode;
}) {
  const proved = proof(summary.best_run != null ? summary.runs[summary.best_run] : null);
  return (
    <>
      {summary.error && (
        <div className="banner critical">
          <strong>The solve failed at {summary.error.stage}:</strong> {summary.error.message}
          {summary.error.traceback && (
            <details>
              <summary>traceback</summary>
              <pre>{summary.error.traceback}</pre>
            </details>
          )}
        </div>
      )}
      {viewError && (
        <div className="banner warning">
          <strong>view.py failed</strong>
          <pre>{viewError}</pre>
        </div>
      )}
      {view?.views.map((v, i) => <ViewCard key={`${summary.rev}-${i}`} view={v} mode={mode} />)}
      {summary.runs.length > 0 && (
        <section className="card">
          <h3>
            Convergence{" "}
            <span className="sub">
              {summary.problem} · {summary.worker} worker{proved && ` · best run ${proved}`}
            </span>
          </h3>
          <Convergence summary={summary} mode={mode} />
        </section>
      )}
      <Search summary={summary} />
    </>
  );
}
