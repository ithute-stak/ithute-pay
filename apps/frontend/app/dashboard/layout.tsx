"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { RealtimeProvider } from "@/components/providers/realtime-provider";
import { useMeQuery } from "@/store/gateway-api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data, isLoading, isError } = useMeQuery();
  useEffect(() => { if (!isLoading && isError) router.replace("/login"); }, [isError,isLoading,router]);
  if (isLoading) return <div className="grid min-h-screen place-items-center bg-background"><div className="text-center"><img src="/brand/ithute-pay-bridge-icon.svg" className="mx-auto h-16 w-16 animate-pulse" alt=""/><p className="mt-3 text-sm font-semibold text-muted-foreground">Opening Ithute Pay Bridge…</p></div></div>;
  if (!data) return null;
  return <RealtimeProvider><div className="flex min-h-screen"><Sidebar/><div className="min-w-0 flex-1"><Topbar/><main className="mx-auto w-full max-w-[1700px] p-4 sm:p-6 lg:p-8">{children}</main></div></div></RealtimeProvider>;
}
