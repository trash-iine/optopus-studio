// Syntax colors for the project's files, line by line, so a diff can color each side's lines.
// highlight.js finds the tokens; its HTML is read back into plain segments here and drawn as React
// spans, so no file's text is ever set as HTML.
import hljs from "highlight.js/lib/core";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";

hljs.registerLanguage("python", python);
hljs.registerLanguage("json", json);
hljs.registerLanguage("rust", rust);

/** Past this size a file is shown plain: an uploaded instance.json can be megabytes. */
export const MAX_HIGHLIGHT_CHARS = 200_000;

/** A run of text and the token classes it is in ("hljs-keyword", …), space-separated. */
export interface Segment {
  text: string;
  scope: string;
}

export type Lines = Segment[][];

/** The language of a project file, by its extension; null for one shown plain. */
export function languageOf(name: string): string | null {
  if (name.endsWith(".py")) return "python";
  if (name.endsWith(".json")) return "json";
  if (name.endsWith(".rs")) return "rust";
  return null;
}

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', "#x27": "'", "#39": "'" };

function unescape(html: string): string {
  return html.replace(/&(amp|lt|gt|quot|#x27|#39);/g, (_, name: string) => ENTITIES[name]);
}

/** Plain lines, one segment each. */
export function plainLines(text: string): Lines {
  return text.split("\n").map((line) => (line ? [{ text: line, scope: "" }] : []));
}

/**
 * A file's lines, each a list of segments with their token classes. A token that spans lines (a
 * docstring) keeps its classes on every line. Plain when the language is unknown or the file is
 * too large.
 */
export function highlightLines(text: string, language: string | null): Lines {
  if (language == null || text.length > MAX_HIGHLIGHT_CHARS) return plainLines(text);
  let html: string;
  try {
    html = hljs.highlight(text, { language, ignoreIllegals: true }).value;
  } catch {
    return plainLines(text);
  }
  const lines: Lines = [[]];
  const scopes: string[] = [];
  for (const [, open, close, chunk] of html.matchAll(/<span class="([^"]*)">|(<\/span>)|([^<]+)/g)) {
    if (open !== undefined) scopes.push(open);
    else if (close !== undefined) scopes.pop();
    else {
      const scope = scopes.join(" ");
      unescape(chunk).split("\n").forEach((part, k) => {
        if (k > 0) lines.push([]);
        if (part) lines[lines.length - 1].push({ text: part, scope });
      });
    }
  }
  return lines;
}
