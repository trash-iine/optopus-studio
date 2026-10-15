// A packaged app's server (docs/adr/0009): the app it holds and the cases its user solves.
import type { AppInfo, AppParameter } from "./generated/app-info";
import type { CaseState } from "./generated/case";

/** What the user typed per parameter: text for a number or a choice, a flag for a boolean. */
export type ParameterForm = Record<string, string | boolean>;

/** The values a solve sends: what the user set; a blank field keeps the packaged value. */
export function parameterValues(parameters: AppParameter[], form: ParameterForm): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const p of parameters) {
    const value = form[p.name];
    if (value === undefined) continue;
    if (typeof value === "boolean") values[p.name] = value;
    else if (value.trim() !== "") values[p.name] = value.trim();
  }
  return values;
}

/** The form a case's stored parameters fill in. */
export function formOf(parameters: Record<string, unknown>): ParameterForm {
  const form: ParameterForm = {};
  for (const [name, value] of Object.entries(parameters)) {
    form[name] = typeof value === "boolean" ? value : String(value);
  }
  return form;
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  return body as T;
}

export const api = {
  info: () => call<AppInfo>("/api/app"),
  newCase: () => call<CaseState>("/api/app/cases", { method: "POST" }),
  getCase: (id: string) => call<CaseState>(`/api/app/cases/${id}`),
  setInput: (id: string, key: string, file: File) =>
    call<CaseState>(`/api/app/cases/${id}/inputs/${encodeURIComponent(key)}?name=${encodeURIComponent(file.name)}`, {
      method: "PUT",
      body: file,
    }),
  removeInput: (id: string, key: string) =>
    call<CaseState>(`/api/app/cases/${id}/inputs/${encodeURIComponent(key)}`, { method: "DELETE" }),
  setNote: (id: string, note: string) =>
    call<CaseState>(`/api/app/cases/${id}/note`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }),
  solve: (id: string, parameters: Record<string, unknown>) =>
    call<CaseState>(`/api/app/cases/${id}/solve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parameters }),
    }),
};
