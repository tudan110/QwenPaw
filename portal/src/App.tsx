import { Navigate, Route, Routes } from "react-router-dom";
import AgentCenterPage from "./pages/AgentCenterPage";
import DigitalEmployeePage from "./pages/DigitalEmployeePage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DigitalEmployeePage />} />
      <Route path="/agent-center" element={<AgentCenterPage />} />
      <Route path="/ops-expert" element={<DigitalEmployeePage forcedSection="ops-expert" />} />
      <Route path="/mcp" element={<DigitalEmployeePage forcedSection="mcp" />} />
      <Route path="/skill-pool" element={<DigitalEmployeePage forcedSection="skill-pool" />} />
      <Route path="/inspiration" element={<DigitalEmployeePage forcedSection="inspiration" />} />
      <Route path="/cli" element={<DigitalEmployeePage forcedSection="cli" />} />
      <Route path="/overview" element={<DigitalEmployeePage forcedSection="overview" />} />
      <Route path="/dashboard" element={<DigitalEmployeePage forcedSection="dashboard" />} />
      <Route path="/tasks" element={<DigitalEmployeePage forcedSection="tasks" />} />
      <Route path="/cron-jobs" element={<DigitalEmployeePage forcedSection="tasks" />} />
      <Route path="/model-config" element={<DigitalEmployeePage forcedSection="model-config" />} />
      <Route path="/token-usage" element={<DigitalEmployeePage forcedSection="token-usage" />} />
      <Route path="/employee/:employeeId" element={<DigitalEmployeePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
