"""**Uma sangria mal digitada assinava uma gaveta VAZIA como SOBRA.**

Medido nas funções reais do fecho:

    esperado(fundo 50,00 · vendas 24,14 · saída 100,00) = −25,86
    diferenca(−25,86 · contado 0,00)                    = +25,86

e no Z montado lia-se «Deve estar na gaveta **€ -25,86** … Contado na gaveta
€ 0,00 … Diferença **+ € 25,86**». Com 1000,00 em vez de 100,00, a gaveta vazia
fecha com uma SOBRA de 925,86 € — e o Z sai assinado.

`PedidoMovimento.valor` só exigia `gt=0` e 2 casas: sem tecto, sem confirmação,
e com o motivo em texto livre. Num depósito diário, 300 em vez de 30 chega.

**A regra que se escolheu: um turno não pode tirar da gaveta mais do que está
lá dentro.** É a única que sai de um facto do próprio turno e não de um número
inventado — não há tecto em euros (o depósito legítimo de uma sexta-feira é
maior do que o de uma terça, e um tecto configurável é uma configuração que
ninguém mantém e que, no dia em que estorva, se levanta), e não há segundo par
de olhos (é UM PC e UMA operadora por loja: a segunda pessoa não existe).

E é a regra que fecha o defeito pela raiz: o `esperado` da gaveta deixa de
poder descer abaixo de zero por causa de um movimento, e por isso a
`diferenca` de uma gaveta vazia deixa de poder ser positiva.

**O que a regra NÃO cobre, dito por extenso:** o `esperado` ainda pode ficar
negativo por uma DEVOLUÇÃO em dinheiro maior do que as vendas do turno (uma
nota de crédito é um documento fiscal e não se recusa por causa da gaveta —
ver `nota_credito.pagamentos_da_fatura`). Esse caminho tem aviso próprio no
ecrã (`tirado_da_gaveta_a_mais`), e ganha aqui uma segunda frase no resumo do
turno, que é o guarda `test_o_z_nao_le_uma_gaveta_negativa_como_sobra`.
"""
import json

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao.caixa import (
    PedidoFecharCaixa,
    PedidoMovimento,
    fechar_caixa,
    registar_movimento,
)
from faturacao.caixa_math import acima_do_que_ha_na_gaveta, diferenca, esperado
from faturacao.db import COLECOES

from .test_a_faixa_do_modo_no_ecra import _montar_no_node
from .test_venda import (  # noqa: F401
    _caixa,
    _corre,
    _db,
    _linha,
    _operador,
    _produto,
    _sessao,
    _venda,
)


# --- A aritmética, pura e em cêntimos inteiros --------------------------------


def test_o_defeito_reproduzido_nas_funcoes_do_fecho():
    """A reprodução exacta, antes de qualquer correcção: as duas funções do
    fecho continuam a dar o que davam — é o MOVIMENTO que deixa de existir."""
    esperado_valor = esperado(50.00, 24.14, [{"tipo": "saida", "valor": 100.00}])
    assert esperado_valor == -25.86
    assert diferenca(esperado_valor, 0.00) == 25.86


@pytest.mark.parametrize(
    "na_gaveta,saida,acima",
    [
        # A sangria da reprodução: 74,14 na gaveta, 100,00 a sair.
        (74.14, 100.00, 25.86),
        # O zero a mais do depósito diário: 300,00 em vez de 30,00.
        (74.14, 300.00, 225.86),
        # Cabe à justa — o depósito de tudo o que lá está.
        (74.14, 74.14, 0.0),
        (74.14, 74.13, 0.0),
        # Um cêntimo a mais é um cêntimo a mais.
        (74.14, 74.15, 0.01),
        # Uma gaveta já negativa (só uma devolução lá chega) não deixa sair
        # nada.
        (-15.40, 0.29, 15.69),
        # Os valores que expõem o cêntimo, somados em inteiros: 0,29 + 1,15 +
        # 10,20 = 11,64, e não 11,639999999999999.
        (11.64, 11.64, 0.0),
    ],
)
def test_quanto_e_que_uma_saida_passa_o_que_esta_na_gaveta(na_gaveta, saida, acima):
    assert acima_do_que_ha_na_gaveta(na_gaveta, saida) == acima


# --- A rota: a saída que não cabe é RECUSADA ----------------------------------


def _venda_em_dinheiro():
    """24,14 € cobrados em dinheiro — 10,20 × 2 + 0,29 + 1,15 × 3."""
    v = _venda(
        id="paga", estado="emitida",
        linhas=[
            _linha(id="l1", produto_nome="Açaí Regular", produto_preco=10.20,
                   produto_tax_id="INT", quantidade=2),
            _linha(id="l2", produto_nome="Água", produto_preco=0.29,
                   produto_tax_id="INT"),
            _linha(id="l3", produto_nome="Coca-Cola", produto_preco=1.15,
                   produto_tax_id="NOR", quantidade=3),
        ],
        criada_em="2026-08-21T10:00:00+00:00",
    )
    v["pagamentos"] = [{
        "tipo_pagamento_id": "tp-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
        "valor": 24.14,
    }]
    return v


def _monta(monkeypatch, vendas=None):
    db = _db(
        [], caixas=[_caixa()], sessoes=[_sessao()],
        vendas=[_venda_em_dinheiro()] if vendas is None else vendas,
        produtos=[_produto()], refs=[],
    )
    db[COLECOES["movimentos_caixa"]]  # `DbFalsa.__getitem__` cria-a vazia
    db[COLECOES["notas_credito"]]
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    async def _sem_vendus(_db, _sessao, _valor):
        return {"nao_verificado": "desligado no teste"}
    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", _sem_vendus)
    return db


def _saida(valor, motivo="Depósito no cofre"):
    return PedidoMovimento(
        caixa_id="caixa-1", tipo="saida", valor=valor, motivo=motivo)


def test_a_saida_maior_do_que_a_gaveta_e_RECUSADA(monkeypatch):
    """**O defeito.** 74,14 € na gaveta (fundo 50,00 + vendas 24,14) e uma
    saída de 100,00 € — o `100` onde ia `10,00`. Isto entrava sem uma
    pergunta."""
    db = _monta(monkeypatch)

    with pytest.raises(HTTPException) as erro:
        _corre(registar_movimento(_saida(100.00), operador=_operador()))

    assert erro.value.status_code == 409
    assert db[COLECOES["movimentos_caixa"]]._documentos == [], (
        "A saída recusada deixou uma linha na colecção — e uma linha `por "
        "confirmar` que ninguém apague volta a ser dinheiro no dia em que "
        "alguém mude o filtro.")


def test_a_recusa_DIZ_os_dois_numeros_e_o_que_esta_em_jogo(monkeypatch):
    """Uma recusa que só diga «não é possível» manda a operadora tentar outra
    vez com o mesmo valor. Ela tem de ler quanto há, quanto pediu, e porque é
    que isto interessa."""
    _monta(monkeypatch)

    with pytest.raises(HTTPException) as erro:
        _corre(registar_movimento(_saida(100.00), operador=_operador()))

    mensagem = erro.value.detail
    assert "100.00 €" in mensagem, mensagem
    assert "74.14 €" in mensagem, mensagem
    assert "25.86 €" in mensagem, mensagem
    assert "sobra" in mensagem.lower(), mensagem


def test_a_sangria_que_CABE_continua_a_passar(monkeypatch):
    """O controlo, e é ele que impede a regra de ser «recusar tudo»: o
    depósito de rotina de 30,00 € numa gaveta de 74,14 € entra como sempre
    entrou."""
    db = _monta(monkeypatch)

    resposta = _corre(registar_movimento(_saida(30.00), operador=_operador()))

    assert resposta["valor"] == 30.00
    guardado = db[COLECOES["movimentos_caixa"]]._documentos
    assert len(guardado) == 1 and guardado[0]["por_confirmar"] is False


def test_a_gaveta_INTEIRA_ainda_se_pode_tirar(monkeypatch):
    """O limite é «o que lá está», e não «o que lá está menos qualquer
    coisa»: esvaziar a gaveta ao cêntimo é uma operação legítima (o fecho de
    uma loja que entrega tudo)."""
    _monta(monkeypatch)

    resposta = _corre(registar_movimento(_saida(74.14), operador=_operador()))

    assert resposta["valor"] == 74.14


def test_a_segunda_saida_conta_com_a_primeira(monkeypatch):
    """A gaveta que a regra lê é a de AGORA, movimentos já registados
    incluídos — senão duas sangrias de 50,00 € numa gaveta de 74,14 €
    passavam as duas e o defeito voltava pela porta do lado."""
    _monta(monkeypatch)

    _corre(registar_movimento(_saida(50.00), operador=_operador()))
    with pytest.raises(HTTPException) as erro:
        _corre(registar_movimento(_saida(50.00), operador=_operador()))

    assert "24.14 €" in erro.value.detail, erro.value.detail


def test_uma_ENTRADA_nunca_e_recusada_por_isto(monkeypatch):
    """A regra é sobre o que SAI. Um reforço de troco de 1000,00 € numa gaveta
    de 74,14 € é uma entrada estranha e continua a entrar: o que ela faz ao Z
    é acusar uma FALTA enorme, que é visível e obriga a explicar — o defeito
    era o contrário, uma gaveta vazia a parecer certa."""
    _monta(monkeypatch)

    resposta = _corre(registar_movimento(PedidoMovimento(
        caixa_id="caixa-1", tipo="entrada", valor=1000.00), operador=_operador()))

    assert resposta["valor"] == 1000.00


# --- E o Z que sai a seguir ----------------------------------------------------


def test_o_Z_deixa_de_poder_assinar_uma_GAVETA_VAZIA_como_SOBRA(monkeypatch):
    """O fim da linha do defeito: com a saída recusada, a gaveta contada a
    zero fecha com uma FALTA de 74,14 € — que é a verdade — em vez de uma
    sobra de 25,86 €."""
    _monta(monkeypatch)

    with pytest.raises(HTTPException):
        _corre(registar_movimento(_saida(100.00), operador=_operador()))

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=0.00), operador=_operador()))

    assert z["esperado"] == 74.14
    assert z["diferenca"] == -74.14
    assert z["saidas"] == 0.0


# --- O ecrã: a operadora LÊ o que está na gaveta antes de escrever a saída ----
#
# A recusa do servidor fecha o defeito; sozinha, porém, chega DEPOIS do toque —
# a operadora escreve 100,00, carrega, e leva um erro. O número que evita o
# engano é o que está na gaveta, e tem de estar à frente dela ENQUANTO escreve.
# Vem SOMADO do servidor (`GET /pos/caixa/ponto`), como todo o dinheiro deste
# POS: o browser não soma euros.

# A biblioteca de UI mínima que responde ao dedo. O `DropdownMenuItem` é um
# `<button>` que chama o `onSelect` — é assim que o de verdade se comporta ao
# toque, e sem ele ninguém abre o diálogo da saída.
_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled, type: 'button',",
    "}, props.children);",
    "const Item = (props) => React.createElement('button', {",
    "  onClick: props.onSelect, disabled: props.disabled, type: 'button',",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  id: props.id, value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "  disabled: props.disabled,",
    "});",
    "const Caixa = (props) => (props.open",
    "  ? React.createElement('div', { 'data-dialogo': 'aberto' }, props.children)",
    "  : null);",
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'DropdownMenuItem') return Item;",
    "  if (nome === 'Input') return Campo;",
    "  if (nome === 'Dialog') return Caixa;",
    "  return Div;",
    "} });",
])

# O Ponto de Caixa como o servidor o devolve, reduzido ao que este ecrã lê. O
# `esperado` é o número da gaveta — 74,14 € do cenário de cima.
_PONTO = {"esperado": 74.14, "fundo": 50.0, "vendas_dinheiro": 24.14,
          "entradas": 0.0, "saidas": 0.0}


def _guiao_do_menu() -> str:
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        # O campo do valor entra a sério: é ao lado dele que a frase da gaveta
        # tem de estar, e uma marca vazia deixava de o provar.
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosCampoValor.js'));",
        "const PosMenuCaixa = carregar(path2.join(POS, 'PosMenuCaixa.js')).default;",
        "const botaoDe = (alvo, texto) => Array.from(alvo.querySelectorAll('button'))",
        "  .find((b) => (b.textContent || '').includes(texto));",
        "const PONTO = %s;" % json.dumps(_PONTO),
        "const saida = {};",
        "async function abrir(nome, respostaDoPonto) {",
        "  for (const k of Object.keys(RESPOSTAS_POS)) delete RESPOSTAS_POS[k];",
        "  RESPOSTAS_POS['/pos/modo-de-emissao'] = () => ({ data: { modo: 'normal' } });",
        "  RESPOSTAS_POS['/pos/caixa/ponto'] = respostaDoPonto;",
        "  pedidos.length = 0;",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(PosMenuCaixa, {",
        "    operador: { nome: 'Rafaela' }, lojaNome: 'Loja do Guarda',",
        "    caixa: { id: 'caixa-1', nome: 'Balcão' }, sessao: { fundo: 50 },",
        "    onSair: () => {}, onFecharCaixa: () => {},",
        "    onMovimentoRegistado: () => {}, modo: 'normal',",
        "    onContaCopiada: () => {} })); });",
        "  await act(async () => {});",
        "  return { alvo, fim: async () => {",
        "    await act(async () => { raiz.unmount(); }); alvo.innerHTML = '';",
        "  } };",
        "}",
        "async function porta(nome, rotulo, respostaDoPonto) {",
        "  const ecra = await abrir(nome, respostaDoPonto);",
        "  await act(async () => { botaoDe(ecra.alvo, rotulo).click(); });",
        "  await act(async () => {});",
        "  saida[nome] = textoVisivel(ecra.alvo);",
        "  saida[nome + '/pedidos'] = pedidos.map((p) => p.url);",
        "  await ecra.fim();",
        "}",
        "await porta('saida', 'Saída de Dinheiro', () => ({ data: PONTO }));",
        "await porta('entrada', 'Entrada de Dinheiro', () => ({ data: PONTO }));",
        "await porta('saida_sem_resposta', 'Saída de Dinheiro',",
        "  () => { throw new Error('Network Error'); });",
        "await porta('saida_pendente', 'Saída de Dinheiro',",
        "  () => new Promise(() => {}));",
        "process.stdout.write(JSON.stringify(saida));",
    ])


@pytest.fixture(scope="module")
def menu(tmp_path_factory):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _guiao_do_menu(),
        tmp_path_factory.mktemp("sangria"), "montar-menu.js",
    )


def test_o_dialogo_da_SAIDA_esta_mesmo_aberto(menu):
    """A afirmação de identidade — sem ela os guardas a seguir mediam o
    vazio."""
    assert "Saída de Dinheiro" in menu["saida"]
    assert "Motivo" in menu["saida"]


def test_a_operadora_LE_quanto_esta_na_gaveta_antes_de_escrever(menu):
    """O número que evita o engano tem de estar à frente dela ENQUANTO
    escreve — não depois, num erro. E vem somado do servidor."""
    lido = menu["saida"]
    assert "Na gaveta estão € 74,14" in lido, (
        "A saída de dinheiro pede um valor sem dizer quanto lá está. O que "
        "ficou no ecrã: %r" % lido)
    assert "/pos/caixa/ponto" in " ".join(menu["saida/pedidos"]), (
        "O ecrã desenhou um número da gaveta sem o ir buscar ao servidor.")


def test_o_ecra_diz_que_o_servidor_RECUSA_o_que_nao_cabe(menu):
    """A regra dita antes do toque: sem isto, a recusa do servidor chega como
    uma avaria."""
    assert "recusa uma saída maior" in menu["saida"]


def test_a_ENTRADA_nao_pergunta_nem_promete_nada(menu):
    """O controlo. A regra é só sobre o que SAI, e um ecrã que dissesse o
    mesmo nos dois estava a desenhar a frase sem a condição."""
    assert "Na gaveta estão" not in menu["entrada"]
    assert "/pos/caixa/ponto" not in " ".join(menu["entrada/pedidos"])


def test_sem_resposta_do_servidor_o_ecra_DIZ_que_nao_sabe(menu):
    """Um número que não veio não se desenha como zero — nem se cala. «Não se
    sabe» e «está vazia» não podem ter o mesmo aspecto num ecrã que autoriza
    tirar dinheiro."""
    for nome in ("saida_sem_resposta", "saida_pendente"):
        lido = menu[nome]
        assert "não foi possível saber quanto está na gaveta" in lido.lower() \
            or "a ver quanto está na gaveta" in lido.lower(), (
            "Sem resposta do servidor, o diálogo da saída não diz nada sobre "
            "a gaveta (%s): %r" % (nome, lido))
        assert "Na gaveta estão €" not in lido


# --- E o Z, quando a gaveta fica negativa por outro caminho -------------------


def test_o_z_nao_le_uma_gaveta_negativa_como_sobra(monkeypatch, tmp_path):
    """**O caminho que a recusa da saída NÃO cobre.** Uma nota de crédito
    devolvida em dinheiro maior do que as vendas do turno põe o `esperado`
    negativo sem passar por movimento nenhum — e uma nota de crédito é um
    documento fiscal que não se recusa por causa da gaveta.

    Com o esperado a −25,86 € e a gaveta contada a zero, a diferença é
    +25,86 €: o mesmo desenho de uma sobra. O ecrã tem de o dizer."""
    resumo = caixa_mod._resumo_do_turno(
        {"id": "sessao-1", "fundo": 50.00}, [],
        [{"id": "v1", "estado": "emitida",
          "linhas": [{"id": "l1", "produto_nome": "Açaí Regular",
                      "produto_preco": 10.20, "produto_tax_id": "INT",
                      "quantidade": 2}],
          "pagamentos": [{"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                          "tipo_fiscal": "NU", "valor": 20.40}],
          "desconto_global_pct": None, "desconto_global_eur": None}],
        [{"estado": "emitida", "total": 96.26,
          "linhas": [{"indice": 1, "titulo": "Açaí Regular", "tax_id": "INT",
                      "quantidade": 1, "preco_unitario": 96.26,
                      "total": 96.26}],
          "devolucao": {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                        "tipo_fiscal": "NU", "valor": 96.26,
                        "acima_do_recebido": 75.86}}],
    )
    assert resumo["esperado"] == -25.86, resumo["esperado"]

    guiao = "\n".join([
        "const Div = (props) => React.createElement('div', null, props.children);",
        "global.__componentes = new Proxy({}, { get: (_, nome) => (",
        "  nome === '__esModule' ? true : Div) });",
        "const path2 = require('path');",
        "SUBSTITUIDOS.delete(path2.join(POS, 'PosResumoDoTurno.js'));",
        "const Resumo = carregar(path2.join(POS, 'PosResumoDoTurno.js')).default;",
        "const saida = {};",
        "saida.negativa = await montar(React.createElement(",
        "  Resumo, { resumo: %s }));" % json.dumps(resumo, ensure_ascii=False),
        "saida.normal = await montar(React.createElement(",
        "  Resumo, { resumo: Object.assign({}, %s, { esperado: 74.14 }) }));"
        % json.dumps(resumo, ensure_ascii=False),
        "process.stdout.write(JSON.stringify(saida));",
    ])
    ecra = _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % guiao, tmp_path, "gaveta-negativa.js")

    lido = ecra["negativa"]["visivel"]
    assert "Deve estar na gaveta € -25,86" in lido, lido
    assert "NÃO é sobra" in lido, (
        "O Z desenha um esperado NEGATIVO sem dizer que a diferença positiva "
        "que vem a seguir não é sobra nenhuma. O que ficou no ecrã: %r" % lido)
    assert "NÃO é sobra" not in ecra["normal"]["visivel"], (
        "A frase aparece com a gaveta em ordem — está desenhada sem condição.")
