import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatEntry } from "../generated/server-event";

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
  onSend: (text: string) => void;
  onStop: () => void;
}

export function Chat({ chat, streaming, busy, connected, error, onSend, onStop }: Props) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [chat, streaming]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy || !connected) return;
    onSend(text);
    setDraft("");
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter while an IME is composing (Japanese input) confirms the conversion, not the message.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
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
      <div className="composer">
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
          <button onClick={submit} disabled={!draft.trim() || !connected}>
            Send
          </button>
        )}
      </div>
    </aside>
  );
}
