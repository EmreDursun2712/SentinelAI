import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { Button } from "@/components/ui/Button";
import { ConfirmProvider, useConfirm, type ConfirmOptions } from "./ConfirmProvider";

// useConfirm must be called *inside* the provider, so the trigger is its own component.
function Trigger({ opts }: { opts: ConfirmOptions }) {
  const confirm = useConfirm();
  return (
    <Button
      onClick={async () => {
        const res = await confirm(opts);
        const out = document.getElementById("out");
        if (out) out.textContent = JSON.stringify(res);
      }}
    >
      Open
    </Button>
  );
}

function renderHarness(opts: ConfirmOptions) {
  return render(
    <ConfirmProvider>
      <Trigger opts={opts} />
      <div id="out" />
    </ConfirmProvider>,
  );
}

describe("ConfirmProvider / useConfirm", () => {
  test("resolves confirmed=false on cancel", async () => {
    renderHarness({ title: "Delete?" });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(document.getElementById("out")?.textContent).toContain('"confirmed":false'),
    );
  });

  test("resolves confirmed=true on confirm", async () => {
    renderHarness({ title: "Proceed?" });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(document.getElementById("out")?.textContent).toContain('"confirmed":true'),
    );
  });

  test("requireReason gates confirm and returns the reason", async () => {
    renderHarness({ title: "Reject", requireReason: true, confirmLabel: "Reject action" });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");

    const confirmBtn = screen.getByRole("button", { name: "Reject action" });
    expect(confirmBtn).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "not a real threat" } });
    expect(confirmBtn).toBeEnabled();
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      const out = document.getElementById("out")?.textContent ?? "";
      expect(out).toContain('"confirmed":true');
      expect(out).toContain("not a real threat");
    });
  });

  test("typedConfirmation must match before confirm is enabled", async () => {
    renderHarness({
      title: "Approve LAB",
      typedConfirmation: "CONFIRM",
      confirmLabel: "Approve LAB action",
    });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("dialog");

    const confirmBtn = screen.getByRole("button", { name: "Approve LAB action" });
    expect(confirmBtn).toBeDisabled();

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "nope" } });
    expect(confirmBtn).toBeDisabled();
    fireEvent.change(input, { target: { value: "CONFIRM" } });
    expect(confirmBtn).toBeEnabled();
  });
});
