"""Um turno fechado não aceita escritas nas contas dele — e o Z deixa de
mentir.

**O que se media antes desta ronda, pelas rotas reais.** Havia um comentário
no `fechar_caixa` (e outro no ecrã do fecho) a afirmar que, a partir da marca
`a_fechar`, *"nenhuma conta nova pode nascer nesta sessão (`abrir_venda`
resolve a sessão por `_sessao_aberta`)"*. A afirmação era verdadeira sobre o
`abrir_venda` e falsa sobre todo o resto — **só ele passava por lá**:

- com a sessão em `a_fechar`, `POST /pos/venda/{id}/dividir` PASSAVA e
  nasciam 3 contas `aberta` nessa sessão;
- com a sessão já `fechada`, o `dividir` passava outra vez (2 partes novas com
  o `sessao_id` da sessão fechada) e o `POST /pos/venda/{id}/linhas` também —
  a conta subia de 14,10 € para **21,15 € numa sessão cujo Z já estava
  assinado**.

O Z é um retrato assinado de um turno: leva lá dentro, com valor, o que ficou
por cobrar (`caixa.py::_contas_abertas_da_sessao`). Ninguém volta a olhar para
a sessão depois do fecho, por isso o turno continuava a mudar por baixo do Z
sem aparecer em relatório nenhum.

**A correcção é a mesma pergunta que o `finalizar` já fazia**
(`fiscal.py::_garante_sessao_da_venda_aberta`, o defeito I1), agora também nas
rotas que ESCREVEM na conta: `venda.py::_garante_sessao_desta_venda_aberta`.
Uma cópia da pergunta e não um import — `fiscal.py` importa de `venda.py`, e
o contrário fechava o ciclo — com as palavras de quem está a PICAR e não a
cobrar.

**A sétima rota de escrita, o `cancelar_venda`, passa de propósito**, e há um
teste só para isso: cancelar não muda o valor de conta nenhuma nem faz nascer
nada, escreve exactamente o que o Z já diz (esta conta nunca foi cobrada), e é
a única forma de a arrumar. Bloqueá-la deixava as contas de um turno fechado
presas em `aberta` para sempre.

Duplo de base de dados no padrão de test_contas_abertas_no_fecho.py. Nenhum
teste liga a uma base de dados nem à rede.
"""
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.venda import (
    PedidoDescontoGlobal,
    PedidoDividir,
    PedidoEditarLinha,
    PedidoJuntarLinha,
    PedidoSeparar,
    _MSG_SESSAO_A_FECHAR_AGORA,
    _MSG_SESSAO_JA_FECHADA,
    _MSG_VENDA_COM_EMISSAO,
    aplicar_desconto_global,
    cancelar_venda,
    dividir_conta,
    editar_linha,
    juntar_linha,
    remover_linha,
    separar_conta,
)


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


class ResultadoDeleteFalso:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class ColeccaoFalsa:
    """Leituras devolvem CÓPIAS FUNDAS, como o Motor: sem isso, a venda que a
    rota tem em mãos actualiza-se sozinha e um teste fica verde sobre uma
    escrita que nunca aconteceu."""

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
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def delete_one(self, filtro):
        self.registo.append(("delete_one", self.nome, filtro))
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
        "aberta_em": "2026-08-15T09:00:00+00:00", "fundo": 50.0, "estado": "aberta",
    }
    s.update(over)
    return s


def _produto(**over):
    p = {
        "id": "prod-1", "nome": "Açaí Regular", "preco": 7.05, "tax_id": "INT",
        "categoria_id": "cat-1", "grupos_personalizacao": [], "ativo": True,
        "vendus_ref": None,
    }
    p.update(over)
    return p


def _linha(**over):
    li = {
        "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 7.05, "produto_tax_id": "INT", "quantidade": 2, "opcoes": [],
        "respostas_texto": [], "preco_override": None, "tax_override": None,
        "desconto_pct": None, "desconto_eur": None,
    }
    li.update(over)
    return li


def _venda(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "sessao_id": "sessao-1", "operador_id": "op-1", "dispositivo_id": "pc-balcao",
        "linhas": [_linha()], "linhas_versao": 0, "desconto_global_pct": None,
        "desconto_global_eur": None, "estado": "aberta",
        "criada_em": "2026-08-15T09:05:00+00:00",
    }
    v.update(over)
    return v


def _monta(monkeypatch, estado_da_sessao="fechada", vendas=None, refs=None):
    registo = []
    db = DbFalsa(registo, {
        COLECOES["caixas"]: ColeccaoFalsa(registo, "caixas", [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(
            registo, "sessoes", [_sessao(estado=estado_da_sessao)]),
        COLECOES["vendas"]: ColeccaoFalsa(
            registo, "vendas", vendas if vendas is not None else [_venda()]),
        COLECOES["produtos"]: ColeccaoFalsa(registo, "produtos", [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, "refs", refs),
        COLECOES["documentos"]: ColeccaoFalsa(registo, "documentos", []),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, "grupos", []),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    return db, registo


# As sete rotas que escrevem numa venda, cada uma com um pedido válido — o
# ponto é que a recusa vem da SESSÃO, não de um corpo mal formado.
def _juntar():
    return juntar_linha(
        "venda-1", PedidoJuntarLinha(produto_id="prod-1", quantidade=1),
        operador=_operador())


def _editar():
    return editar_linha(
        "venda-1", "linha-1", PedidoEditarLinha(quantidade=3), operador=_operador())


def _remover():
    return remover_linha("venda-1", "linha-1", operador=_operador())


def _descontar():
    return aplicar_desconto_global(
        "venda-1", PedidoDescontoGlobal(desconto_pct=10.0), operador=_operador())


def _dividir():
    return dividir_conta("venda-1", PedidoDividir(partes=2), operador=_operador())


def _separar():
    return separar_conta(
        "venda-1",
        PedidoSeparar(partes=[
            {"linhas": [{"linha_id": "linha-1", "quantidade": 1}]},
            {"linhas": [{"linha_id": "linha-1", "quantidade": 1}]},
        ]),
        operador=_operador(),
    )


AS_SEIS_QUE_MEXEM_NO_DINHEIRO = [
    ("juntar_linha", _juntar),
    ("editar_linha", _editar),
    ("remover_linha", _remover),
    ("aplicar_desconto_global", _descontar),
    ("dividir_conta", _dividir),
    ("separar_conta", _separar),
]


# --- O defeito, rota a rota ----------------------------------------------------


@pytest.mark.parametrize("nome,chamada", AS_SEIS_QUE_MEXEM_NO_DINHEIRO)
def test_com_o_turno_fechado_nenhuma_escreve(monkeypatch, nome, chamada):
    """A sessão está `fechada` e o Z assinado. As seis recusam com 409 e a
    mensagem do turno fechado — nenhuma delas com a mensagem genérica de
    "venda não aberta", que mandaria a operadora procurar uma fatura que não
    existe."""
    _monta(monkeypatch, estado_da_sessao="fechada")

    with pytest.raises(HTTPException) as e:
        _corre(chamada())

    assert e.value.status_code == 409, nome
    assert e.value.detail == _MSG_SESSAO_JA_FECHADA, nome


@pytest.mark.parametrize("nome,chamada", AS_SEIS_QUE_MEXEM_NO_DINHEIRO)
def test_com_o_fecho_a_decorrer_nenhuma_escreve(monkeypatch, nome, chamada):
    """`a_fechar` é o estado intermédio de `caixa.py::fechar_caixa`, posto
    ANTES de o Z somar seja o que for. A recusa é a mesma, a mensagem NÃO: o
    fecho ainda pode ser recusado e desfeito, e a conta continua exactamente
    onde está — dizer-lhe "o turno acabou" mandava-a picar tudo de novo numa
    sessão que pode nunca vir a existir (é a distinção que
    `fiscal.py::SessaoEmFechoAgora` já fazia no FINALIZAR)."""
    _monta(monkeypatch, estado_da_sessao="a_fechar")

    with pytest.raises(HTTPException) as e:
        _corre(chamada())

    assert e.value.status_code == 409, nome
    assert e.value.detail == _MSG_SESSAO_A_FECHAR_AGORA, nome
    assert e.value.detail != _MSG_SESSAO_JA_FECHADA, (
        "as duas mensagens colapsaram numa: quem apanha um fecho A DECORRER "
        "espera segundos, quem apanha um fecho FEITO pica noutra caixa"
    )


def test_o_dividir_num_turno_fechado_nao_deixa_partes_na_base(monkeypatch):
    """O número medido: 2 partes novas `aberta` com o `sessao_id` de uma
    sessão fechada. Não basta responder 409 — o que conta é não ter ficado
    escrito nada."""
    db, _ = _monta(monkeypatch, estado_da_sessao="fechada")

    with pytest.raises(HTTPException):
        _corre(_dividir())

    vendas = db[COLECOES["vendas"]]._documentos
    assert len(vendas) == 1, (
        "nasceram contas numa sessão fechada: %s" % [v["id"] for v in vendas])
    assert vendas[0]["estado"] == "aberta", "a mãe também não pode ficar `separada`"


def test_o_dividir_com_o_fecho_a_decorrer_nao_deixa_partes_na_base(monkeypatch):
    """O caso pior dos dois, e o que faltava mesmo: em `a_fechar` as partes
    nasciam DEPOIS de `_contas_abertas_da_sessao` as ter contado — ficavam
    fora do próprio Z que existe para as mencionar."""
    db, _ = _monta(monkeypatch, estado_da_sessao="a_fechar")

    with pytest.raises(HTTPException):
        _corre(_dividir())

    assert len(db[COLECOES["vendas"]]._documentos) == 1


def test_a_conta_de_14_10_nao_sobe_para_21_15_num_turno_fechado(monkeypatch):
    """O número exacto do achado: dois açaís a 7,05 € picados no turno de
    ontem, um terceiro juntado depois do Z. A conta continua a valer o que o
    Z diz que ela vale."""
    db, _ = _monta(monkeypatch, estado_da_sessao="fechada")

    with pytest.raises(HTTPException):
        _corre(_juntar())

    guardada = db[COLECOES["vendas"]]._documentos[0]
    assert len(guardada["linhas"]) == 1
    assert venda_mod._totais(guardada)["total"] == 14.10


def test_nenhuma_das_seis_escreve_o_que_quer_que_seja(monkeypatch):
    """A rede por baixo dos testes de cima: com o turno fechado, nenhuma das
    seis rotas chega a tocar na base — nem um `update_one` de desconto, nem um
    `insert_one` de parte, nem um `delete_one` de compensação."""
    for nome, chamada in AS_SEIS_QUE_MEXEM_NO_DINHEIRO:
        _, registo = _monta(monkeypatch, estado_da_sessao="fechada")
        with pytest.raises(HTTPException):
            _corre(chamada())
        escritas = [e for e in registo if e[0] in ("update_one", "insert_one", "delete_one")]
        assert escritas == [], "%s escreveu num turno fechado: %s" % (nome, escritas)


# --- A ordem das guardas, e a excepção ----------------------------------------


def test_a_emissao_por_confirmar_fala_primeiro_do_que_o_turno(monkeypatch):
    """Uma conta travada é travada em qualquer turno, e "chame o gestor" é a
    acção certa nos dois casos. Dizer-lhe primeiro "o turno já fechou —
    pique numa conta nova" mandava-a abrir uma segunda conta por cima de uma
    Fatura Simplificada que pode ter saído mesmo."""
    _monta(monkeypatch, estado_da_sessao="fechada",
           refs=[{"venda_id": "venda-1", "ext_ref": "x", "documento_id": None}])

    with pytest.raises(HTTPException) as e:
        _corre(_juntar())

    assert e.value.detail == _MSG_VENDA_COM_EMISSAO


def test_o_cancelar_e_a_unica_escrita_que_passa_num_turno_fechado(monkeypatch):
    """**A excepção, e é uma decisão.** Cancelar não muda o valor de conta
    nenhuma nem faz nascer nada: escreve exactamente o que o Z já diz — que
    esta conta nunca foi cobrada. E é a única forma de a arrumar; bloqueá-la
    deixava as contas de um turno fechado presas em `aberta` para sempre, que
    é o problema oposto e não o mesmo.

    Quem chega aqui com a sessão fechada é o GESTOR
    (`caixa.py::arrumar_conta_esquecida`): com a caixa fechada nenhum ecrã do
    POS mostra estas contas — `GET /pos/venda/aberta` e `GET
    /pos/venda/repartidas` resolvem a sessão por `_sessao_aberta`."""
    db, _ = _monta(monkeypatch, estado_da_sessao="fechada")

    resposta = _corre(cancelar_venda("venda-1", operador=_operador()))

    assert resposta["estado"] == "cancelada"
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "cancelada"


def test_o_cancelar_num_turno_fechado_nao_muda_o_valor_de_nada(monkeypatch):
    """A razão pela qual a excepção de cima é segura, medida e não afirmada:
    a conta continua a valer 14,10 €, as linhas continuam lá, e o Z que a
    registou por 14,10 € continua a bater certo com ela."""
    db, _ = _monta(monkeypatch, estado_da_sessao="fechada")

    _corre(cancelar_venda("venda-1", operador=_operador()))

    guardada = db[COLECOES["vendas"]]._documentos[0]
    assert venda_mod._totais(guardada)["total"] == 14.10
    assert len(guardada["linhas"]) == 1


# --- Os casos em que a pergunta não pode rebentar ------------------------------


def test_com_a_caixa_ABERTA_as_seis_continuam_a_passar(monkeypatch):
    """A guarda tem de ser invisível no dia normal — senão o que ela corrige
    é menos do que estraga."""
    for nome, chamada in AS_SEIS_QUE_MEXEM_NO_DINHEIRO:
        _monta(monkeypatch, estado_da_sessao="aberta")
        resposta = _corre(chamada())
        assert resposta, nome


def test_uma_venda_sem_sessao_id_cai_no_mesmo_409_e_nunca_num_500(monkeypatch):
    """`venda.get("sessao_id")`, não `venda["sessao_id"]` — a mesma correcção
    que o núcleo fiscal já levou. Dados corrompidos ou uma migração
    incompleta têm de dar o 409 de sempre, nunca um KeyError que o balcão lê
    como "o sistema foi abaixo".

    A chave é REMOVIDA, não posta a `None`: com `sessao_id: None` o acesso por
    parêntesis rectos também funciona, e a mutação que troca `.get` por `[...]`
    ficava verde — que é precisamente a mutação que este teste existe para
    apanhar."""
    sem_sessao = _venda()
    del sem_sessao["sessao_id"]
    _monta(monkeypatch, estado_da_sessao="aberta", vendas=[sem_sessao])

    with pytest.raises(HTTPException) as e:
        _corre(_juntar())

    assert e.value.status_code == 409
    assert e.value.detail == _MSG_SESSAO_JA_FECHADA


def test_uma_sessao_que_desapareceu_da_base_tambem_recusa(monkeypatch):
    """A venda aponta para uma sessão que já não existe (apagada à mão, uma
    base restaurada a meio). Não se assume "então está aberta" — assume-se o
    contrário, que é o lado seguro: o que se perde é uma conta que ninguém
    consegue cobrar; o que se ganharia era escrever num turno que não se
    consegue ler."""
    _monta(monkeypatch, estado_da_sessao="aberta",
           vendas=[_venda(sessao_id="sessao-que-nao-existe")])

    with pytest.raises(HTTPException) as e:
        _corre(_dividir())

    assert e.value.status_code == 409
    assert e.value.detail == _MSG_SESSAO_JA_FECHADA


def test_a_pergunta_e_pela_sessao_DESTA_venda_e_nao_pela_caixa(monkeypatch):
    """A caixa reabriu com uma sessão NOVA, e a conta é do turno anterior.
    Perguntar "há alguma sessão aberta nesta caixa" respondia que sim e
    deixava escrever numa conta cujo Z já saiu — é a mesma armadilha que a
    docstring de `fiscal.py::_garante_sessao_da_venda_aberta` descreve."""
    registo = []
    db = DbFalsa(registo, {
        COLECOES["caixas"]: ColeccaoFalsa(registo, "caixas", [_caixa()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(registo, "sessoes", [
            _sessao(id="sessao-1", estado="fechada"),
            _sessao(id="sessao-2", estado="aberta"),
        ]),
        COLECOES["vendas"]: ColeccaoFalsa(registo, "vendas", [_venda()]),
        COLECOES["produtos"]: ColeccaoFalsa(registo, "produtos", [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, "refs", []),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, "grupos", []),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(_juntar())

    assert e.value.detail == _MSG_SESSAO_JA_FECHADA


# --- A releitura das linhas também pergunta -----------------------------------


class VendasQueFechamACaixaAMeio(ColeccaoFalsa):
    """A primeira escrita das linhas não casa (a conta mudou de versão por
    baixo) e, nesse intervalo, outro PC fecha a caixa. `_aplicar_as_linhas`
    relê e repete — e é aí que a pergunta pela sessão tem de voltar a ser
    feita."""

    def __init__(self, registo, nome, documentos, sessoes):
        super().__init__(registo, nome, documentos)
        self._sessoes = sessoes
        self._primeira = True

    async def update_one(self, filtro, atualizacao):
        if self._primeira:
            self._primeira = False
            self._sessoes._documentos[0]["estado"] = "fechada"
            return ResultadoUpdateFalso(matched_count=0)
        return await super().update_one(filtro, atualizacao)


def test_a_releitura_das_linhas_volta_a_perguntar_pela_sessao(monkeypatch):
    """As tentativas duram milissegundos, mas é nessa ordem de grandeza que o
    fecho marca a sessão. Sem a pergunta repetida, a segunda tentativa
    escrevia numa sessão que já estava a somar o Z."""
    registo = []
    sessoes = ColeccaoFalsa(registo, "sessoes", [_sessao(estado="aberta")])
    db = DbFalsa(registo, {
        COLECOES["caixas"]: ColeccaoFalsa(registo, "caixas", [_caixa()]),
        COLECOES["sessoes_caixa"]: sessoes,
        COLECOES["vendas"]: VendasQueFechamACaixaAMeio(
            registo, "vendas", [_venda()], sessoes),
        COLECOES["produtos"]: ColeccaoFalsa(registo, "produtos", [_produto()]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, "refs", []),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, "grupos", []),
    })
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(_juntar())

    assert e.value.detail == _MSG_SESSAO_JA_FECHADA, (
        "a repetição da escrita das linhas passou por cima de uma caixa que "
        "fechou entre as duas tentativas"
    )
    assert len(db[COLECOES["vendas"]]._documentos[0]["linhas"]) == 1
