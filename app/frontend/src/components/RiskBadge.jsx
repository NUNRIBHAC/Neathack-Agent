export function RiskBadge({ risk, testid }) {
    if (!risk) return <span data-testid={testid} className="font-mono text-xs text-muted-foreground">—</span>;
    const map = {
      LOW: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
      MEDIUM: "bg-amber-500/10 text-amber-400 border-amber-500/30",
      HIGH: "bg-red-500/10 text-red-400 border-red-500/30",
    };
    const dot = { LOW: "bg-emerald-400", MEDIUM: "bg-amber-400", HIGH: "bg-red-400" };
    return (
      <span
        data-testid={testid || `risk-badge-${risk.toLowerCase()}`}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wider ${map[risk]} ${risk === "HIGH" ? "animate-[risk-halo_2s_ease-in-out_infinite]" : ""}`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${dot[risk]}`} />
        {risk}
      </span>
    );
  }
  
  export function DeltaPill({ value }) {
    if (value == null) return <span className="font-mono text-xs text-muted-foreground">—</span>;
    const up = value >= 0;
    return (
      <span className={`font-mono text-sm font-semibold ${up ? "text-emerald-400" : "text-red-400"}`}>
        {up ? "▲" : "▼"} {Math.abs(value).toFixed(1)}%
      </span>
    );
  }
  
  export function ScoreBar({ value, testid }) {
    if (value == null) return <span data-testid={testid} className="font-mono text-xs text-muted-foreground">—</span>;
    const color = value >= 70 ? "bg-red-400" : value >= 45 ? "bg-amber-400" : "bg-emerald-400";
    const text = value >= 70 ? "text-red-400" : value >= 45 ? "text-amber-400" : "text-emerald-400";
    return (
      <div data-testid={testid} className="flex items-center gap-2">
        <div className="h-1.5 w-14 rounded-full bg-secondary/80 overflow-hidden">
          <div className={`h-full ${color}`} style={{ width: `${Math.min(100, value)}%` }} />
        </div>
        <span className={`font-mono text-xs font-semibold ${text}`}>{value}</span>
      </div>
    );
  }  