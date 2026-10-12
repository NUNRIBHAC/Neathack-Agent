import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Radar, Loader2 } from "lucide-react";
import { toast } from "sonner";

export default function AuthCallback() {
  const { googleSession } = useAuth();
  const nav = useNavigate();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const hash = window.location.hash || "";
    const sid = new URLSearchParams(hash.replace(/^#/, "")).get("session_id");
    if (!sid) { nav("/login", { replace: true }); return; }
    (async () => {
      try {
        await googleSession(sid);
        window.history.replaceState({}, document.title, "/");
        toast.success("Signed in with Google");
        nav("/", { replace: true });
      } catch (e) {
        toast.error("Google sign-in failed");
        nav("/login", { replace: true });
      }
    })();
  }, []);

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-4">
      <Radar className="h-8 w-8 text-primary animate-pulse" />
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="h-4 w-4 animate-spin" /> Completing sign-in…
      </div>
    </div>
  );
}