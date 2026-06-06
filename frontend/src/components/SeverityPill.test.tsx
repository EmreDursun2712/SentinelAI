import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { SeverityPill } from "./SeverityPill";

describe("SeverityPill", () => {
  test("renders each severity label as visible text", () => {
    for (const severity of ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const) {
      const { unmount } = render(<SeverityPill severity={severity} />);
      expect(screen.getByText(severity)).toBeInTheDocument();
      unmount();
    }
  });

  test("renders UNRATED when severity is null", () => {
    render(<SeverityPill severity={null} />);
    expect(screen.getByText("UNRATED")).toBeInTheDocument();
  });

  test("renders UNRATED when severity is undefined", () => {
    render(<SeverityPill severity={undefined} />);
    expect(screen.getByText("UNRATED")).toBeInTheDocument();
  });

  test("applies severity-specific color class for CRITICAL", () => {
    const { container } = render(<SeverityPill severity="CRITICAL" />);
    // CRITICAL maps to the rose palette — guards against accidentally
    // recoloring critical alerts during a theme refactor.
    expect(container.firstChild).toHaveClass("text-rose-300");
  });
});
