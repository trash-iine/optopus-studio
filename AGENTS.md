# Repository guidelines

optopus studio: a chat on the left drives an agent that models and solves optimization tasks with
optopus (the Python bindings, trash-iine/optopus-py); a canvas on the right shows the result.
`README.md` and `docs/guide/` are the source for setup and usage; this file is a digest for
coding agents.

## Layout

- `src/optopus_studio/protocol.py` — every contract (worker protocol, `ViewSpec`, WebSocket
  events). Change it first, then run `uv run python -m optopus_studio.schema` and
  `npm run gen:types` in `frontend/`; `tests/test_schema.py` fails until both are done.
- `worker.py` (solver process), `viewer.py` (runs a project's `view.py`), `runner.py` (starts
  both), `projects.py` (files, revisions and uploads on disk), `tables.py` (reading uploaded
  CSV/TSV/Excel/JSON), `agent.py` (the agent's tools, system prompt and conversation),
  `agent_claude.py` / `agent_codex.py` (its session on Claude or Codex, ADR 0012, on the model
  and effort chosen from the agent's own list, ADR 0017), `app.py` (FastAPI +
  WebSocket), `cli.py` (entry point). `solving.py` turns a model's files into a solve for both the
  agent and apps; `apps.py` and `appserver.py` package a revision with its `app.json` and run it
  without the agent (ADR 0009); the frontend shows `components/AppMode.tsx` when `/api/mode`
  says "app". `image.py` and `docker/app.Dockerfile` build a package into a Docker image to hand
  over (ADR 0010). `frontend.py` serves the built frontend for both servers. `bench.py` judges a
  change of the algorithm on the project's benchmark of instances against a baseline revision,
  whose model re-scores the candidate's solutions (ADR 0013); `candidates.py` saves the work
  files as candidates with their hypotheses, races several against the incumbent at once and
  lets only a better one be adopted (ADR 0018); `generator.py` runs `generate.py`;
  `tune.py` races a heuristic's settings, or several heuristics', on the benchmark, as irace
  does, and reads the race for signs of what settings cannot fix (ADR 0014); `profiling.py` runs
  several heuristics on it and reads how each runs (who leads early, who ends best, who stalls)
  for compositions worth racing, and `guides/recipes.md`, the agent's `recipes` page, says which
  methods work on a kind of problem and how to compose them (ADR 0015).
- `frontend/` — React + Vite + ECharts. `src/generated/` is generated; never edit it.
  Colors come from `src/theme.ts` (the dataviz reference palette): assign categorical slots in
  order, never cycle; past eight, use the muted ink and a label.
- `workers/rust/` — the Rust worker library a project's `rust/main.rs` links (ADR 0005);
  `src/serve.rs` mirrors `worker.py`'s run loop and `src/factory.rs` optopus-py's heuristic
  arguments, so a seeded built-in run matches the Python worker exactly. `GUIDE.md` is what the
  agent reads; keep it in step with the library. `rust.py` builds ports, `verify.py` checks them.
- `examples/` — complete projects; the tests solve them and check the views against the core.
- `docs/adr/` — decisions. Read them before changing the boundaries they describe.
- `docs/guide/` — the user and contributor guide, linked from `README.md`. Keep it in step with
  changes to the UI, the CLI, error messages and the checks. `docs/ja/guide/` is its Japanese
  translation, page for page: change both together.

## Rules

- Generated code (a project's `model.py` / `view.py`) only ever runs in a subprocess with a
  timeout, never in the server process.
- The agent has no built-in Claude Code or Codex tools; it acts only through the tools in
  `agent.py`, which both backends get from `Tools.specs()`. The one exception is the backends'
  web search, and only in a project whose `web_search` switch is on (ADR 0016).
- The agent signs in with the Claude Code or Codex login; do not add API-key handling (ADR 0003,
  ADR 0012).
- The Agent SDK is in the `studio` dependency group, which an app's image leaves out: nothing an
  app runs (`appserver.py`, `apps.py` and what they import) may import `agent*.py` or `app.py`
  (ADR 0010; `tests/test_image.py` checks it).
- Uploaded data reaches a model only through `instance.json` (ADR 0004); never let `model.py`
  read `uploads/`, or a revision stops being reproducible on its own.
- English in code, comments and docs (the one exception: the translation in `docs/ja/`); the chat
  itself follows the user's language.
- Python: Ruff, `line-length = 100`. Tests: tiny instances, hermetic, under `tmp_path`.
- Every module, class and function in `src/` and `examples/`, private and nested ones too, has
  a Google-style docstring: a one-line summary, then `Args`, `Returns` (or `Yields`) and
  `Raises` where they apply, and `Attributes` for a dataclass. Ruff's `D` rules check the public
  ones. The models in `protocol.py` get a summary only: their docstrings and `Field`
  descriptions are the JSON Schemas' descriptions. So does `examples/workload/model.py`, which
  the agent reads whole as the model a Rust port mirrors (`rust_guide` in `agent.py`).
- A change to the worker protocol touches `protocol.py`, `worker.py` and `workers/rust/src`
  together; `tests/test_rust_worker.py` checks the Rust side against the Python models.
- optopus comes from a pinned optopus-py commit (`pyproject.toml`), and the Rust worker's core
  from the commit that one vendors (`workers/rust/Cargo.toml`); move them together and run
  `uv run pytest -m network` (docs/guide/development.md; docs/adr/0008).
- Before committing: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
  `npm test && npm run typecheck` in `frontend/`, and `cargo fmt --check` and
  `cargo clippy --all-targets -- -D warnings` in `workers/rust/`.
- CI (`.github/workflows/ci.yml`) runs all of these, `uv run pytest -m network`, and checks that
  `frontend/src/generated` matches the schemas.
