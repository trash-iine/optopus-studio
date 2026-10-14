// An HTML legend above a chart: identity is never carried by color alone.
export function Legend({ entries, line }: { entries: [string, string][]; line?: boolean }) {
  if (entries.length < 2) return null;
  return (
    <div className="legend">
      {entries.map(([label, color]) => (
        <span className="legend-item" key={label}>
          <span
            className={line ? "legend-line" : "legend-swatch"}
            style={{ background: color }}
          />
          {label}
        </span>
      ))}
    </div>
  );
}
