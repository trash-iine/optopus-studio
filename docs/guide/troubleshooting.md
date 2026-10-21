# Troubleshooting

Find the symptom, then the fix. The terminal where `optopus-studio` runs logs every request and
error; look there first when the page says little.

## Installing

### `uv sync` fails while building optopus

optopus is compiled from source, so this is almost always the Rust toolchain or the network.

- **Rust is missing or old.** `cargo --version` must work in the same terminal and report 1.88 or
  later. Install it from <https://rustup.rs>, or `rustup update`; open a new terminal so `cargo`
  is on `PATH`, then run `uv sync` again.
- **GitHub cannot be reached.** uv fetches optopus-py with git. Check `git ls-remote
  https://github.com/trash-iine/optopus-py` works; behind a proxy, set `HTTPS_PROXY`.
- **A C compiler or linker is missing.** On macOS run `xcode-select --install`; on Debian or
  Ubuntu, `sudo apt install build-essential`.

### `npm install` or `npm run build` fails

Check `node --version` says v24. With mise, run `mise install` in the checkout and make sure your
shell activates mise; otherwise install Node 24 another way. Delete `frontend/node_modules` and
run `npm install` again after switching versions.

## Starting

### `optopus-studio: error: the studio needs an agent, and none can run here (…)`

Neither agent can run. The parentheses say why for each: "the Claude Agent SDK is not installed"
means `uv sync` was run with `--no-default-groups` or `--only-group` (run plain `uv sync` in the
checkout); "Codex is not installed" or "is too old" means `codex` is missing from `PATH` or older
than 0.153 (install or `codex update` it, or point `OPTOPUS_STUDIO_CODEX` at it).

### `optopus-studio: error: the agent cannot run on codex: …`

`--agent codex` or `OPTOPUS_STUDIO_AGENT=codex` asked for Codex, which cannot run for the reason
given; see above. The same goes for `claude`.

### `[Errno 48] … address already in use` (`Errno 98` on Linux)

Another program, often a studio you started earlier, uses port 8765. Stop it, or start this one
on another port: `uv run optopus-studio --port 8770`.

### The page only says `{"detail":"Not Found"}`

The web page has not been built, so the server has nothing to show. Run
`(cd frontend && npm install && npm run build)`, then restart the studio: it looks for the built
page when it starts.

### The page loads but the dot stays grey and the box says "Connecting…"

The page cannot reach the server: it stopped (check its terminal), or you opened another
address or port than the one it listens on. The page retries every second, so it connects as soon
as the server is back.

## The agent

### Red error in the chat about logging in, authentication or the API key

The agent runs on your Claude Code or Codex login, not on an API key
([ADR 0003](../adr/0003-agent-on-claude-code-login.md),
[ADR 0012](../adr/0012-run-the-agent-on-claude-code-or-codex.md)). On Claude, run `claude`, then
`/login`; on Codex ("Codex is not signed in"), run `codex login`. Then send the message again.
`ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are removed from the studio's environment on
purpose (the terminal logs "ignoring ANTHROPIC_API_KEY; the agent on Claude uses the Claude Code
login"), and Codex starts without `OPENAI_API_KEY` and `CODEX_API_KEY`.

If the error mentions a usage limit, your Claude or ChatGPT plan's limit was reached; wait until
it resets, or switch the project to the other agent.

### An agent in the **Agent** menu is marked "(unavailable)"

It cannot run on this machine; hover over it for the reason (not installed, too old). Fix that
and restart the studio: it checks the agents when it starts.

### "Codex stopped: …"

The Codex app-server exited; the rest of the message is the end of what it printed. Send the
message again to start it again. If it keeps failing, run `codex doctor`.

### "the agent stopped: …"

The agent's session ended with an error; the rest of the message says why, and the terminal has
the full traceback. Send your message again to start the agent again; the project, files and
revisions are kept.

### "the agent is still working"

You sent a message while it was busy. Wait until **Stop** turns back into **Send**, or press
**Stop** first.

### The agent says it could not read optopus's documentation

The agent fetches optopus-py's user guide from GitHub the first time it reads each page, then
keeps it under `~/.optopus-studio/docs/`. Offline, or behind a proxy that blocks
`raw.githubusercontent.com`, the fetch fails. The agent can still look up classes with
`api_help`, but models are better with the guide. Fix the network, or clone optopus-py at the
pinned commit (in `pyproject.toml`) and set `OPTOPUS_STUDIO_DOCS=<checkout>/docs/source`.

### The agent keeps getting a model wrong

Be more specific about the objective and the constraints, give a small example of a good
solution, or say which view would show the problem. Ask it to compare heuristics when the result is
poor rather than wrong. Starting a **New project** with a clearer first message also helps after
a long, winding conversation.

## Solving

### Red banner "The solve failed at …"

The solve stopped with an error at that stage (request, build, heuristic, start, run or encode).
The agent sees the same message and traceback and usually fixes it on its own; if it stopped, ask
it to fix the error. At start, the solution `solve.json`'s `"initial_solution"` names does not fit
the problem, as when the data changed since the solution was found; see
[Starting from a solution](projects.md#starting-from-a-solution).

### "the solve took longer than 300.0s"

A solve is stopped after the time its runs may take by their stop conditions plus 30 seconds (20
minutes at most), or after 300 seconds when a heuristic has no time limit. Ask the agent for a time limit ("stop each run after 10 seconds"),
or set `OPTOPUS_STUDIO_SOLVE_TIMEOUT` (seconds) before starting the studio.

### Yellow banner "view.py failed"

The solve worked; only drawing it failed. The result is in the Runs tab. Ask the agent to fix the
view.

### A Rust port does not build

`cargo is not installed; see https://rustup.rs` means the studio cannot find `cargo` on the
`PATH` it was started with. Other build errors are the agent's to fix; ask it to. Ports are built
under `~/.optopus-studio/rust/`; deleting that folder forces a clean build.

## Files and sharing

### Attaching a file fails

The message under the box says why:

- `… expected one of ('.csv', '.tsv', '.txt', '.xlsx', '.json')`: other formats, including the
  old `.xls`, are not read. Save the sheet as `.xlsx` or CSV.
- `… is larger than 20 MiB`: split the file, or drop columns the model does not need.
- `invalid file name …`: rename it to letters, digits, spaces, `.`, `-` and `_`, not starting with
  a dot.

### Import says "not a zip file" or "not an exported studio project"

**Import** takes only a zip made by **Export**. A package made by **Package** is an app; run it
with `uv run optopus-studio app <zip>` instead. A case exported from an app is attached in the chat
with **+**.

### "Cannot package revision N"

`revision N has no app.json` means that revision was solved before the model was made an app: ask
the agent to make it an app, then package the revision it solves. `app.json does not fit the
revision` lists what is wrong; ask the agent to fix it.

### Building a Docker image fails

`docker is not installed` or `docker is not running`: install or start Docker Desktop (or the
daemon) and try again. On Apple Silicon the build emulates `linux/amd64` and takes about ten
minutes; that is expected.

## Starting over

Stop the studio and delete a project's folder under `~/.optopus-studio/projects/`, or the whole
`~/.optopus-studio` directory. Your checkout is not affected.

## Still stuck

Open an issue at <https://github.com/trash-iine/optopus-studio/issues> with what you did, what you
expected, the message on the page and the end of the terminal's log. Exporting the project
(**Export**) and attaching it helps, if its data may be shared.
