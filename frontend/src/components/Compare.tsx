// Two revisions side by side: the best objective, the headline numbers, how each converged, and
// what changed in the files between them.
import { useEffect, useMemo, useState } from "react";
import { diffLines } from "../diff";
import type { RevisionDetail } from "../generated/revision";
import type { KpiView } from "../generated/server-event";
import { compact, type Mode, slotColor } from "../theme";
import { Legend } from "../views/Legend";
import { type Axis, AxisToggle, ConvergenceChart, curve } from "../views/Convergence";

const FILES = ["instance.json", "model.py", "view.py", "solve.json"];

async function fetchRevision(project: string, rev: number): Promise<RevisionDetail> {
  const response = await fetch(`/api/projects/${project}/revisions/${rev}`);
  if (!response.ok) throw new Error(`revision ${rev}: ${response.status}`);
  return response.json();
}

function bestRun(detail: RevisionDetail) {
  const s = detail.summary;
  return s && s.best_run != null ? s.runs[s.best_run] : null;
}

/** Whether going from `before` to `after` is better, worse or the same, in words and a sign. */
export function change(before: number, after: number, higherIsBetter: boolean | null) {
  const delta = after - before;
  if (delta === 0 || higherIsBetter == null) return { delta, verdict: "same" as const };
  const better = higherIsBetter ? delta > 0 : delta < 0;
  return { delta, verdict: better ? ("better" as const) : ("worse" as const) };
}

export function kpiRows(a: RevisionDetail, b: RevisionDetail) {
  const items = (d: RevisionDetail) =>
    new Map(
      (d.view?.views ?? [])
        .filter((v): v is KpiView => v.type === "kpi")
        .flatMap((v) => v.items.map((i) => [i.label, i] as const)),
    );
  const [ia, ib] = [items(a), items(b)];
  const labels = [...new Set([...ib.keys(), ...ia.keys()])];
  return labels.map((label) => ({ label, a: ia.get(label), b: ib.get(label) }));
}

interface Props {
  project: string;
  revisions: number[];
  current: number | null;
  mode: Mode;
}

export function Compare({ project, revisions, current, mode }: Props) {
  const latest = revisions.at(-1) ?? null;
  const [revA, setRevA] = useState<number | null>(current ?? latest);
  const [revB, setRevB] = useState<number | null>(() => {
    const a = current ?? latest;
    const earlier = revisions.filter((r) => a != null && r < a);
    return earlier.at(-1) ?? null;
  });
  const [details, setDetails] = useState<Record<number, RevisionDetail>>({});
  const [error, setError] = useState<string | null>(null);
  const [by, setBy] = useState<Axis>("iteration");

  useEffect(() => {
    for (const rev of [revA, revB]) {
      if (rev == null || details[rev]) continue;
      fetchRevision(project, rev)
        .then((d) => setDetails((all) => ({ ...all, [rev]: d })))
        .catch((e: Error) => setError(e.message));
    }
  }, [project, revA, revB, details]);

  if (revisions.length < 2) {
    return <div className="placeholder">Comparing needs two revisions; solve again after a change.</div>;
  }
  const a = revA != null ? details[revA] : undefined;
  const b = revB != null ? details[revB] : undefined;
  const picker = (value: number | null, set: (r: number) => void) => (
    <select value={value ?? ""} onChange={(e) => set(Number(e.target.value))}>
      {[...revisions].reverse().map((r) => (
        <option key={r} value={r}>
          revision {r}
        </option>
      ))}
    </select>
  );

  return (
    <div className="result">
      <div className="compare-bar">
        {picker(revA, setRevA)}
        <span className="muted">compared with</span>
        {picker(revB, setRevB)}
      </div>
      {error && <div className="banner critical">{error}</div>}
      {a && b && <CompareBody a={a} b={b} by={by} setBy={setBy} mode={mode} />}
    </div>
  );
}

function CompareBody({
  a,
  b,
  by,
  setBy,
  mode,
}: {
  a: RevisionDetail;
  b: RevisionDetail;
  by: Axis;
  setBy: (a: Axis) => void;
  mode: Mode;
}) {
  const [bestA, bestB] = [bestRun(a), bestRun(b)];
  const higherIsBetter = a.summary?.higher_is_better ?? b.summary?.higher_is_better ?? null;
  const series = useMemo(
    () =>
      [
        { detail: a, run: bestA, color: slotColor(mode, 0) },
        { detail: b, run: bestB, color: slotColor(mode, 1) },
      ].flatMap(({ detail, run, color }) =>
        run ? [{ name: `revision ${detail.rev}`, color, data: curve(run, by) }] : [],
      ),
    [a, b, bestA, bestB, by, mode],
  );
  const changedFiles = FILES.filter((f) => a.files[f] !== b.files[f]);
  const rows = kpiRows(a, b);
  const sameProblem = a.summary?.problem === b.summary?.problem;

  return (
    <>
      <section className="card">
        <h3>Best objective</h3>
        {bestA && bestB ? (
          <Verdict before={bestB.best_objective} after={bestA.best_objective} higherIsBetter={higherIsBetter} revA={a.rev} revB={b.rev} />
        ) : (
          <p className="muted">One of the revisions has no result.</p>
        )}
        {!sameProblem && (
          <p className="muted">
            The problems differ ({b.summary?.problem} → {a.summary?.problem}); their objectives may
            not be on one scale.
          </p>
        )}
      </section>
      {rows.length > 0 && (
        <section className="card">
          <h3>Headline numbers</h3>
          <table>
            <thead>
              <tr>
                <th></th>
                <th className="num">revision {b.rev}</th>
                <th className="num">revision {a.rev}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <td>{row.label}</td>
                  <td className="num">{format(row.b?.value)} {row.b?.unit ?? ""}</td>
                  <td className="num">{format(row.a?.value)} {row.a?.unit ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {series.length > 0 && (
        <section className="card">
          <h3>Convergence of the best runs</h3>
          <div className="chart-controls">
            <Legend entries={series.map((s) => [s.name, s.color])} line />
            <AxisToggle by={by} onChange={setBy} />
          </div>
          <ConvergenceChart series={series} by={by} higherIsBetter={higherIsBetter} mode={mode} />
        </section>
      )}
      <section className="card">
        <h3>
          Changed files <span className="sub">revision {b.rev} → {a.rev}</span>
        </h3>
        {changedFiles.length === 0 && <p className="muted">The files are the same; only the runs differ.</p>}
        {changedFiles.map((f) => (
          <FileDiff key={f} name={f} before={b.files[f] ?? ""} after={a.files[f] ?? ""} />
        ))}
      </section>
    </>
  );
}

function format(value: number | string | undefined) {
  if (value === undefined) return "–";
  return typeof value === "number" ? compact(value) : value;
}

function Verdict({
  before,
  after,
  higherIsBetter,
  revA,
  revB,
}: {
  before: number;
  after: number;
  higherIsBetter: boolean | null;
  revA: number;
  revB: number;
}) {
  const { delta, verdict } = change(before, after, higherIsBetter);
  const relative = before !== 0 ? ` (${((delta / Math.abs(before)) * 100).toFixed(1)}%)` : "";
  // Status color always comes with an icon and a word, never alone.
  const icon = { better: "▲", worse: "▼", same: "=" }[verdict];
  return (
    <div className="verdict">
      <div>
        <span className="muted">revision {revB}</span> <strong>{compact(before)}</strong>
      </div>
      <div>
        <span className="muted">revision {revA}</span> <strong>{compact(after)}</strong>
      </div>
      <div className={`verdict-${verdict}`}>
        {icon} {verdict}
        {verdict !== "same" && `, ${delta > 0 ? "+" : ""}${compact(delta)}${relative}`}
      </div>
    </div>
  );
}

function FileDiff({ name, before, after }: { name: string; before: string; after: string }) {
  const lines = useMemo(() => diffLines(before, after), [before, after]);
  return (
    <details className="file-diff" open={name !== "instance.json"}>
      <summary>{name}</summary>
      {lines === null ? (
        <p className="muted">Too large to compare line by line.</p>
      ) : (
        <pre className="code diff">
          {lines.map((line, k) =>
            line.kind === "skip" ? (
              <div key={k} className="diff-skip">
                ⋯ {line.count} unchanged lines
              </div>
            ) : (
              <div key={k} className={`diff-${line.kind}`}>
                {{ same: "  ", added: "+ ", removed: "- " }[line.kind]}
                {line.text}
              </div>
            ),
          )}
        </pre>
      )}
    </details>
  );
}
