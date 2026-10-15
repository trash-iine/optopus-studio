# Getting started

This page installs the studio and opens it in your browser. Each step ends with a check; if a
check fails, [Troubleshooting](troubleshooting.md) has the usual causes.

The studio runs on your own machine (macOS, Linux, or Windows through WSL). It needs a network
connection to GitHub while it installs and while the agent reads optopus's documentation.

## 1. Install the tools

| Tool | Why | Check |
|---|---|---|
| [git](https://git-scm.com/) | to get this repository; uv also fetches optopus with it | `git --version` |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | installs Python and the studio's packages | `uv --version` |
| Python 3.12+ | runs the studio | `uv python find 3.12` (uv downloads it in step 3 if it is missing) |
| [Rust](https://rustup.rs/) 1.88+ | optopus is compiled from source, and so are Rust ports of models | `cargo --version` |
| Node 24 | builds the web page | `node --version` |
| [Claude Code](https://docs.claude.com/en/docs/claude-code/setup) | the agent runs on its login | `claude --version` |

For Node, the repository pins version 24 in `mise.toml`: with [mise](https://mise.jdx.dev/),
`mise install` in the checkout provides it. Any other Node 24 works as well.

## 2. Sign in to Claude Code

The agent in the chat is Claude, and it uses your Claude Code login. Sign in once:

```bash
claude        # then type /login and follow the browser prompt; /exit when done
```

Check: `claude` starts without asking you to log in. An `ANTHROPIC_API_KEY` in your environment is
not used: the studio removes it at start so the login is always the one in use
([ADR 0003](../adr/0003-agent-on-claude-code-login.md)).

## 3. Install the studio

```bash
git clone https://github.com/trash-iine/optopus-studio.git
cd optopus-studio
uv sync
```

`uv sync` creates `.venv/`, installs Python 3.12 there if needed, and compiles optopus from a
pinned commit of [optopus-py](https://github.com/trash-iine/optopus-py). The first run compiles
Rust and takes a few minutes; later runs are quick.

Check: `uv run python -c "import optopus; print('ok')"` prints `ok`.

## 4. Build the web page

```bash
cd frontend
npm install
npm run build
cd ..
```

Check: `frontend/dist/index.html` exists. Without it the server still starts, but the page at
its address only says `{"detail":"Not Found"}`.

Build again after you pull changes to `frontend/`.

## 5. Start the studio

```bash
uv run optopus-studio
```

Open <http://127.0.0.1:8765>. You should see:

- the header: **optopus studio**, a project menu, a small dot that is green while the page is
  connected to the server, and **Import**, **Export**, **New project**;
- the chat on the left, with a short prompt and three example requests;
- the canvas on the right, saying "No result yet".

Stop the studio with `Ctrl+C` in the terminal. Your projects are kept; start it again to carry on.

Continue with [Your first session](first-session.md).

## Options

```bash
uv run optopus-studio --port 9000              # another port
uv run optopus-studio --host 0.0.0.0           # reachable from other machines (no login: trusted networks only)
uv run optopus-studio --reload                 # restart when the Python sources change (development)
```

| Variable | Default | Meaning |
|---|---|---|
| `OPTOPUS_STUDIO_HOME` | `~/.optopus-studio` | where projects and their revisions are stored |
| `OPTOPUS_STUDIO_MODEL` | Claude Code's default | the model the agent runs on |
| `OPTOPUS_STUDIO_DOCS` | fetched from GitHub | a `docs/source` of optopus-py for the agent to read instead |
| `OPTOPUS_STUDIO_WORKER` | the Python worker | the solver command, e.g. a Rust worker |
| `OPTOPUS_STUDIO_SOLVE_TIMEOUT` | from the stop condition | seconds before a solve is killed |
| `OPTOPUS_STUDIO_RUST_DIR` | `$OPTOPUS_STUDIO_HOME/rust` | where Rust ports are built and their binaries kept |

Without `OPTOPUS_STUDIO_SOLVE_TIMEOUT`, a solve is stopped after the time its runs may take by
their stop conditions plus 30 seconds (20 minutes at most), or after 300 seconds when a heuristic
has no time limit (`max_duration_secs`).

## Where your data is

Everything the studio keeps is under `OPTOPUS_STUDIO_HOME` (`~/.optopus-studio` by default):

```
~/.optopus-studio/
    projects/<id>/
        chat.jsonl      the conversation
        work/           the model files the agent is editing
        revs/<n>/       each solve: the files as solved, with result.json and view.json
        uploads/        files you attached in the chat
        cases/<id>/     cases attached from a packaged app
        meta.json       the agent's session, to resume the conversation
    docs/<commit>/      optopus-py documentation pages the agent has read
    rust/               Rust ports being built
```

To start over, stop the studio and delete a project's folder, or the whole directory. To keep
separate sets of projects, point `OPTOPUS_STUDIO_HOME` at another folder.

## Updating

```bash
git pull
uv sync
(cd frontend && npm install && npm run build)
```

Then start the studio again.
