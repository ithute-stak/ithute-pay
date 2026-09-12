"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Bell, Menu, Radio, UserCircle2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SidebarContent } from "./sidebar";
import { Button } from "@/components/ui/button";
import { PROVIDER_WORKSPACES, getProviderWorkspace, type ProviderId } from "@/lib/provider-workspaces";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedProvider } from "@/store/ui-slice";
import { useLogoutMutation, useMeQuery } from "@/store/gateway-api";

export function Topbar() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const dispatch = useAppDispatch();
  const { data: user } = useMeQuery();
  const [logout] = useLogoutMutation();
  const realtime = useAppSelector((s) => s.realtime);
  const selectedProvider = useAppSelector((s) => s.ui.selectedProvider);
  const workspace = getProviderWorkspace(selectedProvider);

  const changeProvider = (provider: ProviderId) => {
    dispatch(setSelectedProvider(provider));
    window.localStorage.setItem("ipb-selected-provider", provider);
    router.push("/dashboard/provider");
  };

  const doLogout = async () => {
    try {
      await logout().unwrap();
    } finally {
      dispatch(setSelectedProvider(null));
      window.localStorage.removeItem("ipb-selected-provider");
      router.replace("/login");
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-border/70 bg-background/90 backdrop-blur-xl">
      <div className="flex min-h-16 items-center gap-3 px-4 py-2 sm:px-6 lg:px-8">
        <Dialog.Root open={open} onOpenChange={setOpen}>
          <Dialog.Trigger asChild>
            <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation"><Menu className="h-5 w-5" /></Button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-[var(--brand-navy)]/45 backdrop-blur-sm" />
            <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-[310px] shadow-2xl">
              <Dialog.Title className="sr-only">Navigation</Dialog.Title>
              <SidebarContent onNavigate={() => setOpen(false)} />
              <Dialog.Close className="absolute right-3 top-3 grid h-9 w-9 place-items-center rounded-xl border bg-card/90 text-foreground shadow-sm"><X className="h-4 w-4" /></Dialog.Close>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

        <div className="hidden min-w-0 sm:block">
          <p className="truncate text-xs font-black uppercase tracking-[.12em] text-muted-foreground">Payment provider</p>
          <p className="truncate text-sm font-black text-[var(--brand-navy)]">{workspace?.name ?? "Choose a provider"}</p>
        </div>

        <div className="min-w-0 flex-1 sm:max-w-[320px]">
          <label className="sr-only" htmlFor="topbar-provider-switch">Switch payment provider</label>
          <select
            id="topbar-provider-switch"
            value={selectedProvider ?? ""}
            onChange={(event) => event.target.value && changeProvider(event.target.value as ProviderId)}
            className="w-full rounded-xl border border-border bg-card px-3 py-2 text-sm font-bold text-foreground shadow-sm outline-none transition focus:border-primary"
          >
            <option value="">Switch provider…</option>
            {PROVIDER_WORKSPACES.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
          </select>
        </div>

        <div className="ml-auto hidden items-center gap-2 rounded-full border border-border/70 bg-card/80 px-3 py-1.5 text-xs font-semibold shadow-xs md:flex">
          <Radio className={`h-3.5 w-3.5 ${realtime.connected ? "text-[var(--brand-green)]" : "text-amber-500"}`} />
          {realtime.connected ? "Live updates" : "Connecting"}
        </div>

        <div className="relative hidden md:block">
          <Button variant="ghost" size="icon" aria-label="Realtime notifications"><Bell className="h-5 w-5" /></Button>
          {realtime.unread > 0 && <span className="absolute right-0 top-0 grid h-5 min-w-5 place-items-center rounded-full bg-destructive px-1 text-[10px] font-bold text-white">{Math.min(realtime.unread, 99)}</span>}
        </div>

        <div className="hidden text-right xl:block">
          <p className="max-w-[190px] truncate text-xs font-bold text-[var(--brand-navy)]">{user?.full_name || "Platform user"}</p>
          <p className="text-[11px] capitalize text-muted-foreground">{user?.role?.replaceAll("_", " ")}</p>
        </div>

        <Button variant="secondary" size="sm" onClick={doLogout}><UserCircle2 className="h-4 w-4" /><span className="hidden sm:inline">Sign out</span></Button>
      </div>
    </header>
  );
}
