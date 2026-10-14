# 0008. Depend on a pinned optopus-py commit, and fetch its docs

- Status: Accepted
- Date: 2026-10-14
- Supersedes: 0002

## Context

ADR 0002 built optopus from a sibling optopus-py checkout because `RunResult.trajectory` and
`on_improvement` were on unmerged branches. Both are on optopus-py's `main` now (#33, #34), but
not in a release. A clone of this repository should build on its own, and the code it builds
should not change under it.

Three things came from the checkout: the Python package, the Rust core the Rust worker links
(its `vendor/optopus`), and the user guide the agent reads (`docs/source`), which the wheel does
not ship.

## Options

1. A git dependency on optopus-py's `main` branch.
2. A git dependency on a commit of optopus-py's `main`; the Rust worker on the optopus commit
   that one vendors; the docs fetched from GitHub at the installed commit.
3. As 2, with the docs copied into this repository.

## Decision

Option 2.

- `pyproject.toml`: `optopus = { git = "https://github.com/trash-iine/optopus-py", rev = <sha> }`.
  `uv sync` builds it, which needs a Rust toolchain.
- `workers/rust/Cargo.toml`: `optopus = { git = "https://github.com/trash-iine/optopus", rev =
  <the sha optopus-py's vendor/optopus points at> }`, so a port runs the search the Python worker
  runs and `verify_rust`'s exact comparison stays meaningful (ADR 0005).
- `docs.py` reads the commit uv recorded in the installed package's `direct_url.json`, fetches a
  page from `raw.githubusercontent.com` at that commit the first time it is read, and keeps it
  under `<home>/docs/<commit>/`. `OPTOPUS_STUDIO_DOCS` still points at a local `docs/source`.

A branch (option 1) would change what builds without a commit here, and `uv.lock` would hide that
until the next `uv lock --upgrade`. Copying the docs (option 3) would need a sync step and could
drift from the code; fetching them at the installed commit cannot.

## Consequences

- The two pins move together. `tests/test_dependencies.py` checks that the Rust pin is the core
  the Python pin vendors, and `tests/test_agent_tools.py` that every page the agent reads exists at
  that commit; both read from GitHub and run with `uv run pytest -m network`.
- The agent needs GitHub the first time it reads each page; offline, `read_docs` says so and
  points to `api_help`, which reads the installed docstrings.
- Trying an unmerged optopus-py change means a local `path` source and `OPTOPUS_STUDIO_DOCS`,
  not committed.
- When optopus-py tags a release with these features, the pins can move to the tag.
