"""**O voucher L'Açaí visto de dentro da CONTA** — as duas coisas que o
`venda.py` tem de saber sobre uma recompensa aplicada ao balcão.

Um `grep voucher venda.py` devolvia zero, e havia dois sítios onde isso custava:

1. **Cancelar a conta não devolvia a recompensa.** O cliente mostra o QR, muda
   de ideias, a funcionária carrega em «Cancelar conta» — e do lado da app o
   voucher fica `reserved`. A carteira só lista os ACTIVOS: a recompensa
   desaparece do telemóvel dele, e se ele voltar à caixa o cartão fica MUDO
   (a ligação nova não encontra voucher activo nenhum). Está sem o produto e
   sem a recompensa — a metade má da regra de ouro 3.
2. **Repartir a conta copiava a marca para cada parte.** `_copia_da_linha` é um
   `deepcopy`: o `voucher_id` e uma fatia do desconto iam para todas as partes,
   cada uma passava o travão do zero (`fiscal._tem_linha_de_voucher`) e emitia a
   0,00 € — N Faturas Simplificadas REAIS por um voucher. E como a ligação do QR
   não viaja para as partes, o `/creditar` nunca corria: o cliente levava o açaí
   E ficava com a recompensa.

As duas regras que mandam nisto, e estão as duas medidas aqui: **nada disto pode
impedir uma fatura de sair** (nem uma conta de ser cancelada) e **falhar fechado
e EM VOZ ALTA**.

A app não é chamada a sério em nenhum teste: o transporte do httpx é o
`MockTransport` da fixture `app`, e é o corpo que sai deste servidor — pela rota
verdadeira do `pontos_app` — que se afirma, nunca um duplo da função que fala com
ela.
"""
import logging

import httpx
import pytest
from fastapi import HTTPException

from faturacao import pontos_app
from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.venda import (
    PedidoDividir,
    PedidoSeparar,
    PedidoSepararUmaParte,
    cancelar_venda,
    dividir_conta,
    separar_conta,
    separar_uma_parte,
)

from .test_os_pontos_da_app import app  # noqa: F401 — fixture
from .test_venda import _corre, _db, _linha, _operador, _venda

# A ligação do QR como o ecrã a guarda e o servidor a grava na venda
# (`fiscal.finalizar_venda`, campo `pontos_ligacao`): é o `pos:{id}` que nomeia
# a reserva do voucher do lado da app, e a ÚNICA chave que a nomeia.
_LIGACAO = {"id": "lig-1", "primeiro_nome": "Ana"}


def _conta_com_voucher(**over):
    """A conta do balcão com a recompensa já aplicada — a marca e o desconto na
    linha, como `pontos_app.voucher_ao_balcao` os escreve.

    O Açaí Grande de 9,00 € com um voucher de 7,20 € é o exemplo do desenho: o
    desconto não zera a linha (`unit_price >= valor` é a regra de
    elegibilidade), e por isso as três formas de repartir esta conta **davam
    201** antes desta ronda — é isso que faz a recusa ser mesmo a recusa nova, e
    não um 422 de uma parte sem valor.
    """
    return _venda(
        linhas=[
            _linha(id="l1", produto_nome="Açaí Grande", produto_preco=9.0,
                   voucher_id="v-1", desconto_eur=7.2),
            _linha(id="l2", produto_nome="Cookie", produto_preco=3.8),
        ],
        **over,
    )


def _conta_sem_voucher(**over):
    return _venda(
        linhas=[
            _linha(id="l1", produto_nome="Açaí Grande", produto_preco=9.0),
            _linha(id="l2", produto_nome="Cookie", produto_preco=3.8),
        ],
        **over,
    )


def _vendas(db):
    return db._coleccoes[COLECOES["vendas"]]._documentos


# --- Cancelar devolve a recompensa ao cliente -----------------------------------


def test_cancelar_uma_conta_com_voucher_pede_a_app_para_a_libertar(monkeypatch, app):
    """O caminho que faltava, e é o mais banal que há ao balcão.

    **As `linhas` VAZIAS são o contrato da libertação**, e não uma rota nova:
    nenhuma linha serve, logo a app liberta a reserva e põe o `voucher_id` da
    ligação a `None` (`routes_pos_integracao.voucher`). É a mesma porta que o
    «Remover» do cartão dos pontos usa."""
    db = _db([], vendas=[_conta_com_voucher(pontos_ligacao=_LIGACAO)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    app.responde(200, {})

    resultado = _corre(cancelar_venda("venda-1", operador=_operador()))

    assert resultado["estado"] == "cancelada"
    assert len(app.pedidos) == 1
    assert str(app.pedidos[0].url) == "http://olacai-api:8001/api/pos-integracao/voucher"
    assert app.pedidos[0].headers["X-Service-Key"] == "chave-de-teste"
    assert app.corpo() == {"ligacao_id": "lig-1", "linhas": []}


def test_o_aviso_vai_DEPOIS_de_a_conta_estar_cancelada(monkeypatch, app):
    """A ordem é a regra de ouro 3 na outra direcção: libertar primeiro e o
    cancelamento falhar a seguir deixava a Fatura Simplificada sair COM o
    desconto e o `/creditar` sem nada para consumir — o cliente levava o açaí E
    ficava com a recompensa.

    Mede-se pelo que a app VÊ quando é chamada: nesse instante a venda já está
    gravada como `cancelada`."""
    db = _db([], vendas=[_conta_com_voucher(pontos_ligacao=_LIGACAO)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    estados = []
    app.responde(200, {})
    transporte = pontos_app._transporte

    def espia(pedido):
        estados.append(_vendas(db)[0]["estado"])
        return transporte.handler(pedido)

    monkeypatch.setattr(pontos_app, "_transporte", httpx.MockTransport(espia))

    _corre(cancelar_venda("venda-1", operador=_operador()))

    assert estados == ["cancelada"]


def test_uma_conta_com_emissao_em_curso_nao_liberta_nada(monkeypatch, app):
    """O outro lado da mesma ordem: o cancelamento recusado (409, há uma reserva
    fiscal viva) não pode devolver o voucher — aquela conta ainda pode virar uma
    fatura com o desconto lá dentro."""
    from .test_venda import _reserva

    db = _db([], vendas=[_conta_com_voucher(pontos_ligacao=_LIGACAO)],
             refs=[_reserva()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(cancelar_venda("venda-1", operador=_operador()))

    assert e.value.status_code == 409
    assert app.pedidos == []


def test_a_app_em_baixo_nao_impede_o_cancelamento(monkeypatch, app):
    """Regra de ouro 1, aqui na versão «nada disto pode impedir uma conta de ser
    cancelada»: cancelar é a única saída que a operadora tem para arrumar uma
    conta. A reserva do voucher morre sozinha do lado da app quando a ligação
    sair da janela das 2 h — tarde, mas o lado seguro."""
    db = _db([], vendas=[_conta_com_voucher(pontos_ligacao=_LIGACAO)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    app.rebenta(httpx.ConnectError("ligação recusada"))

    resultado = _corre(cancelar_venda("venda-1", operador=_operador()))

    assert resultado["estado"] == "cancelada"
    assert _vendas(db)[0]["estado"] == "cancelada"


def test_um_erro_inesperado_do_pontos_app_tambem_nao_impede(monkeypatch, app):
    """O `except Exception` largo, e o que ele paga: esta função chama o
    `pontos_app` por um nome que vive noutro módulo. Se ele mudar de nome, de
    assinatura, ou rebentar por uma razão que ninguém previu, a conta CANCELA-SE
    — nunca um 500 ao balcão numa conta que o cliente já abandonou."""
    db = _db([], vendas=[_conta_com_voucher(pontos_ligacao=_LIGACAO)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    async def rebenta(*_args, **_kwargs):
        raise RuntimeError("o outro lado mudou")

    monkeypatch.setattr(pontos_app, "_libertar_na_app", rebenta)

    assert _corre(cancelar_venda("venda-1", operador=_operador()))["estado"] == "cancelada"
    assert _vendas(db)[0]["estado"] == "cancelada"


def test_cancelar_uma_conta_sem_voucher_nao_fala_com_a_app(monkeypatch, app):
    """O caso normal, a esmagadora maioria dos cancelamentos: nem um pedido de
    rede com a funcionária à espera.

    **Com a ligação gravada e de propósito** — mostrar o QR só para ganhar
    pontos é o caminho de todos os dias, e a maior parte dessas contas não tem
    voucher nenhum. É a MARCA na linha que manda, nunca a ligação: sem marca não
    há reserva para libertar, e um pedido à app por cada cancelamento era o tecto
    de 4 s do `_chamar_app` pendurado num botão que tem de ser instantâneo."""
    db = _db([], vendas=[_conta_sem_voucher(pontos_ligacao=_LIGACAO)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    assert _corre(cancelar_venda("venda-1", operador=_operador()))["estado"] == "cancelada"
    assert app.pedidos == []


def test_um_voucher_sem_ligacao_gravada_GRITA_no_registo(monkeypatch, app, caplog):
    """Falhar fechado e **em voz alta** (regra de ouro 2).

    A ligação do QR é a única chave que nomeia a reserva do lado da app
    (`reserved_by` = `pos:{ligacao_id}`) e vive no `sessionStorage` do ecrã.
    Sem ela gravada na venda não há nada a pedir a ninguém — e isso tem de
    aparecer no registo, com o preço escrito: o cliente fica sem a recompensa na
    carteira e, se voltar, o cartão da caixa fica mudo. Um voucher preso sem
    ninguém perceber porquê é o pior desfecho de todos."""
    db = _db([], vendas=[_conta_com_voucher()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with caplog.at_level(logging.ERROR, logger="faturacao.venda"):
        assert _corre(
            cancelar_venda("venda-1", operador=_operador()))["estado"] == "cancelada"

    assert app.pedidos == [], "sem ligação não se inventa um pedido à app"
    gritos = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(gritos) == 1
    assert "venda-1" in gritos[0] and "recompensa" in gritos[0]


# --- Uma conta com voucher NÃO se reparte (Fase 1) ------------------------------

# As três formas de repartir, cada uma com um pedido que — sem a recusa nova —
# daria 201 nesta conta. É isso que faz esta tabela medir a GUARDA e não um 422
# de uma parte sem valor.
_REPARTIR = {
    "dividir": lambda: dividir_conta(
        "venda-1", PedidoDividir(partes=2), operador=_operador()),
    "separar": lambda: separar_conta(
        "venda-1",
        PedidoSeparar(partes=[
            {"linhas": [{"linha_id": "l1", "quantidade": 1}]},
            {"linhas": [{"linha_id": "l2", "quantidade": 1}]},
        ]),
        operador=_operador()),
    "separar-parte": lambda: separar_uma_parte(
        "venda-1",
        PedidoSepararUmaParte(linhas=[{"linha_id": "l1", "quantidade": 1}]),
        operador=_operador()),
}


@pytest.mark.parametrize("rota", sorted(_REPARTIR))
def test_repartir_uma_conta_com_voucher_e_recusado_e_nada_e_gravado(rota, monkeypatch):
    """As três rotas, porque as três chamam `_copia_da_linha` — a recusa está na
    guarda partilhada e não em cada uma delas.

    E nada gravado: nem partes novas, nem a mãe travada. Uma conta travada
    `separada` com um voucher aplicado não tem saída nenhuma — não se junta, não
    se desconta, não se cancela."""
    db = _db([], vendas=[_conta_com_voucher(pontos_ligacao=_LIGACAO)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(_REPARTIR[rota]())

    assert e.value.status_code == 409
    # A frase tem de dizer o que fazer a seguir, e o que se faz é tirar o cliente
    # da fatura: o «Remover» limpa a marca e o desconto da linha.
    assert "recompensa L'Açaí" in e.value.detail
    assert "Remover" in e.value.detail
    assert len(_vendas(db)) == 1, "nenhuma parte nasceu"
    assert _vendas(db)[0]["estado"] == "aberta", "a mãe não ficou travada"


def test_repartir_uma_conta_SEM_voucher_continua_exactamente_como_hoje(monkeypatch):
    """A guarda nova não pode apertar o caminho de todos os dias: 12,80 € por
    dois são 6,40 € e 6,40 €, e a mãe fica `separada` como sempre ficou."""
    db = _db([], vendas=[_conta_sem_voucher()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    r = _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))

    assert [p["totais"]["total"] for p in r["partes"]] == [6.4, 6.4]
    assert r["conta_mae"]["estado"] == "separada"
