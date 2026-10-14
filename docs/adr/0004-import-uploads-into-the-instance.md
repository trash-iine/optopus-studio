# 0004. Import uploaded files into instance.json

- Status: Accepted
- Date: 2026-10-14

## Context

Users bring their own data as CSV or Excel files, often too large to pass through the agent's
context, and every revision should be reproducible from its own files (ADR 0001).

## Options

1. The agent reads the file and writes its rows into instance.json with write_file.
2. model.py opens the uploaded file itself.
3. A tool parses the file and stores its rows in instance.json under a key the agent picks.

## Decision

Option 3. Uploads are stored under the project's `uploads/`. The agent calls `preview_upload` to
see the shape, columns and first rows, then `import_upload(name, key)`, which writes the table into
`instance.json` as a list of records keyed by the header (numbers parsed, empty cells null; JSON as
it is). `model.py` and `view.py` read `instance[key]`.

The first option costs tokens and time in proportion to the data and lets the model mistype it.
The second makes a revision depend on a file outside it, which a later upload of the same name
would silently change.

## Consequences

- A revision freezes its data with it; re-running it later, or in another worker, needs nothing
  else.
- instance.json grows with the data. `read_file` cuts long files, and the system prompt tells the
  agent to rely on the import summaries rather than reading the data back.
- Only tables and JSON are read (`.csv`, `.tsv`, `.txt`, `.xlsx`, `.json`, up to 20 MiB).
