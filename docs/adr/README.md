# Decisions

Each record says what was decided about the studio's design, in which context, and what follows
from it. Read the one that describes a boundary before changing that boundary.
[Development](../guide/development.md) says how the parts they describe fit together.

| ADR | Decision |
|---|---|
| [0001](0001-solver-behind-a-process-boundary.md) | Keep the solver behind a process boundary, Python first |
| [0002](0002-build-optopus-from-the-sibling-checkout.md) | Build optopus from the sibling optopus-py checkout for now |
| [0003](0003-agent-on-claude-code-login.md) | Run the agent through the Claude Agent SDK on the Claude Code login |
| [0004](0004-import-uploads-into-the-instance.md) | Import uploaded files into instance.json |
| [0005](0005-rust-worker-as-a-verified-port.md) | A Rust worker is a per-project port, verified before it runs |
| [0006](0006-python-worker-progress-through-on-improvement.md) | The Python worker reports progress through optopus-py's on_improvement |
| [0007](0007-share-a-project-as-a-zip.md) | Share a project as a zip, without the agent's session |
| [0008](0008-depend-on-a-pinned-optopus-py-commit.md) | Depend on a pinned optopus-py commit, and fetch its docs |
| [0009](0009-package-a-revision-as-an-app.md) | Package a revision as an app that runs without the agent |
| [0010](0010-deliver-an-app-as-a-docker-image.md) | Deliver a packaged app as a Docker image |
| [0011](0011-start-from-a-solution-in-the-instance.md) | Start a solve from a solution kept in instance.json |
| [0012](0012-run-the-agent-on-claude-code-or-codex.md) | Run the agent on Claude Code or Codex, chosen per project |
| [0013](0013-improve-against-a-benchmark-of-instances.md) | Judge a change of the algorithm on a benchmark of instances |
| [0014](0014-tune-settings-by-racing.md) | Tune a heuristic's settings by racing on the benchmark |
| [0015](0015-profile-heuristics-before-composing-them.md) | Profile heuristics on the benchmark before composing them |
| [0016](0016-let-the-agent-search-the-web-when-allowed.md) | Let the agent search the web when a project allows it |
| [0017](0017-choose-the-model-from-the-agents-own-list.md) | Choose the agent's model and effort from the agent's own list |
| [0018](0018-race-saved-candidates-against-the-incumbent.md) | Race saved candidates against the incumbent, and keep a ledger of them |
| [0019](0019-drive-the-improvement-loop-from-the-studio.md) | Drive the improvement loop from the studio, as a campaign |
| [0020](0020-diagnose-the-search-for-the-next-hypothesis.md) | Diagnose the search, as evidence for the next hypothesis |
| [0021](0021-build-compositions-from-a-grammar-of-leaves.md) | Build compositions from a grammar of leaves, and race them |
