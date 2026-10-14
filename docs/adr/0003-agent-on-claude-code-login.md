# 0003. Run the agent through the Claude Agent SDK on the Claude Code login

- Status: Accepted
- Date: 2026-10-14

## Context

The studio is a local, single-user tool. Its agent needs a multi-turn loop with custom tools,
streaming, interruption and resumable sessions, and should not need a separate API key.

## Decision

The agent is a `ClaudeSDKClient` (claude-agent-sdk, Python) per project. The SDK starts its
bundled Claude Code CLI, which signs in with the user's Claude Code login. `optopus-studio`
removes `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from its environment at start, so an
exported key never takes over.

The agent gets no built-in tools (`tools=[]`) and no user or project settings
(`setting_sources=[]`). It works only through six in-process MCP tools: `read_docs`, `api_help`,
`read_file`, `write_file` (the four project files only), `check_model` and `run_solver`. Each
project's session id is stored in its `meta.json` and resumed after a restart.

## Consequences

- No key to manage; usage counts against the user's Claude plan. This suits personal, local use;
  a hosted, multi-user studio would need its own authentication and is out of scope.
- The agent cannot touch anything outside its project, run shell commands or browse; everything
  it does is visible in the GUI.
- The SDK client must stay in the task that opened it, so each session owns a task fed by a queue.
