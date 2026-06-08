// Inline SVG icons (Heroicons-style outline). Avoids pulling in an icon dep.
// Pass any standard SVG props through `Props`.

import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement>;

const base = {
  fill: "none",
  viewBox: "0 0 24 24",
  strokeWidth: 1.75,
  stroke: "currentColor",
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function ShieldIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3l8 3v6c0 4.5-3 8.5-8 9-5-.5-8-4.5-8-9V6l8-3z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

export function DashboardIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  );
}

export function ServerIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="4" width="18" height="7" rx="1.5" />
      <rect x="3" y="13" width="18" height="7" rx="1.5" />
      <path d="M7 7.5h.01M7 16.5h.01" />
    </svg>
  );
}

export function AlertIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
      <path d="M10.3 3.86 1.82 18a2 2 0 0 0 1.7 3h16.96a2 2 0 0 0 1.7-3L13.7 3.86a2 2 0 0 0-3.4 0z" />
    </svg>
  );
}

export function ResponseIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9.5 12.5l2 2 3.5-4" />
    </svg>
  );
}

export function ReportIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
      <path d="M9 13h6" />
      <path d="M9 17h6" />
    </svg>
  );
}

export function IngestionIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M12 3v12" />
      <path d="M7 8l5-5 5 5" />
      <path d="M5 21h14" />
    </svg>
  );
}

export function CheckIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

export function CloseIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

export function RefreshIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 4v5h-5" />
    </svg>
  );
}

export function ChevronRightIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function SearchIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-5-5" />
    </svg>
  );
}

export function PlayIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M6 4v16l14-8z" />
    </svg>
  );
}

export function DocumentIcon(props: Props) {
  return ReportIcon(props);
}

export function ArrowRightIcon(props: Props) {
  return (
    <svg {...base} {...props}>
      <path d="M5 12h14" />
      <path d="M13 6l6 6-6 6" />
    </svg>
  );
}
