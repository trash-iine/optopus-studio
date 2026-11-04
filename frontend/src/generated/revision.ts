// Generated from schema/revision.json by `npm run gen:types`. Do not edit.

/**
 * The latest earlier revision solved from other files or settings, which Compare sets this one against first: a revision that changes only view.py or app.json solves the same as the one before it. None when every earlier one is solved the same.
 */
export type Baseline = number | null;
export type Rev = number;
export type BestRun = number | null;
export type Message = string;
export type Stage = "request" | "build" | "heuristic" | "start" | "run" | "encode";
export type Traceback = string | null;
export type Type = "error";
export type Label = string;
/**
 * The variants as solved, with any override of solve.json applied; empty in a result.json older than the field.
 */
export type Heuristics = Variant[];
export type HigherIsBetter = boolean | null;
/**
 * The key of instance.json every run started from, if not at random.
 */
export type InitialSolution = string | null;
/**
 * (elapsed_secs, objective)
 */
export type Points = [unknown, unknown][];
export type Run = number;
export type Variant1 = number;
export type Native = boolean | null;
export type Problem = string | null;
export type Rev1 = number;
export type BestIteration = number;
export type BestObjective = number;
/**
 * The best objective a solution a BranchAndBound run had not ruled out could reach, on best_objective's scale: best_objective once proven optimal, and how far from the optimum the run may have stopped otherwise. Null for every other heuristic, and when the run stopped before it had a finite bound.
 */
export type DualBound = number | null;
export type InitialObjective = number;
export type Iterations = number;
/**
 * Moves the run applied; null in a result.json older than the field.
 */
export type NAccepted = number | null;
/**
 * Iterations the run advanced without applying a move; null in a result.json older than the field.
 */
export type NRejected = number | null;
/**
 * Whether a BranchAndBound run proved its best solution optimal; null for every other heuristic.
 */
export type ProvenOptimal = boolean | null;
/**
 * The run's position among all runs of the solve, from 0.
 */
export type Run1 = number;
export type Seed = number | null;
export type TimeToBestSecs = number;
export type TotalTimeSecs = number;
/**
 * (elapsed_secs, iteration, objective) for every improvement of the best.
 */
export type Trajectory = [unknown, unknown, unknown][];
export type Type1 = "run_finished";
/**
 * The index of the variant the run belongs to.
 */
export type Variant2 = number;
export type Runs = RunFinished[];
/**
 * The seed the solve's runs were drawn from.
 */
export type Seed1 = number | null;
export type Variants = string[];
export type Worker = "python" | "rust";
export type Label1 = string;
export type Unit = string | null;
export type Value = number | string;
export type Items = KpiItem[];
export type Title = string | null;
export type Type2 = "kpi";
export type Columns = string[];
export type Rows = (number | string | boolean | null)[][];
export type Title1 = string | null;
export type Type3 = "table";
export type End = number;
/**
 * Tasks of one group share a color, e.g. a job.
 */
export type Group = string | null;
export type Label2 = string;
/**
 * The row the task is drawn on, such as a machine or a person.
 */
export type Lane = string;
export type Start = number;
export type Tasks = GanttTask[];
export type TimeUnit = string | null;
export type Title2 = string | null;
export type Type4 = "gantt";
/**
 * Whether each route returns to its first point.
 */
export type Closed = boolean;
export type Id = number | string;
export type Kind = "node" | "depot";
export type Label3 = string | null;
export type X = number;
export type Y = number;
export type Points1 = MapPoint[];
export type Label4 = string | null;
/**
 * Point ids in visiting order.
 */
export type Path = (number | string)[];
export type Routes = Route[];
export type Title3 = string | null;
export type Type5 = "route_map";
export type Highlight = boolean;
export type Source = number | string;
export type Target = number | string;
export type Weight = number | null;
export type Edges = GraphEdge[];
/**
 * Nodes of one group share a color.
 */
export type Group1 = string | null;
export type Id1 = number | string;
export type Label5 = string | null;
export type X1 = number | null;
export type Y1 = number | null;
export type Nodes = GraphNode[];
export type Title4 = string | null;
export type Type6 = "graph";
export type Categories = string[];
export type Name = string;
export type Values = number[];
export type Series = BarSeries[];
export type Stacked = boolean;
export type Title5 = string | null;
export type Type7 = "bar";
export type Text = string;
export type Title6 = string | null;
export type Type8 = "markdown";
export type Height = number;
/**
 * A whole document, drawn in a sandboxed iframe with scripts on.
 */
export type Html = string;
export type Title7 = string | null;
export type Type9 = "custom_html";
export type Views = (
  | KpiView
  | TableView
  | GanttView
  | RouteMapView
  | GraphView
  | BarView
  | MarkdownView
  | CustomHtmlView
)[];
export type ViewError = string | null;

/**
 * GET /api/projects/{id}/revisions/{rev}: one revision, for comparing two side by side.
 */
export interface RevisionDetail {
  baseline: Baseline;
  files: Files;
  rev: Rev;
  summary: RunSummary | null;
  view: ViewSpec | null;
  view_error: ViewError;
}
export interface Files {
  [k: string]: string;
}
/**
 * What the GUI keeps of one solve, also stored as a revision's result.json.
 */
export interface RunSummary {
  best_run: BestRun;
  error: WorkerError | null;
  heuristics: Heuristics;
  higher_is_better: HigherIsBetter;
  initial_solution: InitialSolution;
  live: LiveRun | null;
  native: Native;
  problem: Problem;
  rev: Rev1;
  runs: Runs;
  seed: Seed1;
  variants: Variants;
  worker: Worker;
}
/**
 * A solve failed, at the stage it failed at.
 */
export interface WorkerError {
  message: Message;
  stage: Stage;
  traceback: Traceback;
  type: Type;
}
/**
 * One heuristic of a solve, under the label the GUI shows it by.
 */
export interface Variant {
  heuristic: Heuristic;
  label: Label;
}
/**
 * A heuristic as {'kind': <optopus class>, **constructor arguments}; 'stop' is a StopCondition's arguments, and a nested heuristic is another such dict.
 */
export interface Heuristic {
  [k: string]: unknown;
}
/**
 * The run under way, as its progress events have reported it.
 */
export interface LiveRun {
  points: Points;
  run: Run;
  variant: Variant1;
}
/**
 * One run's outcome: its best solution, objective, and how the search went.
 */
export interface RunFinished {
  best_iteration: BestIteration;
  best_objective: BestObjective;
  dual_bound: DualBound;
  initial_objective: InitialObjective;
  iterations: Iterations;
  n_accepted: NAccepted;
  n_rejected: NRejected;
  proven_optimal: ProvenOptimal;
  run: Run1;
  seed: Seed;
  solution: Solution;
  time_to_best_secs: TimeToBestSecs;
  total_time_secs: TotalTimeSecs;
  trajectory: Trajectory;
  type: Type1;
  variant: Variant2;
}
/**
 * The best solution, JSON-encoded by the model.
 */
export interface Solution {
  [k: string]: unknown;
}
/**
 * What a project's ``view.py`` hands the GUI to draw: views, top to bottom.
 */
export interface ViewSpec {
  views: Views;
}
/**
 * A row of headline figures.
 */
export interface KpiView {
  items: Items;
  title: Title;
  type: Type2;
}
/**
 * One figure of a KPI view.
 */
export interface KpiItem {
  label: Label1;
  unit: Unit;
  value: Value;
}
/**
 * A table of rows.
 */
export interface TableView {
  columns: Columns;
  rows: Rows;
  title: Title1;
  type: Type3;
}
/**
 * A Gantt chart, such as a schedule of jobs on machines.
 */
export interface GanttView {
  tasks: Tasks;
  time_unit: TimeUnit;
  title: Title2;
  type: Type4;
}
/**
 * One task of a Gantt chart: a bar on a lane, from its start to its end.
 */
export interface GanttTask {
  end: End;
  group: Group;
  label: Label2;
  lane: Lane;
  start: Start;
}
/**
 * Points on a plane and the routes that visit them.
 */
export interface RouteMapView {
  closed: Closed;
  points: Points1;
  routes: Routes;
  title: Title3;
  type: Type5;
}
/**
 * A point on a route map, such as a city or a depot.
 */
export interface MapPoint {
  id: Id;
  kind: Kind;
  label: Label3;
  x: X;
  y: Y;
}
/**
 * One route on a map: the points it visits, in order.
 */
export interface Route {
  label: Label4;
  path: Path;
}
/**
 * A graph of nodes and edges, such as a cut or a coloring.
 */
export interface GraphView {
  edges: Edges;
  nodes: Nodes;
  title: Title4;
  type: Type6;
}
/**
 * An edge of a graph view, which may be highlighted, such as one in the solution.
 */
export interface GraphEdge {
  highlight: Highlight;
  source: Source;
  target: Target;
  weight: Weight;
}
/**
 * A node of a graph view; without x and y, the GUI lays it out.
 */
export interface GraphNode {
  group: Group1;
  id: Id1;
  label: Label5;
  x: X1;
  y: Y1;
}
/**
 * A bar chart.
 */
export interface BarView {
  categories: Categories;
  series: Series;
  stacked: Stacked;
  title: Title5;
  type: Type7;
}
/**
 * One series of a bar chart: a value per category.
 */
export interface BarSeries {
  name: Name;
  values: Values;
}
/**
 * Text in Markdown.
 */
export interface MarkdownView {
  text: Text;
  title: Title6;
  type: Type8;
}
/**
 * Anything the other views cannot draw, as a document in a sandboxed iframe.
 */
export interface CustomHtmlView {
  height: Height;
  html: Html;
  title: Title7;
  type: Type9;
}
