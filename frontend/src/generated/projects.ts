// Generated from schema/projects.json by `npm run gen:types`. Do not edit.

export type Id = string;
/**
 * The id the project had in the studio it was exported from, if imported.
 */
export type ImportedFrom = string | null;
/**
 * The first thing the user asked, shortened.
 */
export type Title = string | null;
export type ProjectList = ProjectInfo[];

/**
 * GET /api/projects: one project, newest first.
 */
export interface ProjectInfo {
  id: Id;
  imported_from: ImportedFrom;
  title: Title;
}
