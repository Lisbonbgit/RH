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
// Em que modo é que o POS das lojas está a emitir: `{ modo: 'tests' | 'normal'
// | null }`. `null` é o terceiro estado — o servidor NÃO SABE (VENDUS_MODE
// ausente ou estragado), que é exactamente o conjunto de casos em que a emissão
// se recusa a acontecer. Ver `faturacao/modo.py`.
//
// JWT de gestão, como todas as deste ficheiro. A rota gémea do POS
// (`/pos/modo-de-emissao`) responde o mesmo com o token do dispositivo — não é
// a mesma rota porque as duas famílias de autenticação deste módulo nunca se
// misturam (test_protecao_rotas.py).
export const getModoDeEmissaoDoBackoffice = () =>
  axios.get(`${API_URL}/faturacao/modo-de-emissao`);

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

// Os métodos de pagamento da conta Vendus, lidos ao vivo (nunca escrevemos
// lá — ver o cabeçalho de faturacao/pagamentos.py). É desta lista que sai o
// `vendus_payment_method_id` de cada tipo, e é por isso que ela existe: sem
// esse id, `fiscal.py::finalizar` recusa a emissão com 422 no momento exacto
// em que a operadora carrega em EMITIR, com o cliente à frente.
//
// Vai numa chamada à parte do resto do ecrã de propósito: é rede, para uma
// conta que pode nem estar configurada, e o ecrã tem de continuar a gravar os
// outros campos quando ela falha.
export const getMetodosVendus = () => axios.get(`${API_URL}/faturacao/tipos-pagamento/metodos-vendus`);

// Utilizadores
export const getUtilizadores = () => axios.get(`${API_URL}/faturacao/utilizadores`);
export const criarUtilizador = (data) => axios.post(`${API_URL}/faturacao/utilizadores`, data);
export const editarUtilizador = (id, data) => axios.put(`${API_URL}/faturacao/utilizadores/${id}`, data);
export const mudarPin = (id, pin) => axios.put(`${API_URL}/faturacao/utilizadores/${id}/pin`, { pin });
export const mudarEstado = (id, ativo) => axios.put(`${API_URL}/faturacao/utilizadores/${id}/estado`, { ativo });

// Dispositivos POS (emparelhamento de PCs de loja)
export const getDispositivosPos = () => axios.get(`${API_URL}/faturacao/dispositivos-pos`);
export const gerarCodigoDispositivo = (data) => axios.post(`${API_URL}/faturacao/dispositivos-pos`, data);
export const revogarDispositivo = (id) => axios.delete(`${API_URL}/faturacao/dispositivos-pos/${id}`);

// Motivos de Nota de Crédito
export const getMotivos = () => axios.get(`${API_URL}/faturacao/motivos-nc`);
export const criarMotivo = (data) => axios.post(`${API_URL}/faturacao/motivos-nc`, data);
export const editarMotivo = (id, data) => axios.put(`${API_URL}/faturacao/motivos-nc/${id}`, data);
export const predefinirMotivo = (id) => axios.put(`${API_URL}/faturacao/motivos-nc/${id}/predefinir`);
export const apagarMotivo = (id) => axios.delete(`${API_URL}/faturacao/motivos-nc/${id}`);

// Categorias
export const getCategorias = () => axios.get(`${API_URL}/faturacao/categorias`);
export const criarCategoria = (data) => axios.post(`${API_URL}/faturacao/categorias`, data);
export const editarCategoria = (id, data) => axios.put(`${API_URL}/faturacao/categorias/${id}`, data);
export const apagarCategoria = (id) => axios.delete(`${API_URL}/faturacao/categorias/${id}`);

// Grupos de personalização (toppings)
export const getGrupos = () => axios.get(`${API_URL}/faturacao/grupos-personalizacao`);
export const criarGrupo = (data) => axios.post(`${API_URL}/faturacao/grupos-personalizacao`, data);
export const editarGrupo = (id, data) => axios.put(`${API_URL}/faturacao/grupos-personalizacao/${id}`, data);
export const apagarGrupo = (id) => axios.delete(`${API_URL}/faturacao/grupos-personalizacao/${id}`);

// Produtos
export const getProdutos = (params) => axios.get(`${API_URL}/faturacao/produtos`, { params });
export const getProdutosSemIva = () => axios.get(`${API_URL}/faturacao/produtos/sem-iva`);
export const criarProduto = (data) => axios.post(`${API_URL}/faturacao/produtos`, data);
export const editarProduto = (id, data) => axios.put(`${API_URL}/faturacao/produtos/${id}`, data);
export const apagarProduto = (id) => axios.delete(`${API_URL}/faturacao/produtos/${id}`);
export const mudarEstadoProduto = (id, ativo) => axios.put(`${API_URL}/faturacao/produtos/${id}/estado`, { ativo });

// Importação do catálogo Vendus
export const importarVendus = () => axios.post(`${API_URL}/faturacao/importacao/vendus`);

// Reservas fiscais presas — a gestão de uma emissão que ficou a meio
// (backend/faturacao/fiscal.py). Estas três são de GESTOR (token do
// backoffice), nunca do balcão: o POS não tem, nem pode ter, forma de
// libertar a sua própria reserva.
export const getReservasPresas = () => axios.get(`${API_URL}/faturacao/fiscal/reservas-presas`);

// Pergunta ao Vendus se a Fatura Simplificada desta venda saiu e, se saiu,
// grava-a. Não emite nada — por isso é que o pedido não tem (nem pode ter)
// campo nenhum para o número ou o ATCUD: esses vêm do Vendus ou não vêm de
// lado nenhum (ver PedidoReconciliarReserva). `nota` é só para o registo.
export const reconciliarReserva = (vendaId, nota) =>
  axios.post(`${API_URL}/faturacao/fiscal/reservas/${vendaId}/reconciliar`, {
    nota: nota || null,
  });

// Apaga a reserva e destranca a conta. `confirmadoNoVendus` é a declaração do
// gestor de que abriu o Vendus e viu que NÃO existe lá documento desta venda:
// sem ela o servidor recusa com um 422, e é de propósito que ela viaja como
// argumento obrigatório desta função em vez de um `true` fixo aqui dentro —
// libertar a reserva de uma fatura que saiu autoriza uma SEGUNDA Fatura
// Simplificada da mesma venda, entregue à AT.
export const libertarReserva = (vendaId, confirmadoNoVendus, nota) =>
  axios.post(`${API_URL}/faturacao/fiscal/reservas/${vendaId}/libertar`, {
    confirmado_no_vendus: confirmadoNoVendus,
    nota: nota || null,
  });

// --- Contas por cobrar de turnos JÁ FECHADOS ---------------------------------
//
// As que sobreviveram ao Z. Medido: 14,10 € divididos por 2, ninguém cobrado,
// caixa fechada — `GET /pos/venda/repartidas` → `[]`, `GET /pos/venda/aberta`
// → `null`, `GET /pos/caixa/contas-abertas` → `{quantas: 0}`, e as duas partes
// continuavam `aberta` na base com o `sessao_id` do turno anterior. Nenhum ecrã
// voltava a mostrá-las, e o `contas_abertas` que o fecho grava na sessão não
// tinha um único leitor.
//
// De GESTOR e não do POS, e é uma decisão: a operadora do turno seguinte não
// tem nada que mexer numa conta de um turno que outra pessoa fechou — as rotas
// de escrita da venda recusam-lho (`venda.py::_garante_sessao_desta_venda_
// aberta`), e um ecrã do balcão a mostrá-las era mandá-la fazer uma coisa que
// o servidor não lhe deixa.
export const getContasEsquecidas = () => axios.get(`${API_URL}/faturacao/caixa/contas-esquecidas`);

// Dá a conta por perdida: passa-a a `cancelada`, com o nome de quem o decidiu.
//
// **Só depois de perguntar a quem lá estava.** Cancelar declara "isto nunca
// foi pago", e isso pode ser falso — o cliente pode ter pago em dinheiro e a
// operadora esquecido-se de finalizar. Por isso o ecrã pede uma declaração
// explícita antes de chamar isto, o mesmo desenho do `libertarReserva` aqui em
// cima. O servidor recusa por sua conta as três que não se arrumam por aqui:
// a que já não está aberta, a de um turno AINDA ABERTO (essa é do balcão) e a
// que tem uma reserva fiscal por resolver (essa é do card de cima).
export const arrumarContaEsquecida = (vendaId) =>
  axios.post(`${API_URL}/faturacao/caixa/contas-esquecidas/${vendaId}/arrumar`);

// Mesmo crivo do backend (precos.py:_tem_mais_de_2_casas_decimais), para o
// campo dizer "não pode ter mais de 2 casas decimais" ANTES de ir ao
// servidor. Number.prototype.toString() em JS, tal como repr() em Python,
// devolve a representação decimal mais curta que reconstrói o número — por
// isso 8.99, 8.9 e 9 dão sempre a contagem de casas certa, sem arredondar
// nada (o que "comeria" cêntimos, ver o cabeçalho de precos.py).
export const temMaisDe2CasasDecimais = (valor) => {
  if (valor === '' || valor === null || valor === undefined) return false;
  const numero = Number(valor);
  if (!Number.isFinite(numero)) return false;
  const texto = numero.toString();
  if (texto.includes('e') || texto.includes('E')) return false; // notação científica: fora do universo de preços reais
  const casas = texto.includes('.') ? texto.split('.')[1] : '';
  return casas.length > 2;
};
