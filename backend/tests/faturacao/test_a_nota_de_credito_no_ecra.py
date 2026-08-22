"""O ecrã da **NOTA DE CRÉDITO** — montado e tocado, não lido.

Este ecrã emite um documento fiscal REAL sobre uma fatura já entregue à
Autoridade Tributária, e devolve dinheiro da gaveta. Até esta ronda não tinha
um único teste: **dez mutações no ficheiro, dez sobreviveram** à suite
completa. Nenhuma delas partia nada — apagar a faixa que diz se sai ou não
dinheiro da gaveta, fazê-la mentir para o Glovo, tirar o tecto da quantidade,
deixar emitir sem motivo, tirar o travão do duplo toque, trocar o `useRef` da
intenção (que é o gatilho da corrida que punha DUAS notas reais na AT),
deixar remarcar linhas já creditadas, fazer as notas anteriores desaparecerem.

A técnica é a de `test_o_separador_de_faturacao_no_ecra.py`, e o preâmbulo de
montagem vem inteiro de `test_a_faixa_do_modo_no_ecra.py` — jsdom, babel, o
React a sério, o servidor fabricado à frente do axios do `lib/pos`. O que se
afirma é o que a OPERADORA LÊ (`textoVisivel`), nunca o `textContent`: uma
classe de estilo apaga uma faixa inteira sem mexer numa palavra do ficheiro.

**Três coisas que este ficheiro faz e os outros não precisavam de fazer:**

1. **escreve nos campos como um dedo escreve** — o valor entra pelo setter
   nativo do `HTMLInputElement` e só depois se dispara o evento, que é o
   único caminho que o React aceita num campo controlado;
2. **carrega no botão DUAS VEZES no mesmo instante**, com o servidor
   suspenso, e conta os `POST` que saem. É a única forma de ver o travão do
   duplo toque: um travão que dependa do re-render não fecha essa janela;
3. **lê o CORPO dos pedidos** (`pedidos[i].corpo`), e não só o caminho. O
   tecto da quantidade prova-se no `{ linhas: [...] }` que sai para o
   servidor — no caminho não se vê nada.

**O que NÃO cobre, dito por extenso.** O que se vê mede-se com a folha de
estilo à mão do preâmbulo (`hidden`, `flex`, `invisible`, `sr-only`);
esconder por outro caminho (opacidade, largura zero) passa por aqui sem
acordar ninguém. O `disabled` prova-se pelo atributo, não pelo pixel. E a
tabela do imposto vem do servidor — o que aqui se afirma é que o ecrã a
mostra, nunca que os números estão certos (isso é `test_nota_credito.py`).
"""
import json

import pytest

from .test_a_faixa_do_modo_no_ecra import _montar_no_node


# --- A biblioteca de UI que responde ao dedo ---------------------------------
#
# Ver a docstring de `test_o_separador_de_faturacao_no_ecra.py`: as marcas
# vazias chegam para um ecrã que se desenha sozinho, e não chegam para um em
# que tudo depende de alguém tocar. O que muda em relação à de lá é o `Campo`:
# aqui os campos são procurados pelo `aria-label` e pelo `id`, e alguns estão
# DESLIGADOS (a linha já creditada) — um `<input>` que deixasse cair esses
# atributos punha metade destes guardas a medir o campo errado, ou a medir um
# campo morto como se estivesse vivo.
_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled,",
    "  className: props.className, type: 'button',",
    "  'data-desligado': props.disabled ? 'sim' : 'nao',",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  id: props.id, type: props.type || 'text',",
    "  'aria-label': props['aria-label'],",
    "  value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "  disabled: props.disabled, maxLength: props.maxLength,",
    "  inputMode: props.inputMode, className: props.className,",
    "});",
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'Input') return Campo;",
    "  return Div;",
    "} });",
])


# --- Os dados que o servidor manda -------------------------------------------
#
# Os valores expõem o cêntimo de propósito, como no resto do módulo: 9,85 ·
# 1,15 · 0,29. A fatura vale 11,29 €, que é a mesma fatura com que os defeitos
# do servidor foram reproduzidos.

_LINHA_ACAI = {
    "indice": 1, "titulo": "Açaí Regular", "tax_id": "INT",
    "quantidade": 2, "creditado": 0, "disponivel": 2,
    "preco_unitario": 9.85, "desconto_percentagem": None, "total": 19.70,
}
# Uma linha JÁ CREDITADA POR INTEIRO numa nota anterior: fica na lista (some-la
# fazia a operadora procurar o artigo que o cliente traz na mão e concluir que
# a fatura não era aquela), mas morta.
_LINHA_COLA = {
    "indice": 2, "titulo": "Coca-Cola", "tax_id": "NOR",
    "quantidade": 1, "creditado": 1, "disponivel": 0,
    "preco_unitario": 1.15, "desconto_percentagem": None, "total": 1.15,
}

_PREPARACAO = {
    "documento": {
        "id": "doc-1", "numero": "FS 05P2026/1824", "atcud": "JFT7-1824",
        "tipo": "FS", "modo": "normal",
        "emitido_em": "2026-08-22T11:12:00", "total": 11.29,
    },
    "cliente_nif": None,
    "pagamentos": [
        {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
         "recebido": 5.00, "devolvido": 0.0, "disponivel": 5.00},
        {"tipo_pagamento_id": "t-mb", "nome": "Multibanco", "tipo_fiscal": "CD",
         "recebido": 6.29, "devolvido": 0.0, "disponivel": 6.29},
    ],
    "linhas": [_LINHA_ACAI, _LINHA_COLA],
    "notas_anteriores": [
        {"id": "n-1", "numero": "NC 05P2026/7", "estado": "emitida",
         "total": 1.15, "motivo": "Refrigerante trocado.",
         "emitido_em": "2026-08-22T12:00:00"},
        {"id": "n-2", "numero": None, "estado": "incerta", "total": 0.29,
         "motivo": "Água.", "emitido_em": None},
    ],
}

_TIPOS = [
    {"id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU", "pronto": True},
    {"id": "t-glovo", "nome": "Glovo", "tipo_fiscal": "OU", "pronto": True},
]

_RESUMO_9_85 = {
    "linhas": [], "subtotal": 8.72, "total": 9.85,
    "mapa_imposto": [{"tax_id": "INT", "taxa": 13, "documentos": 1,
                      "base": 8.72, "iva": 1.13, "total": 9.85}],
    "totais_imposto": {"base": 8.72, "iva": 1.13, "total": 9.85},
}
_RESUMO_ZERO = {
    "linhas": [], "subtotal": 0.0, "total": 0.0,
    "mapa_imposto": [], "totais_imposto": {"base": 0.0, "iva": 0.0, "total": 0.0},
}

_EMITIDA = {
    "id": "n-3", "documento_id": "doc-nc", "numero": "NC 05P2026/9",
    "atcud": "JFT7-NC9", "tipo": "NC", "modo": "normal",
    "emitido_em": "2026-08-22T13:00:00", "numero_origem": "FS 05P2026/1824",
    "motivo": "Cliente devolveu o açaí.",
    "devolucao": {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                  "tipo_fiscal": "NU", "valor": 9.85, "acima_do_recebido": 4.85},
    "linhas": [], "mapa_imposto": [], "totais_imposto": {},
    "total": 9.85, "total_das_linhas": 9.85, "total_divergente": False,
}


def _j(valor):
    return json.dumps(valor, ensure_ascii=False)


# --- O guião: todos os cenários num só arranque de Node ----------------------
#
# Um `_montar_no_node` por cenário custava dez arranques de Node com o babel a
# transformar o ecrã de raiz de cada vez. Aqui é um só: cada cenário monta,
# toca, olha, e desmonta; o que sai é um JSON que as afirmações lêem.

_GUIAO = "\n".join([
    _COMPONENTES,
    "const path2 = require('path');",
    "const PosNotaCredito = carregar(path2.join(POS, 'PosNotaCredito.js')).default;",
    "",
    # --- o dedo -------------------------------------------------------------
    # Um campo controlado do React não muda com `el.value = x`: o React guarda
    # o valor anterior no nó e ignora o evento se o valor "não mudou". O setter
    # nativo escreve por baixo desse rasto, e só depois se dispara o evento —
    # é a técnica de sempre, e sem ela metade destes guardas ficava verde sem
    # ter escrito nada.
    "function escrever(el, valor) {",
    "  const proto = el.tagName === 'SELECT'",
    "    ? dom.window.HTMLSelectElement.prototype",
    "    : dom.window.HTMLInputElement.prototype;",
    "  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, valor);",
    "  el.dispatchEvent(new dom.window.Event(",
    "    el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));",
    "}",
    "const porRotulo = (alvo, rotulo) =>",
    "  alvo.querySelector('[aria-label=\"' + rotulo + '\"]');",
    "const botaoDe = (alvo, texto) => Array.from(alvo.querySelectorAll('button'))",
    "  .find((b) => (b.textContent || '').includes(texto));",
    "",
    "async function abrir(respostas, props) {",
    "  for (const k of Object.keys(RESPOSTAS_POS)) delete RESPOSTAS_POS[k];",
    "  Object.assign(RESPOSTAS_POS, respostas);",
    "  pedidos.length = 0;",
    "  const alvo = document.getElementById('raiz');",
    "  const raiz = createRoot(alvo);",
    "  await act(async () => {",
    "    raiz.render(React.createElement(PosNotaCredito, Object.assign(",
    "      { documento: { id: 'doc-1' }, caixaId: 'caixa-1',",
    "        onFechar: () => {}, onEmitida: () => {} }, props || {})));",
    "  });",
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
    "",
    "const PREPARACAO = %s;" % _j(_PREPARACAO),
    "const TIPOS = %s;" % _j(_TIPOS),
    "const RESUMO = %s;" % _j(_RESUMO_9_85),
    "const RESUMO_ZERO = %s;" % _j(_RESUMO_ZERO),
    "const EMITIDA = %s;" % _j(_EMITIDA),
    "const BASE = {",
    "  'GET /pos/documentos/doc-1/nota-credito': () => ({ data: PREPARACAO }),",
    "  '/pos/tipos-pagamento': () => ({ data: TIPOS }),",
    "  '/pos/documentos/doc-1/nota-credito/pre-visualizar': () => ({ data: RESUMO }),",
    "  'POST /pos/documentos/doc-1/nota-credito': () => ({ data: EMITIDA }),",
    "};",
    "const comBase = (extra) => Object.assign({}, BASE, extra || {});",
    "const saida = {};",
    "",
    # --- 1) escolher o meio da devolução, e o que ele faz à gaveta -----------
    "async function escolherMeio(idDoTipo) {",
    "  const ecra = await abrir(comBase());",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  await act(async () => {",
    "    escrever(ecra.alvo.querySelector('#nc-devolucao'), idDoTipo);",
    "  });",
    "  const visto = ecra.ver();",
    "  await ecra.fechar();",
    "  return visto;",
    "}",
    "saida.meio_dinheiro = await escolherMeio('t-nu');",
    "saida.meio_glovo = await escolherMeio('t-glovo');",
    # O CONTROLO do aviso do meio: a mesma fatura paga TODA em dinheiro. A
    # devolução de 9,85 € cabe nos 11,29 € que a gaveta recebeu, e não há
    # aviso nenhum — sem isto, um aviso que estivesse sempre lá passava por
    # «o aviso funciona».
    "{",
    "  const paga_em_dinheiro = Object.assign({}, PREPARACAO, { pagamentos: [",
    "    { tipo_pagamento_id: 't-nu', nome: 'Dinheiro', tipo_fiscal: 'NU',",
    "      recebido: 11.29, devolvido: 0, disponivel: 11.29 }] });",
    "  const ecra = await abrir(comBase({",
    "    'GET /pos/documentos/doc-1/nota-credito': () => ({ data: paga_em_dinheiro }),",
    "  }));",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-devolucao'), 't-nu'); });",
    "  saida.meio_que_chega = ecra.ver();",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 2) o tecto da quantidade -------------------------------------------
    "{",
    "  const ecra = await abrir(comBase());",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  await act(async () => {",
    "    escrever(porRotulo(ecra.alvo, 'Quantidade a creditar de Açaí Regular'), '5');",
    "  });",
    "  saida.tecto = {",
    "    no_campo: porRotulo(ecra.alvo, 'Quantidade a creditar de Açaí Regular').value,",
    "    ultimo_pedido: (pedidos.filter((p) => p.url.includes('pre-visualizar'))",
    "      .slice(-1)[0] || {}).corpo,",
    "  };",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 3) sem motivo não se emite -----------------------------------------
    "async function comCampos({ motivo, tipo }) {",
    "  const ecra = await abrir(comBase());",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  if (motivo !== null) {",
    "    await act(async () => { escrever(ecra.alvo.querySelector('#nc-motivo'), motivo); });",
    "  }",
    "  if (tipo !== null) {",
    "    await act(async () => { escrever(ecra.alvo.querySelector('#nc-devolucao'), tipo); });",
    "  }",
    "  const botao = botaoDe(ecra.alvo, 'Emitir Nota de Crédito');",
    "  const r = { desligado: botao.getAttribute('data-desligado'), visivel: ecra.ver() };",
    "  await ecra.fechar();",
    "  return r;",
    "}",
    "saida.sem_motivo = await comCampos({ motivo: null, tipo: 't-nu' });",
    "saida.sem_meio = await comCampos({ motivo: 'Veio com a fruta trocada.', tipo: null });",
    "saida.pronto = await comCampos(",
    "  { motivo: 'Veio com a fruta trocada.', tipo: 't-nu' });",
    "",
    # --- 4) o duplo toque ----------------------------------------------------
    # O servidor fica SUSPENSO (uma promessa que ninguém resolve) e os dois
    # toques dão-se no MESMO instante, antes de o React voltar a desenhar: é
    # exactamente a janela que um travão feito de estado não fecha.
    "{",
    "  let resolver;",
    "  const suspenso = new Promise((r) => { resolver = r; });",
    "  const ecra = await abrir(comBase({",
    "    'POST /pos/documentos/doc-1/nota-credito': () => suspenso,",
    "  }));",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-motivo'), 'Fruta trocada.'); });",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-devolucao'), 't-nu'); });",
    "  const botao = botaoDe(ecra.alvo, 'Emitir Nota de Crédito');",
    "  await act(async () => { botao.click(); botao.click(); });",
    "  const emissoes = () => pedidos.filter(",
    "    (p) => p.metodo === 'post' && p.url.endsWith('/nota-credito')).length;",
    "  saida.duplo_toque = {",
    "    emissoes_depois_de_dois_toques: emissoes(),",
    "    desligado_enquanto_emite: botaoDe(ecra.alvo, 'Emitir Nota de Crédito')",
    "      .getAttribute('data-desligado'),",
    "    visivel_enquanto_emite: ecra.ver(),",
    "  };",
    "  await act(async () => { resolver({ data: EMITIDA }); });",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 5) a intenção sobrevive à retentativa -------------------------------
    "{",
    "  let falhar = true;",
    "  const ecra = await abrir(comBase({",
    "    'POST /pos/documentos/doc-1/nota-credito': () => {",
    "      if (falhar) { falhar = false; const e = new Error('Network Error'); throw e; }",
    "      return { data: EMITIDA };",
    "    },",
    "  }));",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-motivo'), 'Fruta trocada.'); });",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-devolucao'), 't-nu'); });",
    "  await act(async () => { botaoDe(ecra.alvo, 'Emitir Nota de Crédito').click(); });",
    "  await act(async () => {});",
    # Entre as duas tentativas a operadora MEXE no ecrã — corrige o motivo,
    # que é o gesto normal depois de uma recusa. É o que obriga o React a
    # refazer o `emitir`, e é por isso que este cenário vê a intenção: um
    # valor calculado a cada render sobrevive a re-renders que reaproveitem o
    # mesmo callback, e só se denuncia quando o callback é refeito.
    "  await act(async () => {",
    "    escrever(ecra.alvo.querySelector('#nc-motivo'), 'Fruta trocada — segunda tentativa.');",
    "  });",
    "  await act(async () => { botaoDe(ecra.alvo, 'Emitir Nota de Crédito').click(); });",
    "  await act(async () => {});",
    "  const emitidos = pedidos.filter(",
    "    (p) => p.metodo === 'post' && p.url.endsWith('/nota-credito'));",
    "  saida.intencoes = emitidos.map((p) => p.corpo.intencao_id);",
    "  saida.motivos = emitidos.map((p) => p.corpo.motivo);",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 6) a linha já creditada, e as notas anteriores ----------------------
    "{",
    "  const ecra = await abrir(comBase());",
    "  const caixaMorta = porRotulo(ecra.alvo, 'Creditar Coca-Cola');",
    "  const campoMorto = porRotulo(ecra.alvo, 'Quantidade a creditar de Coca-Cola');",
    "  saida.ja_creditada = {",
    "    caixa_desligada: caixaMorta.disabled,",
    "    campo_desligado: campoMorto.disabled,",
    "    visivel: ecra.ver(),",
    "  };",
    "  await ecra.fechar();",
    "}",
    "",
    # --- 7) a nota emitida ---------------------------------------------------
    "async function emitir(resposta) {",
    "  const ecra = await abrir(comBase({",
    "    'POST /pos/documentos/doc-1/nota-credito': () => ({ data: resposta }),",
    "  }));",
    "  porRotulo(ecra.alvo, 'Creditar Açaí Regular').click();",
    "  await act(async () => {});",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-motivo'), 'Fruta trocada.'); });",
    "  await act(async () => { escrever(ecra.alvo.querySelector('#nc-devolucao'), 't-nu'); });",
    "  await act(async () => { botaoDe(ecra.alvo, 'Emitir Nota de Crédito').click(); });",
    "  await act(async () => {});",
    "  const visto = ecra.ver();",
    "  await ecra.fechar();",
    "  return visto;",
    "}",
    "saida.emitida_dinheiro = await emitir(EMITIDA);",
    "saida.emitida_glovo = await emitir(Object.assign({}, EMITIDA, {",
    "  devolucao: { tipo_pagamento_id: 't-glovo', nome: 'Glovo',",
    "               tipo_fiscal: 'OU', valor: 9.85 } }));",
    "saida.emitida_divergente = await emitir(Object.assign({}, EMITIDA, {",
    "  total: 9.85, total_das_linhas: 9.86, total_divergente: true }));",
    "",
    # --- 8) o dinheiro vem do servidor --------------------------------------
    "{",
    "  const ecra = await abrir(comBase({",
    "    '/pos/documentos/doc-1/nota-credito/pre-visualizar': () => ({ data: RESUMO_ZERO }),",
    "  }));",
    "  saida.dinheiro_do_servidor_zero = ecra.ver();",
    "  await ecra.fechar();",
    "}",
    "",
    "process.stdout.write(JSON.stringify(saida));",
])


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    """Todos os cenários, num só arranque de Node. As afirmações que se seguem
    são leituras baratas sobre este resultado."""
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _GUIAO,
        tmp_path_factory.mktemp("nc"), "montar-nota-credito.js",
    )


# --- 1. A faixa que diz se sai ou não dinheiro da gaveta ---------------------

_FAIXA_DINHEIRO = (
    "Sai da gaveta — entregue o dinheiro ao cliente. O fecho desta caixa já "
    "conta com esta devolução."
)
_FAIXA_GLOVO = "Fica registada em Glovo — não tire dinheiro da gaveta."


def test_com_a_devolucao_em_DINHEIRO_a_operadora_LE_que_sai_da_gaveta(ecra):
    """A única instrução que separa a gaveta certa da gaveta errada, e as
    palavras do dono: «se a nota de crédito estiver lá que a devolução foi em
    dinheiro, sim sai da gaveta»."""
    assert _FAIXA_DINHEIRO in ecra["meio_dinheiro"]


def test_com_a_devolucao_no_GLOVO_a_faixa_diz_o_CONTRARIO(ecra):
    """E não pode dizer «sai da gaveta»: uma faixa que mentisse aqui mandava a
    operadora tirar 9,85 € da gaveta por uma devolução que nunca lhe tocou —
    e a gaveta fechava a menos todas as noites."""
    assert _FAIXA_GLOVO in ecra["meio_glovo"]
    assert "Sai da gaveta" not in ecra["meio_glovo"]


def test_a_faixa_da_gaveta_MUDA_com_o_meio_escolhido(ecra):
    """A prova de que a faixa é uma decisão e não um texto fixo."""
    assert ecra["meio_dinheiro"] != ecra["meio_glovo"]


def test_depois_de_emitir_a_faixa_da_gaveta_continua_a_dizer_o_que_fazer(ecra):
    """O ecrã do «emitida» é o que a operadora tem à frente com o dinheiro na
    mão — é aí que a instrução conta mesmo."""
    assert _FAIXA_DINHEIRO in ecra["emitida_dinheiro"]
    assert _FAIXA_GLOVO in ecra["emitida_glovo"]
    assert "Sai da gaveta" not in ecra["emitida_glovo"]


# --- 2. O tecto da quantidade ------------------------------------------------


def test_a_quantidade_escrita_ACIMA_do_que_a_linha_tem_e_presa_ao_tecto(ecra):
    """A linha tem 2 por creditar e a operadora escreve 5. O campo mostra 2 —
    e, o que interessa mesmo, é 2 que sai no pedido: sem o tecto, o servidor
    recusava com o cliente à frente, ou (pior) a operadora ficava a acreditar
    que ia devolver cinco açaís."""
    assert ecra["tecto"]["no_campo"] == "2"
    assert ecra["tecto"]["ultimo_pedido"] == {
        "linhas": [{"indice": 1, "quantidade": 2}]
    }


# --- 3. O que impede o toque -------------------------------------------------

_SEM_MOTIVO = (
    "Escreva o motivo: a lei obriga a que a nota de crédito diga porque é que "
    "corrige a fatura, e é isso que sai impresso."
)
_SEM_DEVOLUCAO = (
    "Escolha por onde é que o dinheiro volta ao cliente — é isso que decide se "
    "sai da gaveta ou do outro meio."
)


def test_SEM_MOTIVO_o_botao_de_emitir_esta_desligado_e_diz_porque(ecra):
    """O motivo não é uma formalidade nossa: a lei obriga a nota de crédito a
    dizer o que rectifica e porquê, e a API do Vendus recusa o documento sem
    ele. Sem esta recusa a operadora levava um 422 do servidor depois de
    carregar, com o cliente à frente."""
    assert ecra["sem_motivo"]["desligado"] == "sim"
    assert _SEM_MOTIVO in ecra["sem_motivo"]["visivel"]


def test_SEM_MEIO_DE_DEVOLUCAO_o_botao_de_emitir_esta_desligado_e_diz_porque(ecra):
    assert ecra["sem_meio"]["desligado"] == "sim"
    assert _SEM_DEVOLUCAO in ecra["sem_meio"]["visivel"]


def test_COM_TUDO_ESCOLHIDO_o_botao_liga_e_avisa_do_que_vai_fazer(ecra):
    """O controlo dos dois de cima: sem ele, um botão desligado para sempre
    passava por «a recusa funciona»."""
    assert ecra["pronto"]["desligado"] == "nao"
    assert _SEM_MOTIVO not in ecra["pronto"]["visivel"]
    assert _SEM_DEVOLUCAO not in ecra["pronto"]["visivel"]
    assert (
        "Emite um documento fiscal REAL, entregue à Autoridade Tributária."
        in ecra["pronto"]["visivel"]
    )


# --- 4. O travão do duplo toque ----------------------------------------------


def test_DOIS_TOQUES_no_mesmo_instante_emitem_UMA_nota_so(ecra):
    """A janela que um travão feito de ESTADO não fecha: os dois toques correm
    antes de o React voltar a desenhar, e os dois vêem o mesmo `aEmitir` a
    `false` fechado no callback. Sem a tranca lida no próprio instante do
    toque saíam DOIS `POST` — o segundo voltava 409 «esta nota já está a ser
    emitida» e pintava de vermelho um ecrã em que a nota SAIU."""
    assert ecra["duplo_toque"]["emissoes_depois_de_dois_toques"] == 1


def test_ENQUANTO_EMITE_o_botao_fica_desligado_e_a_operadora_LE_porque(ecra):
    """O outro travão, o que se vê: com o Vendus a demorar, o dedo volta ao
    botão sozinho."""
    assert ecra["duplo_toque"]["desligado_enquanto_emite"] == "sim"
    assert (
        "A emitir a nota de crédito… não carregue outra vez."
        in ecra["duplo_toque"]["visivel_enquanto_emite"]
    )


# --- 5. A intenção -----------------------------------------------------------


def test_a_RETENTATIVA_leva_a_MESMA_intencao_da_primeira_tentativa(ecra):
    """**O gatilho da corrida que punha duas notas reais na AT.** A intenção
    nasce com a janela e não muda enquanto ela estiver aberta: é ela que o
    servidor usa como reserva atómica, e é o que faz a segunda tentativa do
    mesmo toque ser o MESMO toque. Uma intenção nova a cada render (trocar o
    `useRef` por um valor calculado) fazia da retentativa uma nota de crédito
    NOVA — dois documentos fiscais reais a devolver o mesmo dinheiro."""
    assert len(ecra["intencoes"]) == 2
    assert ecra["intencoes"][0] == ecra["intencoes"][1]
    # E o motivo MUDOU entre as duas — a prova de que a segunda tentativa é
    # mesmo outra passagem pelo ecrã, e não a mesma chamada contada duas
    # vezes.
    assert ecra["motivos"] == [
        "Fruta trocada.", "Fruta trocada — segunda tentativa."]


def test_a_intencao_tem_a_FORMA_de_um_uuid(ecra):
    """O servidor valida-a como UUID: um identificador fora do formato podia
    colidir com a intenção de outra loja, e a resposta idempotente devolvia
    uma nota de crédito que não era dela."""
    import uuid

    uuid.UUID(ecra["intencoes"][0])


# --- 6. A linha já creditada, e as notas anteriores --------------------------


def test_uma_linha_JA_CREDITADA_nao_se_volta_a_marcar_e_diz_porque(ecra):
    """Fica na lista — some-la fazia a operadora procurar o artigo que o
    cliente traz na mão, não o encontrar, e concluir que a fatura não era
    aquela — mas com a caixa morta e o porquê à vista."""
    assert ecra["ja_creditada"]["caixa_desligada"] is True
    assert ecra["ja_creditada"]["campo_desligado"] is True
    assert "Já creditado por inteiro numa nota anterior." in ecra["ja_creditada"]["visivel"]


def test_a_linha_que_AINDA_DA_continua_viva(ecra):
    """O controlo do de cima: um ecrã com tudo desligado passava por «a
    recusa funciona»."""
    assert "Açaí Regular" in ecra["ja_creditada"]["visivel"]
    assert ecra["pronto"]["desligado"] == "nao"


def test_as_NOTAS_ANTERIORES_desta_fatura_estao_a_vista(ecra):
    """A operadora tem de saber que o cliente já cá veio, e com que documento
    — senão credita a fatura outra vez e leva com a recusa do servidor sem
    perceber de onde vem."""
    visivel = ecra["ja_creditada"]["visivel"]
    assert "Esta fatura já foi creditada" in visivel
    assert "NC 05P2026/7" in visivel


def test_uma_nota_anterior_POR_APURAR_grita_o_estado_dela(ecra):
    """Uma nota cuja emissão ficou por apurar pode ter saído mesmo. É a única
    forma de alguém ir ver o que aconteceu."""
    assert "POR CONFIRMAR NO VENDUS" in ecra["ja_creditada"]["visivel"]


# --- 7. O total divergente ---------------------------------------------------


def test_o_TOTAL_DIVERGENTE_pinta_o_ecra_e_manda_NAO_devolver(ecra):
    """O `total` do documento é o que a AT tem; o `total_das_linhas` é o que
    este servidor somou. Quando divergem, alguém tem de saber ANTES de abrir a
    gaveta."""
    visivel = ecra["emitida_divergente"]
    assert "O total desta nota não bate com a soma das linhas." in visivel
    assert "Não devolva nada ao cliente sem falar com o gestor." in visivel
    assert "9,85" in visivel and "9,86" in visivel


def test_sem_divergencia_esse_aviso_NAO_aparece(ecra):
    """O controlo: um aviso que estivesse sempre lá não era aviso nenhum."""
    assert "O total desta nota não bate" not in ecra["emitida_dinheiro"]


# --- 8. O dinheiro vem do servidor -------------------------------------------


def test_o_TOTAL_do_ecra_e_o_que_o_SERVIDOR_somou(ecra):
    """Nem uma soma neste ecrã. O subtotal de 8,72 € não aparece em linha
    nenhuma da fatura — só o servidor o sabe — e é ele que o ecrã mostra. Com
    o servidor a responder zero, o ecrã diz zero mesmo com uma linha
    marcada."""
    assert "Subtotal € 8,72" in ecra["pronto"]["visivel"]
    assert "Subtotal € 0,00" in ecra["dinheiro_do_servidor_zero"]
    assert "8,72" not in ecra["dinheiro_do_servidor_zero"]
    assert (
        "Somado pelo servidor, em cêntimos — é o valor que vai na nota de "
        "crédito entregue à Autoridade Tributária."
        in ecra["pronto"]["visivel"]
    )


def test_o_MAPA_DE_IMPOSTO_das_linhas_escolhidas_vem_do_servidor(ecra):
    """A tabela Taxa · Base · IVA · Total, e o convite quando não há nada
    escolhido."""
    assert "13% € 8,72 € 1,13 € 9,85" in ecra["pronto"]["visivel"]
    assert (
        "Marque os artigos para ver o imposto a devolver."
        in ecra["dinheiro_do_servidor_zero"]
    )


# --- 9. A devolução confrontada com o que a fatura recebeu -------------------


def test_a_operadora_LE_como_a_fatura_foi_paga(ecra):
    """Sem estes números, a escolha do meio da devolução era às cegas — e o
    dono disse «a devolução segue o meio de pagamento»."""
    visivel = ecra["meio_dinheiro"]
    assert "Esta fatura foi paga assim" in visivel
    assert "Dinheiro € 5,00" in visivel
    assert "Multibanco € 6,29" in visivel


def test_devolver_MAIS_do_que_o_meio_recebeu_e_dito_em_euros(ecra):
    """A fatura recebeu 5,00 € em dinheiro e a devolução é de 9,85 €: saem
    4,85 € da gaveta que esta venda não pôs lá. Medido no servidor, sem este
    aviso: o esperado da gaveta caía de 55,00 para 45,15 €, abaixo do fundo
    inicial, sem uma palavra em lado nenhum."""
    assert (
        "Esta fatura só tem € 5,00 por devolver em Dinheiro e vai devolver "
        "€ 9,85: saem € 4,85 da gaveta que esta venda não pôs lá."
        in ecra["meio_dinheiro"]
    )


def test_um_meio_que_a_fatura_NUNCA_usou_avisa_pelo_valor_TODO(ecra):
    """A fatura não recebeu um cêntimo no Glovo — a devolução inteira está
    acima do que aquele meio recebeu."""
    assert (
        "Esta fatura só tem € 0,00 por devolver em Glovo e vai devolver "
        "€ 9,85: saem € 9,85 de Glovo que esta venda não pôs lá."
        in ecra["meio_glovo"]
    )


def test_quando_a_devolucao_CABE_no_meio_nao_ha_aviso_nenhum(ecra):
    """O controlo: a mesma fatura paga TODA em dinheiro, e a devolução de
    9,85 € cabe nos 11,29 € que a gaveta recebeu."""
    assert "Dinheiro € 11,29" in ecra["meio_que_chega"]
    assert "que esta venda não pôs lá" not in ecra["meio_que_chega"]
    # E a faixa da gaveta continua lá — o que desaparece é só o aviso.
    assert _FAIXA_DINHEIRO in ecra["meio_que_chega"]
