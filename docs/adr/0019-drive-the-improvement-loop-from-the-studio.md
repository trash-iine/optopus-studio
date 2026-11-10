# 0019. Drive the improvement loop from the studio, as a campaign

- Status: Accepted
- Date: 2026-11-10

## Context

ADR 0013 to 0018 give the agent a judge, a tuner, a profile, recipes, the web and a race of
candidates. The loop that joins them is the system prompt's: a numbered list the agent follows
inside one turn. That makes the loop the weakest part of improving the search on its own.

- **The agent decides alone when it has tried enough.** A turn ends when the agent stops calling
  tools, which in practice is after a few hypotheses, whatever budget the user gave.
- **The rules that protect the result are requests.** "Keep only what is better", "check the
  incumbent against the start on validation" and "restore the start if it does not hold" are
  sentences. Nothing happens when one is skipped.
- **Nothing outlives the turn but the records.** Where the loop stands (the incumbent, the rounds
  that brought nothing) is in the agent's context, which is cut as it grows.

The literature on designing heuristics with a language model agrees on what the loop itself
contributes: a model asked the same question many times without feedback barely improves, while
the plainest loop that keeps the best and goes on beats it with a fraction of the calls; and a
loop that stops on a few rounds without a gain is hurt most by rounds that test one idea.

## Options

1. A longer and stricter prompt.
2. A stop hook that sends the agent back to work. Claude Code has one; Codex does not.
3. The studio drives the rounds: it keeps the loop's state, gives the agent a turn per round
   with a brief of where things stand, and makes the final check itself.
4. The studio runs the whole search without the agent in the loop (a fixed evolutionary
   pipeline that calls the model for each candidate).

## Decision

Option 3: a *campaign* (`campaign.py`), driven by the agent's session (`agent.py`).

- **Starting**: the agent calls `improve_start` with a budget of rounds, minutes or both, after
  it built the benchmark and solved the incumbent. A campaign needs train and validation
  instances, at least five paired runs on validation (below that a signed-rank test cannot say
  "better" at all), and the work files to be a revision with one heuristic.
- **State**: `bench/campaign.json` holds the revision it started from, the incumbent, the budget,
  the rounds in a row that brought nothing, and a line per round.
- **A round is a turn.** After each turn the session asks the campaign what follows. While it
  runs, that is the next round's *brief*, sent to the agent as a message marked `[studio]` and
  shown in the chat as the studio's: the budget left, the incumbent, the ledger (ADR 0018) with
  the families not tried, the latest profile's readings and tuning's signs, and what a round
  is. The brief states where things stand and leaves the method to the agent. It adds two
  hints the records support: choose the structure first when nothing was profiled, and tune
  first when the incumbent's structure changed and was not tuned since. Both backends take a
  turn the same way, so nothing here depends on one of them (ADR 0012).
- **The incumbent moves on evidence only**: to the revision a candidate was adopted as, or to
  one holding the files of a change judged better against the incumbent and then solved (an
  evaluation, or a tuning's check). The campaign reads this from the records after each round.
- **Ending** is the studio's decision: the rounds or minutes are spent, three rounds in a row
  brought no new incumbent, or the user pressed Stop.
- **The final check** is the studio's too. It evaluates the incumbent against the starting
  revision on validation. On "better" the work files become the incumbent's, and the result is
  also measured on the test split when there is one. On anything else they become the starting
  revision's again. Then the agent gets one last turn, with the outcome, to tell the user.
- **Stop** ends the turn and the campaign, and the final check still runs, so what was adopted is
  not left unchecked; a second Stop ends that too and leaves the files as they are. An agent
  that fails mid-campaign ends it where it is, and a studio that starts again does not take up a
  campaign left under way.

The first option is what there was. The second works on one backend only, and still leaves the
final check to the agent. The fourth gives up what the agent is good at here, which is reading
a profile or an instance line and deciding what to try: the studio would need a fixed set of
mutation prompts, and recent comparisons find that the less such machinery a loop has, the more
of the model's ability reaches the result.

## Consequences

- A campaign costs what its rounds cost, and the user sets that. The minutes are checked between
  rounds, so a round under way finishes.
- The GUI hears one `turn_end` for a whole campaign, so the chat stays busy until it ends. Each
  brief arrives as a `studio_message`, and the Improve tab shows the campaign from
  `BenchState.campaign`.
- Validation is read once per campaign by the final check, besides each tuning's own check. The
  test split is read only there.
- The prompt keeps how to work within a round, which also serves a user who asks for one change.
- Not done: there is no button that starts a campaign; the user asks in the chat. A campaign
  does not end early when the incumbent is close to a bound, since the studio has none
  (ADR 0014).
