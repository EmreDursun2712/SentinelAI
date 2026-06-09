import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { Modal } from "./Modal";

describe("Modal", () => {
  test("renders an accessible dialog with title + description when open", () => {
    render(
      <Modal open onClose={() => {}} title="Confirm thing" description="Are you sure?">
        <p>body</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // Labelled by the title, described by the description.
    expect(dialog).toHaveAccessibleName("Confirm thing");
    expect(screen.getByText("Are you sure?")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  test("does not render when closed", () => {
    render(
      <Modal open={false} onClose={() => {}} title="Hidden">
        <p>nope</p>
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("Escape closes when dismissable", () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="X" />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  test("Escape does NOT close when dismissable=false", () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="X" dismissable={false} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    // And no close button is offered.
    expect(screen.queryByRole("button", { name: /close dialog/i })).not.toBeInTheDocument();
  });

  test("close button invokes onClose", () => {
    const onClose = vi.fn();
    render(<Modal open onClose={onClose} title="X" />);
    fireEvent.click(screen.getByRole("button", { name: /close dialog/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  test("moves focus into the dialog on open", () => {
    render(
      <Modal open onClose={() => {}} title="X">
        <button type="button">Inside</button>
      </Modal>,
    );
    // The first focusable (the close button) receives focus.
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });
});
