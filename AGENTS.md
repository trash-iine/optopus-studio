# Repository guidelines

optopus studio: a chat on the left drives an agent that models and solves optimization tasks with
optopus (the Python bindings in ../optopus-py); a canvas on the right shows the result.
`README.md` is the source for setup and usage; this file is a digest for coding agents.

## Layout

- `src/optopus_studio/protocol.py` — every contract (worker protocol, `ViewSpec`, WebSocket
  events). Change it first, then run `uv run python -m optopus_studio.schema` and
  `npm run gen:types` in `frontend/`; `tests/test_schema.py` fails until both are done.
- `worker.py` (solver process), `viewer.py` (runs a project's `view.py`), `runner.py` (starts
  both), `projects.py` (files, revisions and uploads on disk), `tables.py` (reading uploaded
  CSV/TSV/Excel/JSON), `agent.py` (Agent SDK session, tools and system prompt), `app.py` (FastAPI +
  WebSocket), `cli.py` (entry point).
- `frontend/` — React + Vite + ECharts. `src/generated/` is generated; never edit it.
  Colors come from `src/theme.ts` (the dataviz reference palette): assign categorical slots in
  order, never cycle; past eight, use the muted ink and a label.
- `workers/rust/` — the Rust worker library a project's `rust/main.rs` links (ADR 0005);
  `src/serve.rs` mirrors `worker.py`'s run loop and `src/factory.rs` optopus-py's heuristic
  arguments, so a seeded built-in run matches the Python worker exactly. `GUIDE.md` is what the
  agent reads; keep it in step with the library. `rust.py` builds ports, `verify.py` checks them.
- `examples/` — complete projects; the tests solve them and check the views against the core.
- `docs/adr/` — decisions. Read them before changing the boundaries they describe.

## Rules

- Generated code (a project's `model.py` / `view.py`) only ever runs in a subprocess with a
  timeout, never in the server process.
- The agent has no built-in Claude Code tools; it acts only through the tools in `agent.py`.
- The agent signs in with the Claude Code login; do not add API-key handling (ADR 0003).
- Uploaded data reaches a model only through `instance.json` (ADR 0004); never let `model.py`
  read `uploads/`, or a revision stops being reproducible on its own.
- English in code, comments and docs; the chat itself follows the user's language.
- Python: Ruff, `line-length = 100`. Tests: tiny instances, hermetic, under `tmp_path`.
- A change to the worker protocol touches `protocol.py`, `worker.py` and `workers/rust/src`
  together; `tests/test_rust_worker.py` checks the Rust side against the Python models.
- Before committing: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `npm test && npm run typecheck` in `frontend/`, and `cargo fmt --check` and
  `cargo clippy --all-targets -- -D warnings` in `workers/rust/`.
