import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Radar, TrendingUp, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

export default function Auth() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name || "Analyst");
      toast.success(mode === "login" ? "Welcome back" : "Account created");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background grain flex">
      {/* left brand panel */}
      <div className="hidden lg:flex flex-col justify-between w-[46%] border-r border-border p-12 bg-card/30">
        <div className="flex items-center gap-2.5">
          <div className="h-9 w-9 rounded-md bg-primary/15 border border-primary/30 flex items-center justify-center">
            <Radar className="h-5 w-5 text-primary" strokeWidth={2.2} />
          </div>
          <span className="font-display font-extrabold tracking-tight text-lg">DisruptRadar</span>
        </div>
        <div className="max-w-md">
          <div className="font-mono text-xs uppercase tracking-[0.2em] text-primary/80 mb-4">Competitive Intelligence · VC Deal Flow</div>
          <h1 className="font-display text-4xl lg:text-5xl font-extrabold tracking-tight leading-[1.05]">
            Track headcount signals before the market does.
          </h1>
          <p className="text-muted-foreground mt-5 leading-relaxed">
            Watchlist any domain. The agent runs the plan → fetch → analyze → verify → risk → report loop and surfaces material movers to your dashboard.
          </p>
          <div className="mt-8 space-y-3">
            {[["TrendingUp", "Weekly & daily headcount polling"], ["ShieldAlert", "LOW / MEDIUM / HIGH risk classification"]].map(([_, t], i) => (
              <div key={i} className="flex items-center gap-3 text-sm text-foreground/90">
                {i === 0 ? <TrendingUp className="h-4 w-4 text-emerald-400" /> : <ShieldAlert className="h-4 w-4 text-amber-400" />}
                {t}
              </div>
            ))}
          </div>
        </div>
        <div className="font-mono text-[11px] text-muted-foreground">© 2026 DisruptRadar Intelligence</div>
      </div>

      {/* form */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-sm animate-fade-up">
          <div className="lg:hidden flex items-center gap-2.5 mb-8 justify-center">
            <Radar className="h-6 w-6 text-primary" />
            <span className="font-display font-extrabold text-lg">DisruptRadar</span>
          </div>
          <h2 className="font-display text-2xl font-bold tracking-tight">{mode === "login" ? "Sign in" : "Create account"}</h2>
          <p className="text-sm text-muted-foreground mt-1 mb-6">
            {mode === "login" ? "Access your intelligence dashboard" : "Start tracking competitors in minutes"}
          </p>

          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div>
                <Label className="text-xs text-muted-foreground">Name</Label>
                <Input data-testid="auth-name-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Analyst" className="mt-1 bg-secondary/40" />
              </div>
            )}
            <div>
              <Label className="text-xs text-muted-foreground">Email</Label>
              <Input data-testid="auth-email-input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@fund.vc" className="mt-1 bg-secondary/40" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Password</Label>
              <Input data-testid="auth-password-input" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" className="mt-1 bg-secondary/40" />
            </div>
            <Button data-testid="auth-submit-button" type="submit" disabled={loading} className="w-full font-medium">
              {loading ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <div className="flex items-center gap-3 my-5">
            <div className="h-px flex-1 bg-border" />
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">or</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <Button
            data-testid="google-login-button"
            variant="outline"
            className="w-full font-medium gap-2"
            onClick={() => {
              // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
              const redirectUrl = window.location.origin + "/";
              window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"/><path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"/></svg>
            Continue with Google
          </Button>

          <div className="text-center mt-5 text-sm text-muted-foreground">
            {mode === "login" ? "No account? " : "Already have one? "}
            <button
              data-testid="auth-toggle-mode"
              className="text-primary hover:underline font-medium"
              onClick={() => setMode(mode === "login" ? "register" : "login")}
            >
              {mode === "login" ? "Sign up" : "Sign in"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
