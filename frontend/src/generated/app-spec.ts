// Generated from schema/app-spec.json by `npm run gen:types`. Do not edit.

export type Description = string | null;
export type Description1 = string | null;
export type Name = string;
/**
 * Whether every row must have a value.
 */
export type Required = boolean;
/**
 * Checked in every row when given.
 */
export type Type = ("number" | "integer" | "string" | "boolean") | null;
/**
 * The columns every row must have; empty accepts any table or JSON.
 */
export type Columns = AppColumn[];
export type Description2 = string | null;
/**
 * The key of instance.json the file replaces.
 */
export type Key = string;
export type Label = string;
/**
 * Whether a file must be given; otherwise the packaged data is used.
 */
export type Required1 = boolean;
export type Inputs = AppInput[];
export type Choices = (string | number)[] | null;
export type Description3 = string | null;
export type Label1 = string;
export type Max = number | null;
export type Min = number | null;
export type Name1 = string;
/**
 * Where the value goes: instance.<key>[.<key>...] in instance.json, or solve.max_duration_secs (every heuristic's time limit), solve.runs or solve.seed.
 */
export type Target = string;
export type Type1 = "number" | "integer" | "boolean" | "string";
export type Unit = string | null;
export type Parameters = AppParameter[];
export type Title = string;

/**
 * app.json: what a packaged app lets its user change. Everything else is fixed, and is
 * changed in the studio.
 */
export interface AppSpec {
  description?: Description;
  inputs?: Inputs;
  parameters?: Parameters;
  title: Title;
}
/**
 * A file the app's user can give, whose rows replace one key of instance.json.
 */
export interface AppInput {
  columns?: Columns;
  description?: Description2;
  key: Key;
  label: Label;
  required?: Required1;
}
export interface AppColumn {
  description?: Description1;
  name: Name;
  required?: Required;
  type?: Type;
}
/**
 * A value the app's user can change. Its default is what the packaged files hold.
 */
export interface AppParameter {
  choices?: Choices;
  description?: Description3;
  label: Label1;
  max?: Max;
  min?: Min;
  name: Name1;
  target: Target;
  type: Type1;
  unit?: Unit;
}
