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
import { urlDaFoto } from './fotos';

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

// --- A conta de uma linha ----------------------------------------------------
//
// Vive aqui, e não dentro de um ecrã, porque são DOIS ecrãs a ler a mesma
// linha: o painel da conta (PosVenda) e a repartição (PosReparticao). Uma
// segunda cópia desta ordem de arredondamentos era o mesmo artigo a valer
// dois números diferentes em dois sítios do mesmo balcão.

// O `round(x, 2)` do Python, em JavaScript — e não o arredondamento natural
// daqui, que é outro.
//
// Isto era `Math.round(valor * 100) / 100`, e as duas coisas que essa linha
// fazia mal somam-se: multiplicar por 100 empurra o valor para cima do meio
// cêntimo (7,15 × 10 ÷ 100 é 0,71499999…, mas × 100 dá 71,5 redondo), e o
// `Math.round` arredonda o meio PARA CIMA. O Python olha para o valor exacto
// do double e, no empate mesmo, arredonda PARA O PAR. Um desconto em
// PERCENTAGEM que caia a meio do cêntimo decidia-se para lados diferentes nos
// dois sítios, e o ecrã prometia um cêntimo que a fatura desmentia: um Açaí
// Regular de 7,15 € com −10 % dividido por dois mostrava as pastilhas
// 3,22 / 3,21 (soma 6,43) por baixo de um total de 6,44 €, e o servidor
// repartia 3,22 / 3,22 — a segunda pessoa pagava um cêntimo a mais do que o
// ecrã lhe tinha prometido à frente do cliente.
//
// Como se faz o mesmo que ele em duas linhas:
//
// - `toFixed(2)` decide pelo valor EXACTO do double (é o que a norma exige),
//   e não pelo produto por 100 — logo aí acerta com o Python em tudo o que
//   não seja um empate exacto;
// - no empate exacto, `toFixed` sobe e o Python vai para o par. Um empate
//   exacto a 2 casas só existe quando o valor é um múltiplo ÍMPAR de 0,125
//   (0,125 · 0,375 · 0,625 · 1,125 …) — os únicos que o binário representa
//   mesmo em cima do meio cêntimo —, e é isso que o `× 8` reconhece sem
//   arredondar nada (multiplicar por uma potência de dois é exacto). Aí,
//   quando a subida deu um número ÍMPAR de cêntimos, desce-se um: é a mesma
//   escolha do par.
//
// Verificado contra o `round(x, 2)` do Python em 124 000 valores (todos os
// múltiplos ímpares de 0,125 até 500 €, todas as percentagens de desconto da
// casa sobre todos os preços até 40 €, e 80 000 aleatórios): zero
// divergências, contra 5340 da versão anterior. O guarda que o prova vive em
// `backend/tests/faturacao/test_arredondamento_do_ecra.py`, e corre este
// mesmo código em Node — nunca uma cópia dele escrita lá.
//
// **Exportada, e é por isso que ela vive aqui e não dentro do `contasDaLinha`.**
// O `PosDialogoProduto` faz a conta da linha por sua conta — a dele trabalha
// sobre campos de texto a meio de serem escritos, esta sobre uma linha que o
// servidor já aceitou — e tinha aqui a SUA cópia desta função, com o mesmo
// defeito e um comentário a dá-lo por inevitável. A ENTRADA das duas é
// diferente e tem de ser; a ORDEM dos passos e o ARREDONDAMENTO não são —
// são, os dois, os de `precos.linha_de_venda`. Corrigir o arredondamento num
// sítio e deixar o outro a dizer 6,43 € onde o servidor grava 6,44 € é o
// mesmo número a valer duas coisas no mesmo balcão.
export const arredondarComoOServidor = (valor) => {
  const x = Number(valor);
  // NaN e Infinito passam como estavam: quem chama já os filtra
  // (`Number(...) || 0`), e inventar aqui um 0 escondia um valor estragado.
  if (!Number.isFinite(x)) return x;
  const centimos = Math.round(Number(Math.abs(x).toFixed(2)) * 100);
  const empate = Number.isInteger(x * 8) && Math.abs(x * 8) % 2 === 1;
  const escolhido = empate && centimos % 2 === 1 ? centimos - 1 : centimos;
  return (x < 0 ? -escolhido : escolhido) / 100;
};

// Nome curto para as contas aqui em baixo, onde ele aparece quatro vezes na
// mesma expressão.
const cent = arredondarComoOServidor;

// O total de uma linha JÁ GRAVADA, na MESMA ordem de `precos.linha_de_venda`:
// as opções somam ao preço unitário, o resultado multiplica pela quantidade,
// e só depois entra o desconto (com `round` a cada passo, como o servidor).
//
// É uma leitura da linha, para a coluna "Preço" do print — nunca um total da
// conta: esse é o `venda.totais.total` do servidor, e é ele que se mostra.
// Isto acerta com o servidor ao cêntimo (o `cent` acima faz o mesmo
// arredondamento que ele), mas continua a não somar a conta toda: o desconto
// GLOBAL não passa por aqui, e uma soma destas linhas apresentada como total
// seria um número que ninguém do outro lado calculou.
//
// O `PosDialogoProduto` tem a sua própria versão desta conta de propósito, e a
// diferença é a ENTRADA e só ela: a dele trabalha sobre campos de texto a meio
// de serem escritos, esta trabalha sobre uma linha que o servidor já aceitou.
// Os passos são os mesmos nos dois, e nos dois são os de
// `precos.linha_de_venda` — quem lá mexer tem de mexer aqui.
export const contasDaLinha = (linha) => {
  const base = linha.preco_override != null ? linha.preco_override : linha.produto_preco;
  const extra = (linha.opcoes || []).reduce((soma, o) => soma + (Number(o?.preco) || 0), 0);
  const unitario = cent((Number(base) || 0) + extra);
  const bruto = cent(unitario * (Number(linha.quantidade) || 0));
  // Truthiness, como o servidor (`if desconto_eur: ... elif desconto_pct:`):
  // um desconto de 0 € não é desconto e deixa passar a percentagem.
  const desconto = linha.desconto_eur
    ? Number(linha.desconto_eur)
    : (linha.desconto_pct ? cent(bruto * Number(linha.desconto_pct) / 100) : 0);
  return { unitario, bruto, desconto, total: cent(bruto - desconto) };
};

// --- As unidades de uma conta ------------------------------------------------

// As casas decimais da QUANTIDADE — as MESMAS de
// `faturacao/reparticao.py::CASAS_DA_QUANTIDADE`. Um guarda em
// `test_partes_por_cobrar_no_ecra.py` confronta este número com o de lá: as
// quantidades fraccionadas que aqui se somam são as que o servidor gravou com
// essa resolução, e duas resoluções diferentes davam duas contagens diferentes
// da mesma conta.
export const CASAS_DA_QUANTIDADE_POS = 5;

const UNIDADES_POR_QUANTIDADE = 10 ** CASAS_DA_QUANTIDADE_POS;

// Quantas UNIDADES leva esta conta — a soma das quantidades das linhas, feita
// em unidades INTEIRAS e só depois convertida.
//
// A soma em cru (`soma + Number(li.quantidade)`) era vírgula flutuante a somar
// vírgula flutuante: numa parte recuperada de uma conta dividida, cujas
// quantidades têm cinco casas, o painel escrevia **"2 Produtos /
// 0.9666699999999999 Uni."**. Não mexe em dinheiro — o total é sempre o
// `venda.totais.total` do servidor —, mas é o género de número que faz a
// operadora desconfiar de tudo o resto que está no mesmo ecrã, e ela tem o
// cliente à frente.
//
// É a mesma disciplina de `reparticao.py` e de `venda.py::_unidades`: o que se
// SOMA conta-se em inteiros, nunca em floats. Aqui o inteiro é a unidade
// mínima da quantidade (10⁻⁵), não o cêntimo, porque o que se soma são
// quantidades e não dinheiro.
export const unidadesDaConta = (linhas) => {
  const emUnidades = (linhas || []).reduce(
    (soma, li) => soma + Math.round((Number(li?.quantidade) || 0) * UNIDADES_POR_QUANTIDADE),
    0,
  );
  return emUnidades / UNIDADES_POR_QUANTIDADE;
};

// A MESMA repartição do servidor (`reparticao.repartir_centimos`), em cêntimos
// INTEIROS: a base para todos e o cêntimo que sobra para as PRIMEIRAS partes.
//
// Existe aqui por uma razão só — o ecrã tem de poder dizer quanto vai pagar
// cada pessoa ANTES de dividir, com o cliente à frente a perguntar. Os valores
// que contam continuam a ser os que o servidor devolve em cada parte, e é por
// isso que esta conta tem de ser a mesma que a de lá: um ecrã a prometer
// 3,00 / 3,00 / 2,99 e um servidor a repartir de outra maneira é uma promessa
// que a fatura desmente à frente do cliente.
export const repartirCentimos = (totalCentimos, partes) => {
  if (!(partes >= 1)) return [];
  const total = Math.round(Number(totalCentimos) || 0);
  const base = Math.floor(total / partes);
  const resto = total - base * partes;
  return Array.from({ length: partes }, (_, i) => base + (i < resto ? 1 : 0));
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

// O Ponto de Caixa: a conferência a meio do turno. É um GET e o servidor não
// escreve uma única vez a responder-lhe — não marca `a_fechar`, não carimba
// a sessão, não confirma movimento nenhum. Pode ser pedido as vezes que
// forem precisas, dos dois PCs do mesmo balcão, e no meio de uma venda.
//
// Fica no timeout PADRÃO, e não no do Vendus: ao contrário do fecho, isto
// só fala com o Mongo. E é bom que estoure depressa — a operadora está a
// meio do turno e volta a pedir.
export const getPontoDeCaixa = (caixaId) =>
  api.get('/pos/caixa/ponto', { params: { caixa_id: caixaId } });

// Tecto próprio: o fecho não é só uma escrita no Mongo — `caixa.py::
// fechar_caixa` reconcilia as vendas em dinheiro contra o Vendus antes de
// gravar o Z, e essa leitura é paginada por cada dia da sessão (ver
// TIMEOUT_COM_VENDUS_MS). Com os 15 s do padrão, uma reconciliação lenta
// deixava a operadora com um erro de timeout à frente de uma caixa que
// fechou mesmo — e sem o Z que ela precisa de ver.
export const fecharCaixa = (dados) =>
  api.post('/pos/caixa/fechar', dados, { timeout: TIMEOUT_COM_VENDUS_MS });

// O que fica por cobrar se a caixa fechar agora: `{ quantas, total, contas }`.
// Só leitura, e é chamada pelo diálogo do fecho ANTES da contagem — a
// operadora tem de poder ver isto enquanto ainda pode ir cobrar ou cancelar,
// não depois de assinar o Z. O Z que sai a seguir traz a mesma lista outra
// vez, essa já definitiva (ver `caixa.py::_contas_abertas_da_sessao`).
export const getContasAbertasDaCaixa = (caixaId) =>
  api.get('/pos/caixa/contas-abertas', { params: { caixa_id: caixaId } });

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

// **Entregar ao gestor a conta TRAVADA** — o botão "Servir o cliente seguinte".
//
// Era um gesto só do ecrã (`aplicarVenda(null)` e mais nada), e essa era a
// raiz do pior defeito desta ronda: o servidor continuava a contar a conta
// como travada — uma dedução a partir da reserva fiscal, não um facto gravado
// — e no instante em que o gestor libertasse a reserva ela voltava a ser uma
// conta normal do balcão. Ressuscitava à frente do cliente SEGUINTE, sem marca
// nenhuma, e o primeiro produto dele aterrava na conta do anterior: medido,
// 8,99 € + 2,00 € numa Fatura Simplificada de 10,99 € com o açaí de outra
// pessoa.
//
// Agora é uma ESCRITA: o servidor grava `entregue_ao_gestor_em` na venda, e a
// partir daí ela sai ao mesmo tempo da porta do `POST /pos/venda` e do
// `GET /pos/venda/aberta`. Não volta ao balcão — resolve-se no backoffice.
export const entregarContaAoGestor = (vendaId) =>
  api.post(`/pos/venda/${vendaId}/entregar-ao-gestor`);

// A venda pelo ID, em QUALQUER estado — e com o `documento` fiscal lá
// dentro quando já existe (venda.py::obter_venda). É a única pergunta
// honesta que o ecrã pode fazer depois de uma emissão que não devolveu 200:
// em vez de adivinhar pelo status do erro o que aconteceu à Fatura
// Simplificada, vai perguntar ao servidor pelo id que já tem em mãos.
//
// `getVendaAberta` não serve para isto, e é por desenho: filtra
// `estado: "aberta"` e devolve `null` assim que a venda passa a `emitida` —
// que é exactamente o caso a tratar, o da fatura que SAIU e cuja resposta se
// perdeu pelo caminho.
export const obterVenda = (vendaId) => api.get(`/pos/venda/${vendaId}`);

// --- O travão da conta -------------------------------------------------------
//
// `emissao_por_confirmar` é calculado pelo SERVIDOR
// (venda.py::_emissao_por_confirmar: existe reserva fiscal em
// fat_refs_fiscais E a venda ainda não está `emitida`) e vem em TODAS as
// respostas de venda. É exactamente o estado em que as cinco rotas de
// escrita recusam qualquer alteração com 409 (`_garante_sem_emissao`): a
// conta está congelada porque pode haver uma Fatura Simplificada real a
// nascer, ou já nascida e por confirmar.
//
// Vive aqui, e não dentro de um ecrã, para haver UMA definição só. Antes o
// travão era o `erroEmissao` do React — a memória do 503 que tinha acabado
// de chegar — e a seta de voltar limpava-o, tal como o F5, a tela de
// descanso e o outro PC: a conta voltava a parecer normal, editável e com o
// EMITIR aceso, por cima de uma fatura que podia ter saído. Derivado do
// servidor, sobrevive a tudo isso.
//
// `=== true` de propósito, e não a verdade genérica do JavaScript: uma
// resposta sem o campo (uma versão do servidor anterior a ele) não pode
// ler-se como "travada" — trancava o balcão inteiro sem razão nenhuma — e
// escrever a comparação à vista é o que torna essa decisão legível.
export const contaTravada = (venda) => venda?.emissao_por_confirmar === true;

// --- A dúvida que ainda não foi apurada --------------------------------------
//
// O outro travão, e o que ele tem de diferente do de cima: `contaTravada` é o
// que o SERVIDOR sabe; isto é o que o ECRÃ não conseguiu confirmar. Quando a
// emissão falha, o PosVenda vai reler a venda para saber o que aconteceu —
// e há dois desfechos em que essa releitura não resolve a dúvida:
//
//   'incerto'          — o servidor disse que não sabe se a fatura saiu
//                        (503 do `VerificacaoFiscalIncerta`), ou não disse
//                        nada de todo (sem resposta, 504, 500).
//   'recusado-incerto' — o servidor recusou com 409 e explicou porquê, mas a
//                        releitura falhou (ou trouxe a conta ainda travada):
//                        não se conseguiu ver se aquela venda foi emitida ou
//                        cancelada.
//
// Nos dois, a única coisa honesta é a mesma: **não se afirma nada e não se
// emite**. Vive aqui, e não dentro de um ecrã, porque são DOIS ecrãs a ter de
// concordar sobre a mesma lista — o PosVenda, que decide o balde e congela a
// conta, e o PosFinalizar, que desliga o EMITIR e desenha o painel. Com a
// lista escrita duas vezes, bastava acrescentar um balde novo num dos lados
// para o outro voltar a deixar emitir por cima de uma Fatura Simplificada que
// pode ter saído.
export const DUVIDAS_POR_APURAR = ['incerto', 'recusado-incerto'];

export const duvidaPorApurar = (erroEmissao) =>
  !!erroEmissao && DUVIDAS_POR_APURAR.includes(erroEmissao.tipo);

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

// --- Dividir e separar a conta -----------------------------------------------
//
// Cada parte que estas duas devolvem é uma VENDA NORMAL deste módulo (a mesma
// forma de `_venda_publica`, com `conta_mae_id` preenchido): daí em diante
// emite-se, cancela-se e pergunta-se por ela exactamente com as chamadas que
// já existem aqui em cima. Não há um segundo caminho de emissão para as
// partes, e é isso que mantém o núcleo fiscal — a reserva atómica, a
// idempotência, o travão — a valer para elas sem uma linha nova.
//
// `partes` é um NÚMERO no dividir (por quantas pessoas) e uma LISTA no separar
// (quem leva o quê): [{ linhas: [{ linha_id, quantidade }] }, …].

// O dinheiro compara-se e soma-se em CÊNTIMOS INTEIROS, nunca em vírgula
// flutuante (regra 1 do cabeçalho de `venda.py`, do lado do ecrã). Estas duas
// vivem aqui porque `razaoDeNaoComecar` as usa, e essa frase é executada por um
// teste em Node — uma cópia no componente ficava fora do alcance dele.
const centimosPos = (valor) => Math.round((Number(valor) || 0) * 100);

// **O dinheiro que NÃO É UM NÚMERO nunca se desenha como zero.** É a ÚNICA
// formatação de dinheiro do POS, e é ela que os oito ecrãs importam — havia
// oito cópias desta linha, todas com o mesmo `(Number(valor) || 0)`, e esse
// `|| 0` transformava `undefined`, `null`, `NaN`, `''`, `{}` e `'abc'` num
// "€ 0,00" perfeitamente legível.
//
// **Medido, e é o pior desfecho possível:** uma venda emitida sem
// `pagamentos` deixava a coluna "Por tipo de pagamento" a somar 10,20 €
// debaixo de um "Total cobrado 11,35 €" — 1,15 € desaparecidos sem uma
// palavra; e um `resumo` ausente (o servidor não respondeu, o campo mudou de
// nome) pintava um turno INTEIRO de € 0,00, com "Deve estar na gaveta
// € 0,00" — a operadora fecha a gaveta com 200 € lá dentro e o ecrã diz-lhe
// que está certo.
//
// Um valor que não é um número finito sai "€ ?": não se parece com um número,
// não se soma de cabeça e obriga a perguntar. Zero continua a ser "€ 0,00",
// que é uma resposta e não uma ausência.
//
// `null` e `''` são recusados de propósito, apesar de o `Number()` os
// converter em 0: são exactamente as duas ausências que chegam de uma
// resposta JSON e de um campo de texto vazio.
export const numeroPos = (valor) => {
  const n = typeof valor === 'string' && valor.trim() !== '' ? Number(valor) : valor;
  if (typeof n !== 'number' || !Number.isFinite(n)) return '?';
  return n.toLocaleString('pt-PT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const eurosPos = (valor) => `€ ${numeroPos(valor)}`;

// **Um valor de dinheiro COM O SINAL QUE ELE TEM** — e não com um `+` escrito
// à mão por cima dele.
//
// Medido no ecrã do turno: com uma devolução em dinheiro maior do que a fatura
// recebeu, a linha lia-se «Vendas em dinheiro **+ € -15,40**» — um mais colado
// a um número negativo. É a linha onde o vazamento aparece primeiro, e com
// pressa lê-se ao contrário. O `−` é o mesmo traço da linha das "Saídas", e a
// magnitude vai formatada como qualquer outro euro.
//
// O que não é um número finito continua a sair "€ ?" pelo `numeroPos`, com o
// `+` à frente: um sinal inventado sobre uma ausência seria pior do que a
// ausência.
export const eurosComSinal = (valor) => {
  const n = typeof valor === 'string' && valor.trim() !== '' ? Number(valor) : valor;
  return typeof n === 'number' && Number.isFinite(n) && n < 0
    ? `− ${eurosPos(-n)}`
    : `+ ${eurosPos(n)}`;
};

// --- As duas perguntas do resumo do turno, executáveis ------------------------
//
// Vivem aqui, e não escritas dentro do JSX do `PosResumoDoTurno`, por uma razão
// medida: uma condição escrita no meio de uma tabela não se corre em lado
// nenhum, e um guarda que só procure o TEXTO da frase fica verde com a condição
// desligada (`false && …`). Os ecrãs do POS desenham-se sem servidor nenhum, e
// dois defeitos foram a produção exactamente assim.

// **A linha do mapa cuja taxa o servidor não reconheceu.** Ela vem com `base` e
// `iva` a `null` e o `total` preenchido — e é por isso que a última linha da
// tabela deixa de fechar: base + IVA não dá o total. Medido ao balcão:
// «XPTO (?) | 1 | — | — | € 1,15» e o rodapé a somar 9,03 + 1,17 contra um
// total de 11,35, sem uma palavra. Lê-se como um total partido.
// **A gaveta que o servidor diz estar ABAIXO DE ZERO.** É rara e é a leitura
// mais perigosa do Z, porque a linha que vem a seguir mente sozinha: com
// `esperado` a −25,86 € e a gaveta contada a 0,00, a `diferenca` é **+25,86 €**
// e desenha-se exactamente como uma SOBRA.
//
// Um movimento já não lá chega — o servidor recusa a saída que tira mais do que
// está na gaveta (`caixa.py::registar_movimento`). O que ainda lá chega é uma
// DEVOLUÇÃO em dinheiro maior do que as vendas em dinheiro do turno, e essa não
// se recusa: é um documento fiscal (ver `nota_credito.pagamentos_da_fatura`).
//
// `null` e um campo ausente NÃO são negativos — «não veio» não pode acender um
// aviso sobre dinheiro (o `Number(null)` é 0 e o `Number(undefined)` é NaN, e
// os dois caem fora por `Number.isFinite`).
export const gavetaAbaixoDeZero = (resumo) => {
  const n = resumo?.esperado;
  return typeof n === 'number' && Number.isFinite(n) && n < 0;
};

// **O `src` da foto de um produto, no POS.** A regra vive em `lib/fotos.js`
// (o backoffice usa a mesma, e uma cópia aqui era a nona cópia da mesma linha
// que este módulo já teve em oito ecrãs). A base é a do backend, para a foto
// nossa — que é gravada com um endereço RELATIVO — continuar a desenhar-se num
// embrulho onde a API viva noutro anfitrião.
export const urlDaFotoPos = (valor) =>
  urlDaFoto(valor, process.env.REACT_APP_BACKEND_URL);

export const temTaxaDesconhecida = (mapa) =>
  (mapa || []).some((linha) => linha?.taxa === null || linha?.taxa === undefined);

// **O que foi facturado e não tem pagamento nenhum por baixo.** O número vem
// SOMADO do servidor (`pagamentos_por_registar`): o ecrã nunca soma colunas de
// dinheiro. Uma venda emitida sem `pagamentos` deixava a coluna a somar 10,20 €
// debaixo de um "Total cobrado 11,35 €" — 1,15 € desaparecidos sem uma palavra.
//
// `> 0` e não a verdade genérica: `0` é o caso normal (está tudo cobrado) e não
// desenha linha nenhuma; e um valor que não seja um número não pode ligar uma
// linha de dinheiro em branco.
export const haPagamentosPorRegistar = (resumo) =>
  typeof resumo?.pagamentos_por_registar === 'number'
  && Number.isFinite(resumo.pagamentos_por_registar)
  && resumo.pagamentos_por_registar !== 0;

// **O QUE SAIU DA GAVETA A MAIS.** Um turno só pode tirar da gaveta o que lá
// pôs, e isso lê-se nas VENDAS EM DINHEIRO do turno: as faturas menos as
// devoluções. Medido no servidor: fatura de 24,14 € paga 5,00 em dinheiro +
// 19,14 em Multibanco, açaí de 20,40 € devolvido em DINHEIRO →
// `vendas_dinheiro` −15,40 €. A operadora contava a gaveta, batia certo — e
// tinham saído 15,40 € que aquele turno não pôs lá.
//
// **Não é «o esperado abaixo do fundo», e essa era a versão anterior desta
// pergunta.** O esperado inclui os movimentos de caixa, e por isso ela falhava
// nos dois sentidos — medidos os dois em `caixa._resumo_do_turno`: um reforço
// de troco de 20,00 € apagava o aviso com o vazamento intacto, e uma sangria
// de 30,00 € para o cofre acendia-o sem devolução nenhuma. Sangrias e
// pagamentos a fornecedor em dinheiro são rotina numa loja com depósito
// diário: o aviso acendia todas as noites, e a noite verdadeira era igual às
// outras.
//
// O número vem SOMADO do servidor (`tirado_da_gaveta_a_mais`, em
// `caixa_math`): este ecrã não subtrai euros para descobrir se há um aviso —
// comparar campos aqui era uma segunda aritmética de dinheiro no browser, e a
// regra da casa é que não há nenhuma.
//
// `> 0` e não a verdade genérica, pela mesma razão do `haPagamentosPorRegistar`
// aqui em cima: zero é o caso normal e não desenha aviso nenhum.
export const tirouDaGavetaAMais = (resumo) =>
  typeof resumo?.tirado_da_gaveta_a_mais === 'number'
  && Number.isFinite(resumo.tirado_da_gaveta_a_mais)
  && resumo.tirado_da_gaveta_a_mais > 0;

// **E o PORQUÊ, que é uma pergunta PRÓPRIA e não um adorno do aviso de cima.**
//
// `devolucoes_acima_do_recebido` é o leitor de
// `nota_credito.devolucao.acima_do_recebido` — quanto é que as devoluções do
// turno passaram o que aquelas faturas receberam NAQUELE meio de pagamento.
// A frase que o anuncia estava pendurada no predicado da gaveta, e por isso
// desaparecia com ele: com um reforço de troco na gaveta o servidor calculava
// 15,40 € e o ecrã não escrevia nada. O campo voltava a ser só de escrita, que
// é exactamente o defeito que ele veio fechar.
//
// E as duas respostas podem divergir com toda a legitimidade: um turno com uma
// fatura de 100,00 € em dinheiro e outra paga 5,00 em dinheiro + 6,29 em
// Multibanco, creditada em DINHEIRO por 9,85 €, tem a gaveta do turno bem
// (+95,15 €) e 4,85 € devolvidos por um meio que aquela fatura não recebeu.
export const haDevolucoesAcimaDoRecebido = (resumo) =>
  typeof resumo?.devolucoes_acima_do_recebido === 'number'
  && Number.isFinite(resumo.devolucoes_acima_do_recebido)
  && resumo.devolucoes_acima_do_recebido > 0;

// --- A conta repartida, vista de fora ----------------------------------------
//
// Duas perguntas que o PosVenda faz em quatro sítios — a nota do painel do
// balcão, o travão que impede uma segunda repartição, a razão encostada aos
// botões de repartir e a seta de voltar do finalizar. Vivem aqui, e não
// escritas à mão em cada um deles, porque foi exactamente assim que as duas
// se trocaram uma pela outra: a seta de voltar perguntava "**há** partes por
// cobrar?" quando a pergunta era "**esta conta é** uma delas?", e com partes
// vivas o finalizar de uma conta normal do balcão largava-a do ecrã e aterrava
// nas partes do cliente anterior — a conta ficava aberta no servidor, sem uma
// palavra no ecrã.

// As partes que ainda estão por cobrar NESTE POSTO: nem emitidas, nem
// canceladas, nem entregues ao gestor. O `estado` é sempre o que o SERVIDOR
// gravou — uma parte emitida ou cancelada noutro sítio tem de se ler aqui como
// o que ela é agora, nunca como o que este ecrã se lembra dela.
//
// **`entregue_ao_gestor_em` entra nesta pergunta pela mesma razão que entra em
// `venda.py::_filtro_do_balcao`:** é este conjunto que decide a faixa "faltam
// cobrar N pessoas", o travão da segunda repartição e a razão encostada aos
// botões — e uma parte travada que a operadora já entregou ao gestor não é
// coisa que ela consiga cobrar nem cancelar. Contá-la era pôr o ecrã a pedir
// uma acção que a rota recusa, que é o defeito que esta ronda inteira
// persegue. O "de M" da faixa não encolhe: esse é o comprimento da lista toda,
// e uma conta não pode parecer mais pequena do que foi.
export const partesAbertas = (partes) =>
  (partes || []).filter((p) => p?.estado === 'aberta' && !p?.entregue_ao_gestor_em);

// **Esta conta é de OUTRA caixa deste posto?**
//
// Desde que a porta (`venda.py::abrir_venda`) e o ecrã
// (`GET /pos/venda/aberta`) passaram a ler o MESMO conjunto — o do POSTO, em
// qualquer caixa cuja sessão esteja aberta (`venda.py::_contas_do_balcao`) —,
// a conta que o ecrã põe à frente pode ter nascido noutra caixa. É o caso
// normal da troca de caixa: a operadora pica 8,99 € no Balcão, o PC passa para
// o Drive (o ecrã «Qual caixa?» do PosApp), e a conta continua à frente dela.
//
// Antes disto, esse mesmo arranjo era um BECO: o ecrã respondia `null` e a
// rota respondia 409 «acabe a que está à frente», com nada à frente. Agora a
// conta está lá — e tem de dizer DE ONDE, senão a operadora olha para uma
// conta que não sabe de onde veio e desconfia de tudo o resto no mesmo ecrã.
//
// Vive aqui, e não escrita dentro do painel, pela razão de sempre neste
// ficheiro: uma decisão que nenhum teste consegue EXECUTAR é uma decisão que
// ninguém está a guardar. Sem um dos dois ids a resposta é `false` — não se
// inventa uma diferença a partir do que não se sabe.
export const contaDeOutraCaixa = (venda, caixaId) =>
  !!venda?.caixa_id && !!caixaId && venda.caixa_id !== caixaId;

// Esta venda é UMA das partes em cobrança? Compara-se pelo `id`, que é o que
// não muda: a parte volta do servidor a cada leitura com totais e estado
// diferentes, e comparar o objecto (ou o total) dava "não" a meio da
// cobrança. Sem `id` a resposta é sempre `false` — uma conta que ainda não
// nasceu no servidor não é parte de nada.
export const ehUmaDasPartes = (venda, partes) =>
  !!venda?.id && (partes || []).some((p) => p?.id === venda.id);

// --- Porque é que a GRELHA DE PRODUTOS está morta ----------------------------
//
// **A decisão vive aqui porque é aqui que um teste lhe chega.** Estava dentro
// do `PosVenda.js`, e o guarda que existia sobre ela só verificava que certos
// identificadores APARECIAM no ficheiro: partir o bloqueio a sério deixava-o
// verde. Uma decisão que nenhum teste consegue EXECUTAR é uma decisão que
// ninguém está a guardar — é a mesma razão que já trouxe para cá o
// `ehUmaDasPartes` e o `partesAbertas`.
//
// **Isto é a cortesia; quem recusa é a ROTA.** `venda.py::abrir_venda` responde
// 409 a quem tente começar a conta do cliente seguinte com uma conta por
// resolver neste posto, e é essa recusa que fecha a porta — os ecrãs do POS
// desenham-se sem servidor nenhum, e um ecrã que evita o pedido não impede
// pedido nenhum. Estas frases só evitam que a operadora descubra a regra a
// bater com o nariz nela, com o cliente à frente.

// Porque é que não se COMEÇA a conta do cliente seguinte — ou `null` quando se
// pode. Um posto atende um cliente de cada vez: uma conta dividida só acaba
// quando todas as partes estiverem cobradas ou canceladas, e até lá não há
// cliente seguinte neste PC.
export const razaoDeNaoComecar = (porCobrar) => {
  if (porCobrar.length === 0) return null;
  const falta = porCobrar.reduce((soma, p) => soma + centimosPos(p?.totais?.total), 0);
  return `${porCobrar.length === 1
    ? 'Ainda falta cobrar 1 pessoa'
    : `Ainda faltam cobrar ${porCobrar.length} pessoas`} desta conta `
    + `(${eurosPos(falta / 100)}). Atende-se um cliente de cada vez: acabe esta conta — `
    + 'cobre ou cancele as partes que faltam — antes de começar a do cliente seguinte.';
};

// A frase curta que fica no `title` de cada cartão de produto quando a conta à
// frente está travada. Diz a saída, e a saída é um botão que existe:
// "Servir o cliente seguinte" entrega a conta ao gestor
// (`venda.py::entregar_ao_gestor`).
export const MSG_CONTA_TRAVADA_CURTA =
  'Conta travada: há uma emissão de fatura por confirmar. Toque em «Servir o cliente '
  + 'seguinte» para a entregar ao gestor e atender o próximo — é ele que a resolve.';

// **A decisão inteira, numa função só:** porque é que os cartões de produto
// estão apagados, ou `null` quando não estão.
//
// Duas razões, e as duas são o servidor a recusar:
//   1. a conta à frente está TRAVADA — nenhuma linha entra nela
//      (`venda.py::_garante_sem_emissao`), e a saída é entregá-la ao gestor;
//   2. não há conta à frente e há partes por resolver neste posto — nenhuma
//      conta nova nasce aqui (`venda.py::abrir_venda`, 409).
//
// **Com uma conta À FRENTE que não está travada, a grelha está VIVA** — e tem
// de estar: tocar num produto junta-lhe uma linha, que é o cliente que ela
// está a atender. Só quando não há conta nenhuma é que o toque tenta abrir uma
// nova, e é só aí que a recusa da rota entra em jogo.
export const razaoDaGrelhaMorta = ({ venda, partes }) => {
  if (contaTravada(venda)) return MSG_CONTA_TRAVADA_CURTA;
  if (venda) return null;
  return razaoDeNaoComecar(partesAbertas(partes));
};

export const dividirConta = (vendaId, partes) =>
  api.post(`/pos/venda/${vendaId}/dividir`, { partes });

export const separarConta = (vendaId, partes) =>
  api.post(`/pos/venda/${vendaId}/separar`, { partes });

// --- E a repartição depois de o browser se ter esquecido dela ----------------
//
// **A repartição vivia SÓ na memória do browser, e o dinheiro por receber
// desaparecia com ela.** Um F5, a tela de descanso, um "Trocar de operador" ou
// o browser a ir abaixo, e a faixa "Faltam cobrar 2 pessoas de 2 — 14,10 €"
// sumia do ecrã sem uma palavra. Medido, com o servidor a confirmar: dividido
// 14,10 € por duas pessoas, servido o cliente seguinte e carregado em "Trocar
// de operador" — a conta do balcão foi recuperada (`getVendaAberta` sempre
// soube fazê-lo) e as duas partes não; `abertas no servidor: v-5, v-6, v-7`
// contra `devolve: v-7`.
//
// É o mesmo acidente que o `contaTravada` já resolveu duas secções acima, e a
// solução é a mesma: **a verdade vem do servidor**. Cada grupo tem a forma
// EXACTA do que `dividirConta`/`separarConta` devolvem — `{ modo, conta_mae,
// partes }` — para o ecrã montar a repartição pelo mesmo caminho, venha ela
// de um toque ou de um arranque.
export const getContasRepartidas = (caixaId) =>
  api.get('/pos/venda/repartidas', { params: { caixa_id: caixaId } });

// A repartição como o PosVenda a guarda (`{ modo, mae, partes }`), a partir do
// que qualquer uma das três rotas devolve. Vive aqui para não haver duas
// traduções da mesma resposta: enquanto o arranque montasse este objecto à
// mão, bastava o servidor ganhar um campo para o caminho do F5 ficar com uma
// repartição diferente da do toque.
//
// `modo` a `null` (uma repartição feita antes de o servidor o gravar) cai no
// valor por omissão do PosReparticao — é o que ele já fazia, e é melhor do que
// inventar aqui um modo que ninguém escolheu.
export const reparticaoDoServidor = (grupo) => (
  grupo?.conta_mae
    ? { modo: grupo.modo || 'dividir', mae: grupo.conta_mae, partes: grupo.partes || [] }
    : null
);

// --- Em que modo é que este POS está a emitir --------------------------------
//
// **O dono perguntou «neste momento está tudo em teste né? posso fazer faturas
// aqui normal.» e ninguém soube responder sem ir ao servidor.** Enquanto a
// resposta viver só numa variável de ambiente, os dois enganos ficam ambos
// possíveis, e são simétricos:
//
// - em `tests` sem aviso, a operadora julga que está a vender a sério — o
//   cliente leva um talão sem valor, **nada chega à Autoridade Tributária**, e
//   a loja pensa que facturou o dia;
// - em `normal` com o aviso ligado, ela julga que está a treinar e emite
//   **Faturas Simplificadas REAIS** em nome da Fordaimon Foods.
//
// Por isso a faixa **não pode adivinhar**, e por isso há TRÊS estados e não
// dois. O terceiro é o que decide se ela funciona: um ecrã que, ao não
// conseguir perguntar, decide não mostrar nada cai exactamente no primeiro
// engano — e cai em silêncio.
//
// **Vive aqui, e não dentro de um componente, porque é aqui que um teste lhe
// chega e a pode EXECUTAR.** Já aconteceu duas vezes neste módulo um guarda
// verificar que certos nomes apareciam num ficheiro e ficar verde com a decisão
// desligada por trás deles. O guarda destas quatro funções corre-as mesmo, em
// Node (`backend/tests/faturacao/test_a_faixa_do_modo_no_ecra.py`).

export const MODO_TESTES = 'tests';
export const MODO_NORMAL = 'normal';
export const MODO_DESCONHECIDO = 'desconhecido';

// O valor cru do servidor, lido como um dos três estados.
//
// A comparação é EXACTA — sem `trim()`, sem `toLowerCase()`. É a mesma
// comparação que `vendus/emissao.py::_MODOS_VALIDOS` faz para decidir se emite,
// e tem de ser: com `VENDUS_MODE="TESTS"` o servidor RECUSA-SE a emitir, e uma
// cortesia aqui punha o ecrã a anunciar «modo de testes» sobre uma emissão que
// nem sequer acontece. Tudo o que não for exactamente uma das duas palavras é
// o terceiro estado, incluindo `null`, `undefined` e o campo que não veio.
export const estadoDoModo = (bruto) => {
  if (bruto === MODO_TESTES) return MODO_TESTES;
  if (bruto === MODO_NORMAL) return MODO_NORMAL;
  return MODO_DESCONHECIDO;
};

// X-Device-Token (dispositivo_atual), e deliberadamente NÃO o operador: a faixa
// tem de continuar de pé durante a troca de operador, e nesse instante o ecrã
// não tem token de operador nenhum. Ver `faturacao/modo.py`.
export const getModoDeEmissao = () => api.get('/pos/modo-de-emissao');

// **Perguntar, e nunca ficar sem resposta.** `pedir` é um parâmetro e não um
// import por uma razão só: é isso que torna esta função executável por um teste
// — o «servidor não respondeu» reproduz-se com uma função que rebenta, sem rede
// nenhuma. O backoffice passa-lhe a SUA chamada (o JWT de gestão) e recebe a
// mesma decisão, sem uma segunda cópia deste `catch`.
//
// O `catch` está aqui, e não no `useEffect` de um ecrã, porque foi essa a forma
// de falhar que isto existe para apanhar: um `await` sem rede deixa a promessa
// rejeitada, o estado do React fica no valor inicial e o ecrã não desenha nada
// — que é indistinguível de `normal` para quem está ao balcão.
export const estadoDoModoLido = async (pedir) => {
  try {
    const { data } = await pedir();
    return estadoDoModo(data?.modo);
  } catch (e) {
    return MODO_DESCONHECIDO;
  }
};

export const lerEstadoDoModo = () => estadoDoModoLido(getModoDeEmissao);

// O que a faixa diz — ou `null` quando não há faixa nenhuma.
//
// `normal` é silêncio, e é deliberado: é o estado normal de trabalho, e uma
// faixa permanente treinava a operadora a ignorá-la — e nesse dia ela ignorava
// também a de `tests`. O dono já se queixou de o ecrã ser grande de mais e
// pediu uma área de trabalho mais contida; o estado normal não paga um pixel a
// um aviso que não tem nada para avisar.
//
// Qualquer coisa que não seja um dos dois estados conhecidos — incluindo o
// `undefined` do primeiro render, antes de a resposta chegar — dá o aviso do
// terceiro estado. Na dúvida não se escolhe um dos dois lados.
export const faixaDoModo = (estado) => {
  if (estado === MODO_NORMAL) return null;
  if (estado === MODO_TESTES) {
    return {
      estado: MODO_TESTES,
      tom: 'alarme',
      titulo: 'MODO DE TESTES — estas faturas não valem nada',
      texto: 'Nada do que emitir aqui chega à Autoridade Tributária. '
        + 'Serve para treinar; não serve para vender.',
    };
  }
  return {
    estado: MODO_DESCONHECIDO,
    tom: 'perigo',
    titulo: 'NÃO SABEMOS SE ESTAS FATURAS SÃO REAIS',
    texto: 'O servidor não disse em que modo está a emitir. '
      + 'Não venda até isto estar resolvido — chame o gestor.',
  };
};

// **O carimbo daquela fatura em concreto**, e não o modo do instante em que a
// página foi carregada. O documento vem do servidor com o campo `modo`
// (`fiscal.py`), e é essa a verdade dele: um turno que começou em `tests` e a
// que o gestor mudou o servidor a meio tem documentos dos dois tipos à frente.
//
// **O terceiro estado é o que faltava aqui.** O ecrã da confirmação já avisava
// do modo `tests`, mas um documento SEM o campo `modo` (um servidor mais velho,
// uma releitura que o perdeu) não mostrava nada — e «nada» lê-se como «é real».
export const avisoDoDocumento = (documento) => {
  const estado = estadoDoModo(documento?.modo);
  if (estado === MODO_NORMAL) return null;
  if (estado === MODO_TESTES) {
    return {
      estado: MODO_TESTES,
      tom: 'alarme',
      titulo: 'Documento SEM VALOR FISCAL',
      texto: 'Saiu em modo de testes do Vendus: não foi comunicado à Autoridade '
        + 'Tributária e não serve como fatura. Avise o gestor antes de continuar a vender.',
    };
  }
  return {
    estado: MODO_DESCONHECIDO,
    tom: 'perigo',
    titulo: 'NÃO SABEMOS SE ESTA FATURA É REAL',
    texto: 'O documento saiu sem dizer em que modo. Confirme-o no Vendus antes de '
      + 'entregar o talão e avise o gestor — pode não ter valor fiscal.',
  };
};

// A MESMA pergunta, no backoffice — e a única diferença deliberada.
//
// **No POS, `normal` é silêncio; aqui, `normal` responde.** É uma saída
// consciente da regra dos três estados, e a razão é o pedido original: o dono
// perguntou «está tudo em teste né?» e teve de esperar que alguém fosse ao
// servidor. O balcão vive em `normal` o dia inteiro e uma faixa permanente
// ensinava a operadora a ignorar as outras duas; o gestor entra aqui de vez em
// quando, precisamente para CONFIRMAR, e um ecrã calado obriga-o a saber de cor
// que o silêncio quer dizer «sim». O ALARME continua a obedecer à mesma regra
// dos três estados — o que muda é que aqui o estado normal também se lê.
//
// Vive neste ficheiro, ao lado das outras duas, para haver um sítio só onde se
// vê o que cada ecrã diz em cada estado. O backoffice importa daqui só funções
// puras: a instância de axios do POS (isolada de propósito, ver o cabeçalho)
// não vai com elas, e a chamada de rede do backoffice é a dele, com o JWT de
// gestão (`lib/faturacao.js::getModoDeEmissaoDoBackoffice`).
export const avisoDoModoNoBackoffice = (estado) => {
  if (estado === MODO_NORMAL) {
    return {
      estado: MODO_NORMAL,
      tom: 'calmo',
      titulo: 'A emitir faturas reais',
      texto: 'Modo normal: as Faturas Simplificadas do POS são comunicadas à '
        + 'Autoridade Tributária.',
    };
  }
  if (estado === MODO_TESTES) {
    return {
      estado: MODO_TESTES,
      tom: 'alarme',
      titulo: 'MODO DE TESTES — as lojas não estão a facturar',
      texto: 'Nada do que sai do POS chega à Autoridade Tributária. Os documentos '
        + 'parecem faturas e não valem nada.',
    };
  }
  return {
    estado: MODO_DESCONHECIDO,
    tom: 'perigo',
    titulo: 'NÃO SABEMOS EM QUE MODO O POS ESTÁ A EMITIR',
    texto: 'O servidor não respondeu à pergunta. Confirme o VENDUS_MODE antes de '
      + 'deixar as lojas vender.',
  };
};

// --- O separador FATURAÇÃO ----------------------------------------------------
//
// A lista dos documentos já emitidos e a fatura aberta (backend:
// `faturacao/documentos.py`). Até aqui não havia rota nenhuma que lesse
// `fat_documentos`, e uma fatura emitida desaparecia do ecrã para sempre: o
// cliente que voltava com o talão rasgado não tinha por onde ser servido.

export const getDocumentosPos = () => api.get('/pos/documentos');

export const getDocumentoPos = (documentoId) =>
  api.get(`/pos/documentos/${documentoId}`);

// Abre uma conta NOVA com as mesmas linhas. O servidor recusa com 409 se este
// posto tiver conta por resolver — ver `razaoDeNaoCopiar`, que é o que faz o
// ecrã dizer isso ANTES do toque.
export const copiarDocumentoParaVenda = (documentoId, caixaId) =>
  api.post(`/pos/documentos/${documentoId}/copiar-para-venda`, { caixa_id: caixaId });

// Sem acentos e em minúsculas — ao balcão escreve-se "acai" e o produto
// chama-se "Açaí". Mesma normalização do `semAcentos` do PosVenda, aqui porque
// é aqui que um teste lhe chega e a pode EXECUTAR.
export const semAcentosPos = (texto) =>
  String(texto ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

// **A hora da fatura, como a operadora precisa de a ler.**
//
// Só a hora ("21:41") quando é de HOJE, que é o caso da esmagadora maioria; com
// a data à frente quando não é. Sem a data, o cliente que volta AMANHÃ — o caso
// que o dono nomeou — vê duas faturas das 21:41 na mesma lista e não há forma
// de saber qual é a dele.
//
// `agora` é um parâmetro e não `new Date()` lá dentro, por uma razão só: é isso
// que torna isto executável por um teste, sem depender do dia em que a suite
// corre.
export const momentoDaFaturaPos = (iso, agora) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const hoje = agora instanceof Date ? agora : new Date(agora);
  const hora = d.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit' });
  const mesmoDia = (a, b) => a.toDateString() === b.toDateString();
  if (mesmoDia(d, hoje)) return hora;
  const ontem = new Date(hoje.getTime());
  ontem.setDate(ontem.getDate() - 1);
  if (mesmoDia(d, ontem)) return `Ontem ${hora}`;
  return `${d.toLocaleDateString('pt-PT', { day: '2-digit', month: '2-digit' })} ${hora}`;
};

// O que o cliente levou, numa linha: "1× Açaí Regular · 1× Coca-Cola  +2".
//
// **É esta a coluna por que a operadora encontra a fatura.** O cliente que
// volta raramente sabe o número e muitas vezes nem o total; sabe que comprou um
// açaí. As quantidades vêm do servidor tal como estão (podem ser fraccionárias,
// numa parte de conta dividida) e são desenhadas aqui — não são dinheiro.
export const resumoDosArtigosPos = (documento) => {
  const artigos = documento?.artigos || [];
  if (artigos.length === 0) return '';
  const partes = artigos.map((a) => {
    const q = Number(a?.quantidade);
    const qtd = Number.isFinite(q) ? (Number.isInteger(q) ? q : q.toFixed(2)) : '?';
    return `${qtd}× ${a?.nome || '?'}`;
  });
  const mais = Number(documento?.mais_artigos) || 0;
  return partes.join(' · ') + (mais > 0 ? ` +${mais}` : '');
};

// A pesquisa da lista: casa com o NÚMERO, com o TOTAL e com o nome de qualquer
// artigo. As três coisas que o cliente diz ao voltar, e é por isso que são as
// três que procuram.
//
// O total compara-se pelo TEXTO do número (`11,64` e `11.64` casam os dois),
// e não por um valor: isto é uma pesquisa, não uma conta — nenhum euro é somado
// nem comparado aqui.
export const casaComAPesquisaPos = (documento, texto) => {
  const procura = semAcentosPos(texto).trim();
  if (!procura) return true;
  const total = numeroPos(documento?.total);
  const campos = [
    documento?.numero,
    documento?.atcud,
    total,
    total.replace(',', '.'),
    ...(documento?.artigos || []).map((a) => a?.nome),
    ...(documento?.pagamentos || []).map((p) => p?.nome),
  ];
  return campos.some((c) => semAcentosPos(c).includes(procura));
};

// **Porque é que «Copiar para a venda» está desligado — ou `null` quando não
// está.**
//
// Vive aqui, e não dentro do JSX, pela razão de sempre neste ficheiro: uma
// condição escrita no meio de um botão não se corre em lado nenhum, e um guarda
// que procure o TEXTO da frase fica verde com a condição desligada.
//
// **A primeira razão é a regra do dono: um PC atende UM cliente de cada vez.**
// Quem a impõe é o servidor (`venda.abrir_venda` responde 409 se este posto
// tiver conta por resolver), e isto é o ecrã a dizê-lo ANTES do toque em vez de
// depois — a operadora carregava, esperava, e levava uma recusa que já se sabia
// de antemão, com o cliente à frente.
export const razaoDeNaoCopiar = ({ contaEmCurso, documento }) => {
  if (contaEmCurso) {
    return 'Há uma conta por resolver neste posto. Atende-se um cliente de cada vez: '
      + 'acabe a que está à frente — cobre-a ou cancele-a — antes de copiar esta fatura '
      + 'para uma conta nova.';
  }
  if (documento && documento.tem_venda === false) {
    return 'Esta fatura já não tem a conta de origem guardada — não há linhas para copiar.';
  }
  if (documento && (documento.linhas || []).length === 0) {
    return 'Esta fatura não tem nenhuma linha para copiar.';
  }
  return null;
};

// --- A IMPRESSÃO -------------------------------------------------------------
//
// Os três botões que estavam "Brevemente" — «Abrir Gaveta» no menu Caixa,
// «Imprimir Pedido» no ecrã da venda e «Imprimir» dentro de uma fatura —
// passam a pôr trabalho na fila do servidor (`faturacao/impressao.py`). Quem
// imprime é o programa da loja (`agente_impressao/`), que VAI BUSCAR o
// trabalho; este ecrã nunca fala com impressora nenhuma.
//
// **E é por isso que o estado existe.** Uma loja onde ninguém instalou o
// programa não pode ter um botão que parece funcionar: o toque entrava na
// fila, caducava meia hora depois e ninguém sabia de nada — a operadora dava
// o cliente por servido e o papel nunca existiu. `GET /pos/impressao/estado`
// responde «há programa a ouvir?», e é isso que desliga os botões.

export const getEstadoImpressao = () => api.get('/pos/impressao/estado');
export const abrirGavetaPos = () => api.post('/pos/impressao/gaveta');
export const darFalhadosPorVistos = () => api.post('/pos/impressao/falhados/visto');
export const imprimirPedidoPos = (vendaId) =>
  api.post(`/pos/venda/${vendaId}/imprimir-pedido`);
export const imprimirSegundaViaPos = (documentoId) =>
  api.post(`/pos/documentos/${documentoId}/imprimir`);

export const MSG_IMPRESSAO_SEM_PROGRAMA =
  'Não há nenhum programa de impressão a responder nesta loja. Nada vai sair '
  + 'em papel até alguém o abrir no PC do balcão — ver INSTALAR-IMPRESSAO.md.';

export const MSG_IMPRESSAO_POR_SABER =
  'A perguntar se o programa de impressão desta loja está a responder…';

export const MSG_IMPRESSAO_A_ENVIAR =
  'A pôr na fila da impressora… não carregue outra vez.';

// **Porque é que um botão de imprimir está desligado — ou `null` quando não
// está.** Escrito aqui e não dentro do JSX pela razão de sempre neste
// ficheiro: uma condição no meio de um botão não se corre em lado nenhum, e um
// guarda que procure o TEXTO da frase fica verde com a condição desligada por
// trás dela.
//
// O estado `undefined`/`null` é o "ainda não sei", e desliga na mesma: entre
// abrir o ecrã e a primeira resposta há um vão de um segundo, e um botão que
// funcione nesse vão numa loja sem programa é exactamente o engano que isto
// existe para não deixar acontecer.
export const razaoDeNaoImprimir = ({ estado, aImprimir } = {}) => {
  if (aImprimir) return MSG_IMPRESSAO_A_ENVIAR;
  if (!estado) return MSG_IMPRESSAO_POR_SABER;
  if (!estado.ha_programa) return MSG_IMPRESSAO_SEM_PROGRAMA;
  return null;
};

// **O que ficou por sair, dito por extenso — ou `null` quando não há nada a
// dizer.** Uma fila que desiste em silêncio é pior do que uma fila que
// insiste: o servidor desiste de um trabalho ao fim de algumas tentativas
// (`impressao._MAX_TENTATIVAS`) e é ESTA frase que impede isso de ser um
// segredo entre o servidor e o log.
export const avisoDaFilaDeImpressao = (estado) => {
  if (!estado) return null;
  const falhados = Number(estado.falhados || 0);
  if (falhados > 0) {
    return falhados === 1
      ? 'Um papel não chegou a sair na impressora. Reimprima-o pelo separador '
        + 'Faturação depois de ver o papel e a ligação da impressora.'
      : `${falhados} papéis não chegaram a sair na impressora. Reimprima-os `
        + 'pelo separador Faturação depois de ver o papel e a ligação da '
        + 'impressora.';
  }
  const porSair = Number(estado.por_sair || 0);
  if (porSair > 0) {
    return porSair === 1
      ? 'Há um papel à espera da impressora.'
      : `Há ${porSair} papéis à espera da impressora.`;
  }
  return null;
};

// **Há papéis falhados por dar por vistos?** — a condição do botão que
// desliga o aviso, escrita aqui e não no meio do JSX pela razão de sempre
// neste ficheiro: uma condição dentro de um botão não se corre em lado
// nenhum.
//
// O aviso dos papéis que não saíram só desaparecia ao fim de SETE DIAS (o TTL
// do Mongo sobre `fat_trabalhos_impressao`) e não havia nada que o tirasse do
// ecrã. A operadora reimprimia o papel pelo separador Faturação, resolvia o
// assunto, e continuava a ver a mesma frase a semana inteira — que é a
// maneira de ensinar uma loja a não olhar para os avisos.
export const haFalhadosPorVer = (estado) => Number(estado?.falhados || 0) > 0;

// --- A NOTA DE CRÉDITO -------------------------------------------------------
//
// O ecrã que corrige uma Fatura Simplificada já entregue à AT, e devolve o
// dinheiro. As três rotas de `faturacao/nota_credito.py`, e as decisões do ecrã
// aqui em baixo — aqui, e não dentro do JSX, pela razão de sempre neste
// ficheiro: uma condição escrita no meio de um botão não se corre em lado
// nenhum, e um guarda que procure o TEXTO da frase fica verde com a condição
// desligada por trás dela.

// O que a fatura ainda deixa creditar, linha a linha.
export const getNotaCreditoPos = (documentoId) =>
  api.get(`/pos/documentos/${documentoId}/nota-credito`);

// **O dinheiro das linhas escolhidas, somado pelo SERVIDOR.** Chamada a cada
// mudança da selecção. Existe porque a alternativa era este ficheiro somar
// euros ao lado de um servidor a somar cêntimos — e o número que divergisse ia
// parar a uma nota de crédito real.
export const preVisualizarNotaCreditoPos = (documentoId, linhas) =>
  api.post(`/pos/documentos/${documentoId}/nota-credito/pre-visualizar`, { linhas });

export const emitirNotaCreditoPos = (documentoId, corpo) =>
  api.post(`/pos/documentos/${documentoId}/nota-credito`, corpo);

// **A quantidade que a operadora escreveu, presa ao que a linha ainda tem.**
//
// Devolve sempre um número — nunca `NaN`, nunca `undefined`: é ele que vai no
// pedido, e um `NaN` a caminho do servidor voltava como um 422 de validação de
// tipo em vez da frase que diz o que fazer. O tecto é o `disponivel` que o
// servidor mandou; quem RECUSA continua a ser a rota (o travão é dele), e isto
// é só o campo a não deixar escrever um número que já se sabe recusado.
export const quantidadeDaNotaPos = (escrito, disponivel) => {
  const tecto = Number.isFinite(Number(disponivel)) ? Number(disponivel) : 0;
  const texto = String(escrito ?? '').replace(',', '.').trim();
  if (texto === '') return 0;
  const n = Number(texto);
  if (!Number.isFinite(n) || n < 0) return 0;
  return n > tecto ? tecto : n;
};

// As linhas seleccionadas no formato do pedido — as marcadas, com quantidade
// positiva. Uma linha marcada com zero não vai: o servidor recusava-a com
// «a quantidade tem de ser maior do que zero» e a operadora não saberia qual.
export const linhasDaNotaPos = (linhas, escolhas) =>
  (linhas || [])
    .filter((li) => (escolhas || {})[li.indice]?.marcada)
    .map((li) => ({
      indice: li.indice,
      quantidade: quantidadeDaNotaPos(escolhas[li.indice].quantidade, li.disponivel),
    }))
    .filter((li) => li.quantidade > 0);

// **Uma linha já toda creditada NÃO se marca.** Fica na lista (some-la era pior:
// a operadora procurava o artigo que o cliente traz na mão, não o encontrava, e
// concluía que a fatura não era aquela) mas com a caixa morta e o porquê à
// vista.
export const linhaDaNotaCreditavel = (linha) => Number(linha?.disponivel || 0) > 0;

// **E o PORQUÊ da linha morta não pode mentir.** «Já creditado» e «por apurar»
// são coisas diferentes e mandam chamar pessoas diferentes: a primeira é uma
// nota que SAIU (o cliente já cá veio), a segunda é uma nota que reservou e
// ficou pendurada — pode não ter creditado nada, e quem a destranca é o
// gestor, no backoffice. O servidor manda `por_apurar` por linha; sem esta
// distinção, uma fatura travada por uma nota presa dizia à operadora que o
// artigo «já foi creditado» quando não tinha sido creditado nada.
export const MSG_LINHA_JA_CREDITADA = 'Já creditado por inteiro numa nota anterior.';
export const MSG_LINHA_POR_APURAR =
  'Preso numa nota de crédito por apurar — ninguém sabe se ela saiu. Chame o gestor.';

export const razaoDeLinhaMortaPos = (linha) => {
  if (linhaDaNotaCreditavel(linha)) return null;
  return Number(linha?.por_apurar || 0) > 0
    ? MSG_LINHA_POR_APURAR
    : MSG_LINHA_JA_CREDITADA;
};

export const MSG_NC_SEM_LINHAS =
  'Marque os artigos que vai devolver — e a quantidade de cada um.';

// O motivo não é uma formalidade nossa: a lei obriga a que uma nota de crédito
// diga o que rectifica e porquê, e a API do Vendus recusa o documento sem ele.
export const MSG_NC_SEM_MOTIVO =
  'Escreva o motivo: a lei obriga a que a nota de crédito diga porque é que '
  + 'corrige a fatura, e é isso que sai impresso.';

// **A devolução segue o meio de pagamento** — a decisão do dono. Em dinheiro sai
// da gaveta e o fecho conta-a; por Multibanco, Uber, Bolt ou Glovo fica
// registada nesse meio e a gaveta não mexe.
export const MSG_NC_SEM_DEVOLUCAO =
  'Escolha por onde é que o dinheiro volta ao cliente — é isso que decide se '
  + 'sai da gaveta ou do outro meio.';

// **Porque é que «Emitir Nota de Crédito» está desligado — ou `null` quando não
// está.** A ordem é a do dedo: primeiro o que falta escolher, depois o que falta
// escrever.
export const razaoDeNaoEmitirNotaCredito = ({ linhas, motivo, tipoPagamentoId, aEmitir }) => {
  if (aEmitir) return 'A emitir a nota de crédito… não carregue outra vez.';
  if ((linhas || []).length === 0) return MSG_NC_SEM_LINHAS;
  if (!String(motivo || '').trim()) return MSG_NC_SEM_MOTIVO;
  if (!tipoPagamentoId) return MSG_NC_SEM_DEVOLUCAO;
  return null;
};

// **O que esta fatura RECEBEU no meio escolhido, quando não chega para a
// devolução — ou `null` quando chega.**
//
// A regra do dono é «a devolução segue o meio de pagamento», e até aqui nada
// no sistema a confrontava: uma fatura de 11,29 € paga 5,00 em dinheiro +
// 6,29 em Multibanco deixava devolver os 9,85 € do açaí EM DINHEIRO, e o
// esperado da gaveta caía de 55,00 para 45,15 € — abaixo do fundo inicial,
// sem uma palavra em lado nenhum.
//
// O servidor não recusa (ver `nota_credito.pagamentos_da_fatura`: recusar por
// meio fecha a porta sem abrir outra, porque uma nota credita LINHAS e as
// mesmas linhas não se creditam duas vezes). O que ele faz é mandar os
// pagamentos da fatura, e é esta frase que os põe à frente da operadora ANTES
// do toque — em euros, com o número que vai faltar à gaveta.
//
// **O emparelhamento é o do servidor** (`nota_credito._e_o_mesmo_meio`), e é a
// segunda metade dele que faltava aqui: uma linha COM id casa pelo id; uma
// linha SEM id casa pelo NOME, aparado e sem distinguir maiúsculas. Medido —
// fatura paga `{nome: Dinheiro, tipo_fiscal: NU, valor: 20,40}` **sem
// `tipo_pagamento_id`** (gravada por uma versão anterior, ou trazida do Vendus
// por uma reconciliação): devolver 10,20 € em dinheiro pintava esta caixa a
// VERMELHO antes de a operadora tocar em nada, com «só tem € 0,00 por devolver
// em Dinheiro» sobre uma fatura que recebeu 20,40 € em dinheiro.
export const avisoDoMeioDeDevolucaoPos = ({ tipo, pagamentos, total }) => {
  if (!tipo) return null;
  const mesmoNome = (a, b) => {
    const x = String(a || '').trim().toLowerCase();
    return x !== '' && x === String(b || '').trim().toLowerCase();
  };
  const casa = (p) => (p?.tipo_pagamento_id
    ? p.tipo_pagamento_id === tipo.id
    : mesmoNome(p?.nome, tipo.nome));
  // SOMA as linhas que casam, como o servidor: parar na primeira deixava
  // metade do dinheiro de fora quando a reconciliação traz o mesmo meio em
  // duas linhas.
  const centimos = (v) => Math.round(Number(v || 0) * 100);
  const disponivel = (pagamentos || []).filter(casa)
    .reduce((soma, p) => soma + centimos(p?.disponivel), 0) / 100;
  const excesso = centimos(total) - centimos(disponivel);
  if (excesso <= 0) return null;
  const meio = tipo.nome || 'este meio';
  return `Esta fatura só tem ${eurosPos(disponivel)} por devolver em ${meio} `
    + `e vai devolver ${eurosPos(total)}: saem ${eurosPos(excesso / 100)} `
    + `${tipo.tipo_fiscal === 'NU' ? 'da gaveta' : `de ${meio}`} que esta `
    + 'venda não pôs lá.';
};

// A frase por baixo do meio de devolução escolhido, e é o que a operadora
// precisa de ler ANTES de emitir: o que vai acontecer à gaveta dela. O
// `tipo_fiscal` vem do servidor com o tipo de pagamento — 'NU' é numerário.
export const efeitoNaGavetaPos = (tipo) => {
  if (!tipo) return null;
  return tipo.tipo_fiscal === 'NU'
    ? 'Sai da gaveta — entregue o dinheiro ao cliente. O fecho desta caixa já '
      + 'conta com esta devolução.'
    : `Fica registada em ${tipo.nome || 'este meio'} — não tire dinheiro da gaveta.`;
};
