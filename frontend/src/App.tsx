import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import AlertDetailPage from "@/pages/AlertDetailPage";
import AlertsPage from "@/pages/AlertsPage";
import DashboardPage from "@/pages/DashboardPage";
import IngestionPage from "@/pages/IngestionPage";
import ReportsPage from "@/pages/ReportsPage";
import ResponseCenterPage from "@/pages/ResponseCenterPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="alerts/:id" element={<AlertDetailPage />} />
        <Route path="response" element={<ResponseCenterPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="ingestion" element={<IngestionPage />} />
      </Route>
    </Routes>
  );
}
