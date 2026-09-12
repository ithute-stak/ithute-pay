"use client";

import Link from "next/link";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ChevronDown, ChevronLeft, ChevronRight, Grid2X2, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PLATFORM_NAV,
  PROVIDER_WORKSPACES,
  getProviderWorkspace,
  type ProviderId,
} from "@/lib/provider-workspaces";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setSelectedProvider, setSidebarCollapsed, toggleSidebar } from "@/store/ui-slice";

function NavLink({
  href,
  label,
  description,
  Icon,
  collapsed,
  onNavigate,
}: {
  href: string;
  label: string;
  description: string;
  Icon: any;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const path = usePathname();
  const exactOnly = href === "/dashboard/provider" || href === "/dashboard/testing";
  const active = exactOnly ? path === href : path === href || path.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      onClick={onNavigate}
      title={collapsed ? `${label} — ${description}` : undefined}
      aria-label={label}
      className={cn(
        "group flex rounded-xl transition-all duration-200",
        collapsed ? "h-11 items-center justify-center px-2" : "items-start gap-3 px-3 py-2.5",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0 transition-transform group-hover:scale-105", collapsed && "mt-0 h-[18px] w-[18px]")} />
      {!collapsed && (
        <span className="min-w-0">
          <span className="block truncate text-sm font-bold">{label}</span>
          <span className={cn("mt-0.5 block line-clamp-2 text-[10px] leading-4", active ? "text-primary-foreground/75" : "text-muted-foreground/75")}>{description}</span>
        </span>
      )}
    </Link>
  );
}

export function SidebarContent({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  collapsed?: boolean;
}) {
  const path = usePathname();
  const router = useRouter();
  const dispatch = useAppDispatch();
  const selectedProvider = useAppSelector((state) => state.ui.selectedProvider);
  const workspace = getProviderWorkspace(selectedProvider);
  const platformActive = PLATFORM_NAV.some((item) => path === item.href || path.startsWith(`${item.href}/`));

  useEffect(() => {
    if (selectedProvider || typeof window === "undefined") return;
    const saved = window.localStorage.getItem("ipb-selected-provider") as ProviderId | null;
    if (saved && PROVIDER_WORKSPACES.some((provider) => provider.id === saved)) dispatch(setSelectedProvider(saved));
  }, [dispatch, selectedProvider]);

  const changeProvider = (provider: ProviderId) => {
    dispatch(setSelectedProvider(provider));
    window.localStorage.setItem("ipb-selected-provider", provider);
    router.push("/dashboard/provider");
    onNavigate?.();
  };

  return (
    <div className="flex h-full flex-col border-r border-sidebar-border bg-sidebar/95 text-sidebar-foreground shadow-[10px_0_40px_rgba(6,43,85,.06)] backdrop-blur-xl">
      <div className={cn("border-b border-sidebar-border py-4", collapsed ? "px-2" : "px-4")}>
        <Link href="/dashboard" onClick={onNavigate} className={cn("flex items-center", collapsed ? "justify-center" : "gap-3")} title="Choose provider">
          <img src="/brand/ithute-pay-bridge-icon.svg" alt="Ithute Pay Bridge" className="h-11 w-11 shrink-0 rounded-2xl border border-sidebar-border bg-white p-1 shadow-sm" />
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate text-sm font-black text-sidebar-foreground">Ithute Pay Bridge</p>
              <p className="text-[10px] font-extrabold uppercase tracking-[.18em] text-primary">Provider-first console</p>
            </div>
          )}
        </Link>
      </div>

      {!collapsed && (
        <div className="border-b border-sidebar-border p-3">
          <label className="block rounded-2xl border border-sidebar-border bg-card/70 p-3 shadow-sm">
            <span className="text-[10px] font-black uppercase tracking-[.14em] text-muted-foreground">Active provider</span>
            <select
              value={selectedProvider ?? ""}
              onChange={(event) => event.target.value && changeProvider(event.target.value as ProviderId)}
              className="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm font-bold text-foreground outline-none focus:border-primary"
              aria-label="Switch active payment provider"
            >
              <option value="">Select a provider…</option>
              {PROVIDER_WORKSPACES.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
            </select>
            <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
              {workspace ? `${workspace.category} · ${workspace.country}. Menus below are limited to services relevant to ${workspace.shortName}.` : "Choose a provider to open its focused service menu."}
            </p>
          </label>
        </div>
      )}

      <nav className={cn("flex-1 overflow-y-auto py-3", collapsed ? "space-y-1 px-2" : "px-3")}>
        <NavLink href="/dashboard" label="Choose provider" description="Return to the provider landing screen." Icon={Grid2X2} collapsed={collapsed} onNavigate={onNavigate} />

        {workspace && (
          <div className={cn("mt-3", collapsed ? "space-y-1" : "space-y-1")}>
            {!collapsed && <p className="px-3 pb-1 text-[10px] font-black uppercase tracking-[.15em] text-muted-foreground">{workspace.shortName} workspace</p>}
            {workspace.services.map((item) => <NavLink key={item.href} {...item} Icon={item.icon} collapsed={collapsed} onNavigate={onNavigate} />)}
          </div>
        )}

        {collapsed ? (
          <div className="mt-3 space-y-1 border-t border-sidebar-border pt-3">
            {PLATFORM_NAV.map((item) => <NavLink key={item.href} {...item} Icon={item.icon} collapsed onNavigate={onNavigate} />)}
          </div>
        ) : (
          <details className="group mt-4" open={platformActive}>
            <summary className="flex cursor-pointer list-none items-center justify-between rounded-xl px-3 py-2 text-[10px] font-black uppercase tracking-[.15em] text-muted-foreground hover:bg-sidebar-accent marker:content-none">
              Platform administration
              <ChevronDown className="h-3.5 w-3.5 transition group-open:rotate-180" />
            </summary>
            <div className="mt-1 space-y-1">
              {PLATFORM_NAV.map((item) => <NavLink key={item.href} {...item} Icon={item.icon} collapsed={false} onNavigate={onNavigate} />)}
            </div>
          </details>
        )}
      </nav>

      <div className={cn("border-t border-sidebar-border", collapsed ? "p-2" : "p-4")}>
        {collapsed ? (
          <div className="grid place-items-center" title="Secure gateway console"><ShieldCheck className="h-5 w-5 text-[var(--brand-green)]" /></div>
        ) : (
          <div className="text-[11px] leading-5 text-muted-foreground">
            <div className="flex items-center gap-2 font-semibold text-foreground"><ShieldCheck className="h-4 w-4 text-[var(--brand-green)]" />Secure gateway console</div>
            <p className="mt-1">Provider context stays visible while you work.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export function Sidebar() {
  const dispatch = useAppDispatch();
  const collapsed = useAppSelector((state) => state.ui.sidebarCollapsed);

  useEffect(() => {
    const saved = window.localStorage.getItem("ipb-sidebar-collapsed");
    if (saved === "true" || saved === "false") dispatch(setSidebarCollapsed(saved === "true"));
  }, [dispatch]);

  const toggle = () => {
    const next = !collapsed;
    dispatch(toggleSidebar());
    window.localStorage.setItem("ipb-sidebar-collapsed", String(next));
  };

  return (
    <aside className={cn("sticky top-0 hidden h-screen shrink-0 transition-[width] duration-300 lg:block", collapsed ? "w-[84px]" : "w-[296px]")}>
      <SidebarContent collapsed={collapsed} />
      <button type="button" onClick={toggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="absolute -right-3 top-[74px] z-20 grid h-7 w-7 place-items-center rounded-full border border-sidebar-border bg-card text-muted-foreground shadow-md transition hover:border-primary/40 hover:text-primary">
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>
    </aside>
  );
}
