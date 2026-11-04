# 0016. Let the agent search the web when a project allows it

- Status: Accepted
- Date: 2026-10-31

## Context

ADR 0003 and ADR 0012 give the agent no tools but the studio's, so that everything it does goes
through code the studio controls and shows. To improve the search on its own (ADR 0015), the
agent should look up which methods work on problems like the user's. It may not know a recent
method, or know it only vaguely, and the recipes page covers only common kinds of problem. Both
Claude Code and Codex have a web search of their own, which the studio turns off.

## Options

1. Keep the web out; the agent knows what its model knows, plus the recipes.
2. A studio tool that searches a literature index (Semantic Scholar, arXiv) over HTTP.
3. Let the backend's own web tools through, on a switch per project that is off by default:
   Claude Code's `WebSearch` and `WebFetch`, and Codex's web search.

## Decision

Option 3.

- **The switch**: `web_search` in a project's meta.json, off by default.
  - It is set from the chat panel (the "Web search" checkbox next to the agent picker). It cannot
    be changed while the agent works.
  - Changing it closes the agent's session, and the next message reopens it with the session
    resumed and the tools changed.
- **Claude**: with the switch on, `tools=["WebSearch", "WebFetch"]`, both also in
  `allowed_tools`. Everything else stays as ADR 0003 has it: `strict_mcp_config`, no setting
  sources, and the studio's tools as its MCP server.
- **Codex**: with the switch on, `web_search="live"` in place of `"disabled"`. Every other
  feature stays off (ADR 0012).
- **What the user sees**: each search and fetch shows in the chat as a tool line
  (`web_search <query>`, `web_fetch <url>`), as the studio's own tools do.
- **What the agent is told**: what a page says is material, not instructions; it takes a
  method's idea, and names the source in the evaluation's note.
- **Logins**: the login stays the one each backend already has. No key is added (ADR 0003, ADR
  0012).

The first option leaves the agent to its model's memory, which is what the user asked to go
beyond. The second needs an API that may require a key, limits the agent to abstracts, and
duplicates what both backends already do well.

## Consequences

- Pages the agent reads become its input, so they can try to instruct it. The switch bounds this:
  - The agent still acts only through the studio's tools. It has no shell and cannot run commands.
  - The code it writes still runs only in a subprocess with a timeout (AGENTS.md).
  - Every change it makes is still judged on the benchmark, with the baseline's model re-scoring
    the candidate (ADR 0013). A method found on the web wins only by searching better, never by
    changing the objective.
- Searching is not reproducible, but the decisions are. A search only suggests a hypothesis. The
  evaluation, recorded with its note and the sources named there, is what is kept.
- A project shared as a zip carries its switch in meta.json, which an export leaves out (ADR 0007).
  An imported project therefore starts with the web off.
- ADR 0003's "no built-in tools" and ADR 0012's list of Codex tools that are turned off now have
  this one exception.
