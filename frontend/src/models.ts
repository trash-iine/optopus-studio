// The models and efforts an agent offers, as it lists them (GET /api/agents/{agent}/models). The
// studio keeps no list of its own, so a model the agent adds shows up without a change here.
import type { ModelChoice, ModelList } from "./generated/models";

export async function fetchModels(agent: string): Promise<ModelList> {
  const response = await fetch(`/api/agents/${agent}/models`);
  if (!response.ok) return { models: [], error: `the models could not be listed: ${response.status}` };
  return response.json();
}

/** The model a choice runs on: the one chosen, else the agent's default, if the list says. */
export function modelOf(models: ModelChoice[], model: string | null): ModelChoice | undefined {
  return model == null ? models.find((m) => m.is_default) : models.find((m) => m.id === model);
}

/** The efforts to offer for a model choice; empty when the model takes none or is unknown. */
export function effortsFor(models: ModelChoice[], model: string | null): string[] {
  return modelOf(models, model)?.efforts ?? [];
}

/** The choice after picking another model: the effort stays only if the new model takes it. */
export function pickModel(
  models: ModelChoice[],
  model: string | null,
  effort: string | null,
): { model: string | null; effort: string | null } {
  return { model, effort: effort != null && effortsFor(models, model).includes(effort) ? effort : null };
}
