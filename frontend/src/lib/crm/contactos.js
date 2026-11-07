// Os contactos de uma loja, na ficha (desenho de 2026-11-07, §3), sem DOM. Molde do `criarAdicionarARota`: uma
// `vista` congelada a cada mudança, entregue ao `aoMudarVista`; o `components/crm/ContactosLoja.js` só a desenha.
// Fica separado do `criarFicha`: o Guardar e o Recarregar da ficha não lhe tocam, e uma falha daqui fica nesta
// secção.
//
//  - `iniciar()` pede a lista. As quatro rotas devolvem `{hoje, contactos}`, do mais recente para o mais antigo, e
//    cada resposta substitui a lista inteira: um contacto com data antiga renumera os outros, e a numeração é só do
//    servidor. Se a lista não carregar, a secção mostra o erro e "Tentar novamente"; a rede que volta pede-a outra vez.
//  - "Adicionar contacto" só fica ativo com um `hoje` do servidor (a regra do `datas.js`: o relógio do browser nunca
//    decide o dia). Abre um bloco com a data de hoje, o tipo (Visita) e o resumo. "Corrigir" abre o mesmo bloco com o
//    contacto. Só há um bloco de cada vez: com um aberto, "Adicionar contacto", os "Corrigir" e os "Apagar" ficam
//    desativados.
//  - **Ao abrir o bloco** pede-se outra vez a lista, porque a ficha pode estar aberta desde a véspera. O bloco abre
//    logo com o último `hoje` e Guardar fica desativado até à resposta, que atualiza o máximo e, se a pessoa ainda não
//    mexeu na data, a data. Se o pedido falhar, fica o último `hoje` e Guardar volta a ativo. Uma lista pedida antes
//    de uma escrita ou de outra leitura já não conta: a resposta dela ignora-se.
//  - A data pode ser passada e nunca futura. Com o resumo vazio ou uma data fora, Guardar fica desativado e o `falta`
//    diz porquê. Sem rede, "Guardar — sem rede", como na ficha.
//  - **Nada do que se escreveu se perde num erro:** se a gravação falhar, o bloco fica aberto com o texto e a mensagem
//    (o 422 junto ao campo, com o foco lá). O `client_uuid` é um por bloco e só se repete no reenvio exato: com outro
//    tipo, outra data ou outro resumo, vai um novo (`clientUuidDoEnvio`), porque o servidor responde a um repetido com
//    a linha já gravada e o que se mudou perdia-se. No pior caso ficam dois contactos, e quem escreveu apaga um.
//  - "Corrigir" envia só o que mudou; sem nada mudado, Guardar fica desativado.
//  - Apagar pergunta "Apagar este contacto?", com a primeira escolha a que não apaga.
//  - **Foco** (`aoFocar`): ao abrir o bloco, o resumo; ao cancelar ou guardar, o botão que o abriu, ou "Adicionar
//    contacto" se ele já não existir; depois de apagar, "Adicionar contacto". Numa falha, volta ao botão que ficou
//    desativado durante o pedido.
//  - Sucesso: "Contacto guardado" ou "Contacto apagado" (`aoAvisar`, um toast).
//
// Os dados ficam como texto: o React escreve-os como texto.
import { MENSAGEM_ERRO_INESPERADO } from './api';
import { eDataValida, rotuloDataCurta } from './datas';
import { textoDoErro } from './ecraMapa';
import { TEXTO_A_GUARDAR, TEXTO_GUARDAR, TEXTO_GUARDAR_SEM_REDE } from './lojaNova';

// Igual a TIPOS_CONTACTO em backend/crm/dominio/contactos.py (test_consistencia_frontend.py): manter numa só linha.
export const TIPOS_CONTACTO = Object.freeze(['visita', 'chamada', 'mensagem']);

export const TIPO_POR_OMISSAO = 'visita';
// A data mais antiga que o servidor aceita (`dominio.contactos.DATA_MINIMA`; o teste lê-a).
export const DATA_MINIMA = '2000-01-01';
// O tamanho do resumo no servidor (`dominio.contactos.RESUMO_MAXIMO`; o teste lê-o).
export const RESUMO_MAXIMO = 5000;

export const TITULO_CONTACTOS = 'Contactos';
export const TEXTO_A_CARREGAR_CONTACTOS = 'A carregar os contactos…';
export const TEXTO_ADICIONAR_CONTACTO = 'Adicionar contacto';
export const TEXTO_SEM_CONTACTOS = 'Ainda sem contactos. Adicione o primeiro.';
export const TEXTO_TENTAR_DE_NOVO = 'Tentar novamente';
export const TEXTO_NOVO_CONTACTO = 'Novo contacto';
export const TEXTO_CORRIGIR_CONTACTO = 'Corrigir contacto';
export const TEXTO_CORRIGIR = 'Corrigir';
export const TEXTO_APAGAR = 'Apagar';
export const TEXTO_CORRIGIDO = 'corrigido';
export const TEXTO_CANCELAR = 'Cancelar';
export const ROTULO_DATA = 'Data';
export const ROTULO_TIPO = 'Tipo';
export const ROTULO_RESUMO = 'Resumo';
export const TEXTO_EXEMPLO_RESUMO = 'O que foi falado e o próximo passo.';
export const TEXTO_CONTACTO_GUARDADO = 'Contacto guardado';
export const TEXTO_CONTACTO_APAGADO = 'Contacto apagado';

// Os motivos do Guardar desativado (o `falta`), pela ordem em que contam.
export const TEXTO_FALTA_RESUMO = 'Para guardar, escreva o resumo.';
export const TEXTO_FALTA_DATA = 'Para guardar, escolha um dia entre 1 de janeiro de 2000 e hoje.';
export const TEXTO_FALTA_ALTERACOES = 'Sem alterações por guardar.';

export const RESPOSTA_APAGAR = 'apagar';
// A pergunta do Apagar: a primeira escolha é a que não apaga (o foco vai para ela).
export const PERGUNTA_APAGAR = Object.freeze({
  pergunta: 'Apagar este contacto?',
  botoes: Object.freeze([
    Object.freeze({ texto: 'Cancelar', valor: null, variante: 'normal' }),
    Object.freeze({ texto: 'Sim, apagar', valor: RESPOSTA_APAGAR, variante: 'perigo' }),
  ]),
});

// Para onde pode ir o foco (`aoFocar`), além dos campos do bloco.
export const ALVO_ADICIONAR = 'adicionar';
export const ALVO_GUARDAR = 'guardar';
export const alvoCorrigir = (id) => `corrigir:${id}`;
export const alvoApagar = (id) => `apagar:${id}`;

const ROTULOS_TIPO = Object.freeze({ visita: 'Visita', chamada: 'Chamada', mensagem: 'Mensagem' });
export const OPCOES_TIPO = Object.freeze(
  TIPOS_CONTACTO.map((valor) => Object.freeze({ valor, rotulo: ROTULOS_TIPO[valor] })),
);

// Os campos do bloco, pela ordem no ecrã: é o primeiro com erro que recebe o foco.
const CAMPOS_BLOCO = Object.freeze(['data', 'tipo', 'resumo']);

const eObjeto = (valor) => valor !== null && typeof valor === 'object' && !Array.isArray(valor);
const textoComConteudo = (valor) => typeof valor === 'string' && valor !== '';
const contactoValido = (contacto) => eObjeto(contacto) && textoComConteudo(contacto.id)
  && Number.isInteger(contacto.numero);

// --- Funções puras -------------------------------------------------------------------------------

export const rotuloTipo = (tipo) => ROTULOS_TIPO[tipo] ?? String(tipo ?? '');

// "3.º contacto".
export const rotuloNumero = (numero) => `${numero}.º contacto`;

// O que uma linha da lista mostra.
export function linhaDoContacto(contacto) {
  return {
    id: contacto.id,
    titulo: rotuloNumero(contacto.numero),
    data: rotuloDataCurta(contacto.data) ?? String(contacto.data ?? ''),
    tipo: rotuloTipo(contacto.tipo),
    resumo: typeof contacto.resumo === 'string' ? contacto.resumo : '',
    autor: typeof contacto.autor === 'string' ? contacto.autor : '',
    corrigido: contacto.corrigido === true,
    podeAlterar: contacto.pode_alterar === true,
  };
}

// A data que o servidor aceita: um dia que exista, de 2000-01-01 ao `hoje` (os `AAAA-MM-DD` ordenam como texto).
export const dataAceite = (data, hoje) => eDataValida(data) && eDataValida(hoje) && data >= DATA_MINIMA && data <= hoje;

// O bloco de um contacto novo, com o último `hoje` conhecido e um `client_uuid` só dele. `aAtualizar`: a lista pedida
// ao abrir ainda não voltou.
export function blocoNovo({ hoje, clientUuid }) {
  return {
    modo: 'novo',
    origem: ALVO_ADICIONAR,
    contactoId: null,
    original: null,
    data: hoje,
    dataMexida: false,
    tipo: TIPO_POR_OMISSAO,
    resumo: '',
    clientUuid,
    ultimoEnvio: null,
    aAtualizar: true,
    aGuardar: false,
    erros: {},
    alerta: null,
  };
}

// O bloco de "Corrigir", com o que o contacto tem. `original` é com o que se compara, para enviar só o que mudou.
export function blocoDeCorrecao(contacto) {
  const { data, tipo, resumo } = contacto;
  return {
    modo: 'corrigir',
    origem: alvoCorrigir(contacto.id),
    contactoId: contacto.id,
    original: { data, tipo, resumo },
    data,
    dataMexida: false,
    tipo,
    resumo,
    clientUuid: null,
    ultimoEnvio: null,
    aAtualizar: true,
    aGuardar: false,
    erros: {},
    alerta: null,
  };
}

// O bloco com outro valor num campo, sem o erro desse campo nem a mensagem da última falha. O mesmo bloco, se o
// valor não servir (um tipo fora da lista, o que não é texto) ou não mudar.
export function mudarBloco(bloco, campo, valor) {
  if (!CAMPOS_BLOCO.includes(campo) || typeof valor !== 'string' || valor === bloco[campo]) return bloco;
  if (campo === 'tipo' && !TIPOS_CONTACTO.includes(valor)) return bloco;
  const erros = { ...bloco.erros };
  delete erros[campo];
  return {
    ...bloco, [campo]: valor, dataMexida: bloco.dataMexida || campo === 'data', erros, alerta: null,
  };
}

// A resposta à lista pedida ao abrir: o bloco deixa de esperar e, num contacto novo com a data por mexer, fica com o
// `hoje` novo. A data de um contacto a corrigir é a dele.
export function blocoAtualizado(bloco, hoje) {
  const atualizado = { ...bloco, aAtualizar: false };
  if (bloco.modo === 'novo' && !bloco.dataMexida && eDataValida(hoje)) atualizado.data = hoje;
  return atualizado;
}

// `{data, tipo, resumo}` como vão para o servidor, com o resumo aparado (é o que ele guarda).
export const camposDoBloco = ({ data, tipo, resumo }) => ({ data, tipo, resumo: resumo.trim() });

// O corpo do PATCH: só o que mudou em relação ao contacto.
export function corpoCorrecao(bloco) {
  const atual = camposDoBloco(bloco);
  return Object.fromEntries(CAMPOS_BLOCO.filter((campo) => atual[campo] !== bloco.original[campo])
    .map((campo) => [campo, atual[campo]]));
}

// O `client_uuid` deste envio: o do bloco na primeira vez e no reenvio exato do último envio; senão, um novo. `campos`
// é o `camposDoBloco` agora, e `novoUuid` o `novoUuid4` do `ids.js`.
export function clientUuidDoEnvio({ clientUuid, ultimoEnvio }, campos, novoUuid) {
  if (ultimoEnvio === null) return clientUuid;
  return CAMPOS_BLOCO.every((campo) => ultimoEnvio[campo] === campos[campo]) ? clientUuid : novoUuid();
}

// O botão Guardar do bloco: {ativo, texto, falta} (falta: porque não se pode guardar, ou null). Enquanto a lista
// pedida ao abrir não volta fica desativado sem motivo à vista: é um instante.
export function estadoGuardarContacto({
  aGuardar, online, aAtualizar, resumo, data, hoje, alterado,
}) {
  if (aGuardar) return { ativo: false, texto: TEXTO_A_GUARDAR, falta: null };
  if (!online) return { ativo: false, texto: TEXTO_GUARDAR_SEM_REDE, falta: null };
  const desativado = (falta) => ({ ativo: false, texto: TEXTO_GUARDAR, falta });
  if (typeof resumo !== 'string' || resumo.trim() === '') return desativado(TEXTO_FALTA_RESUMO);
  if (!dataAceite(data, hoje)) return desativado(TEXTO_FALTA_DATA);
  if (aAtualizar) return desativado(null);
  if (!alterado) return desativado(TEXTO_FALTA_ALTERACOES);
  return { ativo: true, texto: TEXTO_GUARDAR, falta: null };
}

// Para onde volta o foco ao fechar o bloco: o botão que o abriu, ou "Adicionar contacto" se ele já não existir (o
// contacto saiu da lista, ou a pessoa já não o pode alterar).
export function focoAoFechar(origem, contactos) {
  const existe = contactos.some((contacto) => contacto.pode_alterar === true && alvoCorrigir(contacto.id) === origem);
  return existe ? origem : ALVO_ADICIONAR;
}

// --- Ecrã ----------------------------------------------------------------------------------------

// criarContactos({api, rede, lojaId, novoUuid, aoMudarVista, aoFocar, aoAvisar})
//   → {vista, iniciar, tentarDeNovo, abrirNovo, abrirCorrecao, mudarCampo, cancelar, guardar, pedirApagar,
//      responderApagar, destruir}
//  - api: {listarContactos, criarContacto, alterarContacto, apagarContacto} do lib/crm/api.js; lojaId: a loja da
//    ficha (sem ela é um engano no código: TypeError); rede: o `criarEstadoRede(window, navigator)`;
//  - novoUuid(): o `novoUuid4` do `ids.js` (por parâmetro, para os testes);
//  - aoFocar(alvo): 'data', 'tipo', 'resumo', `ALVO_GUARDAR`, `ALVO_ADICIONAR`, `alvoCorrigir(id)` ou `alvoApagar(id)`;
//  - aoAvisar(texto): o toast do sucesso.
// vista: {estado: 'a_carregar'|'falha'|'pronto', falha: null | {mensagem, aTentar}, linhas, semContactos,
//         adicionar: {ativo}, acoesAtivas, alerta, apagar: null | {id, descricao, pergunta, botoes},
//         bloco: null | {modo, titulo, data, min, max, tipo, resumo, opcoesTipo, erros, alerta, camposDesativados,
//                        guardar: {ativo, texto, falta}}}
//   — nova a cada mudança e congelada a fundo.
// Criar não pede nada: `iniciar()` pede a lista e ouve a rede; `destruir()` (a ficha saiu) faz que as respostas que
// chegarem depois e a rede já não façam nada.
export function criarContactos({
  api, rede, lojaId, novoUuid, aoMudarVista, aoFocar, aoAvisar,
}) {
  if (!textoComConteudo(lojaId)) throw new TypeError('criarContactos: falta a loja.');

  let hoje = null; // o do servidor (null até a lista chegar)
  let contactos = []; // as linhas da última resposta
  let falha = null; // a mensagem, se a lista não carregou
  let aCarregar = false;
  let bloco = null;
  let chaveBloco = 0; // distingue o bloco aberto de um que já fechou
  let porApagar = null; // o id do contacto da pergunta do Apagar
  let aApagar = false;
  let alerta = null; // a falha de um Apagar
  let ultimoPedido = 0; // sobe a cada pedido: uma lista pedida antes já não conta
  let iniciado = false;
  let ativo = true;
  let cancelarRede = () => {};

  const online = () => rede?.online() ?? true;
  const pronto = () => hoje !== null;
  const contactoComId = (id) => contactos.find((contacto) => contacto.id === id) ?? null;
  const acoesAtivas = () => bloco === null && !aApagar;

  function estadoAtual() {
    return estadoGuardarContacto({
      aGuardar: bloco.aGuardar,
      online: online(),
      aAtualizar: bloco.aAtualizar,
      resumo: bloco.resumo,
      data: bloco.data,
      hoje,
      alterado: bloco.modo === 'novo' || Object.keys(corpoCorrecao(bloco)).length > 0,
    });
  }

  function tituloDoBloco() {
    if (bloco.modo === 'novo') return TEXTO_NOVO_CONTACTO;
    const contacto = contactoComId(bloco.contactoId);
    return contacto === null ? TEXTO_CORRIGIR_CONTACTO : `Corrigir o ${rotuloNumero(contacto.numero)}`;
  }

  function vistaDoBloco() {
    if (bloco === null) return null;
    return Object.freeze({
      modo: bloco.modo,
      titulo: tituloDoBloco(),
      data: bloco.data,
      min: DATA_MINIMA,
      max: hoje,
      tipo: bloco.tipo,
      resumo: bloco.resumo,
      opcoesTipo: OPCOES_TIPO,
      erros: Object.freeze({ ...bloco.erros }),
      alerta: bloco.alerta,
      camposDesativados: bloco.aGuardar,
      guardar: Object.freeze(estadoAtual()),
    });
  }

  function vistaDoApagar() {
    if (porApagar === null) return null;
    // A lista pode ter mudado com a pergunta aberta: o servidor dirá que o contacto já não existe.
    const contacto = contactoComId(porApagar);
    const linha = contacto === null ? null : linhaDoContacto(contacto);
    const descricao = linha === null ? '' : `${linha.titulo} · ${linha.data} · ${linha.tipo}`;
    return Object.freeze({ id: porApagar, descricao, ...PERGUNTA_APAGAR });
  }

  function montarVista() {
    let estado = 'a_carregar';
    if (pronto()) estado = 'pronto';
    else if (falha !== null) estado = 'falha';
    return Object.freeze({
      estado,
      falha: estado === 'falha' ? Object.freeze({ mensagem: falha, aTentar: aCarregar }) : null,
      linhas: Object.freeze(contactos.map((contacto) => Object.freeze(linhaDoContacto(contacto)))),
      semContactos: estado === 'pronto' && contactos.length === 0,
      adicionar: Object.freeze({ ativo: pronto() && acoesAtivas() }),
      acoesAtivas: acoesAtivas(),
      alerta,
      apagar: vistaDoApagar(),
      bloco: vistaDoBloco(),
    });
  }

  let vista = montarVista();

  function atualizar() {
    vista = montarVista();
    aoMudarVista?.(vista);
  }

  // A resposta de uma das quatro rotas, se tiver a forma certa; senão fica tudo como estava.
  function aplicarLista(resposta) {
    if (!eDataValida(resposta?.hoje) || !Array.isArray(resposta?.contactos)) return false;
    hoje = resposta.hoje;
    contactos = resposta.contactos.filter(contactoValido);
    falha = null;
    return true;
  }

  async function carregar() {
    if (!ativo || aCarregar || pronto()) return;
    aCarregar = true;
    atualizar();
    let resposta;
    try {
      resposta = await api.listarContactos(lojaId);
    } catch (erro) {
      aCarregar = false;
      if (!ativo) return;
      falha = textoDoErro(erro);
      atualizar();
      return;
    }
    aCarregar = false;
    if (!ativo) return;
    if (!aplicarLista(resposta)) falha = MENSAGEM_ERRO_INESPERADO;
    atualizar();
  }

  // A lista pedida ao abrir o bloco. Se falhar, o bloco fica com o último `hoje` e deixa de esperar.
  async function atualizarAoAbrir(chave) {
    ultimoPedido += 1;
    const pedido = ultimoPedido;
    let resposta = null;
    try {
      resposta = await api.listarContactos(lojaId);
    } catch {
      resposta = null;
    }
    if (!ativo || pedido !== ultimoPedido) return;
    const aplicada = aplicarLista(resposta);
    if (bloco !== null && chave === chaveBloco) {
      bloco = aplicada ? blocoAtualizado(bloco, hoje) : { ...bloco, aAtualizar: false };
    }
    atualizar();
  }

  function abrir(novo) {
    chaveBloco += 1;
    bloco = novo;
    alerta = null;
    atualizar();
    aoFocar?.('resumo');
    atualizarAoAbrir(chaveBloco);
  }

  function fecharBloco() {
    const alvo = focoAoFechar(bloco.origem, contactos);
    bloco = null;
    return alvo;
  }

  // A gravação falhou: o bloco fica aberto, com o erro junto ao campo (e o foco lá) ou com a mensagem.
  function mostrarErroDoBloco(erro) {
    const campos = erro?.codigo === 'validacao' && eObjeto(erro.campos) ? erro.campos : {};
    const comErro = CAMPOS_BLOCO.filter((campo) => textoComConteudo(campos[campo]));
    if (comErro.length > 0) {
      bloco = { ...bloco, erros: Object.fromEntries(comErro.map((campo) => [campo, campos[campo]])) };
      atualizar();
      aoFocar?.(comErro[0]);
      return;
    }
    // O de outro campo (o `client_uuid`): a mensagem dele.
    bloco = { ...bloco, alerta: Object.values(campos).find(textoComConteudo) ?? textoDoErro(erro) };
    atualizar();
    // Sem rede, o botão continua desativado e não recebia o foco.
    aoFocar?.(estadoAtual().ativo ? ALVO_GUARDAR : 'resumo');
  }

  function enviar() {
    if (bloco.modo === 'corrigir') return api.alterarContacto(lojaId, bloco.contactoId, corpoCorrecao(bloco));
    const campos = camposDoBloco(bloco);
    const clientUuid = clientUuidDoEnvio(bloco, campos, novoUuid);
    bloco = { ...bloco, clientUuid, ultimoEnvio: campos };
    return api.criarContacto(lojaId, { ...campos, client_uuid: clientUuid });
  }

  async function guardar() {
    if (!ativo || bloco === null || !estadoAtual().ativo) return;
    const pedido = enviar();
    bloco = {
      ...bloco, aGuardar: true, erros: {}, alerta: null,
    };
    ultimoPedido += 1;
    atualizar();
    let resposta;
    try {
      resposta = await pedido;
    } catch (erro) {
      if (!ativo) return;
      bloco = { ...bloco, aGuardar: false };
      mostrarErroDoBloco(erro);
      return;
    }
    if (!ativo) return;
    aplicarLista(resposta);
    const alvo = fecharBloco();
    atualizar();
    aoAvisar?.(TEXTO_CONTACTO_GUARDADO);
    aoFocar?.(alvo);
  }

  async function apagar(id) {
    aApagar = true;
    alerta = null;
    ultimoPedido += 1;
    atualizar();
    let resposta;
    try {
      resposta = await api.apagarContacto(lojaId, id);
    } catch (erro) {
      if (!ativo) return;
      aApagar = false;
      alerta = textoDoErro(erro);
      atualizar();
      aoFocar?.(alvoApagar(id));
      return;
    }
    if (!ativo) return;
    aApagar = false;
    aplicarLista(resposta);
    atualizar();
    aoAvisar?.(TEXTO_CONTACTO_APAGADO);
    aoFocar?.(ALVO_ADICIONAR);
  }

  return {
    get vista() {
      return vista;
    },
    iniciar() {
      if (!ativo || iniciado) return;
      iniciado = true;
      // Sem rede, Guardar diz "Guardar — sem rede"; quando a rede volta, a lista que falhou pede-se outra vez.
      cancelarRede = rede?.aoMudar((ligado) => {
        if (!ativo) return;
        atualizar();
        if (ligado && falha !== null) carregar();
      }) ?? (() => {});
      carregar();
    },
    // "Tentar novamente" (a lista não carregou); um toque, um pedido.
    tentarDeNovo() {
      if (falha !== null) carregar();
    },
    abrirNovo() {
      if (!ativo || !pronto() || !acoesAtivas()) return;
      abrir(blocoNovo({ hoje, clientUuid: novoUuid() }));
    },
    abrirCorrecao(id) {
      const contacto = contactoComId(id);
      if (!ativo || !acoesAtivas() || contacto?.pode_alterar !== true) return;
      abrir(blocoDeCorrecao(contacto));
    },
    mudarCampo(campo, valor) {
      if (!ativo || bloco === null || bloco.aGuardar) return;
      const novo = mudarBloco(bloco, campo, valor);
      if (novo === bloco) return;
      bloco = novo;
      atualizar();
    },
    cancelar() {
      if (!ativo || bloco === null || bloco.aGuardar) return;
      const alvo = fecharBloco();
      atualizar();
      aoFocar?.(alvo);
    },
    guardar,
    pedirApagar(id) {
      if (!ativo || !acoesAtivas() || porApagar !== null || contactoComId(id)?.pode_alterar !== true) return;
      alerta = null;
      porApagar = id;
      atualizar();
    },
    // A resposta à pergunta do Apagar (`RESPOSTA_APAGAR` ou null); só a primeira conta.
    responderApagar(valor) {
      if (!ativo || porApagar === null) return;
      const id = porApagar;
      porApagar = null;
      atualizar();
      if (valor === RESPOSTA_APAGAR) apagar(id);
    },
    destruir() {
      if (!ativo) return;
      ativo = false;
      cancelarRede();
    },
  };
}
