"""**Uma RESERVA fiscal viva trava o fecho, esteja a venda em que estado
estiver.**

O travão do fecho perguntava pelas VENDAS — «há alguma conta AINDA ABERTA
desta sessão com reserva?» — e essa pergunta tem um buraco com a forma exacta
de uma venda `cancelada`.

**Reproduzido pelas rotas reais, com os números que saíram.** A operadora
cancela a conta de 8,99 €. Na janela entre o `$set cancelada` e a segunda
pergunta pela reserva (`venda.py::cancelar_venda`), outro separador abre a
conta seguinte e a emissão desta reserva. A compensação `_repor_aberta` tenta
pôr a conta outra vez `aberta`, colide com o índice único do posto — que já é
da conta nova — e **engole o `DuplicateKeyError`**::

    2. cancelar -> 409 «Esta conta tem uma emissão de fatura em curso...»
    3. estado real da conta A: 'cancelada'   reserva viva: True
       /fiscal/reservas-presas -> 1
    4. POST /pos/caixa/fechar -> 200
       Z: vendas_dinheiro=0.00  esperado=50.00  contado=50.00  diferenca=0.00

A operadora ouve «a conta NÃO foi cancelada … está travada» — **e ela está
cancelada**. A venda fica `cancelada` com uma Fatura Simplificada REAL a poder
estar a nascer do outro lado. E como o travão só varria as `aberta`, o
`POST /pos/caixa/fechar` respondia **200 e o Z saía a 0,00** por cima dela: é
exactamente o estrago que a docstring de `cancelar_venda` diz existir para
impedir. Só `/fiscal/reservas-presas` ainda a mostrava.

**A assimetria que o torna fácil de fechar.** O travão perguntava pelas vendas
e devia perguntar pelas reservas: o que não se pode fechar por cima é uma
EMISSÃO viva, e o estado da venda é ortogonal a isso. O critério passa a ser o
mesmo de `fiscal.py::listar_reservas_presas` — «a reserva existe e a venda
dela ainda não está `emitida`» —, e é por isso que a lista do gestor e o
travão do fecho deixam de poder discordar sobre a mesma conta.

Duplo de base de dados no padrão de `test_venda.py`. Nenhum teste liga a uma
base de dados nem à rede.
"""
import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import (
    PedidoFecharCaixa,
    _venda_com_emissao_viva,
    fechar_caixa,
)
from faturacao.db import COLECOES
from faturacao.fiscal import listar_reservas_presas
from faturacao.venda import (
    PedidoJuntarLinha,
    PedidoNovaVenda,
    abrir_venda,
    cancelar_venda,
    juntar_linha,
)

from .test_venda import (  # noqa: F401
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


def _op(**over):
    o = _operador(dispositivo_id=_PC)
    o.update(over)
    return o


def _monta(monkeypatch, vendas=None, refs=None):
    db = _db(
        [],
        caixas=[_caixa()],
        sessoes=[_sessao()],
        vendas=vendas,
        refs=refs,
        produtos=[_produto()],
        com_indice_do_posto=True,
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda: db)
    return db


def _conta(**over):
    # O id por omissão de `_venda()` é `venda-1`, e o de `_reserva()` aponta
    # para ele: os dois construtores vêm de test_venda.py e casam-se de fábrica.
    v = _venda(
        dispositivo_id=_PC, linhas=[_linha()],
        entregue_ao_gestor_em=None, criada_em="2026-08-21T10:00:00+00:00",
    )
    v.update(over)
    return v


# --- O travão, estado a estado -------------------------------------------------
#
# `aberta` já travava. Os outros três estados são o buraco, e o `emitida` é a
# fronteira do outro lado: a reserva de uma venda emitida fica em
# `fat_refs_fiscais` PARA SEMPRE de propósito (é ela que sustenta a
# idempotência), e travar por causa dela era travar o fecho de todas as noites.

@pytest.mark.parametrize("estado,trava", [
    ("aberta", True),
    ("cancelada", True),
    ("separada", True),
    ("emitida", False),
])
def test_a_reserva_viva_trava_o_fecho_seja_qual_for_o_estado_da_venda(
    estado, trava, monkeypatch
):
    """A pergunta é pela RESERVA. O `cancelada` é o caso medido; o `separada`
    entra pela mesma porta (uma mãe separada com reserva presa da tentativa de
    emissão da conta inteira); e o `emitida` tem de continuar a NÃO travar."""
    db = _monta(monkeypatch, vendas=[_conta(estado=estado)], refs=[_reserva()])
    encontrada = _corre(_venda_com_emissao_viva(db, "sessao-1"))

    assert (encontrada is not None) == trava, (
        "Uma venda %r com reserva fiscal viva %s o fecho. Enquanto a reserva "
        "estiver viva pode estar a nascer uma Fatura Simplificada REAL do outro "
        "lado, e fechar a caixa a meio disso é assinar o Z antes de o dinheiro "
        "estar contado — seja qual for o estado em que a venda ficou."
        % (estado, "não travou" if trava else "travou e não devia")
    )


def test_o_fecho_recusa_com_a_conta_cancelada_e_a_reserva_viva(monkeypatch):
    """A rota inteira, e não só a função: `POST /pos/caixa/fechar` tem de
    devolver 409 e não pode ter escrito Z nenhum."""
    db = _monta(
        monkeypatch, vendas=[_conta(estado="cancelada")], refs=[_reserva()])

    with pytest.raises(HTTPException) as e:
        _corre(fechar_caixa(
            PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))

    assert e.value.status_code == 409
    assert "venda-1" in e.value.detail
    sessao = _corre(db[COLECOES["sessoes_caixa"]].find_one({"id": "sessao-1"}))
    assert sessao["estado"] == "aberta", (
        "A sessão ficou em %r — o fecho recusou mas deixou a caixa marcada. A "
        "marca `a_fechar` tem de ser desfeita quando a segunda pergunta recusa."
        % sessao["estado"]
    )


def test_o_fecho_de_uma_noite_normal_continua_a_passar(monkeypatch):
    """A rede de segurança do teste de cima: com as reservas todas resolvidas
    (vendas `emitida`), o fecho não pode passar a recusar. Uma caixa que não
    fecha manda a funcionária para casa sem Z."""
    db = _monta(
        monkeypatch,
        vendas=[_conta(estado="emitida"), _conta(id="v-2", estado="emitida")],
        refs=[_reserva(id="r-1", documento_id="doc-1"),
              _reserva(id="r-2", venda_id="v-2", documento_id="doc-2")],
    )
    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))
    assert z["estado"] == "fechada"


def test_uma_venda_cancelada_SEM_reserva_nao_trava_nada(monkeypatch):
    """O caso banal, e o que a mudança não pode partir: cancelar uma conta que
    ninguém pagou é a saída normal do balcão, e uma noite com dez dessas tem de
    fechar na mesma."""
    db = _monta(monkeypatch, vendas=[_conta(estado="cancelada")], refs=[])
    assert _corre(_venda_com_emissao_viva(db, "sessao-1")) is None


def test_a_conta_de_outra_sessao_nao_trava_este_fecho(monkeypatch):
    """O âmbito continua a ser a SESSÃO que está a fechar. Uma reserva presa na
    caixa do lado é problema do fecho dela."""
    db = _monta(
        monkeypatch,
        vendas=[_conta(estado="cancelada", sessao_id="sessao-outra")],
        refs=[_reserva()])
    assert _corre(_venda_com_emissao_viva(db, "sessao-1")) is None


# --- O DEFEITO INTEIRO, pelas rotas --------------------------------------------


def test_o_cancelamento_que_colide_deixa_a_conta_visivel_ao_fecho(monkeypatch):
    """**A reprodução medida, do princípio ao fim.**

    Cancelar → a corrida na janela → a compensação a colidir com o índice → e o
    fecho. Antes: 200 e o Z a 0,00 com 8,99 € de emissão viva por baixo. Agora:
    409, e o Z não se assina enquanto a reserva não estiver resolvida.

    O que aqui NÃO se corrige, e é de propósito: a conta continua a acabar
    `cancelada` com a reserva viva — o índice único não deixa duas contas em
    curso no mesmo posto, e a conta nova já lá está. O que muda é que essa
    conta deixou de ser invisível ao travão do fecho, que é o que a impedia de
    ser encontrada antes de alguém assinar um Z."""
    db = _monta(monkeypatch)
    a = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()))
    _corre(juntar_linha(
        a["id"], PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=_op()))

    refs = db[COLECOES["refs_fiscais"]]
    original = refs.find_one
    chamadas = {"n": 0}

    async def na_janela(filtro, projecao=None):
        chamadas["n"] += 1
        # A SEGUNDA pergunta pela reserva é a de DEPOIS do `$set cancelada`.
        if chamadas["n"] == 2:
            await abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op())
            await refs.insert_one({
                "id": "ref-a", "ext_ref": "pos-loja-1-sessao-1-%s" % a["id"],
                "venda_id": a["id"], "criado_em": "2026-08-21T10:01:00+00:00",
            })
        return await original(filtro, projecao)

    refs.find_one = na_janela
    with pytest.raises(HTTPException) as cancelou:
        _corre(cancelar_venda(a["id"], operador=_op()))
    refs.find_one = original
    assert cancelou.value.status_code == 409

    crua = _corre(db[COLECOES["vendas"]].find_one({"id": a["id"]}))
    assert crua["estado"] == "cancelada", (
        "A reprodução deixou de reproduzir: a compensação conseguiu repor a "
        "conta `aberta`, e este teste passou a medir outra coisa. Se o índice "
        "ou a compensação mudaram, é aqui que se descobre.")
    assert len(_corre(listar_reservas_presas(_={}))) == 1

    with pytest.raises(HTTPException) as fechou:
        _corre(fechar_caixa(
            PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))
    assert fechou.value.status_code == 409, (
        "O fecho passou com uma emissão viva por baixo de uma conta cancelada: "
        "o Z sai a 0,00 e os 8,99 € não entram em Z nenhum.")

    sessao = _corre(db[COLECOES["sessoes_caixa"]].find_one({"id": "sessao-1"}))
    assert sessao["estado"] == "aberta"
    assert sessao.get("contado") is None, (
        "Ficou um Z escrito na sessão apesar da recusa.")


def test_o_travao_do_fecho_e_a_lista_do_gestor_concordam(monkeypatch):
    """As duas perguntas sobre a mesma conta têm de dar a mesma resposta: o que
    o gestor vê em `/fiscal/reservas-presas` é o que impede o fecho de assinar
    o Z. Enquanto discordassem, havia contas que apareciam a quem não as podia
    resolver e desapareciam de quem lhes ia passar por cima."""
    for estado in ("aberta", "cancelada", "separada", "emitida"):
        db = _monta(monkeypatch, vendas=[_conta(estado=estado)], refs=[_reserva()])
        presa = len(_corre(listar_reservas_presas(_={}))) > 0
        trava = _corre(_venda_com_emissao_viva(db, "sessao-1")) is not None
        assert presa == trava, (
            "Com a venda %r: o gestor vê %r e o fecho vê %r — duas respostas "
            "sobre a mesma reserva." % (estado, presa, trava))
