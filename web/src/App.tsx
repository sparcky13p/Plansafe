import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { UserMenu } from "./auth";
import { ProjectPage } from "./pages/ProjectPage";
import { Projects } from "./pages/Projects";
import { Suppliers } from "./pages/Suppliers";
import type { GenericItem, Me } from "./types";

interface AppData {
  me: Me | null;
  items: Record<string, GenericItem>;
}

const Ctx = createContext<AppData>({ me: null, items: {} });
export const useAppData = () => useContext(Ctx);

function useHashRoute() {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(location.hash || "#/");
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return hash.slice(1);
}

export function navigate(path: string) {
  location.hash = path;
}

export function App() {
  const route = useHashRoute();
  const [data, setData] = useState<AppData>({ me: null, items: {} });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<Me>("/api/me"), api<{ items: Record<string, GenericItem> }>("/api/catalog/items")])
      .then(([me, cat]) => setData({ me, items: cat.items }))
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  const projectMatch = route.match(/^\/p\/([0-9a-f]+)/);
  let page;
  if (projectMatch) page = <ProjectPage id={projectMatch[1]} />;
  else if (route.startsWith("/suppliers")) page = <Suppliers />;
  else page = <Projects />;

  return (
    <Ctx.Provider value={data}>
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="logo" aria-hidden>▲</span> PlanSafe
        </a>
        <nav>
          <a href="#/" className={!projectMatch && !route.startsWith("/suppliers") ? "active" : ""}>Projects</a>
          <a href="#/suppliers" className={route.startsWith("/suppliers") ? "active" : ""}>Suppliers</a>
        </nav>
        <UserMenu />
      </header>
      {data.me && <ServiceNotice me={data.me} />}
      <main className="container">{error ? <div className="alert error">Could not reach the API: {error}</div> : page}</main>
    </Ctx.Provider>
  );
}

function ServiceNotice({ me }: { me: Me }) {
  const missing = [];
  if (me.services.database === "sqlite") missing.push("local database");
  if (me.services.vision_model !== "muse") missing.push("hazard detection from drawing labels (vision model not connected)");
  if (missing.length === 0) return null;
  return <div className="notice">Running with: {missing.join(" · ")}</div>;
}
