"use client";

import { ChevronDown, CircleHelp } from "lucide-react";
import { usePathname } from "next/navigation";
import { getPageGuide } from "@/lib/page-guides";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  const pathname = usePathname();
  const guide = getPageGuide(pathname);

  return (
    <div className="mb-6 space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-extrabold uppercase tracking-[.24em] text-primary">Ithute Pay Bridge</p>
          <h1 className="mt-1 text-2xl font-black tracking-tight text-[var(--brand-navy)] dark:text-foreground sm:text-3xl">{title}</h1>
          {description && <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>

      {guide && (
        <details className="group overflow-hidden rounded-2xl border border-blue-100 bg-blue-50/45">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-bold text-[#082b4d] marker:content-none">
            <span className="flex items-center gap-2">
              <CircleHelp className="h-4 w-4 text-primary" />
              Page guide · what this screen is for
            </span>
            <ChevronDown className="h-4 w-4 text-primary transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-blue-100 px-4 py-4 text-sm leading-6 text-slate-700">
            <p>{guide.purpose}</p>
            <ol className="mt-3 grid gap-2 lg:grid-cols-3">
              {guide.steps.map((step, index) => (
                <li key={step} className="flex gap-2 rounded-xl border border-blue-100 bg-white/80 p-3">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-primary text-[11px] font-black text-primary-foreground">{index + 1}</span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
            {guide.note && <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">Important: {guide.note}</p>}
          </div>
        </details>
      )}
    </div>
  );
}
