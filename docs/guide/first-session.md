# Your first session

This page walks through one project: ask for a model, read the result, change it, compare the two
versions, then bring in your own data. It assumes the studio is running
([Getting started](getting-started.md)).

## 1. Ask for something small

In an empty project the chat shows three example requests (in Japanese); clicking one puts it in
the message box. You can write in any language, and the agent answers in yours. For example:

> Find the shortest tour through 15 cities.

Press **Enter** to send (**Shift+Enter** starts a new line). The Enter that confirms Japanese or
other IME input does not send.

## 2. Watch the agent work

While the agent works, the **Send** button becomes **Stop**, and the chat shows each step as a
grey line starting with ▸, for example:

```
▸ read_docs problems         reads optopus's documentation
▸ api_help Tsp               looks up an exact constructor
▸ write_file model.py        writes one of the project's files
▸ check_model                builds the model and tries each heuristic for up to 2 seconds
▸ run_solver                 solves, and makes a revision
```

When something that changes the model is unclear, the agent asks one short question instead of
guessing; answer it in the chat. When you give no data, it makes up a small instance and says so.

A first model usually takes a minute or two; the solve itself is kept to about ten seconds unless
you ask for longer. **Stop** interrupts the agent; what it already wrote stays.

## 3. Read the result

When `run_solver` finishes, the canvas shows revision 1 on the **Result** tab:

- **the views** the agent wrote for this problem: here a map of the tour and the headline numbers
  (its length). A schedule shows as a Gantt chart, a choice as a table, and so on.
- **Convergence**: the best objective found so far against time (or iterations, with the toggle
  on the chart), one curve per run. A curve still improving at its end means more search would
  help.
- **Heuristic**: how it searched, such as `SimulatedAnnealing` with its parameters, the stop
  condition, the seed and the number of runs.

The agent's reply sums up the result in a few lines and suggests what to change next. The
**Model** tab shows the files behind it, and **Runs** a table of every run (best, initial,
iterations, time). See [The interface](interface.md) for every part of the screen.

## 4. Ask for a change

Ask for anything about the task, the data or the search, in plain words:

> Make it 30 cities, and list the visiting order in a table.

> Let it run for 5 seconds per run, with 5 runs.

The agent changes only what the request needs and solves again, which makes revision 2. Every
solve is kept: the **Revision** menu above the canvas goes back to any of them.

## 5. Compare two revisions

Open **Compare**. It puts two revisions side by side: the change in the best objective (marked
better, worse or the same), the headline numbers of both, the convergence of each one's best run,
and a diff of the files.
Pick other revisions with the two menus at its top.

## 6. Compare heuristics

When you wonder which search method suits the problem, ask:

> Compare simulated annealing, tabu search and late acceptance hill climbing, 5 runs each.

They run with the same seeds, so each starts from the same solutions. The Convergence chart
overlays them, and **Runs** adds a table with the best, mean and worst result and the time of each
heuristic.

## 7. Use your own data

Click **+** next to the message box and choose a file: CSV, TSV, `.txt`, Excel (`.xlsx`) or JSON,
up to 20 MiB each. The file appears as a chip above the box; write what it is and send:

> These are our delivery addresses with their demand. Plan routes for 3 trucks of capacity 100.

The agent previews the columns and first rows, asks if a column's meaning or unit is unclear, and
imports the rows into the project's `instance.json`. From then on the data is part of every
revision, so an old revision still solves the same way after the file changes
([ADR 0004](../adr/0004-import-uploads-into-the-instance.md)).

## 8. When a Python model is slow

When the problem has no built-in form in optopus, the agent writes it in Python. Then the Result
tab shows a banner, "This problem is written in Python, so every move runs through Python", with a
**Port to Rust** button. It asks the agent to write the same model in Rust, check it against the
Python one with the same seeds, and switch to it once it matches. It is worth it when the search
needs many more iterations than the Python model manages in the time you accept; a built-in
problem already runs in Rust.

## Tips for good requests

- Say **what is decided**, **what is better** (shorter, cheaper, fewer late jobs) and **what must
  hold** (capacities, time windows, precedence). Say which rules may be broken at a cost.
- Give the **size** you care about. Start small to check the model, then scale up.
- Say what you want to **see**: "show each truck's route on a map", "a Gantt chart per machine",
  "list the jobs that are late".
- One change per message makes the revisions easy to compare.
- The agent can only act through the studio: it writes the project's files and solves. It does not
  browse the web or read files on your machine other than the ones you attach.

## What next

- [Projects, revisions and files](projects.md): what the agent wrote, and how to share a project
  or turn it into an app.
- The four complete projects in [`examples/`](../../examples/) show what a finished model looks
  like.
