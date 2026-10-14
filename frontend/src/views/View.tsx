// Dispatches a ViewSpec entry to its component.
import type { ViewSpec } from "../generated/server-event";
import type { Mode } from "../theme";
import { Bar, Gantt, Graph } from "./charts";
import { RouteMap } from "./RouteMap";
import { CustomHtml, Kpi, Note, Table } from "./simple";

export type AnyView = ViewSpec["views"][number];

export function View({ view, mode }: { view: AnyView; mode: Mode }) {
  switch (view.type) {
    case "kpi":
      return <Kpi view={view} />;
    case "table":
      return <Table view={view} />;
    case "gantt":
      return <Gantt view={view} mode={mode} />;
    case "route_map":
      return <RouteMap view={view} mode={mode} />;
    case "graph":
      return <Graph view={view} mode={mode} />;
    case "bar":
      return <Bar view={view} mode={mode} />;
    case "markdown":
      return <Note view={view} />;
    case "custom_html":
      return <CustomHtml view={view} />;
  }
}

/** A titled card; tiles sit on the page without one. */
export function ViewCard({ view, mode }: { view: AnyView; mode: Mode }) {
  if (view.type === "kpi" && !view.title) return <View view={view} mode={mode} />;
  return (
    <section className={`card card-${view.type}`}>
      {view.title && <h3>{view.title}</h3>}
      <View view={view} mode={mode} />
    </section>
  );
}
