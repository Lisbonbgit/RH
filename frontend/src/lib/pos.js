// Wrappers do Ponto de Venda (POS) — deliberadamente à parte de lib/faturacao.js.
//
// O backoffice guarda o JWT de gestão em axios.defaults.headers.common
// (AuthContext.js) — um objecto GLOBAL e partilhado por toda a SPA. Se o POS
// usasse esse mesmo `axios`, bastaria alguém navegar do backoffice para
// /faturacao/pos (ou vice-versa) sem recarregar a página, dentro da mesma aba,
// para o Authorization de gestão viajar em pedidos do POS, ou os cabeçalhos do
// POS viajarem em pedidos do backoffice. Por isso esta instância é criada com
// `axios.create()`, isolada, e os dois tokens do POS (dispositivo e operador —
// ver faturacao/pos_auth.py) vão em cabeçalhos próprios (X-Device-Token,
// X-Operator-Token), lidos de localStorage a CADA pedido — nunca cravados
// como default no arranque, para uma troca de dispositivo ou operador a meio
// da sessão do browser ser sempre respeitada no pedido seguinte.
import axios from 'axios';

// O /faturacao FAZ PARTE do baseURL, e não de cada caminho. O módulo está
// montado em /api/faturacao (faturacao/__init__.py: APIRouter(prefix=...)),
// e este baseURL nasceu como '/api' — o que punha TODAS as chamadas do POS
// em /api/pos/..., um caminho que não existe. O FastAPI respondia 404 com o
// literal {"detail":"Not Found"}, e era esse "Not Found" cru, em inglês, que
// aparecia no ecrã do balcão ao emparelhar. Não era só o emparelhamento: as
// sete chamadas do POS falhavam todas da mesma maneira, e ninguém deu por
// isso porque os ecrãs desenham-se na mesma sem servidor nenhum. Está no
// baseURL de propósito, e não repetido em cada função, para não haver forma
// de acrescentar amanhã uma chamada nova e voltar a esquecê-lo.
const API_URL = process.env.REACT_APP_BACKEND_URL + '/api/faturacao';

const api = axios.create({ baseURL: API_URL });

api.interceptors.request.use((config) => {
  const deviceToken = getDeviceToken();
  const operatorToken = getOperatorToken();
  config.headers = config.headers || {};
  if (deviceToken) config.headers['X-Device-Token'] = deviceToken;
  if (operatorToken) config.headers['X-Operator-Token'] = operatorToken;
  return config;
});

const CHAVE_DISPOSITIVO = 'pos_device_token';
const CHAVE_LOJA_ID = 'pos_loja_id';
const CHAVE_LOJA_NOME = 'pos_loja_nome';
const CHAVE_OPERADOR_TOKEN = 'pos_operator_token';
const CHAVE_OPERADOR = 'pos_operador';
const CHAVE_CAIXA_ID = 'pos_caixa_id';

// localStorage pode não existir (modo privado em alguns browsers) — nunca
// deixar isso rebentar o ecrã do balcão; sem storage, a app funciona só
// dentro desta aba, até recarregar.
const guardar = (chave, valor) => {
  try {
    if (valor === null || valor === undefined) localStorage.removeItem(chave);
    else localStorage.setItem(chave, valor);
  } catch (e) { /* modo privado sem storage */ }
};
const ler = (chave) => {
  try { return localStorage.getItem(chave); } catch (e) { return null; }
};

// --- Dispositivo -------------------------------------------------------------

export const getDeviceToken = () => ler(CHAVE_DISPOSITIVO);
export const getLojaId = () => ler(CHAVE_LOJA_ID);
export const getLojaNome = () => ler(CHAVE_LOJA_NOME);

export const guardarDispositivo = ({ device_token, loja_id, loja_nome }) => {
  guardar(CHAVE_DISPOSITIVO, device_token);
  guardar(CHAVE_LOJA_ID, loja_id || null);
  guardar(CHAVE_LOJA_NOME, loja_nome || null);
};

// Limpa dispositivo E operador — sem dispositivo não há sessão de operador
// válida (o /pos/entrar seguinte precisava sempre de um X-Device-Token).
export const esquecerDispositivo = () => {
  guardar(CHAVE_DISPOSITIVO, null);
  guardar(CHAVE_LOJA_ID, null);
  guardar(CHAVE_LOJA_NOME, null);
  esquecerOperador();
};

// --- Operador ------------------------------------------------------------

export const getOperatorToken = () => ler(CHAVE_OPERADOR_TOKEN);

export const getOperadorGuardado = () => {
  const bruto = ler(CHAVE_OPERADOR);
  if (!bruto) return null;
  try { return JSON.parse(bruto); } catch (e) { return null; }
};

export const guardarOperador = (operatorToken, operador) => {
  guardar(CHAVE_OPERADOR_TOKEN, operatorToken);
  guardar(CHAVE_OPERADOR, JSON.stringify(operador));
};

export const esquecerOperador = () => {
  guardar(CHAVE_OPERADOR_TOKEN, null);
  guardar(CHAVE_OPERADOR, null);
};

// --- Caixa escolhida (quando a loja tem mais do que uma) ---------------------

export const getCaixaIdGuardada = () => ler(CHAVE_CAIXA_ID);
export const guardarCaixaId = (caixaId) => guardar(CHAVE_CAIXA_ID, caixaId || null);

// Mensagens exactas do servidor (faturacao/pos_auth.py) que o ecrã precisa
// de RECONHECER, não só mostrar — para saber que a causa foi o dispositivo
// (e por isso tem de voltar ao emparelhamento), nunca um PIN errado
// qualquer. /pos/entrar depende de dispositivo_atual E do PIN: um 401 dali
// pode ser um ou outro, e só o texto os distingue.
export const MSG_DISPOSITIVO_INVALIDO = 'Dispositivo não emparelhado.';

// --- Erros -----------------------------------------------------------------
//
// Cópia deliberada de lib/faturacao.js::detalhesErro — não uma importação. O
// POS não pode depender de nada desse módulo (ver o cabeçalho do ficheiro): a
// lógica é pequena e pura, e duplicá-la é o preço de manter os dois mundos
// verdadeiramente separados, sem um import que um dia arraste o resto. O
// 422 do FastAPI/Pydantic vem como um ARRAY de objectos ([{type, loc, msg,
// input}, ...]) — entregue cru a um toast, o sonner tenta renderizar o
// array como filho React e deita a página abaixo.
export const detalhesErroPos = (error, fallback) => {
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

// Mesmo crivo do backend (precos.py / caixa.py: _tem_mais_de_2_casas_decimais),
// duplicado aqui pela mesma razão que detalhesErroPos acima.
export const temMaisDe2CasasDecimaisPos = (valor) => {
  if (valor === '' || valor === null || valor === undefined) return false;
  const numero = Number(valor);
  if (!Number.isFinite(numero)) return false;
  const texto = numero.toString();
  if (texto.includes('e') || texto.includes('E')) return false;
  const casas = texto.includes('.') ? texto.split('.')[1] : '';
  return casas.length > 2;
};

// --- Chamadas ----------------------------------------------------------------

// Sem cabeçalhos (bootstrap): o dispositivo ainda não tem nenhum token neste
// momento — ver faturacao/pos_auth.py::emparelhar.
export const emparelhar = (codigo) => api.post('/pos/emparelhar', { codigo });

// X-Device-Token (dispositivo_atual). Precede /pos/entrar: é a grelha de
// caras do ecrã de entrada/tela de descanso.
export const getOperadoresDoDispositivo = () => api.get('/pos/operadores');

// X-Device-Token (dispositivo_atual). O PIN viaja sempre como string — nunca
// convertido para número, senão "0007" perdia os zeros à esquerda e podia
// colidir com o PIN de outra pessoa.
export const entrarComPin = (pin) => api.post('/pos/entrar', { pin });

// A partir daqui, X-Operator-Token (operador_atual) — nunca precisam do
// device token (a loja já vem embutida no JWT do operador).
export const getEstadoCaixa = (caixaId) =>
  api.get('/pos/caixa/estado', { params: caixaId ? { caixa_id: caixaId } : {} });

export const abrirCaixa = (dados) => api.post('/pos/caixa/abrir', dados);
export const registarMovimento = (dados) => api.post('/pos/caixa/movimento', dados);
export const fecharCaixa = (dados) => api.post('/pos/caixa/fechar', dados);
