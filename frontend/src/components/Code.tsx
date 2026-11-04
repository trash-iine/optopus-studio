import { useMemo } from "react";
import { highlightLines, languageOf, type Segment } from "../highlight";

/** One line's segments, each in its token's color. */
export function CodeLine({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((s, k) =>
        s.scope ? (
          <span key={k} className={s.scope}>
            {s.text}
          </span>
        ) : (
          s.text
        ),
      )}
    </>
  );
}

/** A whole project file, colored by the language its name says. */
export function CodeBlock({ name, text }: { name: string; text: string }) {
  const lines = useMemo(() => highlightLines(text, languageOf(name)), [name, text]);
  return (
    <pre className="code">
      {lines.map((segments, k) => (
        // A newline after every line but the last, as the file has them.
        <span key={k}>
          <CodeLine segments={segments} />
          {k < lines.length - 1 ? "\n" : null}
        </span>
      ))}
    </pre>
  );
}
