"""O fecho de caixa conta as contas que ficaram por cobrar — e di-lo ANTES do Z.

**A promessa que o ecrã fazia e o fecho não cumpria.** Por cima das partes de
uma conta repartida, a faixa do balcão lia-se assim: *"Enquanto não forem
cobradas ou canceladas, ficam abertas no servidor e o fecho desta caixa vai
contá-las."* Não contava. O Z lia `{"sessao_id": …, "estado": "emitida"}` e
mais nada, e o único travão do fecho — `_venda_com_emissao_viva` — exige uma
RESERVA FISCAL, que uma parte que nunca chegou ao EMITIR não tem. Dividida uma
conta de 14,10 € por duas pessoas e cobrada a nenhuma, a caixa fechava, o Z
saía sem uma palavra sobre elas, e os 14,10 € não apareciam em relatório
nenhum: nem neste (já assinado) nem no da sessão seguinte, que filtra por
outro `sessao_id`.

**As duas correcções erradas, e porque é que não são estas.** Travar o fecho
prendia a loja para sempre por causa de uma parte que ninguém vai pagar
(regra 3 do dono: o fecho não bloqueia, regista e segue). Mudar a frase da
faixa para "não conta" era resolver com palavras um buraco a sério. A que
está feita é a terceira: **contar, dizer à operadora enquanto ela ainda pode
ir cobrar, e escrever no Z o que ficou.**

O que este ficheiro guarda:

- o fecho CONTA-AS e não se recusa por causa delas;
- o número é lido DEPOIS da marca `a_fechar`, que é o que o torna definitivo;
- fica no Z e fica GRAVADO na sessão, para o gestor o encontrar dias depois;
- o âmbito é a SESSÃO inteira (os dois PCs da mesma caixa), ao contrário da
  `GET /pos/venda/repartidas`, que responde ao ecrã de um posto;
- e a leitura à parte (`GET /pos/caixa/contas-abertas`) responde antes de
  qualquer escrita, que é o que a operadora tem à frente antes de assinar.

Duplo de base de dados no padrão de test_caixa_endpoints.py, com um cursor que
ORDENA a sério. Nenhum teste liga a uma base de dados nem à rede.
"""
import re
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import venda as venda_mod
from faturacao.caixa import (
    PedidoFecharCaixa,
    _contas_abertas_da_sessao,
    contas_abertas_da_caixa,
    fechar_caixa,
)
from faturacao.db import COLECOES
from faturacao.venda import PedidoDividir, dividir_conta


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Duplo de base de dados ----------------------------------------------------


def _corresponde(item, filtro):
    if not filtro:
        return True
    for chave, valor in filtro.items():
        if isinstance(valor, dict) and "$in" in valor:
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
    """Ordena a sério: a lista das contas abertas sai por `criada_em` para a
    operadora as ler pela ordem em que apareceram no turno.

    E REGISTA a ordenação. Faz falta a um teste em particular (o do momento em
    que as contas abertas são lidas): o filtro dessa leitura é, letra por
    letra, o de `_venda_com_emissao_viva` — `{"sessao_id": …, "estado":
    "aberta"}` —, e no registo as duas eram indistinguíveis. O `.sort` não é:
    só a leitura das contas abertas ordena por `criada_em`."""

    def __init__(self, itens, registo=None, nome=None):
        self._itens = list(itens)
        self._registo = registo
        self._nome = nome

    def sort(self, campo, direccao=1):
        if self._registo is not None:
            self._registo.append(("sort", self._nome, campo, direccao))
        self._itens.sort(key=lambda d: d.get(campo) or "", reverse=(direccao == -1))
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
    def __init__(self, registo, nome, documentos=None):
        self.registo = registo
        self.nome = nome
        self._documentos = documentos if documentos is not None else []

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", self.nome, filtro))
        return CursorFalso(
            [deepcopy(d) for d in self._documentos if _corresponde(d, filtro)],
            self.registo, self.nome,
        )

    async def find_one(self, filtro, projecao=None):
        self.registo.append(("find_one", self.nome, filtro))
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return deepcopy(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        self.registo.append(("insert_one", self.nome, dict(doc)))
        self._documentos.append(deepcopy(doc))
        return None

    async def update_many(self, filtro, atualizacao):
        """`$set`/`$unset` em TODAS as que casam — hoje só o `$unset` da
        etiqueta do posto, que o fecho de caixa faz às contas que deixa
        abertas (`caixa._largar_o_posto_das_contas_abertas`). Sem isto o duplo
        levantava `AttributeError`, o `except` de lá engolia-o e o teste ficava
        verde a medir o contrário do que diz."""
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        for alvo in alvos:
            alvo.update(atualizacao.get("$set", {}))
            for campo in atualizacao.get("$unset", {}):
                alvo.pop(campo, None)
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def update_one(self, filtro, atualizacao):
        self.registo.append(("update_one", self.nome, filtro, atualizacao))
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
            for campo, valor in (atualizacao.get("$push") or {}).items():
                alvos[0].setdefault(campo, []).append(deepcopy(valor))
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def delete_one(self, filtro):
        for i, d in enumerate(self._documentos):
            if _corresponde(d, filtro):
                del self._documentos[i]
                return ResultadoDeleteFalso(deleted_count=1)
        return ResultadoDeleteFalso(deleted_count=0)


class DbFalsa:
    def __init__(self, registo, coleccoes):
        self.registo = registo
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        if nome not in self._coleccoes:
            self._coleccoes[nome] = ColeccaoFalsa(self.registo, nome, [])
        return self._coleccoes[nome]


def _db(registo, caixas=None, sessoes=None, movimentos=None, vendas=None, refs=None,
        dispositivos=None):
    return DbFalsa(registo, {
        COLECOES["caixas"]: ColeccaoFalsa(registo, "caixas", caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, "sessoes", sessoes),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa(registo, "movimentos", movimentos),
        COLECOES["vendas"]: ColeccaoFalsa(registo, "vendas", vendas),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, "refs", refs),
        # Os PCs emparelhados: é daqui que sai o NOME do posto, para o ecrã
        # poder escrever "PC Drive-Thru" onde só tinha um uuid.
        COLECOES["dispositivos"]: ColeccaoFalsa(
            registo, "dispositivos",
            dispositivos if dispositivos is not None else [
                {"id": "pc-balcao", "loja_id": "loja-1", "nome": "PC Balcão"},
                {"id": "pc-drive", "loja_id": "loja-1", "nome": "PC Drive-Thru"},
            ],
        ),
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


def _venda_aberta(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "sessao_id": "sessao-1", "operador_id": "op-1", "dispositivo_id": "pc-balcao",
        "linhas": [_linha()], "linhas_versao": 0, "desconto_global_pct": None,
        "desconto_global_eur": None, "estado": "aberta",
        "criada_em": "2026-08-15T09:05:00+00:00",
    }
    v.update(over)
    return v


def _venda_emitida(**over):
    v = _venda_aberta(
        id="venda-paga", estado="emitida", criada_em="2026-08-15T09:01:00+00:00")
    v["pagamentos"] = [{
        "tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro",
        "tipo_fiscal": "NU", "valor": 14.10,
    }]
    v.update(over)
    return v


def _sem_vendus(monkeypatch):
    async def verificacao(_db, _sessao, _valor):
        return {"nao_verificado": "desligado no teste"}
    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", verificacao)


def _monta(monkeypatch, vendas, sessoes=None, movimentos=None, refs=None):
    registo = []
    db = _db(
        registo, caixas=[_caixa()], sessoes=sessoes or [_sessao()],
        movimentos=movimentos or [], vendas=vendas, refs=refs,
    )
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    _sem_vendus(monkeypatch)
    return db, registo


# --- O defeito, com os números que se mediram ---------------------------------


def test_o_z_diz_quantas_contas_ficaram_por_cobrar_e_quanto_valem(monkeypatch):
    """14,10 € divididos por duas pessoas e cobrada a nenhuma: o Z saía sem
    uma palavra sobre elas. Agora leva as duas, com o valor."""
    db, _ = _monta(monkeypatch, vendas=[_venda_aberta()])
    _corre(dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador()))

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["quantas"] == 2, (
        "As duas pessoas por cobrar não entraram no Z — é a promessa que a "
        "faixa do balcão faz à operadora."
    )
    assert z["contas_abertas"]["total"] == 14.10
    assert all(c["conta_mae_id"] == "venda-1" for c in z["contas_abertas"]["contas"]), (
        "O Z tem de dizer QUAIS são partes de uma conta repartida: «faltou "
        "cobrar uma pessoa» e «ficou uma conta a meio» são duas conversas "
        "diferentes com o gestor."
    )
    assert db  # a base ficou de pé


def test_o_fecho_nao_se_recusa_por_causa_delas(monkeypatch):
    """Regra 3 do dono. Uma parte que ninguém vai pagar prenderia a loja para
    sempre — o fecho regista e segue em frente, e a sessão fica mesmo
    `fechada`."""
    db, _ = _monta(monkeypatch, vendas=[_venda_aberta()])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["estado"] == "fechada"
    assert db[COLECOES["sessoes_caixa"]]._documentos[0]["estado"] == "fechada"


def test_o_dinheiro_por_cobrar_nao_entra_no_esperado_da_gaveta(monkeypatch):
    """Contar não é somar à gaveta: uma conta aberta não foi paga, e pô-la no
    `esperado` fazia a contagem acusar uma falta de 14,10 € que não existe."""
    _monta(monkeypatch, vendas=[_venda_aberta()])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["vendas_dinheiro"] == 0.0
    assert z["esperado"] == 50.0
    assert z["diferenca"] == 0.0
    assert z["contas_abertas"]["total"] == 14.10


def test_o_z_fica_gravado_na_sessao(monkeypatch):
    """O Z que a operadora leva é papel. A pergunta "o que é que ficou por
    cobrar na noite de terça?" faz-se dias depois, no backoffice — e um número
    que só existiu numa resposta HTTP não responde a nada."""
    db, _ = _monta(monkeypatch, vendas=[_venda_aberta()])

    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    gravado = db[COLECOES["sessoes_caixa"]]._documentos[0]["contas_abertas"]
    assert gravado["quantas"] == 1 and gravado["total"] == 14.10


def test_a_chave_esta_sempre_la_mesmo_sem_nada_por_cobrar(monkeypatch):
    """A mesma regra do `emissao_por_confirmar` em venda.py: o ecrã não pode
    ter de adivinhar se a ausência da chave quer dizer "não ficou nada" ou
    "esta versão do servidor não sabe responder a isso"."""
    _monta(monkeypatch, vendas=[_venda_emitida()])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=64.10), operador=_operador()))

    assert z["contas_abertas"] == {
        "quantas": 0, "total": 0.0, "quantas_travam": 0, "total_que_trava": 0.0,
        "total_por_cobrar": 0.0, "total_do_balcao": 0.0,
        "quantas_do_gestor": 0, "total_do_gestor": 0.0,
        "contas": [], "dispositivo_id": "pc-balcao",
    }
    assert z["vendas_dinheiro"] == 14.10, "as vendas emitidas continuam a contar"


# --- Âmbito e momento ----------------------------------------------------------


def test_conta_as_contas_dos_DOIS_pcs_da_mesma_caixa(monkeypatch):
    """Ao contrário da `GET /pos/venda/repartidas` (que responde ao ECRÃ de um
    posto), o Z é do TURNO: uma conta aberta no "PC Drive-Thru" tem de
    aparecer no Z da caixa que os dois postos partilham, senão volta a haver
    dinheiro por receber que ninguém vê."""
    _monta(monkeypatch, vendas=[
        _venda_aberta(),
        _venda_aberta(id="venda-drive", dispositivo_id="pc-drive",
                      criada_em="2026-08-15T09:07:00+00:00"),
    ])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["quantas"] == 2
    assert z["contas_abertas"]["total"] == 28.20


def test_nao_conta_contas_de_outra_sessao(monkeypatch):
    """O Z é desta sessão. Uma conta aberta que sobrou do turno de ontem é
    problema do Z de ontem, não deste."""
    _monta(monkeypatch, vendas=[_venda_aberta(id="de-ontem", sessao_id="sessao-0")])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["quantas"] == 0


def test_a_contagem_e_feita_DEPOIS_da_marca_a_fechar(monkeypatch):
    """É a marca que torna o número definitivo: a partir dela nenhuma conta
    nova pode nascer nesta sessão (`abrir_venda` resolve a sessão por
    `_sessao_aberta`, que só aceita `aberta`) e nenhuma das abertas pode
    passar a `emitida` (o núcleo fiscal recusa). Lida antes, era uma
    fotografia que ainda podia mudar entre a leitura e o Z."""
    _, registo = _monta(monkeypatch, vendas=[_venda_aberta()])

    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    marca = next(
        i for i, e in enumerate(registo)
        if e[0] == "update_one" and e[1] == "sessoes"
        and e[3].get("$set", {}).get("estado") == "a_fechar"
    )
    # Pela ORDENAÇÃO, e não pelo filtro: o filtro desta leitura é igual ao de
    # `_venda_com_emissao_viva` (que corre duas vezes, uma de cada lado da
    # marca) e no registo não se distinguem. O `.sort("criada_em")` distingue —
    # é só esta que ordena, e ordena no mesmo instante em que lê.
    leitura_das_abertas = next(
        i for i, e in enumerate(registo)
        if e[0] == "sort" and e[1] == "vendas" and e[2] == "criada_em"
    )
    assert leitura_das_abertas > marca, (
        "As contas abertas foram lidas ANTES da marca `a_fechar` — nesse "
        "intervalo ainda pode nascer uma conta que o Z não vai mencionar."
    )


# --- A leitura à parte, antes de assinar --------------------------------------


def test_a_operadora_ve_isto_antes_de_assinar_o_z(monkeypatch):
    """`GET /pos/caixa/contas-abertas` — só leitura. É o que o diálogo do
    fecho mostra ANTES da contagem, enquanto ainda dá para ir cobrar ou
    cancelar. Depois do Z não há volta atrás."""
    db, registo = _monta(monkeypatch, vendas=[_venda_aberta()])

    resposta = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    assert resposta["quantas"] == 1 and resposta["total"] == 14.10
    assert resposta["contas"][0]["id"] == "venda-1"
    assert not any(e[0] in ("update_one", "insert_one", "delete_one") for e in registo), (
        "A leitura de antes do fecho escreveu alguma coisa. Se ela mexer na "
        "sessão, abre outra vez a janela que o `fechar_caixa` fechou."
    )
    assert db[COLECOES["sessoes_caixa"]]._documentos[0]["estado"] == "aberta"


def test_a_leitura_responde_tambem_numa_sessao_a_meio_de_um_fecho(monkeypatch):
    """`_sessao_viva` e não `_sessao_aberta`: uma sessão que ficou a meio de um
    fecho continua a ter contas abertas, e é precisamente nessa que a
    operadora vai carregar em FECHAR outra vez."""
    _monta(monkeypatch, vendas=[_venda_aberta()],
           sessoes=[_sessao(estado="a_fechar", fecho_iniciado_em="2026-08-15T23:00:00+00:00")])

    resposta = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))
    assert resposta["quantas"] == 1


def test_sem_sessao_viva_responde_zero_e_nao_um_erro(monkeypatch):
    """Numa caixa fechada não há nada por cobrar — e isso não é um erro que
    valha a pena pôr à frente de quem só abriu o diálogo."""
    _monta(monkeypatch, vendas=[], sessoes=[_sessao(estado="fechada")])

    assert _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador())) == {
        "quantas": 0, "total": 0.0, "quantas_travam": 0, "total_que_trava": 0.0,
        "total_por_cobrar": 0.0, "contas": [], "dispositivo_id": "pc-balcao",
    }


def test_a_leitura_de_uma_caixa_de_outra_loja_e_404(monkeypatch):
    _monta(monkeypatch, vendas=[_venda_aberta()])
    with pytest.raises(HTTPException) as excinfo:
        _corre(contas_abertas_da_caixa(
            caixa_id="caixa-1", operador=_operador(loja_id="loja-2")))
    assert excinfo.value.status_code == 404


# --- O que não pode acontecer: o fecho rebentar por causa disto ---------------


def test_uma_conta_que_ja_nao_se_consegue_somar_nao_derruba_o_fecho(monkeypatch):
    """Uma linha que `linha_de_venda` já não sabe avaliar (um produto que
    perdeu o IVA no retrato) não pode transformar o fecho num 500 — isso
    mandava a funcionária fechar outra vez uma caixa que não fechou. A conta
    conta-se na mesma, com o valor a `None`: o que não se pode perder é a
    EXISTÊNCIA dela."""
    _monta(monkeypatch, vendas=[
        _venda_aberta(id="venda-torta", linhas=[_linha(produto_tax_id=None)]),
        _venda_aberta(id="venda-boa", criada_em="2026-08-15T09:06:00+00:00"),
    ])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    por_id = {c["id"]: c["total"] for c in z["contas_abertas"]["contas"]}
    assert por_id["venda-torta"] is None
    assert por_id["venda-boa"] == 14.10
    assert z["contas_abertas"]["quantas"] == 2
    assert z["contas_abertas"]["total"] == 14.10, (
        "O total soma o que se consegue somar — e a que não se conseguiu "
        "continua na lista, com um travessão em vez de um valor inventado."
    )


def test_a_funcao_pura_soma_pelo_mesmo_calculo_das_vendas(monkeypatch):
    """O valor de uma conta sai sempre de `precos.linha_de_venda`
    (`venda.py::_totais`), em todo o módulo — nunca de uma soma escrita à
    parte no fecho. Aqui compara-se com o próprio `_totais`, e não com um
    número escrito à mão, que ficaria verde no dia em que os dois
    divergissem."""
    db, _ = _monta(monkeypatch, vendas=[
        _venda_aberta(linhas=[_linha(quantidade=3, desconto_pct=10)]),
    ])
    esperado = venda_mod._totais(db[COLECOES["vendas"]]._documentos[0])["total"]

    resposta = _corre(_contas_abertas_da_sessao(db, "sessao-1"))

    assert resposta["total"] == esperado
    assert resposta["contas"][0]["total"] == esperado


# --- As duas famílias, e de que posto é cada conta -----------------------------
#
# A lista é do âmbito da SESSÃO (bem — é o turno inteiro que se está a fechar),
# mas as contas dentro dela não são todas a mesma coisa, e o ecrã dizia que
# eram. Dois achados desta ronda, os dois medidos no browser:
#
#   - a caixa de aviso afirmava, sobre TODAS as contas listadas, "Não impedem
#     o fecho". O diálogo listou 2 partes e uma conta travada, e carregar em
#     Fechar Caixa devolveu 409 por causa da travada. Uma conta com RESERVA
#     FISCAL viva impede mesmo o fecho (`_venda_com_emissao_viva`) — e está
#     certo que impeça; o que estava errado era a frase;
#   - e todas as acções do ecrã são do âmbito do DISPOSITIVO: `GET
#     /pos/venda/repartidas` filtra pelo `dispositivo_id` do token. Dois postos
#     na mesma caixa, o Drive-Thru divide a conta dele e não cobra ninguém: o
#     fecho pedido do Balcão listava as três contas do turno (28,20 €) e
#     mandava-a cobrá-las, e o ecrã do Balcão respondia `0 grupos`.
#
# O servidor não alarga o âmbito de nada — quem manda cobrar continua a ser o
# posto de onde a conta é. O que ele passa a dar é o que faltava ao texto para
# poder dizer a verdade: `trava_o_fecho`, `dispositivo_id` e `dispositivo_nome`
# por conta, e o `dispositivo_id` de quem PERGUNTOU no envelope.


def test_a_conta_com_reserva_fiscal_diz_que_trava_o_fecho(monkeypatch):
    """O critério é o MESMO de `_venda_com_emissao_viva` (conta `aberta` com
    reserva), feito conta a conta em vez de parar na primeira — senão o ecrã
    não sabe QUAL delas é."""
    _monta(
        monkeypatch,
        vendas=[
            _venda_aberta(id="venda-travada"),
            _venda_aberta(id="venda-normal", criada_em="2026-08-15T09:06:00+00:00"),
        ],
        refs=[{"venda_id": "venda-travada", "ext_ref": "x", "documento_id": None}],
    )

    resposta = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    trava = {c["id"]: c["trava_o_fecho"] for c in resposta["contas"]}
    assert trava == {"venda-travada": True, "venda-normal": False}, (
        "O ecrã voltou a não conseguir distinguir a conta que RECUSA o fecho "
        "das que não travam nada — e é sobre todas elas que ele escreve «Não "
        "impedem o fecho»."
    )


def test_sem_reserva_nenhuma_nenhuma_conta_trava_o_fecho(monkeypatch):
    """O caso normal de todas as noites: contas por cobrar às dezenas e o
    fecho passa. Um `trava_o_fecho` sempre a `True` fazia o ecrã chamar o
    gestor por causa de um café."""
    _monta(monkeypatch, vendas=[_venda_aberta(), _venda_aberta(id="v2")])

    resposta = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    assert [c["trava_o_fecho"] for c in resposta["contas"]] == [False, False]


def test_cada_conta_diz_de_que_posto_e_e_a_resposta_diz_quem_perguntou(monkeypatch):
    """Os 28,20 € medidos: três contas do turno, uma do Balcão e duas do
    Drive-Thru. O ecrã do Balcão só alcança a dele — e agora tem por onde o
    dizer."""
    _monta(monkeypatch, vendas=[
        _venda_aberta(id="do-balcao"),
        _venda_aberta(id="do-drive-1", dispositivo_id="pc-drive",
                      criada_em="2026-08-15T09:06:00+00:00"),
        _venda_aberta(id="do-drive-2", dispositivo_id="pc-drive",
                      criada_em="2026-08-15T09:07:00+00:00"),
    ])

    resposta = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    assert resposta["total"] == 42.30, "o âmbito da LISTA continua a ser o turno"
    assert resposta["dispositivo_id"] == "pc-balcao", (
        "sem saber quem perguntou, quem desenha não consegue separar as contas "
        "que este posto alcança das que não alcança — o token do POS não viaja "
        "para o browser em texto legível"
    )
    postos = {c["id"]: (c["dispositivo_id"], c["dispositivo_nome"])
              for c in resposta["contas"]}
    assert postos == {
        "do-balcao": ("pc-balcao", "PC Balcão"),
        "do-drive-1": ("pc-drive", "PC Drive-Thru"),
        "do-drive-2": ("pc-drive", "PC Drive-Thru"),
    }


def test_um_pc_revogado_deixa_o_nome_a_none_e_a_conta_na_lista(monkeypatch):
    """O PC foi revogado desde então e já não tem documento. A conta NÃO
    desaparece por causa disso — o que se perde é o nome bonito, e quem lê
    trata a ausência como "outro posto", que é a verdade que se sabe."""
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], movimentos=[],
             vendas=[_venda_aberta(dispositivo_id="pc-que-ja-nao-existe")],
             dispositivos=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)

    resposta = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    assert resposta["quantas"] == 1
    assert resposta["contas"][0]["dispositivo_nome"] is None
    assert resposta["contas"][0]["dispositivo_id"] == "pc-que-ja-nao-existe"


def test_os_nomes_dos_postos_saem_numa_leitura_so(monkeypatch):
    """Um `$in` e não N leituras: são os postos de uma loja, e o fecho já
    corre uma pergunta por conta pela reserva fiscal. Duplicar isso com uma
    pergunta por conta pelo nome do PC era pagar duas vezes pela mesma
    lista."""
    _, registo = _monta(monkeypatch, vendas=[
        _venda_aberta(id="v1"),
        _venda_aberta(id="v2", criada_em="2026-08-15T09:06:00+00:00"),
        _venda_aberta(id="v3", dispositivo_id="pc-drive",
                      criada_em="2026-08-15T09:07:00+00:00"),
    ])

    _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    leituras = [e for e in registo if e[1] == "dispositivos"]
    assert len(leituras) == 1, leituras
    assert leituras[0][2] == {"id": {"$in": ["pc-balcao", "pc-drive"]}}


def test_o_z_tambem_leva_o_posto_de_cada_conta(monkeypatch):
    """O mesmo no Z, e não só na leitura de antes: o gestor que o lê dias
    depois precisa de saber em que posto ficou cada conta para ir perguntar à
    pessoa certa."""
    _monta(monkeypatch, vendas=[
        _venda_aberta(id="do-drive", dispositivo_id="pc-drive"),
    ])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    conta = z["contas_abertas"]["contas"][0]
    assert conta["dispositivo_nome"] == "PC Drive-Thru"
    assert z["contas_abertas"]["dispositivo_id"] == "pc-balcao", (
        "no Z, o posto que perguntou é o PC onde a operadora carregou em "
        "FECHAR CAIXA"
    )


def test_os_dois_subtotais_saem_do_servidor_e_nao_do_browser(monkeypatch):
    """O ecrã mostra as duas famílias em caixas separadas, cada uma com o seu
    euro em cima. Somá-las no JavaScript era pôr o ecrã a fazer aritmética de
    dinheiro — a única coisa que este módulo nunca lhe deixa fazer (regra 1 do
    cabeçalho de `venda.py`). Os dois subtotais têm de bater com o total."""
    _monta(
        monkeypatch,
        vendas=[
            _venda_aberta(id="travada"),
            _venda_aberta(id="normal-1", criada_em="2026-08-15T09:06:00+00:00"),
            _venda_aberta(id="normal-2", criada_em="2026-08-15T09:07:00+00:00"),
        ],
        refs=[{"venda_id": "travada", "ext_ref": "x", "documento_id": None}],
    )

    r = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    assert r["quantas"] == 3 and r["total"] == 42.30
    assert r["quantas_travam"] == 1
    assert r["total_que_trava"] == 14.10
    assert r["total_por_cobrar"] == 28.20
    assert round(r["total_que_trava"] + r["total_por_cobrar"], 2) == r["total"], (
        "As duas metades deixaram de somar o todo — o ecrã passa a mostrar "
        "dois euros que não fecham com o do Z."
    )


def test_uma_conta_sem_valor_nao_estraga_nenhum_dos_subtotais(monkeypatch):
    """A conta que já não se consegue somar continua na lista (o que não se
    pode perder é a existência dela) e não entra em soma nenhuma — nem no
    total, nem no subtotal da família dela."""
    _monta(monkeypatch, vendas=[
        _venda_aberta(id="torta", linhas=[_linha(produto_tax_id=None)]),
        _venda_aberta(id="boa", criada_em="2026-08-15T09:06:00+00:00"),
    ])

    r = _corre(contas_abertas_da_caixa(caixa_id="caixa-1", operador=_operador()))

    assert r["quantas"] == 2
    assert r["total"] == 14.10
    assert r["total_por_cobrar"] == 14.10
    assert r["total_que_trava"] == 0.0


# --- O RETRATO REPETIDO: o Z descreve o turno no instante em que assina -------
#
# **O defeito desta ronda, medido pelas funções reais.** A guarda que
# `venda.py` ganhou na ronda passada (`_garante_sessao_desta_venda_aberta`)
# PERGUNTA pela sessão e não a prende. Entre a pergunta e a escrita da rota há
# idas ao Mongo, e um fecho inteiro cabe lá dentro: com o fecho a correr nessa
# janela, o Z era assinado com `contas_abertas {quantas: 1, total: 14.10}` e a
# seguir o `POST /pos/venda/{id}/linhas` respondia 201 deixando a conta a
# 21,15 €; o `PUT /pos/venda/{id}/desconto` respondia 200 e gravava 50 %; o
# `dividir` e o `separar` criavam partes `aberta` numa sessão já `fechada`. O
# `contas_abertas` gravado na sessão continuava a dizer 14,10 € nos quatro.
#
# O estrago não é a escrita aterrar — é o Z MENTIR: é o único registo de que
# aqueles euros ficaram por receber, e ninguém volta a olhar para a sessão
# depois do fecho.
#
# A correcção não trava escritas nenhumas: tira o retrato das contas abertas
# outra vez, e outra, até duas leituras seguidas darem exactamente o mesmo. A
# marca `a_fechar` garante que o conjunto de escritas em voo é finito e drena
# (nenhum escritor NOVO passa a guarda), por isso a repetição converge — e o Z
# é assinado sobre a última leitura.


class _CursorQueDeixaAterrarUmaEscrita(CursorFalso):
    """Um cursor que, DEPOIS de entregar o resultado de um retrato, deixa
    aterrar a escrita que estava em voo.

    É a única forma de pôr a escrita exactamente onde ela dói: entre duas
    leituras do fecho. Só conta como retrato a leitura que ordena por
    `criada_em` — o filtro de `_contas_abertas_da_sessao` é, letra por letra,
    o de `_venda_com_emissao_viva`, e no registo não se distinguem; a
    ordenação distingue."""

    def __init__(self, itens, registo, nome, aterrar):
        super().__init__(itens, registo, nome)
        self._aterrar = aterrar
        self._e_um_retrato = False

    def sort(self, campo, direccao=1):
        if campo == "criada_em" and direccao == 1:
            self._e_um_retrato = True
        return super().sort(campo, direccao)

    async def to_list(self, n=None):
        itens = await super().to_list(n)
        if self._e_um_retrato:
            self._aterrar()
        return itens


class _VendasComEscritasEmVoo(ColeccaoFalsa):
    """As vendas, com uma fila de escritas que aterram uma por cada retrato
    tirado — o equivalente, em lock-step, a rotas que passaram a guarda um
    instante antes da marca `a_fechar` e cuja escrita chega a seguir."""

    def __init__(self, registo, nome, documentos, escritas):
        super().__init__(registo, nome, documentos)
        self._escritas = list(escritas)
        self.retratos = 0

    def find(self, filtro=None, projecao=None):
        self.registo.append(("find", self.nome, filtro))
        itens = [deepcopy(d) for d in self._documentos if _corresponde(d, filtro)]

        def aterrar():
            self.retratos += 1
            if self._escritas:
                self._escritas.pop(0)(self._documentos)

        return _CursorQueDeixaAterrarUmaEscrita(itens, self.registo, self.nome, aterrar)


def _monta_com_escritas_em_voo(monkeypatch, vendas, escritas):
    registo = []
    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], movimentos=[],
             vendas=[], refs=[])
    coleccao = _VendasComEscritasEmVoo(registo, "vendas", vendas, escritas)
    db._coleccoes[COLECOES["vendas"]] = coleccao
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    _sem_vendus(monkeypatch)
    return db, coleccao


def _mais_um_acai(documentos):
    """A escrita medida: `POST /pos/venda/{id}/linhas` a aterrar depois da
    marca — a conta sobe de 14,10 € para 21,15 €."""
    documentos[0]["linhas"].append(_linha(id="linha-2", quantidade=1))


def test_o_z_leva_a_conta_como_ela_ficou_e_nao_como_estava(monkeypatch):
    """14,10 € no primeiro retrato, um açaí a aterrar a seguir, 21,15 € na
    base. O Z tem de dizer 21,15 € — com uma leitura só dizia 14,10 €, e esse
    número era o único registo daquele dinheiro por receber."""
    _, vendas = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[_mais_um_acai])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["total"] == 21.15, (
        "O Z foi assinado com o retrato de ANTES da escrita — diz %s € onde a "
        "base tem 21,15 €." % z["contas_abertas"]["total"]
    )
    assert z["contas_abertas"]["total_por_cobrar"] == 21.15
    assert vendas.retratos >= 3, (
        "O retrato não chegou a ser repetido: uma leitura só não pode "
        "detectar uma escrita que aterra a seguir a ela."
    )


def test_o_que_fica_gravado_na_sessao_e_o_retrato_estavel(monkeypatch):
    """O Z de papel é o que a operadora leva; o que o gestor lê dias depois é
    o `contas_abertas` gravado na sessão. Têm de ser o mesmo número."""
    db, _ = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[_mais_um_acai])

    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    sessao = db[COLECOES["sessoes_caixa"]]._documentos[0]
    assert sessao["contas_abertas"]["total"] == 21.15


def test_sem_nada_a_mudar_bastam_dois_retratos(monkeypatch):
    """O caso normal — que é toda a gente, todas as noites. Duas leituras
    concordantes e assina-se; repetir sem fim uma leitura por conta aberta
    era pagar o preço de uma corrida que não está a acontecer."""
    _, vendas = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["total"] == 14.10
    assert vendas.retratos == 2, (
        "Foram tirados %s retratos onde dois bastavam." % vendas.retratos)


def test_um_cancelamento_a_aterrar_depois_da_marca_entra_no_z(monkeypatch):
    """O `cancelar_venda` é a única escrita que NÃO passa pela guarda, de
    propósito. Com uma leitura só, um cancelar que aterrasse depois dela
    ficava fora do Z: a primeira tentativa de fecho dizia 1 conta / 14,10 € e
    a retoma respondia `{'quantas': 0, 'total': 0.0}` — dois Z da mesma
    sessão a discordar. Agora o retrato é retirado e o Z descreve o que está
    mesmo lá quando assina."""
    def cancela(documentos):
        documentos[0]["estado"] = "cancelada"

    _, vendas = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[cancela])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["quantas"] == 0, (
        "O Z ficou a dizer que uma conta cancelada ficou por cobrar.")
    assert z["contas_abertas"]["total"] == 0.0
    assert vendas.retratos >= 3


def test_uma_parte_nascida_depois_da_marca_tambem_entra(monkeypatch):
    """`dividir`/`separar` fazem NASCER contas. Uma parte que apareça depois
    do primeiro retrato tem de entrar no Z — senão o turno fecha com dinheiro
    por receber que não está escrito em lado nenhum."""
    def nasce_uma_parte(documentos):
        documentos.append(_venda_aberta(
            id="parte-2", conta_mae_id="venda-1",
            criada_em="2026-08-15T09:07:00+00:00"))

    _, _ = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[nasce_uma_parte])

    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert z["contas_abertas"]["quantas"] == 2
    assert z["contas_abertas"]["total"] == 28.20


def test_se_nunca_estabilizar_nao_se_assina_nenhum_z(monkeypatch):
    """Não estabilizar não é assinar na mesma. É 409 — e a caixa fica em
    `a_fechar`, que é o estado de que se sai carregando outra vez em FECHAR
    CAIXA, e é essa marca que faz a tentativa seguinte encontrar tudo
    parado."""
    def sobe(documentos):
        documentos[0]["linhas"].append(_linha(id="mais", quantidade=1))

    db, _ = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[sobe] * 20)

    with pytest.raises(HTTPException) as e:
        _corre(fechar_caixa(
            PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    assert e.value.status_code == 409
    assert e.value.detail == caixa_mod._MSG_FECHO_SEM_RETRATO_ESTAVEL
    sessao = db[COLECOES["sessoes_caixa"]]._documentos[0]
    assert sessao["estado"] == "a_fechar", (
        "A caixa não ficou marcada a fechar — é essa marca que impede "
        "escritas novas e que faz a tentativa seguinte estabilizar."
    )
    assert sessao.get("contas_abertas") is None, "Ficou gravado um Z que não se assinou."
    assert sessao.get("fechada_em") is None


def test_o_retrato_repetido_nao_desfaz_a_ordem_marca_depois_leitura(monkeypatch):
    """A repetição acrescenta leituras DEPOIS da marca — nunca uma antes. Se
    a primeira delas escorregasse para cima da marca, voltava-se ao retrato
    que ainda podia mudar entre a leitura e o Z."""
    _, _ = _monta_com_escritas_em_voo(
        monkeypatch, vendas=[_venda_aberta()], escritas=[])
    registo = []

    db = _db(registo, caixas=[_caixa()], sessoes=[_sessao()], movimentos=[],
             vendas=[_venda_aberta()], refs=[])
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_operador()))

    marca = next(
        i for i, ev in enumerate(registo)
        if ev[0] == "update_one" and ev[1] == "sessoes"
        and ev[3].get("$set", {}).get("estado") == "a_fechar"
    )
    retratos = [
        i for i, ev in enumerate(registo)
        if ev[0] == "sort" and ev[1] == "vendas" and ev[2] == "criada_em"
    ]
    assert len(retratos) >= 2, "O retrato deixou de ser repetido."
    assert min(retratos) > marca, (
        "Um dos retratos foi tirado ANTES da marca `a_fechar`.")
