import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import { applyTheme } from "./lib/hooks";

// Apply the saved theme before first paint to avoid a flash of the wrong theme.
try {
  const saved = localStorage.getItem("theme");
  if (saved === "light" || saved === "dark") applyTheme(saved);
} catch {
  /* storage unavailable */
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
