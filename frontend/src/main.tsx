// main.tsx - React entry point: mounts the router with all 15 pages inside the Layout.
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Inventory from "./pages/Inventory";
import Topology from "./pages/Topology";
import Alarms from "./pages/Alarms";
import Incidents from "./pages/Incidents";
import IncidentDetail from "./pages/IncidentDetail";
import Performance from "./pages/Performance";
import FaultLocalization from "./pages/FaultLocalization";
import ServiceImpact from "./pages/ServiceImpact";
import RCA from "./pages/RCA";
import Knowledge from "./pages/Knowledge";
import Restoration from "./pages/Restoration";
import Approvals from "./pages/Approvals";
import ActionTracker from "./pages/ActionTracker";
import Reports from "./pages/Reports";
import AgentExecution from "./pages/AgentExecution";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/topology" element={<Topology />} />
          <Route path="/alarms" element={<Alarms />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/incidents/:id" element={<IncidentDetail />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/fault" element={<FaultLocalization />} />
          <Route path="/impact" element={<ServiceImpact />} />
          <Route path="/rca" element={<RCA />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/restoration" element={<Restoration />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/actions" element={<ActionTracker />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/agents" element={<AgentExecution />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
