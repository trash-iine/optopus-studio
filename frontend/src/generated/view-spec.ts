// Generated from schema/view-spec.json by `npm run gen:types`. Do not edit.

export type Label = string;
export type Unit = string | null;
export type Value = number | string;
export type Items = KpiItem[];
export type Title = string | null;
export type Type = "kpi";
export type Columns = string[];
export type Rows = (number | string | boolean | null)[][];
export type Title1 = string | null;
export type Type1 = "table";
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
export type Type2 = "gantt";
/**
 * Whether each route returns to its first point.
 */
export type Closed = boolean;
export type Id = number | string;
export type Kind = "node" | "depot";
export type Label2 = string | null;
export type X = number;
export type Y = number;
export type Points = MapPoint[];
export type Label3 = string | null;
/**
 * Point ids in visiting order.
 */
export type Path = (number | string)[];
export type Routes = Route[];
export type Title3 = string | null;
export type Type3 = "route_map";
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
export type Type4 = "graph";
export type Categories = string[];
export type Name = string;
export type Values = number[];
export type Series = BarSeries[];
export type Stacked = boolean;
export type Title5 = string | null;
export type Type5 = "bar";
export type Text = string;
export type Title6 = string | null;
export type Type6 = "markdown";
export type Height = number;
/**
 * A whole document, drawn in a sandboxed iframe with scripts on.
 */
export type Html = string;
export type Title7 = string | null;
export type Type7 = "custom_html";
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
  type: Type;
}
/**
 * One figure of a KPI view.
 */
export interface KpiItem {
  label: Label;
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
  type: Type1;
}
/**
 * A Gantt chart, such as a schedule of jobs on machines.
 */
export interface GanttView {
  tasks: Tasks;
  time_unit: TimeUnit;
  title: Title2;
  type: Type2;
}
/**
 * One task of a Gantt chart: a bar on a lane, from its start to its end.
 */
export interface GanttTask {
  end: End;
  group: Group;
  label: Label1;
  lane: Lane;
  start: Start;
}
/**
 * Points on a plane and the routes that visit them.
 */
export interface RouteMapView {
  closed: Closed;
  points: Points;
  routes: Routes;
  title: Title3;
  type: Type3;
}
/**
 * A point on a route map, such as a city or a depot.
 */
export interface MapPoint {
  id: Id;
  kind: Kind;
  label: Label2;
  x: X;
  y: Y;
}
/**
 * One route on a map: the points it visits, in order.
 */
export interface Route {
  label: Label3;
  path: Path;
}
/**
 * A graph of nodes and edges, such as a cut or a coloring.
 */
export interface GraphView {
  edges: Edges;
  nodes: Nodes;
  title: Title4;
  type: Type4;
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
  label: Label4;
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
  type: Type5;
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
  type: Type6;
}
/**
 * Anything the other views cannot draw, as a document in a sandboxed iframe.
 */
export interface CustomHtmlView {
  height: Height;
  html: Html;
  title: Title7;
  type: Type7;
}
