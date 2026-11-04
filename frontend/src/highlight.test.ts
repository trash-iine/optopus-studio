import { describe, expect, it } from "vitest";
import { highlightLines, languageOf, MAX_HIGHLIGHT_CHARS } from "./highlight";

const text = (line: { text: string }[]) => line.map((s) => s.text).join("");

describe("highlight", () => {
  it("knows a project file's language by its extension", () => {
    expect(["model.py", "instance.json", "rust/main.rs", "notes.txt"].map(languageOf)).toEqual([
      "python",
      "json",
      "rust",
      null,
    ]);
  });

  it("keeps every line and character of the file", () => {
    const source = 'def f(x):\n    """Doc\n    more"""\n\n    return "<a>" & 1  # c\n';
    const lines = highlightLines(source, "python");
    expect(lines.map(text).join("\n")).toBe(source);
  });

  it("colors tokens, and a token that spans lines on each of its lines", () => {
    const lines = highlightLines('def f():\n    """Doc\n    more"""\n    return 1  # c', "python");
    const scopeOf = (row: number, word: string) => lines[row].find((s) => s.text.trim() === word)?.scope;
    expect(scopeOf(0, "def")).toBe("hljs-keyword");
    expect(scopeOf(0, "f")).toContain("hljs-title");
    expect(scopeOf(1, '"""Doc')).toBe("hljs-string");
    expect(scopeOf(2, 'more"""')).toBe("hljs-string");
    expect(scopeOf(3, "1")).toBe("hljs-number");
    expect(scopeOf(3, "# c")).toBe("hljs-comment");
  });

  it("shows unknown and very large files plain", () => {
    expect(highlightLines("def f(): pass", null)).toEqual([[{ text: "def f(): pass", scope: "" }]]);
    const big = `{"a": "${"x".repeat(MAX_HIGHLIGHT_CHARS)}"}`;
    expect(highlightLines(big, "json")[0][0].scope).toBe("");
  });
});
