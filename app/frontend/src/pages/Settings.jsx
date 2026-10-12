import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import api, { formatApiError } from "@/lib/api";
import Layout from "@/components/Layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Slack, Bell, Briefcase, Loader2, Users, Mail, Crown, Trash2, Zap } from "lucide-react";

export default function Settings() {
  const { activeWs, workspaces, loadWorkspaces, switchWs, user } = useAuth();
  const [params] = useSearchParams();
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [newWsName, setNewWsName] = useState("");
  const [creating, setCreating] = useState(false);
  const [members, setMembers] = useState({ members: [], pending: [] });
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviting, setInviting] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [sendingDigest, setSendingDigest] = useState(false);

  const loadMembers = async () => {
    if (!activeWs) return;
    try { const { data } = await api.get(`/workspaces/${activeWs}/members`); setMembers(data); } catch { /* noop */ }
  };

  useEffect(() => {
    if (!activeWs) return;
    api.get(`/workspaces/${activeWs}/settings`).then(({ data }) => setSettings(data)).catch(() => {});
    loadMembers();
  }, [activeWs]);

  const invite = async () => {
    setInviting(true);
    try {
      const { data } = await api.post(`/workspaces/${activeWs}/invite`, { email: inviteEmail });
      toast.success(data.status === "added" ? "Member added" : "Invite sent");
      setInviteEmail("");
      loadMembers();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setInviting(false); }
  };

  const removeMember = async (uid) => {
    try { await api.delete(`/workspaces/${activeWs}/members/${uid}`); toast.success("Removed"); loadMembers(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const upgrade = async () => {
    setUpgrading(true);
    try {
      const { data } = await api.post("/billing/checkout", { workspace_id: activeWs });
      if (data.checkout_url) window.location.assign(data.checkout_url);
      else toast.error("No checkout URL returned");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setUpgrading(false); }
  };

  const sendDigest = async () => {
    setSendingDigest(true);
    try {
      const { data } = await api.post(`/workspaces/${activeWs}/digest/send`);
      if (data.ok) toast.success(`Digest sent to ${data.sent_to} (${data.movers} movers)`);
      else toast.message(data.reason || "Digest not sent", { description: `Recipient: ${data.sent_to}` });
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSendingDigest(false); }
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/workspaces/${activeWs}/settings`, settings);
      toast.success("Settings saved");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setSaving(false); }
  };

  const testSlack = async () => {
    if (!settings?.slack_webhook) { toast.error("Add a webhook URL first"); return; }
    await save();
    try {
      await api.post(`/workspaces/${activeWs}/slack/test`);
      toast.success("Test alert posted to Slack — HIGH-risk runs will auto-post here.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const createWs = async () => {
    setCreating(true);
    try {
      const { data } = await api.post("/workspaces", { name: newWsName });
      await loadWorkspaces();
      switchWs(data.id);
      setNewWsName("");
      toast.success("Workspace created");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    finally { setCreating(false); }
  };

  const current = workspaces.find((w) => w.id === activeWs);

  return (
    <Layout>
      <div className="p-4 sm:p-6 lg:p-8 max-w-3xl mx-auto">
        <div className="mb-6">
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-primary/80 mb-1.5">Configuration</div>
          <h1 className="font-display text-3xl font-extrabold tracking-tight">Settings</h1>
        </div>

        {/* workspace */}
        <Card className="bg-card border-border p-6 mb-6">
          <div className="font-display font-bold flex items-center gap-2 mb-4"><Briefcase className="h-4 w-4 text-primary" /> Workspace</div>
          <div className="flex items-center justify-between mb-4 pb-4 border-b border-border">
            <div>
              <div className="font-medium">{current?.name}</div>
              <div className="text-xs text-muted-foreground mt-0.5">Plan: <span className="uppercase font-mono">{current?.plan}</span> · {current?.domain_count} domains</div>
            </div>
          </div>
          <Label className="text-xs text-muted-foreground">Create new workspace</Label>
          <div className="flex gap-2 mt-1">
            <Input data-testid="new-workspace-input" value={newWsName} onChange={(e) => setNewWsName(e.target.value)} placeholder="Corporate Dev — Cybersecurity" className="bg-secondary/40" />
            <Button data-testid="create-workspace-button" onClick={createWs} disabled={creating || !newWsName}>
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create"}
            </Button>
          </div>
        </Card>

        {/* billing */}
        <Card className="bg-card border-border p-6 mb-6">
          <div className="font-display font-bold flex items-center gap-2 mb-4"><Crown className="h-4 w-4 text-amber-400" /> Plan & billing</div>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs uppercase px-2 py-0.5 rounded-full border border-border bg-secondary/50">{current?.plan || "free"}</span>
                <span className="text-sm text-muted-foreground">
                  {current?.plan === "pro" ? "50 domains · daily polling · Slack + email" : "3 domains · weekly polling"}
                </span>
              </div>
            </div>
            {current?.plan !== "pro" && (
              <Button data-testid="upgrade-pro-button" onClick={upgrade} disabled={upgrading} className="gap-1.5">
                {upgrading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Upgrade to Pro
              </Button>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground mt-3">Secure checkout via Dodo Payments (test mode). Your plan upgrades automatically once payment is confirmed.</p>
        </Card>

        {/* members */}
        <Card className="bg-card border-border p-6 mb-6">
          <div className="font-display font-bold flex items-center gap-2 mb-4"><Users className="h-4 w-4 text-primary" /> Members</div>
          <div className="space-y-2 mb-4">
            {members.members.map((m) => (
              <div key={m.user_id} data-testid={`member-${m.email}`} className="flex items-center justify-between py-1.5">
                <div className="flex items-center gap-2.5">
                  <div className="h-7 w-7 rounded-full bg-primary/15 border border-primary/30 flex items-center justify-center font-mono text-xs text-primary">{m.email[0].toUpperCase()}</div>
                  <div>
                    <div className="text-sm font-medium">{m.name || m.email}</div>
                    <div className="text-[11px] text-muted-foreground">{m.email}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] uppercase text-muted-foreground">{m.role}</span>
                  {m.role !== "owner" && (
                    <Button data-testid={`remove-member-${m.email}`} size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={() => removeMember(m.user_id)}>
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-red-400" />
                    </Button>
                  )}
                </div>
              </div>
            ))}
            {members.pending.map((p) => (
              <div key={p.id} data-testid={`pending-${p.email}`} className="flex items-center justify-between py-1.5 opacity-70">
                <div className="flex items-center gap-2.5">
                  <div className="h-7 w-7 rounded-full bg-secondary/60 flex items-center justify-center"><Mail className="h-3.5 w-3.5 text-muted-foreground" /></div>
                  <div className="text-sm">{p.email}</div>
                </div>
                <span className="font-mono text-[10px] uppercase text-amber-400">pending</span>
              </div>
            ))}
          </div>
          <Label className="text-xs text-muted-foreground">Invite a colleague by email</Label>
          <div className="flex gap-2 mt-1">
            <Input data-testid="invite-email-input" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="colleague@fund.vc" className="bg-secondary/40" />
            <Button data-testid="invite-button" onClick={invite} disabled={inviting || !inviteEmail}>
              {inviting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Invite"}
            </Button>
          </div>
        </Card>

        {/* digest */}
        <Card className="bg-card border-border p-6 mb-6">
          <div className="font-display font-bold flex items-center gap-2 mb-2"><Mail className="h-4 w-4 text-emerald-400" /> Weekly digest</div>
          <p className="text-sm text-muted-foreground mb-4">A summary of your top headcount movers is emailed to the workspace owner every Monday. Send one now to preview.</p>
          <Button data-testid="send-digest-button" variant="outline" onClick={sendDigest} disabled={sendingDigest}>
            {sendingDigest ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <Mail className="h-4 w-4 mr-1.5" />} Send digest now
          </Button>
        </Card>

        {/* alerts */}
        <Card className="bg-card border-border p-6 mb-6">
          <div className="font-display font-bold flex items-center gap-2 mb-4"><Bell className="h-4 w-4 text-amber-400" /> Alerts & thresholds</div>
          {!settings ? <Loader2 className="h-4 w-4 animate-spin" /> : (
            <div className="space-y-5">
              <div>
                <Label className="text-xs text-muted-foreground flex items-center gap-1.5"><Slack className="h-3.5 w-3.5" /> Slack incoming webhook</Label>
                <div className="flex gap-2 mt-1">
                  <Input
                    data-testid="slack-webhook-input"
                    value={settings.slack_webhook}
                    onChange={(e) => setSettings({ ...settings, slack_webhook: e.target.value })}
                    placeholder="https://hooks.slack.com/services/…"
                    className="bg-secondary/40"
                  />
                  <Button data-testid="test-slack-button" variant="outline" onClick={testSlack}>Save & test</Button>
                </div>
                <p className="text-[11px] text-muted-foreground mt-1.5">Alerts fire when risk = HIGH or headcount delta exceeds the threshold below.</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-xs text-muted-foreground">Delta threshold (%)</Label>
                  <Input
                    data-testid="threshold-input" type="number"
                    value={settings.delta_threshold}
                    onChange={(e) => setSettings({ ...settings, delta_threshold: parseFloat(e.target.value) || 0 })}
                    className="mt-1 bg-secondary/40"
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Polling cadence</Label>
                  <Select value={settings.cadence} onValueChange={(v) => setSettings({ ...settings, cadence: v })}>
                    <SelectTrigger data-testid="cadence-select" className="mt-1 bg-secondary/40"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="weekly">Weekly (Free)</SelectItem>
                      <SelectItem value="daily">Daily (Pro)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button data-testid="save-settings-button" onClick={save} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save settings"}
              </Button>
            </div>
          )}
        </Card>
      </div>
    </Layout>
  );
}