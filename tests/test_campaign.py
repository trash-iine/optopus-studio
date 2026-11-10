"""An improvement campaign, driven by the studio through a scripted agent (campaign.py)."""

import asyncio
import json

import pytest

from optopus_studio import agent, bench, campaign, candidates
from optopus_studio.agent import AgentSession, TurnResult
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import BenchChanged, FilesChanged, StudioMessage, TurnEnd
from tests.test_agent_tools import Recorder
from tests.test_bench import SA, random_cities, tsp_bench, with_heuristic
from tests.test_candidates import WALK, walking


class Scripted:
    """A backend whose turns do what a script says, with the session's own tools."""

    def __init__(self, script):
        self.script = script
        self.heard = []

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def interrupt(self) -> None:
        pass

    async def turn(self, text):
        self.heard.append(text)
        error = await self.script(len(self.heard), text)
        yield TurnResult(session_id="s", error=error)


def run(project: Project, script, monkeypatch) -> tuple[Scripted, Recorder]:
    """Sends one message to a session on a scripted agent, and waits for its turns to end."""
    backend, recorder = Scripted(None), Recorder()

    async def main() -> None:
        session = AgentSession(project, recorder)
        backend.script = lambda turn, text: script(session.tools, turn, text)
        monkeypatch.setattr(agent, "open_backend", lambda *args: backend)
        assert session.submit("improve the search")
        while session.busy:
            await asyncio.sleep(0.01)
        await session.close()

    asyncio.run(main())
    return backend, recorder


async def tool(fn, **args) -> str:
    result = await fn(args)
    assert not result.get("is_error"), result["content"][0]["text"]
    return result["content"][0]["text"]


def test_a_campaign_needs_a_benchmark_and_an_incumbent(home):
    project, _ = tsp_bench(home, validation=0)
    with pytest.raises(ProjectError, match="no validation instances"):
        campaign.start(project, rounds=2)
    project, rev = tsp_bench(home)
    with pytest.raises(ProjectError, match="give 4 paired runs"):
        campaign.start(project, rounds=2)
    bench.configure(project, runs=5)
    with_heuristic(project, WALK)
    with pytest.raises(ProjectError, match="not a revision"):
        campaign.start(project, rounds=2)
    project.restore(rev)
    with pytest.raises(ProjectError, match="1 to 50 rounds"):
        campaign.start(project, rounds=0)
    state = campaign.start(project)
    assert (state["start_rev"], state["rounds"], state["minutes"]) == (rev, 5, None)
    with pytest.raises(ProjectError, match="running already"):
        campaign.start(project, rounds=2)


def improving(home) -> tuple[Project, int]:
    """A benchmark a campaign can run on, whose incumbent is a random walk."""
    project, rev = walking(home)
    bench.add_instance(project, "tsp3", "validation", "seed 3", {"cities": random_cities(3)})
    return project, rev


def test_rounds_that_bring_nothing_end_the_campaign(home, monkeypatch):
    project, rev = improving(home)

    async def script(tools, turn, text):
        if turn == 1:
            started = await tool(tools.improve_start, rounds=10)
            assert f"campaign started from revision {rev}: 10 rounds" in started

    backend, recorder = run(project, script, monkeypatch)
    # The user's turn, three rounds without a candidate, and the summary.
    assert len(backend.heard) == 5
    assert backend.heard[1].startswith("[studio] Improvement campaign, round 1 of 10.")
    assert "0 of the last rounds brought nothing" in backend.heard[1]
    assert "2 of the last rounds brought nothing" in backend.heard[3]
    assert "3 rounds in a row brought no better candidate" in backend.heard[4]
    assert f"No change was better than revision {rev}" in backend.heard[4]
    assert "Tell the user now" in backend.heard[4]
    state = campaign.load(project)
    assert (state["status"], state["round"], state["final"]["kept"]) == ("finished", 3, False)
    assert [e.role for e in project.chat()] == ["user", "studio", "studio", "studio", "studio"]
    shown = [e for e in recorder.events if isinstance(e, StudioMessage | TurnEnd)]
    assert [type(e) for e in shown] == [StudioMessage] * 4 + [TurnEnd]
    assert shown[-1].error is None
    described = campaign.describe(project)
    assert (described.status, described.kept, described.validation) == ("finished", False, None)


def test_an_adopted_candidate_is_checked_on_validation_and_measured_on_test(home, monkeypatch):
    project, rev = improving(home)
    bench.add_instance(project, "unseen", "test", "seed 9", {"cities": random_cities(9)})

    async def script(tools, turn, text):
        if turn == 1:
            await tool(tools.improve_start, rounds=1)
        elif turn == 2:
            assert f"The incumbent is revision {rev}" in text
            with_heuristic(project, SA)
            await tool(
                tools.candidate_save, baseline_rev=rev, hypothesis="annealing", family="heuristic"
            )
            await tool(tools.race, candidates=[1])
            await tool(tools.adopt, candidate=1, lesson="a walk never settles")
            # Left in the work files when the round ends: not part of what is kept.
            with_heuristic(project, {**SA, "cooling_rate": 0.5})

    backend, recorder = run(project, script, monkeypatch)
    assert len(backend.heard) == 3
    end = backend.heard[2]
    assert "its 1 rounds are spent. 1 candidates were saved, 1 adopted" in end
    assert f"Final check of revision 3 against revision {rev}:" in end
    assert "- on validation: BETTER, mean gain +" in end
    assert "- on test, which nothing was chosen on: SAME, mean gain +" in end
    assert "The improvement holds: the files are revision 3's." in end
    assert json.loads(project.read_file("solve.json"))["heuristic"] == SA
    state = campaign.load(project)
    assert state["log"] == [{"round": 1, "incumbent": rev, "incumbent_after": 3}]
    assert state["final"]["kept"] is True
    splits = [(r["split"], r["candidate"]["where"]) for r in bench.history(project)]
    assert splits == [
        ("train", "candidate 1"),
        ("validation", "revision 3"),
        ("test", "revision 3"),
    ]
    assert any(isinstance(e, FilesChanged) for e in recorder.events)
    assert isinstance(recorder.events[-2], BenchChanged)


def test_a_gain_that_does_not_hold_on_validation_is_undone(home, monkeypatch):
    project, rev = walking(home)
    # Five cities have twelve tours, which a walk finds the best of as well.
    for name in ("tsp2", "tsp3"):
        bench.add_instance(project, name, "validation", "five", {"cities": random_cities(1, n=5)})

    async def script(tools, turn, text):
        if turn == 1:
            await tool(tools.improve_start, rounds=1)
        elif turn == 2:
            with_heuristic(project, SA)
            await tool(
                tools.candidate_save, baseline_rev=rev, hypothesis="annealing", family="heuristic"
            )
            await tool(tools.adopt, candidate=1)

    backend, _ = run(project, script, monkeypatch)
    end = backend.heard[-1]
    assert "- on validation: SAME, mean gain +0.000%" in end
    assert "does not hold on validation, so it fit the train instances" in end
    assert f"the files are revision {rev}'s again" in end
    assert json.loads(project.read_file("solve.json"))["heuristic"] == WALK
    described = campaign.describe(project)
    assert (described.kept, described.validation.verdict, described.test) == (False, "same", None)
    assert project.revisions() == [1, rev, 3]


def test_a_stopped_campaign_still_checks_what_it_adopted(home, monkeypatch):
    project, rev = improving(home)

    async def script(tools, turn, text):
        if turn == 1:
            await tool(tools.improve_start, minutes=30)
        elif turn == 2:
            with_heuristic(project, SA)
            await tool(
                tools.candidate_save, baseline_rev=rev, hypothesis="annealing", family="heuristic"
            )
            await tool(tools.adopt, candidate=1)
            # The user stops the turn, which the agent ends as a failed one.
            assert campaign.request_stop(project)
            return "interrupted"

    backend, recorder = run(project, script, monkeypatch)
    assert len(backend.heard) == 2
    assert "about 30 of 30 minutes left" in backend.heard[1]
    state = campaign.load(project)
    assert (state["status"], state["reason"]) == ("stopped", "stopped by the user")
    assert state["final"]["validation"]["verdict"] == "better"
    said = project.chat()[-1]
    assert said.role == "studio"
    assert "The improvement holds" in said.text
    assert "Tell the user now" not in said.text
    assert recorder.events[-1] == TurnEnd(error=None)


def test_an_agent_that_fails_ends_the_campaign_where_it_is(home, monkeypatch):
    project, _ = improving(home)

    async def script(tools, turn, text):
        if turn == 1:
            await tool(tools.improve_start, rounds=3)
        else:
            return "the model is overloaded"

    backend, recorder = run(project, script, monkeypatch)
    assert len(backend.heard) == 2
    assert campaign.load(project)["status"] == "stopped"
    assert recorder.events[-1] == TurnEnd(error="the model is overloaded")
    # A studio that starts again does not take up a campaign left under way.
    campaign.start(project, rounds=1)
    AgentSession(project, Recorder())
    assert campaign.load(project)["status"] == "stopped"


def test_the_incumbent_follows_a_change_judged_better_and_then_solved(home):
    project, rev = walking(home)
    with_heuristic(project, SA)
    assert asyncio.run(bench.evaluate(project, rev)).verdict == "better"
    assert campaign.advance(project, rev) == rev
    kept = project.snapshot()
    assert campaign.advance(project, rev) == kept
    # Not a change that lost, and not one judged against another revision.
    with_heuristic(project, WALK)
    assert asyncio.run(bench.evaluate(project, kept)).verdict == "worse"
    project.snapshot()
    assert campaign.advance(project, rev) == kept
    assert campaign.advance(project, 1) == 1


def test_a_brief_says_what_the_records_suggest(home):
    project, rev = improving(home)
    state = campaign.start(project, rounds=4, minutes=20)
    state["round"] = 1
    brief = campaign.round_brief(project, state)
    assert "round 1 of 4, about 20 of 20 minutes left" in brief
    assert "No heuristics were profiled yet" in brief
    assert "The ledger so far" not in brief
    with_heuristic(project, SA)
    asyncio.run(candidates.save(project, rev, "annealing", "heuristic"))
    brief = campaign.round_brief(project, state)
    assert "The ledger so far:\n  1 [heuristic] on revision 2: not raced yet - annealing" in brief
    assert "families tried: heuristic 1; not yet: settings, composition" in brief
