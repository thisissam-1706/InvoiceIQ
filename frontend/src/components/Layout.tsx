import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api, Health } from "../api";
import { DashboardIcon, DatabaseIcon, GearIcon, PlusIcon } from "./Icons";

const NAV = [
  { to: "/", label: "Dashboard", icon: DashboardIcon, end: true },
  { to: "/new", label: "New Run", icon: PlusIcon, end: false },
  { to: "/reference", label: "Reference Data", icon: DatabaseIcon, end: false },
  { to: "/settings", label: "Settings", icon: GearIcon, end: false },
];

export default function Layout() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(() => setHealth(null));
    load();
    const t = window.setInterval(load, 10000);
    return () => window.clearInterval(t);
  }, []);

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 flex w-56 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">IQ</div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight">InvoiceIQ</div>
            <div className="text-[11px] text-slate-500">AP invoice agent</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 px-5 py-4 text-[11px] leading-5 text-slate-500">
          {health ? (
            <>
              <div className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${health.status === "ok" ? "bg-emerald-500" : "bg-amber-500"}`} />
                <span className="font-medium text-slate-700">{health.provider}</span>
                <span className="truncate">· {health.model}</span>
              </div>
              <div>LLM cache {health.cache_enabled ? `on (${health.cache_entries})` : "off"}</div>
              {health.provider_note && (
                <div className="mt-1 text-amber-700" title={health.provider_note}>
                  {health.configured_provider} key missing → offline
                </div>
              )}
            </>
          ) : (
            <div className="text-rose-600">API unreachable</div>
          )}
        </div>
      </aside>
      <main className="ml-56 min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}
