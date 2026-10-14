import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "@testing-library/react";
import { RouteMap } from "./RouteMap";
import { Kpi, Table } from "./simple";

afterEach(cleanup);

describe("simple views", () => {
  it("compacts large KPI values and shows the unit", () => {
    render(
      <Kpi
        view={{
          type: "kpi",
          title: null,
          items: [{ label: "Cost", value: 12900, unit: "yen" }],
        }}
      />,
    );
    expect(screen.getByText("12.9K")).toBeTruthy();
    expect(screen.getByText("yen")).toBeTruthy();
  });

  it("marks booleans and right-aligns numbers in tables", () => {
    const { container } = render(
      <Table
        view={{
          type: "table",
          title: null,
          columns: ["item", "weight", "packed"],
          rows: [["tent", 10, true]],
        }}
      />,
    );
    expect(screen.getByText("✓")).toBeTruthy();
    expect(container.querySelector("td.num")?.textContent).toBe("10");
  });
});

describe("RouteMap", () => {
  it("closes each route and draws a legend for two routes", () => {
    const { container } = render(
      <RouteMap
        mode="light"
        view={{
          type: "route_map",
          title: null,
          closed: true,
          points: [
            { id: 0, x: 0, y: 0, label: "depot", kind: "depot" },
            { id: 1, x: 1, y: 0, label: null, kind: "node" },
            { id: 2, x: 0, y: 1, label: null, kind: "node" },
          ],
          routes: [
            { path: [0, 1], label: "truck A" },
            { path: [0, 2], label: "truck B" },
          ],
        }}
      />,
    );
    const lines = container.querySelectorAll("polyline");
    expect(lines).toHaveLength(2);
    expect(lines[0].getAttribute("points")?.split(" ")).toHaveLength(3);
    expect(container.querySelector(".legend")?.textContent).toBe("truck Atruck B");
    expect(container.querySelectorAll("rect")).toHaveLength(1);
  });
});
