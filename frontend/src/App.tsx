import { Route, Routes } from "react-router-dom";

import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import AdminUsersPage from "@/pages/AdminUsersPage";
import AlertDetailPage from "@/pages/AlertDetailPage";
import AlertsPage from "@/pages/AlertsPage";
import AuditPage from "@/pages/AuditPage";
import DashboardPage from "@/pages/DashboardPage";
import HostTimelinePage from "@/pages/HostTimelinePage";
import IngestionPage from "@/pages/IngestionPage";
import LoginPage from "@/pages/LoginPage";
import ReportsPage from "@/pages/ReportsPage";
import ResponseCenterPage from "@/pages/ResponseCenterPage";
import SystemPage from "@/pages/SystemPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="alerts/:id" element={<AlertDetailPage />} />
          <Route path="hosts/:ip" element={<HostTimelinePage />} />
          <Route path="response" element={<ResponseCenterPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="ingestion" element={<IngestionPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="admin/users" element={<AdminUsersPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
