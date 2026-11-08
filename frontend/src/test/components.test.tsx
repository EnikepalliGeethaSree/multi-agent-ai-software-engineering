import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { EMPTY_FILTERS, FindingsTable, applyFilters } from "../components/FindingsTable";
import { HBarChart } from "../components/HBarChart";
import { SuspectsPanel } from "../components/SuspectsPanel";
import { StatTile } from "../components/StatTile";
import { compact, duration, location, num, pct } from "../lib/format";
import { categoryData, severityData } from "../pages/ReviewDetail";
import { validateFile } from "../pages/NewReview";
import { FINDINGS, SUMMARY, finding } from "./fixtures";

describe("format helpers", () => {
  it("formats numbers, percentages and durations", () => {
    expect(compact(1284)).toBe("1,284");
    expect(compact(12900)).toBe("12.9K");
    expect(compact(4_200_000)).toBe("4.2M");
    expect(pct(0.1234, 1)).toBe("12.3%");
    expect(pct(null)).toBe("–");
    expect(num(0.53912)).toBe("0.539");
    expect(num(17)).toBe("17");
    expect(num(undefined)).toBe("–");
    expect(duration("2026-01-01T00:00:00Z", "2026-01-01T00:01:05Z")).toBe("1m 05s");
    expect(duration("2026-01-01T00:00:00Z", "2026-01-01T00:00:09Z")).toBe("9s");
    expect(location("a.py", 3, 3)).toBe("a.py:3");
    expect(location("a.py", 3, 7)).toBe("a.py:3-7");
  });
});

describe("HBarChart", () => {
  const data = [
    { key: "a", label: "Alpha", value: 6 },
    { key: "b", label: "Beta", value: 2 },
  ];

  it("renders labelled bars with values and scales widths to the max", () => {
    render(<HBarChart title="Counts" data={data} />);
    expect(screen.getByRole("heading", { name: "Counts" })).toBeInTheDocument();
    const alpha = screen.getByLabelText("Alpha: 6");
    expect(alpha).toBeInTheDocument();
    expect(screen.getByLabelText("Beta: 2")).toBeInTheDocument();
    const fills = document.querySelectorAll<HTMLElement>(".bar-fill");
    expect(fills[0].style.width).toBe("100%");
    expect(fills[1].style.width).toContain("33.33");
  });

  it("shows a tooltip on hover and focus", () => {
    render(<HBarChart title="Counts" data={data} valueLabel="Findings" />);
    fireEvent.mouseMove(screen.getByLabelText("Beta: 2"), { clientX: 10, clientY: 10 });
    const tip = screen.getByRole("tooltip");
    expect(within(tip).getByText("Beta")).toBeInTheDocument();
    expect(tip).toHaveTextContent("Findings: 2 (25%)");
    fireEvent.blur(screen.getByLabelText("Beta: 2"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("toggles an accessible table view", async () => {
    render(<HBarChart title="Counts" data={data} />);
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("Alpha")).toBeInTheDocument();
    expect(within(table).getByText("75%")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Chart" }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows the empty text when every value is zero", () => {
    render(<HBarChart title="Counts" data={[{ key: "a", label: "A", value: 0 }]} emptyText="No data here" />);
    expect(screen.getByText("No data here")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Table" })).not.toBeInTheDocument();
  });
});

describe("summary widgets", () => {
  it("severity data keeps ordinal order and category data is sorted", () => {
    expect(severityData(SUMMARY).map((d) => [d.key, d.value])).toEqual([
      ["critical", 0],
      ["high", 1],
      ["medium", 1],
      ["low", 1],
      ["info", 0],
    ]);
    expect(categoryData({ ...SUMMARY, by_category: { quality: 1, security: 4, bug: 0 } }).map((d) => d.key)).toEqual([
      "security",
      "quality",
    ]);
  });

  it("stat tile compacts numbers", () => {
    render(<StatTile label="Lines" value={12900} hint="hint" />);
    expect(screen.getByText("12.9K")).toBeInTheDocument();
    expect(screen.getByText("hint")).toBeInTheDocument();
  });
});

describe("findings", () => {
  it("applyFilters filters by severity, category, source, file and text", () => {
    const f = (over: Partial<typeof EMPTY_FILTERS>) => applyFilters(FINDINGS, { ...EMPTY_FILTERS, ...over }).map((x) => x.id);
    expect(f({})).toEqual(["CR-001", "CR-002", "CR-003"]); // priority order
    expect(f({ severities: new Set(["low"]) })).toEqual(["CR-003"]);
    expect(f({ category: "edge_case" })).toEqual(["CR-002"]);
    expect(f({ source: "llm" })).toEqual(["CR-001", "CR-002"]);
    expect(f({ file: "shop/db.py" })).toEqual(["CR-001", "CR-003"]);
    expect(f({ query: "cwe-89" })).toEqual(["CR-001"]);
    expect(applyFilters(FINDINGS, EMPTY_FILTERS, "location").map((x) => x.id)).toEqual(["CR-003", "CR-001", "CR-002"]);
  });

  it("shows what triggers a bug and how to reproduce it", async () => {
    const bug = finding({
      id: "BD-001",
      bug: {
        bug_type: "boundary",
        trigger: "values is an empty list",
        expected: "a clear error",
        actual: "ZeroDivisionError",
        root_cause: "No empty check.",
        repro_steps: ["Call mean([])"],
        involved_names: ["values"],
      },
    });
    render(<FindingsTable findings={[bug]} />);
    await userEvent.click(screen.getByRole("button", { name: "Expand BD-001" }));
    expect(screen.getByText("values is an empty list")).toBeInTheDocument();
    expect(screen.getByText("ZeroDivisionError")).toBeInTheDocument();
    expect(screen.getByText("Call mean([])")).toBeInTheDocument();
    expect(screen.getByText(/not run/)).toBeInTheDocument();
  });

  it("ranks suspects and says when the LLM could not", () => {
    const suspect = { rank: 1, file: "shop/cart.py", symbol: "total", start_line: 4, end_line: 5, score: 1, reasons: ["called by the test: total"], signals: [] };
    const found = { suspects: [suspect], candidates_considered: 3, candidates_shown: 0, ranked_by: "static", hypothesis: null, llm_failed: true, errors: [] };
    render(<SuspectsPanel found={found} />);
    expect(screen.getByText("total")).toBeInTheDocument();
    expect(screen.getByText("shop/cart.py:4")).toBeInTheDocument();
    expect(screen.getByText(/could not rank/)).toBeInTheDocument();
    expect(screen.getByText(/static signals from 3 candidates/)).toBeInTheDocument();
  });

  it("table filters, counts and expands a finding with its evidence, fix and test", async () => {
    render(<FindingsTable findings={FINDINGS} />);
    expect(screen.getByText("Showing 3 of 3 findings")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Medium/ }));
    expect(screen.getByText("Showing 1 of 3 findings")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    await userEvent.type(screen.getByLabelText("Search findings"), "nothing-matches");
    expect(screen.getByText("No findings match these filters.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Search findings"));

    await userEvent.click(screen.getByRole("button", { name: "Expand CR-001" }));
    expect(screen.getByText("Use parameterised queries.")).toBeInTheDocument();
    expect(screen.getByText(/treated as data/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CWE-89" })).toHaveAttribute(
      "href",
      "https://cwe.mitre.org/data/definitions/89.html",
    );
    expect(screen.getByText(/Proposed severity/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse CR-001" })).toHaveAttribute("aria-expanded", "true");
  });

  it("shows an empty state when there are no findings", () => {
    render(<FindingsTable findings={[]} />);
    expect(screen.getByText("No findings above the confidence threshold")).toBeInTheDocument();
  });
});

describe("upload validation", () => {
  const file = (name: string, size: number) => {
    const f = new File(["x"], name);
    Object.defineProperty(f, "size", { value: size });
    return f;
  };
  it("accepts zip/py within limits and rejects the rest", () => {
    expect(validateFile(file("repo.zip", 1000))).toBeNull();
    expect(validateFile(file("app.py", 10))).toBeNull();
    expect(validateFile(file("notes.txt", 10))).toMatch(/\.zip archive/);
    expect(validateFile(file("empty.py", 0))).toMatch(/empty/);
    expect(validateFile(file("big.py", 3 * 1024 * 1024))).toMatch(/2 MB/);
    expect(validateFile(file("huge.zip", 101 * 1024 * 1024))).toMatch(/100 MB/);
  });
});
