// A line diff for comparing a revision's files: the longest common subsequence, then the lines
// either side adds, with unchanged runs folded down to a little context.

export type DiffLine = { kind: "same" | "added" | "removed"; text: string } | { kind: "skip"; count: number };

const MAX_CELLS = 4_000_000;
const CONTEXT = 2;

export function diffLines(before: string, after: string): DiffLine[] | null {
  const a = before.split("\n");
  const b = after.split("\n");
  if (a.length * b.length > MAX_CELLS) return null;
  // lcs[i][j]: the common subsequence length of a[i:] and b[j:].
  const lcs = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      lines.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (j < b.length && (i === a.length || lcs[i][j + 1] >= lcs[i + 1][j])) {
      lines.push({ kind: "added", text: b[j++] });
    } else {
      lines.push({ kind: "removed", text: a[i++] });
    }
  }
  return fold(lines);
}

function fold(lines: DiffLine[]): DiffLine[] {
  const changed = lines.map((l) => l.kind !== "same");
  const near = (k: number) => {
    for (let d = -CONTEXT; d <= CONTEXT; d++) if (changed[k + d]) return true;
    return false;
  };
  const out: DiffLine[] = [];
  let skipped = 0;
  lines.forEach((line, k) => {
    if (line.kind === "same" && !near(k)) {
      skipped++;
      return;
    }
    if (skipped) out.push({ kind: "skip", count: skipped });
    skipped = 0;
    out.push(line);
  });
  if (skipped) out.push({ kind: "skip", count: skipped });
  return out;
}
