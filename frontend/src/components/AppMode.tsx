import { useCallback, useEffect, useState } from "react";
import { api, formOf, type ParameterForm, parameterValues } from "../appmode";
import { download } from "../download";
import type { AppInfo, AppInput, AppParameter } from "../generated/app-info";
import type { CaseState } from "../generated/case";
import { compact, type ThemePreference, useTheme } from "../theme";
import { SolveResult } from "./SolveResult";

const ACCEPT = ".csv,.tsv,.txt,.xlsx,.json";
const POLL_MS = 500;

/** A packaged app: give data, set the parameters app.json lists, solve, see the result. */
export function AppMode() {
  const [mode, preference, setPreference] = useTheme();
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [current, setCurrent] = useState<CaseState | null>(null);
  const [form, setForm] = useState<ParameterForm>({});
  const [error, setError] = useState<string | null>(null);

  const open = useCallback((state: CaseState) => {
    setCurrent(state);
    history.replaceState(null, "", `?case=${state.id}`);
  }, []);
  const run = useCallback(async (action: () => Promise<CaseState>) => {
    setError(null);
    try {
      setCurrent(await action());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    api.info().then((loaded) => {
      setInfo(loaded);
      document.title = loaded.spec.title;
    }, (e: Error) => setError(e.message));
    const fromUrl = new URLSearchParams(location.search).get("case");
    (fromUrl ? api.getCase(fromUrl).catch(() => api.newCase()) : api.newCase()).then((state) => {
      open(state);
      setForm(formOf(state.parameters));
    }, (e: Error) => setError(e.message));
  }, [open]);

  // A solve runs in the background on the server; follow it until it ends.
  useEffect(() => {
    if (current?.status !== "solving") return;
    const timer = setTimeout(() => run(() => api.getCase(current.id)), POLL_MS);
    return () => clearTimeout(timer);
  }, [current, run]);

  if (!info || !current) {
    return <div className="placeholder">{error ?? "Opening the app…"}</div>;
  }
  const solving = current.status === "solving";
  const startNew = () =>
    run(async () => {
      const state = await api.newCase();
      open(state);
      setForm({});
      return state;
    });

  return (
    <div className="app">
      <header>
        <span className="brand">{info.spec.title}</span>
        <span className="muted app-version" title={`packaged ${info.packaged_at}`}>
          revision {info.rev} of studio project {info.project}
        </span>
        <div className="spacer" />
        {error && <span className="header-error">{error}</span>}
        <button className="secondary" disabled={solving} onClick={startNew}>
          New case
        </button>
        <select
          aria-label="theme"
          value={preference}
          onChange={(e) => setPreference(e.target.value as ThemePreference)}
        >
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </header>
      <div className="workspace">
        <aside className="chat app-panel">
          <div className="messages app-form">
            {info.spec.description && <p className="app-description">{info.spec.description}</p>}
            {info.spec.inputs.length > 0 && <h3>Data</h3>}
            {info.spec.inputs.map((input) => (
              <InputCard
                key={input.key}
                input={input}
                given={current.inputs.find((i) => i.key === input.key)}
                disabled={solving}
                onFile={(file) => run(() => api.setInput(current.id, input.key, file))}
                onRemove={() => run(() => api.removeInput(current.id, input.key))}
              />
            ))}
            {info.spec.parameters.length > 0 && <h3>Settings</h3>}
            {info.spec.parameters.map((p) => (
              <ParameterField
                key={p.name}
                parameter={p}
                packaged={info.defaults[p.name]}
                value={form[p.name]}
                disabled={solving}
                onChange={(value) => setForm((f) => ({ ...f, [p.name]: value }))}
              />
            ))}
          </div>
          <div className="composer app-actions">
            <span className="muted">{statusLine(current)}</span>
            <button
              className="secondary"
              title="Download these inputs and what they gave, to attach in the studio's chat"
              disabled={solving || (current.inputs.length === 0 && !current.summary && current.problems.length === 0)}
              onClick={async () => {
                setError(await download(`/api/app/cases/${current.id}/export`, `optopus-case-${current.id}.zip`));
              }}
            >
              Export case
            </button>
            <button
              disabled={solving}
              onClick={() => run(() => api.solve(current.id, parameterValues(info.spec.parameters, form)))}
            >
              Solve
            </button>
          </div>
        </aside>
        <main className="canvas">
          <div className="canvas-body">
            <div className="result">
              {current.problems.length > 0 && (
                <div className="banner critical">
                  <strong>These inputs cannot be solved as they are</strong>
                  <ul>
                    {current.problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
              {current.summary ? (
                <SolveResult summary={current.summary} view={current.view} viewError={current.view_error} mode={mode} />
              ) : (
                info.sample && (
                  <>
                    <div className="banner info">
                      The result on the data the app was made with. Give your data on the left and solve.
                    </div>
                    <SolveResult summary={info.sample} view={info.sample_view} viewError={null} mode={mode} />
                  </>
                )
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function statusLine(state: CaseState): string {
  const summary = state.summary;
  if (state.status === "solving") {
    const point = summary?.live?.points.at(-1) as number[] | undefined;
    const runs = summary ? `${summary.runs.length} runs done` : "starting";
    return `Solving: ${runs}${point ? `, best so far ${compact(point[1])}` : ""}`;
  }
  if (state.status === "solved") return "Solved";
  if (state.status === "failed") return "The solve failed";
  return "";
}

function InputCard({
  input,
  given,
  disabled,
  onFile,
  onRemove,
}: {
  input: AppInput;
  given: { file: string; rows: number | null } | undefined;
  disabled: boolean;
  onFile: (file: File) => void;
  onRemove: () => void;
}) {
  return (
    <div className="app-input">
      <div className="app-input-head">
        <strong>{input.label}</strong>
        {input.required && <span className="muted">required</span>}
      </div>
      {input.description && <p className="muted">{input.description}</p>}
      {input.columns.length > 0 && (
        <div className="app-columns">
          {input.columns.map((c) => (
            <code key={c.name} title={c.description ?? undefined}>
              {c.name}
              {c.type ? `: ${c.type}` : ""}
              {c.required ? "" : " (optional)"}
            </code>
          ))}
        </div>
      )}
      <div className="app-input-file">
        {given ? (
          <span>
            {given.file}
            {given.rows != null && <span className="muted"> · {given.rows} rows</span>}
          </span>
        ) : (
          <span className="muted">{input.required ? "No file yet" : "Using the packaged data"}</span>
        )}
        <label className={`file-button ${disabled ? "disabled" : ""}`}>
          {given ? "Replace" : "Choose file"}
          <input
            type="file"
            accept={ACCEPT}
            hidden
            disabled={disabled}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFile(file);
              e.target.value = "";
            }}
          />
        </label>
        {given && (
          <button className="secondary" disabled={disabled} onClick={onRemove}>
            Use packaged data
          </button>
        )}
      </div>
    </div>
  );
}

function ParameterField({
  parameter: p,
  packaged,
  value,
  disabled,
  onChange,
}: {
  parameter: AppParameter;
  packaged: unknown;
  value: string | boolean | undefined;
  disabled: boolean;
  onChange: (value: string | boolean) => void;
}) {
  const label = `${p.label}${p.unit ? ` (${p.unit})` : ""}`;
  let field;
  if (p.type === "boolean") {
    field = (
      <input
        type="checkbox"
        checked={typeof value === "boolean" ? value : Boolean(packaged)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  } else if (p.choices) {
    field = (
      <select value={typeof value === "string" ? value : ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        <option value="">packaged: {String(packaged)}</option>
        {p.choices.map((c) => (
          <option key={String(c)} value={String(c)}>
            {String(c)}
          </option>
        ))}
      </select>
    );
  } else {
    const numeric = p.type !== "string";
    field = (
      <input
        type={numeric ? "number" : "text"}
        step={p.type === "integer" ? 1 : "any"}
        min={p.min ?? undefined}
        max={p.max ?? undefined}
        placeholder={packaged == null ? "as packaged" : String(packaged)}
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <label className="app-param">
      <span>{label}</span>
      {field}
      {p.description && <small className="muted">{p.description}</small>}
    </label>
  );
}
