import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { Toaster } from './components/ui/sonner';
import { initNativeStatusBar } from './lib/statusbar';

// Pages
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import PrivacyPolicy from './pages/PrivacyPolicy';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminCompanies from './pages/admin/AdminCompanies';
import AdminLocations from './pages/admin/AdminLocations';
import AdminEmployees from './pages/admin/AdminEmployees';
import AdminTimeRecords from './pages/admin/AdminTimeRecords';
import AdminLeaveRequests from './pages/admin/AdminLeaveRequests';
import AdminVacationMap from './pages/admin/AdminVacationMap';
import AdminHoursReport from './pages/admin/AdminHoursReport';
import AdminDocuments from './pages/admin/AdminDocuments';
import AdminManagers from './pages/admin/AdminManagers';
import AdminSchedules from './pages/admin/AdminSchedules';
import AdminHolidays from './pages/admin/AdminHolidays';
import FinInicio from './pages/admin/financeiro/FinInicio';
import FinPagamentos from './pages/admin/financeiro/FinPagamentos';
import FinVendas from './pages/admin/financeiro/FinVendas';
import FinFornecedores from './pages/admin/financeiro/FinFornecedores';
import FinExtrato from './pages/admin/financeiro/FinExtrato';
import FinRelatorios from './pages/admin/financeiro/FinRelatorios';
import PainelGlobal from './pages/admin/financeiro/PainelGlobal';
import EmployeeDashboard from './pages/employee/EmployeeDashboard';
import EmployeeProfile from './pages/employee/EmployeeProfile';
import EmployeeTimeRecord from './pages/employee/EmployeeTimeRecord';
import EmployeeLeaveRequests from './pages/employee/EmployeeLeaveRequests';
import EmployeeDocuments from './pages/employee/EmployeeDocuments';

// Layout
import AdminLayout from './components/layouts/AdminLayout';
import EmployeeLayout from './components/layouts/EmployeeLayout';
import MarketingCampaigns from './pages/admin/marketing/MarketingCampaigns';
import MarketingCalendar from './pages/admin/marketing/MarketingCalendar';
import MarketingReviews from './pages/admin/marketing/MarketingReviews';
import MarketingReports from './pages/admin/marketing/MarketingReports';

// Protected Route Component - checks for authentication and must_change_password
const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, loading, isAuthenticated, mustChangePassword } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  // Redirect to change password if required
  if (mustChangePassword) {
    return <Navigate to="/alterar-senha" replace />;
  }
  
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={['admin', 'gerente', 'contabilista'].includes(user.role) ? '/admin' : '/colaborador'} replace />;
  }
  
  return children;
};

// Change Password Route - only accessible when must_change_password is true
const ChangePasswordRoute = ({ children }) => {
  const { user, loading, isAuthenticated, mustChangePassword } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  // If user doesn't need to change password, redirect to appropriate dashboard
  if (!mustChangePassword) {
    return <Navigate to={['admin', 'gerente', 'contabilista'].includes(user.role) ? '/admin' : '/colaborador'} replace />;
  }
  
  return children;
};

// Redirect based on role
const RoleRedirect = () => {
  const { user, loading, isAuthenticated, mustChangePassword } = useAuth();
  
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  // Redirect to change password if required
  if (mustChangePassword) {
    return <Navigate to="/alterar-senha" replace />;
  }
  
  return <Navigate to={['admin', 'gerente', 'contabilista'].includes(user.role) ? '/admin' : '/colaborador'} replace />;
};

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/esqueci-senha" element={<ForgotPasswordPage />} />
      <Route path="/redefinir-senha" element={<ResetPasswordPage />} />
      <Route path="/privacidade" element={<PrivacyPolicy />} />
      <Route path="/alterar-senha" element={
        <ChangePasswordRoute>
          <ChangePasswordPage />
        </ChangePasswordRoute>
      } />
      <Route path="/" element={<RoleRedirect />} />
      
      {/* Admin Routes */}
      <Route path="/admin" element={
        <ProtectedRoute allowedRoles={['admin', 'gerente', 'contabilista']}>
          <AdminLayout />
        </ProtectedRoute>
      }>
        <Route index element={<AdminDashboard />} />
        <Route path="painel" element={<PainelGlobal />} />
        <Route path="empresas" element={<AdminCompanies />} />
        <Route path="locais" element={<AdminLocations />} />
        <Route path="colaboradores" element={<AdminEmployees />} />
        <Route path="ponto" element={<AdminTimeRecords />} />
        <Route path="relatorio-horas" element={<AdminHoursReport />} />
        <Route path="ausencias" element={<AdminLeaveRequests />} />
        <Route path="mapa-ferias" element={<AdminVacationMap />} />
        <Route path="feriados" element={<AdminHolidays />} />
        <Route path="documentos" element={<AdminDocuments />} />
        <Route path="gestores" element={
          <ProtectedRoute allowedRoles={['admin']}>
            <AdminManagers />
          </ProtectedRoute>
        } />
        <Route path="escalas" element={<AdminSchedules />} />

        {/* ===== Financeiro ===== */}
        {/* Fase 2: Início (empresas+unidades) e Equipa já implementados. */}
        <Route path="financeiro" element={<FinInicio />} />
        <Route path="financeiro/pagamentos" element={<FinPagamentos />} />
        <Route path="financeiro/vendas" element={<FinVendas />} />
        <Route path="financeiro/relatorios" element={<FinRelatorios />} />
        <Route path="financeiro/fornecedores" element={<FinFornecedores />} />
        <Route path="financeiro/extrato" element={<FinExtrato />} />

        {/* ===== Marketing ===== */}
        <Route path="marketing" element={<MarketingCampaigns />} />
        <Route path="marketing/calendario" element={<MarketingCalendar />} />
        <Route path="marketing/avaliacoes" element={<MarketingReviews />} />
        <Route path="marketing/relatorios" element={<MarketingReports />} />
      </Route>
      
      {/* Employee Routes */}
      <Route path="/colaborador" element={
        <ProtectedRoute allowedRoles={['colaborador']}>
          <EmployeeLayout />
        </ProtectedRoute>
      }>
        <Route index element={<EmployeeDashboard />} />
        <Route path="perfil" element={<EmployeeProfile />} />
        <Route path="ponto" element={<EmployeeTimeRecord />} />
        <Route path="ausencias" element={<EmployeeLeaveRequests />} />
        <Route path="documentos" element={<EmployeeDocuments />} />
      </Route>
      
      {/* Catch all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  useEffect(() => {
    // Barra de estado nativa a acompanhar o tema (app Android/iOS).
    initNativeStatusBar();
  }, []);
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
        <Toaster position="top-right" richColors />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
