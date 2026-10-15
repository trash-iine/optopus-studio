import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AppMode } from "./components/AppMode";
import "./styles.css";

/** The studio, or a packaged app when the server runs one (docs/adr/0009). */
function Root() {
  const [mode, setMode] = useState<"studio" | "app" | null>(null);
  useEffect(() => {
    fetch("/api/mode")
      .then((response) => response.json())
      .then((body) => setMode(body.mode === "app" ? "app" : "studio"))
      .catch(() => setMode("studio"));
  }, []);
  if (mode === null) return null;
  return mode === "app" ? <AppMode /> : <App />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
