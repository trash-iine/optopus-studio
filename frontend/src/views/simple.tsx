// The views that need no chart library: tiles, tables, notes and custom HTML.
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CustomHtmlView, KpiView, MarkdownView, TableView } from "../generated/server-event";
import { compact } from "../theme";

export function Kpi({ view }: { view: KpiView }) {
  return (
    <div className="kpi-row">
      {view.items.map((item, i) => (
        <div className="kpi" key={i}>
          <div className="kpi-label">{item.label}</div>
          <div className="kpi-value">
            {typeof item.value === "number" ? compact(item.value) : item.value}
            {item.unit && <span className="kpi-unit"> {item.unit}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function cell(value: number | string | boolean | null) {
  if (value === true) return "✓";
  if (value === false) return "–";
  if (value === null) return "";
  return typeof value === "number" ? value.toLocaleString("en-US") : value;
}

export function Table({ view }: { view: TableView }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {view.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row, i) => (
            <tr key={i}>
              {row.map((value, j) => (
                <td key={j} className={typeof value === "number" ? "num" : undefined}>
                  {cell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Note({ view }: { view: MarkdownView }) {
  return (
    <div className="markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{view.text}</Markdown>
    </div>
  );
}

export function CustomHtml({ view }: { view: CustomHtmlView }) {
  // Scripts run, but without same-origin they cannot reach the studio or its API.
  return (
    <iframe
      className="custom-html"
      sandbox="allow-scripts"
      srcDoc={view.html}
      style={{ height: view.height }}
      title={view.title ?? "custom view"}
    />
  );
}
