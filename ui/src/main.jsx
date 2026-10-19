import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./tokens.css";
import "./styles.css";
import { App } from "./App.jsx";
import "./studio.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
