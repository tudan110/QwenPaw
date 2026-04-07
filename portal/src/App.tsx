import { Navigate, Route, Routes } from "react-router-dom";
import AgentCenterPage from "./pages/AgentCenterPage";
import DigitalEmployeePage from "./pages/DigitalEmployeePage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AgentCenterPage />} />
      <Route path="/employee/:employeeId" element={<DigitalEmployeePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
