# 0007. Share a project as a zip, without the agent's session

- Status: Accepted
- Date: 2026-10-14

## Context

Users want to hand a project to a teammate: the conversation, the model, every revision with its
result, and the data they attached. Each studio is local and single-user (ADR 0003), so there is
no server to share through; a file passed by hand is enough.

The agent's memory of the conversation is its Claude Agent SDK session, which Claude Code keeps
under the sender's home, keyed by the project's absolute path. That path differs on another
machine, and the session holds every tool result, the data included.

## Options

1. Export the project directory and the session transcript; the importer moves the transcript to
   where its Claude Code looks for it and resumes the session.
2. Export the project directory without the session; the importer's agent starts a new session
   and is given the conversation as the GUI shows it.

## Decision

Option 2. `GET /api/projects/{id}/export` writes a zip of `chat.jsonl`, `work/`, `revs/` (files,
`result.json`, `view.json`) and `uploads/`, with a manifest `optopus-studio-project.json`
(`format: 1`, the project's id, the time of export). `meta.json` stays behind. `POST
/api/projects/import` checks every member against what a project holds and parses the JSON,
the chat and the results before it writes anything, then creates a new project whose
`meta.json` records `imported_from`.

When a project has a chat but no session, the agent's first message starts with that chat
(`with_history`, the last 40,000 characters), and the system prompt is unchanged. The project
files carry the rest: the agent reads them as the conversation left them.

The first option depends on where Claude Code stores sessions, which is not part of its
interface, and on resuming a session recorded under another path.

## Consequences

- An imported project shows the same chat, revisions, results and views, and can be solved
  again at once. A Rust port is rebuilt from its `rust/main.rs` on first use, which needs cargo.
- The importer's agent knows what was said and what the files are, not the tool results of the
  earlier session; it reads the files again when it needs them.
- A newer studio reads a `format` it knows and refuses others with a message saying so.
