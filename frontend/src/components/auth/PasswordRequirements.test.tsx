import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { PasswordRequirements } from "./PasswordRequirements";

describe("PasswordRequirements", () => {
  test("marks unmet rules and shows the username rule when a username is given", () => {
    render(<PasswordRequirements password="weak" username="alice" />);
    const list = screen.getByLabelText("Password requirements");
    // length rule unmet → uses the ○ marker
    expect(list.textContent).toContain("At least 12 characters");
    expect(list.textContent).toContain("Does not contain the username");
    expect(list.textContent).toContain("○");
  });

  test("a strong password satisfies every rule (all checks ✓)", () => {
    render(<PasswordRequirements password="Str0ng-Passw0rd!" username="alice" />);
    const list = screen.getByLabelText("Password requirements");
    expect(list.textContent).not.toContain("○");
    expect(list.textContent).toContain("✓");
  });
});
