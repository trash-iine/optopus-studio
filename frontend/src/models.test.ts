import { describe, expect, it } from "vitest";
import type { ModelChoice } from "./generated/models";
import { effortsFor, pickModel } from "./models";

const model = (id: string, efforts: string[], is_default = false): ModelChoice => ({
  id,
  name: id,
  description: null,
  efforts,
  default_effort: null,
  is_default,
});
const models = [model("big", ["low", "high", "max"], true), model("small", ["low"]), model("old", [])];

describe("models", () => {
  it("offers the efforts of the chosen model, or of the default one", () => {
    expect(effortsFor(models, "small")).toEqual(["low"]);
    expect(effortsFor(models, null)).toEqual(["low", "high", "max"]);
    expect(effortsFor(models, "old")).toEqual([]);
    expect(effortsFor(models, "gone")).toEqual([]);
    expect(effortsFor([model("a", ["low"])], null)).toEqual([]);
  });

  it("keeps the effort across a change of model only where the new model takes it", () => {
    expect(pickModel(models, "small", "low")).toEqual({ model: "small", effort: "low" });
    expect(pickModel(models, "small", "max")).toEqual({ model: "small", effort: null });
    expect(pickModel(models, null, "max")).toEqual({ model: null, effort: "max" });
  });
});
