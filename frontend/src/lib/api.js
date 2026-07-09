import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

// Companies
export const getCompanies = () => axios.get(`${API_URL}/companies`);
export const getCompany = (id) => axios.get(`${API_URL}/companies/${id}`);
export const createCompany = (data) => axios.post(`${API_URL}/companies`, data);
export const updateCompany = (id, data) => axios.put(`${API_URL}/companies/${id}`, data);
export const deleteCompany = (id) => axios.delete(`${API_URL}/companies/${id}`);

// Locations
export const getLocations = (companyId) => axios.get(`${API_URL}/locations`, { params: { company_id: companyId } });
export const createLocation = (data) => axios.post(`${API_URL}/locations`, data);
export const updateLocation = (id, data) => axios.put(`${API_URL}/locations/${id}`, data);
export const deleteLocation = (id) => axios.delete(`${API_URL}/locations/${id}`);

// Employees
export const getEmployees = (params) => axios.get(`${API_URL}/employees`, { params });
export const getEmployee = (id) => axios.get(`${API_URL}/employees/${id}`);
export const createEmployee = (data) => axios.post(`${API_URL}/employees`, data);
export const updateEmployee = (id, data) => axios.put(`${API_URL}/employees/${id}`, data);
export const deleteEmployee = (id) => axios.delete(`${API_URL}/employees/${id}`);

// Perfil do próprio colaborador
export const getMyProfile = () => axios.get(`${API_URL}/me/profile`);
export const updateMyProfile = (data) => axios.put(`${API_URL}/me/profile`, data);

// Time Records
export const getTimeRecords = (params) => axios.get(`${API_URL}/time-records`, { params });
export const createTimeRecord = (data) => axios.post(`${API_URL}/time-records`, data);
export const correctTimeRecord = (id, data) => axios.put(`${API_URL}/time-records/${id}/correct`, data);
export const getWorkedHoursReport = (params) => axios.get(`${API_URL}/reports/worked-hours`, { params });

// Leave Requests
export const getLeaveRequests = (params) => axios.get(`${API_URL}/leave-requests`, { params });
export const createLeaveRequest = (data) => axios.post(`${API_URL}/leave-requests`, data);
export const respondLeaveRequest = (id, status, response) => 
  axios.put(`${API_URL}/leave-requests/${id}/respond`, { status, response });
export const updateLeaveRequest = (id, data) => axios.put(`${API_URL}/leave-requests/${id}`, data);
export const deleteLeaveRequest = (id) => axios.delete(`${API_URL}/leave-requests/${id}`);
export const createAdminLeave = (data) => axios.post(`${API_URL}/admin/leave`, data);

// Work Schedules
export const getSchedules = () => axios.get(`${API_URL}/schedules`);
export const createSchedule = (data) => axios.post(`${API_URL}/schedules`, data);
export const updateSchedule = (id, data) => axios.put(`${API_URL}/schedules/${id}`, data);
export const deleteSchedule = (id) => axios.delete(`${API_URL}/schedules/${id}`);
export const getScheduleAssignments = (params) => axios.get(`${API_URL}/schedules/assignments`, { params });
export const assignSchedule = (data) => axios.post(`${API_URL}/schedules/assign`, data);
export const deleteScheduleAssignment = (id) => axios.delete(`${API_URL}/schedules/assignments/${id}`);

// Folders
export const getFolders = (employeeId) => axios.get(`${API_URL}/folders`, { params: { employee_id: employeeId } });
export const createFolder = (data) => axios.post(`${API_URL}/folders`, data);
export const updateFolder = (id, data) => axios.put(`${API_URL}/folders/${id}`, data);
export const deleteFolder = (id) => axios.delete(`${API_URL}/folders/${id}`);

// Documents
export const getDocuments = (params) => axios.get(`${API_URL}/documents`, { params });
export const uploadDocument = (folderId, file) => {
  const formData = new FormData();
  formData.append('folder_id', folderId);
  formData.append('file', file);
  return axios.post(`${API_URL}/documents`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
};
export const downloadDocument = (id) => axios.get(`${API_URL}/documents/${id}/download`, { responseType: 'blob' });
export const deleteDocument = (id) => axios.delete(`${API_URL}/documents/${id}`);

// Notifications
export const getNotifications = () => axios.get(`${API_URL}/notifications`);
export const markNotificationRead = (id) => axios.put(`${API_URL}/notifications/${id}/read`);
export const markAllNotificationsRead = () => axios.put(`${API_URL}/notifications/read-all`);

// Dashboard
export const getAdminDashboard = (companyId) => axios.get(`${API_URL}/dashboard/admin`, { params: { company_id: companyId } });
export const getEmployeeDashboard = () => axios.get(`${API_URL}/dashboard/employee`);

// Calendar
export const getCalendarLeaves = (params) => axios.get(`${API_URL}/calendar/leaves`, { params });

// Password Management
export const changePassword = (currentPassword, newPassword) => 
  axios.post(`${API_URL}/auth/change-password`, { 
    current_password: currentPassword, 
    new_password: newPassword 
  });
export const forgotPassword = (email) => 
  axios.post(`${API_URL}/auth/forgot-password`, { email });
export const resetPassword = (token, newPassword) => 
  axios.post(`${API_URL}/auth/reset-password`, { token, new_password: newPassword });
export const verifyResetToken = (token) => 
  axios.get(`${API_URL}/auth/verify-reset-token?token=${token}`);
export const resetEmployeePassword = (employeeId, newPassword) => 
  axios.post(`${API_URL}/employees/${employeeId}/reset-password`, { new_password: newPassword });

// Admin/Manager Management
export const getAdmins = () => axios.get(`${API_URL}/admins`);
export const createAdmin = (data) => axios.post(`${API_URL}/admins`, data);
export const deleteAdmin = (id) => axios.delete(`${API_URL}/admins/${id}`);
export const updateAdmin = (id, data) => axios.put(`${API_URL}/admins/${id}`, data);

// ==================== FINANCEIRO ====================

// Empresas (financeiro)
export const getFinCompanies = () => axios.get(`${API_URL}/fin/companies`);
export const createFinCompany = (data) => axios.post(`${API_URL}/fin/companies`, data);
export const updateFinCompany = (id, data) => axios.put(`${API_URL}/fin/companies/${id}`, data);
export const deleteFinCompany = (id) => axios.delete(`${API_URL}/fin/companies/${id}`);

// Unidades / Lojas (financeiro)
export const getFinUnits = (companyId) =>
  axios.get(`${API_URL}/fin/units`, { params: companyId ? { company_id: companyId } : {} });
export const createFinUnit = (data) => axios.post(`${API_URL}/fin/units`, data);
export const updateFinUnit = (id, data) => axios.put(`${API_URL}/fin/units/${id}`, data);
export const deleteFinUnit = (id) => axios.delete(`${API_URL}/fin/units/${id}`);

// Equipa global (financeiro)
export const getFinTeam = () => axios.get(`${API_URL}/fin/team`);
export const addFinTeamMember = (data) => axios.post(`${API_URL}/fin/team`, data);
export const updateFinTeamMember = (memberId, role) =>
  axios.put(`${API_URL}/fin/team/${memberId}`, { role });
export const removeFinTeamMember = (memberId) => axios.delete(`${API_URL}/fin/team/${memberId}`);

// Faturas / Pagamentos (financeiro)
export const getFinInvoices = (companyId) =>
  axios.get(`${API_URL}/fin/invoices`, { params: { company_id: companyId } });
// Ficha de detalhe: fatura completa + linked_movement (movimento do extrato ligado, ou null)
export const getFinInvoice = (id) => axios.get(`${API_URL}/fin/invoices/${id}`);
export const getFinInvoicePdf = (id) => axios.get(`${API_URL}/fin/invoices/${id}/pdf`, { responseType: 'blob' });
export const createFinInvoice = (data) => axios.post(`${API_URL}/fin/invoices`, data);
export const updateFinInvoice = (id, data) => axios.put(`${API_URL}/fin/invoices/${id}`, data);
export const toggleFinInvoicePaid = (id, paid, paidDate) =>
  axios.put(`${API_URL}/fin/invoices/${id}/toggle-paid`, { paid, paid_date: paidDate || null });
export const reclassifyFinInvoice = (id, companyId) =>
  axios.put(`${API_URL}/fin/invoices/${id}/reclassify`, { company_id: companyId });
export const setFinInvoiceUnit = (id, unitId) =>
  axios.put(`${API_URL}/fin/invoices/${id}/set-unit`, { unit_id: unitId || null });
export const deleteFinInvoice = (id) => axios.delete(`${API_URL}/fin/invoices/${id}`);
export const cancelFinInvoiceSeries = (id) =>
  axios.delete(`${API_URL}/fin/invoices/${id}`, { params: { series: 'future' } });

// Regras de fornecedor (financeiro)
export const getFinSupplierRules = () => axios.get(`${API_URL}/fin/supplier-rules`);
export const upsertFinSupplierRule = (data) => axios.post(`${API_URL}/fin/supplier-rules`, data);
export const deleteFinSupplierRule = (key) =>
  axios.delete(`${API_URL}/fin/supplier-rules`, { params: { key } });

// Extrato / Tesouraria — contas bancárias e movimentos (financeiro)
export const getFinBankAccounts = (companyId) =>
  axios.get(`${API_URL}/fin/bank-accounts`, { params: { company_id: companyId } });
export const createFinBankAccount = (data) => axios.post(`${API_URL}/fin/bank-accounts`, data);
export const getFinMovements = (params) => axios.get(`${API_URL}/fin/movements`, { params });
export const importFinMovements = (data) => axios.post(`${API_URL}/fin/movements/import`, data);
export const importFinMovementsPdf = (file) => {
  const fd = new FormData();
  fd.append('file', file);
  return axios.post(`${API_URL}/fin/movements/import-pdf`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const setFinMovementTitle = (id, title) =>
  axios.put(`${API_URL}/fin/movements/${id}/set-title`, { title });
export const linkFinMovement = (id, invoiceId) =>
  axios.put(`${API_URL}/fin/movements/${id}/link`, { invoice_id: invoiceId });
export const unlinkFinMovement = (id) => axios.put(`${API_URL}/fin/movements/${id}/unlink`);
export const attachFinMovement = (id, file) => {
  const fd = new FormData();
  fd.append('file', file);
  return axios.post(`${API_URL}/fin/movements/${id}/attach`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const automatchFinMovements = (companyId) =>
  axios.post(`${API_URL}/fin/movements/automatch`, { company_id: companyId });

// Vendas (financeiro) — params: { company_id, month?, unit_id? }
export const getFinSales = (params) => axios.get(`${API_URL}/fin/sales`, { params });
export const createFinSale = (data) => axios.post(`${API_URL}/fin/sales`, data);
export const updateFinSale = (id, data) => axios.put(`${API_URL}/fin/sales/${id}`, data);
export const deleteFinSale = (id) => axios.delete(`${API_URL}/fin/sales/${id}`);
export const syncFinVendus = (companyId, withCost = false) =>
  axios.post(`${API_URL}/fin/vendus/sync`, { company_id: companyId, with_cost: withCost });
// Despachante: escolhe o motor (Vendus/Moloni) consoante a empresa.
export const syncFinSales = (companyId, withCost = false) =>
  axios.post(`${API_URL}/fin/sales/sync`, { company_id: companyId, with_cost: withCost });

// Botões de atualização instantânea (Painel Global) — um por sistema.
export const syncNowVendus = () => axios.post(`${API_URL}/fin/sync/vendus`);
export const syncNowMoloni = () => axios.post(`${API_URL}/fin/sync/moloni`);
export const syncNowIngest = () => axios.post(`${API_URL}/fin/sync/ingest`);

// Painel Global (financeiro) — cruza KPIs Financeiro + RH + Marketing por empresa
// params: { company_id, month? }
export const getFinGlobalDashboard = (params) =>
  axios.get(`${API_URL}/fin/global/dashboard`, { params });
// Ligação empresa/unidade do Financeiro ao RH
export const linkFinCompanyRh = (id, rhCompanyId) =>
  axios.put(`${API_URL}/fin/companies/${id}/link-rh`, { rh_company_id: rhCompanyId });
export const linkFinUnitRh = (id, rhLocationId) =>
  axios.put(`${API_URL}/fin/units/${id}/link-rh`, { rh_location_id: rhLocationId });

// Marketing — Campanhas
export const getCampaigns = (params) => axios.get(`${API_URL}/marketing/campaigns`, { params });
export const createCampaign = (data) => axios.post(`${API_URL}/marketing/campaigns`, data);
export const updateCampaign = (id, data) => axios.put(`${API_URL}/marketing/campaigns/${id}`, data);
export const deleteCampaign = (id) => axios.delete(`${API_URL}/marketing/campaigns/${id}`);

// Marketing — Calendário de conteúdos (publicações)
export const getPosts = (params) => axios.get(`${API_URL}/marketing/posts`, { params });
export const createPost = (data) => axios.post(`${API_URL}/marketing/posts`, data);
export const updatePost = (id, data) => axios.put(`${API_URL}/marketing/posts/${id}`, data);
export const deletePost = (id) => axios.delete(`${API_URL}/marketing/posts/${id}`);

// Marketing — Avaliações (Google)
export const getReviews = (params) => axios.get(`${API_URL}/marketing/reviews`, { params });
export const findPlace = (query) => axios.get(`${API_URL}/marketing/reviews/find-place`, { params: { query } });

// Marketing — Relatórios / métricas
export const getMarketingReports = (params) => axios.get(`${API_URL}/marketing/reports`, { params });

// Escala do próprio colaborador (para o lembrete de ponto no app)
export const getMySchedule = () => axios.get(`${API_URL}/me/schedule`);

// RH — Feriados personalizados (municipais)
export const getHolidays = () => axios.get(`${API_URL}/holidays`);
export const createHoliday = (data) => axios.post(`${API_URL}/holidays`, data);
export const updateHoliday = (id, data) => axios.put(`${API_URL}/holidays/${id}`, data);
export const deleteHoliday = (id) => axios.delete(`${API_URL}/holidays/${id}`);
