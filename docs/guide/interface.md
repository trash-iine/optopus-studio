# The interface

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ optopus studio  [project ▾] ●            Import  Export  New project  [System ▾]     │  header
├───────────────────────────┬──────────────────────────────────────────────────────────┤
│                           │ Result  Model  Runs  Compare     Revision [3 (latest)▾]  │
│  you: ...                 │                                               Package    │
│  agent: ...               │ ┌──────────────────────────────────────────────────────┐ │
│  ▸ write_file model.py    │ │ views: map, Gantt chart, table, headline numbers ... │ │
│  ▸ run_solver             │ └──────────────────────────────────────────────────────┘ │
│                           │ ┌ Convergence ─────────────────────────────────────────┐ │
│                           │ └──────────────────────────────────────────────────────┘ │
│ [+] [message box] [Send]  │ ┌ Heuristic ───────────────────────────────────────────┐ │
│        chat               │                    canvas                                │
└───────────────────────────┴──────────────────────────────────────────────────────────┘
```

## Header

| Control | What it does |
|---|---|
| project menu | switches between projects. A project is named after its first message; one imported from a zip says "(imported)". The open project's id is also in the page address (`?project=<id>`), so a bookmark reopens it. |
| ● dot | green while the page is connected to the server, grey while it is not. The page reconnects by itself every second, for example after you restart the server. |
| **Import** | opens a project someone exported (a `.zip`) as a new project. |
| **Export** | downloads the open project as one `.zip`: chat, every revision with its result, and attached files. |
| **New project** | starts an empty project. Use one project per task; ask for changes within it. |
| theme menu | System, Light or Dark. |

## Chat (left)

- **Message box**: **Enter** sends, **Shift+Enter** starts a new line. While Japanese (or other
  IME) input is being converted, Enter confirms the conversion and does not send.
- **+**: attaches files: CSV, TSV, `.txt`, `.xlsx`, JSON (up to 20 MiB each), or a case `.zip`
  exported from a packaged app. Attached files show as chips above the box until you send; × removes
  one.
- **Send / Stop**: while the agent works the button is **Stop**, which interrupts it. You cannot
  send another message until it has finished or stopped.
- **▸ lines**: each tool the agent uses, with the file or page it acts on. `working…` means it is
  thinking.
- **Red text** under the messages is an error from the agent or the server, for example "the agent
  stopped: …". See [Troubleshooting](troubleshooting.md).

The conversation is kept with the project. Coming back to a project later resumes the same agent
session, so it remembers what was said.

## Canvas (right)

### Revision and Package

Every solve makes a revision, numbered from 1. The **Revision** menu shows any earlier one, with
its files, result and views; the newest is marked "(latest)". Selecting an older revision only
shows it: the agent always carries on from the latest files. To return to an earlier model, tell
the agent which change to undo.

**Package** downloads the selected revision as an app that runs without the agent. It needs the
revision to have an `app.json`; ask the agent to "make this an app" first. See the
[README](../../README.md#packaging-a-model-as-an-app).

### Result

What the selected revision gave, from top to bottom:

- **Status line** while a solve runs: "Solving revision N with the python worker: 2 / 3 runs,
  best so far …".
- **Banners**:
  - red, "The solve failed at …": the model raised an error; open *traceback* for details. The
    agent sees the same error and usually fixes it on its own.
  - yellow, "view.py failed": the solve worked but drawing it did not.
  - blue, "This problem is written in Python…" with **Port to Rust**: see
    [Your first session](first-session.md#8-when-a-python-model-is-slow).
- **Views**: what the agent chose to draw for this problem. The kinds are headline numbers, table,
  Gantt chart, route map, graph, bar chart, a text note, and, when none of those fits, a custom
  HTML page shown in a sandbox.
- **Convergence**: the best objective so far in each run, against time or iterations (the toggle
  on the chart). The title shows the optopus problem and the worker (python or rust), and, for a
  `BranchAndBound` solve, what the best run proved: "proven optimal", or the bound it reached and
  the gap to it.
- **Heuristic**: the search method and its parameters, the stop condition, the seed and the number
  of runs, and the key of `instance.json` the runs started from when they did not start at random.

### Model

The files of the selected revision: `model.py`, `view.py`, `instance.json`, `solve.json`, and
`app.json` and `rust/main.rs` when they exist. They are read-only here; ask the agent for changes.
[Projects, revisions and files](projects.md) explains each.

### Runs

The heuristic card again, then a table with one row per run: best and initial objective,
iterations, the iteration and time at which the best was found, total time, and seed; a
`BranchAndBound` solve adds a bound column, "optimal" for a run that proved its best optimal and
otherwise the best objective a solution it had not ruled out could reach. The best run is
highlighted. When the solve compared several heuristics, a second table gives each one's
best, mean and worst result and mean times.

### Compare

Two revisions side by side; it needs at least two. The menus at the top choose them (the selected
revision and the one before it at first).

- **Best objective**: the change between them, marked better, worse or the same, with what a
  `BranchAndBound` revision proved next to its value.
- **Headline numbers**: the numbers of both revisions' views, row by row.
- **Convergence of the best runs**: one curve per revision.
- **Changed files**: a line diff of every file that differs. "The files are the same; only the
  runs differ" means the same model was solved again.
