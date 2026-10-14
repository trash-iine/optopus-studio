# 0002. Build optopus from the sibling optopus-py checkout for now

- Status: Superseded by 0008
- Date: 2026-10-14

## Context

The convergence chart needs `RunResult.trajectory`, added in trash-iine/optopus-py#33 and not in
a release yet. The agent also reads the optopus-py user guide (`docs/source`), which the wheel
does not ship.

## Options

1. A git dependency on the feature branch.
2. A path dependency on `../optopus-py`.
3. Vendor optopus-py as a submodule.

## Decision

Option 2, `[tool.uv.sources] optopus = { path = "../optopus-py" }`, with the docs read from the
same checkout (`OPTOPUS_STUDIO_DOCS` overrides). It builds whatever the checkout has, so a change
to the bindings is tried here without a release, and it needs no nested submodules.

## Consequences

- A clone of this repository alone does not build; the README says to put optopus-py beside it.
- Once a tagged release carries `trajectory`, switch to a git or index dependency pinned to that
  tag, and supersede this record.
