"""Guarda de regressão: gravar um tipo de pagamento não lhe desliga a emissão.

O `PUT /tipos-pagamento/{id}` substitui o registo INTEIRO — faz `$set` com o
`model_dump()` do modelo completo, e `vendus_payment_method_id` tem `None` por
omissão. Quer dizer que um pedido que não traga o campo não o "deixa como
estava": apaga-o. E um tipo sem `vendus_payment_method_id` é um tipo que
`fiscal.py::finalizar` recusa emitir, com 422, no segundo exacto em que a
operadora carrega em EMITIR — com o cliente à frente e a venda por fechar.

Por isso é que o ecrã reenvia sempre o mapeamento, mesmo quando ninguém lhe
tocou (`FatPagamentos.js`, no `openEdit` e no `payload` do `handleSubmit`).
Corrigir o nome de um tipo de pagamento deixava-o mudo. É uma linha em cada
sítio, e nenhuma das duas tinha teste nenhum: apagavam-se as duas e a suite
ficava verde, o `yarn build` compilava, e o defeito ia inteiro para produção.

O frontend deste repositório não tem infra-estrutura de testes — não há um
único `*.test.js`, nem jest nem testing-library, e acrescentar a dependência
não estava em cima da mesa. A técnica é então a mesma do
`test_caminhos_do_pos.py`, que nasceu do mesmo tipo de buraco (um caminho
escrito de um lado, servido do outro, e nada a olhar para os dois ao mesmo
tempo): ler o ficheiro do frontend como TEXTO e confrontá-lo com a verdade do
servidor. Aqui a verdade do servidor não é uma lista de rotas, é um
comportamento — e por isso o `editar` é mesmo exercido, em baixo, em vez de
descrito num comentário.

O que este guarda NÃO faz, para ninguém lhe pedir mais do que ele dá: não
executa o JavaScript. Prova que o campo vai no pedido e que o valor sai do
sítio certo (`form.` num caso, `tipo.` no outro); não prova que o ecrã se
comporta bem — isso continua a ser trabalho de percorrer o ecrã no browser.
"""
import asyncio
import re
from copy import deepcopy
from pathlib import Path

import pytest

from faturacao import pagamentos as pagamentos_mod
from faturacao.pagamentos import TipoPagamentoEntrada, editar

_CAMPO = "vendus_payment_method_id"

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_ECRA = _RAIZ / "frontend" / "src" / "pages" / "admin" / "faturacao" / "FatPagamentos.js"


# --- Metade 1: o servidor faz mesmo o que o ecrã assume ------------------------

def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class ColeccaoFalsa:
    """Duplo mínimo de uma colecção Mongo: regista o que lhe fizeram.

    `deepcopy` à saída pela mesma razão do test_pagamentos_endpoints.py: o
    `find_one` real descodifica BSON de fresco e nunca devolve o objecto do
    teste, e um duplo que o devolvesse deixava passar defeitos por aliasing."""

    def __init__(self, registo, documento):
        self.registo = registo
        self._documento = documento

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        return deepcopy(self._documento)

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", filtro, deepcopy(atualizacao)))
        return None


class DbFalsa:
    def __init__(self, coleccao):
        self._coleccao = coleccao

    def __getitem__(self, nome):
        return self._coleccao


_GRAVADO = {
    "id": "x",
    "protegido": False,
    "nome": "Dinheiro",
    "tipo_fiscal": "NU",
    _CAMPO: "145234375",  # o método "Dinheiro" da conta Vendus real
}


def _edita(monkeypatch, dados):
    registo = []
    monkeypatch.setattr(
        pagamentos_mod, "obter_db", lambda: DbFalsa(ColeccaoFalsa(registo, _GRAVADO))
    )
    _corre(editar("x", dados, _={}))
    escritas = [c for c in registo if c[0] == "update_one"]
    assert len(escritas) == 1, "esperava exactamente um update_one, vi %d" % len(escritas)
    return escritas[0][2]["$set"]


def test_o_put_apaga_o_mapeamento_quando_o_pedido_o_omite(monkeypatch):
    """A verdade do servidor de que os dois guardas abaixo dependem, exercida e
    não assumida: o PUT substitui o registo inteiro.

    Um pedido que só traga o nome e o código fiscal — que é exactamente o que
    um formulário "só mudei o nome" enviaria — grava `None` por cima de um
    mapeamento que estava bom. O tipo de pagamento continua a existir, continua
    "Ativo", continua com um botão no POS; só deixou de emitir faturas, sem
    dizer nada a ninguém."""
    escrito = _edita(monkeypatch, TipoPagamentoEntrada(nome="Dinheiro", tipo_fiscal="NU"))

    assert _CAMPO in escrito, (
        "o $set deixou de escrever %s — se o PUT passar a poupar os campos que "
        "não vêm no pedido, este ficheiro inteiro deixa de fazer sentido e as "
        "duas linhas que ele vigia no frontend deixam de ser necessárias." % _CAMPO
    )
    assert escrito[_CAMPO] is None


def test_o_put_mantem_o_mapeamento_quando_o_pedido_o_traz(monkeypatch):
    """O outro lado da mesma moeda: reenviar o campo preserva a emissão. É
    isto que as duas linhas do ecrã compram."""
    escrito = _edita(
        monkeypatch,
        TipoPagamentoEntrada(nome="Dinheiro (novo nome)", tipo_fiscal="NU",
                             vendus_payment_method_id="145234375"),
    )

    assert escrito[_CAMPO] == "145234375"


# --- Metade 2: o ecrã reenvia mesmo o campo ------------------------------------

def _sem_comentarios(js: str) -> str:
    """Apaga os comentários (`//` e `/* */`), preservando o comprimento.

    Sem isto o guarda não valia rigorosamente nada: o ficheiro FALA de
    `vendus_payment_method_id` em vários comentários — incluindo um a explicar
    porque é que a linha existe — e um `in conteudo` cru continuava verde com a
    linha do payload apagada, que é precisamente a mutação que ele existe para
    apanhar. O texto que fica é código.

    As aspas são seguidas para o `//` de dentro de uma cadeia não cortar o
    ficheiro a meio."""
    saida = []
    i, n = 0, len(js)
    aspas = None
    while i < n:
        c = js[i]
        if aspas is not None:
            saida.append(c)
            if c == "\\" and i + 1 < n:
                saida.append(js[i + 1])
                i += 2
                continue
            if c == aspas:
                aspas = None
            i += 1
            continue
        if c in "'\"`":
            aspas = c
            saida.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            while i < n and js[i] != "\n":
                saida.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "*":
            fim = js.find("*/", i + 2)
            fim = n if fim < 0 else fim + 2
            saida.append(" " * (fim - i))
            i = fim
            continue
        saida.append(c)
        i += 1
    return "".join(saida)


def _objecto(fonte: str, *ancoras: str) -> str:
    """O texto do objecto literal cuja chaveta de abertura é o último caractere
    da última âncora. As âncoras procuram-se por ordem, cada uma a partir de
    onde a anterior acabou — é assim que se chega ao `setForm({` do `openEdit`
    sem apanhar os outros `setForm({` do ficheiro."""
    pos = 0
    for ancora in ancoras:
        achado = fonte.find(ancora, pos)
        assert achado >= 0, (
            "não encontrei %r em %s — o ecrã foi reescrito e este guarda tem de "
            "ser actualizado, senão passa a verde sem verificar nada."
            % (ancora, _ECRA.name)
        )
        pos = achado + len(ancora)
    profundidade, i = 1, pos
    while i < len(fonte) and profundidade:
        if fonte[i] == "{":
            profundidade += 1
        elif fonte[i] == "}":
            profundidade -= 1
        i += 1
    assert profundidade == 0, "objecto literal sem fecho a partir de %r" % ancoras[-1]
    return fonte[pos:i - 1]


def _ler_ecra() -> str:
    # Falha em vez de saltar, como no test_caminhos_do_pos.py: um guarda que se
    # desliga sozinho quando não encontra o que devia vigiar é pior do que não
    # existir — ficava verde para sempre e ninguém reparava.
    assert _ECRA.exists(), (
        "Não encontrei %s — este guarda precisa dos dois lados (frontend e "
        "backend) para ter algum valor." % _ECRA
    )
    return _sem_comentarios(_ECRA.read_text(encoding="utf-8"))


def _payload(fonte: str) -> str:
    """O objecto que o `handleSubmit` envia ao servidor."""
    return _objecto(fonte, "const payload = {")


def _formulario_de_edicao(fonte: str) -> str:
    """O objecto com que o `openEdit` enche o formulário a partir do registo."""
    return _objecto(fonte, "const openEdit = ", "setForm({")


def test_os_comentarios_sao_mesmo_apagados():
    """Rede de segurança do próprio guarda. `Optional[str]` só aparece num
    comentário do ecrã; se sobreviver, o `_sem_comentarios` deixou de cortar e
    os testes seguintes passam a poder ficar verdes por causa de uma frase em
    português em vez de uma linha de código."""
    bruto = _ECRA.read_text(encoding="utf-8")
    assert "Optional[str]" in bruto, (
        "o comentário-sentinela desapareceu do ecrã — escolha outro texto que "
        "só exista em comentário, senão este teste deixa de provar nada."
    )
    assert "Optional[str]" not in _ler_ecra()
    assert _CAMPO in bruto  # e o campo continua a ser o assunto do ficheiro


def test_o_guarda_encontra_os_dois_blocos():
    """A outra rede de segurança: se o ecrã for reescrito noutro estilo, os
    blocos deixam de ser encontrados e os testes abaixo percorreriam texto
    vazio, verdes e cegos."""
    fonte = _ler_ecra()
    assert "nome:" in _payload(fonte)
    assert "nome:" in _formulario_de_edicao(fonte)


def test_o_pedido_do_ecra_reenvia_sempre_o_mapeamento():
    """A linha do `payload`. Sem ela, gravar um tipo de pagamento a que
    ninguém tocou o mapeamento — mudar-lhe o nome, a ordem, o troco —
    desligava-lhe a emissão em silêncio (ver o teste do PUT, acima)."""
    payload = _payload(_ler_ecra())
    assert _CAMPO in payload, (
        "o payload de FatPagamentos.js deixou de enviar %s. Como o PUT "
        "substitui o registo inteiro, gravar qualquer alteração passa a apagar "
        "a ligação ao Vendus e o tipo deixa de emitir faturas." % _CAMPO
    )
    assert "form.%s" % _CAMPO in payload, (
        "o payload envia %s mas não o vai buscar ao formulário — um valor fixo "
        "aqui grava o mesmo em todos os tipos de pagamento." % _CAMPO
    )


def test_o_formulario_de_edicao_carrega_o_mapeamento_gravado():
    """A outra metade da mesma linha: de nada servia reenviar o campo se o
    formulário abrisse vazio — o payload mandava `null` na mesma."""
    formulario = _formulario_de_edicao(_ler_ecra())
    assert _CAMPO in formulario, (
        "o openEdit de FatPagamentos.js deixou de carregar %s do registo: o "
        "formulário abre sem o mapeamento e o Guardar apaga-o." % _CAMPO
    )
    assert "tipo.%s" % _CAMPO in formulario, (
        "o openEdit enche %s com outra coisa que não o valor gravado no tipo "
        "que está a ser editado." % _CAMPO
    )


# --- Prova por mutação, feita aqui dentro e não à mão --------------------------
#
# Um guarda de texto é fácil de escrever de maneira a nunca falhar. Estes dois
# fabricam as duas formas exactas de partir cada linha e exigem que o crivo
# acima as apanhe. Se eles falharem, são os quatro testes de cima que deixaram
# de valer alguma coisa.

def _sem_a_linha(fonte: str) -> str:
    """O defeito nº1: a linha desaparece."""
    return "\n".join(l for l in fonte.splitlines() if (_CAMPO + ":") not in l)


def _com_valor_fixo(fonte: str) -> str:
    """O defeito nº2, mais traiçoeiro: a linha fica, o valor é que deixa de
    vir de onde devia. O campo continua a viajar — e viaja sempre a `null`."""
    return re.sub(r"%s:[^,\n]*" % _CAMPO, "%s: null" % _CAMPO, fonte)


@pytest.mark.parametrize(
    "extrair,esperado",
    [(_payload, "form"), (_formulario_de_edicao, "tipo")],
)
def test_o_guarda_apanha_a_linha_apagada(extrair, esperado):
    fonte = _ler_ecra()
    assert _CAMPO in extrair(fonte)  # verde no ficheiro a sério
    assert _CAMPO not in extrair(_sem_a_linha(fonte)), (
        "com a linha do %s apagada o guarda continuava verde — não vigia nada." % _CAMPO
    )


@pytest.mark.parametrize(
    "extrair,origem",
    [(_payload, "form"), (_formulario_de_edicao, "tipo")],
)
def test_o_guarda_apanha_o_valor_fixo(extrair, origem):
    fonte = _ler_ecra()
    assert "%s.%s" % (origem, _CAMPO) in extrair(fonte)
    assert "%s.%s" % (origem, _CAMPO) not in extrair(_com_valor_fixo(fonte)), (
        "com o campo preso a `null` o guarda continuava verde — e um `null` "
        "fixo apaga o mapeamento de todos os tipos de pagamento."
    )
