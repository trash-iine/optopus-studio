# The interface

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ optopus studio  [project ▾] ●            Import  Export  New project  [System ▾]     │  header
├───────────────────────────┬──────────────────────────────────────────────────────────┤
│                           │ Result  Model  Runs  Compare  Improve  Revision [3 ▾]    │
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
  send another message until it has finished or stopped. During an improvement campaign Stop
  ends the campaign: the studio still checks what was adopted on the validation instances, and
  a second Stop skips that too.
- **studio: lines**: the studio's own messages to the agent during an improvement campaign
  ([ADR 0019](../adr/0019-drive-the-improvement-loop-from-the-studio.md)): each round's brief
  and the campaign's end. Click one to read it.
- **▸ lines**: each tool the agent uses, with the file or page it acts on. `working…` means it is
  thinking.
- **Red text** under the messages is an error from the agent or the server, for example "the agent
  stopped: …". See [Troubleshooting](troubleshooting.md).
- **Agent**: the agent this project's chat runs on, Claude or Codex. Switching is possible while
  the agent is idle; the other agent reads the conversation so far with its next message, and
  continues from the project's files. An agent that cannot run on this machine is marked
  "(unavailable)"; hover over it for the reason.
- **Model** and **Effort**: the model the agent runs on in this project, and how much it
  reasons, chosen from the list the agent itself gives
  ([ADR 0017](../adr/0017-choose-the-model-from-the-agents-own-list.md)), so a model it adds shows
  up after a restart. **Default** runs on the model set by `OPTOPUS_STUDIO_CLAUDE_MODEL` /
  `OPTOPUS_STUDIO_CODEX_MODEL`, else the agent's own default. Effort is shown only for a model
  that takes one. Each agent keeps its own choice; it can be changed while the agent is idle, and
  the session carries on. When the agent cannot list its models, "Model: default" stands instead;
  hover over it for the reason.
- **Web search**: lets the agent search and read the web, for methods that work on problems like
  yours ([ADR 0016](../adr/0016-let-the-agent-search-the-web-when-allowed.md)). It is off for a new
  or imported project, and can be changed while the agent is idle. Searches show as
  `web_search` and `web_fetch` lines.

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
`app.json` and `rust/main.rs` when they exist, with Python, JSON and Rust in syntax colors (a file
over 200,000 characters, such as a large uploaded instance, is shown plain). They are read-only
here; ask the agent for changes.
[Projects, revisions and files](projects.md) explains each.

### Runs

The heuristic card again, then a table with one row per run: best and initial objective,
iterations, the iteration and time at which the best was found, total time, and seed; a
`BranchAndBound` solve adds a bound column, "optimal" for a run that proved its best optimal and
otherwise the best objective a solution it had not ruled out could reach. The best run is
highlighted. When the solve compared several heuristics, a second table gives each one's
best, mean and worst result and mean times.

### Compare

Two revisions side by side; it needs at least two. The menus at the top choose them. At first
the selected revision is compared with the last earlier one solved from another model, data or
settings: a revision that changes only `view.py` or `app.json` solves the same as the one before
it, so it is compared past it, and a line above the cards names the revisions skipped. When
every earlier revision is solved the same, it is the one before.

- **Best objective**: the change between them, marked better, worse or the same, with what a
  `BranchAndBound` revision proved next to its value.
- **Headline numbers**: the numbers of both revisions' views, row by row.
- **Convergence of the best runs**: one curve per revision.
- **Changed files**: a line diff of every file that differs. "The files are the same; only the
  runs differ" means the same model was solved again.

### Improve

What the agent did to improve the search
([Improving the algorithm](projects.md#improving-the-algorithm)); empty until it builds a
benchmark. It updates as the agent works, with a progress bar while an evaluation, a race, a tuning
or a profile runs.

- **Benchmark**: the runs per instance and each run's budget, and the train and validation
  instances, and the test instances when there are any; hover one for where it came from and
  the best objective known on it.
- **Campaign**: the latest improvement campaign: whether it runs or why it ended, the round and
  the minutes spent, the incumbent, and at its end whether the result was kept, with its
  verdict and gain on validation and on test.
- **Hypotheses**: the ledger of the changes the agent saved as candidates
  ([ADR 0018](../adr/0018-race-saved-candidates-against-the-incumbent.md)), newest first: the
  kind of change, the hypothesis (hover it for what suggested it), the revision it changes, the
  race it ran in, what became of it (the revision it was adopted as, or its verdict), its gain,
  and the lesson the agent drew. The heading counts the kinds tried.
- **Heuristics profiled**: every profile of several heuristics on the benchmark, newest first. Each
  table lists the heuristics, the best first, with:
  - the mean rank and the instances won;
  - the gap of the best so far to the best any of them found, at 10%, 25%, 50% and 100% of the
    budget. The leader at each share is in bold, so a heuristic that leads early and another that
    ends best stand out;
  - how far into the budget each found its best;
  - iterations per second, and the moves accepted.

  The readings under the table are the compositions the profile suggests.
- **Changes judged**: every evaluation, newest first: the agent's note of what changed, the
  revision it was compared with, the split, the verdict, the mean gain (+ is better), how many
  instances got better, stayed and got worse, and the revision the change was solved into ("—"
  when it was undone). Click a row for each instance's mean objectives, or for why a change was
  rejected or failed.
- **Settings tuned**: every tuning: the heuristic and revision ("RW or SA" when it chose among
  several), the runs made of the budget, the settings raced, dropped and failed, the best ("the
  revision's own" when none beat it, prefixed by its heuristic when it chose), and the verdict of
  its check on validation. The signs the race showed are listed under its row.
