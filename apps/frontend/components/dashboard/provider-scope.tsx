"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowRightLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getProviderWorkspace } from "@/lib/provider-workspaces";
import { useAppSelector } from "@/store/hooks";

export function useProviderScopedRows<T extends Record<string, any>>(rows: T[], providerField = "provider") {
  const selectedProvider = useAppSelector((state) => state.ui.selectedProvider);
  return useMemo(() => {
    if (!selectedProvider) return rows;
    return rows.filter((row) => String(row?.[providerField] ?? "").toLowerCase() === selectedProvider);
  }, [providerField, rows, selectedProvider]);
}

export function ProviderScopeBar({ noun = "records" }: { noun?: string }) {
  const selectedProvider = useAppSelector((state) => state.ui.selectedProvider);
  const workspace = getProviderWorkspace(selectedProvider);
  if (!workspace) return null;

  return (
    <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-blue-100 bg-blue-50/45 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-[10px] font-black uppercase tracking-[.14em] text-primary">Provider scope</p>
        <p className="mt-0.5 text-sm font-bold text-[#082b4d]">Showing {noun} for {workspace.name} only</p>
        <p className="mt-0.5 text-xs text-muted-foreground">Switch provider to view the same workflow for another payment rail.</p>
      </div>
      <Button asChild variant="secondary" size="sm"><Link href="/dashboard"><ArrowRightLeft className="h-4 w-4" />Change provider</Link></Button>
    </div>
  );
}
