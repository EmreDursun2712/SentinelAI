import { passwordChecklist } from "@/lib/auth/passwordPolicy";
import { cn } from "@/lib/cn";

interface Props {
  password: string;
  username?: string;
}

/** Live checklist of the password policy. Each rule turns green when satisfied. */
export function PasswordRequirements({ password, username }: Props) {
  const checks = passwordChecklist(password, username);
  return (
    <ul className="space-y-1 text-xs" aria-label="Password requirements">
      {checks.map((c) => (
        <li
          key={c.label}
          className={cn("flex items-center gap-1.5", c.ok ? "text-emerald-400" : "text-slate-500")}
        >
          <span aria-hidden className="font-mono">
            {c.ok ? "✓" : "○"}
          </span>
          <span>{c.label}</span>
        </li>
      ))}
    </ul>
  );
}
