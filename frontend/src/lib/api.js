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

// Time Records
export const getTimeRecords = (params) => axios.get(`${API_URL}/time-records`, { params });
export const createTimeRecord = (data) => axios.post(`${API_URL}/time-records`, data);
export const correctTimeRecord = (id, data) => axios.put(`${API_URL}/time-records/${id}/correct`, data);

// Leave Requests
export const getLeaveRequests = (params) => axios.get(`${API_URL}/leave-requests`, { params });
export const createLeaveRequest = (data) => axios.post(`${API_URL}/leave-requests`, data);
export const respondLeaveRequest = (id, status, response) => 
  axios.put(`${API_URL}/leave-requests/${id}/respond`, { status, response });

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

// Pending Registrations
export const getPendingRegistrations = () => axios.get(`${API_URL}/auth/pending-registrations`);
export const approveRegistration = (id, role = 'admin') => axios.post(`${API_URL}/auth/approve-registration/${id}`, null, { params: { role } });
export const rejectRegistration = (id) => axios.post(`${API_URL}/auth/reject-registration/${id}`);
