# optopus studio

Chat-driven optimization on [optopus](https://github.com/trash-iine/optopus-py). Describe a task
in the chat on the left; an agent models it, solves it with optopus, and draws the result on the
canvas on the right. Ask for a change and it re-models, re-solves and redraws, keeping every solve
as a revision you can go back to.

Optimization is the point: the canvas exists to make a result clear (routes on a map, schedules as
a Gantt chart, the convergence of every run).

- **Your data**: attach CSV, TSV, Excel or JSON files in the chat (the + button). The agent previews
  them and imports the rows into the project, then models on them.
- **Comparing heuristics**: a solve can run several heuristics with the same seeds; the canvas
  overlays their convergence and the Runs tab tabulates best, mean and worst per heuristic.
- **Comparing revisions**: the Compare tab puts two revisions side by side, with the change in the
  best objective, the headline numbers, both convergence curves and a diff of the files.
- **Problems of your own**: when no built-in problem or `Formula` fits (an objective that is a
  maximum, a lookup, a simulation), the agent writes the problem in Python.
- **Speeding up with Rust**: a problem written in Python can be ported to Rust (the "Port to
  Rust" button, or just ask). The agent writes `rust/main.rs`, the studio builds it, checks it
  against the Python model with the same seeds, and switches the worker once it passes.
- **Live progress**: while a solve runs, the canvas shows each run's best so far, from either
  worker (`docs/adr/0006`).

## Quick start

You need git, [uv](https://docs.astral.sh/uv/), a Rust toolchain (1.88+), Node 24, and an agent
signed in: [Claude Code](https://docs.claude.com/en/docs/claude-code/setup) (`claude`, then
`/login`) or [Codex](https://developers.openai.com/codex/cli) 0.153+ (`codex login`). The agent
runs on that login, and each project chooses which one in the chat; API keys are ignored
(`docs/adr/0003`, `docs/adr/0012`).

```bash
uv sync                                   # builds optopus from optopus-py's pinned commit
(cd frontend && npm install && npm run build)
uv run optopus-studio                     # http://127.0.0.1:8765
```

First time? [Getting started](docs/guide/getting-started.md) goes through each step with a check,
and [Your first session](docs/guide/first-session.md) through the first model.

## Documentation

The [guide](docs/guide/README.md) ([日本語](docs/ja/guide/README.md)):

- [Getting started](docs/guide/getting-started.md): install, start, options, environment
  variables, where data is kept
- [Your first session](docs/guide/first-session.md): ask, read the result, change, compare, bring
  your own data
- [The interface](docs/guide/interface.md): every button, tab and banner
- [Projects, revisions and files](docs/guide/projects.md): what the agent writes, and the examples
- [Troubleshooting](docs/guide/troubleshooting.md): symptoms and fixes
- [Development](docs/guide/development.md): architecture, checks, changing the protocol, moving
  the optopus pin

## Sharing a project

**Export** in the header downloads the open project as one zip: the chat, every revision with its
result and view, and the attached files. A teammate opens it with **Import**, which adds it as a
new project; the project menu in the header switches between projects. Their agent starts a new
session that reads the conversation first, since the original one stays on the machine it ran on
(`docs/adr/0007`).

## Packaging a model as an app

When a model is ready for others, ask the agent to make it an app. It writes `app.json`: the
tables the app's user may replace and the settings they may change, each checked before a solve.
**Package**, above the canvas, downloads the selected revision as a zip (Safari unpacks it into
a folder, which works as well). From a checkout of this repository, without an agent or a login,
it runs with:

```bash
uv run optopus-studio app optopus-app-<project>-r<rev>.zip   # http://127.0.0.1:8766
```

The app shows the revision's own result first. Its user gives files, sets values and solves, and
the app says, row by row, what keeps a file from being solved. Anything else about the model is
changed in the studio and packaged again (`docs/adr/0009`).

When a case goes wrong, or its result is not what its user expected, they write it in **Notes
for the developer**, and **Export case** downloads the case's files, settings, problems, result
and note as a zip. Attach it with **+** in the studio's chat: the agent reads it (`read_case`),
reproduces it (`load_case`), and tells whether the data or the model is at fault, or which
requirement the note points to. A fixed model reaches the app's users when its revision is
packaged again.

## Handing an app to a customer

For someone without this repository, build the package into a Docker image. It holds the app,
the solver, the built Rust port if the model has one, and no agent (`docs/adr/0010`). Building
needs Docker running:

```bash
uv run optopus-studio image optopus-app-<project>-r<rev>.zip --save app-r<rev>.tar
```

The image is tagged `optopus-app-<project>:r<rev>` (`--tag` changes it) and built for
`linux/amd64` (`--platform` changes it), which Docker Desktop runs on Windows, macOS and Linux.
On Apple Silicon this builds optopus under emulation and takes about ten minutes; the tar is
about 60 MB. Before it is
done, the image solves the packaged data once (`--no-test` skips this).

The customer needs only Docker:

```bash
docker load -i app-r<rev>.tar
docker run -d -p 127.0.0.1:8766:8766 -v optopus-app-data:/data optopus-app-<project>:r<rev>
# then open http://127.0.0.1:8766
```

Their cases live in the `optopus-app-data` volume, so a newer image started on the same volume
keeps them. They send exported cases back as files; nothing leaves their machine otherwise.

## How it fits together

```
browser (React)  <-- WebSocket: ServerEvent / ClientEvent -->  backend (FastAPI, Agent SDK)
                                                                  |  stdin/stdout JSON Lines:
                                                                  |  SolveRequest -> WorkerEvent
                                                                  v
                                                          solver worker (a subprocess)
```

A project is the files the agent writes (`instance.json`, `model.py`, `solve.json`, `view.py`, and
optionally `rust/main.rs` and `app.json`), frozen into a revision on every solve. The contracts
live in `src/optopus_studio/protocol.py`; the decisions behind the design are in `docs/adr/`.
`examples/` holds four complete projects. [Development](docs/guide/development.md) has the details,
the checks to run before committing, and how to move to a newer optopus-py.

## License

MIT OR Apache-2.0, like optopus.
