import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { MarkdownView } from "./MarkdownView";

describe("MarkdownView", () => {
  test("renders h1 / h2 / h3 with semantic heading roles", () => {
    render(<MarkdownView source={"# Top\n\n## Mid\n\n### Sub"} />);
    expect(screen.getByRole("heading", { level: 1, name: "Top" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Mid" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Sub" })).toBeInTheDocument();
  });

  test("renders GFM tables (the report uses these heavily)", () => {
    const md = [
      "| Field | Value |",
      "|-------|-------|",
      "| **Severity** | CRITICAL |",
      "| **Priority** | 92.0 |",
    ].join("\n");
    render(<MarkdownView source={md} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Field" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Value" })).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("92.0")).toBeInTheDocument();
  });

  test("renders bullet lists", () => {
    render(<MarkdownView source={"- one\n- two\n- three"} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("one");
  });

  test("renders inline code with a code element", () => {
    const { container } = render(<MarkdownView source={"Use `simulated=TRUE`."} />);
    const code = container.querySelector("code");
    expect(code).not.toBeNull();
    expect(code).toHaveTextContent("simulated=TRUE");
  });

  test("renders blockquotes", () => {
    render(<MarkdownView source={"> An evidence-based summary."} />);
    expect(screen.getByText("An evidence-based summary.")).toBeInTheDocument();
  });
});
