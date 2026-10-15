# Development

This page is for changing the studio itself. Set it up first as in
[Getting started](getting-started.md). [`AGENTS.md`](../../AGENTS.md) is the short version of
this page for coding agents; keep the two in step.

## The development loop

Run the backend with reload, and the frontend's dev server next to it:

```bash
OPTOPUS_STUDIO_HOME=/tmp/studio-dev uv run optopus-studio --reload   # terminal 1, :8765
(cd frontend && npm run dev)                                         # terminal 2, :5173
```

Open <http://127.0.0.1:5173>: Vite reloads the page on every frontend change and forwards `/api`
(HTTP and WebSocket) to the backend on 8765. A separate `OPTOPUS_STUDIO_HOME` keeps test projects
out of your own.

A packaged app runs with `uv run optopus-studio app <zip-or-folder>` on :8766; the same frontend
shows it in app mode when `/api/mode` says `"app"`.

## How it fits together

```
browser (React)  <-- WebSocket: ServerEvent / ClientEvent -->  backend (FastAPI, Agent SDK)
                                                                  |  stdin/stdout JSON Lines:
                                                                  |  SolveRequest -> WorkerEvent
                                                                  v
                                                          solver worker (a subprocess)
```

The agent edits a project's files through the tools in `agent.py` only; it has no built-in Claude
Code tools. Every solve freezes the files into a revision:

| File | Runs in | Says |
|---|---|---|
| `instance.json` | — | the data |
| `model.py` | the worker | `build(instance)` returns an optopus problem; optional `encode_solution` makes the solution JSON |
| `solve.json` | the worker | the heuristic as `{"kind": ..., **arguments}`, or labeled `"heuristics"` to compare; runs, seed |
| `view.py` | the backend's viewer process | `to_view(instance, result)` returns a `ViewSpec` for the canvas |
| `rust/main.rs` (optional) | a Rust worker | the model ported to Rust; `"worker": "rust"` in `solve.json` runs it |
| `app.json` (optional) | a packaged app | what the app's user may change: input tables and parameters |

The three contracts live in `src/optopus_studio/protocol.py`, the single source of the schemas in
`schema/` and of the TypeScript types in `frontend/src/generated/`. Because the worker only speaks
`SolveRequest` / `WorkerEvent` and the canvas only reads `ViewSpec`, a solver written in Rust
replaces the Python worker without touching the GUI
([ADR 0001](../adr/0001-solver-behind-a-process-boundary.md)).

## Where things are

| Path | What |
|---|---|
| `src/optopus_studio/protocol.py` | every contract: worker protocol, `ViewSpec`, WebSocket events |
| `cli.py` | the `optopus-studio` command and its `app` and `image` subcommands |
| `app.py` | the studio's FastAPI server and WebSocket |
| `agent.py` | the Agent SDK session, the agent's tools and its system prompt |
| `projects.py` | projects, revisions and uploads on disk |
| `tables.py` | reading uploaded CSV, TSV, Excel and JSON |
| `solving.py` | turns a model's files into a solve, for both the agent and apps |
| `runner.py`, `worker.py`, `viewer.py` | start the solver and view processes; what runs inside them |
| `rust.py`, `verify.py` | build a project's Rust port; check it against the Python model |
| `apps.py`, `appserver.py` | package a revision with its `app.json`, and serve it without the agent |
| `image.py`, `docker/app.Dockerfile` | build a package into a Docker image |
| `frontend.py` | serves the built frontend for both servers |
| `docs.py` | fetches the optopus-py guide pages the agent reads |
| `frontend/` | React + Vite + ECharts; `src/generated/` is generated, never edit it |
| `workers/rust/` | the Rust worker library a port links ([GUIDE.md](../../workers/rust/GUIDE.md) is what the agent reads) |
| `examples/` | four complete projects that the tests solve |
| `schema/` | JSON Schemas generated from `protocol.py` |
| `docs/adr/` | the decisions behind the boundaries above |

## Rules that are easy to break

- Generated code (`model.py`, `view.py`) runs only in a subprocess with a timeout, never in the
  server process.
- The agent signs in with the Claude Code login; do not add API-key handling
  ([ADR 0003](../adr/0003-agent-on-claude-code-login.md)).
- Nothing an app runs (`appserver.py`, `apps.py` and their imports) may import `agent.py` or
  `app.py`: an app's image has no Agent SDK
  ([ADR 0010](../adr/0010-deliver-an-app-as-a-docker-image.md); `tests/test_image.py` checks it).
- Uploaded data reaches a model only through `instance.json`; `model.py` never reads `uploads/`
  ([ADR 0004](../adr/0004-import-uploads-into-the-instance.md)).
- A change to the worker protocol touches `protocol.py`, `worker.py` and `workers/rust/src`
  together.
- Colors in the frontend come from `src/theme.ts`.
- English in code, comments and docs. The Japanese guide in `docs/ja/` is a translation of
  `docs/guide/`; change both together.

## Checks

Run all of these before committing; CI runs them too.

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
(cd frontend && npm test && npm run typecheck)
(cd workers/rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings)
```

Two sets of tests run only when asked for:

```bash
uv run pytest -m network   # reads from GitHub: the docs pages the agent reads, the vendored core
uv run pytest -m docker    # builds and runs an app's image; needs Docker
```

Tests use tiny instances and stay under `tmp_path`.

## Changing the protocol

Change `protocol.py` first, then regenerate the schemas and the TypeScript types:

```bash
uv run python -m optopus_studio.schema && (cd frontend && npm run gen:types)
```

`tests/test_schema.py` fails until both are done, and CI checks that `frontend/src/generated`
matches the schemas.

## Moving to a newer optopus-py

optopus comes from a pinned optopus-py commit, and the Rust worker's core from the commit that
one vendors ([ADR 0008](../adr/0008-depend-on-a-pinned-optopus-py-commit.md)). To move:

1. Set `rev` in `pyproject.toml` to the new optopus-py commit.
2. Set `rev` in `workers/rust/Cargo.toml` to the commit of its `vendor/optopus`.
3. `uv sync`, then `uv run pytest` and `uv run pytest -m network`.

To try an optopus-py checkout before it is merged, point `[tool.uv.sources]` at it with `path` and
`OPTOPUS_STUDIO_DOCS` at its `docs/source`, without committing that.

## The Rust worker

`workers/rust/` is the library a project's `rust/main.rs` links
([ADR 0005](../adr/0005-rust-worker-as-a-verified-port.md)). `src/serve.rs` mirrors `worker.py`'s
run loop and `src/factory.rs` optopus-py's heuristic arguments, so a seeded run gives the same
result in both workers; `tests/test_rust_worker.py` checks it against the Python models.
`GUIDE.md` is what the agent reads when it ports a model; keep it in step with the library.

## Decisions

Read the ADR before changing a boundary it describes:

| ADR | Decision |
|---|---|
| [0001](../adr/0001-solver-behind-a-process-boundary.md) | the solver runs behind a process boundary, Python first |
| [0002](../adr/0002-build-optopus-from-the-sibling-checkout.md) | build optopus from the sibling optopus-py checkout (since replaced by 0008) |
| [0003](../adr/0003-agent-on-claude-code-login.md) | the agent runs through the Agent SDK on the Claude Code login |
| [0004](../adr/0004-import-uploads-into-the-instance.md) | uploaded files are imported into `instance.json` |
| [0005](../adr/0005-rust-worker-as-a-verified-port.md) | a Rust worker is a per-project port, verified before it runs |
| [0006](../adr/0006-python-worker-progress-through-on-improvement.md) | the Python worker reports progress through `on_improvement` |
| [0007](../adr/0007-share-a-project-as-a-zip.md) | a project is shared as a zip, without the agent's session |
| [0008](../adr/0008-depend-on-a-pinned-optopus-py-commit.md) | depend on a pinned optopus-py commit and fetch its docs |
| [0009](../adr/0009-package-a-revision-as-an-app.md) | a revision is packaged as an app that runs without the agent |
| [0010](../adr/0010-deliver-an-app-as-a-docker-image.md) | a packaged app is delivered as a Docker image |
