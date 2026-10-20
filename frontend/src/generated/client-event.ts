// Generated from schema/client-event.json by `npm run gen:types`. Do not edit.

export type ClientEvent = UserMessage | SelectRevision | Interrupt | SelectAgent;
export type Text = string;
export type Type = "user_message";
export type Rev = number;
export type Type1 = "select_revision";
export type Type2 = "interrupt";
export type Agent = "claude" | "codex";
export type Type3 = "select_agent";

export interface UserMessage {
  text: Text;
  type?: Type;
}
export interface SelectRevision {
  rev: Rev;
  type?: Type1;
}
export interface Interrupt {
  type?: Type2;
}
export interface SelectAgent {
  agent: Agent;
  type?: Type3;
}
