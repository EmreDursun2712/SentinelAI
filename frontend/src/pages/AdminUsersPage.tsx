import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { PasswordRequirements } from "@/components/auth/PasswordRequirements";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { ApiError, authApi } from "@/lib/api";
import { isStrongPassword } from "@/lib/auth/passwordPolicy";
import { useAuth } from "@/lib/auth/AuthContext";
import type { Role } from "@/lib/types";

const INPUT =
  "w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: { code?: string; details?: { issues?: string[] } } } | null;
    const code = body?.error?.code;
    if (code === "weak_password") {
      const issues = body?.error?.details?.issues ?? [];
      return issues.length ? `Weak password: ${issues.join(" ")}` : "Password is too weak.";
    }
    if (code === "conflict") return "That username already exists.";
    if (err.status === 403) return "You don't have permission to create users.";
  }
  return "Could not create the user. Please try again.";
}

export default function AdminUsersPage() {
  const { hasRole } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("VIEWER");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Admin-only page; bounce everyone else.
  if (!hasRole("ADMIN")) {
    return <Navigate to="/" replace />;
  }

  const strong = isStrongPassword(password, username);
  const canSubmit = username.trim().length > 0 && strong && !submitting;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setSubmitting(true);
    try {
      const created = await authApi.createUser(username.trim(), password, role);
      setSuccess(`Created ${created.username} (${created.role}).`);
      setUsername("");
      setPassword("");
      setRole("VIEWER");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Users"
        description="Create operator accounts. Passwords must meet the security policy."
      />
      <Card className="max-w-md" padding="lg">
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="new-username" className="block text-xs font-medium text-slate-400">
              Username
            </label>
            <input
              id="new-username"
              name="username"
              type="text"
              autoComplete="off"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={INPUT}
              placeholder="analyst-2"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="new-role" className="block text-xs font-medium text-slate-400">
              Role
            </label>
            <Select
              id="new-role"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="w-full"
            >
              <option value="VIEWER">VIEWER</option>
              <option value="ANALYST">ANALYST</option>
              <option value="ADMIN">ADMIN</option>
            </Select>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="new-password" className="block text-xs font-medium text-slate-400">
              Password
            </label>
            <input
              id="new-password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={INPUT}
              placeholder="••••••••••••"
            />
            <div className="pt-1">
              <PasswordRequirements password={password} username={username} />
            </div>
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-300"
            >
              {error}
            </p>
          )}
          {success && (
            <p
              role="status"
              className="rounded-md border border-emerald-900/60 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300"
            >
              {success}
            </p>
          )}

          <Button type="submit" variant="primary" className="w-full justify-center" disabled={!canSubmit}>
            {submitting ? "Creating…" : "Create user"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
