# optopus studio

Chat-driven optimization on [optopus](https://github.com/trash-iine/optopus-py). Describe a task
in the chat on the left; an agent models it, solves it with optopus, and draws the result on the
canvas on the right. Ask for a change and it re-models, re-solves and redraws, keeping every solve
as a revision you can go back to.

Optimization is the point: the canvas exists to make a result clear (routes on a map, schedules as
a Gantt chart, the convergence of every run).

## Requirements

- [uv](https://docs.astral.sh/uv/) and Python 3.12+
- Node 24 for the frontend (`mise.toml` pins it; `mise install` provides it)
- Claude Code, signed in (`claude` then `/login`). The agent runs on that login through the
  Claude Agent SDK; `ANTHROPIC_API_KEY` is ignored (see `docs/adr/0003`).
- A checkout of [optopus-py](https://github.com/trash-iine/optopus-py) next to this one
  (`../optopus-py`), until a release carries `RunResult.trajectory` (see `docs/adr/0002`). Its
  `docs/source` is also what the agent reads; `OPTOPUS_STUDIO_DOCS` points elsewhere.

## Run

```bash
uv sync                                   # builds optopus from ../optopus-py the first time
(cd frontend && npm install && npm run build)
uv run optopus-studio                     # http://127.0.0.1:8765
```

For frontend work, run `npm run dev` in `frontend/` as well and open http://127.0.0.1:5173; it
forwards `/api` to the backend.

| Variable | Default | Meaning |
|---|---|---|
| `OPTOPUS_STUDIO_HOME` | `~/.optopus-studio` | where projects and their revisions are stored |
| `OPTOPUS_STUDIO_MODEL` | Claude Code's default | the model the agent runs on |
| `OPTOPUS_STUDIO_DOCS` | `../optopus-py/docs/source` | the optopus-py user guide the agent reads |
| `OPTOPUS_STUDIO_WORKER` | the Python worker | the solver command, e.g. a Rust worker |
| `OPTOPUS_STUDIO_SOLVE_TIMEOUT` | from the stop condition | seconds before a solve is killed |

## How it fits together

```
browser (React)  <-- WebSocket: ServerEvent / ClientEvent -->  backend (FastAPI, Agent SDK)
                                                                  |  stdin/stdout JSON Lines:
                                                                  |  SolveRequest -> WorkerEvent
                                                                  v
                                                          solver worker (a subprocess)
```

A project is four files the agent writes, frozen into a revision on every solve:

| File | Runs in | Says |
|---|---|---|
| `instance.json` | — | the data |
| `model.py` | the worker | `build(instance)` returns an optopus problem; optional `encode_solution` makes the solution JSON |
| `solve.json` | the worker | the heuristic as `{"kind": ..., **arguments}`, runs, seed |
| `view.py` | the backend's viewer process | `to_view(instance, result)` returns a `ViewSpec` for the canvas |

The three contracts live in `src/optopus_studio/protocol.py`, the single source of the schemas in
`schema/` and of the TypeScript types in `frontend/src/generated/`. Because the worker only
speaks `SolveRequest` / `WorkerEvent` and the canvas only reads `ViewSpec`, a solver written in
Rust replaces the Python worker without touching the GUI (`docs/adr/0001`). `examples/` holds three
complete projects (TSP, job shop, a knapsack as a `Formula`).

## Develop

```bash
uv run pytest                      # backend: worker, runner, projects, tools, server
uv run ruff check . && uv run ruff format --check .
(cd frontend && npm test && npm run typecheck)
```

After changing `protocol.py`, regenerate the schemas and types:

```bash
uv run python -m optopus_studio.schema && (cd frontend && npm run gen:types)
```

## License

MIT OR Apache-2.0, like optopus.
