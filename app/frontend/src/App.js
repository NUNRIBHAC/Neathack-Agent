import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import { Loader2 } from "lucide-react";
import Auth from "@/pages/Auth";
import AuthCallback from "@/pages/AuthCallback";
import Dashboard from "@/pages/Dashboard";
import CompanyDetail from "@/pages/CompanyDetail";
import Settings from "@/pages/Settings";

function BillingReturn() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6 text-center">
      <div className="max-w-md">
        <h1 className="font-display text-2xl font-bold">Payment submitted</h1>
        <p className="text-muted-foreground mt-2">Your workspace upgrades to Pro once the payment is confirmed. Head back to the dashboard.</p>
        <a href="/" className="inline-block mt-5 text-primary hover:underline">Back to dashboard</a>
      </div>
    </div>
  );
}

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null)
    return <div className="min-h-screen bg-background flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  if (user === false) return <Navigate to="/login" replace />;
  return children;
}

function Public({ children }) {
  const { user } = useAuth();
  if (user === null)
    return <div className="min-h-screen bg-background flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  if (user) return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  const location = useLocation();
  if (location.hash?.includes("session_id=")) return <AuthCallback />;
  return (
    <Routes>
      <Route path="/login" element={<Public><Auth /></Public>} />
      <Route path="/billing/return" element={<BillingReturn />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/company/:itemId" element={<Protected><CompanyDetail /></Protected>} />
      <Route path="/settings" element={<Protected><Settings /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <div className="App dark">
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
        <Toaster position="top-right" theme="dark" />
      </AuthProvider>
    </div>
  );
}

export default App;