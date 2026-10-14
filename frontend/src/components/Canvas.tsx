import { useState } from "react";
import type { RunSummary } from "../generated/server-event";
import type { StudioState } from "../studio";
import { compact, type Mode } from "../theme";
import { runLabel, variantStats } from "../views/Convergence";
import { Compare } from "./Compare";
import { Search } from "./Search";
import { SolveResult } from "./SolveResult";

type Tab = "result" | "model" | "runs" | "compare";

/** What the "Port to Rust" button asks the agent. */
export const PORT_REQUEST =
  "Port this model to Rust, verify it against the Python model, and switch to the Rust worker if it passes.";
const TABS: Record<Tab, string> = { result: "Result", model: "Model", runs: "Runs", compare: "Compare" };
const FILE_ORDER = ["model.py", "view.py", "instance.json", "solve.json", "app.json", "rust/main.rs"];

interface Props {
  project: string | null;
  state: StudioState;
  mode: Mode;
  onSelect: (rev: number) => void;
  onAsk: (text: string) => void;
}

/** Downloads a revision as an app package, or returns why it cannot be packaged. */
export async function downloadPackage(project: string, rev: number): Promise<string | null> {
  const response = await fetch(`/api/projects/${project}/revisions/${rev}/package`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    return body.detail ?? `packaging failed: ${response.status}`;
  }
  const name = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1];
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = name ?? `optopus-app-${project}-r${rev}.zip`;
  link.click();
  URL.revokeObjectURL(link.href);
  return null;
}

export function Canvas({ project, state, mode, onSelect, onAsk }: Props) {
  const [tab, setTab] = useState<Tab>("result");
  const [packageError, setPackageError] = useState<string | null>(null);
  const latest = state.revisions.at(-1);
  const packageRevision = async () => {
    if (!project || state.rev == null) return;
    setPackageError(await downloadPackage(project, state.rev));
  };
  return (
    <main className="canvas">
      <div className="canvas-bar">
        <div className="tabs" role="tablist">
          {(Object.keys(TABS) as Tab[]).map((t) => (
            <button key={t} role="tab" className={t === tab ? "on" : ""} onClick={() => setTab(t)}>
              {TABS[t]}
            </button>
          ))}
        </div>
        {state.revisions.length > 0 && (
          <div className="rev-actions">
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
            <button
              className="secondary"
              title="Download this revision as an app that runs without the agent (needs app.json)"
              disabled={state.busy}
              onClick={packageRevision}
            >
              Package
            </button>
          </div>
        )}
      </div>
      <div className="canvas-body">
        {packageError && (
          <div className="banner warning package-error">
            <strong>Cannot package revision {state.rev}</strong>
            <pre>{packageError}</pre>
            <button className="secondary" onClick={() => setPackageError(null)}>
              Dismiss
            </button>
          </div>
        )}
        {tab === "result" && <Result state={state} mode={mode} onAsk={onAsk} />}
        {tab === "model" && <Files files={state.files} />}
        {tab === "runs" && state.summary && <Runs summary={state.summary} />}
        {tab === "compare" && project && (
          <Compare
            key={`${state.rev}-${state.revisions.length}`}
            project={project}
            revisions={state.revisions}
            current={state.rev}
            mode={mode}
          />
        )}
      </div>
    </main>
  );
}

function Result({
  state,
  mode,
  onAsk,
}: {
  state: StudioState;
  mode: Mode;
  onAsk: (text: string) => void;
}) {
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
          Solving revision {solving.rev} with the {summary.worker} worker: {summary.runs.length} /{" "}
          {solving.runs} runs
          {summary.live && summary.live.points.length > 0 && (
            <>, best so far {compact((summary.live.points.at(-1) as unknown as number[])[1])}</>
          )}
        </div>
      )}
      {summary.native === false && !solving && !state.busy && (
        <div className="banner info">
          This problem is written in Python, so every move runs through Python.
          <button className="secondary" onClick={() => onAsk(PORT_REQUEST)}>
            Port to Rust
          </button>
        </div>
      )}
      <SolveResult summary={summary} view={view} viewError={viewError} mode={mode} />
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
  const stats = variantStats(summary);
  const several = summary.variants.length > 1;
  return (
    <div className="result">
      <Search summary={summary} />
      {several && (
        <section className="card table-wrap">
          <h3>
            Heuristics <span className="sub">same seeds, so each starts from the same solutions</span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>heuristic</th>
                <th className="num">runs</th>
                <th className="num">best</th>
                <th className="num">mean</th>
                <th className="num">worst</th>
                <th className="num">mean time to best (s)</th>
                <th className="num">mean total (s)</th>
              </tr>
            </thead>
            <tbody>
              {stats.map((v) => (
                <tr key={v.label}>
                  <td>{v.label}</td>
                  <td className="num">{v.runs}</td>
                  <td className="num">{compact(v.best)}</td>
                  <td className="num">{compact(v.mean)}</td>
                  <td className="num">{compact(v.worst)}</td>
                  <td className="num">{v.meanTimeToBest.toFixed(4)}</td>
                  <td className="num">{v.meanTotalTime.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <section className="card table-wrap">
        <h3>Runs</h3>
        <table>
          <thead>
            <tr>
              <th>run</th>
              <th className="num">best</th>
              <th className="num">initial</th>
              <th className="num">iterations</th>
              <th className="num">best at</th>
              <th className="num">time to best (s)</th>
              <th className="num">total (s)</th>
              <th className="num">seed</th>
            </tr>
          </thead>
          <tbody>
            {summary.runs.map((r) => (
              <tr key={r.run} className={r.run === summary.best_run ? "best" : undefined}>
                <td>{runLabel(summary, r)}</td>
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
      </section>
    </div>
  );
}
