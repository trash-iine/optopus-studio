import { useEffect, useState } from "react";
import { Canvas } from "./components/Canvas";
import { Chat } from "./components/Chat";
import { useStudio } from "./studio";
import { type ThemePreference, useTheme } from "./theme";

async function createProject(): Promise<string> {
  const response = await fetch("/api/projects", { method: "POST" });
  return (await response.json()).id;
}

async function upload(project: string, file: File): Promise<string> {
  const url = `/api/projects/${project}/uploads?name=${encodeURIComponent(file.name)}`;
  const response = await fetch(url, { method: "POST", body: file });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? `upload failed: ${response.status}`);
  return body.name;
}

/** The project in the URL, else the latest one, else a new one. */
async function initialProject(): Promise<string> {
  const fromUrl = new URLSearchParams(location.search).get("project");
  if (fromUrl) return fromUrl;
  const projects: string[] = await (await fetch("/api/projects")).json();
  return projects[0] ?? (await createProject());
}

export function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [mode, preference, setPreference] = useTheme();
  const { state, say, send } = useStudio(projectId);

  useEffect(() => {
    initialProject().then(setProjectId);
  }, []);
  useEffect(() => {
    if (projectId) history.replaceState(null, "", `?project=${projectId}`);
  }, [projectId]);

  return (
    <div className="app">
      <header>
        <span className="brand">optopus studio</span>
        <span className="project">{projectId}</span>
        <span className={`dot ${state.connected ? "on" : ""}`} title={state.connected ? "connected" : "disconnected"} />
        <div className="spacer" />
        <button className="secondary" onClick={() => createProject().then(setProjectId)}>
          New project
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
        <Chat
          chat={state.chat}
          streaming={state.streaming}
          busy={state.busy}
          connected={state.connected}
          error={state.error}
          onSend={say}
          onStop={() => send({ type: "interrupt" })}
          onUpload={(file) => upload(projectId ?? "", file)}
        />
        <Canvas
          project={projectId}
          state={state}
          mode={mode}
          onSelect={(rev) => send({ type: "select_revision", rev })}
          onAsk={say}
        />
      </div>
    </div>
  );
}
