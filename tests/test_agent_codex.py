"""The agent on Codex, against tests/fake_codex.py: no model and no network are involved."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from optopus_studio.agent import SYSTEM_PROMPT, AgentSession, Tools, agent_choices
from optopus_studio.agent_codex import FEATURES_OFF, codex_unavailable, config_overrides
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import (
    AssistantDelta,
    AssistantText,
    ChatEntry,
    FilesChanged,
    ToolActivity,
    TurnEnd,
)

FAKE = Path(__file__).with_name("fake_codex.py")


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """The fake's log, once OPTOPUS_STUDIO_CODEX names it."""
    binary = tmp_path / "codex"
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    binary.chmod(0o755)
    log = tmp_path / "codex.jsonl"
    monkeypatch.setenv("OPTOPUS_STUDIO_CODEX", str(binary))
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-codex")
    return log


def received(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def calls(log: Path, method: str) -> list[dict]:
    return [m["params"] for m in received(log) if m.get("method") == method]


class Recorder:
    def __init__(self):
        self.events = []
        self.ended = asyncio.Event()

    async def __call__(self, event):
        self.events.append(event)
        if isinstance(event, TurnEnd):
            self.ended.set()


def converse(project: Project, *texts: str, select: str | None = None) -> list:
    async def main():
        recorder = Recorder()
        session = AgentSession(project, recorder)
        try:
            if select:
                await session.select(select)
            for text in texts:
                recorder.ended.clear()
                assert session.submit(text)
                await asyncio.wait_for(recorder.ended.wait(), 30)
        finally:
            await session.close()
        return recorder.events

    return asyncio.run(main())


def codex_project(home: Path, **meta) -> Project:
    project = Project.create(home)
    project.set_meta(agent="codex", **meta)
    return project


def test_a_turn_on_codex_runs_the_studios_tools(home, codex):
    project = codex_project(home)
    events = converse(project, "write an empty instance")

    assert events == [
        AssistantDelta(text="Writing"),
        ToolActivity(name="write_file", summary="instance.json"),
        FilesChanged(files={"instance.json": "{}"}),
        AssistantText(text="Wrote instance.json."),
        TurnEnd(error=None),
    ]
    assert [e.role for e in project.chat()] == ["user", "tool", "assistant"]
    assert project.meta() == {"agent": "codex", "session_id": "thread-1"}
    (tool_answer,) = [m for m in received(codex) if m.get("id") == "tool"]
    assert tool_answer["result"]["success"] is True
    # Codex's own tools are refused.
    (approval,) = [m for m in received(codex) if m.get("id") == "approval"]
    assert "error" in approval


def test_codex_is_given_only_the_studios_tools(home, codex):
    project = codex_project(home)
    converse(project, "hi")

    (start,) = calls(codex, "thread/start")
    tools = [spec.name for spec in Tools(project, Recorder()).specs()]
    assert [t["name"] for t in start["dynamicTools"]] == tools
    assert start["baseInstructions"] == SYSTEM_PROMPT
    assert start["sandbox"] == "read-only"
    assert start["approvalPolicy"] == "never"
    assert start["cwd"] == str(project.work)
    launch = received(codex)[0]
    for feature in ("shell_tool", "unified_exec", "apps", "plugins", "multi_agent"):
        assert f"features.{feature}=false" in launch["argv"]
    assert 'web_search="disabled"' in launch["argv"]
    # Codex signs in with its own login, not a key that happens to be exported.
    assert launch["openai_key"] is False


def test_the_mcp_servers_in_codexs_config_are_turned_off(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[mcp_servers.docs]\ncommand = "x"\n\n[mcp_servers."my.server"]\nurl = "http://x"\n'
    )
    overrides = config_overrides(tmp_path)
    assert 'mcp_servers."docs".enabled=false' in overrides
    assert 'mcp_servers."my.server".enabled=false' in overrides
    assert {f"features.{name}=false" for name in FEATURES_OFF} <= set(overrides)
    assert "project_doc_max_bytes=0" in config_overrides(tmp_path / "missing")


def test_a_later_session_resumes_the_codex_thread(home, codex):
    project = codex_project(home, session_id="thread-1")
    project.append_chat(ChatEntry(role="user", text="earlier"))
    converse(project, "go on")

    assert calls(codex, "thread/start") == []
    (resume,) = calls(codex, "thread/resume")
    assert resume["threadId"] == "thread-1"
    (turn,) = calls(codex, "turn/start")
    assert turn["input"] == [{"type": "text", "text": "go on"}]


def test_a_lost_codex_thread_is_replaced_by_one_that_reads_the_conversation(home, codex):
    project = codex_project(home, session_id="gone")
    project.append_chat(ChatEntry(role="user", text="visit every city"))
    events = converse(project, "now from the depot")

    assert events[-1] == TurnEnd(error=None)
    assert len(calls(codex, "thread/start")) == 1
    (turn,) = calls(codex, "turn/start")
    text = turn["input"][0]["text"]
    assert "<conversation>" in text
    assert text.index("visit every city") < text.index("now from the depot")
    assert project.meta()["session_id"] == "thread-1"


def test_switching_to_codex_hands_it_the_conversation(home, codex):
    project = Project.create(home)
    project.set_meta(session_id="a-claude-session")
    project.append_chat(ChatEntry(role="user", text="visit every city"))
    project.append_chat(ChatEntry(role="assistant", text="The tour is 412 long."))
    converse(project, "now from the depot", select="codex")

    assert calls(codex, "thread/resume") == []
    (turn,) = calls(codex, "turn/start")
    assert turn["input"][0]["text"].index("412") < turn["input"][0]["text"].index("depot")
    assert project.meta()["agent"] == "codex"


def test_the_agent_is_not_switched_mid_turn_or_to_one_that_cannot_run(home):
    async def main():
        session = AgentSession(Project.create(home), Recorder())
        session.busy = True
        with pytest.raises(ProjectError, match="still working"):
            await session.select("codex")
        session.busy = False
        with pytest.raises(ProjectError, match="codex cannot run here"):
            await session.select("codex")

    asyncio.run(main())


def test_a_signed_out_codex_says_how_to_sign_in(home, codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_SIGNED_OUT", "1")
    project = codex_project(home)
    events = converse(project, "hi")

    (end,) = events
    assert "codex login" in end.error
    assert project.chat() == []
    assert calls(codex, "thread/start") == []


def test_codex_is_offered_only_where_it_can_run(codex, monkeypatch, tmp_path):
    assert codex_unavailable() is None
    assert [c.name for c in agent_choices()] == ["claude", "codex"]
    monkeypatch.setenv("FAKE_CODEX_VERSION", "0.1.0")
    old = tmp_path / "old-codex"
    old.write_text((tmp_path / "codex").read_text())
    old.chmod(0o755)
    monkeypatch.setenv("OPTOPUS_STUDIO_CODEX", str(old))
    assert "0.1.0 is too old" in codex_unavailable()
    monkeypatch.setenv("OPTOPUS_STUDIO_CODEX", str(tmp_path / "missing"))
    assert "not an executable" in codex_unavailable()
