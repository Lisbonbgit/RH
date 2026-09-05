// Wrappers do módulo Faturação. O token continua a viver em
// axios.defaults.headers.common, posto pelo AuthContext — como em lib/api.js e
// lib/finance.js —, mas as chamadas daqui saem por um cliente próprio, que lho
// vai buscar a cada pedido e lhes põe um tecto de espera (ver mais abaixo).
import axios from 'axios';
import { urlDaFoto } from './fotos';

const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

// --- Tectos de espera --------------------------------------------------------
//
// **Sem `timeout`, o axios espera PARA SEMPRE**, e não há
// `axios.defaults.timeout` em lado nenhum deste repositório — só o `lib/pos.js`
// tinha tectos. Um pedido pendurado (o Wi-Fi a piscar, o servidor a não fechar
// a ligação) deixa o ecrã que o fez no ESTADO INICIAL, sem erro, sem spinner
// que acabe e sem nada que diga a quem está a olhar que está a ler uma
// resposta que nunca chegou.
//
// O ecrã onde isso custa mais é o `FatModoDeEmissao`: ele responde à pergunta
// que o dono fez — «está tudo em teste né? posso fazer faturas aqui normal.» —
// e um pedido pendurado deixava-o a dizer «não sabemos» para sempre. Com um
// estado inicial menos cuidadoso, dizia «A emitir faturas reais» para sempre,
// que é a mentira permanente.
//
// Está no CLIENTE e não repetido em cada função, exactamente pela razão do
// `baseURL` do `lib/pos.js`: para não haver forma de acrescentar amanhã uma
// chamada nova e voltar a esquecê-lo. São 51 exportações neste ficheiro.
//
// 30 s (padrão) — tudo o que só fala com o Mongo. São pedidos de dezenas de
// milissegundos; 30 s é folga de sobra para um pico de rede ou um arranque
// frio, e curto o bastante para o gestor perceber que alguma coisa se passou.
//
// 120 s (o que espera pelo VENDUS) — três chamadas, e nelas a demora é
// legítima e não avaria: `metodos-vendus` e `importacao/vendus` fazem leituras
// PAGINADAS à API do Vendus (`vendus/cliente.py::_paginar`, 100 por página,
// 20 s de httpx por página), e `reservas/{id}/reconciliar` vai perguntar ao
// Vendus se a Fatura Simplificada saiu. Erra-se por excesso de propósito:
// desistir a meio de uma importação não a cancela do outro lado, só tira o
// ecrã de cima dela.
export const TIMEOUT_BACKOFFICE_MS = 30000;
export const TIMEOUT_COM_VENDUS_MS = 120000;

const api = axios.create({ timeout: TIMEOUT_BACKOFFICE_MS });

// **O JWT lido A CADA PEDIDO, e não copiado na criação.** `axios.create()`
// copia os `defaults` no instante em que corre — e este módulo é importado
// muito antes do login — e nunca mais volta a olhar para eles. Uma instância
// que nascesse antes do `AuthContext` pôr o `Authorization` ficava sem ele
// para sempre, e o backoffice inteiro respondia 401. É por isso que aqui se
// vai buscar o cabeçalho do axios global no momento do pedido, que é onde o
// `AuthContext` o põe (e de onde o `logout` o tira).
api.interceptors.request.use((config) => {
  const autorizacao = axios.defaults.headers.common.Authorization;
  config.headers = config.headers || {};
  if (autorizacao) config.headers.Authorization = autorizacao;
  return config;
});

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
  api.get(`${API_URL}/faturacao/modo-de-emissao`);
// Vira o interruptor. Diz sempre PARA ONDE — nunca «alterna»: um pedido
// repetido pela rede, ou um duplo toque, passava a real e voltava a testes
// sem ninguém dar por isso, e as faturas do meio eram reais para sempre.
export const mudarModoDeEmissao = (modo) =>
  api.put(`${API_URL}/faturacao/modo-de-emissao`, { modo });

export const getFatDashboard = (comIva = true) =>
  api.get(`${API_URL}/faturacao/dashboard`, { params: { com_iva: comIva } });

// Lojas
export const getLojas = () => api.get(`${API_URL}/faturacao/lojas`);
export const criarLoja = (data) => api.post(`${API_URL}/faturacao/lojas`, data);
export const editarLoja = (id, data) => api.put(`${API_URL}/faturacao/lojas/${id}`, data);
export const apagarLoja = (id) => api.delete(`${API_URL}/faturacao/lojas/${id}`);

// As vendas da APP L'Açaí.
//
// A app emite as Faturas Simplificadas dela pela MESMA caixa API e pela MESMA
// série das cinco lojas; o portal vai buscá-las ao Vendus e grava-as na loja
// que o gestor escolher aqui — `{ loja_id, ativo }` em `fat_definicoes`. Sem
// loja escolhida a sincronização não corre de todo, e diz porquê: adivinhá-la
// era pôr a receita da app na loja errada (faturacao/sincronizacao_rota.py).
export const getSincronizacaoApp = () =>
  api.get(`${API_URL}/faturacao/sincronizacao-app/definicoes`);
export const guardarSincronizacaoApp = (dados) =>
  api.put(`${API_URL}/faturacao/sincronizacao-app/definicoes`, dados);
// Vai ao VENDUS ler dois dias inteiros, documento a documento — tecto de 120 s,
// como as outras chamadas deste ficheiro que lá falam. Corre sozinha de 5 em 5
// minutos pelo cron; este botão é para quando alguém não quer esperar.
export const sincronizarAppAgora = () =>
  api.post(`${API_URL}/faturacao/sincronizacao-app/sincronizar-agora`, undefined,
    { timeout: TIMEOUT_COM_VENDUS_MS });

// **O que a volta da sincronização diz a quem carregou no botão.**
//
// Vive aqui e não dentro do ecrã por causa dos `assinalados`: são os documentos
// que ficaram de fora POR AVARIA (sem ATCUD, total ilegível, desapareceram do
// Vendus) e que **não voltam a ser tentados** — a janela do cron só olha para
// hoje e ontem. Até hoje esse campo não tinha consumidor nenhum: existia no log
// da API, onde ninguém olha. Quem pode agir é quem está à frente do ecrã, e por
// isso eles aparecem mesmo quando o resto da volta correu bem.
export const resumoDaSincronizacao = (resultado) => {
  const r = resultado || {};
  const gravados = r.gravados || 0;
  const assinalados = r.assinalados || [];
  const erros = r.erros || [];
  // **Os assinalados JÁ ESTÃO dentro dos ignorados.** No servidor, `_saltar`
  // chama `_contar` (`sincronizacao_rota.py`), por isso «8 ignoradas» seguido
  // de «2 documentos ficaram de fora» são 8 documentos e não 10 — mas quem lê
  // soma, e fica à procura de dois documentos que não existem. O parêntesis
  // diz de que número é que os 2 saíram.
  const deFora = assinalados.length > 0
    ? ` (${assinalados.length} ${assinalados.length === 1
      ? 'dela ficou de fora e não volta' : 'delas ficaram de fora e não voltam'})`
    : '';
  const partes = [
    `${gravados} ${gravados === 1 ? 'nova' : 'novas'} · ${r.repetidos || 0} `
    + `${r.repetidos === 1 ? 'repetida' : 'repetidas'} · ${r.ignorados || 0} `
    + `${r.ignorados === 1 ? 'ignorada' : 'ignoradas'}${deFora}`,
  ];
  if (assinalados.length > 0) {
    partes.push(
      'São estas:\n'
      + assinalados.join('\n'),
    );
  }
  if (erros.length > 0) partes.push(erros.join('\n'));
  return {
    // A avaria manda no tom: uma volta que parou a meio com 3 faturas gravadas
    // não é um sucesso com um aviso, é uma volta por acabar.
    tipo: erros.length > 0 ? 'error' : assinalados.length > 0 ? 'warning' : 'success',
    titulo: erros.length > 0
      ? 'A sincronização não chegou ao fim'
      : assinalados.length > 0
        ? `${assinalados.length} ${assinalados.length === 1
          ? 'documento ficou de fora' : 'documentos ficaram de fora'}`
        : gravados > 0
          ? `${gravados} ${gravados === 1
            ? 'fatura nova da app' : 'faturas novas da app'}`
          : 'Sem faturas novas da app',
    descricao: partes.join('\n\n'),
  };
};

// Caixas (de uma loja)
export const getCaixas = (lojaId) => api.get(`${API_URL}/faturacao/lojas/${lojaId}/caixas`);
export const criarCaixa = (lojaId, data) => api.post(`${API_URL}/faturacao/lojas/${lojaId}/caixas`, data);
export const editarCaixa = (id, data) => api.put(`${API_URL}/faturacao/caixas/${id}`, data);
export const apagarCaixa = (id) => api.delete(`${API_URL}/faturacao/caixas/${id}`);

// Tipos de Pagamento
export const getTiposPagamento = () => api.get(`${API_URL}/faturacao/tipos-pagamento`);
export const getCodigosFiscais = () => api.get(`${API_URL}/faturacao/tipos-pagamento/codigos-fiscais`);
export const criarTipoPagamento = (data) => api.post(`${API_URL}/faturacao/tipos-pagamento`, data);
export const editarTipoPagamento = (id, data) => api.put(`${API_URL}/faturacao/tipos-pagamento/${id}`, data);
export const apagarTipoPagamento = (id) => api.delete(`${API_URL}/faturacao/tipos-pagamento/${id}`);

// Os métodos de pagamento da conta Vendus, lidos ao vivo (nunca escrevemos
// lá — ver o cabeçalho de faturacao/pagamentos.py). É desta lista que sai o
// `vendus_payment_method_id` de cada tipo, e é por isso que ela existe: sem
// esse id, `fiscal.py::finalizar` recusa a emissão com 422 no momento exacto
// em que a operadora carrega em EMITIR, com o cliente à frente.
//
// Vai numa chamada à parte do resto do ecrã de propósito: é rede, para uma
// conta que pode nem estar configurada, e o ecrã tem de continuar a gravar os
// outros campos quando ela falha.
export const getMetodosVendus = () =>
  api.get(`${API_URL}/faturacao/tipos-pagamento/metodos-vendus`,
    { timeout: TIMEOUT_COM_VENDUS_MS });

// Utilizadores
export const getUtilizadores = () => api.get(`${API_URL}/faturacao/utilizadores`);
export const criarUtilizador = (data) => api.post(`${API_URL}/faturacao/utilizadores`, data);
export const editarUtilizador = (id, data) => api.put(`${API_URL}/faturacao/utilizadores/${id}`, data);
export const mudarPin = (id, pin) => api.put(`${API_URL}/faturacao/utilizadores/${id}/pin`, { pin });
export const mudarEstado = (id, ativo) => api.put(`${API_URL}/faturacao/utilizadores/${id}/estado`, { ativo });

// Dispositivos POS (emparelhamento de PCs de loja)
export const getDispositivosPos = () => api.get(`${API_URL}/faturacao/dispositivos-pos`);
export const gerarCodigoDispositivo = (data) => api.post(`${API_URL}/faturacao/dispositivos-pos`, data);
export const revogarDispositivo = (id) => api.delete(`${API_URL}/faturacao/dispositivos-pos/${id}`);

// Motivos de Nota de Crédito
export const getMotivos = () => api.get(`${API_URL}/faturacao/motivos-nc`);
export const criarMotivo = (data) => api.post(`${API_URL}/faturacao/motivos-nc`, data);
export const editarMotivo = (id, data) => api.put(`${API_URL}/faturacao/motivos-nc/${id}`, data);
export const predefinirMotivo = (id) => api.put(`${API_URL}/faturacao/motivos-nc/${id}/predefinir`);
export const apagarMotivo = (id) => api.delete(`${API_URL}/faturacao/motivos-nc/${id}`);

// Categorias
export const getCategorias = () => api.get(`${API_URL}/faturacao/categorias`);
export const criarCategoria = (data) => api.post(`${API_URL}/faturacao/categorias`, data);
export const editarCategoria = (id, data) => api.put(`${API_URL}/faturacao/categorias/${id}`, data);
export const apagarCategoria = (id) => api.delete(`${API_URL}/faturacao/categorias/${id}`);

// Relatórios — as nove vistas da mesma tabela. A dimensão viaja no caminho
// (`/relatorios/produto`), os filtros em `params`.
export const getRelatorio = (dimensao, params) => api.get(
  `${API_URL}/faturacao/relatorios/${dimensao}`, { params });

// Clientes — quem já pediu fatura com NIF. A lista deriva das COMPRAS (não há
// "criar cliente"); o que se grava por NIF é só o nome e o contacto.
export const getClientes = (q) => api.get(
  `${API_URL}/faturacao/clientes`, q ? { params: { q } } : undefined);
export const getCliente = (nif) => api.get(`${API_URL}/faturacao/clientes/${nif}`);
export const gravarCliente = (nif, data) => api.put(
  `${API_URL}/faturacao/clientes/${nif}`, data);

// Documentos — as faturas e notas de crédito emitidas, de TODAS as lojas. São
// rotas próprias do backoffice: as do POS (`/pos/documentos`) respondem à
// pergunta do balcão (a loja do token, sem filtros) e recusam o JWT do portal.
export const getDocumentos = (params) => api.get(
  `${API_URL}/faturacao/documentos`, { params });
export const getDocumento = (id) => api.get(`${API_URL}/faturacao/documentos/${id}`);
// A segunda via sai na loja onde a fatura foi emitida (o gestor pode estar em
// casa; a impressora que interessa é a do balcão que atendeu o cliente).
// O PDF CERTIFICADO, ido buscar ao Vendus pelo servidor (a chave da API nunca
// chega ao browser). Vem como blob porque o JWT viaja no cabeçalho — um
// `<a href>` simples não ia autenticado e trazia um 403 com nome de fatura.
export const getDocumentoPdf = (id) => api.get(
  `${API_URL}/faturacao/documentos/${id}/pdf`, { responseType: 'blob' });

export const reimprimirDocumento = (id) => api.post(
  `${API_URL}/faturacao/documentos/${id}/reimprimir`);

// Subcategorias — as gavetas dentro de cada categoria (Venda ao Público →
// Açaís, Salgados). São só nossas: o Vendus não as tem e a importação não lhes
// toca. Servem para arrumar a grelha do POS.
// O `categoria_id` vai em `params` e não colado ao caminho de propósito: o
// guarda que confronta as chamadas com as rotas do servidor
// (test_caminhos_do_pos.py) lê o caminho do template literal, e uma query
// construída com um `?:` lá dentro lia-se como parte do endereço — apanhou
// exactamente isto.
export const getSubcategorias = (categoriaId) => api.get(
  `${API_URL}/faturacao/subcategorias`,
  categoriaId ? { params: { categoria_id: categoriaId } } : undefined);
export const criarSubcategoria = (data) => api.post(`${API_URL}/faturacao/subcategorias`, data);
export const editarSubcategoria = (id, data) => api.put(`${API_URL}/faturacao/subcategorias/${id}`, data);
export const apagarSubcategoria = (id) => api.delete(`${API_URL}/faturacao/subcategorias/${id}`);

// Grupos de personalização (toppings)
export const getGrupos = () => api.get(`${API_URL}/faturacao/grupos-personalizacao`);
export const criarGrupo = (data) => api.post(`${API_URL}/faturacao/grupos-personalizacao`, data);
export const editarGrupo = (id, data) => api.put(`${API_URL}/faturacao/grupos-personalizacao/${id}`, data);
export const apagarGrupo = (id) => api.delete(`${API_URL}/faturacao/grupos-personalizacao/${id}`);

// Produtos
export const getProdutos = (params) => api.get(`${API_URL}/faturacao/produtos`, { params });
export const getProdutosSemIva = () => api.get(`${API_URL}/faturacao/produtos/sem-iva`);
// Os que a emissão não consegue ligar a um artigo do Vendus — a lista vem do
// servidor porque a regra é a da fatura (precos.id_vendus_do_produto), e não
// um "tem vendus_ref?" escrito no browser: um `VACA123` escrito à mão é
// verdadeiro para o browser e inútil para a emissão.
export const getProdutosSemVendus = () => api.get(`${API_URL}/faturacao/produtos/sem-vendus`);
// O catálogo da conta Vendus, para a ficha do produto poder ESCOLHER a que
// artigo se liga — em vez de esperar que a importação lhe acerte no nome.
export const getArtigosVendus = () => api.get(`${API_URL}/faturacao/vendus/artigos`);

// --- Movimentos de caixa (histórico dos turnos) ---
export const getHistoricoDeCaixa = (params) =>
  api.get(`${API_URL}/faturacao/caixa/historico`, { params });
export const getTurno = (id) =>
  api.get(`${API_URL}/faturacao/caixa/historico/${id}`);

// --- Relatório diário por email ---
export const getDefinicoesRelatorio = () =>
  api.get(`${API_URL}/faturacao/relatorio-diario/definicoes`);
export const gravarDefinicoesRelatorio = (dados) =>
  api.put(`${API_URL}/faturacao/relatorio-diario/definicoes`, dados);
// Sem `para`, vai para a lista configurada — que é o que o botão do ecrã faz.
export const enviarRelatorioAgora = (para) =>
  api.post(`${API_URL}/faturacao/relatorio-diario/enviar-agora`, para ? { para } : {});
export const criarProduto = (data) => api.post(`${API_URL}/faturacao/produtos`, data);
export const editarProduto = (id, data) => api.put(`${API_URL}/faturacao/produtos/${id}`, data);
export const apagarProduto = (id) => api.delete(`${API_URL}/faturacao/produtos/${id}`);
export const mudarEstadoProduto = (id, ativo) => api.put(`${API_URL}/faturacao/produtos/${id}/estado`, { ativo });

// A FOTO de um produto carregada do computador do dono. Sai por `multipart`
// (é um ficheiro), e por isso não leva o `Content-Type: application/json` que
// o axios poria sozinho — deixa-se o browser escolher a fronteira do
// `FormData`, que é a única forma de o servidor conseguir separar as partes.
//
// A imagem já vai REDUZIDA pelo ecrã (`lib/fotos.js::reduzirImagem`, 640 px no
// lado maior): a grelha do POS carrega dezenas destas de uma vez num PC de
// loja. Quem RECUSA o que for grande de mais é o servidor (`fotos.py`, tecto
// de 512 KB) — este lado é a comodidade, não a garantia.
export const carregarFotoProduto = (ficheiro) => {
  const corpo = new FormData();
  corpo.append('ficheiro', ficheiro, ficheiro.name || 'foto');
  return api.post(`${API_URL}/faturacao/produtos/fotos`, corpo);
};

// O endereço a pôr num `<img>` — ver `lib/fotos.js`. A mesma regra que o POS
// usa, e não uma cópia dela.
export const urlDaFotoProduto = (valor) =>
  urlDaFoto(valor, process.env.REACT_APP_BACKEND_URL);

// Importação do catálogo Vendus
export const importarVendus = () =>
  api.post(`${API_URL}/faturacao/importacao/vendus`, undefined,
    { timeout: TIMEOUT_COM_VENDUS_MS });

// Reservas fiscais presas — a gestão de uma emissão que ficou a meio
// (backend/faturacao/fiscal.py). Estas três são de GESTOR (token do
// backoffice), nunca do balcão: o POS não tem, nem pode ter, forma de
// libertar a sua própria reserva.
export const getReservasPresas = () => api.get(`${API_URL}/faturacao/fiscal/reservas-presas`);

// Pergunta ao Vendus se a Fatura Simplificada desta venda saiu e, se saiu,
// grava-a. Não emite nada — por isso é que o pedido não tem (nem pode ter)
// campo nenhum para o número ou o ATCUD: esses vêm do Vendus ou não vêm de
// lado nenhum (ver PedidoReconciliarReserva). `nota` é só para o registo.
export const reconciliarReserva = (vendaId, nota) =>
  api.post(
    `${API_URL}/faturacao/fiscal/reservas/${vendaId}/reconciliar`,
    { nota: nota || null },
    { timeout: TIMEOUT_COM_VENDUS_MS },
  );

// Apaga a reserva e destranca a conta. `confirmadoNoVendus` é a declaração do
// gestor de que abriu o Vendus e viu que NÃO existe lá documento desta venda:
// sem ela o servidor recusa com um 422, e é de propósito que ela viaja como
// argumento obrigatório desta função em vez de um `true` fixo aqui dentro —
// libertar a reserva de uma fatura que saiu autoriza uma SEGUNDA Fatura
// Simplificada da mesma venda, entregue à AT.
export const libertarReserva = (vendaId, confirmadoNoVendus, nota) =>
  api.post(`${API_URL}/faturacao/fiscal/reservas/${vendaId}/libertar`, {
    confirmado_no_vendus: confirmadoNoVendus,
    nota: nota || null,
  });

// --- Notas de crédito PRESAS -------------------------------------------------
//
// O gémeo das reservas fiscais presas, para o OUTRO documento: uma intenção de
// nota de crédito que reservou e ficou `reservada` porque a rota morreu entre
// o `insert_one` e o `$set` final (um reinício, um deploy a meio, o 409 da
// corrida do crédito). Enquanto lá estiver, `caixa._nota_de_credito_em_curso`
// recusa o fecho daquela caixa — com a frase «espere alguns segundos», que
// para uma nota presa nunca chega a ser verdade.
//
// **As três rotas existiam desde o primeiro dia e NÃO tinham cliente nenhum
// em todo o repositório.** A mensagem do fecho mandava o gestor à «lista de
// notas de crédito presas do backoffice» — e essa lista não existia. Com UM
// PC por loja, a única saída era um POST à mão com um JWT.
//
// De GESTOR, nunca do balcão (`gestor_atual`, o token do backoffice — não o
// PIN da operadora): resolver isto é ir ao Vendus ver se o documento saiu.
export const getNotasCreditoPresas = () =>
  api.get(`${API_URL}/faturacao/fiscal/notas-credito-presas`);

// A saída SEGURA: marca a nota `incerta`. Ela continua a travar novo crédito
// das mesmas linhas (não se credita por cima do que talvez já tenha saído),
// continua a NÃO descontar a gaveta (não se devolve dinheiro que talvez não
// tenha saído), e deixa de travar o fecho. Não pede confirmação nenhuma, e é
// de propósito: esta direcção não pode fazer estrago.
export const marcarNotaCreditoPorApurar = (intencaoId, nota) =>
  api.post(`${API_URL}/faturacao/fiscal/notas-credito/${intencaoId}/por-apurar`, {
    nota: nota || null,
  });

// Apaga a intenção. `confirmadoNoVendus` é a declaração do gestor de que abriu
// o Vendus e viu que NÃO existe lá nota de crédito nenhuma com aquela
// referência: sem ela o servidor recusa com 422, e é de propósito que ela
// viaja como argumento obrigatório desta função em vez de um `true` fixo aqui
// dentro — libertar uma nota que SAIU é autorizar uma segunda nota de crédito
// real da mesma devolução, dois documentos entregues à AT a devolver o mesmo
// dinheiro.
export const libertarNotaCreditoPresa = (intencaoId, confirmadoNoVendus, nota) =>
  api.post(`${API_URL}/faturacao/fiscal/notas-credito/${intencaoId}/libertar`, {
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
export const getContasEsquecidas = () => api.get(`${API_URL}/faturacao/caixa/contas-esquecidas`);

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
  api.post(`${API_URL}/faturacao/caixa/contas-esquecidas/${vendaId}/arrumar`);

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
