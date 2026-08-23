"""O ecrã das **NOTAS DE CRÉDITO PRESAS** — montado e tocado, não lido.

**O buraco que este ficheiro fecha, medido.** As três rotas de gestão
existiam e as guardas seguravam (libertar com documento gravado recusa;
libertar aos 10 s recusa; sem `confirmado_no_vendus` recusa; as escritas são
condicionais). **E não havia ecrã nenhum.** `App.js` só tinha
`faturacao/reservas-presas`, o `AdminLayout` só tinha o item de menu dela, e
`lib/faturacao.js` não tinha cliente nenhum para
`/fiscal/notas-credito-presas`. A mensagem do fecho da caixa mandava o gestor
«à lista de notas de crédito presas do backoffice» — uma lista que não
existia. Com UM PC por loja, a única saída era um POST à mão com um JWT.

**A decisão: um CARD NOVO no mesmo ecrã, e não um ecrã irmão.** Três razões,
e a terceira é a que decide:

1. é o MESMO género de problema — ficou a meio, não se resolve sozinho, e
   alguém tem de ir perguntar ao Vendus o que aconteceu;
2. é o ecrã a que o gestor JÁ vem quando a loja telefona a dizer que a caixa
   não fecha — e as duas coisas trancam o fecho exactamente da mesma maneira;
3. **as duas listas cruzam-se**: o mesmo turno pode estar trancado pelas
   duas, e lado a lado leem-se como UMA resposta à pergunta «porque é que
   esta caixa não fecha?». Em páginas diferentes, o gestor resolve uma,
   tenta fechar, leva outro 409, e vai à procura da segunda.

O precedente está escrito no próprio ficheiro: o card das contas por cobrar
de turnos fechados já vive lá pela mesma família de razões.

A técnica é a de `test_a_nota_de_credito_no_ecra.py`: jsdom, babel, o React a
sério, o axios de GESTÃO fabricado à frente, e o que se afirma é o que o
gestor LÊ (`textoVisivel`) e o que o ecrã MANDA (`pedidos[i].corpo`) — nunca
o `textContent` nem o texto do ficheiro. Um guarda que leia o HTML não vale
nada: foi um desses que deixou passar o ecrã inteiro em falta.
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node


# --- A biblioteca de UI que responde ao dedo ---------------------------------
#
# Este ecrã abre DIÁLOGOS e tem uma CAIXA DE CONFIRMAÇÃO que arma o botão
# destrutivo — as marcas vazias não chegam. O `Dialog`/`AlertDialog` só
# desenha os filhos quando está `open`, que é o que torna afirmável «o
# diálogo abriu» e «o que ele diz».
_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled,",
    "  className: props.className, type: 'button',",
    "  'data-testid': props['data-testid'],",
    "  'data-desligado': props.disabled ? 'sim' : 'nao',",
    "}, props.children);",
    "const Caixa = (props) => React.createElement('input', {",
    "  type: 'checkbox', id: props.id,",
    "  checked: !!props.checked,",
    "  onChange: (e) => props.onCheckedChange && props.onCheckedChange(e.target.checked),",
    "});",
    "const Area = (props) => React.createElement('textarea', {",
    "  id: props.id, value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "});",
    "const Div = (props) => React.createElement('div', null, props.children);",
    # Os dois diálogos: fechados não desenham nada, e é isso que distingue
    # «o gestor leu o aviso» de «o aviso está no ficheiro».
    "const Dialogo = (props) => (props.open",
    "  ? React.createElement('div', { 'data-dialogo': 'aberto' }, props.children)",
    "  : null);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button' || nome === 'AlertDialogAction'",
    "      || nome === 'AlertDialogCancel') return Botao;",
    "  if (nome === 'Checkbox') return Caixa;",
    "  if (nome === 'Textarea') return Area;",
    "  if (nome === 'Dialog' || nome === 'AlertDialog') return Dialogo;",
    "  return Div;",
    "} });",
])


# --- O que o servidor manda --------------------------------------------------
#
# Os valores expõem o cêntimo, como no resto do módulo: 10,20 · 1,15 · 0,29.

_NOTA_PRESA = {
    "id": "33333333-3333-4333-8333-333333333333",
    "ext_ref": "pos-loja-1-sessao-1-nc-33333333-3333-4333-8333-333333333333",
    "loja_id": "loja-1", "caixa_id": "caixa-1", "sessao_id": "sessao-1",
    "documento_id": "doc-1", "numero_origem": "FS 05P2026/1824",
    "motivo": "Cliente devolveu o açaí.",
    "total": 10.20,
    "devolucao": {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                  "tipo_fiscal": "NU", "valor": 10.20},
    "operador": {"id": "op-1", "nome": "Rafaela"},
    "criada_em": "2026-08-22T10:00:00+00:00",
    "presa_ha_segundos": 5400.0,
    "emissao_talvez_a_decorrer": False,
    "saidas": ("Procure a referência externa no Vendus. NÃO está lá: "
               "LIBERTAR. Está lá, ou não consegue apurar: POR APURAR."),
}
# A que pode estar a falar com o Vendus NESTE instante: as duas rotas
# recusam-na, e o ecrã não pode convidar ao toque.
_NOTA_RECENTE = dict(
    _NOTA_PRESA,
    id="44444444-4444-4444-8444-444444444444",
    ext_ref="pos-loja-1-sessao-1-nc-44444444-4444-4444-8444-444444444444",
    numero_origem="FS 05P2026/1825", total=1.15,
    presa_ha_segundos=12.0, emissao_talvez_a_decorrer=True,
)

_LIBERTADA = {
    "libertada": True, "id": _NOTA_PRESA["id"], "ext_ref": _NOTA_PRESA["ext_ref"],
    "o_que_confirmou": ("Confirmou que NÃO existe no Vendus nenhuma nota de "
                        "crédito com a referência externa «%s»."
                        % _NOTA_PRESA["ext_ref"]),
    "a_seguir": ("A intenção foi apagada: a fatura volta a deixar creditar "
                 "estas linhas e o fecho desta caixa deixa de ser recusado "
                 "por causa dela."),
}
_POR_APURAR = {
    "por_apurar": True, "id": _NOTA_PRESA["id"], "ext_ref": _NOTA_PRESA["ext_ref"],
    "a_seguir": ("A nota ficou marcada POR APURAR: continua a travar novo "
                 "crédito destas linhas, NÃO desconta a gaveta e já não trava "
                 "o fecho da caixa."),
}


def _j(valor):
    return json.dumps(valor, ensure_ascii=False)


_GUIAO = "\n".join([
    _COMPONENTES,
    "const path2 = require('path');",
    "const ADMIN = path2.join(RAIZ, 'pages', 'admin', 'faturacao');",
    "const Ecra = carregar(path2.join(ADMIN, 'FatReservasPresas.js')).default;",
    "",
    "function escrever(el, valor) {",
    "  const proto = el.tagName === 'TEXTAREA'",
    "    ? dom.window.HTMLTextAreaElement.prototype",
    "    : dom.window.HTMLInputElement.prototype;",
    "  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, valor);",
    "  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));",
    "}",
    "const porTestid = (alvo, id) => alvo.querySelector('[data-testid=\"' + id + '\"]');",
    "const botaoDe = (alvo, texto) => Array.from(alvo.querySelectorAll('button'))",
    "  .find((b) => (b.textContent || '').includes(texto));",
    "",
    "const NOTA = %s;" % _j(_NOTA_PRESA),
    "const RECENTE = %s;" % _j(_NOTA_RECENTE),
    "const LIBERTADA = %s;" % _j(_LIBERTADA),
    "const POR_APURAR = %s;" % _j(_POR_APURAR),
    "const BASE = {",
    "  '/faturacao/fiscal/reservas-presas': () => ({ data: [] }),",
    "  '/faturacao/lojas': () => ({ data: [{ id: 'loja-1', nome: 'Loja do Guarda' }] }),",
    "  '/faturacao/caixa/contas-esquecidas': () => ({ data: [] }),",
    "  '/faturacao/fiscal/notas-credito-presas': () => ({ data: [NOTA, RECENTE] }),",
    "};",
    "const comBase = (extra) => Object.assign({}, BASE, extra || {});",
    "",
    "async function abrir(respostas) {",
    "  for (const k of Object.keys(RESPOSTAS_GESTAO)) delete RESPOSTAS_GESTAO[k];",
    "  Object.assign(RESPOSTAS_GESTAO, respostas);",
    "  pedidos.length = 0;",
    "  const alvo = document.getElementById('raiz');",
    "  const raiz = createRoot(alvo);",
    "  await act(async () => { raiz.render(React.createElement(Ecra)); });",
    "  await act(async () => {});",
    "  return {",
    "    alvo,",
    "    ver: () => textoVisivel(alvo),",
    "    fechar: async () => {",
    "      await act(async () => { raiz.unmount(); });",
    "      alvo.innerHTML = '';",
    "    },",
    "  };",
    "}",
    "const saida = {};",
    "",
    # --- 1) a lista existe, e pergunta ao servidor ---------------------------
    "{",
    "  const ecra = await abrir(comBase());",
    "  saida.lista = {",
    "    visivel: ecra.ver(),",
    "    perguntou: pedidos.some((p) => p.url.includes('/notas-credito-presas')),",
    "  };",
    "  await ecra.fechar();",
    "}",
    # Uma marca no PRÓPRIO JavaScript, e não um comentário de Python: é por ela
    # que o controlo do instrumento corta o guião para medir só a listagem
    # contra a versão do ecrã ANTERIOR ao card (os cenários que TOCAM nos
    # botões nem chegam a correr sem eles, e um erro de Node não é uma
    # medição).
    "// --- fim do cenario da listagem ---",
    "",
    # --- 2) POR APURAR: a saída segura, sem confirmação nenhuma -------------
    "{",
    "  const ecra = await abrir(comBase({",
    "    ['POST /faturacao/fiscal/notas-credito/' + NOTA.id + '/por-apurar']:",
    "      () => ({ data: POR_APURAR }),",
    "  }));",
    "  await act(async () => { porTestid(ecra.alvo, 'nc-por-apurar-' + NOTA.id).click(); });",
    "  await act(async () => {});",
    "  const p = pedidos.filter((x) => x.url.includes('/por-apurar'));",
    "  saida.por_apurar = {",
    "    quantos: p.length,",
    "    url: (p[0] || {}).url,",
    "    corpo: (p[0] || {}).corpo,",
    "    visivel: ecra.ver(),",
    "  };",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 3) LIBERTAR: o diálogo, a declaração, e o botão armado -------------
    "{",
    "  const ecra = await abrir(comBase({",
    "    ['POST /faturacao/fiscal/notas-credito/' + NOTA.id + '/libertar']:",
    "      () => ({ data: LIBERTADA }),",
    "  }));",
    "  await act(async () => { porTestid(ecra.alvo, 'nc-libertar-' + NOTA.id).click(); });",
    "  const confirmar = () => porTestid(ecra.alvo, 'nc-libertar-confirmar');",
    "  saida.libertar_dialogo = {",
    "    visivel: ecra.ver(),",
    "    desligado_sem_declaracao: confirmar().getAttribute('data-desligado'),",
    "  };",
    # O toque no botão AINDA POR ARMAR: nada pode sair daqui.
    "  await act(async () => { confirmar().click(); });",
    "  await act(async () => {});",
    "  saida.libertar_sem_declaracao = pedidos.filter(",
    "    (x) => x.url.includes('/libertar')).length;",
    # E agora a declaração à mão.
    "  await act(async () => {",
    "    ecra.alvo.querySelector('#nc-confirmou-no-vendus').click();",
    "  });",
    "  await act(async () => {",
    "    escrever(ecra.alvo.querySelector('#nc-nota-libertar'), 'Procurei e não está.');",
    "  });",
    "  saida.libertar_armado = confirmar().getAttribute('data-desligado');",
    "  await act(async () => { confirmar().click(); });",
    "  await act(async () => {});",
    "  const p = pedidos.filter((x) => x.url.includes('/libertar'));",
    "  saida.libertar = {",
    "    quantos: p.length,",
    "    url: (p[0] || {}).url,",
    "    corpo: (p[0] || {}).corpo,",
    "    visivel: ecra.ver(),",
    "  };",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 4) a lista vazia ----------------------------------------------------
    "{",
    "  const ecra = await abrir(comBase({",
    "    '/faturacao/fiscal/notas-credito-presas': () => ({ data: [] }),",
    "  }));",
    "  saida.vazia = ecra.ver();",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 5) a rota em baixo --------------------------------------------------
    "{",
    "  const ecra = await abrir(comBase({",
    "    '/faturacao/fiscal/notas-credito-presas': () => {",
    "      const e = new Error('Network Error'); e.response = { status: 500,",
    "        data: { detail: 'a base de dados não respondeu' } }; throw e; },",
    "  }));",
    "  saida.em_baixo = ecra.ver();",
    "  await ecra.fechar();",
    "}",
    "",
    "process.stdout.write(JSON.stringify(saida));",
])


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _GUIAO,
        tmp_path_factory.mktemp("ncpresas"), "montar-nc-presas.js",
    )


# --- 1. A lista existe --------------------------------------------------------


def test_o_ecra_PERGUNTA_ao_servidor_pelas_notas_de_credito_presas(ecra):
    """O defeito, na sua forma mais curta: não havia cliente nenhum para
    `/fiscal/notas-credito-presas` em todo o repositório, e por isso este
    pedido NÃO saía. O gestor abria o ecrã a que a mensagem do fecho o
    mandava e não via a nota que estava a trancar a caixa."""
    assert ecra["lista"]["perguntou"] is True


def test_a_nota_presa_APARECE_com_o_que_o_gestor_precisa_de_ir_procurar(ecra):
    """A referência externa é o que ele escreve no Vendus — e escrevê-la mal
    uma vez é procurar o documento errado e concluir a coisa errada. Com o
    total, a fatura de origem e o motivo ao lado, para ele saber que nota é."""
    visivel = ecra["lista"]["visivel"]
    assert "Notas de Crédito Presas" in visivel
    assert _NOTA_PRESA["ext_ref"] in visivel
    assert "FS 05P2026/1824" in visivel
    assert "10,20" in visivel
    assert "Cliente devolveu o açaí." in visivel
    assert "Loja do Guarda" in visivel


def test_a_nota_presa_diz_HA_QUANTO_TEMPO_e_as_duas_saidas(ecra):
    """1h30 e não «5400.0 s»: o gestor tem de distinguir de relance os 12
    segundos de uma emissão a decorrer da nota de ontem à noite. E as saídas
    são as do SERVIDOR, tal e qual — é lá que elas são decididas."""
    visivel = ecra["lista"]["visivel"]
    assert "presa há 1 h 30 min" in visivel
    assert _NOTA_PRESA["saidas"] in visivel


def test_a_que_PODE_estar_a_falar_com_o_Vendus_agora_nao_tem_botoes(ecra):
    """As duas rotas recusam-na com 409, e um ecrã que a convidasse ao toque
    era um ecrã a mentir. Quem decide é o SERVIDOR
    (`emissao_talvez_a_decorrer`), nunca o relógio do browser."""
    visivel = ecra["lista"]["visivel"]
    assert "Não é para mexer" in visivel
    # E é distinguível: a outra tem os dois botões.
    assert "Marcar por apurar" in visivel
    assert "Libertar a nota" in visivel


# --- 2. POR APURAR: a saída segura --------------------------------------------


def test_MARCAR_POR_APURAR_e_um_toque_so_e_sai_para_a_rota_certa(ecra):
    """É a direcção que nunca pode fazer estrago — a nota continua a travar o
    crédito, continua a não descontar a gaveta, e deixa de travar o fecho. Por
    isso não pede confirmação nenhuma: pedi-la era pôr um passo entre o gestor
    e a saída segura."""
    assert ecra["por_apurar"]["quantos"] == 1
    assert ecra["por_apurar"]["url"].endswith(
        "/faturacao/fiscal/notas-credito/%s/por-apurar" % _NOTA_PRESA["id"])
    assert ecra["por_apurar"]["corpo"] == {"nota": None}


def test_depois_do_POR_APURAR_o_gestor_LE_o_que_ficou_a_valer(ecra):
    """A frase é a do servidor, tal e qual: é lá que ela é decidida, e uma
    segunda cópia aqui divergia dela no dia seguinte."""
    assert _POR_APURAR["a_seguir"] in ecra["por_apurar"]["visivel"]


# --- 3. LIBERTAR: o botão que autoriza uma segunda nota real ------------------


def test_LIBERTAR_abre_um_dialogo_que_diz_o_que_ele_esta_a_declarar(ecra):
    """Libertar uma nota que SAIU é autorizar uma segunda nota de crédito real
    da mesma devolução — dois documentos entregues à AT a devolver o mesmo
    dinheiro. O diálogo escreve o que ele tem de ter visto, com a referência
    dentro."""
    visivel = ecra["libertar_dialogo"]["visivel"]
    assert "Libertar a nota de crédito presa" in visivel
    assert _NOTA_PRESA["ext_ref"] in visivel
    assert "segunda nota de crédito real da mesma devolução" in visivel


def test_SEM_A_DECLARACAO_o_botao_esta_desligado_e_nada_sai(ecra):
    """Cinto e suspensórios, o mesmo desenho do LIBERTAR das reservas fiscais:
    o botão está morto, e um toque nele — que o jsdom deixa dar — não manda
    pedido nenhum. Um `true` fixo no cliente transformava o 422 do servidor,
    que é a última rede, em decoração."""
    assert ecra["libertar_dialogo"]["desligado_sem_declaracao"] == "sim"
    assert ecra["libertar_sem_declaracao"] == 0


def test_COM_A_DECLARACAO_o_botao_arma_e_o_pedido_leva_a_confirmacao(ecra):
    """O controlo do de cima (um botão desligado para sempre passava por «a
    recusa funciona») e o corpo do pedido: `confirmado_no_vendus` só sai a
    `true` porque o gestor carimbou a caixa à mão."""
    assert ecra["libertar_armado"] == "nao"
    assert ecra["libertar"]["quantos"] == 1
    assert ecra["libertar"]["url"].endswith(
        "/faturacao/fiscal/notas-credito/%s/libertar" % _NOTA_PRESA["id"])
    assert ecra["libertar"]["corpo"] == {
        "confirmado_no_vendus": True, "nota": "Procurei e não está."}


def test_depois_de_LIBERTAR_o_gestor_LE_o_que_declarou_e_o_que_se_segue(ecra):
    visivel = ecra["libertar"]["visivel"]
    assert _LIBERTADA["o_que_confirmou"] in visivel
    assert _LIBERTADA["a_seguir"] in visivel


# --- 4. e 5. O vazio e o silêncio ---------------------------------------------


def test_a_lista_VAZIA_diz_que_e_uma_boa_noticia(ecra):
    """Vazia e muda parecia uma avaria — e é aqui que o gestor chega com a
    loja ao telefone a dizer que a caixa não fecha."""
    assert "Nenhuma nota de crédito presa" in ecra["vazia"]
    assert _NOTA_PRESA["ext_ref"] not in ecra["vazia"]


def test_com_a_rota_EM_BAIXO_o_ecra_diz_que_nao_SABE(ecra):
    """Nunca uma lista vazia — aqui isso lia-se como «não há nenhuma presa», e
    mandava o gestor procurar o problema noutro sítio. E a lista das reservas
    fiscais, que é a razão de ser do ecrã, continua a desenhar-se."""
    visivel = ecra["em_baixo"]
    assert "Nenhuma nota de crédito presa" not in visivel
    assert "a base de dados não respondeu" in visivel
    assert "Nenhuma reserva fiscal presa" in visivel
