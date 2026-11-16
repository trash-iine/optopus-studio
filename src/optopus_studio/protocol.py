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
    """A contract's base: unknown fields are rejected, and defaults are always sent."""

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


class InitialSolution(Strict):
    """Where every run of a solve starts instead of a random solution."""

    key: str = Field(description="The key of instance.json the solution was read from.")
    solution: Any = Field(
        description="The solution in the form encode_solution writes it, which the worker turns "
        "back into the problem's own with the model's decode_solution."
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
    initial_solution: InitialSolution | None = None


class Started(Strict):
    """The worker built the problem and its heuristics, and the runs begin."""

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
    """One run's outcome: its best solution, objective, and how the search went."""

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
    proven_optimal: bool | None = Field(
        None,
        description="Whether a BranchAndBound run proved its best solution optimal; null for "
        "every other heuristic.",
    )
    dual_bound: float | None = Field(
        None,
        description="The best objective a solution a BranchAndBound run had not ruled out could "
        "reach, on best_objective's scale: best_objective once proven optimal, and how far from "
        "the optimum the run may have stopped otherwise. Null for every other heuristic, and "
        "when the run stopped before it had a finite bound.",
    )
    n_accepted: int | None = Field(
        None, description="Moves the run applied; null in a result.json older than the field."
    )
    n_rejected: int | None = Field(
        None,
        description="Iterations the run advanced without applying a move; null in a result.json "
        "older than the field.",
    )


class Done(Strict):
    """Every run has finished; the best of them."""

    type: Literal["done"] = "done"
    best_run: int
    best_objective: float


class WorkerError(Strict):
    """A solve failed, at the stage it failed at."""

    type: Literal["error"] = "error"
    stage: Literal["request", "build", "heuristic", "start", "run", "encode"]
    message: str
    traceback: str | None = None


WorkerEvent = Annotated[
    Started | Progress | RunFinished | Done | WorkerError, Field(discriminator="type")
]


class EvaluateRequest(Strict):
    """A worker started with ``--evaluate``: score solutions with a model, without searching.

    The answer is one JSON line, ``{"objectives": [...]}`` in the order of ``solutions`` on the
    scale ``best_objective`` reports, or ``{"error": ...}`` when the model cannot build or a
    solution cannot be decoded. A Rust worker is the model, so it reads only ``instance`` and
    ``solutions``.
    """

    model_path: str = Field(description="Path of the model.py that scores the solutions.")
    instance: dict[str, Any]
    solutions: list[Any] = Field(description="Solutions in the form encode_solution writes.")
    heuristic: dict[str, Any] = Field(
        description="A heuristic of the model's solve.json. The Python worker starts a run of it "
        "from each solution and stops it before its first iteration, so a built-in problem "
        "scores the solution as a run would report it."
    )


# --- ViewSpec ----------------------------------------------------------------------------------


class KpiItem(Strict):
    """One figure of a KPI view."""

    label: str
    value: float | int | str
    unit: str | None = None


class KpiView(Strict):
    """A row of headline figures."""

    type: Literal["kpi"] = "kpi"
    title: str | None = None
    items: list[KpiItem]


class TableView(Strict):
    """A table of rows."""

    type: Literal["table"] = "table"
    title: str | None = None
    columns: list[str]
    rows: list[list[float | int | str | bool | None]]


class GanttTask(Strict):
    """One task of a Gantt chart: a bar on a lane, from its start to its end."""

    lane: str = Field(description="The row the task is drawn on, such as a machine or a person.")
    label: str
    start: float
    end: float
    group: str | None = Field(None, description="Tasks of one group share a color, e.g. a job.")


class GanttView(Strict):
    """A Gantt chart, such as a schedule of jobs on machines."""

    type: Literal["gantt"] = "gantt"
    title: str | None = None
    tasks: list[GanttTask]
    time_unit: str | None = None


class MapPoint(Strict):
    """A point on a route map, such as a city or a depot."""

    id: int | str
    x: float
    y: float
    label: str | None = None
    kind: Literal["node", "depot"] = "node"


class Route(Strict):
    """One route on a map: the points it visits, in order."""

    path: list[int | str] = Field(description="Point ids in visiting order.")
    label: str | None = None


class RouteMapView(Strict):
    """Points on a plane and the routes that visit them."""

    type: Literal["route_map"] = "route_map"
    title: str | None = None
    points: list[MapPoint]
    routes: list[Route]
    closed: bool = Field(True, description="Whether each route returns to its first point.")


class GraphNode(Strict):
    """A node of a graph view; without x and y, the GUI lays it out."""

    id: int | str
    label: str | None = None
    group: str | None = Field(None, description="Nodes of one group share a color.")
    x: float | None = None
    y: float | None = None


class GraphEdge(Strict):
    """An edge of a graph view, which may be highlighted, such as one in the solution."""

    source: int | str
    target: int | str
    weight: float | None = None
    highlight: bool = False


class GraphView(Strict):
    """A graph of nodes and edges, such as a cut or a coloring."""

    type: Literal["graph"] = "graph"
    title: str | None = None
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class BarSeries(Strict):
    """One series of a bar chart: a value per category."""

    name: str
    values: list[float]


class BarView(Strict):
    """A bar chart."""

    type: Literal["bar"] = "bar"
    title: str | None = None
    categories: list[str]
    series: list[BarSeries]
    stacked: bool = False


class MarkdownView(Strict):
    """Text in Markdown."""

    type: Literal["markdown"] = "markdown"
    title: str | None = None
    text: str


class CustomHtmlView(Strict):
    """Anything the other views cannot draw, as a document in a sandboxed iframe."""

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
    """What a project's ``view.py`` hands the GUI to draw: views, top to bottom."""

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
    initial_solution: str | None = Field(
        None, description="The key of instance.json every run started from, if not at random."
    )
    runs: list[RunFinished] = []
    best_run: int | None = None
    error: WorkerError | None = None


class ChatEntry(Strict):
    """One entry of the conversation as the GUI shows it."""

    role: Literal["user", "assistant", "tool"]
    text: str


# The agents a project's chat can run on (docs/adr/0012).
AgentName = Literal["claude", "codex"]


class AgentChoice(Strict):
    """An agent a project's chat can run on, and whether it can run here."""

    name: AgentName
    available: bool
    reason: str | None = Field(None, description="Why the agent cannot run here, if it cannot.")


class ModelChoice(Strict):
    """A model an agent can run on, as the agent's own list of models names it."""

    id: str = Field(
        description="What the agent is told to run on; an alias such as Claude's 'opus' follows "
        "the agent's updates."
    )
    name: str = Field(description="The model's name to show.")
    description: str | None = None
    efforts: list[str] = Field(
        description="The reasoning efforts the model takes, least first; empty when it takes none."
    )
    default_effort: str | None = Field(
        None, description="The effort the model runs at unless told otherwise, when known."
    )
    is_default: bool = Field(
        False, description="Whether the agent runs on this model unless told otherwise."
    )


class ModelList(Strict):
    """GET /api/agents/{agent}/models: the models an agent offers, as it lists them now."""

    models: list[ModelChoice]
    error: str | None = Field(
        None, description="Why the agent could not list its models; it then runs on its default."
    )


class AssistantDelta(Strict):
    """Text of the agent's reply as it streams."""

    type: Literal["assistant_delta"] = "assistant_delta"
    text: str


class AssistantText(Strict):
    """A whole text of the agent's reply."""

    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolActivity(Strict):
    """A tool the agent called, and what it called it with, in a few words."""

    type: Literal["tool"] = "tool"
    name: str
    summary: str


class TurnEnd(Strict):
    """The agent finished its turn, or failed it."""

    type: Literal["turn_end"] = "turn_end"
    error: str | None = None


class FilesChanged(Strict):
    """The work files changed: all of them, as they are now."""

    type: Literal["files"] = "files"
    files: dict[str, str]


class SolveStarted(Strict):
    """A solve of a new revision began."""

    type: Literal["solve_started"] = "solve_started"
    rev: int
    runs: int


class SolveProgress(Strict):
    """How a solve stands, after each event of its worker."""

    type: Literal["solve_progress"] = "solve_progress"
    rev: int
    summary: RunSummary


class ViewUpdated(Strict):
    """What a revision's ``view.py`` drew, or why it failed."""

    type: Literal["view"] = "view"
    rev: int
    view: ViewSpec | None
    error: str | None = None


# What the agent runs on the benchmark (bench.py), and the instances it runs on.
BenchTask = Literal["evaluation", "tuning", "profile", "race"]
# "all" is train and validation: the test split is never part of a choice (docs/adr/0018).
BenchSplit = Literal["train", "validation", "test", "all"]


class BenchProgress(Strict):
    """How far the evaluation or tuning on the benchmark the agent is running has got."""

    type: Literal["bench_progress"] = "bench_progress"
    task: BenchTask
    done: int = Field(
        description="Solves finished in an evaluation or a profile, runs in a tuning."
    )
    total: int


class BenchChanged(Strict):
    """The benchmark, its evaluations, tunings or profiles changed.

    The browser reads them again from GET /api/projects/{id}/bench.
    """

    type: Literal["bench_changed"] = "bench_changed"


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
    agent: AgentName = Field(description="The agent this project's chat runs on.")
    agents: list[AgentChoice] = Field(description="The agents to choose from, in order.")
    web_search: bool = Field(
        False, description="Whether the agent may search and read the web (docs/adr/0016)."
    )
    model: str | None = Field(
        None, description="The model the agent runs on in this project; None for its default."
    )
    effort: str | None = Field(
        None, description="The reasoning effort the agent runs at; None for the model's default."
    )


class AgentSelected(Strict):
    """The project's chat now runs on another agent, which reads the conversation so far first."""

    type: Literal["agent_selected"] = "agent_selected"
    agent: AgentName
    model: str | None = Field(None, description="The model chosen for that agent, if any.")
    effort: str | None = Field(None, description="The effort chosen for that agent, if any.")


class ModelSelected(Strict):
    """The agent runs on another model or effort from the next message, in the same session."""

    type: Literal["model_selected"] = "model_selected"
    model: str | None
    effort: str | None


class WebSearchChanged(Strict):
    """The agent may now search the web, or no longer, from the next message."""

    type: Literal["web_search_changed"] = "web_search_changed"
    enabled: bool


ServerEvent = Annotated[
    Snapshot
    | AssistantDelta
    | AssistantText
    | ToolActivity
    | TurnEnd
    | FilesChanged
    | SolveStarted
    | SolveProgress
    | ViewUpdated
    | AgentSelected
    | ModelSelected
    | WebSearchChanged
    | BenchProgress
    | BenchChanged,
    Field(discriminator="type"),
]


class RevisionDetail(Strict):
    """GET /api/projects/{id}/revisions/{rev}: one revision, for comparing two side by side."""

    rev: int
    files: dict[str, str]
    summary: RunSummary | None
    view: ViewSpec | None
    view_error: str | None = None
    baseline: int | None = Field(
        None,
        description="The latest earlier revision solved from other files or settings, which "
        "Compare sets this one against first: a revision that changes only view.py or app.json "
        "solves the same as the one before it. None when every earlier one is solved the same.",
    )


class ProjectInfo(Strict):
    """GET /api/projects: one project, newest first."""

    id: str
    title: str | None = Field(description="The first thing the user asked, shortened.")
    imported_from: str | None = Field(
        description="The id the project had in the studio it was exported from, if imported."
    )


class UserMessage(Strict):
    """A message the user sent to the agent."""

    type: Literal["user_message"] = "user_message"
    text: str = Field(min_length=1)


class SelectRevision(Strict):
    """The user chose a revision to show."""

    type: Literal["select_revision"] = "select_revision"
    rev: int


class Interrupt(Strict):
    """The user stopped the agent's turn."""

    type: Literal["interrupt"] = "interrupt"


class SelectAgent(Strict):
    """The user chose another agent for the project's chat."""

    type: Literal["select_agent"] = "select_agent"
    agent: AgentName


class SetWebSearch(Strict):
    """The user let the agent search the web, or stopped it."""

    type: Literal["set_web_search"] = "set_web_search"
    enabled: bool


class SelectModel(Strict):
    """The user chose the model and effort the agent runs on; None for the default."""

    type: Literal["select_model"] = "select_model"
    model: str | None = Field(None, max_length=200)
    effort: str | None = Field(None, max_length=50)


ClientEvent = Annotated[
    UserMessage | SelectRevision | Interrupt | SelectAgent | SetWebSearch | SelectModel,
    Field(discriminator="type"),
]


# --- Apps: a revision packaged to run without the agent (docs/adr/0009) ------------------------

# Also a directory name in an app's cases, so no dots or slashes.
INPUT_KEY = r"^[A-Za-z_][A-Za-z0-9_-]*$"
PARAMETER_TARGET = r"^(instance(\.[^.]+)+|solve\.(max_duration_secs|runs|seed))$"


class AppColumn(Strict):
    """A column every row of an app's input must have."""

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
    """app.json: what a packaged app lets its user change.

    Everything else is fixed, and is changed in the studio.
    """

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
    """A file the app's user gave for one input of a case."""

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


# --- Benchmark: the instances a change of the algorithm is judged on (docs/adr/0013) ----------

# Also a file name under bench/instances, so no dots or slashes.
BENCH_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$"


class BenchInstance(Strict):
    """One instance of the benchmark, kept under bench/instances."""

    name: str = Field(pattern=BENCH_NAME)
    split: Literal["train", "validation", "test"] = Field(
        description="Candidates are chosen on train; the final choice is checked on validation; "
        "test only measures what is reported, and decides nothing."
    )
    source: str = Field(description="Where the instance came from, such as 'revision 3'.")
    sha256: str = Field(description="Of the instance file, so a result says what it ran on.")


class BenchSpec(Strict):
    """bench/bench.json: the instances and the budget every evaluation runs with."""

    instances: list[BenchInstance] = []
    runs: int = Field(5, ge=1, le=50, description="Runs per instance and side, paired by seed.")
    seed: int = Field(0, ge=0, lt=2**64)
    max_duration_secs: float | None = Field(
        1.0,
        gt=0,
        description="Each run's time limit, which replaces the stop of every evaluated heuristic.",
    )
    max_iteration: int | None = Field(
        None, ge=1, description="Each run's iteration limit, instead of or as well as the time."
    )


Verdict = Literal["better", "mixed", "same", "worse", "rejected", "failed"]


class BenchSide(Strict):
    """One side of an evaluation: whose files, which heuristic, which worker."""

    where: str = Field(description="'the work files', 'revision <n>' or 'candidate <n>'.")
    rev: int | None
    variant: str
    worker: Literal["python", "rust"]
    candidate_id: int | None = Field(
        None, description="The saved candidate the side ran, if it is one (docs/adr/0018)."
    )


class BenchInstanceResult(Strict):
    """How the candidate did against the baseline on one instance."""

    name: str
    gain: float = Field(
        description="The mean gain over the paired runs, relative to the "
        "baseline's mean objective; + is better."
    )
    outcome: Literal["better", "same", "worse"]
    baseline: float = Field(description="The baseline's mean best objective.")
    candidate: float = Field(description="The candidate's mean best objective.")


class BenchEvaluation(Strict):
    """One evaluation of a change against a baseline revision (bench.py)."""

    id: int
    split: BenchSplit
    candidate: BenchSide
    baseline: BenchSide
    note: str = Field(description="What the candidate changes, as the agent said it.")
    verdict: Verdict
    gain: float | None = Field(description="The mean gain over all pairs; null unless judged.")
    worsening: float = Field(description="The mean worsening over the instances, one way.")
    p_better: float
    p_worse: float
    detail: str | None = Field(description="Why a candidate was rejected or failed.")
    instances: list[BenchInstanceResult]
    kept: int | None = Field(
        description="The later revision whose files are the candidate's, if it was solved into one."
    )


class BenchTuning(Strict):
    """One tuning of a heuristic's settings by racing (tune.py)."""

    id: int
    rev: int
    variants: list[str] = Field(
        description="The variants raced: one, or several to choose among, the first the one the "
        "others were measured against."
    )
    used: int = Field(description="The runs made.")
    budget: int
    settings: int = Field(description="The settings raced.")
    eliminated: int
    failed: int
    best: dict[str, Any] | None = Field(
        description="The best settings by parameter path; null when the revision's own stayed."
    )
    best_variant: str | None = Field(
        description="The variant of the best settings when several were raced; null otherwise, "
        "or when the revision's own stayed."
    )
    validation: int | None = Field(description="The evaluation that checked them on validation.")
    signs: list[str] = Field(
        description="What the race shows that settings cannot fix, as hints for the next change."
    )


class BenchProfileVariant(Strict):
    """How one heuristic behaved in a profile."""

    label: str
    error: str | None = Field(description="Why its runs failed; the rest is null then.")
    mean_rank: float | None = Field(description="Over the runs, 1 the best.")
    p_vs_best: float | None = Field(
        description="Conover's p-value against the best; under 0.05 it is clearly worse."
    )
    wins: int = Field(description="Instances on which its mean objective is the best.")
    anytime: list[float] = Field(
        description="The mean gap of its best so far to the best any heuristic found on the "
        "instance, relative to that best, at each of the profile's fractions of the budget."
    )
    best_found_at: float | None = Field(
        description="The mean share of the budget spent when a run found its best."
    )
    iterations_per_sec: float | None
    accepted: float | None = Field(description="The share of moves accepted.")


class BenchProfile(Strict):
    """One profile of several heuristics on the benchmark (profiling.py, docs/adr/0015)."""

    id: int
    rev: int | None = Field(description="The revision profiled; null for the work files.")
    split: Literal["train", "validation", "all"]
    instances: list[str]
    fractions: list[float] = Field(description="The shares of the budget 'anytime' is read at.")
    p: float | None = Field(description="The Friedman test's p-value over all runs.")
    variants: list[BenchProfileVariant]
    readings: list[str] = Field(
        description="Compositions the profile suggests, as hints for the next variants."
    )


# What a candidate changes, so the ledger says which kinds of change were tried (docs/adr/0018).
Family = Literal[
    "settings",
    "heuristic",
    "composition",
    "neighborhood",
    "delta",
    "representation",
    "start",
    "port",
]


class BenchCandidate(Strict):
    """One saved candidate, a line of the ledger: a hypothesis and what became of it."""

    id: int
    baseline_rev: int = Field(description="The revision it changes, and is judged against.")
    family: Family
    hypothesis: str = Field(description="What it changes and why that should help.")
    evidence: str = Field(description="What suggested it: a reading, a sign, a source.")
    variant: str = Field(description="The heuristic of its solve.json it runs.")
    evaluation: int | None = Field(description="Its latest evaluation, if it was judged.")
    verdict: Verdict | None
    gain: float | None
    adopted: int | None = Field(description="The revision it was adopted as, if it was.")
    lesson: str = Field(description="What its result taught, in the agent's words.")


class BenchRaceEntry(Strict):
    """How one candidate did in a race."""

    candidate: int
    evaluation: int = Field(description="Its evaluation against the baseline, from the race.")
    verdict: Verdict
    gain: float | None
    mean_rank: float | None = Field(
        description="Over the runs, 1 the best, among the baseline and the candidates judged."
    )


class BenchRace(Strict):
    """One race of several candidates against a baseline revision (candidates.py)."""

    id: int
    baseline: BenchSide
    baseline_rank: float | None
    p: float | None = Field(description="The Friedman test's p-value over all runs.")
    entries: list[BenchRaceEntry]
    winner: int | None = Field(
        description="The best-ranked candidate judged better than the baseline, if any."
    )


class BenchBest(Strict):
    """The best objective known on one instance of the benchmark."""

    name: str
    objective: float
    source: str = Field(description="What found it, such as 'evaluation 4'.")


class BenchState(Strict):
    """GET /api/projects/{id}/bench: the benchmark and everything judged or measured on it."""

    spec: BenchSpec
    evaluations: list[BenchEvaluation]
    tunings: list[BenchTuning]
    profiles: list[BenchProfile] = []
    candidates: list[BenchCandidate] = []
    races: list[BenchRace] = []
    best: list[BenchBest] = []
