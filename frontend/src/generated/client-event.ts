// Generated from schema/client-event.json by `npm run gen:types`. Do not edit.

export type ClientEvent = UserMessage | SelectRevision | Interrupt | SelectAgent | SetWebSearch;
export type Text = string;
export type Type = "user_message";
export type Rev = number;
export type Type1 = "select_revision";
export type Type2 = "interrupt";
export type Agent = "claude" | "codex";
export type Type3 = "select_agent";
export type Enabled = boolean;
export type Type4 = "set_web_search";

/**
 * A message the user sent to the agent.
 */
export interface UserMessage {
  text: Text;
  type?: Type;
}
/**
 * The user chose a revision to show.
 */
export interface SelectRevision {
  rev: Rev;
  type?: Type1;
}
/**
 * The user stopped the agent's turn.
 */
export interface Interrupt {
  type?: Type2;
}
/**
 * The user chose another agent for the project's chat.
 */
export interface SelectAgent {
  agent: Agent;
  type?: Type3;
}
/**
 * The user let the agent search the web, or stopped it.
 */
export interface SetWebSearch {
  enabled: Enabled;
  type?: Type4;
}
