import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { formatApiError } from "@/lib/api";
import Layout from "@/components/Layout";
import { RiskBadge, DeltaPill, ScoreBar } from "@/components/RiskBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Plus, Play, Trash2, ExternalLink, Users, AlertTriangle, Activity, Loader2, Radar } from "lucide-react";

const STAGES = ["plan", "fetch", "analyze", "verify", "risk", "report"];

export default function Dashboard() {
  const { activeWs } = useAuth();
  const nav = useNavigate();
  const [data, setData] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [domain, setDomain] = useState("");
  const [tags, setTags] = useState("");
  const [adding, setAdding] = useState(false);
  const [runningId, setRunningId] = useState(null);
  const [runStage, setRunStage] = useState(0);

  const load = useCallback(async () => {
    if (!activeWs) return;
    try {
      const { data } = await api.get(`/workspaces/${activeWs}/dashboard`);
      setData(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  }, [activeWs]);

  useEffect(() => { setData(null); load(); }, [load]);

  const addDomain = async () => {
    setAdding(true);
    try {
      await api.post(`/workspaces/${activeWs}/watchlist`, {
        domain, tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      toast.success("Domain added to watchlist");
      setAddOpen(false); setDomain(""); setTags("");
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setAdding(false); }
  };

  const runNow = async (itemId) => {
    setRunningId(itemId); setRunStage(0);
    const timer = setInterval(() => setRunStage((s) => Math.min(s + 1, STAGES.length - 1)), 600);
    try {
      const { data: run } = await api.post("/runs/run-now", { workspace_id: activeWs, watchlist_item_id: itemId });
      clearInterval(timer);
      toast.success(`${run.domain}: ${run.risk} risk, ${run.delta_pct >= 0 ? "+" : ""}${run.delta_pct}%`);
      await load();
    } catch (e) {
      clearInterval(timer);
      toast.error(formatApiError(e.response?.data?.detail));
    } finally { setRunningId(null); }
  };

  const removeItem = async (id, e) => {
    e.stopPropagation();
    try { await api.delete(`/watchlist/${id}`); toast.success("Removed"); load(); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
  };

  const s = data?.summary;
  const metrics = [
    { label: "Tracked domains", value: s?.total ?? "—", icon: Users, color: "text-primary" },
    { label: "High movers", value: s?.high_movers ?? "—", icon: AlertTriangle, color: "text-red-400" },
    { label: "Medium signals", value: s?.risk_counts?.MEDIUM ?? "—", icon: Activity, color: "text-amber-400" },
    { label: "Stable", value: s?.risk_counts?.LOW ?? "—", icon: Radar, color: "text-emerald-400" },
  ];

  return (
    <Layout>
      <div className="p-4 sm:p-6 lg:p-8 max-w-[1400px] mx-auto">
        <div className="flex items-start justify-between flex-wrap gap-4 mb-6">
          <div>
            <div className="font-mono text-xs uppercase tracking-[0.2em] text-primary/80 mb-1.5">Intelligence Dashboard</div>
            <h1 className="font-display text-3xl font-extrabold tracking-tight">Watchlist</h1>
            <p className="text-muted-foreground text-sm mt-1">Headcount signals across your tracked domains</p>
          </div>
          <Dialog open={addOpen} onOpenChange={setAddOpen}>
            <DialogTrigger asChild>
              <Button data-testid="add-domain-button"><Plus className="h-4 w-4 mr-1.5" /> Add domain</Button>
            </DialogTrigger>
            <DialogContent className="bg-card border-border">
              <DialogHeader><DialogTitle className="font-display">Add domain to watchlist</DialogTitle></DialogHeader>
              <div className="space-y-4 py-2">
                <div>
                  <Label className="text-xs text-muted-foreground">Domain</Label>
                  <Input data-testid="watchlist-domain-input" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="stripe.com" className="mt-1 bg-secondary/40" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Tags (comma separated)</Label>
                  <Input data-testid="watchlist-tags-input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="fintech, series-b" className="mt-1 bg-secondary/40" />
                </div>
              </div>
              <DialogFooter>
                <Button data-testid="confirm-add-domain" onClick={addDomain} disabled={adding || !domain}>
                  {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : "Add to watchlist"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>

        {/* metrics */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {metrics.map((m) => (
            <Card key={m.label} data-testid={`metric-${m.label}`} className="bg-card border-border p-5">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{m.label}</span>
                <m.icon className={`h-4 w-4 ${m.color}`} />
              </div>
              <div className="font-mono font-bold text-3xl mt-3 tracking-tight">{m.value}</div>
            </Card>
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* table */}
          <Card className="lg:col-span-8 bg-card border-border overflow-hidden">
            <div className="px-5 py-4 border-b border-border font-display font-bold">Tracked companies</div>
            {!data ? (
              <div className="p-10 text-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin mx-auto" /></div>
            ) : data.companies.length === 0 ? (
              <div className="p-12 text-center">
                <Radar className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
                <p className="text-muted-foreground text-sm">No domains yet. Add your first competitor to start tracking.</p>
              </div>
            ) : (
              <div className="divide-y divide-border">
                <div className="grid grid-cols-12 gap-2 px-5 py-2.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  <div className="col-span-3">Domain</div>
                  <div className="col-span-2 text-right">Headcount</div>
                  <div className="col-span-2">Disruption</div>
                  <div className="col-span-2 text-right">Delta</div>
                  <div className="col-span-1">Risk</div>
                  <div className="col-span-2 text-right">Actions</div>
                </div>
                {data.companies.map((c) => {
                  const running = runningId === c.id;
                  return (
                    <div
                      key={c.id}
                      data-testid={`company-row-${c.domain}`}
                      onClick={() => nav(`/company/${c.id}`)}
                      className="grid grid-cols-12 gap-2 px-5 py-3.5 items-center hover:bg-secondary/30 cursor-pointer transition-colors group"
                    >
                      <div className="col-span-3 min-w-0">
                        <div className="font-medium text-sm truncate">{c.domain}</div>
                        <div className="flex gap-1 mt-1 flex-wrap">
                          {c.tags.slice(0, 3).map((t) => (
                            <span key={t} className="font-mono text-[9px] uppercase tracking-wide bg-secondary/60 text-muted-foreground px-1.5 py-0.5 rounded">{t}</span>
                          ))}
                        </div>
                      </div>
                      <div className="col-span-2 text-right font-mono font-semibold text-sm">{c.headcount ?? "—"}</div>
                      <div className="col-span-2"><ScoreBar value={c.disruption_score} testid={`disruption-${c.domain}`} /></div>
                      <div className="col-span-2 text-right"><DeltaPill value={c.delta_pct} /></div>
                      <div className="col-span-1"><RiskBadge risk={c.risk} /></div>
                      <div className="col-span-2 flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <Button
                          data-testid={`run-now-${c.domain}`}
                          size="sm" variant="ghost" className="h-8 w-8 p-0"
                          disabled={running} onClick={() => runNow(c.id)}
                        >
                          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : <Play className="h-3.5 w-3.5 text-primary" />}
                        </Button>
                        {c.trace_url && (
                          <a href={c.trace_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                            <Button size="sm" variant="ghost" className="h-8 w-8 p-0"><ExternalLink className="h-3.5 w-3.5 text-muted-foreground" /></Button>
                          </a>
                        )}
                        <Button data-testid={`delete-${c.domain}`} size="sm" variant="ghost" className="h-8 w-8 p-0" onClick={(e) => removeItem(c.id, e)}>
                          <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-red-400" />
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* pipeline + alerts */}
          <div className="lg:col-span-4 space-y-6">
            <Card className="bg-card border-border p-5">
              <div className="font-display font-bold mb-4">Agent pipeline</div>
              <div className="space-y-2.5">
                {STAGES.map((st, i) => {
                  const active = runningId && runStage === i;
                  const done = runningId && runStage > i;
                  return (
                    <div key={st} className="flex items-center gap-3">
                      <div className={`h-6 w-6 rounded-md flex items-center justify-center font-mono text-[10px] border ${active ? "border-primary text-primary animate-[scan-pulse_1s_ease-in-out_infinite]" : done ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10" : "border-border text-muted-foreground"}`}>
                        {i + 1}
                      </div>
                      <span className={`text-sm capitalize ${active ? "text-primary font-medium" : done ? "text-foreground" : "text-muted-foreground"}`}>{st}</span>
                      {active && <Loader2 className="h-3 w-3 animate-spin text-primary ml-auto" />}
                    </div>
                  );
                })}
              </div>
              {!runningId && <p className="text-xs text-muted-foreground mt-4">Hit ▶ on any company to run the loop.</p>}
            </Card>

            <Card className="bg-card border-border p-5">
              <div className="font-display font-bold mb-4 flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-400" /> Recent alerts</div>
              {!data?.alerts?.length ? (
                <p className="text-xs text-muted-foreground">No material signals yet.</p>
              ) : (
                <div className="space-y-3">
                  {data.alerts.map((a, i) => (
                    <div key={i} data-testid={`alert-${i}`} className="flex items-start gap-2.5">
                      <RiskBadge risk={a.risk} />
                      <div className="min-w-0">
                        <div className="text-xs font-medium truncate">{a.domain}</div>
                        <div className="text-[11px] text-muted-foreground">{a.message}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      </div>
    </Layout>
  );
}