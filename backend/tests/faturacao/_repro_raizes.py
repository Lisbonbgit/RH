"""Guião de REPRODUÇÃO das quatro raízes — não é um teste, é o instrumento.

Corre-se com:
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.faturacao._repro_raizes

Usa os mesmos duplos de test_venda.py e as ROTAS REAIS.
"""
import asyncio
import sys

from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import (
    PedidoFecharCaixa,
    _contas_esquecidas,
    _venda_com_emissao_viva,
    fechar_caixa,
)
from faturacao.db import COLECOES
from faturacao.fiscal import listar_reservas_presas, libertar_reserva_presa
from faturacao.fiscal import PedidoLibertarReserva
from faturacao.venda import (
    PedidoDividir,
    PedidoNovaVenda,
    abrir_venda,
    contas_repartidas,
    dividir_conta,
    venda_aberta,
)

from tests.faturacao.test_venda import (
    ColeccaoFalsa,
    _caixa,
    _corre,
    _db,
    _linha,
    _operador,
    _produto,
    _reserva,
    _sessao,
    _venda,
)

_PC = "pc-balcao"


def op(**over):
    o = _operador(dispositivo_id=_PC)
    o.update(over)
    return o


def monta(vendas=None, refs=None, sessoes=None):
    db = _db(
        [], caixas=[_caixa()], sessoes=sessoes if sessoes is not None else [_sessao()],
        vendas=vendas, refs=refs, produtos=[_produto()],
        com_indice_do_posto=True,
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        setattr(modulo, "obter_db", lambda db=db: db)
    return db


def linha(preco, qtd=1, tax="INT", lid="l1"):
    return _linha(id=lid, produto_preco=preco, quantidade=qtd, produto_tax_id=tax)


def cabecalho(t):
    print("\n" + "=" * 76)
    print(t)
    print("=" * 76)


# ---------------------------------------------------------------- RAIZ 1 -----
def raiz1_janela_observavel():
    cabecalho("RAIZ 1a — as filhas são VISÍVEIS antes de a mãe travar")
    mae = _venda(
        id="mae", dispositivo_id=_PC, posto_em_curso="loja-1|%s" % _PC,
        linhas=[linha(10.20), linha(1.15, lid="l2", tax="NOR")],
        linhas_versao=0,
    )
    db = monta(vendas=[mae])
    col = db[COLECOES["vendas"]]
    visto = {}

    inserts = {"n": 0}
    original = col.insert_one

    async def insert_espia(doc):
        await original(doc)
        inserts["n"] += 1
        if inserts["n"] == 3:  # as três filhas já lá estão, a mãe ainda `aberta`
            visto["repartidas"] = await contas_repartidas("caixa-1", operador=op())
            visto["aberta"] = await venda_aberta("caixa-1", operador=op())
            visto["estado_da_mae"] = (await col.find_one({"id": "mae"}))["estado"]

    col.insert_one = insert_espia
    _corre(dividir_conta("mae", PedidoDividir(partes=3), operador=op()))
    col.insert_one = original

    print("  estado da mãe nesse instante ......... %r" % visto["estado_da_mae"])
    print("  GET /pos/venda/repartidas ............ %d grupo(s)" % len(visto["repartidas"]))
    for g in visto["repartidas"]:
        print("      modo=%r  mãe=%s  partes=%d" % (
            g["modo"], g["conta_mae"]["estado"], len(g["partes"])))
        for p in g["partes"]:
            print("        parte %s  %.2f EUR" % (p["id"][:8], p["totais"]["total"]))
    print("  GET /pos/venda/aberta ................ %s" % (
        "null" if visto["aberta"] is None
        else "%s %.2f EUR (mae_id=%s)" % (
            visto["aberta"]["id"][:8], visto["aberta"]["totais"]["total"],
            visto["aberta"].get("conta_mae_id"))))
    return bool(visto["repartidas"]) or (
        visto["aberta"] is not None and visto["aberta"].get("conta_mae_id"))


def raiz1_separada_sem_partes():
    cabecalho("RAIZ 1b — uma mãe `separada` SEM partes: quem a vê?")
    mae = _venda(
        id="mae", dispositivo_id=_PC, estado="separada", reparticao_modo="dividir",
        linhas=[linha(10.20), linha(1.15, lid="l2", tax="NOR")],
    )
    db = monta(vendas=[mae])
    print("  conta: mãe `separada` sem filhas nenhumas, 11,35 EUR")
    print("  GET /pos/venda/aberta ................ %r" % _corre(
        venda_aberta("caixa-1", operador=op())))
    print("  GET /pos/venda/repartidas ............ %r" % _corre(
        contas_repartidas("caixa-1", operador=op())))
    esq = _corre(_contas_esquecidas(db))
    print("  GET /caixa/contas-esquecidas ......... %d" % len(esq))
    ab = _corre(caixa_mod._contas_abertas_da_sessao(db, "sessao-1"))
    print("  diálogo do fecho ..................... quantas=%d total=%.2f" % (
        ab["quantas"], ab["total"]))
    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=op()))
    print("  POST /pos/caixa/fechar ............... %s" % z["estado"])
    print("      Z: por cobrar %.2f EUR (%d contas)   esperado=%.2f" % (
        z["contas_abertas"]["total"], z["contas_abertas"]["quantas"], z["esperado"]))
    return z["contas_abertas"]["total"] == 0.0


# ---------------------------------------------------------------- RAIZ 2 -----
def raiz2_travao_vs_dialogo():
    cabecalho("RAIZ 2 — o travão vê a reserva órfã, o diálogo do fecho não")
    # Uma reserva desta sessão cuja VENDA já não existe (filha apagada pela
    # compensação de `_grava_as_partes`).
    ref = _reserva(id="ref-orfa", ext_ref="pos-loja-1-sessao-1-filha-9",
                   venda_id="filha-9", documento_id=None)
    db = monta(vendas=[], refs=[ref])
    ab = _corre(caixa_mod._contas_abertas_da_sessao(db, "sessao-1"))
    print("  GET /pos/caixa/contas-abertas (o que ela assina) .. quantas=%d total=%.2f"
          % (ab["quantas"], ab["total"]))
    presas = _corre(listar_reservas_presas())
    print("  GET /fiscal/reservas-presas ...................... %d (venda=%r)"
          % (len(presas), presas[0]["estado_da_venda"] if presas else None))
    travao = _corre(_venda_com_emissao_viva(db, _sessao()))
    print("  o travão do fecho ................................ %r" % (travao,))
    try:
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=op()))
        print("  POST /pos/caixa/fechar ........................... 200")
        return False
    except HTTPException as e:
        print("  POST /pos/caixa/fechar ........................... %d" % e.status_code)
        print("      %s" % e.detail)
        return ab["quantas"] == 0


# ---------------------------------------------------------------- RAIZ 3 -----
def raiz3_libertar_faz_desaparecer():
    cabecalho("RAIZ 3 — LIBERTAR faz 11,64 EUR sair de um Z assinado")
    mae = _venda(
        id="mae", dispositivo_id=_PC, estado="separada", reparticao_modo="separar",
        linhas=[linha(10.20), linha(1.15, lid="l2", tax="NOR"), linha(0.29, lid="l3", tax="NOR")],
    )
    ref = _reserva(id="ref-1", ext_ref="pos-loja-1-sessao-1-mae", venda_id="mae",
                   documento_id=None)
    db = monta(vendas=[mae], refs=[ref])

    print("  antes de LIBERTAR:")
    ab = _corre(caixa_mod._contas_abertas_da_sessao(db, "sessao-1"))
    print("      diálogo do fecho ......... quantas=%d total=%.2f" % (ab["quantas"], ab["total"]))
    print("      /fiscal/reservas-presas .. %d" % len(_corre(listar_reservas_presas())))
    print("      /caixa/contas-esquecidas . %d" % len(_corre(_contas_esquecidas(db))))
    try:
        _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=op()))
        print("      POST /pos/caixa/fechar ... 200 (!)")
    except HTTPException as e:
        print("      POST /pos/caixa/fechar ... %d" % e.status_code)

    gestor = {"id": "g1", "nome": "Gestor", "perfil": "gestor"}
    r = _corre(libertar_reserva_presa(
        "mae", PedidoLibertarReserva(confirmado_no_vendus=True), gestor=gestor))
    print("  POST /fiscal/reservas-presas/.../libertar -> libertada=%r" % r.get("libertada"))

    print("  depois de LIBERTAR:")
    print("      GET /pos/venda/aberta .... %r" % _corre(venda_aberta("caixa-1", operador=op())))
    print("      /fiscal/reservas-presas .. %d" % len(_corre(listar_reservas_presas())))
    print("      /caixa/contas-esquecidas . %d" % len(_corre(_contas_esquecidas(db))))
    ab = _corre(caixa_mod._contas_abertas_da_sessao(db, "sessao-1"))
    print("      diálogo do fecho ......... quantas=%d total=%.2f" % (ab["quantas"], ab["total"]))
    z = _corre(fechar_caixa(PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=op()))
    print("      POST /pos/caixa/fechar ... 200, Z ASSINADO com por cobrar %.2f EUR"
          % z["contas_abertas"]["total"])
    conta = _corre(db[COLECOES["vendas"]].find_one({"id": "mae"}))
    from faturacao.venda import _totais
    print("      ... e na base está uma conta %r de %.2f EUR"
          % (conta["estado"], _totais(conta)["total"]))
    return z["contas_abertas"]["total"] == 0.0


# ---------------------------------------------------------------- RAIZ 4 -----
def raiz4_mapa_arredonda_no_turno():
    cabecalho("RAIZ 4 — o mapa arredonda ao nível do TURNO, não do documento")
    import random
    from faturacao.mapa_imposto import (
        _base_em_centimos, _centimos, _itens_vendus, _liquido_da_linha,
        mapa_de_imposto, totais_do_mapa,
    )

    def soma_documento_a_documento(vendas):
        base = iva = total = 0
        for v in vendas:
            if v.get("estado") != "emitida":
                continue
            por_taxa = {}
            for item in _itens_vendus(v):
                por_taxa[item.get("tax_id")] = (
                    por_taxa.get(item.get("tax_id"), 0)
                    + _centimos(_liquido_da_linha(item)))
            for tax_id, c in por_taxa.items():
                from faturacao.mapa_imposto import _TAXA_DO_CODIGO
                taxa = _TAXA_DO_CODIGO.get(tax_id)
                total += c
                if taxa is not None:
                    b = _base_em_centimos(c, taxa)
                    base += b
                    iva += c - b
        return base, iva, total

    random.seed(20260821)
    precos = [0.29, 1.15, 10.20, 8.99, 2.99, 3.45, 0.85, 6.30, 12.75, 1.99]
    iguais = 0
    piores = []
    for turno in range(40):
        vendas = []
        for d in range(180):
            linhas = []
            for k in range(random.randint(1, 4)):
                linhas.append(_linha(
                    id="l%d" % k, produto_preco=random.choice(precos),
                    quantidade=random.randint(1, 3),
                    produto_tax_id=random.choice(["INT", "NOR"])))
            vendas.append(_venda(id="v%d" % d, estado="emitida", linhas=linhas))
        mapa = mapa_de_imposto(vendas)
        t = totais_do_mapa(mapa)
        b2, i2, tot2 = soma_documento_a_documento(vendas)
        if _centimos(t["base"]) == b2:
            iguais += 1
        else:
            piores.append((
                _centimos(t["base"]) - b2, t["total"], t["base"], b2 / 100.0))
    print("  40 turnos de 180 documentos: coincidiu em %d" % iguais)
    piores.sort(key=lambda x: x[0])
    for d, tot, bz, bd in piores[:2] + piores[-2:]:
        print("      turno de %8.2f EUR: Z diz base %.2f, doc-a-doc %.2f  (%+d cent)"
              % (tot, bz, bd, d))
    return iguais < 40


# ------------------------------------------------- CONTROLO DO INSTRUMENTO ---
#
# Desliga cada correcção EM MEMÓRIA, sem tocar no repositório. Se o defeito não
# voltar, é o arnês que está a mentir — não a correcção que está lá.


def desliga_raiz1():
    """A mãe deixa de ser o interruptor: uma parte volta a existir para
    toda a gente mal seja inserida."""
    import faturacao.por_resolver as pr

    async def sempre(db, venda, conhecidas):
        return True
    pr._mae_ja_travou = sempre


def desliga_raiz1b():
    """Uma mãe `separada` volta a ser sempre 'resolvida' — com partes ou
    sem elas."""
    import faturacao.por_resolver as pr

    async def sempre(db, venda_id):
        return True
    pr._tem_partes = sempre


def desliga_raiz2():
    """O diálogo do fecho volta a PARTIR das vendas: uma reserva cuja venda
    já não existe deixa de lhe chegar. O travão continua a vê-la — que é
    exactamente a divergência que se mediu."""
    import faturacao.caixa as c
    import faturacao.por_resolver as pr
    original = pr.contas_por_resolver
    normal = c._contas_abertas_da_sessao

    async def so_as_que_tem_venda(db, sessao_id, dispositivo_id=None):
        async def filtrada(db2, ids):
            return [i for i in await original(db2, ids) if i["venda"] is not None]
        pr.contas_por_resolver = filtrada
        try:
            return await normal(db, sessao_id, dispositivo_id=dispositivo_id)
        finally:
            pr.contas_por_resolver = original
    c._contas_abertas_da_sessao = so_as_que_tem_venda


def desliga_raiz4():
    """O mapa volta a arredondar uma vez só, no fim, sobre o total do turno."""
    import faturacao.mapa_imposto as mi
    original = mi.mapa_de_imposto

    def como_era(vendas):
        saida = original(vendas)
        for linha in saida:
            if linha["taxa"] is None:
                continue
            centimos = mi._centimos(linha["total"])
            base = mi._base_em_centimos(centimos, linha["taxa"])
            linha["base"] = base / 100.0
            linha["iva"] = (centimos - base) / 100.0
        return saida
    mi.mapa_de_imposto = como_era
    import faturacao.caixa  # noqa: F401 — o import de `_resumo_do_turno` é local


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    controlo = "--controlo" in argumentos
    quais = [a for a in argumentos if a != "--controlo"] or ["1a", "1b", "2", "3", "4"]
    if controlo:
        cabecalho("CONTROLO DO INSTRUMENTO — correcções desligadas em memória")
        for q in quais:
            {"1a": desliga_raiz1, "1b": desliga_raiz1b, "2": desliga_raiz2,
             "3": desliga_raiz1b, "4": desliga_raiz4}[q]()
    tabela = {
        "1a": raiz1_janela_observavel,
        "1b": raiz1_separada_sem_partes,
        "2": raiz2_travao_vs_dialogo,
        "3": raiz3_libertar_faz_desaparecer,
        "4": raiz4_mapa_arredonda_no_turno,
    }
    resultados = {}
    for q in quais:
        try:
            resultados[q] = tabela[q]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            resultados[q] = "REBENTOU: %s" % e
    cabecalho("DEFEITO REPRODUZIDO?")
    for q, r in resultados.items():
        print("  raiz %-3s -> %r" % (q, r))
