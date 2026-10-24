// The benchmark the agent improves the search on: its instances, every change it judged there,
// and every tuning of a heuristic's settings (docs/adr/0013, 0014).
import { Fragment, useEffect, useState } from "react";
import type { BenchEvaluation, BenchState, BenchTuning } from "../generated/bench-state";
import type { BenchProgress } from "../generated/server-event";
import {
  best,
  budget,
  fetchBench,
  outcomes,
  percent,
  progressText,
  side,
  verdictClass,
} from "../improve";
import { compact } from "../theme";

interface Props {
  project: string;
  /** Changes whenever the benchmark or the revisions do, to fetch it again. */
  version: string;
  progress: BenchProgress | null;
}

export function Improve({ project, version, progress }: Props) {
  const [bench, setBench] = useState<BenchState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    fetchBench(project)
      .then((b) => {
        setBench(b);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [project, version]);

  const status = progress && (
    <div className="status">
      {progressText(progress)} <progress value={progress.done} max={progress.total} />
    </div>
  );
  if (error) return <div className="banner critical">{error}</div>;
  if (!bench) return <div className="placeholder">Loading the benchmark…</div>;
  const { spec, evaluations, tunings } = bench;
  if (spec.instances.length === 0 && evaluations.length === 0) {
    return (
      <div className="result">
        {status}
        <div className="placeholder">
          No benchmark yet. Ask the agent to improve the search; the changes it judges, and how,
          show up here.
        </div>
      </div>
    );
  }
  const byId = new Map(evaluations.map((e) => [e.id, e]));
  return (
    <div className="result improve">
      {status}
      <section className="card">
        <h3>
          Benchmark{" "}
          <span className="sub">
            {spec.runs} runs per instance, {budget(spec)} each, paired by seed
          </span>
        </h3>
        {(["train", "validation"] as const).map((split) => {
          const entries = spec.instances.filter((i) => i.split === split);
          return (
            <div key={split} className="bench-split">
              <span className="muted">{split === "train" ? "Train" : "Validation"}</span>
              {entries.length === 0 && <span className="muted">none</span>}
              {entries.map((i) => (
                <span key={i.name} className="chip" title={i.source}>
                  {i.name}
                </span>
              ))}
            </div>
          );
        })}
      </section>
      {evaluations.length > 0 && (
        <section className="card table-wrap">
          <h3>
            Changes judged{" "}
            <span className="sub">newest first; gain relative to the baseline, + is better</span>
          </h3>
          <table className="attempts">
            <thead>
              <tr>
                <th className="num">#</th>
                <th>change</th>
                <th>against</th>
                <th>on</th>
                <th>verdict</th>
                <th className="num">gain</th>
                <th className="num">instances better / same / worse</th>
                <th className="num">solved into</th>
              </tr>
            </thead>
            <tbody>
              {[...evaluations].reverse().map((e) => (
                <Fragment key={e.id}>
                  <tr
                    className={open === e.id ? "on" : undefined}
                    onClick={() => setOpen(open === e.id ? null : e.id)}
                    title="Show each instance"
                  >
                    <td className="num">{e.id}</td>
                    <td>{e.note || <span className="muted">{side(e.candidate)}</span>}</td>
                    <td>{side(e.baseline)}</td>
                    <td>{e.split}</td>
                    <td className={verdictClass(e.verdict)}>{e.verdict}</td>
                    <td className="num">{percent(e.gain)}</td>
                    <td className="num">{outcomes(e)}</td>
                    <td className="num">{e.kept != null ? `revision ${e.kept}` : "—"}</td>
                  </tr>
                  {open === e.id && (
                    <tr className="attempt-detail">
                      <td colSpan={8}>
                        <Detail evaluation={e} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {tunings.length > 0 && (
        <section className="card table-wrap">
          <h3>
            Settings tuned <span className="sub">by racing them on the train instances</span>
          </h3>
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th>heuristic</th>
                <th className="num">runs</th>
                <th className="num">settings raced / dropped / failed</th>
                <th>best</th>
                <th>on validation</th>
              </tr>
            </thead>
            <tbody>
              {[...tunings].reverse().map((t) => (
                <TuningRow
                  key={t.id}
                  tuning={t}
                  check={t.validation != null ? byId.get(t.validation) : undefined}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function Detail({ evaluation: e }: { evaluation: BenchEvaluation }) {
  return (
    <div className="attempt">
      <p className="muted">
        {side(e.candidate)} ({e.candidate.variant}, {e.candidate.worker} worker) against{" "}
        {side(e.baseline)} ({e.baseline.variant}, {e.baseline.worker} worker)
        {e.verdict !== "rejected" && e.verdict !== "failed" && (
          <>
            ; p = {e.p_better.toPrecision(3)} against better, {e.p_worse.toPrecision(3)} against
            worse; mean worsening {(e.worsening * 100).toFixed(2)}%
          </>
        )}
      </p>
      {e.detail && <pre className="attempt-why">{e.detail}</pre>}
      {e.instances.length > 0 && e.verdict !== "rejected" && (
        <table>
          <thead>
            <tr>
              <th>instance</th>
              <th className="num">baseline mean</th>
              <th className="num">candidate mean</th>
              <th className="num">gain</th>
              <th>outcome</th>
            </tr>
          </thead>
          <tbody>
            {e.instances.map((i) => (
              <tr key={i.name}>
                <td>{i.name}</td>
                <td className="num">{compact(i.baseline)}</td>
                <td className="num">{compact(i.candidate)}</td>
                <td className="num">{percent(i.gain)}</td>
                <td className={verdictClass(i.outcome)}>{i.outcome}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TuningRow({ tuning: t, check }: { tuning: BenchTuning; check: BenchEvaluation | undefined }) {
  return (
    <>
      <tr>
        <td className="num">{t.id}</td>
        <td>
          {t.variants.join(" or ")} of revision {t.rev}
        </td>
        <td className="num">
          {t.used} / {t.budget}
        </td>
        <td className="num">
          {t.settings} / {t.eliminated} / {t.failed}
        </td>
        <td>{t.best ? best(t) : <span className="muted">the revision's own</span>}</td>
        <td>
          {check ? (
            <>
              <span className={verdictClass(check.verdict)}>{check.verdict}</span>{" "}
              <span className="muted">(#{check.id})</span>
            </>
          ) : (
            <span className="muted">—</span>
          )}
        </td>
      </tr>
      {t.signs.length > 0 && (
        <tr className="tuning-signs">
          <td />
          <td colSpan={5}>
            <ul>
              {t.signs.map((sign) => (
                <li key={sign}>{sign}</li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}
