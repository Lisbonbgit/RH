"""Guião de REPRODUÇÃO das duas famílias com dinheiro PRESO — não é um teste,
é o instrumento.

Corre-se com:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.faturacao._repro_ronda8

Usa os mesmos duplos de test_venda.py e as ROTAS REAIS. Os valores são os que
EXPÕEM a diferença (0,29 · 1,15 · 10,20 = 11,64 €), nunca 0,30 e 8,50.
"""
import asyncio  # noqa: F401  (o `_corre` usa-o)

from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import (
    _contas_abertas_da_sessao,
    arrumar_conta_esquecida,
    listar_contas_esquecidas,
)
from faturacao.fiscal import (
    PedidoLibertarReserva,
    ext_ref_determinista,
    libertar_reserva_presa,
    listar_reservas_presas,
    reconciliar_reserva_presa,
)
from faturacao.venda import contas_repartidas, entregar_ao_gestor, venda_aberta

from tests.faturacao.test_venda import (
    _caixa,
    _corre,
    _db,
    _linha,
    _operador,
    _produto,
    _sessao,
    _venda,
)

_LOJA = "loja-1"
_SESSAO = "sessao-1"
_LINHAS = [
    _linha(id="l1", produto_preco=10.20, produto_tax_id="INT"),
    _linha(id="l2", produto_preco=1.15, produto_tax_id="NOR"),
    _linha(id="l3", produto_preco=0.29, produto_tax_id="NOR"),
]
_GESTOR = {"user_id": "u-9", "email": "gestor@lojas.pt", "role": "admin"}


def monta(vendas=None, refs=None, sessoes=None):
    db = _db(
        [], caixas=[_caixa()],
        sessoes=[_sessao(estado="aberta")] if sessoes is None else sessoes,
        vendas=vendas, refs=refs, produtos=[_produto()], com_indice_do_posto=True,
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        setattr(modulo, "obter_db", lambda db=db: db)
    return db


def cabecalho(t):
    print("\n" + "=" * 76)
    print(t)
    print("=" * 76)


def tentar(rotulo, coro):
    try:
        r = _corre(coro)
    except HTTPException as e:
        print("  %-38s -> %s %s" % (rotulo, e.status_code, e.detail[:120]))
        return ("HTTP", e.status_code)
    print("  %-38s -> %r" % (rotulo, r if not isinstance(r, dict) else
                             {k: r[k] for k in list(r)[:3]}))
    return r


# ------------------------------------------------ FAMÍLIA (a): sem ext_ref ---
def familia_a_reserva_sem_ext_ref():
    cabecalho("(a) RESERVA VIVA SEM ext_ref — dados estragados, 11,64 EUR")
    # Turno JÁ FECHADO: é assim que ela chega à lista do gestor (com o turno
    # a decorrer fica só no diálogo do fecho, que é a família (b)).
    db = monta(
        sessoes=[_sessao(estado="fechada")],
        vendas=[_venda(id="conta", loja_id=_LOJA, sessao_id=_SESSAO,
                       dispositivo_id="pc-balcao", linhas=_LINHAS,
                       criada_em="2026-08-21T10:00:00+00:00")],
        refs=[{"id": "ref-1", "venda_id": "conta", "ext_ref": None,
               "criado_em": "2026-08-21T10:02:00+00:00", "documento_id": None}],
    )
    lista = _corre(listar_contas_esquecidas(_=_GESTOR))
    print("  GET /caixa/contas-esquecidas ......... %r" % (
        [(c["id"], c["motivo"], c["total"], c["reserva_fiscal_por_resolver"])
         for c in lista],))
    presas = _corre(listar_reservas_presas())
    print("  GET /fiscal/reservas-presas .......... %r" % (
        [(r["venda_id"], r["motivo"], r["ext_ref"]) for r in presas],))
    saidas = []
    saidas.append(tentar("POST arrumar", arrumar_conta_esquecida("conta", gestor=_GESTOR)))
    saidas.append(tentar("POST libertar", libertar_reserva_presa(
        "conta", PedidoLibertarReserva(confirmado_no_vendus=True), gestor=_GESTOR)))
    saidas.append(tentar("POST reconciliar", reconciliar_reserva_presa(
        "conta", None, gestor=_GESTOR)))
    executaveis = [s for s in saidas if not (isinstance(s, tuple) and s[0] == "HTTP")]
    print("  --> saídas EXECUTÁVEIS: %d" % len(executaveis))
    return len(executaveis)


# -------------------------------------------- FAMÍLIA (b): posto que morreu ---
def familia_b_posto_que_morreu():
    cabecalho("(b) CONTA ABERTA NUM POSTO QUE JÁ NÃO EXISTE, turno a decorrer")
    db = monta(vendas=[_venda(
        id="conta", loja_id=_LOJA, sessao_id=_SESSAO,
        dispositivo_id="pc-que-morreu", posto_em_curso="%s|pc-que-morreu" % _LOJA,
        linhas=_LINHAS, criada_em="2026-08-21T10:00:00+00:00")])
    op = _operador(dispositivo_id="pc-balcao")

    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO, dispositivo_id="pc-balcao"))
    print("  diálogo do fecho / Z ................. quantas=%s total=%.2f" % (
        dialogo["quantas"], dialogo["total"]))
    print("  GET /pos/venda/aberta (pc-balcao) .... %r" % (
        _corre(venda_aberta("caixa-1", operador=op)),))
    print("  GET /pos/venda/repartidas ............ %r" % (
        _corre(contas_repartidas("caixa-1", operador=op)),))
    print("  GET /caixa/contas-esquecidas ......... %r" % (
        [c["id"] for c in _corre(listar_contas_esquecidas(_=_GESTOR))],))
    saidas = []
    saidas.append(tentar("POST arrumar", arrumar_conta_esquecida("conta", gestor=_GESTOR)))
    saidas.append(tentar("POST entregar-ao-gestor", entregar_ao_gestor("conta", operador=op)))
    executaveis = [s for s in saidas if not (isinstance(s, tuple) and s[0] == "HTTP")]
    print("  --> saídas EXECUTÁVEIS com o turno aberto: %d" % len(executaveis))
    return len(executaveis)


# ------------------------------------------------------- menor: a frase falsa ---
def menor_a_frase_da_orfa():
    cabecalho("menor — _MSG_CONTA_ESQUECIDA_TRAVADA nomeia RECONCILIAR à órfã")
    db = monta(
        vendas=[],
        sessoes=[_sessao(estado="fechada")],
        refs=[{"id": "ref-1", "venda_id": "orfa",
               "ext_ref": ext_ref_determinista(_LOJA, _SESSAO, "orfa"),
               "criado_em": "2026-08-21T10:02:00+00:00", "documento_id": None}],
    )
    print("  GET /caixa/contas-esquecidas ......... %r" % (
        [(c["id"], c["motivo"]) for c in _corre(listar_contas_esquecidas(_=_GESTOR))],))
    tentar("POST arrumar", arrumar_conta_esquecida("orfa", gestor=_GESTOR))
    tentar("POST reconciliar", reconciliar_reserva_presa("orfa", None, gestor=_GESTOR))


if __name__ == "__main__":
    a = familia_a_reserva_sem_ext_ref()
    b = familia_b_posto_que_morreu()
    menor_a_frase_da_orfa()
    cabecalho("DEFEITO REPRODUZIDO?")
    print("  (a) reserva viva sem ext_ref .... saídas executáveis = %d" % a)
    print("  (b) posto que morreu ............ saídas executáveis = %d" % b)
