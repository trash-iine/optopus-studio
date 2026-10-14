import type { RunSummary, ViewSpec } from "../generated/server-event";
import type { Mode } from "../theme";
import { Convergence } from "../views/Convergence";
import { ViewCard } from "../views/View";
import { Search } from "./Search";

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
              {summary.problem} · {summary.worker} worker
            </span>
          </h3>
          <Convergence summary={summary} mode={mode} />
        </section>
      )}
      <Search summary={summary} />
    </>
  );
}
