// The connection to one project's WebSocket, and the state the GUI draws from it.
import { useCallback, useEffect, useReducer, useRef } from "react";
import type { ClientEvent } from "./generated/client-event";
import type { ChatEntry, RunSummary, ServerEvent, ViewSpec } from "./generated/server-event";

export interface StudioState {
  connected: boolean;
  chat: ChatEntry[];
  streaming: string;
  busy: boolean;
  files: Record<string, string>;
  revisions: number[];
  rev: number | null;
  summary: RunSummary | null;
  view: ViewSpec | null;
  viewError: string | null;
  solving: { rev: number; runs: number } | null;
  error: string | null;
}

export const initialState: StudioState = {
  connected: false,
  chat: [],
  streaming: "",
  busy: false,
  files: {},
  revisions: [],
  rev: null,
  summary: null,
  view: null,
  viewError: null,
  solving: null,
  error: null,
};

type Action =
  | { type: "connected"; connected: boolean }
  | { type: "sent"; text: string }
  | { type: "event"; event: ServerEvent };

export function reduce(state: StudioState, action: Action): StudioState {
  if (action.type === "connected") return { ...state, connected: action.connected };
  if (action.type === "sent") {
    return {
      ...state,
      busy: true,
      error: null,
      chat: [...state.chat, { role: "user", text: action.text }],
    };
  }
  const e = action.event;
  switch (e.type) {
    case "snapshot":
      return {
        ...state,
        chat: e.chat,
        streaming: "",
        busy: e.busy,
        files: e.files,
        revisions: e.revisions,
        rev: e.rev,
        summary: e.summary,
        view: e.view,
        viewError: e.view_error,
      };
    case "assistant_delta":
      return { ...state, streaming: state.streaming + e.text };
    case "assistant_text":
      return { ...state, streaming: "", chat: [...state.chat, { role: "assistant", text: e.text }] };
    case "tool":
      return {
        ...state,
        chat: [...state.chat, { role: "tool", text: `${e.name} ${e.summary}`.trim() }],
      };
    case "turn_end":
      return { ...state, busy: false, streaming: "", solving: null, error: e.error };
    case "files":
      return { ...state, files: e.files };
    case "solve_started":
      return {
        ...state,
        revisions: [...state.revisions, e.rev],
        rev: e.rev,
        solving: { rev: e.rev, runs: e.runs },
        summary: {
          rev: e.rev,
          runs: [],
          variants: [],
          worker: "python",
          native: null,
          live: null,
          best_run: null,
          error: null,
          higher_is_better: null,
          problem: null,
        },
        view: null,
        viewError: null,
      };
    case "solve_progress":
      return e.rev === state.rev ? { ...state, summary: e.summary } : state;
    case "view":
      return {
        ...state,
        solving: null,
        ...(e.rev === state.rev ? { view: e.view, viewError: e.error } : {}),
      };
  }
}

export function useStudio(projectId: string | null) {
  const [state, dispatch] = useReducer(reduce, initialState);
  const socket = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${scheme}://${location.host}/api/projects/${projectId}/ws`);
      socket.current = ws;
      ws.onopen = () => dispatch({ type: "connected", connected: true });
      ws.onmessage = (m) => dispatch({ type: "event", event: JSON.parse(m.data) as ServerEvent });
      ws.onclose = () => {
        dispatch({ type: "connected", connected: false });
        if (!closed) retry = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket.current?.close();
    };
  }, [projectId]);

  const send = useCallback((event: ClientEvent) => {
    socket.current?.send(JSON.stringify(event));
  }, []);

  const say = useCallback(
    (text: string) => {
      dispatch({ type: "sent", text });
      send({ type: "user_message", text });
    },
    [send],
  );

  return { state, say, send };
}
