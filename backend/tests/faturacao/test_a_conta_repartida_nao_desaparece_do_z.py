"""**Uma conta que a divisão não chegou a dividir volta SEMPRE a `aberta` — e
por isso volta sempre ao Z.**

`venda.py::_grava_as_partes` compensa uma corrida apagando as filhas e
repondo a mãe. Entre as duas escritas o balcão PARECE livre
(`_contas_do_balcao` responde `[]`: a mãe está `separada` e as filhas já não
existem), e o separador do lado abre ali a conta do cliente seguinte com a
etiqueta `posto_em_curso` deste posto. A reposição da mãe colide então com o
índice único parcial de `db.py` — e a versão anterior de `_repor_aberta`
**engolia o `DuplicateKeyError` e desistia**.

A mãe ficava `separada` sem partes nenhumas. Esse estado não existe para
conjunto nenhum: `_contas_do_balcao`, `caixa._contas_esquecidas` e
`caixa._contas_abertas_da_sessao` filtram todos por `estado: "aberta"`.
Reproduzido pelas rotas reais, com a conta de 11,64 € (0,29 + 1,15 + 10,20 —
valores escolhidos por serem os que EXPÕEM uma diferença, e não os que batem
certo em qualquer modo)::

    POST /pos/venda/mae/separar -> 409
    estado real da mãe: separada   total: 11.64 EUR   filhas vivas: 0
    /caixa/contas-esquecidas -> 0
    POST /pos/caixa/fechar -> 200
    Z: contas_abertas = {quantas: 1, total_por_cobrar: 0.00}

Onze euros e sessenta e quatro cêntimos apagados de um Z assinado, e a
docstring da própria função a prometer o contrário («uma mãe `separada` sem
partes é uma conta travada que o gestor resolve» — medida, a lista do gestor
vinha vazia).

**A correcção não é a ordem das escritas.** As filhas continuam a ser apagadas
PRIMEIRO, e de propósito: filhas órfãs vivas são N Faturas Simplificadas REAIS
a mais, e uma FS entregue à Autoridade Tributária não se desfaz. O que mudou é
que `_repor_aberta` deixou de desistir: o que colide é a ETIQUETA e não o
estado, por isso a segunda tentativa repõe `aberta` e larga a etiqueta na mesma
escrita — a mesma coisa que `entregar_ao_gestor` e o fecho de caixa já fazem.

Duplo de base de dados no padrão de test_venda.py. Nenhum teste liga a uma base
de dados nem à rede.
"""
import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import PedidoFecharCaixa, _contas_esquecidas, fechar_caixa
from faturacao.db import COLECOES
from faturacao.fiscal import _libertar_reserva, ext_ref_determinista
from faturacao.venda import (
    PedidoNovaVenda,
    PedidoSeparar,
    PedidoSepararLinha,
    PedidoSepararParte,
    _contas_do_balcao,
    abrir_venda,
    separar_conta,
)

from .test_venda import (  # noqa: F401
    ColeccaoFalsa,
    DbFalsa,
    _caixa,
    _chave_do_posto,
    _corre,
    _linha,
    _operador,
    _produto,
    _reserva,
    _sessao,
    _venda,
)

_PC = "pc-balcao"
# 0,29 + 1,15 + 10,20. Três guardas deste módulo revelaram-se inúteis por
# escolherem 0,30 e 8,50 — exactos em qualquer modo de cálculo. Estes expõem.
_TOTAL = 11.64


def _op(**over):
    o = _operador(dispositivo_id=_PC)
    o.update(over)
    return o


class ColeccaoComGancho(ColeccaoFalsa):
    """A colecção do duplo com um gancho `async` por operação de escrita.

    É o instrumento que põe a corrida no instante EXACTO que se quer medir —
    sem ele, a janela entre o `delete_one` da última filha e a reposição da mãe
    é código sequencial e nenhum teste lhe consegue entrar. O gancho é
    deliberadamente cru: chama-se DEPOIS da escrita, e quem o instala decide em
    que chamada é que faz alguma coisa."""

    ganchos = {}

    async def insert_one(self, doc):
        r = await super().insert_one(doc)
        await self._dispara("insert_one", doc)
        return r

    async def update_one(self, filtro, atualizacao):
        r = await super().update_one(filtro, atualizacao)
        await self._dispara("update_one", filtro, atualizacao)
        return r

    async def delete_one(self, filtro):
        r = await super().delete_one(filtro)
        await self._dispara("delete_one", filtro)
        return r

    async def _dispara(self, nome, *args):
        gancho = (self.ganchos or {}).get(nome)
        if gancho:
            await gancho(*args)


def _monta(monkeypatch, vendas):
    registo = []
    coleccao_vendas = ColeccaoComGancho(registo, vendas, unico=_chave_do_posto)
    db = DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, [_sessao()]),
        COLECOES["vendas"]: coleccao_vendas,
        COLECOES["produtos"]: ColeccaoFalsa(registo, [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, None),
        COLECOES["documentos"]: ColeccaoFalsa(registo, None),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, None),
    })
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda: db)
    return db, coleccao_vendas


def _mae():
    return _venda(
        id="mae", dispositivo_id=_PC, entregue_ao_gestor_em=None,
        criada_em="2026-08-21T10:00:00+00:00",
        posto_em_curso="loja-1|%s" % _PC,
        linhas=[
            _linha(id="L1", produto_preco=0.29),
            _linha(id="L2", produto_preco=1.15),
            _linha(id="L3", produto_preco=10.20),
        ],
    )


_SEPARAR = PedidoSeparar(partes=[
    PedidoSepararParte(linhas=[PedidoSepararLinha(linha_id="L3", quantidade=1)]),
    PedidoSepararParte(linhas=[
        PedidoSepararLinha(linha_id="L1", quantidade=1),
        PedidoSepararLinha(linha_id="L2", quantidade=1),
    ]),
])


def _a_corrida(db, coleccao, monkeypatch):
    """Monta a corrida medida e devolve o que aconteceu à mãe.

    A reserva nasce quando a mãe é travada (a emissão ganhou-a depois do
    `_garante_sem_emissao` de quem chamou, que é a janela que a compensação
    existe para tratar), e a conta do cliente seguinte nasce quando a ÚLTIMA
    filha é apagada — o instante em que o balcão parece livre."""
    estado = {"apagadas": 0, "reservou": False}

    async def ao_travar_a_mae(filtro, atualizacao):
        if not estado["reservou"] and atualizacao.get("$set", {}).get("estado") == "separada":
            estado["reservou"] = True
            await db[COLECOES["refs_fiscais"]].insert_one(_reserva(
                id="ref-mae", venda_id="mae",
                ext_ref=ext_ref_determinista("loja-1", "sessao-1", "mae")))

    async def ao_apagar_a_filha(filtro):
        estado["apagadas"] += 1
        if estado["apagadas"] == 2:
            estado["balcao_na_janela"] = await _contas_do_balcao(db, "loja-1", _PC)
            estado["nova"] = await abrir_venda(
                PedidoNovaVenda(caixa_id="caixa-1"), operador=_op())

    coleccao.ganchos = {"update_one": ao_travar_a_mae, "delete_one": ao_apagar_a_filha}
    with pytest.raises(HTTPException) as recusa:
        _corre(separar_conta("mae", _SEPARAR, operador=_op()))
    coleccao.ganchos = {}
    assert recusa.value.status_code == 409
    assert estado["balcao_na_janela"] == [], (
        "A reprodução deixou de reproduzir: o balcão já não parece livre na "
        "janela, e a corrida que este teste mede deixou de ser possível. Se "
        "isso foi de propósito, é aqui que se reescreve o teste.")
    return estado


def test_a_mae_de_uma_separacao_abortada_volta_sempre_a_aberta(monkeypatch):
    """A corrida inteira, pelas rotas reais — e o que a base tem no fim.

    A mãe não pode ficar `separada`: esse estado tira-a do ecrã do posto, da
    lista do gestor e do Z ao mesmo tempo, e 11,64 € de um cliente que ainda
    está à frente da operadora deixam de existir para o sistema."""
    db, coleccao = _monta(monkeypatch, [_mae()])
    _a_corrida(db, coleccao, monkeypatch)

    mae = _corre(db[COLECOES["vendas"]].find_one({"id": "mae"}))
    assert mae["estado"] == "aberta", (
        "A mãe ficou %r. A compensação desistiu de a repor por causa da "
        "etiqueta do posto, e uma conta que não está `aberta` não existe para "
        "conjunto nenhum: nem para o ecrã, nem para o gestor, nem para o Z."
        % mae["estado"])
    assert "posto_em_curso" not in mae, (
        "Voltou a `aberta` COM a etiqueta do posto. É a etiqueta que colide "
        "com a conta nova no índice único — mantê-la era não ter reposto nada.")
    assert _corre(db[COLECOES["vendas"]].find({"conta_mae_id": "mae"}).to_list(9)) == [], (
        "Sobraram filhas vivas de uma separação que não se fez: são N contas "
        "prontas a emitir N Faturas Simplificadas REAIS de uma conta que "
        "ninguém separou.")


def test_a_conta_reposta_esta_no_ecra_do_posto_e_no_Z_assinado(monkeypatch):
    """E o que interessa ao dono: os 11,64 € entram no Z.

    A emissão que provocou a compensação aborta sozinha (a mãe já não estava
    `aberta` quando ela releu — `fiscal._garante_venda_ainda_aberta`) e liberta
    a reserva; a partir daí nada trava o fecho, e é exactamente aí que o
    dinheiro desaparecia."""
    db, coleccao = _monta(monkeypatch, [_mae()])
    corrida = _a_corrida(db, coleccao, monkeypatch)

    no_balcao = _corre(_contas_do_balcao(db, "loja-1", _PC))
    assert {v["id"] for v in no_balcao} == {"mae", corrida["nova"]["id"]}, (
        "O ecrã deste posto tem de mostrar as DUAS contas: a que sobrou da "
        "corrida e a do cliente que a operadora começou a atender.")

    _corre(_libertar_reserva(
        db, ext_ref_determinista("loja-1", "sessao-1", "mae"), "ref-mae"))
    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))

    assert z["contas_abertas"]["total_por_cobrar"] == _TOTAL, (
        "O Z assinado diz %r € por cobrar e a base tem uma conta de %r €. É "
        "esta a diferença que se mede: dinheiro apagado de um Z que uma pessoa "
        "assinou." % (z["contas_abertas"]["total_por_cobrar"], _TOTAL))
    assert "mae" in {c["id"] for c in z["contas_abertas"]["contas"]}


def test_a_conta_reposta_chega_ao_gestor_quando_o_turno_fecha(monkeypatch):
    """A promessa que a docstring de `_repor_aberta` fazia e não cumpria: a
    conta que sobrou aparece na lista do gestor. Ela só lá chega `aberta` — a
    lista filtra por esse estado, e era por isso que a mãe `separada` não
    aparecia a ninguém."""
    db, coleccao = _monta(monkeypatch, [_mae()])
    _a_corrida(db, coleccao, monkeypatch)
    _corre(_libertar_reserva(
        db, ext_ref_determinista("loja-1", "sessao-1", "mae"), "ref-mae"))
    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))

    esquecidas = _corre(_contas_esquecidas(db))
    assert "mae" in {c["id"] for c in esquecidas}, (
        "A conta não chegou à lista do gestor — que é o único sítio onde "
        "alguém a vai procurar depois de o turno fechar.")
    assert next(c for c in esquecidas if c["id"] == "mae")["total"] == _TOTAL


def test_sem_corrida_nenhuma_a_compensacao_continua_a_ser_a_de_sempre(monkeypatch):
    """A rede de segurança: no caso normal (ninguém abre nada na janela) a
    reposição não colide, a mãe volta a `aberta` **com** a etiqueta, e o posto
    continua ocupado por ela. Largar a etiqueta sempre era abrir a porta a duas
    contas em curso no mesmo posto — o defeito que o índice existe para
    fechar."""
    db, coleccao = _monta(monkeypatch, [_mae()])

    async def ao_travar_a_mae(filtro, atualizacao):
        if atualizacao.get("$set", {}).get("estado") == "separada":
            await db[COLECOES["refs_fiscais"]].insert_one(_reserva(
                id="ref-mae", venda_id="mae",
                ext_ref=ext_ref_determinista("loja-1", "sessao-1", "mae")))

    coleccao.ganchos = {"update_one": ao_travar_a_mae}
    with pytest.raises(HTTPException):
        _corre(separar_conta("mae", _SEPARAR, operador=_op()))
    coleccao.ganchos = {}

    mae = _corre(db[COLECOES["vendas"]].find_one({"id": "mae"}))
    assert mae["estado"] == "aberta"
    assert mae["posto_em_curso"] == "loja-1|%s" % _PC, (
        "A conta voltou a `aberta` sem a etiqueta do posto sem ter havido "
        "colisão nenhuma: o posto ficou livre com uma conta em curso à frente "
        "da operadora, e o toque seguinte abre uma segunda.")
