"""The contracts between the parts of the studio, and the single source of their schemas.

Three boundaries are fixed here so that each side can be replaced on its own:

- ``SolveRequest`` and ``WorkerEvent``: the backend and a solver worker, as JSON Lines over the
  worker's stdin and stdout. The Python worker and a future Rust worker speak the same protocol.
- ``ViewSpec``: what a project's ``view.py`` hands the GUI to draw.
- ``ServerEvent``: what the backend sends the browser over the WebSocket.

``python -m optopus_studio.schema`` writes the JSON Schemas the frontend types are generated from.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    # In the serialization schemas a field with a default is still always present, so the
    # generated TypeScript types can narrow unions on `type`.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --- Worker protocol ---------------------------------------------------------------------------


class SolveRequest(Strict):
    """One solve: the model to build, its data, and how to search."""

    model_path: str = Field(description="Path of the project's model.py.")
    instance: dict[str, Any] = Field(description="The project's instance.json.")
    heuristic: dict[str, Any] = Field(
        description="A heuristic as {'kind': <optopus class>, **constructor arguments}; "
        "'stop' is a StopCondition's arguments, and a nested heuristic is another such dict."
    )
    runs: int = Field(1, ge=1, le=100)
    seed: int | None = Field(0, ge=0, lt=2**64)


class Started(Strict):
    type: Literal["started"] = "started"
    runs: int
    higher_is_better: bool = Field(description="The direction best_objective is ranked in.")
    problem: str = Field(description="The class name of the problem the model built.")


class RunFinished(Strict):
    type: Literal["run_finished"] = "run_finished"
    run: int
    seed: int | None
    best_objective: float
    initial_objective: float
    solution: Any = Field(description="The best solution, JSON-encoded by the model.")
    trajectory: list[tuple[float, int, float]] = Field(
        description="(elapsed_secs, iteration, objective) for every improvement of the best."
    )
    iterations: int
    best_iteration: int
    time_to_best_secs: float
    total_time_secs: float


class Done(Strict):
    type: Literal["done"] = "done"
    best_run: int
    best_objective: float


class WorkerError(Strict):
    type: Literal["error"] = "error"
    stage: Literal["request", "build", "heuristic", "run", "encode"]
    message: str
    traceback: str | None = None


WorkerEvent = Annotated[Started | RunFinished | Done | WorkerError, Field(discriminator="type")]


# --- ViewSpec ----------------------------------------------------------------------------------


class KpiItem(Strict):
    label: str
    value: float | int | str
    unit: str | None = None


class KpiView(Strict):
    type: Literal["kpi"] = "kpi"
    title: str | None = None
    items: list[KpiItem]


class TableView(Strict):
    type: Literal["table"] = "table"
    title: str | None = None
    columns: list[str]
    rows: list[list[float | int | str | bool | None]]


class GanttTask(Strict):
    lane: str = Field(description="The row the task is drawn on, such as a machine or a person.")
    label: str
    start: float
    end: float
    group: str | None = Field(None, description="Tasks of one group share a color, e.g. a job.")


class GanttView(Strict):
    type: Literal["gantt"] = "gantt"
    title: str | None = None
    tasks: list[GanttTask]
    time_unit: str | None = None


class MapPoint(Strict):
    id: int | str
    x: float
    y: float
    label: str | None = None
    kind: Literal["node", "depot"] = "node"


class Route(Strict):
    path: list[int | str] = Field(description="Point ids in visiting order.")
    label: str | None = None


class RouteMapView(Strict):
    type: Literal["route_map"] = "route_map"
    title: str | None = None
    points: list[MapPoint]
    routes: list[Route]
    closed: bool = Field(True, description="Whether each route returns to its first point.")


class GraphNode(Strict):
    id: int | str
    label: str | None = None
    group: str | None = Field(None, description="Nodes of one group share a color.")
    x: float | None = None
    y: float | None = None


class GraphEdge(Strict):
    source: int | str
    target: int | str
    weight: float | None = None
    highlight: bool = False


class GraphView(Strict):
    type: Literal["graph"] = "graph"
    title: str | None = None
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class BarSeries(Strict):
    name: str
    values: list[float]


class BarView(Strict):
    type: Literal["bar"] = "bar"
    title: str | None = None
    categories: list[str]
    series: list[BarSeries]
    stacked: bool = False


class MarkdownView(Strict):
    type: Literal["markdown"] = "markdown"
    title: str | None = None
    text: str


class CustomHtmlView(Strict):
    type: Literal["custom_html"] = "custom_html"
    title: str | None = None
    html: str = Field(description="A whole document, drawn in a sandboxed iframe with scripts on.")
    height: int = Field(400, ge=100, le=2000)


View = Annotated[
    KpiView
    | TableView
    | GanttView
    | RouteMapView
    | GraphView
    | BarView
    | MarkdownView
    | CustomHtmlView,
    Field(discriminator="type"),
]


class ViewSpec(Strict):
    views: list[View]


# --- Backend to browser ------------------------------------------------------------------------


class RunSummary(Strict):
    """What the GUI keeps of one solve, also stored as a revision's result.json."""

    rev: int
    problem: str | None = None
    higher_is_better: bool | None = None
    runs: list[RunFinished] = []
    best_run: int | None = None
    error: WorkerError | None = None


class ChatEntry(Strict):
    role: Literal["user", "assistant", "tool"]
    text: str


class AssistantDelta(Strict):
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str


class AssistantText(Strict):
    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolActivity(Strict):
    type: Literal["tool"] = "tool"
    name: str
    summary: str


class TurnEnd(Strict):
    type: Literal["turn_end"] = "turn_end"
    error: str | None = None


class FilesChanged(Strict):
    type: Literal["files"] = "files"
    files: dict[str, str]


class SolveStarted(Strict):
    type: Literal["solve_started"] = "solve_started"
    rev: int
    runs: int


class SolveProgress(Strict):
    type: Literal["solve_progress"] = "solve_progress"
    rev: int
    summary: RunSummary


class ViewUpdated(Strict):
    type: Literal["view"] = "view"
    rev: int
    view: ViewSpec | None
    error: str | None = None


class Snapshot(Strict):
    """Everything the GUI shows, sent when a browser connects."""

    type: Literal["snapshot"] = "snapshot"
    project: str
    chat: list[ChatEntry]
    files: dict[str, str]
    revisions: list[int]
    rev: int | None
    summary: RunSummary | None
    view: ViewSpec | None
    view_error: str | None = None
    busy: bool


ServerEvent = Annotated[
    Snapshot
    | AssistantDelta
    | AssistantText
    | ToolActivity
    | TurnEnd
    | FilesChanged
    | SolveStarted
    | SolveProgress
    | ViewUpdated,
    Field(discriminator="type"),
]


class UserMessage(Strict):
    type: Literal["user_message"] = "user_message"
    text: str = Field(min_length=1)


class SelectRevision(Strict):
    type: Literal["select_revision"] = "select_revision"
    rev: int


class Interrupt(Strict):
    type: Literal["interrupt"] = "interrupt"


ClientEvent = Annotated[UserMessage | SelectRevision | Interrupt, Field(discriminator="type")]
