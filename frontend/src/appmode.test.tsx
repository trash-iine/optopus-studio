import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { formOf, parameterValues } from "./appmode";
import type { AppParameter } from "./generated/app-info";

afterEach(cleanup);

const parameters: AppParameter[] = [
  { name: "capacity", label: "Capacity", type: "number", target: "instance.capacity", description: null, min: 0, max: null, choices: null, unit: "kg" },
  { name: "strict", label: "Strict", type: "boolean", target: "instance.strict", description: null, min: null, max: null, choices: null, unit: null },
  { name: "runs", label: "Runs", type: "integer", target: "solve.runs", description: null, min: 1, max: 20, choices: null, unit: null },
];

describe("app parameters", () => {
  it("sends what the user set and leaves a blank field to the packaged value", () => {
    expect(parameterValues(parameters, { capacity: " 12 ", strict: false, runs: "" })).toEqual({
      capacity: "12",
      strict: false,
    });
    expect(parameterValues(parameters, {})).toEqual({});
  });

  it("fills the form from a case's stored values", () => {
    expect(formOf({ capacity: 12, strict: true })).toEqual({ capacity: "12", strict: true });
  });
});

