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
import inspect

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
from faturacao.fiscal import ext_ref_determinista, listar_reservas_presas
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


def crua_nova(db, excepto_id):
    """O id da OUTRA conta aberta deste posto — a que a corrida abriu."""
    todas = _corre(db[COLECOES["vendas"]].find({"estado": "aberta"}).to_list(50))
    return next(v["id"] for v in todas if v["id"] != excepto_id)


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
    encontrada = _corre(_venda_com_emissao_viva(db, _sessao()))

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
    assert _corre(_venda_com_emissao_viva(db, _sessao())) is None


def test_a_conta_de_outra_sessao_nao_trava_este_fecho(monkeypatch):
    """O âmbito continua a ser a SESSÃO que está a fechar. Uma reserva presa na
    caixa do lado é problema do fecho dela."""
    db = _monta(
        monkeypatch,
        vendas=[_conta(estado="cancelada", sessao_id="sessao-outra")],
        # A `ext_ref` é a que a produção teria gravado para uma venda dessa
        # sessão — construída pela MESMA função, nunca escrita à mão: é por ela
        # que o travão sabe de que sessão é a reserva.
        refs=[_reserva(ext_ref=ext_ref_determinista(
            "loja-1", "sessao-outra", "venda-1"))])
    assert _corre(_venda_com_emissao_viva(db, _sessao())) is None


# --- A reserva cuja VENDA já não existe ----------------------------------------
#
# A ronda anterior mudou o FILTRO DO ESTADO e manteve a DIRECÇÃO: a leitura
# partia de `{"sessao_id": …}` em `fat_vendas` e só depois perguntava a
# `fat_refs_fiscais` por cada venda encontrada. Uma reserva cuja venda já não
# existe nunca era alcançada — e as vendas são mesmo apagadas: a compensação de
# `venda._grava_as_partes` faz `delete_one` das filhas em dois caminhos, e as
# filhas são visíveis em `/pos/venda/repartidas` entre o insert e o travão da
# mãe, por isso um `finalizar` pode ter reservado numa delas.


def _reserva_de_uma_filha_apagada():
    """A reserva que uma emissão ganhou numa PARTE que a compensação apagou a
    seguir. A `ext_ref` é a que `fiscal._reservar` teria gravado — construída
    pela MESMA função, porque é o prefixo dela que diz ao fecho de que sessão é
    esta reserva."""
    return _reserva(
        id="ref-filha", venda_id="filha-2",
        ext_ref=ext_ref_determinista("loja-1", "sessao-1", "filha-2"))


def test_uma_reserva_sem_venda_nenhuma_trava_o_fecho(monkeypatch):
    """**O controlo e o defeito, lado a lado.** A MESMA reserva: com a venda
    presente sempre travou; sem a venda, o fecho respondia 200 e assinava o Z
    por cima de uma Fatura Simplificada que podia estar a nascer.

    O que não se pode fechar por cima é uma EMISSÃO viva. Se a venda dela ainda
    existe é ortogonal a isso — tal como o estado em que ela ficou."""
    com_venda = _monta(
        monkeypatch,
        vendas=[_conta(id="filha-2", estado="aberta")],
        refs=[_reserva_de_uma_filha_apagada()])
    assert _corre(_venda_com_emissao_viva(com_venda, _sessao())) is not None

    sem_venda = _monta(monkeypatch, vendas=[], refs=[_reserva_de_uma_filha_apagada()])
    encontrada = _corre(_venda_com_emissao_viva(sem_venda, _sessao()))
    assert encontrada is not None, (
        "A reserva de uma venda que já não existe não trava o fecho. Medido "
        "pelas rotas reais: a mesma reserva com a venda presente dá 409 e sem "
        "a venda dá 200 — com o Z assinado por cima dela.")
    assert encontrada.get("id") == "filha-2", (
        "A recusa tem de nomear a conta: é por esse id que o gestor a procura "
        "em /fiscal/reservas-presas.")


def test_o_fecho_recusa_a_reserva_orfa_pela_rota_e_nao_assina_Z(monkeypatch):
    """A rota inteira: `POST /pos/caixa/fechar` devolve 409 e a sessão fica
    exactamente como estava — sem marca `a_fechar` pendurada e sem Z."""
    db = _monta(monkeypatch, vendas=[], refs=[_reserva_de_uma_filha_apagada()])

    with pytest.raises(HTTPException) as e:
        _corre(fechar_caixa(
            PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))
    assert e.value.status_code == 409
    assert "filha-2" in e.value.detail

    sessao = _corre(db[COLECOES["sessoes_caixa"]].find_one({"id": "sessao-1"}))
    assert sessao["estado"] == "aberta" and sessao.get("contado") is None


def test_uma_reserva_presa_de_uma_sessao_ANTIGA_nao_prende_o_fecho_de_hoje(monkeypatch):
    """A outra ponta, e a que não se pode partir ao arranjar a de cima: a
    pergunta continua a ser DESTA sessão.

    Uma reserva presa de anteontem — cuja venda também já não existe — não pode
    deixar a caixa de hoje por fechar todas as noites até alguém a resolver.
    Ela é do gestor (`/fiscal/reservas-presas`), e é o prefixo da `ext_ref` que
    faz essa separação sem precisar da venda para nada."""
    db = _monta(monkeypatch, vendas=[], refs=[_reserva(
        id="ref-velha", venda_id="venda-de-anteontem",
        ext_ref=ext_ref_determinista("loja-1", "sessao-de-anteontem", "venda-de-anteontem"))])

    assert _corre(_venda_com_emissao_viva(db, _sessao())) is None
    z = _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))
    assert z["estado"] == "fechada"
    assert len(_corre(listar_reservas_presas(_={}))) == 1, (
        "E continua a ser do gestor: se ela desaparecesse também da lista "
        "dele, ninguém a resolvia nunca.")


def test_o_prefixo_da_sessao_sai_da_funcao_que_gera_a_ext_ref():
    """A fórmula da `ext_ref` tem UMA fonte. O travão pergunta pelo prefixo
    `pos-{loja}-{sessão}-`, e se ele o escrevesse à mão bastava mudar o formato
    num sítio para o fecho deixar de encontrar as reservas — em silêncio, e a
    resposta seria 200."""
    prefixo = ext_ref_determinista("loja-1", "sessao-1", "")
    assert ext_ref_determinista("loja-1", "sessao-1", "venda-1").startswith(prefixo)
    assert not ext_ref_determinista("loja-1", "sessao-2", "venda-1").startswith(prefixo)
    # Só o CÓDIGO: a docstring e os comentários da função citam o formato de
    # propósito, e é para continuarem a poder citá-lo.
    fonte = inspect.getsource(caixa_mod._venda_com_emissao_viva)
    codigo = "\n".join(
        linha
        for linha in fonte.replace(
            caixa_mod._venda_com_emissao_viva.__doc__ or "", "").split("\n")
        if not linha.strip().startswith("#")
    )
    assert "ext_ref_determinista" in codigo, (
        "O travão do fecho deixou de construir o prefixo com a função que gera "
        "a referência — é a segunda cópia do formato que um dia diverge.")
    assert "pos-" not in codigo, (
        "O formato da ext_ref voltou a estar escrito à mão dentro do travão.")


# --- O DEFEITO INTEIRO, pelas rotas --------------------------------------------


def test_o_cancelamento_que_colide_deixa_a_conta_visivel_ao_fecho(monkeypatch):
    """**A reprodução medida, do princípio ao fim.**

    Cancelar → a corrida na janela → a compensação a colidir com o índice → e o
    fecho. Antes: 200 e o Z a 0,00 com 8,99 € de emissão viva por baixo. Agora:
    409, e o Z não se assina enquanto a reserva não estiver resolvida.

    **E o que a ronda seguinte acrescentou.** A conta já não acaba `cancelada`:
    a compensação deixou de desistir quando o índice recusa (`_repor_aberta`
    larga a etiqueta do posto e repõe `aberta` na mesma), por isso a frase que
    a operadora ouve — «a conta NÃO foi cancelada» — passou a ser verdade. O
    que o índice continua a não deixar são duas contas EM CURSO no mesmo posto:
    a conta nova fica com a etiqueta, esta fica sem ela, e as duas ficam à
    vista no ecrã deste PC e no Z. O travão do fecho continua a ser o que
    impede a assinatura enquanto a reserva viver."""
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
    assert crua["estado"] == "aberta", (
        "A compensação desistiu outra vez: a conta ficou %r. O 409 diz à "
        "operadora que a conta NÃO foi cancelada — se ela ficar `cancelada`, a "
        "frase é mentira e o dinheiro dela sai de todos os conjuntos que "
        "filtram por `estado: \"aberta\"` (o ecrã, a lista do gestor e o Z)."
        % crua["estado"])
    assert "posto_em_curso" not in crua, (
        "Voltou a `aberta` COM a etiqueta do posto — é a etiqueta que colide, "
        "e mantê-la era não ter reposto nada.")
    assert crua.get("cancelada_em") is None and crua.get("cancelada_por") is None, (
        "A conta voltou a `aberta` com os carimbos do cancelamento colados. "
        "`_venda_publica` mostra-os ao balcão: a operadora fica com uma conta "
        "aberta que o ecrã diz ter sido cancelada às 23h04 pela Rafaela. A "
        "reposição desfaz a escrita INTEIRA, não só o estado.")
    assert {v["id"] for v in _corre(venda_mod._contas_do_balcao(db, "loja-1", _PC))} == {
        a["id"], crua_nova(db, a["id"])}, (
        "O ecrã deste posto tem de mostrar as DUAS: a que sobrou da corrida e a "
        "do cliente novo.")
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
    for estado in ("aberta", "cancelada", "separada", "emitida", None):
        # `None` é a venda que já NÃO EXISTE (uma parte apagada pela
        # compensação): a lista do gestor mostra-a com `estado_da_venda=None`,
        # e o travão do fecho tem de a ver na mesma.
        db = _monta(
            monkeypatch,
            vendas=[] if estado is None else [_conta(estado=estado)],
            refs=[_reserva()])
        presa = len(_corre(listar_reservas_presas(_={}))) > 0
        trava = _corre(_venda_com_emissao_viva(db, _sessao())) is not None
        assert presa == trava, (
            "Com a venda %r: o gestor vê %r e o fecho vê %r — duas respostas "
            "sobre a mesma reserva." % (estado, presa, trava))
