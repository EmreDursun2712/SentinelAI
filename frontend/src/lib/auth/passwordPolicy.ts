// Password policy — mirrors backend app/core/password_policy.py.
//   - at least 12 characters,
//   - at least 3 of 4 categories: lowercase, uppercase, number, symbol,
//   - must not contain the username (case-insensitive).
// Client-side validation is UX only; the backend is the source of truth.

export const MIN_LENGTH = 12;
export const MIN_CATEGORIES = 3;

export interface PasswordCheck {
  label: string;
  ok: boolean;
}

function categoryCount(password: string): number {
  let n = 0;
  if (/[a-z]/.test(password)) n++;
  if (/[A-Z]/.test(password)) n++;
  if (/[0-9]/.test(password)) n++;
  if (/[^A-Za-z0-9]/.test(password)) n++;
  return n;
}

/** Live checklist for a password (and optional username), for UI display. */
export function passwordChecklist(password: string, username?: string): PasswordCheck[] {
  const checks: PasswordCheck[] = [
    { label: `At least ${MIN_LENGTH} characters`, ok: password.length >= MIN_LENGTH },
    {
      label: `${MIN_CATEGORIES}+ of: lowercase, uppercase, number, symbol`,
      ok: categoryCount(password) >= MIN_CATEGORIES,
    },
  ];
  if (username && username.trim()) {
    checks.push({
      label: "Does not contain the username",
      ok: !password.toLowerCase().includes(username.trim().toLowerCase()),
    });
  }
  return checks;
}

/** Human-readable policy violations (empty ⇒ valid). */
export function passwordIssues(password: string, username?: string): string[] {
  return passwordChecklist(password, username)
    .filter((c) => !c.ok)
    .map((c) => c.label);
}

export function isStrongPassword(password: string, username?: string): boolean {
  return passwordIssues(password, username).length === 0;
}
