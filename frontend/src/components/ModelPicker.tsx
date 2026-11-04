import { useEffect, useState } from "react";
import type { ModelList } from "../generated/models";
import { effortsFor, fetchModels, modelOf, pickModel } from "../models";

interface Props {
  agent: string;
  model: string | null;
  effort: string | null;
  disabled: boolean;
  onSelect: (model: string | null, effort: string | null) => void;
}

/** The model and the effort the agent runs on, from the list the agent gives. */
export function ModelPicker({ agent, model, effort, disabled, onSelect }: Props) {
  const [list, setList] = useState<ModelList | null>(null);
  useEffect(() => {
    let current = true;
    setList(null);
    fetchModels(agent)
      .then((l) => current && setList(l))
      .catch((e: Error) => current && setList({ models: [], error: e.message }));
    return () => {
      current = false;
    };
  }, [agent]);

  if (list == null) return <span className="muted">Model …</span>;
  if (list.error || list.models.length === 0) {
    return (
      <span className="muted" title={list.error ?? "The agent lists no models."}>
        Model: default
      </span>
    );
  }
  const models = list.models;
  const efforts = effortsFor(models, model);
  const fallback = modelOf(models, model);
  return (
    <>
      <label title={fallback?.description ?? "The model the agent runs on in this project"}>
        Model{" "}
        <select
          value={model ?? ""}
          disabled={disabled}
          onChange={(e) => {
            const next = pickModel(models, e.target.value || null, effort);
            onSelect(next.model, next.effort);
          }}
        >
          <option value="">Default</option>
          {/* A model chosen earlier that the agent no longer lists stays shown, not swapped. */}
          {model != null && !models.some((m) => m.id === model) && <option value={model}>{model}</option>}
          {models.map((m) => (
            <option key={m.id} value={m.id} title={m.description ?? undefined}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      {efforts.length > 0 && (
        <label title="How much the model reasons before it answers">
          Effort{" "}
          <select
            value={effort ?? ""}
            disabled={disabled}
            onChange={(e) => onSelect(model, e.target.value || null)}
          >
            <option value="">
              Default{fallback?.default_effort ? ` (${fallback.default_effort})` : ""}
            </option>
            {efforts.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      )}
    </>
  );
}
