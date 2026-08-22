"""Depois do Z, as contas por cobrar deixam de ficar sem caminho nenhum.

**O que se mediu.** 14,10 € divididos por 2, ninguém cobrado, caixa fechada,
turno seguinte aberto. `GET /pos/venda/repartidas` → `[]`; `GET
/pos/venda/aberta` → `null`; `GET /pos/caixa/contas-abertas` →
`{quantas: 0}`. As duas partes continuavam na base a `estado=aberta` com o
`sessao_id` do turno anterior, e **nenhum ecrã voltava a mostrá-las**. O
`contas_abertas` que o fecho grava na sessão não tinha um único leitor em todo
o repositório — escrevia-se para o Z de papel e mais nada.

Os ecrãs do POS não têm culpa disso: é o desenho deles, e está certo
(`venda_aberta` e `contas_repartidas` resolvem a sessão por `_sessao_aberta`,
porque um balcão só mostra o turno a decorrer). O que faltava era o outro
lado, e é do GESTOR — a pergunta é sobre dinheiro do passado, não sobre o
cliente que está à frente.

O que este ficheiro guarda:

- as contas de turnos FECHADOS aparecem, e as do turno a decorrer NÃO;
- cada uma diz de que turno é, de que caixa, quem estava a picar e quanto
  vale — o suficiente para ir perguntar o que aconteceu;
- a que tem uma reserva fiscal aparece MARCADA e não se arruma por aqui: essa
  é do card das reservas presas, onde se descobre se saiu uma FS real;
- arrumar delega em `venda.cancelar_venda` e não numa segunda cópia da
  escrita — é de lá que vem a compensação que repõe `aberta` se uma reserva
  aparecer no meio;
- e arrumar NÃO mexe no Z: o valor da conta fica igual ao que o Z registou.

Duplo de base de dados no padrão de test_contas_abertas_no_fecho.py. Nenhum
teste liga a uma base de dados nem à rede.
"""
import asyncio
import pathlib
import re
from copy import deepcopy

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import (
    _MSG_CONTA_ESQUECIDA_DE_TURNO_ABERTO,
    _MSG_CONTA_ESQUECIDA_JA_RESOLVIDA,
    _MSG_CONTA_ESQUECIDA_TRAVADA,
    arrumar_conta_esquecida,
    listar_contas_esquecidas,
)
from faturacao.db import COLECOES
# A `ext_ref` das reservas dos cenários sai da função que a GERA, nunca de uma
# cópia do formato escrita aqui: o predicado único (`por_resolver`) pergunta
# pelas reservas pelo PREFIXO da sessão.
from faturacao.fiscal import ext_ref_determinista


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    if not filtro:
        return True
    for chave, valor in filtro.items():
        # `$or` e `$nin` — ver o mesmo ramo em test_venda.py. É por eles que
        # `por_resolver.contas_por_resolver` pergunta pelas RESERVAS de várias
        # sessões de uma vez e pelas vendas em estado NÃO TERMINAL. Um duplo
        # que os ignorasse tratava "$or" como um campo do documento (nenhuma
        # reserva casava) e `$nin` como um valor a comparar (casava com tudo,
        # `emitida` incluída) — metade do predicado ficava verde sem correr.
        if chave == "$or":
            if not any(_corresponde(item, sub) for sub in valor):
                return False
        elif isinstance(valor, dict) and "$nin" in valor:
            if item.get(chave) in valor["$nin"]:
                return False
        elif isinstance(valor, dict) and "$in" in valor:
            if item.get(chave) not in valor["$in"]:
                return False
        # `$ne`, e não é um extra decorativo: é por ele que o travão do fecho
        # pergunta pelas contas que ainda NÃO estão `emitida`
        # (`caixa._venda_com_emissao_viva`). Um duplo que o ignorasse casava
        # com tudo e punha o teste a medir o contrário do que diz.
        elif isinstance(valor, dict) and "$ne" in valor:
            if item.get(chave) == valor["$ne"]:
                return False
        # `$regex`, ancorado — é por ele que o travão do fecho pergunta pelas
        # RESERVAS desta sessão (`caixa._venda_com_emissao_viva`), pelo prefixo
        # `pos-{loja}-{sessão}-` da `ext_ref`. Um duplo que o ignorasse tratava
        # o dicionário como um valor a comparar, não casava com reserva
        # nenhuma, e o travão ficava verde sem nunca travar.
        elif isinstance(valor, dict) and "$regex" in valor:
            if not re.search(valor["$regex"], str(item.get(chave) or "")):
                return False
        elif item.get(chave) != valor:
            return False
    return True


class CursorFalso:
    def __init__(self, itens):
        self._itens = list(itens)

    def sort(self, campo, direccao=1):
        self._itens.sort(key=lambda d: d.get(campo) or "", reverse=(direccao == -1))
        return self

    async def to_list(self, n=None):
        return self._itens if n is None else self._itens[:n]


class ResultadoUpdateFalso:
    def __init__(self, matched_count):
        self.matched_count = matched_count
        self.modified_count = matched_count


class ColeccaoFalsa:
    def __init__(self, registo, nome, documentos=None):
        self.registo = registo
        self.nome = nome
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", self.nome, filtro))
        return CursorFalso(
            [deepcopy(d) for d in self._documentos if _corresponde(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", self.nome, filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return deepcopy(encontrados[0]) if encontrados else None

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", self.nome, filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdateFalso(matched_count=len(alvos))


class DbFalsa:
    def __init__(self, registo, coleccoes):
        self.registo = registo
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        if nome not in self._coleccoes:
            self._coleccoes[nome] = ColeccaoFalsa(self.registo, nome, [])
        return self._coleccoes[nome]


def _gestor(**over):
    g = {"user_id": "u-9", "email": "gestor@lojas.pt", "role": "admin"}
    g.update(over)
    return g


def _caixa(**over):
    c = {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão", "ativa": True}
    c.update(over)
    return c


def _sessao(**over):
    s = {
        "id": "sessao-ontem", "caixa_id": "caixa-1", "loja_id": "loja-1",
        "aberta_em": "2026-08-14T09:00:00+00:00", "fundo": 50.0,
        "estado": "fechada", "fechada_em": "2026-08-14T23:40:00+00:00",
        "fechada_por": {"id": "op-1", "nome": "Rafaela"},
    }
    s.update(over)
    return s


def _linha(**over):
    li = {
        "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 7.05, "produto_tax_id": "INT", "quantidade": 1, "opcoes": [],
        "respostas_texto": [], "preco_override": None, "tax_override": None,
        "desconto_pct": None, "desconto_eur": None,
    }
    li.update(over)
    return li


def _venda(**over):
    v = {
        "id": "parte-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "sessao_id": "sessao-ontem", "operador_id": "op-1",
        "dispositivo_id": "pc-balcao", "linhas": [_linha()], "linhas_versao": 0,
        "desconto_global_pct": None, "desconto_global_eur": None,
        "estado": "aberta", "criada_em": "2026-08-14T22:10:00+00:00",
        "conta_mae_id": "venda-mae",
    }
    v.update(over)
    return v


def _monta(monkeypatch, vendas, sessoes=None, caixas=None, refs=None):
    registo = []
    db = DbFalsa(registo, {
        COLECOES["caixas"]: ColeccaoFalsa(
            registo, "caixas", caixas if caixas is not None else [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(
            registo, "sessoes", sessoes if sessoes is not None else [_sessao()]),
        COLECOES["vendas"]: ColeccaoFalsa(registo, "vendas", vendas),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, "refs", refs),
        COLECOES["documentos"]: ColeccaoFalsa(registo, "documentos", []),
    })
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    # A OUTRA lista do gestor (`fiscal.listar_reservas_presas`) é metade da
    # resposta à pergunta «há aqui alguém que lhe possa pegar?» — sem ela,
    # um guarda sobre as saídas media meio ecrã.
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    return db, registo


# --- O buraco, com os números que se mediram -----------------------------------


def test_as_duas_partes_de_um_turno_fechado_voltam_a_aparecer(monkeypatch):
    """Os 14,10 € divididos por 2 e cobrados a ninguém: `[]` em todos os ecrãs
    do POS. Aqui aparecem as duas, com o valor."""
    _monta(monkeypatch, vendas=[
        _venda(id="parte-1"),
        _venda(id="parte-2", criada_em="2026-08-14T22:10:01+00:00"),
    ])

    lista = _corre(listar_contas_esquecidas(_=_gestor()))

    assert [c["id"] for c in lista] == ["parte-1", "parte-2"]
    assert sum(c["total"] for c in lista) == 14.10
    assert all(c["conta_mae_id"] == "venda-mae" for c in lista), (
        "«faltou cobrar uma pessoa» e «ficou uma conta a meio» são duas "
        "conversas diferentes com quem lá estava"
    )


def test_a_conta_do_turno_QUE_ESTA_ABERTO_nao_aparece(monkeypatch):
    """Essa está no ecrã de alguém neste instante e não é um esquecimento —
    pô-la aqui era chamar o gestor a uma conta que a operadora está a picar."""
    _monta(monkeypatch, vendas=[_venda(id="a-decorrer", sessao_id="sessao-hoje")],
           sessoes=[_sessao(id="sessao-hoje", estado="aberta")])

    assert _corre(listar_contas_esquecidas(_=_gestor())) == []


def test_uma_conta_de_uma_sessao_a_MEIO_de_um_fecho_aparece(monkeypatch):
    """`a_fechar` não é "aberta": ou o fecho se conclui e ela fica mesmo para
    trás, ou é desfeito e ela volta ao balcão. Aparecer aqui é o lado
    conservador — a lista é de leitura, e nada se perde por a ver."""
    _monta(monkeypatch, vendas=[_venda()], sessoes=[_sessao(estado="a_fechar")])

    lista = _corre(listar_contas_esquecidas(_=_gestor()))
    assert [c["sessao_estado"] for c in lista] == ["a_fechar"]


def test_uma_conta_cuja_sessao_desapareceu_tambem_aparece(monkeypatch):
    """Dinheiro sem turno nenhum é ainda mais invisível do que o resto. O
    `sessao_estado` fica a `None`, e isso é informação: quem lê distingue "o
    turno fechou" de "não há turno nenhum onde procurar"."""
    _monta(monkeypatch, vendas=[_venda(sessao_id="sessao-que-sumiu")], sessoes=[])

    lista = _corre(listar_contas_esquecidas(_=_gestor()))
    assert len(lista) == 1 and lista[0]["sessao_estado"] is None


def test_as_contas_ja_resolvidas_nao_aparecem(monkeypatch):
    """Uma conta emitida ou cancelada não tem nada por receber. Uma mãe
    `separada` COM partes também não: o dinheiro dela mudou-se para as filhas,
    e são elas que aparecem enquanto estiverem por cobrar."""
    _monta(monkeypatch, vendas=[
        _venda(id="emitida", estado="emitida"),
        _venda(id="cancelada", estado="cancelada"),
        _venda(id="mae", estado="separada"),
        _venda(id="filha", conta_mae_id="mae", estado="emitida"),
    ])

    assert _corre(listar_contas_esquecidas(_=_gestor())) == []


def test_uma_mae_separada_SEM_PARTES_nao_pode_ficar_calada(monkeypatch):
    """**11,64 € saíam de um Z assinado por aqui.** Uma mãe `separada` sem
    partes nenhumas é um estado que não devia existir (as filhas nascem antes
    de a mãe travar, `venda._grava_as_partes`, e um processo que morra entre as
    duas escritas deixa-a assim) — e enquanto todos os leitores filtrassem por
    `estado: "aberta"` ela não aparecia a NINGUÉM: nem no balcão, nem nesta
    lista, nem no diálogo do fecho, nem no Z.

    Não é reparada — ninguém sabe quais eram as partes que ela devia ter ——
    mas também não fica calada: aparece aqui, com o motivo escrito."""
    _monta(monkeypatch, vendas=[_venda(id="mae", estado="separada")])

    lista = _corre(listar_contas_esquecidas(_=_gestor()))
    assert [(c["id"], c["motivo"], c["estado_da_venda"]) for c in lista] == [
        ("mae", "mae_separada_sem_partes", "separada")], (
        "Uma mãe `separada` sem partes voltou a não aparecer em lado nenhum.")
    assert lista[0]["total"] == 7.05


def test_cada_conta_diz_onde_ficou_e_com_quem(monkeypatch):
    """O mínimo para o gestor ir perguntar o que aconteceu: de que caixa, de
    que turno, quando é que esse turno fechou e quem o fechou, e quem estava a
    picar."""
    _monta(monkeypatch, vendas=[_venda()])

    conta = _corre(listar_contas_esquecidas(_=_gestor()))[0]

    assert conta["caixa_nome"] == "Balcão"
    assert conta["sessao_id"] == "sessao-ontem"
    assert conta["sessao_estado"] == "fechada"
    assert conta["sessao_fechada_em"] == "2026-08-14T23:40:00+00:00"
    assert conta["sessao_fechada_por"] == {"id": "op-1", "nome": "Rafaela"}
    assert conta["operador_id"] == "op-1"
    assert conta["loja_id"] == "loja-1"


def test_uma_conta_que_ja_nao_se_consegue_somar_entra_sem_valor(monkeypatch):
    """A mesma regra de `_contas_abertas_da_sessao`: o que não se pode perder
    é a EXISTÊNCIA dela. Um 500 aqui deixava o gestor sem lista nenhuma por
    causa de uma conta estragada."""
    _monta(monkeypatch, vendas=[
        _venda(id="torta", linhas=[_linha(produto_tax_id=None)]),
        _venda(id="boa", criada_em="2026-08-14T22:11:00+00:00"),
    ])

    por_id = {c["id"]: c["total"] for c in _corre(listar_contas_esquecidas(_=_gestor()))}
    assert por_id == {"torta": None, "boa": 7.05}


def test_a_listagem_nao_escreve_nada(monkeypatch):
    """Um Z assinado não se reabre para nada, e muito menos para uma
    listagem."""
    _, registo = _monta(monkeypatch, vendas=[_venda()])

    _corre(listar_contas_esquecidas(_=_gestor()))

    assert [e for e in registo if e[0] == "update_one"] == []


def test_as_sessoes_repetidas_lem_se_uma_vez_so(monkeypatch):
    """As partes de uma conta repartida são todas do mesmo turno. Uma leitura
    por parte era pagar N vezes pela mesma sessão."""
    _, registo = _monta(monkeypatch, vendas=[
        _venda(id="p1"), _venda(id="p2", criada_em="2026-08-14T22:10:01+00:00"),
        _venda(id="p3", criada_em="2026-08-14T22:10:02+00:00"),
    ])

    _corre(listar_contas_esquecidas(_=_gestor()))

    leituras = [e for e in registo if e[0] == "find_one" and e[1] == "sessoes"]
    assert len(leituras) == 1, leituras


# --- Arrumar: a acção, e as três recusas ---------------------------------------


def test_arrumar_cancela_a_conta_com_o_nome_de_quem_o_decidiu(monkeypatch):
    """O botão existe para a lista se poder esvaziar — uma lista que nunca se
    esvazia deixa de ser lida, e a partir daí volta a haver dinheiro
    invisível com um ecrã por cima a fingir o contrário."""
    db, _ = _monta(monkeypatch, vendas=[_venda()])

    resposta = _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    assert resposta["estado"] == "cancelada"
    guardada = db[COLECOES["vendas"]]._documentos[0]
    assert guardada["estado"] == "cancelada"
    assert guardada["cancelada_por"] == {"id": "u-9", "nome": "gestor@lojas.pt"}, (
        "sem o nome de quem arrumou, a conta some-se e ninguém sabe por "
        "decisão de quem — é o mesmo dado que o `cancelada_por` do balcão "
        "existe para guardar"
    )
    assert guardada["cancelada_em"]


def test_arrumar_nao_muda_o_valor_da_conta_e_o_z_continua_a_bater(monkeypatch):
    """O Z daquele turno registou esta conta por 7,05 € e continua a dizer
    isso. Arrumar escreve o DESFECHO, não um número novo."""
    db, _ = _monta(monkeypatch, vendas=[_venda()])

    _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    guardada = db[COLECOES["vendas"]]._documentos[0]
    assert venda_mod._totais(guardada)["total"] == 7.05
    assert len(guardada["linhas"]) == 1


def test_arrumar_uma_conta_do_turno_A_DECORRER_e_recusado(monkeypatch):
    """Essa é do balcão e resolve-se lá, por quem está lá. O gestor a cancelar
    a conta que a operadora tem à frente é o defeito 4 ao contrário — uma
    acção sobre uma conta que ele não está a ver."""
    db, _ = _monta(monkeypatch, vendas=[_venda(sessao_id="sessao-hoje")],
                   sessoes=[_sessao(id="sessao-hoje", estado="aberta")])

    with pytest.raises(HTTPException) as e:
        _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    assert e.value.status_code == 409
    assert e.value.detail == _MSG_CONTA_ESQUECIDA_DE_TURNO_ABERTO
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_arrumar_uma_conta_com_reserva_fiscal_e_recusado(monkeypatch):
    """Pode ter uma Fatura Simplificada real do lado da AT. Essa vai primeiro
    a Reservas Fiscais Presas, onde se pergunta ao Vendus — cancelá-la aqui
    era apagar do nosso sistema uma venda ligada a um documento que continua
    a existir lá fora."""
    db, _ = _monta(monkeypatch, vendas=[_venda()],
                   refs=[{"venda_id": "parte-1",
                          "ext_ref": ext_ref_determinista(
                              "loja-1", "sessao-ontem", "parte-1"),
                          "documento_id": None}])

    with pytest.raises(HTTPException) as e:
        _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    assert e.value.status_code == 409
    assert e.value.detail == _MSG_CONTA_ESQUECIDA_TRAVADA
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_a_conta_travada_aparece_na_mesma_na_lista_marcada(monkeypatch):
    """Recusar a acção não é escondê-la: o dinheiro não pode ficar invisível.
    Aparece marcada, e o ecrã manda-o ao card de cima."""
    _monta(monkeypatch, vendas=[_venda()],
           refs=[{"venda_id": "parte-1",
                          "ext_ref": ext_ref_determinista(
                              "loja-1", "sessao-ontem", "parte-1"),
                          "documento_id": None}])

    lista = _corre(listar_contas_esquecidas(_=_gestor()))
    assert lista[0]["reserva_fiscal_por_resolver"] is True


def test_arrumar_uma_conta_ja_resolvida_e_recusado(monkeypatch):
    """Duas pessoas com o ecrã aberto: a segunda tem de saber que a primeira
    já lá foi, e não receber um 200 sobre uma escrita que não aconteceu."""
    _monta(monkeypatch, vendas=[_venda(estado="cancelada")])

    with pytest.raises(HTTPException) as e:
        _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    assert e.value.status_code == 409
    assert e.value.detail == _MSG_CONTA_ESQUECIDA_JA_RESOLVIDA


def test_arrumar_uma_conta_que_nao_existe_e_404(monkeypatch):
    _monta(monkeypatch, vendas=[])

    with pytest.raises(HTTPException) as e:
        _corre(arrumar_conta_esquecida("nao-existe", gestor=_gestor()))

    assert e.value.status_code == 404


def test_arrumar_passa_pela_escrita_condicionada_do_cancelar_venda(monkeypatch):
    """Delega em `venda._cancelar_conta` — a MESMA escrita que
    `venda.cancelar_venda` usa — e não numa segunda cópia dela: é de lá que vem
    a disciplina toda, o filtro condicionado ao estado que se leu (é o
    `matched_count` que decide, não a leitura de cima) e a segunda pergunta
    pela reserva DEPOIS de escrever. Prova-se pelo FILTRO da escrita, que é o
    que uma reescrita à mão aqui perderia primeiro."""
    _, registo = _monta(monkeypatch, vendas=[_venda()])

    _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    escritas = [e for e in registo if e[0] == "update_one" and e[1] == "vendas"]
    assert len(escritas) == 1
    assert escritas[0][2] == {"id": "parte-1", "estado": "aberta"}
    depois_da_escrita = registo[registo.index(escritas[0]) + 1:]
    assert any(e[0] == "find_one" and e[1] == "refs" for e in depois_da_escrita), (
        "a segunda pergunta pela reserva deixou de ser feita depois de "
        "escrever — é ela que apanha uma emissão que nasceu no meio"
    )


def test_a_pergunta_das_esquecidas_tem_um_indice_por_baixo():
    """`{"estado": "aberta"}` ordenada por `criada_em` sobre `fat_vendas` —
    sem índice, é um varrimento completo de uma colecção que ao fim de um ano
    tem centenas de milhares de vendas JÁ RESOLVIDAS, que são exactamente as
    que esta pergunta não quer ver.

    PARCIAL, e não um índice normal sobre `estado`: o que interessa indexar
    são as poucas contas `aberta` que existem em cada instante. É o mesmo
    raciocínio (e a mesma forma) do índice único de sessão aberta por caixa —
    e do `documento_id` das reservas, onde a parte pequena da chave é a que
    se percorre."""
    from faturacao.db import INDICES

    parciais = [
        (chaves, opcoes)
        for (coleccao, chaves, opcoes) in INDICES
        if coleccao == "fat_vendas"
        and opcoes.get("partialFilterExpression") == {"estado": "aberta"}
    ]
    assert parciais, (
        "A listagem das contas esquecidas voltou a percorrer `fat_vendas` "
        "inteira — o índice parcial sobre as contas `aberta` desapareceu."
    )
    chaves = parciais[0][0]
    assert ("criada_em", 1) in chaves, (
        "O índice deixou de cobrir a ORDENAÇÃO da listagem (`criada_em`): a "
        "leitura passa a ter de ordenar em memória o que o índice já podia "
        "dar ordenado."
    )


def test_arrumar_uma_conta_de_um_turno_A_FECHAR_e_recusado(monkeypatch):
    """O Z está a somar, neste instante, a lista onde esta conta entra
    (`_contas_abertas_da_sessao` é lida DEPOIS da marca `a_fechar`).
    Cancelá-la agora fazia-a desaparecer do Z — o registo de que aqueles euros
    ficaram por receber ia-se com ela, que é o oposto do que este ecrã existe
    para fazer.

    E não prende nada: um fecho que fique preso conclui-se no POS (FECHAR
    CAIXA outra vez), e a conta volta a estar arrumável a seguir."""
    db, _ = _monta(monkeypatch, vendas=[_venda()],
                   sessoes=[_sessao(estado="a_fechar")])

    with pytest.raises(HTTPException) as e:
        _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    assert e.value.status_code == 409
    assert e.value.detail == caixa_mod._MSG_CONTA_ESQUECIDA_COM_FECHO_A_DECORRER
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


# --- A regra: por resolver sem saída é um beco ---------------------------------
#
# **Toda a conta que `por_resolver.contas_por_resolver` declara POR RESOLVER
# tem de ter pelo menos uma acção EXECUTÁVEL que a resolva.**
#
# Medido antes desta ronda, sobre uma mãe `separada` sem partes de 11,64 €: a
# lista mostrava-a com `reserva_fiscal_por_resolver: false`, o ecrã desenhava-
# lhe o botão «Dar por perdida», e carregar devolvia 409 «Esta conta já não
# está aberta — … Recarregue a lista.» Recarregar trazia a mesma linha de
# volta: o ciclo fechava-se sobre si próprio. Sete rotas, zero saídas.


# As CINCO formas com que uma conta chega a esta lista. O nome de cada uma é o
# que se lhe chama ao telefone; o que está aqui é como ela fica na base.
_FAMILIAS = {
    # (documentos das vendas, reservas, motivo esperado, tem reserva viva)
    "conta_aberta": (lambda: [_venda()], None, "conta_aberta", False),
    "mae_separada_sem_partes": (
        lambda: [_venda(id="parte-1", estado="separada")], None,
        "mae_separada_sem_partes", False),
    "estado_desconhecido": (
        lambda: [_venda(estado="em_conferencia")], None,
        "estado_desconhecido", False),
    "conta_aberta_com_reserva_viva": (
        lambda: [_venda()], "parte-1", "conta_aberta", True),
    # A filha que a compensação de `venda._grava_as_partes` apagou: fica só a
    # reserva, sem venda nenhuma por baixo.
    "reserva_orfa": (lambda: [], "parte-1", "emissao_viva", True),
}


def _monta_da_familia(monkeypatch, familia):
    vendas, com_reserva, _, _ = _FAMILIAS[familia]
    refs = None
    if com_reserva:
        refs = [{
            "id": "ref-1",
            "ext_ref": ext_ref_determinista("loja-1", "sessao-ontem", com_reserva),
            "venda_id": com_reserva, "documento_id": None,
            "criado_em": "2026-08-14T22:11:00+00:00",
        }]
    return _monta(monkeypatch, vendas=vendas(), refs=refs)


def _recusa(gestor=None):
    """O `detail` da recusa de `arrumar`, ou `None` se ela não recusou."""
    try:
        _corre(arrumar_conta_esquecida("parte-1", gestor=gestor or _gestor()))
    except HTTPException as e:
        return e.detail
    return None


@pytest.mark.parametrize("familia", sorted(_FAMILIAS))
def test_nenhuma_familia_por_resolver_fica_sem_saida(monkeypatch, familia):
    """Para cada família do predicado: ou o botão desta lista a resolve, ou a
    recusa NOMEIA um ecrã onde a saída existe mesmo.

    A recusa que não pode acontecer a família nenhuma é
    `_MSG_CONTA_ESQUECIDA_JA_RESOLVIDA` — «foi cobrada, cancelada ou repartida
    entretanto. Recarregue a lista.» Sobre uma conta que ESTÁ na lista, ela é
    uma instrução que se contradiz: recarregar traz a mesma linha de volta."""
    _, _, motivo, trava = _FAMILIAS[familia]
    db, _ = _monta_da_familia(monkeypatch, familia)
    lista = _corre(listar_contas_esquecidas(_=_gestor()))
    assert [(c["motivo"], c["reserva_fiscal_por_resolver"]) for c in lista] == [
        (motivo, trava)], (
        "O cenário da família «%s» deixou de produzir a família: %r"
        % (familia, lista))

    recusa = _recusa()
    assert recusa != _MSG_CONTA_ESQUECIDA_JA_RESOLVIDA, (
        "A família «%s» está na lista e o botão dela responde «recarregue a "
        "lista» — e recarregar traz a mesma linha de volta. É o beco que esta "
        "regra existe para não haver." % familia)

    if trava:
        # A saída é NOUTRO ecrã (Reservas Fiscais Presas: Libertar ou
        # Reconciliar), e a recusa manda-o lá. Tem de estar mesmo lá.
        assert recusa == _MSG_CONTA_ESQUECIDA_TRAVADA
        assert "Reservas Fiscais Presas" in recusa
        assert [r["venda_id"] for r in _corre(fiscal_mod.listar_reservas_presas())] == [
            "parte-1"], (
            "A recusa manda o gestor a Reservas Fiscais Presas e a conta não "
            "está lá — a saída nomeada não existe.")
    elif motivo == "estado_desconhecido":
        # **A única que NÃO pode ter saída**, e por isso deixou de ser tratada
        # como as outras: cancelar declara «isto nunca foi pago», e sobre um
        # estado que este sistema não sabe ler não se pode declarar nada. Tem
        # nome e texto próprios — ver
        # `caixa._MSG_CONTA_ESQUECIDA_ESTADO_DESCONHECIDO`.
        assert recusa is not None
        assert "em_conferencia" in recusa, (
            "A frase não diz QUAL é o estado que o sistema não conhece — sem "
            "isso, o gestor não tem o que levar a quem mantém o sistema.")
        assert "nada foi alterado" in recusa.lower()
        assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "em_conferencia", (
            "O botão que devia recusar escreveu na mesma.")
    else:
        assert recusa is None, (
            "A família «%s» não tem ninguém no POS que lhe chegue e este botão "
            "recusou-a (%r): fica sem saída nenhuma." % (familia, recusa))
        assert _corre(listar_contas_esquecidas(_=_gestor())) == [], (
            "A conta foi arrumada e a lista continua a mostrá-la.")


def test_a_mae_separada_sem_partes_arruma_se_mesmo_com_o_turno_ABERTO(monkeypatch):
    """A recusa do turno aberto é sobre quem está EM CURSO NO BALCÃO, e a mãe
    `separada` não está: o POS recusa-lhe alterar e cancelar, e ela nem chega
    ao ecrã da operadora. Mandá-la para «quem lá está» era nomear uma saída
    que não existe — o mesmo que a marca `entregue_ao_gestor` já tinha vindo
    corrigir para a outra família."""
    db, _ = _monta(monkeypatch, vendas=[_venda(id="parte-1", estado="separada")],
                   sessoes=[_sessao(estado="aberta")])
    assert [c["motivo"] for c in _corre(listar_contas_esquecidas(_=_gestor()))] == [
        "mae_separada_sem_partes"]

    _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "cancelada"


def test_arrumar_a_mae_separada_escreve_condicionado_ao_estado_dela(monkeypatch):
    """E a escrita continua a ser a do POS: condicionada ao estado que se LEU
    — `separada`, aqui, e não o literal `"aberta"` que lá estava. Com o
    literal, o filtro nunca casava e o botão respondia 409 sobre uma escrita
    que não aconteceu; e a compensação repunha `aberta` uma mãe que nunca
    esteve aberta, devolvendo-a ao ecrã da operadora."""
    _, registo = _monta(monkeypatch, vendas=[_venda(id="parte-1", estado="separada")])

    _corre(arrumar_conta_esquecida("parte-1", gestor=_gestor()))

    escritas = [e for e in registo if e[0] == "update_one" and e[1] == "vendas"]
    assert len(escritas) == 1
    assert escritas[0][2] == {"id": "parte-1", "estado": "separada"}


def test_uma_mae_separada_COM_partes_nao_esta_na_lista_nem_se_arruma(monkeypatch):
    """A fronteira do outro lado: uma mãe cujas partes existem está RESOLVIDA
    — o dinheiro dela mudou-se para as filhas. Não aparece nesta lista, e o
    botão sobre ela responde «já foi … repartida entretanto. Recarregue a
    lista», que aqui é a instrução certa: recarregar não a traz de volta."""
    _monta(monkeypatch, vendas=[
        _venda(id="mae", estado="separada", conta_mae_id=None),
        _venda(id="parte-1", conta_mae_id="mae"),
    ])

    assert [c["id"] for c in _corre(listar_contas_esquecidas(_=_gestor()))] == ["parte-1"]
    with pytest.raises(HTTPException) as e:
        _corre(arrumar_conta_esquecida("mae", gestor=_gestor()))
    assert (e.value.status_code, e.value.detail) == (
        409, _MSG_CONTA_ESQUECIDA_JA_RESOLVIDA)


# --- O ecrã desenha o que o servidor lhe manda ---------------------------------


_ECRA_DO_GESTOR = (
    pathlib.Path(__file__).resolve().parents[3]
    / "frontend" / "src" / "pages" / "admin" / "faturacao" / "FatReservasPresas.js"
)

# Os dois campos que o ecrã não desenha com o nome deles, e porquê. Não é uma
# lista de dispensas: é a razão escrita de cada uma, e uma linha nova aqui é
# uma decisão que alguém tem de justificar.
_SO_PARA_O_GEMEO_LEGIVEL = {
    # O ecrã desenha o `caixa_nome`, que é o mesmo dado numa forma que o gestor
    # lê. Um id ao lado do nome não acrescentava nada.
    "caixa_id",
    # Vai pelo `nomeLoja(c)`, que o traduz para o nome da loja (e recua para o
    # id quando a loja não é conhecida).
    "loja_id",
}


def test_o_ecra_do_gestor_usa_todos_os_campos_que_o_servidor_manda(monkeypatch):
    """**O servidor manda e o ecrã não desenha** — foi assim que o beco da mãe
    `separada` ficou invisível.

    `_contas_esquecidas` passou a mandar `motivo` e `estado_da_venda` com o
    comentário «sem isto o ecrã tinha três coisas diferentes com o mesmo
    aspecto». O ecrã não desenhava nem um nem outro (o `badgeMotivo` que lá
    existia é da OUTRA lista, a das reservas presas), e por isso uma conta
    sem saída nenhuma tinha exactamente o aspecto de uma conta cobrável, com o
    botão «Dar por perdida» por baixo.

    Os campos saem da RESPOSTA da rota, não de uma lista escrita aqui: um
    campo novo entra sozinho, e é isso que impede este guarda de envelhecer
    calado.

    O que ele mede é o USO (`c.<campo>` aparece no ficheiro), e não o desenho —
    um guarda de texto não sabe distinguir um `<Badge>` de um `if`. Quem mede
    o desenho de cada MOTIVO é o guarda a seguir; este apanha a omissão
    inteira, que foi o que aconteceu."""
    _monta(monkeypatch, vendas=[_venda()])
    conta = _corre(listar_contas_esquecidas(_=_gestor()))[0]
    ecra = _ECRA_DO_GESTOR.read_text(encoding="utf-8")

    esquecidos = [
        campo for campo in conta
        if campo not in _SO_PARA_O_GEMEO_LEGIVEL and ("c.%s" % campo) not in ecra
    ]
    assert esquecidos == [], (
        "O servidor manda %s em cada conta esquecida e o ecrã do gestor não "
        "desenha nada disso. É esta omissão que faz três coisas diferentes "
        "terem o mesmo aspecto — e um botão que devolve 409 por baixo de uma "
        "delas." % esquecidos
    )


def test_o_ecra_do_gestor_nao_oferece_o_botao_a_quem_ele_recusa(monkeypatch):
    """A outra metade da regra, do lado do ecrã: a família
    `estado_desconhecido` é a única que este botão não pode resolver, e por
    isso é a única que não pode ter o botão desenhado. Um botão que devolve
    409 e uma lista que o volta a desenhar a seguir é o ciclo que esta ronda
    veio abrir."""
    ecra = _ECRA_DO_GESTOR.read_text(encoding="utf-8")
    assert "c.motivo === 'estado_desconhecido'" in ecra, (
        "O ecrã voltou a desenhar «Dar por perdida» por cima de um estado que "
        "o servidor recusa — e recarregar traz a mesma linha de volta.")
    ramo = ecra[ecra.index("c.motivo === 'estado_desconhecido'"):]
    ramo = ramo[:ramo.index("c.reserva_fiscal_por_resolver ?")]
    assert "arrumar-esquecida-" not in ramo, (
        "O botão «Dar por perdida» voltou a ser desenhado a esta família. "
        "(A frase dela NOMEIA o botão de propósito, para explicar porque é "
        "que ele não está lá — por isso o que se procura é o botão, não o "
        "texto.)")
    assert "não sabe ler" in ramo and "Copiar referência" in ramo, (
        "A frase desta família deixou de dizer o que se sabe e o que se leva a "
        "quem mantém o sistema.")


def test_o_ecra_do_gestor_tem_um_rotulo_para_cada_motivo_do_servidor():
    """E o `motivo` não basta ser LIDO: cada família tem de ter um rótulo que o
    gestor veja.

    Os motivos saem das constantes de `por_resolver`, não de uma lista escrita
    aqui — um motivo novo do lado do servidor faz este guarda ficar vermelho no
    dia em que nascer, que é o único dia em que alguém se lembra de lhe
    escrever o texto.

    `conta_aberta` é a única sem crachá, e é de propósito: é a família normal
    desta lista (o parágrafo por cima já a descreve) e um crachá em todas as
    linhas não distingue nada."""
    from faturacao import por_resolver

    motivos = {
        v for k, v in vars(por_resolver).items()
        if k.startswith("MOTIVO_") and isinstance(v, str)
    }
    assert por_resolver.MOTIVO_ABERTA in motivos, (
        "As constantes dos motivos mudaram de nome e este guarda deixou de as "
        "encontrar.")
    ecra = _ECRA_DO_GESTOR.read_text(encoding="utf-8")

    # O sítio onde o rótulo é DESENHADO, e não só o mapa onde ele está
    # escrito: sem esta linha, apagar o crachá do cartão deixava o mapa
    # intacto e este guarda verde. (O que um guarda de texto não consegue
    # provar é que o React o pinta mesmo — o que ele prende é a existência do
    # sítio, que é o que desapareceu.)
    assert "BADGE_MOTIVO_CONTA[c.motivo]" in ecra and "esquecida-motivo-" in ecra, (
        "O cartão da conta esquecida deixou de desenhar o crachá do motivo: as "
        "três famílias voltam a ter o mesmo aspecto.")

    sem_rotulo = sorted(
        m for m in motivos - {por_resolver.MOTIVO_ABERTA}
        if ("%s:" % m) not in ecra
    )
    assert sem_rotulo == [], (
        "O servidor pode mandar as contas com o motivo %s e o ecrã do gestor "
        "não tem rótulo nenhum para elas: ficam com o aspecto de uma conta "
        "normal, e a instrução por baixo passa a ser a errada." % sem_rotulo
    )

