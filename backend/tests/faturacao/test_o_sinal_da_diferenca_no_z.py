"""**A linha do Z que separa a falta da sobra — lida, não procurada.**

O Z tinha TRÊS convenções de sinal na mesma janela, e a que estava sozinha era
a linha mais cara:

    Vendas em dinheiro   − € 15,40      (`eurosComSinal`, o traço à frente)
    Saídas               − € 30,00      (o traço escrito, magnitude a seguir)
    Diferença            + € 10,20      (o `+` colado, escrito à mão)
    Diferença            € -4,60        (e o menos POR DENTRO do número)

A última linha era `${diferenca > 0 ? '+' : ''}${euros(diferenca)}`, em
`PosFecharCaixa.js`. O sinal positivo é escrito à mão e o negativo não é
escrito de todo — desce de dentro do `toLocaleString`, colado ao algarismo, com
o hífen do teclado em vez do traço de menos que o resto da janela usa. Duas
linhas acima, a mesma pergunta («este dinheiro entrou ou saiu?») responde-se com
um desenho diferente.

É a linha em que a operadora decide se tem de justificar uma FALTA ou uma
SOBRA, e é a última coisa que ela lê antes de assinar. Com pressa, «€ -4,60»
lê-se «€ 4,60».

**Como é que este guarda mede.** Os números vêm do SERVIDOR a sério — o
`fechar_caixa` real sobre a base falsa, o mesmo Z que sai ao balcão — e o
ecrã é MONTADO: escreve-se o contado no campo, carrega-se em FECHAR CAIXA, e o
que se afirma é o que fica LEGÍVEL no ecrã (`textoVisivel`), nunca o
`textContent` nem o texto do ficheiro. Um guarda que procurasse `eurosComSinal`
no ficheiro ficava verde com a chamada dentro de um ramo que nunca acende.

Os valores expõem o cêntimo, como no resto do módulo: 24,14 € de vendas
(10,20 × 2 + 0,29 + 1,15 × 3), sobra de 10,20 € e falta de 4,60 €.
"""
import json

import pytest

from faturacao import caixa as caixa_mod
from faturacao.caixa import PedidoFecharCaixa, fechar_caixa
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

_ACAI = "INT"
_REFRI = "NOR"


def _venda_em_dinheiro():
    """24,14 € cobrados TODOS em dinheiro (`tipo_fiscal == "NU"`, que é o que
    faz o dinheiro entrar na gaveta)."""
    v = _venda(
        id="paga", estado="emitida",
        linhas=[
            _linha(id="l1", produto_nome="Açaí Regular", produto_preco=10.20,
                   produto_tax_id=_ACAI, quantidade=2),
            _linha(id="l2", produto_nome="Água", produto_preco=0.29,
                   produto_tax_id=_ACAI),
            _linha(id="l3", produto_nome="Coca-Cola", produto_preco=1.15,
                   produto_tax_id=_REFRI, quantidade=3),
        ],
        criada_em="2026-08-21T10:00:00+00:00",
    )
    v["pagamentos"] = [{
        "tipo_pagamento_id": "tp-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
        "valor": 24.14,
    }]
    return v


def _z(monkeypatch, contado: float) -> dict:
    """O Z como o servidor o devolve — a rota real, não um dicionário à mão."""
    db = _db(
        [], caixas=[_caixa()], sessoes=[_sessao()],
        vendas=[_venda_em_dinheiro()], produtos=[_produto()], refs=[],
    )
    db[COLECOES["movimentos_caixa"]]  # `DbFalsa.__getitem__` cria-a vazia
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    async def _sem_vendus(_db, _sessao, _valor):
        return {"nao_verificado": "desligado no teste"}
    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", _sem_vendus)

    return _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=contado),
        operador=_operador()))


# Fundo 50,00 + vendas em dinheiro 24,14 = **74,14 € na gaveta**.
#   contado 84,34 -> sobra  +10,20
#   contado 69,54 -> falta   −4,60
#   contado 74,14 -> bate certo, 0,00
_CONTAGENS = {"sobra": 84.34, "falta": 69.54, "certo": 74.14}


@pytest.fixture(scope="module")
def zetas(request):
    """Os três Z, saídos da rota real."""
    saida = {}
    for nome, contado in _CONTAGENS.items():
        patch = pytest.MonkeyPatch()
        try:
            saida[nome] = _z(patch, contado)
        finally:
            patch.undo()
    return saida


def test_o_servidor_MEDE_a_sobra_e_a_falta(zetas):
    """A reprodução, nos números do servidor: a mesma gaveta contada de três
    maneiras."""
    assert zetas["sobra"]["esperado"] == 74.14
    assert zetas["sobra"]["diferenca"] == 10.20
    assert zetas["falta"]["diferenca"] == -4.60
    assert zetas["certo"]["diferenca"] == 0.0


# --- O ecrã: o Z montado, com o dedo a escrever a contagem --------------------

# A biblioteca de UI mínima que responde ao dedo (o mesmo gancho
# `global.__componentes` de `test_a_nota_de_credito_no_ecra.py`): sem um
# `<button>` a sério ninguém carrega em FECHAR CAIXA, e sem um `Dialog` que só
# desenhe quando `open` estes guardas mediam um diálogo que ninguém abriu.
_COMPONENTES = "\n".join([
    "const Botao = (props) => React.createElement('button', {",
    "  onClick: props.onClick, disabled: props.disabled,",
    "  className: props.className, type: 'button',",
    "}, props.children);",
    "const Campo = (props) => React.createElement('input', {",
    "  id: props.id, value: props.value === undefined ? '' : props.value,",
    "  onChange: props.onChange, placeholder: props.placeholder,",
    "  disabled: props.disabled, className: props.className,",
    "});",
    "const Caixa = (props) => (props.open",
    "  ? React.createElement('div', { 'data-dialogo': 'aberto' }, props.children)",
    "  : null);",
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => {",
    "  if (nome === '__esModule') return true;",
    "  if (nome === 'Button') return Botao;",
    "  if (nome === 'Input') return Campo;",
    "  if (nome === 'Dialog') return Caixa;",
    "  return Div;",
    "} });",
])


def _guiao(zetas) -> str:
    return "\n".join([
        _COMPONENTES,
        "const path2 = require('path');",
        # O preâmbulo substitui os ecrãs do POS por marcas vazias — é o que
        # deixa montar o `PosApp` sem montar tudo o que está por baixo dele.
        # Aqui são ESTES três que se querem medir: o diálogo do fecho, o campo
        # onde a contagem se escreve, e o bloco que desenha as linhas de cima.
        # Sem os tirar da lista, o `#contado-fecho` não existe no DOM e não há
        # contagem nenhuma para escrever.
        "for (const nome of ['PosFecharCaixa', 'PosCampoValor', 'PosResumoDoTurno'])",
        "  SUBSTITUIDOS.delete(path2.join(POS, nome + '.js'));",
        "const PosFecharCaixa = carregar("
        "path2.join(POS, 'PosFecharCaixa.js')).default;",
        # O dedo: um campo controlado do React não muda com `el.value = x` — o
        # React guarda o valor anterior no nó e ignora o evento. O setter
        # nativo escreve por baixo desse rasto.
        "function escrever(el, valor) {",
        "  Object.getOwnPropertyDescriptor(",
        "    dom.window.HTMLInputElement.prototype, 'value').set.call(el, valor);",
        "  el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));",
        "}",
        "const botaoDe = (alvo, texto) => Array.from(alvo.querySelectorAll('button'))",
        "  .find((b) => (b.textContent || '').includes(texto));",
        "const ZETAS = %s;" % json.dumps(zetas, ensure_ascii=False),
        "const CONTAGENS = %s;" % json.dumps(
            {nome: str(valor) for nome, valor in _CONTAGENS.items()}),
        "const saida = {};",
        "for (const nome of Object.keys(ZETAS)) {",
        "  for (const k of Object.keys(RESPOSTAS_POS)) delete RESPOSTAS_POS[k];",
        "  RESPOSTAS_POS['/pos/caixa/contas-abertas'] = () => ({ data: {",
        "    quantas: 0, total: 0, contas: [] } });",
        "  RESPOSTAS_POS['POST /pos/caixa/fechar'] = () => ({ data: ZETAS[nome] });",
        "  const alvo = document.getElementById('raiz');",
        "  const raiz = createRoot(alvo);",
        "  await act(async () => { raiz.render(React.createElement(",
        "    PosFecharCaixa, { aberto: true, onFechar: () => {},",
        "      caixa: { id: 'caixa-1', nome: 'Balcão' },",
        "      sessao: { fundo: 50 }, onFechado: () => {} })); });",
        "  await act(async () => {});",
        "  saida[nome + '/contagem'] = textoVisivel(alvo);",
        "  await act(async () => {",
        "    escrever(alvo.querySelector('#contado-fecho'), CONTAGENS[nome]);",
        "  });",
        "  await act(async () => { botaoDe(alvo, 'Fechar Caixa').click(); });",
        "  await act(async () => {});",
        "  saida[nome] = textoVisivel(alvo);",
        "  await act(async () => { raiz.unmount(); });",
        "  alvo.innerHTML = '';",
        "}",
        "process.stdout.write(JSON.stringify(saida));",
    ])


@pytest.fixture(scope="module")
def ecra(zetas, tmp_path_factory):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _guiao(zetas),
        tmp_path_factory.mktemp("sinal"), "montar-z.js",
    )


def test_o_Z_esta_mesmo_montado(ecra):
    """A afirmação de identidade: sem ela, um ecrã que não chegasse ao Z
    deixava todos os guardas a seguir verdes sobre o vazio."""
    for nome in _CONTAGENS:
        assert "Relatório Z" in ecra[nome], (
            "O cenário %r não chegou ao Z. O que ficou no ecrã: %r"
            % (nome, ecra[nome]))
        assert "Deve estar na gaveta € 74,14" in ecra[nome]


def test_a_FALTA_le_se_com_o_traco_a_FRENTE_do_euro(ecra):
    """**O defeito.** «Diferença € -4,60»: o menos por dentro do número, com o
    hífen do teclado, colado ao algarismo — e a operadora com pressa lê
    «€ 4,60». Na janela inteira, mais nenhuma linha de dinheiro se escreve
    assim."""
    lido = ecra["falta"]
    assert "Diferença − € 4,60" in lido, (
        "A linha da diferença não se lê com o traço à frente do euro. O que "
        "ficou no ecrã: %r" % lido)
    assert "€ -4,60" not in lido, (
        "O menos continua por DENTRO do número — a única linha de euros do POS "
        "que o escreve assim.")


def test_a_SOBRA_le_se_com_o_mesmo_desenho(ecra):
    assert "Diferença + € 10,20" in ecra["sobra"]


def test_a_diferenca_usa_a_MESMA_convencao_das_linhas_de_cima(ecra):
    """As três linhas de sinal da mesma janela têm de se ler da mesma maneira.
    É isto que apanha a correcção feita a meio — trocar o `+` à mão e deixar o
    negativo como estava, ou o contrário."""
    lido = ecra["falta"]
    assert "Vendas em dinheiro + € 24,14" in lido
    assert "Saídas − € 0,00" in lido
    assert "Diferença − € 4,60" in lido


def test_a_gaveta_que_BATE_CERTO_nao_se_desenha_como_uma_falta(ecra):
    """Zero é uma resposta: nada falta e nada sobra. A convenção é a mesma das
    "Entradas" e das "Vendas em dinheiro" a zero na mesma janela — o sinal
    positivo, e nunca um traço a sugerir uma falta que não existe."""
    lido = ecra["certo"]
    assert "Diferença + € 0,00" in lido
    assert "Diferença − € 0,00" not in lido


def test_as_tres_contagens_dao_TRES_linhas_diferentes(ecra):
    """A afirmação directa contra um valor cravado: três gavetas, três coisas
    diferentes para ler."""
    linhas = set()
    for nome in _CONTAGENS:
        lido = ecra[nome]
        inicio = lido.index("Diferença")
        linhas.add(lido[inicio:inicio + 20])
    assert len(linhas) == 3, (
        "A linha da diferença não muda com a contagem: %r" % sorted(linhas))
