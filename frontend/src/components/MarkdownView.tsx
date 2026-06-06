import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/cn";

interface MarkdownViewProps {
  source: string;
  className?: string;
}

// Dark-theme styling for every markdown element the reports use. Kept inline
// so we don't pull in the @tailwindcss/typography plugin.
const components: Components = {
  h1: ({ children }) => (
    <h1 className="mt-6 mb-3 text-2xl font-semibold text-slate-100 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-6 mb-2 border-b border-slate-800 pb-1 text-lg font-semibold text-slate-100">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-4 mb-1.5 text-base font-semibold text-slate-200">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="my-2 text-sm leading-relaxed text-slate-300">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="my-2 ml-5 list-disc space-y-1 text-sm text-slate-300">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 ml-5 list-decimal space-y-1 text-sm text-slate-300">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => (
    <strong className="font-semibold text-slate-100">{children}</strong>
  ),
  em: ({ children }) => <em className="italic text-slate-400">{children}</em>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-emerald-500/60 bg-slate-900/40 px-3 py-2 text-sm italic text-slate-300">
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }) => {
    const isInline = !/language-/.test(className ?? "");
    if (isInline) {
      return (
        <code
          className="rounded bg-slate-800 px-1 py-0.5 font-mono text-[12px] text-amber-300"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code
        className={cn(
          "block overflow-x-auto rounded-md border border-slate-800 bg-slate-950/70 p-3 font-mono text-[12px] text-slate-200",
          className,
        )}
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="my-3 overflow-x-auto">{children}</pre>,
  hr: () => <hr className="my-4 border-slate-800" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-emerald-400 underline-offset-2 hover:underline"
    >
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-slate-700 bg-slate-800/60 text-slate-300">
      {children}
    </thead>
  ),
  tbody: ({ children }) => (
    <tbody className="divide-y divide-slate-800">{children}</tbody>
  ),
  tr: ({ children }) => <tr>{children}</tr>,
  th: ({ children }) => (
    <th className="px-3 py-1.5 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-1.5 align-top text-slate-300">{children}</td>
  ),
};

export function MarkdownView({ source, className }: MarkdownViewProps) {
  return (
    <div className={cn("max-w-none", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
