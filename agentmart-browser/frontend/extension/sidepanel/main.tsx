import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "../../src/styles.css";
import "./sidepanel.css";

const container = document.getElementById("root");
if (!container) throw new Error("side panel root not found");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
