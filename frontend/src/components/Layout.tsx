// components/Layout.tsx - app shell: left navigation grouped by the NOC workflow
// (Monitor -> Diagnose -> Restore -> Knowledge & Reports) and the page content area.
import { NavLink, Outlet } from "react-router-dom";
import { Activity, AlertTriangle, BookOpen, Boxes, CheckSquare, ClipboardList, FileText, Gauge, GitBranch,
         Layers, ListChecks, Network, Search, ShieldCheck, Bot, Wrench } from "lucide-react";
import { usePoll } from "../hooks";

const NAV = [
  { group: "Monitor", items: [
    ["/", "NOC Dashboard", Gauge], ["/alarms", "Alarm Console", AlertTriangle], ["/performance", "Performance", Activity],
    ["/topology", "Network Topology", Network], ["/inventory", "Network Inventory", Boxes]] },
  { group: "Diagnose", items: [
    ["/incidents", "Incident Center", Layers], ["/fault", "Fault Localization", Search], ["/impact", "Service Impact", GitBranch],
    ["/rca", "Root Cause Analysis", ClipboardList], ["/agents", "Agent Execution", Bot]] },
  { group: "Restore", items: [
    ["/restoration", "Restoration Planning", Wrench], ["/approvals", "Approval Center", ShieldCheck], ["/actions", "Action Tracker", ListChecks]] },
  { group: "Knowledge & reports", items: [["/knowledge", "Knowledge Base", BookOpen], ["/reports", "Incident Reports", FileText]] },
] as const;

export default function Layout() {
  const { data } = usePoll<any>("/api/dashboard", 6000);
  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      <aside className="md:w-60 shrink-0 border-b md:border-b-0 md:border-r border-line bg-[#0B1320]">
        <div className="px-4 py-4 border-b border-line">
          <div className="text-sm font-semibold leading-tight">NOC Decision Support</div>
          <div className="text-xs text-mute">Agentic fault diagnosis &amp; restoration</div>
        </div>
        <nav className="p-2 flex md:block gap-2 overflow-x-auto">
          {NAV.map((g) => (
            <div key={g.group} className="mb-3 shrink-0">
              <div className="px-2 py-1 text-[11px] text-mute">{g.group}</div>
              {g.items.map(([to, label, Icon]) => (
                <NavLink key={to} to={to} end={to === "/"}
                  className={({ isActive }) => `flex items-center gap-2 px-2 py-1.5 rounded text-sm whitespace-nowrap ${isActive ? "bg-sig/15 text-sig" : "text-txt/85 hover:bg-line/40"}`}>
                  <Icon size={15} /> {label}
                  {to === "/approvals" && data?.pending_approvals > 0 && <span className="ml-auto text-[11px] bg-crit text-white rounded px-1">{data.pending_approvals}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="hidden md:block px-4 py-3 text-[11px] text-mute border-t border-line">
          LLM: {data?.llm?.enabled ? <span className="text-ok">{data.llm.model}</span> : <span className="text-major">rule-based fallback</span>}
          <div className="mt-1 flex items-center gap-1"><CheckSquare size={11} /> Recommends only - never changes devices</div>
        </div>
      </aside>
      <main className="flex-1 p-4 md:p-6 min-w-0"><Outlet /></main>
    </div>
  );
}
