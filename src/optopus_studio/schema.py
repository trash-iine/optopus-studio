"""``python -m optopus_studio.schema``: write the JSON Schemas of the protocol to ``schema/``.

The frontend generates its TypeScript types from these files (``npm run gen:types``), and a
worker in another language checks its output against ``worker-event.json``. A test fails when a
file is out of date.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from optopus_studio.protocol import ClientEvent, ServerEvent, SolveRequest, ViewSpec, WorkerEvent

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"

# What a side reads is described as it is validated (defaults may be left out), what it is sent
# as it is serialized (every field present).
SCHEMAS = {
    "solve-request.json": (TypeAdapter(SolveRequest), "validation"),
    "worker-event.json": (TypeAdapter(WorkerEvent), "serialization"),
    "view-spec.json": (TypeAdapter(ViewSpec), "serialization"),
    "server-event.json": (TypeAdapter(ServerEvent), "serialization"),
    "client-event.json": (TypeAdapter(ClientEvent), "validation"),
}


def render() -> dict[str, str]:
    titles = {
        "solve-request.json": "SolveRequest",
        "worker-event.json": "WorkerEvent",
        "view-spec.json": "ViewSpec",
        "server-event.json": "ServerEvent",
        "client-event.json": "ClientEvent",
    }
    out = {}
    for name, (adapter, mode) in SCHEMAS.items():
        schema = adapter.json_schema(mode=mode)
        schema.setdefault("title", titles[name])
        out[name] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return out


def main() -> int:
    SCHEMA_DIR.mkdir(exist_ok=True)
    for name, text in render().items():
        (SCHEMA_DIR / name).write_text(text)
        print(f"wrote schema/{name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
