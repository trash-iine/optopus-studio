import { useState } from "react";
import type { RunSummary } from "../generated/server-event";
import type { StudioState } from "../studio";
import { compact, type Mode } from "../theme";
import { Convergence } from "../views/Convergence";
import { ViewCard } from "../views/View";

type Tab = "result" | "model" | "runs";
const FILE_ORDER = ["model.py", "view.py", "instance.json", "solve.json"];

interface Props {
  state: StudioState;
  mode: Mode;
  onSelect: (rev: number) => void;
}

export function Canvas({ state, mode, onSelect }: Props) {
  const [tab, setTab] = useState<Tab>("result");
  const latest = state.revisions.at(-1);
  return (
    <main className="canvas">
      <div className="canvas-bar">
        <div className="tabs" role="tablist">
          {(["result", "model", "runs"] as const).map((t) => (
            <button key={t} role="tab" className={t === tab ? "on" : ""} onClick={() => setTab(t)}>
              {{ result: "Result", model: "Model", runs: "Runs" }[t]}
            </button>
          ))}
        </div>
        {state.revisions.length > 0 && (
          <label className="rev-select">
            Revision
            <select value={state.rev ?? ""} onChange={(e) => onSelect(Number(e.target.value))}>
              {[...state.revisions].reverse().map((r) => (
                <option key={r} value={r}>
                  {r}
                  {r === latest ? " (latest)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <div className="canvas-body">
        {tab === "result" && <Result state={state} mode={mode} />}
        {tab === "model" && <Files files={state.files} />}
        {tab === "runs" && state.summary && <Runs summary={state.summary} />}
      </div>
    </main>
  );
}

function Result({ state, mode }: { state: StudioState; mode: Mode }) {
  const { summary, view, viewError, solving } = state;
  if (!summary) {
    return (
      <div className="placeholder">
        {state.busy ? "Building the model…" : "No result yet. Ask in the chat and it shows up here."}
      </div>
    );
  }
  return (
    <div className="result">
      {solving && solving.rev === summary.rev && (
        <div className="status">
          Solving revision {solving.rev}: {summary.runs.length} / {solving.runs} runs
        </div>
      )}
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
            Convergence <span className="sub">{summary.problem}</span>
          </h3>
          <Convergence summary={summary} mode={mode} />
        </section>
      )}
    </div>
  );
}

function Files({ files }: { files: Record<string, string> }) {
  const names = FILE_ORDER.filter((n) => n in files);
  const [open, setOpen] = useState(names[0] ?? "model.py");
  if (names.length === 0) return <div className="placeholder">No files yet.</div>;
  return (
    <div className="files">
      <div className="file-tabs">
        {names.map((n) => (
          <button key={n} className={n === open ? "on" : ""} onClick={() => setOpen(n)}>
            {n}
          </button>
        ))}
      </div>
      <pre className="code">{files[open] ?? ""}</pre>
    </div>
  );
}

function Runs({ summary }: { summary: RunSummary }) {
  return (
    <div className="table-wrap card">
      <table>
        <thead>
          <tr>
            <th>run</th>
            <th>best</th>
            <th>initial</th>
            <th>iterations</th>
            <th>best at</th>
            <th>time to best (s)</th>
            <th>total (s)</th>
            <th>seed</th>
          </tr>
        </thead>
        <tbody>
          {summary.runs.map((r) => (
            <tr key={r.run} className={r.run === summary.best_run ? "best" : undefined}>
              <td className="num">{r.run}</td>
              <td className="num">{compact(r.best_objective)}</td>
              <td className="num">{compact(r.initial_objective)}</td>
              <td className="num">{r.iterations.toLocaleString("en-US")}</td>
              <td className="num">{r.best_iteration.toLocaleString("en-US")}</td>
              <td className="num">{r.time_to_best_secs.toFixed(4)}</td>
              <td className="num">{r.total_time_secs.toFixed(4)}</td>
              <td className="num">{r.seed ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
