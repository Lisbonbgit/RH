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

// --- Tectos de espera --------------------------------------------------------
//
// Sem `timeout`, o axios espera PARA SEMPRE. No POS isso não é uma espera: é
// o ecrã inteiro preso. As escritas da conta correm numa fila estritamente
// sequencial (PosVenda::executar, que existe para dois toques seguidos não
// gravarem por cima um do outro), por isso UM pedido pendurado — o Wi-Fi da
// loja a piscar, o PC do balcão a adormecer a placa de rede — bloqueia todos
// os que vierem a seguir, com um spinner de 14px ao lado da palavra "Produto"
// como único sinal. Se o pendurado for o Gravar do diálogo, a seta de voltar
// fica desligada e não há saída nenhuma a não ser o F5, que ninguém tem razão
// para adivinhar. O arranque ficava igual: o spinner de `carregando` para
// sempre.
//
// Dois valores, porque os dois casos não têm nada a ver um com o outro.
//
// 15 s (padrão) — tudo o que só fala com o Mongo: abrir a conta,
// juntar/editar/remover uma linha, o desconto, o cancelamento, o catálogo, o
// estado da caixa, o PIN. São pedidos de dezenas de milissegundos; 15 s é
// umas centenas de vezes isso — folga de sobra para um pico de rede ou um
// arranque frio do servidor — e continua curto o bastante para a fila se
// destravar sozinha com o cliente ainda à frente.
//
// 90 s (o que espera pelo VENDUS) — aqui a demora é legítima, não é avaria.
// Na emissão, o pior caminho NORMAL do servidor é: POST a estourar o timeout
// do httpx (`vendus/emissao.py`: 30 s) → VendusIndisponivel → verificação por
// referência externa, outro pedido com os mesmos 30 s → só então o 503 "não
// sabemos se saiu". São 60 s de trabalho legítimo antes de o servidor
// concluir seja o que for, mais os backoffs de 5xx (1 s + 2 s), mais o
// orçamento de espera pelo vencedor da reserva (fiscal.py: 50 × 0,05 s), mais
// o proxy e a rede. 90 s cobre isso com margem.
//
// **Curto de mais na emissão é PERIGOSO**, e é por isso que aqui se erra por
// excesso: desistir aos 30 s não cancela nada do outro lado — o POST ao
// Vendus continua a criar uma Fatura Simplificada REAL — só tira o ecrã de
// cima de uma emissão que está mesmo a acontecer. O fecho de caixa leva o
// mesmo tecto pela mesma razão: `caixa.py::fechar_caixa` reconcilia contra o
// Vendus (`fiscal.py::verificar_vendas_dinheiro_no_vendus`, uma leitura
// paginada por cada dia da sessão) antes de gravar o Z, e desistir a meio
// deixava a operadora sem o Z de uma caixa que fechou mesmo.
//
// Um pedido que estoura por timeout fica SEM `response` (é o que
// `semRespostaPos` reconhece). Na emissão isso é exactamente o que se quer:
// o PosVenda manda tudo o que não tem resposta para o balde 'incerto' — não
// se sabe se a fatura saiu, e a regra da casa é dizê-lo em vez de afirmar o
// que dá jeito.
export const TIMEOUT_PADRAO_MS = 15000;
export const TIMEOUT_COM_VENDUS_MS = 90000;

const api = axios.create({ baseURL: API_URL, timeout: TIMEOUT_PADRAO_MS });

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

// Um erro SEM `response`: o pedido nunca chegou ao servidor, a resposta
// perdeu-se pelo caminho, ou estourou o nosso tecto de espera acima. A
// diferença para um 4xx/5xx é tudo o que interessa — num erro com resposta o
// servidor DISSE alguma coisa; aqui não se sabe nada, nem sequer se o pedido
// chegou a ser executado do outro lado. Quem chama tem de tratar isto como
// "não sei", nunca como "não aconteceu": foi essa confusão que pôs o ecrã de
// finalizar a afirmar "há algo por corrigir nesta venda" a um pedido que
// podia estar, nesse instante, a emitir uma Fatura Simplificada real.
export const semRespostaPos = (error) => !!error && !error.response;

// ... e, destes, os que foram o NOSSO tecto de espera a disparar (o axios usa
// ECONNABORTED por omissão, ETIMEDOUT com clarifyTimeoutError ligado). Serve
// só para a mensagem poder dizer "não respondeu em 15 segundos" em vez de uma
// "falha de ligação" genérica, que mandava a operadora olhar para o router
// quando o problema podia ser o servidor a arrastar-se.
export const ehTimeoutPos = (error) =>
  semRespostaPos(error) && (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT');

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
//
// O `operadorId` (a cara em que se tocou) é OBRIGATÓRIO e vai junto: o
// servidor compara o PIN só com essa pessoa. Sem ele, esta chamada mandava
// apenas o PIN e o servidor entrava como o dono do PIN, fosse ele quem
// fosse — tocar numa cara e escrever o PIN de outra pessoa entrava como a
// outra, e era o nome dela que assinava as vendas e o fecho de caixa.
export const entrarComPin = (operadorId, pin) =>
  api.post('/pos/entrar', { operador_id: operadorId, pin });

// A partir daqui, X-Operator-Token (operador_atual) — nunca precisam do
// device token (a loja já vem embutida no JWT do operador).
export const getEstadoCaixa = (caixaId) =>
  api.get('/pos/caixa/estado', { params: caixaId ? { caixa_id: caixaId } : {} });

export const abrirCaixa = (dados) => api.post('/pos/caixa/abrir', dados);
export const registarMovimento = (dados) => api.post('/pos/caixa/movimento', dados);

// Tecto próprio: o fecho não é só uma escrita no Mongo — `caixa.py::
// fechar_caixa` reconcilia as vendas em dinheiro contra o Vendus antes de
// gravar o Z, e essa leitura é paginada por cada dia da sessão (ver
// TIMEOUT_COM_VENDUS_MS). Com os 15 s do padrão, uma reconciliação lenta
// deixava a operadora com um erro de timeout à frente de uma caixa que
// fechou mesmo — e sem o Z que ela precisa de ver.
export const fecharCaixa = (dados) =>
  api.post('/pos/caixa/fechar', dados, { timeout: TIMEOUT_COM_VENDUS_MS });

// --- Catálogo e tipos de pagamento -------------------------------------------
//
// Rotas PRÓPRIAS do POS (faturacao/pos_catalogo.py), não as do backoffice: as
// do backoffice (/produtos, /categorias, /tipos-pagamento) dependem todas do
// JWT de gestão, que este ecrã por desenho nunca tem.
//
// Um pedido só, e não três, porque isto é o arranque do ecrã com fila à
// frente. Traz `categorias`, `produtos` e `grupos_personalizacao`.
export const getCatalogoPos = () => api.get('/pos/catalogo');

// Cada tipo traz `da_troco` (se o ecrã mostra o recebido e o troco) e
// `pronto` (se está mesmo mapeado ao Vendus). Um tipo com `pronto: false`
// aparece na mesma, inutilizável: o finalizar recusa-o com 422, e é melhor
// vê-lo morto e explicado do que descobri-lo ao carregar em EMITIR com o
// cliente à frente.
export const getTiposPagamentoPos = () => api.get('/pos/tipos-pagamento');

// --- A conta do balcão -------------------------------------------------------

// A conta em curso desta caixa, ou `null` (200, não 404 — é o estado normal
// do início do dia). É o que devolve a venda depois da tela de descanso, de
// um F5 ou de o browser ir abaixo, em vez de a operadora repicar tudo.
export const getVendaAberta = (caixaId) =>
  api.get('/pos/venda/aberta', { params: { caixa_id: caixaId } });

export const abrirVenda = (caixaId) => api.post('/pos/venda', { caixa_id: caixaId });

export const juntarLinha = (vendaId, dados) =>
  api.post(`/pos/venda/${vendaId}/linhas`, dados);

export const editarLinha = (vendaId, linhaId, dados) =>
  api.put(`/pos/venda/${vendaId}/linhas/${linhaId}`, dados);

export const removerLinha = (vendaId, linhaId) =>
  api.delete(`/pos/venda/${vendaId}/linhas/${linhaId}`);

export const aplicarDescontoGlobal = (vendaId, dados) =>
  api.put(`/pos/venda/${vendaId}/desconto`, dados);

export const cancelarVenda = (vendaId) => api.post(`/pos/venda/${vendaId}/cancelar`);

// A emissão da Fatura Simplificada real. `dados` = { pagamentos: [{
// tipo_pagamento_id, valor }], nif }. Os erros deste pedido NÃO são todos
// iguais e o ecrã tem de os distinguir (ver PosFinalizar): 503 quer dizer
// que o servidor NÃO SABE se a fatura saiu — nunca convidar a repetir às
// cegas.
//
// Tecto próprio, e o mais largo de todos, porque é o único pedido em que
// desistir cedo de mais custa uma fatura a dobrar: o servidor pode estar
// legitimamente 60 s a falar com o Vendus (ver TIMEOUT_COM_VENDUS_MS), e o
// nosso timeout não cancela nada do outro lado — só nos tira o direito de
// saber o que aconteceu. Quando dispara, o erro fica sem `response` e o
// PosVenda trata-o como 'incerto', que é a verdade.
export const finalizarVenda = (vendaId, dados) =>
  api.post(`/pos/venda/${vendaId}/finalizar`, dados, { timeout: TIMEOUT_COM_VENDUS_MS });
