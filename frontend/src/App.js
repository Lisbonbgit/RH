import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { Toaster } from './components/ui/sonner';

// Pages
import LoginPage from './pages/LoginPage';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminCompanies from './pages/admin/AdminCompanies';
import AdminLocations from './pages/admin/AdminLocations';
import AdminEmployees from './pages/admin/AdminEmployees';
import AdminTimeRecords from './pages/admin/AdminTimeRecords';
import AdminLeaveRequests from './pages/admin/AdminLeaveRequests';
import AdminDocuments from './pages/admin/AdminDocuments';
import AdminPendingRegistrations from './pages/admin/AdminPendingRegistrations';
import EmployeeDashboard from './pages/employee/EmployeeDashboard';
import EmployeeTimeRecord from './pages/employee/EmployeeTimeRecord';
import EmployeeLeaveRequests from './pages/employee/EmployeeLeaveRequests';
import EmployeeDocuments from './pages/employee/EmployeeDocuments';

// Layout
import AdminLayout from './components/layouts/AdminLayout';
import EmployeeLayout from './components/layouts/EmployeeLayout';

// Protected Route Component
const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, loading, isAuthenticated } = useAuth();
  
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
  
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={user.role === 'admin' ? '/admin' : '/colaborador'} replace />;
  }
  
  return children;
};

// Redirect based on role
const RoleRedirect = () => {
  const { user, loading, isAuthenticated } = useAuth();
  
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
  
  return <Navigate to={user.role === 'admin' ? '/admin' : '/colaborador'} replace />;
};

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<RoleRedirect />} />
      
      {/* Admin Routes */}
      <Route path="/admin" element={
        <ProtectedRoute allowedRoles={['admin']}>
          <AdminLayout />
        </ProtectedRoute>
      }>
        <Route index element={<AdminDashboard />} />
        <Route path="empresas" element={<AdminCompanies />} />
        <Route path="locais" element={<AdminLocations />} />
        <Route path="colaboradores" element={<AdminEmployees />} />
        <Route path="ponto" element={<AdminTimeRecords />} />
        <Route path="ausencias" element={<AdminLeaveRequests />} />
        <Route path="documentos" element={<AdminDocuments />} />
        <Route path="registos" element={<AdminPendingRegistrations />} />
      </Route>
      
      {/* Employee Routes */}
      <Route path="/colaborador" element={
        <ProtectedRoute allowedRoles={['colaborador']}>
          <EmployeeLayout />
        </ProtectedRoute>
      }>
        <Route index element={<EmployeeDashboard />} />
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
