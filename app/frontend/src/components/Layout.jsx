import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Radar, LayoutDashboard, Settings as SettingsIcon, LogOut, Plus } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";

export default function Layout({ children }) {
  const { user, workspaces, activeWs, switchWs, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const current = workspaces.find((w) => w.id === activeWs);

  const navItems = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard },
    { to: "/settings", label: "Settings", icon: SettingsIcon },
  ];

  return (
    <div className="min-h-screen bg-background grain flex">
      <aside className="w-60 border-r border-border bg-card/40 flex flex-col fixed h-full">
        <div className="p-5 border-b border-border flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-md bg-primary/15 border border-primary/30 flex items-center justify-center">
            <Radar className="h-4.5 w-4.5 text-primary" strokeWidth={2.2} />
          </div>
          <div>
            <div className="font-display font-extrabold text-sm tracking-tight leading-none">DisruptRadar</div>
            <div className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest mt-0.5">intel</div>
          </div>
        </div>

        <div className="p-3 border-b border-border">
          <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1.5 px-1">Workspace</div>
          <Select value={activeWs || ""} onValueChange={switchWs}>
            <SelectTrigger data-testid="workspace-switcher" className="w-full bg-secondary/50 border-border text-sm">
              <SelectValue placeholder="Select workspace" />
            </SelectTrigger>
            <SelectContent>
              {workspaces.map((w) => (
                <SelectItem key={w.id} value={w.id} data-testid={`workspace-option-${w.id}`}>
                  {w.name} <span className="text-muted-foreground">· {w.domain_count}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            data-testid="new-workspace-button"
            variant="ghost" size="sm"
            className="w-full mt-1.5 justify-start text-muted-foreground hover:text-foreground h-8"
            onClick={() => nav("/settings?new=1")}
          >
            <Plus className="h-3.5 w-3.5 mr-1.5" /> New workspace
          </Button>
        </div>

        <nav className="p-3 flex-1 space-y-1">
          {navItems.map((n) => {
            const active = loc.pathname === n.to;
            return (
              <button
                key={n.to}
                data-testid={`nav-${n.label.toLowerCase()}`}
                onClick={() => nav(n.to)}
                className={`w-full flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors ${active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"}`}
              >
                <n.icon className="h-4 w-4" /> {n.label}
              </button>
            );
          })}
        </nav>

        <div className="p-3 border-t border-border">
          <div className="flex items-center gap-2.5 px-2 mb-2">
            <div className="h-7 w-7 rounded-full bg-primary/15 border border-primary/30 flex items-center justify-center font-mono text-xs text-primary">
              {(user?.name || user?.email || "?")[0].toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-medium truncate">{user?.name}</div>
              <div className="text-[10px] text-muted-foreground truncate">{user?.email}</div>
            </div>
          </div>
          <Button data-testid="logout-button" variant="ghost" size="sm" className="w-full justify-start text-muted-foreground h-8" onClick={logout}>
            <LogOut className="h-3.5 w-3.5 mr-1.5" /> Sign out
          </Button>
        </div>
      </aside>

      <main className="flex-1 ml-60">{children}</main>
    </div>
  );
}