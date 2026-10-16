import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import SaasApp from "./saas/SaasApp";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {import.meta.env.VITE_APPLICATION_MODE === "prototype" ? <App /> : <SaasApp />}
  </StrictMode>,
);
