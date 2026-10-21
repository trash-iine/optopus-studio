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
2. **The studio as an MCP server, for both agents.** The studio would serve its tools at `/mcp`
   on 127.0.0.1, with a token per session, and give both agents its URL. The tools would still
   run in the studio's process; Codex would no longer depend on an experimental API, and any
   other agent that speaks MCP would be cheap to add. It costs a port and a token, the `-c`
   overrides are still needed to turn off Codex's own tools, and whether Codex asks for approval
   before an MCP tool call under `approvalPolicy: "never"` was not checked.
3. **The OpenAI Agents SDK or the Responses API.** An API key, which ADR 0003 rules out.
4. **The user's own agent drives the studio.** The studio would serve its tools and the canvas
   over MCP, and the chat would move to Claude Code, Codex or an IDE: no code per agent. But the
   studio could no longer keep that agent to its tools, the conversation would not be in the
   project to share (ADR 0007) or to hand to another agent, and the system prompt would have to
   travel as the MCP server's instructions.
5. **The Agent Client Protocol.** The studio as an ACP client, reaching each agent through an
   adapter (`claude-code-acp`, `codex-acp`) and handing it the tools in `session/new`'s
   `mcpServers` (option 2's server): one protocol for many agents. The adapters are separate npm
   packages, so the studio would need Node; ACP has no standard way to turn off an agent's own
   tools, which leaves that to each adapter; and the adapters' packages were still moving.

## Decision

Option 1: it is the only one that keeps all of what ADR 0003 guarantees, and the conversation in
the project, with nothing more to run or listen on. `agent.py` keeps the system prompt, the tools
(`Tools.specs()`) and the conversation; a `Backend` holds one agent's session: `agent_claude.py`
(unchanged from ADR 0003) and `agent_codex.py`, a small JSON-RPC client with no new dependency.

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
- If dynamic tools go away or keep changing, option 2 is the way out: `Tools.specs()` carries
  over as it is, and the same `/mcp` is the first step of option 4. Option 5 is worth another look
  once ACP can turn off an agent's own tools. Running the agent and the generated code in a
  container is a separate question, open under any of these options: it would contain what a
  prompt injection through uploaded data or a shared project's conversation could make the
  agent write.
