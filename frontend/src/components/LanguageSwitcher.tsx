import { useTranslation } from "react-i18next";

import { SUPPORTED_LANGUAGES } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** Compact EN / TR toggle. Persists to localStorage via the i18n detector. */
export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const current = i18n.resolvedLanguage ?? i18n.language;

  return (
    <div
      className="flex items-center rounded-md border border-slate-800 bg-slate-900/60 p-0.5"
      role="group"
      aria-label={t("topbar.language")}
    >
      {SUPPORTED_LANGUAGES.map((lang) => {
        const active = current === lang.code;
        return (
          <button
            key={lang.code}
            type="button"
            onClick={() => i18n.changeLanguage(lang.code)}
            aria-pressed={active}
            className={cn(
              "rounded px-2 py-0.5 text-xs font-medium transition",
              active
                ? "bg-slate-700 text-slate-100"
                : "text-slate-400 hover:text-slate-200",
            )}
          >
            {lang.label}
          </button>
        );
      })}
    </div>
  );
}
