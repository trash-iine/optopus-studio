# 0017. Choose the agent's model and effort from the agent's own list

- Status: Accepted
- Date: 2026-11-04

## Context

The agent ran on Claude Code's or Codex's default model, or on one set for the whole studio with
`OPTOPUS_STUDIO_CLAUDE_MODEL` / `OPTOPUS_STUDIO_CODEX_MODEL`, at the model's default reasoning
effort. A user may want a stronger model or more effort for a hard problem, or a faster one for
a quick change, without restarting the studio. Both agents add and drop models often, and the
efforts a model takes differ from model to model (Codex offers `ultra` on some, Claude's older
models take none), so a list kept in the studio would go stale.

## Decision

The studio keeps no list of models. It asks each agent for its own, and offers what it gets.

- Claude: the Agent SDK's `get_server_info()` after `connect()` carries the CLI's `models`
  (`value`, `displayName`, `description`, `supportsEffort`, `supportedEffortLevels`). The studio
  connects with no tools, settings or prompt to read it. The `default` entry is the default unless
  `OPTOPUS_STUDIO_CLAUDE_MODEL` names another.
- Codex: the app-server's `model/list`, every page, without hidden models (`model`,
  `displayName`, `isDefault`, `supportedReasoningEfforts`, `defaultReasoningEffort`).
- `GET /api/agents/{agent}/models` serves the list (`ModelList`), or why the agent could not list
  it. It is kept in memory while the studio runs, and asked again after a restart.
- A project's `meta.json` keeps a model and an effort per agent (`models`), so switching agents
  keeps each one's choice. None means the default: the environment's model, else the agent's.
  The chat's **Model** and **Effort** menus set it while the agent is idle (`select_model`); the
  studio checks the choice against the agent's list. Like the web search switch (ADR 0016), a
  change closes the session and the next message resumes it.
- Claude gets the model and effort as `ClaudeAgentOptions(model=..., effort=...)`. Codex gets the
  model on `thread/start` and `thread/resume`, and the effort on every `turn/start`.

## Consequences

- A model or effort an agent adds shows up after a restart, with no change to the studio.
- Listing starts the Claude Code CLI or the Codex app-server, a few seconds the first time; until
  it answers, or when it cannot (no login, the agent not installed), the menus are not shown and
  the agent runs on its default.
- `meta.json` is not exported (ADR 0007), so an imported project starts on the defaults.
- A model the agent stops offering stays chosen, shown by its id, until the user picks another;
  what the agent does with it is up to the agent.
