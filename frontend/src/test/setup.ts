// Vitest setup — runs once before any test file.
// - Extends `expect` with @testing-library/jest-dom matchers (toBeInTheDocument, …).
// - Manually wires `cleanup` because we disabled vitest globals (`globals: false`)
//   so RTL's auto-cleanup hook isn't installed for us.

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
