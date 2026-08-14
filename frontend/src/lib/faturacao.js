// Wrappers do módulo Faturação. O token vai em axios.defaults.headers.common,
// posto pelo AuthContext — como em lib/api.js e lib/finance.js.
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

// Traduz o erro do axios numa mensagem amigável e, quando o 422 aponta para
// um campo, devolve também o nome desse campo. O `detail` de um 422 do
// FastAPI/Pydantic é um array de objectos ([{type, loc, msg, input}, ...]) — e
// não uma string, por isso nunca pode ir directo para o toast (o sonner
// tentaria renderizar o array como filho React e desmontava a página).
export const detalhesErro = (error, fallback) => {
  const status = error.response?.status;
  const detail = error.response?.data?.detail;
  if (status === 422 && Array.isArray(detail) && detail.length > 0) {
    const primeiro = detail[0];
    const campo = Array.isArray(primeiro.loc) ? primeiro.loc[primeiro.loc.length - 1] : null;
    const mensagem = (primeiro.msg || '').replace(/^Value error,\s*/i, '') || fallback;
    return { campo, mensagem };
  }
  if (typeof detail === 'string' && detail) return { campo: null, mensagem: detail };
  return { campo: null, mensagem: fallback };
};

// Dashboard
export const getFatDashboard = (comIva = true) =>
  axios.get(`${API_URL}/faturacao/dashboard`, { params: { com_iva: comIva } });

// Lojas
export const getLojas = () => axios.get(`${API_URL}/faturacao/lojas`);
export const criarLoja = (data) => axios.post(`${API_URL}/faturacao/lojas`, data);
export const editarLoja = (id, data) => axios.put(`${API_URL}/faturacao/lojas/${id}`, data);
export const apagarLoja = (id) => axios.delete(`${API_URL}/faturacao/lojas/${id}`);

// Caixas (de uma loja)
export const getCaixas = (lojaId) => axios.get(`${API_URL}/faturacao/lojas/${lojaId}/caixas`);
export const criarCaixa = (lojaId, data) => axios.post(`${API_URL}/faturacao/lojas/${lojaId}/caixas`, data);
export const editarCaixa = (id, data) => axios.put(`${API_URL}/faturacao/caixas/${id}`, data);
export const apagarCaixa = (id) => axios.delete(`${API_URL}/faturacao/caixas/${id}`);

// Tipos de Pagamento
export const getTiposPagamento = () => axios.get(`${API_URL}/faturacao/tipos-pagamento`);
export const getCodigosFiscais = () => axios.get(`${API_URL}/faturacao/tipos-pagamento/codigos-fiscais`);
export const criarTipoPagamento = (data) => axios.post(`${API_URL}/faturacao/tipos-pagamento`, data);
export const editarTipoPagamento = (id, data) => axios.put(`${API_URL}/faturacao/tipos-pagamento/${id}`, data);
export const apagarTipoPagamento = (id) => axios.delete(`${API_URL}/faturacao/tipos-pagamento/${id}`);

// Utilizadores
export const getUtilizadores = () => axios.get(`${API_URL}/faturacao/utilizadores`);
export const criarUtilizador = (data) => axios.post(`${API_URL}/faturacao/utilizadores`, data);
export const editarUtilizador = (id, data) => axios.put(`${API_URL}/faturacao/utilizadores/${id}`, data);
export const mudarPin = (id, pin) => axios.put(`${API_URL}/faturacao/utilizadores/${id}/pin`, { pin });
export const mudarEstado = (id, ativo) => axios.put(`${API_URL}/faturacao/utilizadores/${id}/estado`, { ativo });

// Motivos de Nota de Crédito
export const getMotivos = () => axios.get(`${API_URL}/faturacao/motivos-nc`);
export const criarMotivo = (data) => axios.post(`${API_URL}/faturacao/motivos-nc`, data);
export const editarMotivo = (id, data) => axios.put(`${API_URL}/faturacao/motivos-nc/${id}`, data);
export const predefinirMotivo = (id) => axios.put(`${API_URL}/faturacao/motivos-nc/${id}/predefinir`);
export const apagarMotivo = (id) => axios.delete(`${API_URL}/faturacao/motivos-nc/${id}`);
