"""A stand-in for ``codex``: ``--version``, and an ``app-server`` that plays one scripted turn.

Every message it reads, its arguments and whether an OpenAI key reached it go to FAKE_CODEX_LOG
as JSON Lines, for the test to check. A turn streams a delta, asks for a command approval (which
the studio must refuse), calls the studio's write_file tool, and ends with the agent's message
once the tool has answered.
"""

import json
import os
import sys

LOG = os.environ["FAKE_CODEX_LOG"]


def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    if sys.argv[1:] == ["--version"]:
        print(f"codex-cli {os.environ.get('FAKE_CODEX_VERSION', '0.153.4')}")
        return
    log({"argv": sys.argv[1:], "openai_key": "OPENAI_API_KEY" in os.environ})
    thread = "thread-1"
    for line in sys.stdin:
        message = json.loads(line)
        log(message)
        method, params = message.get("method"), message.get("params") or {}
        if method is None:
            if message["id"] == "tool":
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread,
                            "item": {"type": "agentMessage", "text": "Wrote instance.json."},
                        },
                    }
                )
                send(
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": thread,
                            "turn": {"id": "turn-1", "status": "completed", "error": None},
                        },
                    }
                )
            continue
        if "id" not in message:
            continue
        result = {}
        if method == "account/read":
            signed_in = not os.environ.get("FAKE_CODEX_SIGNED_OUT")
            result = {
                "account": {"type": "chatgpt"} if signed_in else None,
                "requiresOpenaiAuth": True,
            }
        elif method == "thread/start":
            result = {"thread": {"id": thread}}
        elif method == "thread/resume" and params["threadId"] == "gone":
            send({"id": message["id"], "error": {"code": -32600, "message": "no rollout found"}})
            continue
        elif method == "turn/start":
            result = {"turn": {"id": "turn-1", "status": "inProgress"}}
        send({"id": message["id"], "result": result})
        if method == "turn/start":
            send(
                {
                    "method": "item/agentMessage/delta",
                    "params": {"threadId": thread, "delta": "Writing"},
                }
            )
            # A sub-agent's message is not the conversation's.
            send(
                {
                    "method": "item/agentMessage/delta",
                    "params": {"threadId": "other", "delta": "elsewhere"},
                }
            )
            send(
                {
                    "id": "approval",
                    "method": "item/commandExecution/requestApproval",
                    "params": {"threadId": thread, "command": "rm -rf /"},
                }
            )
            send(
                {
                    "id": "tool",
                    "method": "item/tool/call",
                    "params": {
                        "threadId": thread,
                        "turnId": "turn-1",
                        "callId": "c1",
                        "tool": "write_file",
                        "arguments": {"name": "instance.json", "content": "{}"},
                    },
                }
            )


main()
