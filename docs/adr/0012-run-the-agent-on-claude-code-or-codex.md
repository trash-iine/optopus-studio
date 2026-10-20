# 0012. Run the agent on Claude Code or Codex, chosen per project

- Status: Accepted
- Date: 2026-10-20

## Context

ADR 0003 ran the agent only through the Claude Agent SDK on the Claude Code login. Some users
have a Codex (ChatGPT or OpenAI) login instead, or want to compare the two agents on the same
task. What ADR 0003 guarantees has to hold for either: the agent works only through the studio's
tools, signs in with a login rather than a key the studio handles, streams its replies, can be
interrupted, and resumes its session after a restart.

## Options

1. **Codex app-server with dynamic tools.** `codex app-server` speaks JSON-RPC over stdio. A
   thread can be started with `dynamicTools`; Codex calls one by sending the client an
   `item/tool/call` request, so the tools run in the studio's process, as the in-process MCP
   server does for Claude.
2. **Codex with the studio as an MCP server.** The studio would serve its tools over HTTP for
   Codex to connect to: a port and a token per session, and the tools' broadcasts would cross
   that boundary.
3. **The OpenAI Agents SDK or the Responses API.** An API key, which ADR 0003 rules out.

## Decision

Option 1. `agent.py` keeps the system prompt, the tools (`Tools.specs()`) and the conversation;
a `Backend` holds one agent's session: `agent_claude.py` (unchanged from ADR 0003) and
`agent_codex.py`, a small JSON-RPC client with no new dependency.

- Each project records its agent in `meta.json` (`agent`, next to `session_id`). The chat's
  **Agent** menu switches it while the agent is idle. Switching drops the session; the next
  message hands the new agent the conversation so far, as an imported project does (ADR 0007).
  A project from before this ADR is on Claude. A new project starts on `--agent` /
  `OPTOPUS_STUDIO_AGENT`, else the first agent that can run.
- Codex starts as `codex app-server` with `-c` overrides that turn its own tools off (shell,
  unified exec, apply_patch with it, web search, images, apps, plugins, memories, skills'
  instructions, project docs) and every MCP server in its `config.toml`. The thread runs with
  `sandbox: "read-only"` and `approvalPolicy: "never"`; any approval or user-input request is
  answered with an error.
- It signs in with the Codex login (`codex login`, kept in `$CODEX_HOME`); `OPENAI_API_KEY` and
  `CODEX_API_KEY` are removed from the app-server's environment. A missing login is found with
  `account/read` before the thread starts and reported as "run `codex login`".
- The thread id is the session id. A thread that cannot be resumed is replaced by a new one that
  reads the conversation.
- Codex 0.153 or later, the release this was built and checked against.

## Consequences

- Some of Codex's tools cannot be turned off from the outside and stay visible to the model:
  `request_user_input` (refused when called), reading skills, and the clock; on models that run
  in code mode (gpt-6-astra, gpt-5.6), a JavaScript `exec` that can only call the tools above,
  and on models with multi-agent v2, sub-agents that have the same tools. None reaches files,
  the shell or the network. A global `~/.codex/AGENTS.md` is still read. Claude reads neither
  its user settings nor CLAUDE.md (`setting_sources=[]`).
- Dynamic tools are an experimental part of the app-server protocol, and the overrides name
  feature flags that may change. Before raising `MIN_VERSION`, check them again: send a
  thread's request to a local stand-in for the Responses API (a `model_providers` entry with a
  `base_url`) and read the tools in it.
- A resumed Codex thread keeps the tools it was started with; a tool added later reaches
  existing projects only after a switch or a new session.
- The hermetic tests run against a fake app-server (`tests/fake_codex.py`); nothing in CI needs
  Codex or a login.
