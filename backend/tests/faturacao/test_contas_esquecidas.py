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
import re
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
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
    """Delega em `venda.cancelar_venda` e não numa segunda cópia da escrita —
    é de lá que vem a disciplina toda: o filtro `{"estado": "aberta"}` (é o
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
