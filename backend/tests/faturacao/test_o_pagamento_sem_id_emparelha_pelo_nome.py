"""**Uma devolução perfeitamente coberta acendia os DOIS avisos.**

Uma fatura cujo pagamento não tem `tipo_pagamento_id` — um documento gravado
por uma versão anterior, ou trazido do Vendus por uma reconciliação — chega ao
ecrã da nota de crédito com o `nome` e sem o id.

`pagamentos_da_fatura` já se defende: a chave dela é
`tipo_pagamento_id or nome`, e por isso a linha existe e mostra o dinheiro
certo. O que ela guarda no campo, porém, é o id como veio: `None`. E quem
emparelha depois — `acima_do_recebido` no servidor e
`avisoDoMeioDeDevolucaoPos` no ecrã — comparava **só por id**.

Medido: fatura paga `{nome: Dinheiro, tipo_fiscal: NU, valor: 20,40}` **sem
id**, a operadora escolhe devolver 10,20 € em **Dinheiro**:

- `acima_do_recebido` = **10,20** (a devolução inteira dada como descoberta),
  gravado no documento fiscal e lido pelo Ponto de Caixa e pelo Z
  (`caixa_math.devolucoes_acima_do_recebido`) — 10,20 € de acusação por
  escrito, sobre uma devolução que a fatura cobre com folga;
- e o ecrã pinta a **caixa vermelha** antes do toque: «Esta fatura só tem
  € 0,00 por devolver em Dinheiro e vai devolver € 10,20».

`caixa_math.por_tipo_de_pagamento` já trata este caso pela chave
`tipo_pagamento_id or nome` — logo é alcançável, e não uma hipótese.

**A regra do emparelhamento, dita por extenso.** Uma linha COM id casa pelo
id, e só por ele: dois tipos de pagamento diferentes podem partilhar o nome, e
o id é a resposta exacta. Uma linha SEM id casa pelo NOME (aparado e sem
distinguir maiúsculas), porque não há mais nada com que a casar — é a mesma
escolha que `pagamentos_da_fatura` e `por_tipo_de_pagamento` já fazem na
chave, agora dita uma vez e usada nos três sítios.
"""
import json

import pytest

from faturacao.nota_credito import acima_do_recebido, pagamentos_da_fatura

from .test_a_faixa_do_modo_no_ecra import _correr_no_node, _montar_no_node
from .test_arredondamento_do_ecra import (
    _LIB_POS,
    _corpo_da_funcao,
    _corpo_da_seta,
    _ler,
)

_DINHEIRO = {"id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU"}
_GLOVO = {"id": "t-glovo", "nome": "Glovo", "tipo_fiscal": "OU"}

# A fatura de 20,40 € paga em dinheiro — **sem `tipo_pagamento_id`**.
_SEM_ID = {"pagamentos": [
    {"nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 20.40}]}
# A mesma, com o id — o controlo.
_COM_ID = {"pagamentos": [
    {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
     "valor": 20.40}]}


# --- O servidor ----------------------------------------------------------------


def test_a_linha_da_fatura_sem_id_ja_mostrava_o_dinheiro_certo():
    """`pagamentos_da_fatura` nunca teve este defeito — é o que torna o resto
    surpreendente. A linha existe, com 20,40 € por devolver, e o id a `None`."""
    linhas = pagamentos_da_fatura(_SEM_ID, [])
    assert len(linhas) == 1
    assert linhas[0]["nome"] == "Dinheiro"
    assert linhas[0]["tipo_pagamento_id"] is None
    assert linhas[0]["disponivel"] == 20.40


def test_uma_devolucao_COBERTA_deixa_de_ser_gravada_como_descoberta():
    """**O defeito.** 10,20 € devolvidos em dinheiro sobre uma fatura que
    recebeu 20,40 € em dinheiro: nada está acima do recebido.

    O número não morre no ecrã — é gravado em `devolucao.acima_do_recebido`,
    entra no Z pelo `caixa_math.devolucoes_acima_do_recebido`, e fica lá para o
    gestor o encontrar dias depois."""
    assert acima_do_recebido(
        pagamentos_da_fatura(_SEM_ID, []), _DINHEIRO, 10.20) == 0.0


def test_com_id_continua_a_dar_o_que_dava():
    """O controlo do caminho normal."""
    assert acima_do_recebido(
        pagamentos_da_fatura(_COM_ID, []), _DINHEIRO, 10.20) == 0.0


@pytest.mark.parametrize("venda", [_SEM_ID, _COM_ID])
def test_um_meio_que_a_fatura_NAO_usou_continua_descoberto(venda):
    """E é isto que impede a correcção de ser «nunca avisar»: devolver 10,20 €
    pelo Glovo numa fatura paga em dinheiro continua a ser 10,20 € por um meio
    que aquela venda não recebeu."""
    assert acima_do_recebido(
        pagamentos_da_fatura(venda, []), _GLOVO, 10.20) == 10.20


def test_dois_pagamentos_sem_id_distinguem_se_pelo_NOME():
    """A fatura de 11,29 € paga 5,00 em dinheiro + 6,29 em Multibanco, os dois
    sem id. Devolver 10,20 € em dinheiro passa os 5,00 € que a gaveta recebeu
    — e o número certo é 5,20, não 10,20 nem 0,00."""
    venda = {"pagamentos": [
        {"nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 5.00},
        {"nome": "Multibanco", "tipo_fiscal": "CD", "valor": 6.29},
    ]}
    assert acima_do_recebido(
        pagamentos_da_fatura(venda, []), _DINHEIRO, 10.20) == 5.20


def test_o_nome_casa_aparado_e_sem_distinguir_maiusculas():
    """Um nome que veio do Vendus com um espaço a mais ou noutra caixa é o
    mesmo meio de pagamento — e o contrário mandava a operadora justificar uma
    devolução coberta por causa de um espaço."""
    venda = {"pagamentos": [
        {"nome": " dinheiro ", "tipo_fiscal": "NU", "valor": 20.40}]}
    assert acima_do_recebido(
        pagamentos_da_fatura(venda, []), _DINHEIRO, 10.20) == 0.0


def test_uma_linha_sem_id_E_sem_nome_nao_casa_com_nada():
    """Duas ausências não fazem uma identidade: uma linha sem id e sem nome não
    pode absorver a devolução de um meio qualquer só por ser a única lá."""
    venda = {"pagamentos": [{"tipo_fiscal": "NU", "valor": 20.40}]}
    assert acima_do_recebido(
        pagamentos_da_fatura(venda, []), _DINHEIRO, 10.20) == 10.20


def test_uma_devolucao_ANTERIOR_sem_id_desconta_do_mesmo_meio():
    """O outro lado da mesma chave: a nota anterior de 10,20 € gravada sem id
    tem de descontar do dinheiro, senão a segunda devolução volta a parecer
    coberta quando já não está."""
    nota = {"estado": "emitida", "devolucao": {
        "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 10.20}}
    linhas = pagamentos_da_fatura(_SEM_ID, [nota])
    assert len(linhas) == 1 and linhas[0]["disponivel"] == 10.20
    assert acima_do_recebido(linhas, _DINHEIRO, 10.20) == 0.0
    assert acima_do_recebido(linhas, _DINHEIRO, 11.35) == 1.15


# --- O ecrã: a mesma regra, corrida em Node ------------------------------------


def _aviso(tipo, pagamentos, total, tmp_path, nome):
    """Corre `avisoDoMeioDeDevolucaoPos` como ele está escrito no `lib/pos.js`
    — nunca uma cópia aqui, que ficava verde no dia em que o ecrã mudasse."""
    lib = _ler(_LIB_POS)
    guiao = "\n".join([
        _corpo_da_funcao(lib, "export const numeroPos = (valor) =>", _LIB_POS)
        .replace("export ", "", 1),
        _corpo_da_seta(lib, "export const eurosPos = (valor) =>", _LIB_POS)
        .replace("export ", "", 1),
        _corpo_da_funcao(
            lib, "export const avisoDoMeioDeDevolucaoPos = ({ tipo, pagamentos, total }) =>",
            _LIB_POS).replace("export ", "", 1),
        "process.stdout.write(JSON.stringify(avisoDoMeioDeDevolucaoPos({",
        "  tipo: %s, pagamentos: %s, total: %s })));" % (
            json.dumps(tipo), json.dumps(pagamentos), json.dumps(total)),
    ])
    return _correr_no_node(guiao, tmp_path, nome)


def test_o_ECRA_deixa_de_pintar_a_caixa_vermelha_sobre_uma_devolucao_coberta(tmp_path):
    """A metade do defeito que a operadora vê: a caixa vermelha «Esta fatura só
    tem € 0,00 por devolver em Dinheiro» antes de ela tocar em nada."""
    assert _aviso(_DINHEIRO, pagamentos_da_fatura(_SEM_ID, []), 10.20,
                  tmp_path, "aviso-coberta.js") is None


def test_o_ECRA_continua_a_avisar_quando_o_meio_nao_chega(tmp_path):
    """O controlo: o Glovo numa fatura paga em dinheiro continua a acender."""
    aviso = _aviso(_GLOVO, pagamentos_da_fatura(_SEM_ID, []), 10.20,
                   tmp_path, "aviso-glovo.js")
    assert aviso is not None
    assert "€ 10,20" in aviso


def test_o_ECRA_e_o_SERVIDOR_dao_a_mesma_resposta(tmp_path):
    """Os dois emparelham a mesma coisa, e a divergência aparecia ao balcão:
    um ecrã calado sobre uma devolução que o servidor grava como descoberta (ou
    o contrário) é a pior das duas leituras."""
    for tipo, total, nome in ((_DINHEIRO, 10.20, "par-1"),
                              (_DINHEIRO, 25.00, "par-2"),
                              (_GLOVO, 10.20, "par-3")):
        pagamentos = pagamentos_da_fatura(_SEM_ID, [])
        do_servidor = acima_do_recebido(pagamentos, tipo, total)
        do_ecra = _aviso(tipo, pagamentos, total, tmp_path, nome + ".js")
        assert (do_servidor > 0) == (do_ecra is not None), (
            "O servidor diz %s e o ecrã diz %r (tipo %s, total %s)"
            % (do_servidor, do_ecra, tipo["nome"], total))


# --- E o ecrã da nota de crédito, MONTADO --------------------------------------

_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled, type: 'button',",
    "  'aria-label': props['aria-label'],",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  id: props.id, type: props.type || 'text',",
    "  'aria-label': props['aria-label'],",
    "  value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, disabled: props.disabled,",
    "});",
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'Input') return Campo;",
    "  return Div;",
    "} });",
])

# A preparação que o servidor manda para esta fatura: um pagamento em dinheiro
# de 20,40 € **sem id**, e uma linha de 10,20 € para creditar.
_PREPARACAO = {
    "documento": {"id": "doc-1", "numero": "FS 05P2026/1824",
                  "atcud": "JFT7-1824", "tipo": "FS", "modo": "normal",
                  "emitido_em": "2026-08-22T11:12:00", "total": 20.40},
    "cliente_nif": None,
    "pagamentos": [{"tipo_pagamento_id": None, "nome": "Dinheiro",
                    "tipo_fiscal": "NU", "recebido": 20.40, "devolvido": 0.0,
                    "disponivel": 20.40}],
    "linhas": [{"indice": 1, "titulo": "Açaí Regular", "tax_id": "INT",
                "quantidade": 1, "creditado": 0, "disponivel": 1,
                "por_apurar": 0, "preco_unitario": 10.20,
                "desconto_percentagem": None, "total": 10.20}],
    "notas_anteriores": [],
}
_TIPOS = [dict(_DINHEIRO, pronto=True), dict(_GLOVO, pronto=True)]
_RESUMO = {"linhas": [], "subtotal": 9.03, "total": 10.20,
           "mapa_imposto": [{"tax_id": "INT", "taxa": 13, "documentos": 1,
                             "base": 9.03, "iva": 1.17, "total": 10.20}],
           "totais_imposto": {"base": 9.03, "iva": 1.17, "total": 10.20}}


@pytest.fixture(scope="module")
def ecra_da_nota(tmp_path_factory):
    guiao = "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        "const PosNotaCredito = carregar("
        "path2.join(POS, 'PosNotaCredito.js')).default;",
        "function escrever(el, valor) {",
        "  const proto = el.tagName === 'SELECT'",
        "    ? dom.window.HTMLSelectElement.prototype",
        "    : dom.window.HTMLInputElement.prototype;",
        "  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, valor);",
        "  el.dispatchEvent(new dom.window.Event(",
        "    el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));",
        "}",
        "RESPOSTAS_POS['GET /pos/documentos/doc-1/nota-credito'] = () => ({ data: %s });"
        % json.dumps(_PREPARACAO, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/tipos-pagamento'] = () => ({ data: %s });"
        % json.dumps(_TIPOS, ensure_ascii=False),
        "RESPOSTAS_POS['/pos/documentos/doc-1/nota-credito/pre-visualizar'] ="
        " () => ({ data: %s });" % json.dumps(_RESUMO, ensure_ascii=False),
        "const saida = {};",
        "async function escolher(idDoTipo) {",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(",
        "    PosNotaCredito, { documento: { id: 'doc-1' }, caixaId: 'caixa-1',",
        "      onFechar: () => {}, onEmitida: () => {} })); });",
        "  await act(async () => {});",
        "  alvo.querySelector('[aria-label=\"Creditar Açaí Regular\"]').click();",
        "  await act(async () => {});",
        "  await act(async () => {",
        "    escrever(alvo.querySelector('#nc-devolucao'), idDoTipo); });",
        "  await act(async () => {});",
        "  const visto = textoVisivel(alvo);",
        "  await act(async () => { raiz.unmount(); });",
        "  alvo.innerHTML = '';",
        "  return visto;",
        "}",
        "saida.dinheiro = await escolher('t-nu');",
        "saida.glovo = await escolher('t-glovo');",
        "process.stdout.write(JSON.stringify(saida));",
    ])
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % guiao, tmp_path_factory.mktemp("nc-sem-id"), "montar-nc.js")


def test_o_ecra_da_nota_esta_mesmo_montado(ecra_da_nota):
    for nome in ("dinheiro", "glovo"):
        assert "Açaí Regular" in ecra_da_nota[nome]
        assert "€ 10,20" in ecra_da_nota[nome]


def test_a_devolucao_COBERTA_nao_pinta_nada_de_vermelho(ecra_da_nota):
    """**O ecrã, montado.** A fatura recebeu 20,40 € em dinheiro (sem id) e a
    operadora escolhe devolver 10,20 € em dinheiro: não há aviso nenhum para
    ler."""
    lido = ecra_da_nota["dinheiro"]
    assert "por devolver em Dinheiro" not in lido, (
        "A caixa vermelha continua a acender sobre uma devolução que a fatura "
        "cobre com folga. O que ficou no ecrã: %r" % lido)
    assert "Sai da gaveta" in lido, (
        "Sem a frase do efeito na gaveta não é este ecrã que está montado.")


def test_o_meio_que_a_fatura_NAO_recebeu_continua_a_acender(ecra_da_nota):
    """O controlo, no ecrã: escolher o Glovo sobre a mesma fatura acende."""
    assert "por devolver em Glovo" in ecra_da_nota["glovo"]
