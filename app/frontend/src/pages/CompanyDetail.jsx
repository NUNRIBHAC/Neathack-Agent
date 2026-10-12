import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { formatApiError } from "@/lib/api";
import Layout from "@/components/Layout";
import { RiskBadge, DeltaPill } from "@/components/RiskBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { toast } from "sonner";
import { ArrowLeft, Play, ExternalLink, Loader2, Users, Clock, CheckCircle2, Zap, Briefcase, Banknote } from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

const RANGES = { "30D": 30, "90D": 90, "1Y": 365, ALL: 99999 };
const STAGES = ["plan", "fetch", "analyze", "verify", "risk", "report"];

function renderReport(md) {
  if (!md) return null;
  return md.split("\n").map((line, i) => {
    const t = line.trim();
    if (!t) return <div key={i} className="h-2" />;
    if (t.startsWith("### ")) return <h3 key={i} className="font-display font-bold text-base mt-3 mb-1">{t.slice(4)}</h3>;
    if (t.startsWith("## ")) return <h2 key={i} className="font-display font-bold text-lg mt-3 mb-1">{t.slice(3)}</h2>;
    const bold = t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    return <p key={i} className="text-sm text-foreground/90 leading-relaxed" dangerouslySetInnerHTML={{ __html: bold }} />;
  });
}

export default function CompanyDetail() {
  const { itemId } = useParams();
  const { activeWs } = useAuth();
  const nav = useNavigate();
  const [item, setItem] = useState(null);
  const [snaps, setSnaps] = useState([]);
  const [runs, setRuns] = useState([]);
  const [range, setRange] = useState("90D");
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, sn, r] = await Promise.all([
        api.get(`/watchlist/${itemId}`),
        api.get(`/watchlist/${itemId}/snapshots`),
        api.get(`/watchlist/${itemId}/runs`),
      ]);
      setItem(d.data); setSnaps(sn.data); setRuns(r.data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  }, [itemId]);

  useEffect(() => { load(); }, [load]);

  const runNow = async () => {
    setRunning(true);
    try {
      const { data: run } = await api.post("/runs/run-now", { workspace_id: activeWs, watchlist_item_id: itemId });
      toast.success(`${run.domain}: ${run.risk} risk`);
      await load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setRunning(false); }
  };

  const latest = item?.latest_run;
  const cutoff = Date.now() - RANGES[range] * 86400000;
  const chartData = snaps
    .filter((s) => new Date(s.captured_at).getTime() >= cutoff)
    .map((s) => ({ date: new Date(s.captured_at).toLocaleDateString("en", { month: "short", day: "numeric" }), headcount: s.headcount }));

  return (
    <Layout>
      <div className="p-4 sm:p-6 lg:p-8 max-w-[1400px] mx-auto">
        <button data-testid="back-button" onClick={() => nav("/")} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-4">
          <ArrowLeft className="h-4 w-4" /> Back to dashboard
        </button>

        <div className="flex items-start justify-between flex-wrap gap-4 mb-6">
          <div>
            <h1 className="font-display text-3xl font-extrabold tracking-tight">{item?.domain || "…"}</h1>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              {latest && <RiskBadge risk={latest.risk} />}
              {latest && <DeltaPill value={latest.delta_pct} />}
              {item?.tags?.map((t) => <span key={t} className="font-mono text-[9px] uppercase bg-secondary/60 text-muted-foreground px-1.5 py-0.5 rounded">{t}</span>)}
            </div>
          </div>
          <div className="flex gap-2">
            {latest?.trace_url && (
              <a href={latest.trace_url} target="_blank" rel="noreferrer">
                <Button variant="outline" data-testid="open-trace-button"><ExternalLink className="h-4 w-4 mr-1.5" /> Trace</Button>
              </a>
            )}
            <Button data-testid="run-analysis-button" onClick={runNow} disabled={running}>
              {running ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Play className="h-4 w-4 mr-1.5" />}
              Analyze now
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* chart */}
          <Card className="lg:col-span-8 bg-card border-border p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="font-display font-bold flex items-center gap-2"><Users className="h-4 w-4 text-primary" /> Headcount over time</div>
              <div className="flex gap-1 bg-secondary/40 rounded-md p-0.5">
                {Object.keys(RANGES).map((r) => (
                  <button
                    key={r} data-testid={`range-${r}`} onClick={() => setRange(r)}
                    className={`px-2.5 py-1 rounded font-mono text-[11px] ${range === r ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                  >{r}</button>
                ))}
              </div>
            </div>
            <div className="h-72" style={{ minHeight: 288 }}>
              {chartData.length === 0 ? (
                <div className="h-full flex items-center justify-center text-muted-foreground text-sm">No data in range</div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ left: -10, right: 10, top: 10 }}>
                    <defs>
                      <linearGradient id="hc" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(217 91% 60%)" stopOpacity={0.4} />
                        <stop offset="100%" stopColor="hsl(217 91% 60%)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(225 22% 18%)" vertical={false} />
                    <XAxis dataKey="date" stroke="hsl(215 18% 50%)" fontSize={11} tickLine={false} axisLine={false} minTickGap={30} />
                    <YAxis stroke="hsl(215 18% 50%)" fontSize={11} tickLine={false} axisLine={false} width={44} />
                    <Tooltip
                      contentStyle={{ background: "hsl(225 28% 11%)", border: "1px solid hsl(225 22% 22%)", borderRadius: 8, fontSize: 12 }}
                      labelStyle={{ color: "hsl(215 18% 70%)" }}
                    />
                    <Area type="monotone" dataKey="headcount" stroke="hsl(217 91% 60%)" strokeWidth={2} fill="url(#hc)" />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>

          {/* executive report */}
          <Card className="lg:col-span-4 bg-card border-border p-5">
            <div className="font-display font-bold mb-3">Executive briefing</div>
            {latest?.report ? (
              <div data-testid="executive-report" className="space-y-1">{renderReport(latest.report)}</div>
            ) : (
              <p className="text-sm text-muted-foreground">Run an analysis to generate the executive briefing.</p>
            )}
            {latest && (
              <div className="mt-4 pt-4 border-t border-border font-mono text-[11px] text-muted-foreground">
                source: {latest.source} · {latest.duration_ms}ms
              </div>
            )}
          </Card>

          {/* multi-signal breakdown */}
          <Card className="lg:col-span-12 bg-card border-border p-5" data-testid="signals-panel">
            <div className="font-display font-bold mb-4 flex items-center gap-2"><Zap className="h-4 w-4 text-primary" /> Disruption signals <span className="font-mono text-xs text-muted-foreground font-normal">v2 · headcount + hiring + funding</span></div>
            {!latest?.signals ? (
              <p className="text-sm text-muted-foreground">Run an analysis to compute the composite disruption score.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 flex flex-col justify-center items-center">
                  <div className="font-mono text-[10px] uppercase tracking-widest text-primary/80">Disruption score</div>
                  <div className="font-mono font-bold text-4xl mt-1">{latest.disruption_score}</div>
                  <div className="font-mono text-[10px] text-muted-foreground">out of 100</div>
                </div>
                <div className="rounded-lg border border-border bg-secondary/20 p-4">
                  <div className="flex items-center gap-1.5 text-sm font-semibold"><Users className="h-3.5 w-3.5 text-chart-1" /> Headcount</div>
                  <div className="font-mono text-2xl font-bold mt-2">{latest.signals.headcount?.growth_6m_pct}%</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">6-month growth · score {latest.signals.headcount?.score}</div>
                </div>
                <div className="rounded-lg border border-border bg-secondary/20 p-4">
                  <div className="flex items-center gap-1.5 text-sm font-semibold"><Briefcase className="h-3.5 w-3.5 text-chart-3" /> Hiring</div>
                  <div className="font-mono text-2xl font-bold mt-2">{latest.signals.hiring?.openings ?? "—"}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">open roles{latest.signals.hiring?.growth_pct != null ? ` · ${latest.signals.hiring.growth_pct}% growth` : ""} · score {latest.signals.hiring?.score}</div>
                </div>
                <div className="rounded-lg border border-border bg-secondary/20 p-4">
                  <div className="flex items-center gap-1.5 text-sm font-semibold"><Banknote className="h-3.5 w-3.5 text-chart-2" /> Funding</div>
                  <div className="font-mono text-lg font-bold mt-2 capitalize">{(latest.signals.funding?.last_round_type || "n/a").replace(/_/g, " ")}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    {latest.signals.funding?.last_round_amount_usd ? `$${(latest.signals.funding.last_round_amount_usd / 1e6).toFixed(0)}M` : "—"}
                    {latest.signals.funding?.last_fundraise_date ? ` · ${latest.signals.funding.last_fundraise_date}` : ""} · score {latest.signals.funding?.score}
                  </div>
                </div>
              </div>
            )}
          </Card>

          {/* run history */}
          <Card className="lg:col-span-12 bg-card border-border p-5">
            <div className="font-display font-bold mb-4 flex items-center gap-2"><Clock className="h-4 w-4 text-primary" /> Run history</div>
            {runs.length === 0 ? (
              <p className="text-sm text-muted-foreground">No runs yet.</p>
            ) : (
              <div className="space-y-3">
                {runs.map((r) => (
                  <div key={r.id} data-testid={`run-${r.id}`} className="flex items-center gap-4 py-2 border-b border-border/60 last:border-0">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    <div className="font-mono text-xs text-muted-foreground w-40 shrink-0">{new Date(r.created_at).toLocaleString()}</div>
                    <RiskBadge risk={r.risk} />
                    <div className="font-mono text-sm w-20">{r.headcount}</div>
                    <DeltaPill value={r.delta_pct} />
                    <div className="font-mono text-[11px] text-muted-foreground ml-auto">{r.duration_ms}ms · {r.source}</div>
                    {r.trace_url && <a href={r.trace_url} target="_blank" rel="noreferrer" className="text-primary"><ExternalLink className="h-3.5 w-3.5" /></a>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </Layout>
  );
}