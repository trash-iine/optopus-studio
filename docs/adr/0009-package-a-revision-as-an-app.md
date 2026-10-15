# 0009. Package a revision as an app that runs without the agent

- Status: Accepted
- Date: 2026-10-14

## Context

After a few rounds of chat, a model is ready for other people: they have their own data and want
to solve it and see the result, without the agent and without changing the model. The model
will also keep improving in the studio, and when the app fails on someone's data, that data has
to reach the studio so the failure can be understood and fixed.

A revision already freezes everything a solve needs (ADR 0001): `model.py`, `view.py`,
`instance.json`, `solve.json`, and `rust/main.rs` for a port. What it lacks is a statement of
what an app's user may change: which data, in which shape, and which settings.

## Options

1. A generated, standalone program per model: its own server and page.
2. A package of the revision's files plus a declaration of its inputs, run by the studio's own
   code in a mode without the agent.
3. A static report of a revision's result.

## Decision

Option 2.

- **`app.json`** (`AppSpec` in `protocol.py`) is a project file the agent writes and the
  revision freezes. `inputs` are tables (read as `import_upload` reads uploads) that replace a
  key of `instance.json`, with the columns and types the model reads; an input not given keeps
  the packaged data. `parameters` set a value at `instance.<path>` or the solve's
  `max_duration_secs`, `runs` or `seed`; their default is the packaged value. Nothing else can
  change in the app: anything more is changed in the studio and packaged again.
- **`check_app`** checks `app.json` against the project, and the agent makes `model.py` raise
  `ValueError` with a message in the user's terms where the data breaks its assumptions.
- **Packaging** (`GET /api/projects/{id}/revisions/{rev}/package`, the Package button) writes the
  revision's files, its result as a sample, and a manifest (project, revision, time, optopus
  commit) into a zip. Only a revision whose `app.json` fits its files is packaged.
- **`optopus-studio app <package>`** serves the package with the same worker, viewer and canvas
  views, and no agent. Each set of inputs is a case, kept under
  `<home>/apps/<hash of the model files>/cases/`, so a revision packaged again finds its cases.
  The app checks every table against `app.json` before solving and lists what is wrong, by row.
- **Cases go back to the studio.** A case is exported as a zip (its files, parameters, problems
  and result) and attached in the studio's chat, where the agent can read it and reproduce it.

A program per model (option 1) would copy the solver, the views and the checks into every app,
and each would drift from the studio that improves the model. A report (option 3) cannot solve
new data.

## Consequences

- The person running an app needs this repository installed, as for the studio, but no Claude
  Code login; a Rust port is built on first use, which needs cargo.
- The views an app shows are the studio's; improving them improves every app on the next
  package.
- `app.json` is versioned with the model, so an app's inputs change only with a new package.
