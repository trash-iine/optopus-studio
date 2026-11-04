// Generated from schema/models.json by `npm run gen:types`. Do not edit.

/**
 * Why the agent could not list its models; it then runs on its default.
 */
export type Error = string | null;
/**
 * The effort the model runs at unless told otherwise, when known.
 */
export type DefaultEffort = string | null;
export type Description = string | null;
/**
 * The reasoning efforts the model takes, least first; empty when it takes none.
 */
export type Efforts = string[];
/**
 * What the agent is told to run on; an alias such as Claude's 'opus' follows the agent's updates.
 */
export type Id = string;
/**
 * Whether the agent runs on this model unless told otherwise.
 */
export type IsDefault = boolean;
/**
 * The model's name to show.
 */
export type Name = string;
export type Models = ModelChoice[];

/**
 * GET /api/agents/{agent}/models: the models an agent offers, as it lists them now.
 */
export interface ModelList {
  error: Error;
  models: Models;
}
/**
 * A model an agent can run on, as the agent's own list of models names it.
 */
export interface ModelChoice {
  default_effort: DefaultEffort;
  description: Description;
  efforts: Efforts;
  id: Id;
  is_default: IsDefault;
  name: Name;
}
