"""A conta TRAVADA que sai do balcão — e a conta que ressuscitava dentro da
fatura do cliente seguinte.

**A raiz, e é dela que tudo o resto sai.** O conjunto que a PORTA contava
(`venda.py::_conta_por_resolver`, todas as `aberta` do posto menos as
travadas) e o conjunto que o ECRÃ mostrava (`GET /pos/venda/aberta`, a mais
recente, sem a excepção) não eram o mesmo conjunto. Enquanto houvesse uma
conta só, batiam certo — e foi por isso que passou.

A diferença entrava pela excepção da travada, e essa excepção era **calculada**
(existe uma reserva em `fat_refs_fiscais`?) e não **gravada**. Deixava de ser
verdade no instante em que o gestor resolvesse a reserva — e
`fiscal.py::libertar_reserva_presa` não toca na venda por desenho.

**O GRAVE, reproduzido pelas rotas reais antes da correcção**, com a saída
medida do guião::

    1. cliente A: 8.99 EUR
    2. A travada (reserva fiscal viva): emissao_por_confirmar=True
    3. cliente B aberto por cima da travada: 2.00 EUR
       abertas neste PC: 2   no ecrã: 1        <- 8,99 € abertos e invisíveis
    4. o gestor liberta a reserva de A -> a venda A fica ['aberta']
    5. B emitida
    6. o ecrã põe à frente: A   emissao_por_confirmar=False
       conta_mae_id=None   total=8.99   linhas=['Açaí Regular']
    7. o cliente seguinte pede uma Coca-Cola:
       conta = ['Açaí Regular', 'Coca-Cola']   total: 10.99 EUR
       a Fatura Simplificada que sairia:
         [('Açaí Regular', 1.0, 8.99), ('Coca-Cola', 1.0, 2.0)]

A Fatura Simplificada do cliente novo levava o açaí do cliente anterior.

**A correcção é uma marca GRAVADA na venda** (`entregue_ao_gestor_em`), posta
por uma acção da operadora (`POST /pos/venda/{id}/entregar-ao-gestor`, o botão
"Servir o cliente seguinte"). A partir dela a conta sai do conjunto da porta e
do conjunto do ecrã AO MESMO TEMPO — os dois lêem o mesmo
`venda.py::_filtro_do_balcao` —, e continua a ser do gestor depois de ele
libertar a reserva.

Os duplos (base de dados falsa, fixtures) são os de `test_venda.py`,
importados e não copiados: uma segunda cópia divergia no dia em que a primeira
mudasse, e a divergência entre duas descrições da mesma conta é exactamente o
defeito que este ficheiro guarda.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import arrumar_conta_esquecida, listar_contas_esquecidas
from faturacao.db import COLECOES
from faturacao.fiscal import PedidoLibertarReserva, libertar_reserva_presa
from faturacao.venda import (
    PedidoDividir,
    PedidoJuntarLinha,
    PedidoNovaVenda,
    abrir_venda,
    cancelar_venda,
    contas_repartidas,
    dividir_conta,
    entregar_ao_gestor,
    juntar_linha,
    venda_aberta,
)
from tests.faturacao.test_venda import (
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
_COLA = {"id": "prod-cola", "nome": "Coca-Cola", "preco": 2.00, "tax_id": "NOR",
         "categoria_id": "cat-1", "foto_url": None, "grupos_personalizacao": [],
         "ativo": True, "vendus_ref": None}


def _monta(monkeypatch, vendas=None, refs=None, sessoes=None, caixas=None,
           com_indice=False, ceder=False):
    """A loja: uma caixa, uma sessão aberta, dois produtos. As três rotas que
    este ficheiro cruza (venda, fiscal, caixa) vêem a MESMA base — é esse
    cruzamento que o defeito precisava para acontecer."""
    registo = []
    db = _db(
        registo,
        caixas=caixas if caixas is not None else [_caixa()],
        sessoes=sessoes if sessoes is not None else [_sessao()],
        vendas=vendas,
        produtos=[_produto(), dict(_COLA)],
        refs=refs,
        com_indice_do_posto=com_indice,
        ceder=ceder,
    )
    for mod in (venda_mod, fiscal_mod, caixa_mod):
        monkeypatch.setattr(mod, "obter_db", lambda: db)
    return db


def _op(**over):
    return _operador(dispositivo_id=_PC, **over)


def _vendas_cruas(db):
    return db._coleccoes[COLECOES["vendas"]]._documentos


def _abertas_do_posto(db, dispositivo_id=_PC):
    return [d for d in _vendas_cruas(db)
            if d["estado"] == "aberta" and d.get("dispositivo_id") == dispositivo_id]


def _travar(db, venda_id, criado_em="2026-08-15T09:06:00+00:00"):
    """A reserva fiscal como `fiscal.py::_reservar` a insere — é ela, e só
    ela, que faz uma conta estar TRAVADA. `criado_em` velho de propósito: a
    rota do gestor recusa-se a libertar uma reserva recente."""
    _corre(db[COLECOES["refs_fiscais"]].insert_one(
        _reserva(id="ref-%s" % venda_id, venda_id=venda_id, criado_em=criado_em,
                 ext_ref="pos-loja-1-sessao-1-%s" % venda_id)))


def _cliente_a_com_acai(db):
    """O cliente A: uma conta com um Açaí Regular de 8,99 €, travada por uma
    emissão que o Vendus não confirmou."""
    a = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    a = _corre(juntar_linha(
        a["id"], PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=_op()))
    _travar(db, a["id"])
    return a


# --- O GRAVE ------------------------------------------------------------------


def test_a_conta_do_cliente_anterior_nao_ressuscita_na_fatura_do_seguinte(monkeypatch):
    """**O defeito medido, do princípio ao fim, pelas rotas reais.**

    Os sete passos do guião de reprodução, agora com a marca: o que mudou é o
    passo 3 (largar passou a ser uma escrita no servidor) e o passo 6 (a conta
    do cliente A não volta à frente de ninguém).

    Os números são os que saíram: A = 8,99 €, B = 2,00 €, e a conta em que a
    Coca-Cola do cliente seguinte aterrava valia 10,99 € com DUAS linhas."""
    db = _monta(monkeypatch)

    # 1. e 2. O cliente A, e a emissão que ficou por confirmar.
    a = _cliente_a_com_acai(db)
    assert a["totais"]["total"] == 8.99
    assert _corre(venda_mod._emissao_por_confirmar(db, _vendas_cruas(db)[0])) is True

    # 3. A operadora toca em "Servir o cliente seguinte" — e isso é agora uma
    #    ESCRITA no servidor, não um gesto só do ecrã.
    entregue = _corre(entregar_ao_gestor(a["id"], operador=_op()))
    assert entregue["entregue_ao_gestor_em"]
    # Sai dos DOIS conjuntos ao mesmo tempo: a porta deixa passar, e o ecrã
    # fica vazio. É esta igualdade que é a correcção.
    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_op())) is None

    b = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    b = _corre(juntar_linha(
        b["id"], PedidoJuntarLinha(produto_id="prod-cola", quantidade=1), operador=_op()))
    assert b["totais"]["total"] == 2.00

    # 4. O gestor liberta a reserva presa de A (confirmou no Vendus que não
    #    saiu FS nenhuma). A venda continua `aberta` — e continua DELE.
    resultado = _corre(libertar_reserva_presa(
        a["id"], PedidoLibertarReserva(confirmado_no_vendus=True),
        gestor={"email": "gestor@lisbonb.com"}))
    assert resultado["libertada"] is True
    assert "continua a ser dele" in resultado["a_seguir"]

    # 5. O cliente B é cobrado.
    for d in _vendas_cruas(db):
        if d["id"] == b["id"]:
            d["estado"] = "emitida"

    # 6. O ecrã recarrega (F5, tela de descanso). A conta de A NÃO volta.
    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_op())) is None

    # 7. O cliente seguinte pede uma Coca-Cola: nasce uma conta NOVA, com uma
    #    linha só e 2,00 € — não os 10,99 € com o açaí de outra pessoa.
    nova = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    nova = _corre(juntar_linha(
        nova["id"], PedidoJuntarLinha(produto_id="prod-cola", quantidade=1),
        operador=_op()))
    assert nova["id"] not in (a["id"], b["id"])
    assert [li["produto_nome"] for li in nova["linhas"]] == ["Coca-Cola"]
    assert nova["totais"]["total"] == 2.00

    # E a conta de A ficou intacta, com o açaí dela e mais nada.
    guardada = [d for d in _vendas_cruas(db) if d["id"] == a["id"]][0]
    assert [li["produto_nome"] for li in guardada["linhas"]] == ["Açaí Regular"]


def test_o_gestor_libertar_a_reserva_nao_devolve_a_conta_ao_balcao(monkeypatch):
    """A metade do GRAVE que se pode dizer numa frase: a marca sobrevive ao
    `libertar`.

    Era aqui que a excepção calculada morria — apagada a reserva, a conta
    voltava sozinha ao conjunto da porta e ao do ecrã, sem ninguém ter escrito
    nada. A marca está gravada NA VENDA, e `libertar_reserva_presa` não toca na
    venda (por desenho, e continua a não tocar)."""
    db = _monta(monkeypatch)
    a = _cliente_a_com_acai(db)
    _corre(entregar_ao_gestor(a["id"], operador=_op()))

    _corre(libertar_reserva_presa(
        a["id"], PedidoLibertarReserva(confirmado_no_vendus=True),
        gestor={"email": "gestor@lisbonb.com"}))

    guardada = [d for d in _vendas_cruas(db) if d["id"] == a["id"]][0]
    assert guardada["estado"] == "aberta"
    assert guardada["entregue_ao_gestor_em"], (
        "A marca desapareceu com o `libertar`. Se ela não sobrevive à reserva, "
        "a conta volta ao balcão à frente do cliente errado."
    )
    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_op())) is None
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"


def test_a_conta_escondida_atras_da_travada_volta_a_ficar_a_frente(monkeypatch):
    """**O outro ramo do mesmo buraco: o beco.** Com uma conta normal
    invisível (A) e uma travada à frente (B), tocar num produto dava 409, o
    ecrã repunha a travada, e repetia — não vendia, não via os 8,99 €, e o
    fecho de caixa também recusava.

    A conta A entra outra vez nos DOIS conjuntos, por isso: entregue a B, o
    ecrã põe A à frente, e a operadora resolve-a com os dedos."""
    db = _monta(monkeypatch, vendas=[
        _venda(id="conta-A", dispositivo_id=_PC, linhas=[_linha()],
               criada_em="2026-08-15T09:05:00+00:00"),
        _venda(id="conta-B", dispositivo_id=_PC, linhas=[_linha()],
               criada_em="2026-08-15T09:10:00+00:00"),
    ])
    _travar(db, "conta-B")

    # A porta está fechada, e o que o ecrã mostra é a travada.
    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    assert excinfo.value.status_code == 409
    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_op()))["id"] == "conta-B"

    # Entregue a travada, o ecrã põe à frente a conta que estava escondida.
    _corre(entregar_ao_gestor("conta-B", operador=_op()))
    frente = _corre(venda_aberta(caixa_id="caixa-1", operador=_op()))
    assert frente["id"] == "conta-A"
    assert frente["totais"]["total"] == 8.99

    # E essa a operadora cancela — com os dedos, sem chamar ninguém.
    _corre(cancelar_venda("conta-A", operador=_op()))
    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_op())) is None
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"


# --- A porta e o ecrã contam o MESMO conjunto ---------------------------------


def test_sempre_que_a_porta_recusa_ha_alguma_coisa_a_frente(monkeypatch):
    """**A mensagem manda fazer o que se consegue mesmo fazer.**

    `_MSG_CONTA_POR_RESOLVER` diz «Acabe a que está à frente», e antes disto
    era mostrada em estados em que não havia nada à frente (o ecrã vazio depois
    de largar) e em estados em que o que estava à frente era precisamente a
    travada que a mesma frase dizia não contar.

    A propriedade que fecha isso não é o texto — é o conjunto: em TODOS os
    estados em que a porta recusa, `GET /pos/venda/aberta` tem uma conta para
    mostrar, e essa conta aceita pelo menos uma das três saídas que a frase
    nomeia. Aqui percorrem-se os três estados que produzem o 409 e executa-se
    a saída de cada um."""
    # 1. Uma conta normal por resolver: a saída é CANCELAR.
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    assert excinfo.value.status_code == 409
    frente = _corre(venda_aberta(caixa_id="caixa-1", operador=_op()))
    assert frente is not None and frente["id"] == "venda-1"
    _corre(cancelar_venda(frente["id"], operador=_op()))
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"

    # 2. Uma conta TRAVADA: a saída é ENTREGAR AO GESTOR.
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")
    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    assert excinfo.value.status_code == 409
    frente = _corre(venda_aberta(caixa_id="caixa-1", operador=_op()))
    assert frente is not None and frente["emissao_por_confirmar"] is True
    _corre(entregar_ao_gestor(frente["id"], operador=_op()))
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"

    # 3. Uma conta DIVIDIDA com partes por cobrar: a saída é cobrar ou
    #    cancelar cada parte, e o ecrã tem-nas todas.
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    partes = _corre(dividir_conta(
        "venda-1", PedidoDividir(partes=2), operador=_op()))["partes"]
    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    assert excinfo.value.status_code == 409
    assert _corre(venda_aberta(caixa_id="caixa-1", operador=_op())) is not None
    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_op()))
    assert [p["id"] for p in grupos[0]["partes"]] == [p["id"] for p in partes]
    for parte in partes:
        _corre(cancelar_venda(parte["id"], operador=_op()))
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"


def test_a_conta_entregue_sai_das_partes_por_cobrar_do_ecra(monkeypatch):
    """`GET /pos/venda/repartidas` lê o MESMO conjunto — uma PARTE travada que
    a operadora entregou ao gestor deixa de aparecer na lista de quem falta
    cobrar. Se aparecesse, o ecrã pedia-lhe para cobrar uma conta que a rota
    de cobrança recusa."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    partes = _corre(dividir_conta(
        "venda-1", PedidoDividir(partes=2), operador=_op()))["partes"]
    _travar(db, partes[0]["id"])

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_op()))
    assert len(grupos) == 1

    _corre(entregar_ao_gestor(partes[0]["id"], operador=_op()))
    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_op()))
    # O grupo continua lá pela OUTRA parte, que ainda está por cobrar — e a
    # entregue continua a aparecer DENTRO dele, marcada, porque a faixa diz
    # "faltam cobrar N de M" e o M não pode encolher.
    assert len(grupos) == 1
    entregues = [p for p in grupos[0]["partes"] if p["entregue_ao_gestor_em"]]
    assert [p["id"] for p in entregues] == [partes[0]["id"]]

    # A porta, essa, deixa-se prender só pela parte que ainda é do balcão.
    with pytest.raises(HTTPException):
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    _corre(cancelar_venda(partes[1]["id"], operador=_op()))
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"


# --- As recusas de `entregar_ao_gestor` ---------------------------------------


def test_so_a_conta_travada_se_entrega(monkeypatch):
    """Uma conta normal cobra-se ou cancela-se. Deixar entregar essa era
    reabrir «pôr uma conta de lado e cobrar outra» com uma marca oficial por
    cima — e nada é gravado na venda."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])

    with pytest.raises(HTTPException) as excinfo:
        _corre(entregar_ao_gestor("venda-1", operador=_op()))
    assert excinfo.value.status_code == 409
    assert "não está travada" in excinfo.value.detail
    assert _vendas_cruas(db)[0].get("entregue_ao_gestor_em") is None


def test_nao_se_entrega_a_conta_de_outro_posto(monkeypatch):
    """O `dispositivo_id` vem do TOKEN. O PC Drive-Thru não faz desaparecer do
    ecrã do PC Balcão a conta que alguém lá tem à frente."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")

    with pytest.raises(HTTPException) as excinfo:
        _corre(entregar_ao_gestor("venda-1", operador=_operador(dispositivo_id="pc-drive")))
    assert excinfo.value.status_code == 409
    assert "não é deste posto" in excinfo.value.detail
    assert _vendas_cruas(db)[0].get("entregue_ao_gestor_em") is None


def test_nao_se_entrega_duas_vezes(monkeypatch):
    """A segunda entrega é recusada, e quem decide é o `matched_count` da
    escrita CONDICIONADA — não a leitura de cima. O carimbo da primeira não se
    reescreve: o nome e a hora que ficam são os de quem a entregou mesmo."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")

    primeira = _corre(entregar_ao_gestor("venda-1", operador=_op()))
    with pytest.raises(HTTPException) as excinfo:
        _corre(entregar_ao_gestor("venda-1", operador=_op()))
    assert excinfo.value.status_code == 409
    guardada = _vendas_cruas(db)[0]
    assert guardada["entregue_ao_gestor_em"] == primeira["entregue_ao_gestor_em"]


def test_duas_entregas_ao_mesmo_tempo_so_carimbam_uma(monkeypatch):
    """**A escrita da marca é CONDICIONADA, e é o `matched_count` que decide.**

    A leitura de cima (`_garante_do_balcao`) não chega: entre ela e a escrita
    há `await`s — a pergunta pela reserva fiscal —, e nessa janela um segundo
    separador do POS pode ter entregue a mesma conta. Sem a condição, o
    segundo carimbo escrevia-se por cima do primeiro e o gestor ficava com o
    nome e a hora ERRADOS na única conta em que vai ter de perguntar a alguém
    o que aconteceu àquele cliente. Pior ainda com o `finalizar` a ganhar a
    corrida: a marca aterrava numa venda que ACABOU de receber uma Fatura
    Simplificada real.

    O duplo cede o event loop em cada ida à base de dados, que é o que o Motor
    faz contra o Mongo real — sem isso as duas corriam uma DEPOIS da outra e o
    teste ficava verde a testar o caminho sequencial."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])],
                ceder=True)
    _travar(db, "venda-1")

    async def duas_ao_mesmo_tempo():
        return await asyncio.gather(
            entregar_ao_gestor("venda-1", operador=_op(nome="Rafaela")),
            entregar_ao_gestor("venda-1", operador=_op(nome="Ana")),
            return_exceptions=True,
        )

    resultados = _corre(duas_ao_mesmo_tempo())
    entregues = [r for r in resultados if isinstance(r, dict)]
    recusas = [r for r in resultados if isinstance(r, HTTPException)]
    assert len(entregues) == 1, (
        "As duas carimbaram: %r" % [type(r).__name__ for r in resultados])
    assert len(recusas) == 1 and recusas[0].status_code == 409

    guardada = _vendas_cruas(db)[0]
    assert guardada["entregue_ao_gestor_em"] == entregues[0]["entregue_ao_gestor_em"]
    assert guardada["entregue_ao_gestor_por"] == entregues[0]["entregue_ao_gestor_por"]


def test_nao_se_carimba_uma_conta_que_ja_deixou_de_estar_aberta(monkeypatch):
    """A outra metade da mesma condição: `estado: "aberta"` no filtro. Se o
    `finalizar` emitir esta venda entre a leitura e a escrita, a marca NÃO
    aterra — carimbar "é do gestor" numa venda com Fatura Simplificada real é
    escondê-la do único sítio onde ela conta como receita."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")

    # A emissão ganha a corrida, exactamente na janela entre a leitura da rota
    # e a escrita dela: `_emissao_por_confirmar` é o último `await` antes do
    # `update_one`.
    original = venda_mod._emissao_por_confirmar

    async def emite_no_meio(db_, venda):
        resposta = await original(db_, venda)
        for d in _vendas_cruas(db):
            if d["id"] == "venda-1":
                d["estado"] = "emitida"
        return resposta

    monkeypatch.setattr(venda_mod, "_emissao_por_confirmar", emite_no_meio)

    with pytest.raises(HTTPException) as excinfo:
        _corre(entregar_ao_gestor("venda-1", operador=_op()))
    assert excinfo.value.status_code == 409
    assert _vendas_cruas(db)[0].get("entregue_ao_gestor_em") is None


def test_a_conta_entregue_nao_aceita_mais_escritas_do_balcao(monkeypatch):
    """Os ecrãs do POS desenham-se sem servidor nenhum: tirar a conta do ecrã
    não impede um pedido feito com o id dela na mão (a nota do painel mostra-o,
    um separador antigo ainda o tem). Quem recusa é a rota.

    Depois de o gestor libertar a reserva — o momento em que
    `_garante_sem_emissao` deixa de a proteger — é esta guarda que fica de pé,
    e é a única."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")
    _corre(entregar_ao_gestor("venda-1", operador=_op()))
    _corre(libertar_reserva_presa(
        "venda-1", PedidoLibertarReserva(confirmado_no_vendus=True),
        gestor={"email": "gestor@lisbonb.com"}))

    with pytest.raises(HTTPException) as excinfo:
        _corre(juntar_linha(
            "venda-1", PedidoJuntarLinha(produto_id="prod-cola", quantidade=1),
            operador=_op()))
    assert excinfo.value.status_code == 409
    assert "entregue ao gestor" in excinfo.value.detail
    assert len(_vendas_cruas(db)[0]["linhas"]) == 1


# --- E do outro lado: o GESTOR fica mesmo com ela -----------------------------


def test_a_conta_entregue_aparece_na_lista_do_gestor_com_o_turno_aberto(monkeypatch):
    """A lista das contas por resolver excluía as sessões ABERTAS, com a razão
    de que «essa conta está no ecrã de alguém neste instante». Deixou de ser
    verdade para esta família: a entregue foi tirada do balcão de propósito, e
    se esta lista também a excluísse ela não aparecia em sítio NENHUM — nem no
    POS, nem nas reservas presas depois de o gestor libertar a reserva."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")

    # Antes de ser entregue, é uma conta do turno a decorrer — e não é um
    # esquecimento de ninguém.
    assert _corre(listar_contas_esquecidas(_={"email": "g"})) == []

    _corre(entregar_ao_gestor("venda-1", operador=_op()))
    lista = _corre(listar_contas_esquecidas(_={"email": "g"}))
    assert [c["id"] for c in lista] == ["venda-1"]
    assert lista[0]["sessao_estado"] == "aberta"
    assert lista[0]["total"] == 8.99
    assert lista[0]["reserva_fiscal_por_resolver"] is True
    assert lista[0]["entregue_ao_gestor_por"]["nome"] == "Rafaela"


def test_o_gestor_pode_arrumar_a_conta_entregue_sem_esperar_pelo_fecho(monkeypatch):
    """A promessa do outro lado: ela continua dele ATÉ ELE A RESOLVER. O botão
    de dar por perdida recusava-se com o turno aberto («isso resolve-se no POS,
    por quem lá está») — e para esta conta não há ninguém no POS que lhe
    chegue. A recusa da reserva fiscal fica de pé: essa vai primeiro a
    Reservas Fiscais Presas."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")
    _corre(entregar_ao_gestor("venda-1", operador=_op()))

    with pytest.raises(HTTPException) as excinfo:
        _corre(arrumar_conta_esquecida("venda-1", gestor={"email": "g", "user_id": "u"}))
    assert excinfo.value.status_code == 409

    _corre(libertar_reserva_presa(
        "venda-1", PedidoLibertarReserva(confirmado_no_vendus=True),
        gestor={"email": "gestor@lisbonb.com"}))
    arrumada = _corre(arrumar_conta_esquecida(
        "venda-1", gestor={"email": "gestor@lisbonb.com", "user_id": "u"}))
    assert arrumada["estado"] == "cancelada"
    assert _corre(listar_contas_esquecidas(_={"email": "g"})) == []


def test_a_conta_entregue_continua_a_travar_o_fecho_e_a_contar_no_z(monkeypatch):
    """Sair do BALCÃO não é ser cobrada. Enquanto a reserva fiscal viver, pode
    estar a nascer uma Fatura Simplificada real do outro lado, e fechar a caixa
    a meio disso é fechar as contas antes de o dinheiro estar contado — seja de
    quem for a conta. E o Z é o único registo de que aqueles 8,99 € ficaram por
    receber neste turno: se ela saísse dali, o dinheiro voltava a ser
    invisível."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    _travar(db, "venda-1")
    _corre(entregar_ao_gestor("venda-1", operador=_op()))

    presa = _corre(caixa_mod._venda_com_emissao_viva(db, "sessao-1"))
    assert presa is not None and presa["id"] == "venda-1"

    retrato = _corre(caixa_mod._contas_abertas_da_sessao(db, "sessao-1"))
    assert retrato["quantas"] == 1
    assert retrato["total"] == 8.99
    assert retrato["contas"][0]["trava_o_fecho"] is True
    assert retrato["contas"][0]["entregue_ao_gestor"] is True, (
        "O diálogo do fecho lista esta conta e manda cobrá-la ou cancelá-la — "
        "duas coisas que a operadora não consegue fazer a uma conta do gestor."
    )


# --- Os menores que a raiz arrastou -------------------------------------------


def test_o_ambito_da_recusa_e_o_POSTO_e_nao_a_caixa_do_corpo(monkeypatch):
    """O `caixa_id` vem do CORPO do pedido. Numa loja com duas caixas activas,
    o mesmo PC com o mesmo token abria uma conta em cada — e a segunda ficava
    fora do ecrã, que segue a caixa guardada no localStorage. Um PC atende um
    cliente de cada vez, seja qual for a caixa que o corpo nomeie."""
    db = _monta(
        monkeypatch,
        caixas=[_caixa(), _caixa(id="caixa-2", nome="Drive")],
        sessoes=[_sessao(), _sessao(id="sessao-2", caixa_id="caixa-2")],
        vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])],
    )

    with pytest.raises(HTTPException) as excinfo:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))
    assert excinfo.value.status_code == 409
    assert len(_abertas_do_posto(db)) == 1

    # Resolvida a conta que estava presa na outra caixa, o posto está livre.
    _corre(cancelar_venda("venda-1", operador=_op()))
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))["sessao_id"] == "sessao-2"


def test_uma_conta_de_um_turno_fechado_de_outra_caixa_nao_prende_este(monkeypatch):
    """O alargamento do âmbito não pode arrastar turnos que já fecharam: só as
    sessões ABERTAS da loja entram na pergunta."""
    _monta(
        monkeypatch,
        caixas=[_caixa(), _caixa(id="caixa-2", nome="Drive")],
        sessoes=[_sessao(), _sessao(id="sessao-ontem", caixa_id="caixa-2",
                                    estado="fechada")],
        vendas=[_venda(dispositivo_id=_PC, sessao_id="sessao-ontem", linhas=[_linha()])],
    )
    assert _corre(abrir_venda(
        PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))["estado"] == "aberta"


def test_o_duplo_toque_nao_abre_duas_contas_no_mesmo_posto(monkeypatch):
    """**A corrida do duplo toque, e é o ÍNDICE que a fecha.**

    `abrir_venda` é ler-e-depois-escrever, sem lock: dois `POST /pos/venda`
    simultâneos do mesmo PC lêem os dois um balcão livre. Medido com o duplo a
    ceder o event loop em cada leitura (que é o que o Motor faz contra o Mongo
    real): **201 e 201, duas contas abertas neste posto, uma órfã**.

    O predicado da porta só se tornou expressável num índice depois de a
    excepção da travada deixar de ser calculada — o índice único parcial de
    `db.py` está sobre `posto_em_curso`, a etiqueta que `abrir_venda` escreve.
    Aqui o duplo faz cumprir esse índice, e quem perde a corrida sai com o
    MESMO 409 de quem a perdeu pela leitura."""
    db = _monta(monkeypatch, com_indice=True, ceder=True)

    async def duas_ao_mesmo_tempo():
        return await asyncio.gather(
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()),
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()),
            return_exceptions=True,
        )

    resultados = _corre(duas_ao_mesmo_tempo())
    criadas = [r for r in resultados if isinstance(r, dict)]
    recusas = [r for r in resultados if isinstance(r, HTTPException)]
    assert len(criadas) == 1, (
        "As duas passaram: %r" % [type(r).__name__ for r in resultados])
    assert len(recusas) == 1 and recusas[0].status_code == 409
    assert len(_abertas_do_posto(db)) == 1


def test_a_entrega_liberta_o_posto_no_INDICE_e_nao_so_na_leitura(monkeypatch):
    """A etiqueta `posto_em_curso` é a chave do índice único parcial, e é
    `entregar_ao_gestor` o ÚNICO sítio do módulo que a tira (as outras saídas
    da conta tiram-se sozinhas pelo `estado`, que sai do filtro parcial).

    Esquecer o `$unset` era o pior desfecho possível desta ronda: a leitura
    deixava passar, o índice não, e o balcão ficava trancado com um 409 por uma
    conta que já é do gestor — para o resto do turno."""
    db = _monta(monkeypatch, com_indice=True)
    a = _cliente_a_com_acai(db)
    # A etiqueta LIDA da função que a escreve, nunca copiada para aqui: ela
    # mudou de âmbito (era `"{sessao_id}|{dispositivo_id}"`, é agora
    # `"{loja_id}|{dispositivo_id}"` — ver `venda._etiqueta_do_posto`), e uma
    # cópia local prendia este teste ao formato de ontem em vez de à garantia.
    assert [d.get("posto_em_curso") for d in _vendas_cruas(db)] == [
        venda_mod._etiqueta_do_posto(_op()["loja_id"], _PC)]

    _corre(entregar_ao_gestor(a["id"], operador=_op()))
    assert "posto_em_curso" not in _vendas_cruas(db)[0], (
        "A conta entregue ficou com a etiqueta do posto: o índice único ainda a "
        "conta como a conta em curso, e a seguinte não nasce."
    )
    seguinte = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    assert seguinte["estado"] == "aberta"


def test_uma_parte_nao_se_volta_a_dividir(monkeypatch):
    """Dividir uma PARTE era aceite (201) e criava um SEGUNDO grupo de
    repartição no mesmo posto — e o ecrã só tem lugar para um. O grupo que
    ficasse de fora levava consigo as pessoas por cobrar dele, sem nada no ecrã
    a dizê-lo."""
    db = _monta(monkeypatch, vendas=[_venda(dispositivo_id=_PC, linhas=[_linha()])])
    partes = _corre(dividir_conta(
        "venda-1", PedidoDividir(partes=2), operador=_op()))["partes"]

    with pytest.raises(HTTPException) as excinfo:
        _corre(dividir_conta(partes[0]["id"], PedidoDividir(partes=2), operador=_op()))
    assert excinfo.value.status_code == 409
    assert "já é uma PARTE" in excinfo.value.detail
    # E não ficou nenhuma neta gravada.
    assert [d["conta_mae_id"] for d in _vendas_cruas(db) if d.get("conta_mae_id")] == [
        "venda-1", "venda-1"]
