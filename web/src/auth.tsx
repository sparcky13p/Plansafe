import { ClerkProvider, SignIn, SignedIn, SignedOut, UserButton, useAuth } from "@clerk/clerk-react";
import { ReactNode, useEffect, useState } from "react";
import { setTokenGetter } from "./api";

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

export const authEnabled = Boolean(CLERK_KEY);

/** Wraps the app in Clerk sign-in when VITE_CLERK_PUBLISHABLE_KEY is set; otherwise passes through (dev mode). */
export function AuthGate({ children }: { children: ReactNode }) {
  if (!CLERK_KEY) return <>{children}</>;
  return (
    <ClerkProvider publishableKey={CLERK_KEY}>
      <SignedOut>
        <div className="signin">
          <h1>PlanSafe</h1>
          <p className="muted">Safety equipment plans from your drawings.</p>
          <SignIn routing="hash" />
        </div>
      </SignedOut>
      <SignedIn>
        <TokenBridge>{children}</TokenBridge>
      </SignedIn>
    </ClerkProvider>
  );
}

function TokenBridge({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setTokenGetter(() => getToken());
    setReady(true);
    return () => setTokenGetter(null);
  }, [getToken]);
  return ready ? <>{children}</> : null;
}

export function UserMenu() {
  return authEnabled ? <UserButton /> : <span className="badge">dev mode</span>;
}
