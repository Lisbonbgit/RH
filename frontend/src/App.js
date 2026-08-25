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
import EstoqueFaturas from './pages/admin/estoque/EstoqueFaturas';
import EstoqueStock from './pages/admin/estoque/EstoqueStock';
import EstoqueListaCompras from './pages/admin/estoque/EstoqueListaCompras';
import EstoqueTransferencias from './pages/admin/estoque/EstoqueTransferencias';
import EstoqueHistorico from './pages/admin/estoque/EstoqueHistorico';
import EstoqueFichas from './pages/admin/estoque/EstoqueFichas';
import EstoqueProducao from './pages/admin/estoque/EstoqueProducao';
import EstoqueEmBreve from './pages/admin/estoque/EstoqueEmBreve';
import ComingSoon from './components/ComingSoon';
import {
  FileText,
  Percent,
  Users,
  BarChart3,
  Truck,
  Banknote,
  Store,
} from 'lucide-react';
import FatDashboard from './pages/admin/faturacao/FatDashboard';
import FatProdutos from './pages/admin/faturacao/FatProdutos';
import FatCategorias from './pages/admin/faturacao/FatCategorias';
import FatDocumentos from './pages/admin/faturacao/FatDocumentos';
import FatPersonalizacoes from './pages/admin/faturacao/FatPersonalizacoes';
import FatLojas from './pages/admin/faturacao/FatLojas';
import FatPagamentos from './pages/admin/faturacao/FatPagamentos';
import FatUtilizadores from './pages/admin/faturacao/FatUtilizadores';
import FatMotivos from './pages/admin/faturacao/FatMotivos';
import FatDispositivos from './pages/admin/faturacao/FatDispositivos';
import FatReservasPresas from './pages/admin/faturacao/FatReservasPresas';
import PosApp from './pages/pos/PosApp';
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

      {/* Ponto de Venda: rota de topo, fora do /admin e sem sessão de
          backoffice — as lojas usam só este link, com entrada por PIN,
          nunca o login do portal. Ver AdminLayout: o botão "Iniciar Ponto
          de Venda" abre este caminho num separador novo. PosApp é o shell
          (emparelhamento -> entrada -> caixa -> venda); os dois tokens do
          POS vivem em localStorage (lib/pos.js), nunca no Authorization do
          backoffice. */}
      <Route path="/faturacao/pos" element={<PosApp />} />
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
        {/* Início deixou de existir: aterra em Vendas. Empresas/lojas movidas
            para Configurações (botão de engrenagem no topo). */}
        <Route path="financeiro" element={<Navigate to="/admin/financeiro/vendas" replace />} />
        <Route path="financeiro/configuracoes" element={<FinInicio />} />
        <Route path="financeiro/pagamentos" element={<FinPagamentos />} />
        <Route path="financeiro/vendas" element={<FinVendas />} />
        <Route path="financeiro/relatorios" element={<FinRelatorios />} />
        <Route path="financeiro/fornecedores" element={<FinFornecedores />} />
        <Route path="financeiro/extrato" element={<FinExtrato />} />

        {/* ===== Estoque ===== */}
        <Route path="estoque" element={<Navigate to="/admin/estoque/stock" replace />} />
        <Route path="estoque/stock" element={<EstoqueStock />} />
        <Route path="estoque/escanear" element={<EstoqueEmBreve />} />
        <Route path="estoque/lista-compras" element={<EstoqueListaCompras />} />
        <Route path="estoque/transferencias" element={<EstoqueTransferencias />} />
        <Route path="estoque/fichas" element={<EstoqueFichas />} />
        <Route path="estoque/producao" element={<EstoqueProducao />} />
        <Route path="estoque/faturas" element={<EstoqueFaturas />} />
        <Route path="estoque/historico" element={<EstoqueHistorico />} />

        {/* ===== Faturação ===== */}
        <Route path="faturacao" element={<Navigate to="/admin/faturacao/dashboard" replace />} />

        {/* Gestão — a estrutura pedida pelo dono, decalcada do backoffice do
            Vendus. O que ainda não está construído mostra "Brevemente", como o
            Financeiro fez enquanto crescia. */}
        <Route path="faturacao/dashboard" element={<FatDashboard />} />
        <Route path="faturacao/produtos" element={<Navigate to="/admin/faturacao/produtos/lista" replace />} />
        <Route path="faturacao/produtos/lista" element={<FatProdutos />} />
        <Route path="faturacao/produtos/categorias" element={<FatCategorias />} />
        <Route path="faturacao/produtos/personalizacoes" element={<FatPersonalizacoes />} />
        <Route path="faturacao/documentos" element={<FatDocumentos />} />
        {/* A lista que as mensagens do POS já mandavam o gestor consultar
            ("chame o gestor, que resolve na lista de reservas fiscais presas")
            e que não existia — sem ela, uma emissão que fica a meio tranca a
            conta e impede a loja de fechar a caixa. */}
        <Route path="faturacao/reservas-presas" element={<FatReservasPresas />} />
        <Route path="faturacao/taloes-desconto" element={<ComingSoon icon={Percent} title="Talões de Desconto" subtitle="Faturação · Gestão" />} />
        <Route path="faturacao/clientes" element={<ComingSoon icon={Users} title="Clientes" subtitle="Faturação · Gestão" note="Fichas de cliente e NIF para as faturas." />} />
        <Route path="faturacao/relatorios" element={<ComingSoon icon={BarChart3} title="Relatórios" subtitle="Faturação · Gestão" note="Movimentos de caixa, produtos, categorias, lojas, utilizadores, diário, por hora, dias da semana e mensal." />} />
        <Route path="faturacao/compras" element={<ComingSoon icon={Truck} title="Compras" subtitle="Faturação · Gestão" note="Entrada de mercadoria a partir das faturas de compra que já existem no Financeiro." />} />

        {/* POS — o "Iniciar Ponto de Venda" já não vive aqui: é o botão do
            topo do painel, e abre /faturacao/pos (fora do /admin) num
            separador novo. Ver App.js, rotas de topo, e AdminLayout. */}
        <Route path="faturacao/movimentos-caixa" element={<ComingSoon icon={Banknote} title="Movimentos de Caixa" subtitle="Faturação · POS" note="Aberturas, entradas, saídas e fechos de caixa, loja a loja." />} />
        <Route path="faturacao/pos-lojas" element={<ComingSoon icon={Store} title="Lojas" subtitle="Faturação · POS" note="Definições de cada loja e o que sai impresso no talão do cliente." />} />

        {/* Configuração — os ecrãs que já funcionam. A Configuração pendura-se
            no carril como um item com filhos (ver AdminLayout); precisa de
            um caminho próprio para o pai poder navegar antes de expandir. */}
        <Route path="faturacao/config" element={<Navigate to="/admin/faturacao/config/lojas" replace />} />
        <Route path="faturacao/config/lojas" element={<FatLojas />} />
        <Route path="faturacao/config/pagamentos" element={<FatPagamentos />} />
        <Route path="faturacao/config/utilizadores" element={<FatUtilizadores />} />
        <Route path="faturacao/config/motivos" element={<FatMotivos />} />
        <Route path="faturacao/config/dispositivos" element={<FatDispositivos />} />

        {/* Os caminhos antigos, de antes da estrutura por secções */}
        <Route path="faturacao/lojas" element={<Navigate to="/admin/faturacao/config/lojas" replace />} />
        <Route path="faturacao/pagamentos" element={<Navigate to="/admin/faturacao/config/pagamentos" replace />} />
        <Route path="faturacao/utilizadores" element={<Navigate to="/admin/faturacao/config/utilizadores" replace />} />
        <Route path="faturacao/motivos" element={<Navigate to="/admin/faturacao/config/motivos" replace />} />

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
