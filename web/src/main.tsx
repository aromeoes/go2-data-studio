import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./app/components.css";
import "./app/layout.css";
import "./app/theme.css";
import { robot } from "./sdk";
import { App } from "./app/App";

// Steam launch selects the controller as input. Driving still needs L1.
if (new URLSearchParams(window.location.search).get("input") === "controller") {
  robot.selectInput("controller");
}

const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
