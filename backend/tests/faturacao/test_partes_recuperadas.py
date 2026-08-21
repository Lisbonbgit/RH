"""As partes por cobrar vêm do SERVIDOR — `GET /pos/venda/repartidas`.

O defeito que esta rota fecha vivia todo no browser. A lista das pessoas por
cobrar (`reparticao`, em `PosVenda.js`) era estado do React e mais nada: um
F5, a tela de descanso, um "Trocar de operador" ou o browser a ir abaixo, e a
faixa *"Faltam cobrar 2 pessoas de 2 — 14,10 €"* desaparecia do ecrã sem uma
palavra. As partes continuavam bem `aberta` no servidor — medido, com as
rotas reais: `abertas no servidor: v-5, v-6, v-7`, e o que o ecrã recuperava
era `v-7` e mais nada, porque `GET /pos/venda/aberta` devolve UMA conta, a
mais recente, e nunca soube responder a "quem é que falta pagar".

É o mesmo acidente que o `emissao_por_confirmar` já tinha resolvido neste
módulo, e a solução é a mesma: **a verdade vem do servidor.**

O que este ficheiro guarda, e porquê cada coisa:

- a rota RESOLVE (não é engolida pela `GET /pos/venda/{venda_id}`, que casa
  com qualquer caminho de três segmentos) — provado no router a sério, como
  em `test_venda.py`;
- o âmbito é a sessão E o dispositivo, como na irmã dela;
- devolve as partes TODAS de cada mãe, não só as que faltam — é o "de 3" da
  faixa;
- e devolve-as com o TRAVÃO de cada uma já calculado, porque é desta lista
  que sai a conta que a operadora vai pôr à frente para emitir.

O cenário é construído chamando as rotas REAIS (`dividir_conta`,
`separar_conta`) e não escrevendo partes à mão na colecção: uma parte
inventada aqui podia ter uma forma que o servidor nunca produz, e o teste
ficava a defender uma resposta que ninguém dá.
"""
import asyncio
from copy import deepcopy

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from faturacao import router as router_do_modulo
from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.pos_auth import operador_atual
from faturacao.venda import (
    PedidoDividir,
    PedidoSeparar,
    contas_repartidas,
    dividir_conta,
    separar_conta,
    venda_aberta,
)


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados (o de test_venda.py, com a ordenação a sério) -----


def _corresponde(item, filtro):
    if not filtro:
        return True
    for chave, valor in filtro.items():
        if isinstance(valor, dict) and "$in" in valor:
            if item.get(chave) not in valor["$in"]:
                return False
        elif item.get(chave) != valor:
            return False
    return True


class CursorFalso:
    """ORDENA e LIMITA a sério — não um `sort()` que se devolve a si próprio.

    Aqui isso faz falta: a rota escolhe a mãe pela parte aberta MAIS RECENTE
    (`.sort("criada_em", -1)`), e com um `sort` de mentira a ordem certa vinha
    por acaso da ordem de inserção. Um teste que continua verde com o
    `.sort()` apagado não defende nada."""

    def __init__(self, itens):
        self._itens = list(itens)

    def sort(self, campo, direccao=1):
        self._itens.sort(key=lambda d: d.get(campo), reverse=(direccao == -1))
        return self

    async def to_list(self, n=None):
        return self._itens if n is None else self._itens[:n]


class ResultadoUpdateFalso:
    def __init__(self, matched_count):
        self.matched_count = matched_count
        self.modified_count = matched_count


class ResultadoDeleteFalso:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Leituras devolvem CÓPIAS PROFUNDAS, como o Motor — sem isso, o
    dicionário que o código de produção tem em mãos actualiza-se sozinho e o
    teste fica verde com a escrita apagada."""

    def __init__(self, registo, documentos=None):
        self.registo = registo
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", filtro))
        return CursorFalso(
            [deepcopy(d) for d in self._documentos if _corresponde(d, filtro)]
        )

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return deepcopy(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        self._documentos.append(deepcopy(doc))
        return None

    async def update_one(self, filtro, atualizacao):
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def delete_one(self, filtro):
        for i, d in enumerate(self._documentos):
            if _corresponde(d, filtro):
                del self._documentos[i]
                return ResultadoDeleteFalso(deleted_count=1)
        return ResultadoDeleteFalso(deleted_count=0)


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes.setdefault(nome, ColeccaoFalsa([]))


def _db(registo, caixas=None, sessoes=None, vendas=None, refs=None):
    return DbFalsa({
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, sessoes),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, refs),
        COLECOES["documentos"]: ColeccaoFalsa(registo, []),
        COLECOES["produtos"]: ColeccaoFalsa(registo, []),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, []),
    })


def _operador(**over):
    o = {
        "operador_id": "op-1", "nome": "Rafaela", "perfil": "operador_caixa",
        "loja_id": "loja-1", "dispositivo_id": "pc-balcao",
    }
    o.update(over)
    return o


def _caixa(**over):
    c = {"id": "caixa-1", "loja_id": "loja-1", "nome": "Balcão", "ativa": True}
    c.update(over)
    return c


def _sessao(**over):
    s = {
        "id": "sessao-1", "caixa_id": "caixa-1", "loja_id": "loja-1",
        "aberta_por": {"id": "op-1", "nome": "Rafaela"},
        "aberta_em": "2026-08-15T09:00:00+00:00", "fundo": 50.0, "estado": "aberta",
        "fechada_por": None, "fechada_em": None, "contado": None,
        "esperado": None, "diferenca": None,
    }
    s.update(over)
    return s


def _linha(**over):
    li = {
        "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 7.05, "produto_tax_id": "INT", "quantidade": 2, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None,
        "desconto_eur": None,
    }
    li.update(over)
    return li


def _venda(**over):
    """A conta de 14,10 € do cenário medido no browser: dois açaís a 7,05 €."""
    v = {
        "id": "venda-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "sessao_id": "sessao-1", "operador_id": "op-1", "dispositivo_id": "pc-balcao",
        "linhas": [_linha()], "linhas_versao": 0, "desconto_global_pct": None,
        "desconto_global_eur": None, "estado": "aberta",
        "criada_em": "2026-08-15T09:05:00+00:00",
    }
    v.update(over)
    return v


def _monta(monkeypatch, registo, vendas, refs=None):
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=vendas, refs=refs)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    return db


# --- O defeito, com os números que se viram no ecrã ----------------------------


def test_as_duas_partes_por_cobrar_voltam_do_servidor(monkeypatch):
    """14,10 € divididos por duas pessoas, nenhuma cobrada, e o browser
    esquecido: é isto que o arranque do ecrã tem de conseguir perguntar."""
    registo = []
    _monta(monkeypatch, registo, [_venda()])
    repartida = _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    assert [p["totais"]["total"] for p in repartida["partes"]] == [7.05, 7.05]

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))

    assert len(grupos) == 1, "A conta repartida por cobrar não voltou do servidor."
    assert grupos[0]["conta_mae"]["id"] == "venda-1"
    assert [p["totais"]["total"] for p in grupos[0]["partes"]] == [7.05, 7.05]
    assert all(p["estado"] == "aberta" for p in grupos[0]["partes"])
    # O que a faixa do balcão diz: 14,10 € por receber.
    assert round(sum(p["totais"]["total"] for p in grupos[0]["partes"]), 2) == 14.10


def test_a_venda_aberta_sozinha_nunca_soube_responder_a_isto(monkeypatch):
    """A razão de existir da rota nova, medida lado a lado. A irmã dela
    responde UMA conta — a parte mais recente — e é por isso que o ecrã ficava
    com uma pessoa à frente e as outras esquecidas. Guarda também que a rota
    velha CONTINUA a fazer o que fazia: é por ela que o balcão recupera a
    conta em curso, e não se parte o que salva o balcão."""
    registo = []
    _monta(monkeypatch, registo, [_venda()])
    repartida = _corre(dividir_conta("venda-1", PedidoDividir(partes=3), operador=_operador()))
    ids_das_partes = [p["id"] for p in repartida["partes"]]

    uma = _corre(venda_aberta(caixa_id="caixa-1", operador=_operador()))
    assert uma is not None and uma["id"] in ids_das_partes, (
        "A `GET /pos/venda/aberta` deixou de devolver uma conta aberta do posto."
    )

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    assert [p["id"] for p in grupos[0]["partes"]] == ids_das_partes, (
        "A rota nova tem de devolver as TRÊS partes — é isso que a distingue "
        "da de cima, que devolve uma."
    )


def test_as_partes_ja_resolvidas_vêm_na_lista_para_o_de_quantas(monkeypatch):
    """A faixa diz "Faltam cobrar 1 pessoa **de 3**". Com só as abertas na
    resposta, o "de 3" virava "de 1" e a conta parecia mais pequena do que
    foi — e a lista deixava de poder mostrar o número da fatura das que já
    foram cobradas."""
    registo = []
    db = _monta(monkeypatch, registo, [_venda()])
    repartida = _corre(dividir_conta("venda-1", PedidoDividir(partes=3), operador=_operador()))
    partes = repartida["partes"]
    # Uma emitida e uma cancelada, escritas como o resto do módulo as deixa.
    for doc in db[COLECOES["vendas"]]._documentos:
        if doc["id"] == partes[0]["id"]:
            doc["estado"] = "emitida"
        if doc["id"] == partes[1]["id"]:
            doc["estado"] = "cancelada"

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))

    assert len(grupos) == 1
    estados = [p["estado"] for p in grupos[0]["partes"]]
    assert estados == ["emitida", "cancelada", "aberta"], (
        "As partes já resolvidas têm de vir na lista: são elas o «de 3»."
    )


def test_uma_reparticao_toda_resolvida_nao_volta_ao_ecra(monkeypatch):
    """Sem nenhuma parte aberta não há dinheiro por receber, e a faixa não tem
    o que dizer. Devolver o grupo à mesma punha o ecrã a insistir com uma
    conta que já acabou."""
    registo = []
    db = _monta(monkeypatch, registo, [_venda()])
    repartida = _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    for doc in db[COLECOES["vendas"]]._documentos:
        if doc.get("conta_mae_id") == "venda-1":
            doc["estado"] = "emitida"

    assert _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador())) == []


# --- Âmbito: a sessão E o dispositivo -----------------------------------------


def test_as_partes_do_outro_pc_nao_aparecem_neste(monkeypatch):
    """O mesmo âmbito de `GET /pos/venda/aberta`, e pela mesma razão: uma loja
    com uma caixa e dois PCs emparelhados ("PC Balcão" e "PC Drive-Thru") é
    uma configuração real, e o ecrã de um não tem que mostrar as pessoas por
    cobrar do outro — tal como não mostra a conta em curso dele. Quem tem de
    ver TUDO é o fecho de caixa, e isso é outro ficheiro."""
    registo = []
    _monta(monkeypatch, registo, [_venda()])
    _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))

    do_drive = _corre(contas_repartidas(
        caixa_id="caixa-1", operador=_operador(dispositivo_id="pc-drive")))
    assert do_drive == [], (
        "As partes do PC Balcão apareceram no PC Drive-Thru — o cliente de um "
        "posto acabaria a pagar a conta do outro."
    )
    do_balcao = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    assert len(do_balcao) == 1


def test_sem_sessao_aberta_e_recusado(monkeypatch):
    """Sem caixa aberta não há partes por cobrar para recuperar — o 409 de
    `_sessao_aberta`, o mesmo da rota irmã."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao(estado="fechada")], vendas=[])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as excinfo:
        _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    assert excinfo.value.status_code == 409


def test_uma_caixa_de_outra_loja_e_404(monkeypatch):
    registo = []
    _monta(monkeypatch, registo, [_venda()])
    with pytest.raises(HTTPException) as excinfo:
        _corre(contas_repartidas(
            caixa_id="caixa-1", operador=_operador(loja_id="loja-2")))
    assert excinfo.value.status_code == 404


def test_uma_parte_cuja_mae_e_de_outra_loja_nao_arrasta_a_mae_para_a_resposta(monkeypatch):
    """O âmbito da mãe é o de sempre — a loja do token. Uma parte não pode ser
    a porta por onde a conta de outra loja entra numa resposta."""
    registo = []
    orfa = _venda(
        id="parte-estranha", conta_mae_id="mae-de-outra-loja",
        criada_em="2026-08-15T09:06:00+00:00",
    )
    _monta(monkeypatch, registo, [
        orfa,
        _venda(id="mae-de-outra-loja", loja_id="loja-9", estado="separada"),
    ])
    assert _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador())) == []


# --- O travão de cada parte ---------------------------------------------------


def test_uma_parte_com_emissao_por_confirmar_chega_ao_ecra_ja_travada(monkeypatch):
    """É desta lista que sai a conta que a operadora vai pôr à frente para
    emitir. Uma parte com uma reserva fiscal viva tem de chegar já travada —
    senão o EMITIR aparece aceso por cima de uma Fatura Simplificada que pode
    ter saído, que é exactamente o defeito que `emissao_por_confirmar` existe
    para fechar."""
    registo = []
    db = _monta(monkeypatch, registo, [_venda()])
    repartida = _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    presa = repartida["partes"][1]["id"]
    db[COLECOES["refs_fiscais"]]._documentos.append(
        {"id": "ref-1", "venda_id": presa, "ext_ref": "pos-loja-1-sessao-1-%s" % presa})

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    travadas = {p["id"]: p["emissao_por_confirmar"] for p in grupos[0]["partes"]}

    assert travadas[presa] is True, "A parte com reserva fiscal viva chegou destravada."
    assert list(travadas.values()).count(False) == 1, (
        "As outras partes não podem vir travadas por arrasto."
    )


# --- O modo: "Divisão de Conta" e "Conta Separada" são dois ecrãs -------------


def test_o_dividir_grava_o_modo_e_a_resposta_traz_o_mesmo(monkeypatch):
    registo = []
    db = _monta(monkeypatch, registo, [_venda()])
    resposta = _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    assert resposta["modo"] == "dividir"
    mae = [d for d in db[COLECOES["vendas"]]._documentos if d["id"] == "venda-1"][0]
    assert mae["reparticao_modo"] == "dividir"
    assert mae["estado"] == "separada"

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    assert grupos[0]["modo"] == "dividir"


def test_o_separar_grava_o_seu_e_o_ecra_recuperado_nao_lhe_chama_divisao(monkeypatch):
    """Sem este campo, uma conta SEPARADA recuperada do servidor voltava com o
    cabeçalho "Divisão de Conta" — o ecrã a dizer à operadora uma coisa que
    não aconteceu."""
    registo = []
    _monta(monkeypatch, registo, [_venda()])
    resposta = _corre(separar_conta(
        "venda-1",
        PedidoSeparar(partes=[
            {"linhas": [{"linha_id": "linha-1", "quantidade": 1}]},
            {"linhas": [{"linha_id": "linha-1", "quantidade": 1}]},
        ]),
        operador=_operador(),
    ))
    assert resposta["modo"] == "separar"

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    assert grupos[0]["modo"] == "separar"


def test_uma_reparticao_anterior_a_este_campo_nao_rebenta(monkeypatch):
    """Nada de migrações: uma mãe gravada antes de `reparticao_modo` existir
    não o tem, e a resposta diz `None` — que é o ecrã a ficar com o cabeçalho
    por omissão, exactamente o que ele já fazia."""
    registo = []
    _monta(monkeypatch, registo, [
        _venda(id="mae-antiga", estado="separada"),
        _venda(
            id="parte-antiga", conta_mae_id="mae-antiga",
            criada_em="2026-08-15T09:06:00+00:00",
        ),
    ])
    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))
    assert len(grupos) == 1
    assert grupos[0]["modo"] is None


# --- Mais do que uma conta repartida por cobrar -------------------------------


def test_a_reparticao_mais_recente_vem_primeiro(monkeypatch):
    """O ecrã tem UM lugar para uma repartição e fica com a primeira da lista.
    Tem de ser aquela em que a operadora estava a trabalhar — a mais recente —,
    e não a que o Mongo calhar devolver."""
    registo = []
    db = _monta(monkeypatch, registo, [_venda()])
    _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    # Uma segunda conta, repartida DEPOIS. As partes de uma divisão nascem
    # todas com o mesmo `criada_em` do relógio real, por isso o cenário força
    # a ordem à mão — que é o que a base de dados teria.
    db[COLECOES["vendas"]]._documentos.append(
        _venda(id="venda-2", criada_em="2026-08-15T10:00:00+00:00"))
    _corre(dividir_conta("venda-2", PedidoDividir(partes=2), operador=_operador()))
    for doc in db[COLECOES["vendas"]]._documentos:
        if doc.get("conta_mae_id") == "venda-1":
            doc["criada_em"] = "2026-08-15T09:10:00+00:00"
        if doc.get("conta_mae_id") == "venda-2":
            doc["criada_em"] = "2026-08-15T10:10:00+00:00"

    grupos = _corre(contas_repartidas(caixa_id="caixa-1", operador=_operador()))

    assert [g["conta_mae"]["id"] for g in grupos] == ["venda-2", "venda-1"], (
        "A repartição mais recente tem de vir primeiro — é a que o ecrã mostra."
    )


# --- A rota RESOLVE (o router a sério) ----------------------------------------


def _cliente():
    """App mínima com o router REAL do módulo (mesmo padrão de test_venda.py).
    Sem prefixo à mão: o router de `faturacao/__init__.py` já traz o
    `/api/faturacao` dentro dele, e acrescentar-lho aqui dava caminhos a
    dobrar — a app do teste deixava de ser a app a sério."""
    app = FastAPI()
    app.include_router(router_do_modulo)
    app.dependency_overrides[operador_atual] = lambda: _operador()
    return TestClient(app)


def test_repartidas_nao_e_engolida_pela_rota_do_id(monkeypatch):
    """`GET /pos/venda/{venda_id}` casa com QUALQUER caminho de três
    segmentos, "repartidas" incluído. Só a ordem de declaração as separa — e é
    exactamente o defeito que a `GET /pos/venda/aberta` já documenta. Provado
    no router montado, não por leitura do ficheiro."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[_venda()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    cliente = _cliente()

    _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))
    resposta = cliente.get("/api/faturacao/pos/venda/repartidas?caixa_id=caixa-1")

    assert resposta.status_code == 200, (
        "A rota das partes por cobrar foi servida por outra (provavelmente a "
        "`/pos/venda/{venda_id}`, que a engole se for declarada acima dela)."
    )
    corpo = resposta.json()
    assert isinstance(corpo, list) and len(corpo) == 1
    assert corpo[0]["conta_mae"]["id"] == "venda-1"
    assert len(corpo[0]["partes"]) == 2


def test_a_conta_aberta_continua_a_resolver_ao_lado_dela(monkeypatch):
    """A rota nova não pode ter-se metido à frente da que salva o balcão."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], vendas=[_venda()])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    cliente = _cliente()

    resposta = cliente.get("/api/faturacao/pos/venda/aberta?caixa_id=caixa-1")
    assert resposta.status_code == 200
    assert resposta.json()["id"] == "venda-1"
