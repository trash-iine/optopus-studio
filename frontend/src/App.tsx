import { useEffect, useRef, useState } from "react";
import { Canvas } from "./components/Canvas";
import { Chat } from "./components/Chat";
import type { ProjectInfo } from "./generated/projects";
import { useStudio } from "./studio";
import { type ThemePreference, useTheme } from "./theme";

async function createProject(): Promise<string> {
  const response = await fetch("/api/projects", { method: "POST" });
  return (await response.json()).id;
}

/** Attaches a file, or a case an app exported (a .zip), and returns the name the agent sees. */
async function upload(project: string, file: File): Promise<string> {
  const isCase = file.name.toLowerCase().endsWith(".zip");
  const url = isCase
    ? `/api/projects/${project}/cases`
    : `/api/projects/${project}/uploads?name=${encodeURIComponent(file.name)}`;
  const response = await fetch(url, { method: "POST", body: file });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? `upload failed: ${response.status}`);
  return isCase ? `case:${body.case}` : body.name;
}

async function listProjects(): Promise<ProjectInfo[]> {
  return (await fetch("/api/projects")).json();
}

/** Creates a project from a zip another studio exported. */
async function importProject(file: File): Promise<string> {
  const response = await fetch("/api/projects/import", { method: "POST", body: file });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? `import failed: ${response.status}`);
  return body.id;
}

export function projectLabel(project: ProjectInfo): string {
  const title = project.title ?? "Untitled";
  return project.imported_from ? `${title} (imported)` : title;
}

/** The project in the URL, else the latest one, else a new one. */
async function initialProject(): Promise<string> {
  const fromUrl = new URLSearchParams(location.search).get("project");
  if (fromUrl) return fromUrl;
  const projects = await listProjects();
  return projects[0]?.id ?? (await createProject());
}

export function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [mode, preference, setPreference] = useTheme();
  const { state, say, send } = useStudio(projectId);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [shareError, setShareError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const started = state.chat.length > 0;

  useEffect(() => {
    initialProject().then(setProjectId);
  }, []);
  useEffect(() => {
    if (projectId) history.replaceState(null, "", `?project=${projectId}`);
  }, [projectId]);
  // A project is titled by its first message, so the list changes when one starts.
  useEffect(() => {
    listProjects().then(setProjects);
  }, [projectId, started]);

  const importFile = async (file: File | undefined) => {
    if (!file) return;
    setShareError(null);
    try {
      setProjectId(await importProject(file));
    } catch (e) {
      setShareError((e as Error).message);
    } finally {
      if (picker.current) picker.current.value = "";
    }
  };

  return (
    <div className="app">
      <header>
        <span className="brand">optopus studio</span>
        <select
          className="projects"
          aria-label="project"
          title={projectId ?? undefined}
          value={projectId ?? ""}
          onChange={(e) => setProjectId(e.target.value)}
        >
          {projectId && !projects.some((p) => p.id === projectId) && <option value={projectId}>Untitled</option>}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {projectLabel(p)}
            </option>
          ))}
        </select>
        <span className={`dot ${state.connected ? "on" : ""}`} title={state.connected ? "connected" : "disconnected"} />
        <div className="spacer" />
        {shareError && <span className="header-error">{shareError}</span>}
        <input
          ref={picker}
          type="file"
          accept=".zip"
          hidden
          onChange={(e) => importFile(e.target.files?.[0])}
        />
        <button
          className="secondary"
          title="Open a project someone exported"
          onClick={() => picker.current?.click()}
        >
          Import
        </button>
        <button
          className="secondary"
          title="Download this project, its chat, revisions and attachments, as one zip to hand on"
          disabled={!projectId}
          onClick={() => location.assign(`/api/projects/${projectId}/export`)}
        >
          Export
        </button>
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
