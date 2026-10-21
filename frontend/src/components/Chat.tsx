import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AgentChoice, ChatEntry } from "../generated/server-event";

// A .zip is a case exported from a packaged app (docs/adr/0009).
const ACCEPT = ".csv,.tsv,.txt,.xlsx,.json,.zip";

/** The message the agent receives: the attached files first, as its system prompt expects. */
export function withAttachments(text: string, files: string[]): string {
  if (files.length === 0) return text;
  const head = `Attached: ${files.join(", ")}`;
  return text ? `${head}\n\n${text}` : head;
}

/**
 * Whether a key press sends the message: Enter without Shift, and not the Enter that confirms an
 * IME conversion (Japanese input). Safari, and some IMEs elsewhere, end the composition before
 * that keydown, so `isComposing` is already false; its `keyCode` is still 229.
 */
export function sendsMessage(
  e: Pick<globalThis.KeyboardEvent, "key" | "shiftKey" | "isComposing" | "keyCode">,
): boolean {
  return e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229;
}

const AGENT_LABELS: Record<AgentChoice["name"], string> = { claude: "Claude", codex: "Codex" };

const EXAMPLES = [
  "15 都市を回る最短の巡回路を求めて",
  "4 つのジョブを 3 台の機械で、全体が最短で終わるように並べて",
  "容量 20 のナップサックに価値が最大になるように詰めて",
];

interface Props {
  chat: ChatEntry[];
  streaming: string;
  busy: boolean;
  connected: boolean;
  error: string | null;
  agent: AgentChoice["name"] | null;
  agents: AgentChoice[];
  onSend: (text: string) => void;
  onStop: () => void;
  onUpload: (file: File) => Promise<string>;
  onSelectAgent: (agent: AgentChoice["name"]) => void;
}

export function Chat(props: Props) {
  const { chat, streaming, busy, connected, error, agent, agents } = props;
  const { onSend, onStop, onUpload, onSelectAgent } = props;
  const [draft, setDraft] = useState("");
  const [attached, setAttached] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [chat, streaming]);

  const submit = () => {
    const text = draft.trim();
    if ((!text && attached.length === 0) || busy || !connected || uploading) return;
    onSend(withAttachments(text, attached));
    setDraft("");
    setAttached([]);
  };
  const attach = async (files: FileList | null) => {
    if (!files) return;
    setUploading(true);
    setUploadError(null);
    try {
      for (const file of Array.from(files)) {
        const name = await onUpload(file);
        setAttached((names) => (names.includes(name) ? names : [...names, name]));
      }
    } catch (e) {
      setUploadError((e as Error).message);
    } finally {
      setUploading(false);
      if (picker.current) picker.current.value = "";
    }
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (sendsMessage(e.nativeEvent)) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <aside className="chat">
      <div className="messages">
        {chat.length === 0 && (
          <div className="empty">
            <p>Describe what you want to optimize. The model and its result appear on the right.</p>
            {EXAMPLES.map((text) => (
              <button key={text} className="example" onClick={() => setDraft(text)}>
                {text}
              </button>
            ))}
          </div>
        )}
        {chat.map((entry, i) =>
          entry.role === "tool" ? (
            <div key={i} className="tool-line">
              ▸ {entry.text}
            </div>
          ) : (
            <div key={i} className={`bubble ${entry.role}`}>
              {entry.role === "assistant" ? <Markdown remarkPlugins={[remarkGfm]}>{entry.text}</Markdown> : entry.text}
            </div>
          ),
        )}
        {streaming && (
          <div className="bubble assistant">
            <Markdown remarkPlugins={[remarkGfm]}>{streaming}</Markdown>
          </div>
        )}
        {busy && !streaming && <div className="tool-line working">working…</div>}
        {error && <div className="chat-error">{error}</div>}
        <div ref={end} />
      </div>
      {(attached.length > 0 || uploading || uploadError) && (
        <div className="attachments">
          {attached.map((name) => (
            <span key={name} className="chip">
              {name}
              <button
                aria-label={`remove ${name}`}
                onClick={() => setAttached((names) => names.filter((n) => n !== name))}
              >
                ×
              </button>
            </span>
          ))}
          {uploading && <span className="muted">uploading…</span>}
          {uploadError && <span className="chat-error">{uploadError}</span>}
        </div>
      )}
      {agent && (
        <label className="agent-picker" title="Switching hands the conversation so far to the other agent">
          Agent
          <select
            value={agent}
            disabled={busy || !connected}
            onChange={(e) => onSelectAgent(e.target.value as AgentChoice["name"])}
          >
            {agents.map((choice) => (
              <option key={choice.name} value={choice.name} disabled={!choice.available} title={choice.reason ?? undefined}>
                {AGENT_LABELS[choice.name]}
                {choice.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="composer">
        <input
          ref={picker}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => attach(e.target.files)}
        />
        <button
          className="secondary attach"
          title="Attach CSV, TSV, Excel or JSON, or a case exported from an app"
          aria-label="attach a file"
          onClick={() => picker.current?.click()}
          disabled={!connected || uploading}
        >
          +
        </button>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={connected ? "Enter to send, Shift+Enter for a new line" : "Connecting…"}
          rows={3}
        />
        {busy ? (
          <button className="secondary" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={(!draft.trim() && attached.length === 0) || !connected || uploading}
          >
            Send
          </button>
        )}
      </div>
    </aside>
  );
}
