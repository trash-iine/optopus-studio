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


MAX_VARIANTS = 8


class Variant(Strict):
    """One heuristic of a solve, under the label the GUI shows it by."""

    label: str = Field(min_length=1)
    heuristic: dict[str, Any] = Field(
        description="A heuristic as {'kind': <optopus class>, **constructor arguments}; "
        "'stop' is a StopCondition's arguments, and a nested heuristic is another such dict."
    )


class SolveRequest(Strict):
    """One solve: the model to build, its data, and how to search.

    Every variant runs ``runs`` times with the same per-run seeds, so variants start from the same
    initial solutions and compare fairly.
    """

    model_path: str = Field(description="Path of the project's model.py.")
    instance: dict[str, Any] = Field(description="The project's instance.json.")
    variants: list[Variant] = Field(min_length=1, max_length=MAX_VARIANTS)
    runs: int = Field(1, ge=1, le=100)
    seed: int | None = Field(0, ge=0, lt=2**64)


class Started(Strict):
    type: Literal["started"] = "started"
    runs: int = Field(description="Runs per variant.")
    variants: list[str] = Field(description="The variants' labels, in the order they run.")
    higher_is_better: bool = Field(description="The direction best_objective is ranked in.")
    problem: str = Field(description="The class name of the problem the model built.")
    native: bool = Field(
        description="Whether the search runs in compiled code: a built-in problem, or any "
        "problem in a Rust worker. A problem written in Python is not."
    )


class Progress(Strict):
    """A run's best so far, while it runs. Only a worker that can see inside a run sends it."""

    type: Literal["progress"] = "progress"
    run: int
    variant: int
    elapsed_secs: float
    objective: float


class RunFinished(Strict):
    type: Literal["run_finished"] = "run_finished"
    run: int = Field(description="The run's position among all runs of the solve, from 0.")
    variant: int = Field(description="The index of the variant the run belongs to.")
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


WorkerEvent = Annotated[
    Started | Progress | RunFinished | Done | WorkerError, Field(discriminator="type")
]


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


class LiveRun(Strict):
    """The run under way, as its progress events have reported it."""

    run: int
    variant: int
    points: list[tuple[float, float]] = Field(description="(elapsed_secs, objective)")


class RunSummary(Strict):
    """What the GUI keeps of one solve, also stored as a revision's result.json."""

    rev: int
    worker: Literal["python", "rust"] = "python"
    problem: str | None = None
    native: bool | None = None
    higher_is_better: bool | None = None
    live: LiveRun | None = None
    variants: list[str] = []
    heuristics: list[Variant] = Field(
        [],
        description="The variants as solved, with any override of solve.json applied; empty in "
        "a result.json older than the field.",
    )
    seed: int | None = Field(None, description="The seed the solve's runs were drawn from.")
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


class RevisionDetail(Strict):
    """GET /api/projects/{id}/revisions/{rev}: one revision, for comparing two side by side."""

    rev: int
    files: dict[str, str]
    summary: RunSummary | None
    view: ViewSpec | None
    view_error: str | None = None


class ProjectInfo(Strict):
    """GET /api/projects: one project, newest first."""

    id: str
    title: str | None = Field(description="The first thing the user asked, shortened.")
    imported_from: str | None = Field(
        description="The id the project had in the studio it was exported from, if imported."
    )


class UserMessage(Strict):
    type: Literal["user_message"] = "user_message"
    text: str = Field(min_length=1)


class SelectRevision(Strict):
    type: Literal["select_revision"] = "select_revision"
    rev: int


class Interrupt(Strict):
    type: Literal["interrupt"] = "interrupt"


ClientEvent = Annotated[UserMessage | SelectRevision | Interrupt, Field(discriminator="type")]


# --- Apps: a revision packaged to run without the agent (docs/adr/0009) ------------------------

# Also a directory name in an app's cases, so no dots or slashes.
INPUT_KEY = r"^[A-Za-z_][A-Za-z0-9_-]*$"
PARAMETER_TARGET = r"^(instance(\.[^.]+)+|solve\.(max_duration_secs|runs|seed))$"


class AppColumn(Strict):
    name: str = Field(min_length=1)
    type: Literal["number", "integer", "string", "boolean"] | None = Field(
        None, description="Checked in every row when given."
    )
    required: bool = Field(True, description="Whether every row must have a value.")
    description: str | None = None


class AppInput(Strict):
    """A file the app's user can give, whose rows replace one key of instance.json."""

    key: str = Field(pattern=INPUT_KEY, description="The key of instance.json the file replaces.")
    label: str = Field(min_length=1)
    description: str | None = None
    columns: list[AppColumn] = Field(
        [], description="The columns every row must have; empty accepts any table or JSON."
    )
    required: bool = Field(
        False, description="Whether a file must be given; otherwise the packaged data is used."
    )


class AppParameter(Strict):
    """A value the app's user can change. Its default is what the packaged files hold."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    label: str = Field(min_length=1)
    description: str | None = None
    type: Literal["number", "integer", "boolean", "string"]
    target: str = Field(
        pattern=PARAMETER_TARGET,
        description="Where the value goes: instance.<key>[.<key>...] in instance.json, or "
        "solve.max_duration_secs (every heuristic's time limit), solve.runs or solve.seed.",
    )
    min: float | None = None
    max: float | None = None
    choices: list[str | int | float] | None = None
    unit: str | None = None


class AppSpec(Strict):
    """app.json: what a packaged app lets its user change. Everything else is fixed, and is
    changed in the studio."""

    title: str = Field(min_length=1)
    description: str | None = None
    inputs: list[AppInput] = []
    parameters: list[AppParameter] = []


class AppInfo(Strict):
    """GET /api/app: the app a package holds."""

    spec: AppSpec
    project: str = Field(description="The studio project the package was made from.")
    rev: int = Field(description="The revision of that project it holds.")
    packaged_at: str
    defaults: dict[str, Any] = Field(description="Each parameter's value in the packaged files.")
    sample: RunSummary | None = Field(description="The revision's own result, on its own data.")
    sample_view: ViewSpec | None


class CaseInput(Strict):
    key: str
    file: str
    rows: int | None = Field(description="The number of rows read, for a table.")


class CaseState(Strict):
    """GET /api/app/cases/{id}: one set of inputs and what solving it gave."""

    id: str
    status: Literal["draft", "solving", "solved", "failed"]
    inputs: list[CaseInput]
    parameters: dict[str, Any]
    problems: list[str] = Field(
        description="Why the inputs cannot be solved as they are, in the user's terms."
    )
    note: str = Field(
        default="", description="What the app's user says about the case, for the developer."
    )
    summary: RunSummary | None
    view: ViewSpec | None
    view_error: str | None
