// Generated from schema/revision.json by `npm run gen:types`. Do not edit.

export type Rev = number;
export type BestRun = number | null;
export type Message = string;
export type Stage = "request" | "build" | "heuristic" | "run" | "encode";
export type Traceback = string | null;
export type Type = "error";
export type HigherIsBetter = boolean | null;
/**
 * (elapsed_secs, objective)
 */
export type Points = [unknown, unknown][];
export type Run = number;
export type Variant = number;
export type Native = boolean | null;
export type Problem = string | null;
export type Rev1 = number;
export type BestIteration = number;
export type BestObjective = number;
export type InitialObjective = number;
export type Iterations = number;
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
export type Variant1 = number;
export type Runs = RunFinished[];
export type Variants = string[];
export type Worker = "python" | "rust";
export type Label = string;
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
export type Label1 = string;
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
export type Label2 = string | null;
export type X = number;
export type Y = number;
export type Points1 = MapPoint[];
export type Label3 = string | null;
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
export type Label4 = string | null;
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
  higher_is_better: HigherIsBetter;
  live: LiveRun | null;
  native: Native;
  problem: Problem;
  rev: Rev1;
  runs: Runs;
  variants: Variants;
  worker: Worker;
}
export interface WorkerError {
  message: Message;
  stage: Stage;
  traceback: Traceback;
  type: Type;
}
/**
 * The run under way, as its progress events have reported it.
 */
export interface LiveRun {
  points: Points;
  run: Run;
  variant: Variant;
}
export interface RunFinished {
  best_iteration: BestIteration;
  best_objective: BestObjective;
  initial_objective: InitialObjective;
  iterations: Iterations;
  run: Run1;
  seed: Seed;
  solution: Solution;
  time_to_best_secs: TimeToBestSecs;
  total_time_secs: TotalTimeSecs;
  trajectory: Trajectory;
  type: Type1;
  variant: Variant1;
}
/**
 * The best solution, JSON-encoded by the model.
 */
export interface Solution {
  [k: string]: unknown;
}
export interface ViewSpec {
  views: Views;
}
export interface KpiView {
  items: Items;
  title: Title;
  type: Type2;
}
export interface KpiItem {
  label: Label;
  unit: Unit;
  value: Value;
}
export interface TableView {
  columns: Columns;
  rows: Rows;
  title: Title1;
  type: Type3;
}
export interface GanttView {
  tasks: Tasks;
  time_unit: TimeUnit;
  title: Title2;
  type: Type4;
}
export interface GanttTask {
  end: End;
  group: Group;
  label: Label1;
  lane: Lane;
  start: Start;
}
export interface RouteMapView {
  closed: Closed;
  points: Points1;
  routes: Routes;
  title: Title3;
  type: Type5;
}
export interface MapPoint {
  id: Id;
  kind: Kind;
  label: Label2;
  x: X;
  y: Y;
}
export interface Route {
  label: Label3;
  path: Path;
}
export interface GraphView {
  edges: Edges;
  nodes: Nodes;
  title: Title4;
  type: Type6;
}
export interface GraphEdge {
  highlight: Highlight;
  source: Source;
  target: Target;
  weight: Weight;
}
export interface GraphNode {
  group: Group1;
  id: Id1;
  label: Label4;
  x: X1;
  y: Y1;
}
export interface BarView {
  categories: Categories;
  series: Series;
  stacked: Stacked;
  title: Title5;
  type: Type7;
}
export interface BarSeries {
  name: Name;
  values: Values;
}
export interface MarkdownView {
  text: Text;
  title: Title6;
  type: Type8;
}
export interface CustomHtmlView {
  height: Height;
  html: Html;
  title: Title7;
  type: Type9;
}
