"""**A MATRIZ: os cinco leitores respondem à mesma pergunta.**

Cinco rondas corrigiram um par de leitores de cada vez, e as cinco acabaram com
a divergência a reaparecer entre outros dois. Este ficheiro existe para não
haver sexta.

Cruza os estados da VENDA (`aberta`, `emitida`, `cancelada`, `separada` com
partes, `separada` SEM partes, filha órfã, venda apagada) com os da SESSÃO
(`aberta`, `a_fechar`, `fechada`) e com a RESERVA fiscal (sim/não) — 42 casas.
Em cada uma faz as quatro perguntas:

- **quem a vê** — `venda.py::_contas_do_balcao` (a porta e os dois ecrãs);
- **quem a conta** — `caixa.py::_contas_abertas_da_sessao` (o diálogo e o Z);
- **quem a arruma** — `caixa.py::_contas_esquecidas` **e**
  `fiscal.py::listar_reservas_presas` (as duas listas do gestor: uma para o
  dinheiro por cobrar, outra para as emissões por resolver — uma conta com
  reserva viva não se arruma na primeira, e é a segunda que a tem);
- **quem a trava** — `caixa.py::_venda_com_emissao_viva` (o fecho).

E confronta as quatro respostas com uma expectativa escrita À MÃO aqui
(`_o_que_devia_acontecer`) — não com o que a produção devolve. Uma tabela que
só comparasse os leitores uns com os outros ficava verde no dia em que os cinco
se enganassem da mesma maneira; e uma que só medisse a produção contra si
própria não é um teste, é um espelho.

**Os dois invariantes que a matriz prende**, além das 42 expectativas:

1. **Se o travão trava, o diálogo conta.** Foi exactamente aqui que a última
   ronda partiu: o travão passou a perguntar do lado das reservas e via uma
   reserva sem venda; o diálogo que a operadora lê ANTES de assinar continuava
   a partir das vendas e não a via. Ela lia «0 contas por cobrar», carregava em
   FECHAR e levava um 409 a nomear um id que não estava em ecrã nenhum.
2. **Nada por resolver fica invisível.** Toda a conta por resolver aparece pelo
   menos a UM dos três que agem sobre ela — o balcão, o diálogo do fecho ou o
   gestor. Uma mãe `separada` sem partes não aparecia a nenhum, e foi assim que
   11,35 € saíram de um Z assinado a dizer «por cobrar 0,00 €».

Duplo de base de dados no padrão de test_venda.py. Nenhum teste liga a uma base
de dados nem à rede.
"""
import pytest

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import (
    _contas_abertas_da_sessao,
    _contas_esquecidas,
    _venda_com_emissao_viva,
)
from faturacao.fiscal import ext_ref_determinista, listar_reservas_presas
from faturacao.venda import _contas_do_balcao

from .test_venda import (  # noqa: F401
    _caixa,
    _corre,
    _db,
    _linha,
    _operador,
    _produto,
    _sessao,
    _venda,
)

_PC = "pc-balcao"
_LOJA = "loja-1"
_SESSAO = "sessao-1"

# Uma conta de 11,64 € — os valores que EXPÕEM a diferença (0,29 · 1,15 ·
# 10,20), nunca os que a escondem.
_LINHAS = [
    _linha(id="l1", produto_preco=10.20, produto_tax_id="INT"),
    _linha(id="l2", produto_preco=1.15, produto_tax_id="NOR"),
    _linha(id="l3", produto_preco=0.29, produto_tax_id="NOR"),
]
_TOTAL = 11.64

# --- As sete formas que uma conta pode ter -------------------------------------
#
# O nome de cada uma é o que se lhe chama ao balcão; o que está aqui é como ela
# fica na base de dados.
_FORMAS = (
    "aberta",
    "emitida",
    "cancelada",
    "separada_com_partes",
    "separada_sem_partes",
    "filha_orfa",
    "venda_apagada",
)
_ESTADOS_DA_SESSAO = ("aberta", "a_fechar", "fechada")


def _vendas_da_forma(forma):
    """Os documentos de `fat_vendas` desta forma, e o id da conta que está em
    causa (aquela sobre quem as quatro perguntas se fazem)."""
    base = dict(
        id="conta", loja_id=_LOJA, caixa_id="caixa-1", sessao_id=_SESSAO,
        dispositivo_id=_PC, linhas=_LINHAS, criada_em="2026-08-21T10:00:00+00:00",
        entregue_ao_gestor_em=None,
    )
    if forma == "venda_apagada":
        # A filha que a compensação de `_grava_as_partes` apagou: fica só a
        # reserva, sem venda nenhuma por baixo.
        return [], "conta"
    if forma == "separada_com_partes":
        mae = _venda(**dict(base, estado="separada", reparticao_modo="separar"))
        filha = _venda(**dict(
            base, id="parte", estado="aberta", conta_mae_id="conta",
            criada_em="2026-08-21T10:01:00+00:00"))
        # A pergunta é sobre a MÃE: é ela que já não tem nada por receber.
        return [mae, filha], "conta"
    if forma == "separada_sem_partes":
        return [_venda(**dict(base, estado="separada", reparticao_modo="separar"))], "conta"
    if forma == "filha_orfa":
        # Uma parte `aberta` cuja mãe foi apagada da base à mão. Esconder-lhe o
        # dinheiro era o defeito ao contrário.
        return [_venda(**dict(base, estado="aberta", conta_mae_id="mae-que-sumiu"))], "conta"
    return [_venda(**dict(base, estado=forma))], "conta"


def _o_que_devia_acontecer(forma, estado_da_sessao, com_reserva):
    """**A expectativa, escrita à mão.** É o oráculo desta matriz, e não sai de
    função nenhuma da produção.

    Está por resolver: uma venda em estado NÃO TERMINAL (`emitida` e
    `cancelada` são os dois terminais), uma mãe `separada` SEM partes, ou uma
    reserva viva — mesmo sem venda nenhuma por baixo dela."""
    estado_da_venda = {
        "separada_com_partes": "separada", "separada_sem_partes": "separada",
        "filha_orfa": "aberta", "venda_apagada": None,
    }.get(forma, forma)

    reserva_viva = com_reserva and estado_da_venda != "emitida"
    por_resolver = reserva_viva or (
        estado_da_venda in ("aberta",)
        or forma == "separada_sem_partes"
    )
    # **Quem a VÊ**: o balcão só tem em mãos a conta `aberta` de um turno a
    # decorrer. Uma mãe `separada`, uma cancelada e uma emitida não voltam ao
    # ecrã, e um turno que já não está aberto não tem balcão nenhum.
    ve = estado_da_venda == "aberta" and estado_da_sessao == "aberta"
    # **Quem a TRAVA**: a reserva viva, e só ela. O fecho não bloqueia por
    # dinheiro que ninguém vai pagar (regra 3 do dono).
    trava = reserva_viva
    # **Quem a CONTA**: o diálogo do fecho e o Z contam tudo o que está por
    # resolver neste turno, esteja em que estado estiver.
    conta = por_resolver
    # **Quem a ARRUMA**, e são DUAS listas com fins diferentes:
    #
    # - *Contas por Resolver* fica com tudo o que está por resolver e não está
    #   no ecrã de ninguém — é lá que se dá uma conta por perdida;
    # - *Reservas Fiscais Presas* fica com TODA a reserva viva, mesmo a de uma
    #   conta que ainda está ao balcão: essa está travada no ecrã da operadora
    #   (ela não a pode cobrar nem cancelar) e quem a destranca é o gestor.
    #   São as duas ao mesmo tempo, e é de propósito.
    esquecidas = por_resolver and not ve
    presas = reserva_viva
    return {"ve": ve, "trava": trava, "conta": conta,
            "esquecidas": esquecidas, "presas": presas}


def _monta(monkeypatch, forma, estado_da_sessao, com_reserva):
    vendas, alvo = _vendas_da_forma(forma)
    refs = []
    if com_reserva:
        refs = [{
            "id": "ref-1",
            # Pela função que a GERA — a pergunta pelas reservas de uma sessão
            # faz-se pelo prefixo da `ext_ref`, e uma escrita à mão aqui era um
            # documento que a produção nunca poderia ter gravado.
            "ext_ref": ext_ref_determinista(_LOJA, _SESSAO, alvo),
            "venda_id": alvo,
            "criado_em": "2026-08-21T10:02:00+00:00",
            "documento_id": None,
        }]
    db = _db(
        [], caixas=[_caixa()], sessoes=[_sessao(estado=estado_da_sessao)],
        vendas=vendas, refs=refs, produtos=[_produto()],
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda db=db: db)
    return db, alvo


def _as_quatro_perguntas(db, alvo):
    balcao = _corre(_contas_do_balcao(db, _LOJA, _PC))
    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    gestor = _corre(_contas_esquecidas(db))
    # As DUAS listas do gestor. Uma conta com reserva viva não se arruma em
    # Contas por Resolver (`arrumar_conta_esquecida` recusa-a de propósito —
    # pode ter uma FS real do lado da AT); quem a tem é Reservas Fiscais
    # Presas. São dois ecrãs e uma só pergunta: "há aqui alguém que lhe possa
    # pegar?".
    presas = _corre(listar_reservas_presas())
    travada = _corre(_venda_com_emissao_viva(db, {"id": _SESSAO, "loja_id": _LOJA}))
    return {
        "ve": alvo in [v["id"] for v in balcao],
        "conta": alvo in [c["id"] for c in dialogo["contas"]],
        "esquecidas": alvo in [c["id"] for c in gestor],
        "presas": alvo in [r["venda_id"] for r in presas],
        "trava": (travada or {}).get("id") == alvo,
        "dialogo": dialogo,
        "travada": travada,
    }


_CASAS = [
    (forma, sessao, reserva)
    for forma in _FORMAS
    for sessao in _ESTADOS_DA_SESSAO
    for reserva in (False, True)
]


@pytest.mark.parametrize("forma,estado_da_sessao,com_reserva", _CASAS)
def test_a_matriz(monkeypatch, forma, estado_da_sessao, com_reserva):
    """Cada casa da matriz, com as quatro perguntas confrontadas com a
    expectativa escrita à mão. Falha se duas respostas discordarem — ou se
    alguma delas discordar do que devia ser."""
    db, alvo = _monta(monkeypatch, forma, estado_da_sessao, com_reserva)
    obtido = _as_quatro_perguntas(db, alvo)
    esperado = _o_que_devia_acontecer(forma, estado_da_sessao, com_reserva)

    resumo = {k: obtido[k] for k in ("ve", "conta", "esquecidas", "presas", "trava")}
    assert resumo == esperado, (
        "A casa (%s · sessão %s · reserva %s) responde %s e devia responder "
        "%s. Quem a vê, quem a conta, quem a arruma e quem a trava têm de "
        "sair todos do MESMO predicado — se um deles voltou a ter o seu, é a "
        "sexta ronda a começar."
        % (forma, estado_da_sessao, com_reserva, resumo, esperado)
    )

    # **INVARIANTE 1 — se o travão trava, o diálogo conta.** A operadora lê o
    # diálogo ANTES de assinar; um 409 que nomeie um id que ela não viu é um
    # beco.
    if obtido["travada"] is not None:
        ids_no_dialogo = [c["id"] for c in obtido["dialogo"]["contas"]]
        assert obtido["travada"]["id"] in ids_no_dialogo, (
            "O fecho vai recusar por causa de %s e o diálogo que a operadora "
            "lê antes de carregar em FECHAR não a mostra: %s"
            % (obtido["travada"]["id"], ids_no_dialogo)
        )

    # **INVARIANTE 2 — nada por resolver fica invisível.**
    if esperado["conta"]:
        assert (obtido["ve"] or obtido["conta"]
                or obtido["esquecidas"] or obtido["presas"]), (
            "A casa (%s · sessão %s · reserva %s) tem dinheiro por resolver e "
            "não aparece a ninguém — nem ao balcão, nem ao diálogo do fecho, "
            "nem a nenhuma das duas listas do gestor."
            % (forma, estado_da_sessao, com_reserva)
        )


@pytest.mark.parametrize("forma,estado_da_sessao,com_reserva", _CASAS)
def test_o_valor_e_o_mesmo_em_todos_os_leitores(monkeypatch, forma, estado_da_sessao, com_reserva):
    """E o EURO também é um só. Não basta a conta aparecer nos mesmos sítios:
    o valor que o diálogo mostra, o que o gestor lê e o que o Z grava têm de
    ser o mesmo número — senão a operadora assina 11,64 € e o gestor procura
    outra coisa no dia seguinte."""
    db, alvo = _monta(monkeypatch, forma, estado_da_sessao, com_reserva)
    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    gestor = _corre(_contas_esquecidas(db))

    valores = {
        "diálogo": next((c["total"] for c in dialogo["contas"] if c["id"] == alvo), None),
        "gestor": next((c["total"] for c in gestor if c["id"] == alvo), None),
    }
    presentes = {quem: v for quem, v in valores.items() if v is not None}
    if len(presentes) == 2:
        assert presentes["diálogo"] == presentes["gestor"] == _TOTAL, (
            "O mesmo dinheiro com dois valores: %s" % presentes)


# --- Os defeitos que a matriz veio fechar, um a um, com os números medidos -----


def test_uma_mae_separada_sem_partes_nao_sai_de_um_z_assinado(monkeypatch):
    """**11,35 € saíam de um Z assinado.** Medido, antes: `GET
    /pos/venda/aberta` `null`, `GET /pos/venda/repartidas` `[]`,
    `/caixa/contas-esquecidas` 0, o diálogo do fecho `quantas=0 total=0,00` e
    o `POST /pos/caixa/fechar` a responder 200 com «por cobrar 0,00 €»."""
    db, _ = _monta(monkeypatch, "separada_sem_partes", "aberta", False)

    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert (dialogo["quantas"], dialogo["total"]) == (1, _TOTAL), (
        "A mãe `separada` sem partes voltou a não contar para o Z.")
    assert dialogo["contas"][0]["motivo"] == "mae_separada_sem_partes"
    assert [c["id"] for c in _corre(_contas_esquecidas(db))] == ["conta"], (
        "E voltou a não ter ninguém que a arrume.")


def test_uma_mae_separada_COM_partes_esta_resolvida(monkeypatch):
    """O contrário, e é o que impede a correcção de inventar dinheiro: uma mãe
    cujas partes existem já não tem nada por receber — o dinheiro dela mudou-se
    para as filhas, e é lá que se conta. Contá-la nas duas era o Z a dizer o
    dobro."""
    db, _ = _monta(monkeypatch, "separada_com_partes", "aberta", False)

    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert [c["id"] for c in dialogo["contas"]] == ["parte"], (
        "A mãe voltou a ser contada por cima das partes dela — o Z passa a "
        "dizer o dobro do que ficou por receber.")
    assert dialogo["total"] == _TOTAL


def test_uma_reserva_sem_venda_chega_ao_dialogo_e_nao_so_ao_travao(monkeypatch):
    """**O 409 com um id que não estava em ecrã nenhum.** Medido, antes: o
    travão respondia `{'id': 'conta'}` e o `POST /pos/caixa/fechar` dava 409 a
    nomeá-la, enquanto o diálogo dizia `quantas=0 total=0,00`."""
    db, _ = _monta(monkeypatch, "venda_apagada", "aberta", True)

    travada = _corre(_venda_com_emissao_viva(db, {"id": _SESSAO, "loja_id": _LOJA}))
    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert travada is not None and travada["id"] == "conta"
    assert [c["id"] for c in dialogo["contas"]] == ["conta"]
    linha = dialogo["contas"][0]
    assert linha["trava_o_fecho"] is True
    assert linha["motivo"] == "emissao_viva"
    # Não há venda: o valor não se sabe, e "não se sabe" diz-se — nunca 0,00 €.
    assert linha["total"] is None and linha["estado_da_venda"] is None


def test_uma_venda_cancelada_com_reserva_viva_conta_e_trava(monkeypatch):
    """`cancelada` é um estado terminal para a VENDA e não para a EMISSÃO: se a
    reserva está viva, pode estar a nascer uma Fatura Simplificada real do
    outro lado."""
    db, _ = _monta(monkeypatch, "cancelada", "aberta", True)

    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert [(c["id"], c["trava_o_fecho"]) for c in dialogo["contas"]] == [("conta", True)]
    assert dialogo["total_que_trava"] == _TOTAL


def test_uma_venda_emitida_com_reserva_nao_trava_o_fecho_de_todas_as_noites(monkeypatch):
    """A fronteira do outro lado: a reserva de uma venda emitida fica em
    `fat_refs_fiscais` para sempre de propósito (é ela que sustenta a
    idempotência). Travar por causa dela era travar o fecho todas as noites."""
    db, _ = _monta(monkeypatch, "emitida", "aberta", True)

    assert _corre(_venda_com_emissao_viva(db, {"id": _SESSAO, "loja_id": _LOJA})) is None
    assert _corre(_contas_abertas_da_sessao(db, _SESSAO))["quantas"] == 0
    assert _corre(_contas_esquecidas(db)) == []


def test_um_estado_que_ninguem_conhece_cai_do_lado_de_contar(monkeypatch):
    """O filtro é `$nin` sobre os dois estados TERMINAIS, e não uma lista dos
    que contam: um estado novo que apareça amanhã cai do lado de CONTAR, que é
    o lado seguro. Com uma lista, aparecia zero e não dava por nada."""
    vendas, _ = _vendas_da_forma("aberta")
    vendas[0]["estado"] = "em_conferencia"
    db = _db(
        [], caixas=[_caixa()], sessoes=[_sessao()], vendas=vendas, refs=[],
        produtos=[_produto()],
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda db=db: db)

    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert [(c["id"], c["motivo"]) for c in dialogo["contas"]] == [
        ("conta", "estado_desconhecido")]
    assert dialogo["total"] == _TOTAL
    # Mas não vai para o balcão: o ecrã só sabe mostrar uma conta `aberta`.
    assert _corre(_contas_do_balcao(db, _LOJA, _PC)) == []


# --- RAIZ 1: a mãe é o único interruptor da divisão ----------------------------
#
# As filhas nascem PRIMEIRO e a mãe trava a seguir (`venda._grava_as_partes`), e
# a ordem é deliberada — ver lá. O que estava errado era a janela entre as duas
# escritas ser OBSERVÁVEL: as filhas já estavam gravadas e a mãe ainda `aberta`.
#
# Medido pelas rotas reais, com o `insert_one` das vendas espiado: nesse
# instante o `GET /pos/venda/repartidas` respondia **1 grupo com 3 partes**
# (3,79 + 3,78 + 3,78 €) e o `GET /pos/venda/aberta` devolvia uma PARTE de
# 3,78 € como a conta em curso — no lugar da conta de 11,35 € que a operadora
# tinha à frente. É isso que torna a compensação perigosa: ela apaga filhas que
# alguém pode ter visto.


def _db_com_a_mae_aberta(monkeypatch):
    mae = _venda(
        id="mae", dispositivo_id=_PC, posto_em_curso="loja-1|%s" % _PC,
        linhas=[_linha(id="l1", produto_preco=10.20, produto_tax_id="INT"),
                _linha(id="l2", produto_preco=1.15, produto_tax_id="NOR")],
        linhas_versao=0, entregue_ao_gestor_em=None,
    )
    db = _db(
        [], caixas=[_caixa()], sessoes=[_sessao()], vendas=[mae], refs=[],
        produtos=[_produto()], com_indice_do_posto=True,
    )
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda db=db: db)
    return db


def test_as_partes_nao_existem_para_ninguem_antes_de_a_mae_travar(monkeypatch):
    """A janela entre o último insert e a escrita que trava a mãe, espiada por
    dentro. Se alguém a conseguir observar, a compensação está a apagar coisas
    que já foram vistas."""
    from faturacao.db import COLECOES
    from faturacao.venda import PedidoDividir, contas_repartidas, dividir_conta, venda_aberta

    db = _db_com_a_mae_aberta(monkeypatch)
    col = db[COLECOES["vendas"]]
    visto = {}
    inserts = {"n": 0}
    original = col.insert_one

    async def insert_espia(doc):
        await original(doc)
        inserts["n"] += 1
        if inserts["n"] == 3:  # as três filhas já lá estão; a mãe ainda `aberta`
            visto["estado_da_mae"] = (await col.find_one({"id": "mae"}))["estado"]
            visto["repartidas"] = await contas_repartidas(
                "caixa-1", operador=_operador(dispositivo_id=_PC))
            visto["aberta"] = await venda_aberta(
                "caixa-1", operador=_operador(dispositivo_id=_PC))

    col.insert_one = insert_espia
    try:
        _corre(dividir_conta("mae", PedidoDividir(partes=3),
                             operador=_operador(dispositivo_id=_PC)))
    finally:
        col.insert_one = original

    assert visto["estado_da_mae"] == "aberta", (
        "A espia deixou de apanhar a janela — a mãe já tinha travado.")
    assert visto["repartidas"] == [], (
        "O `GET /pos/venda/repartidas` voltou a mostrar as partes de uma "
        "divisão que ainda não aconteceu: %r" % (visto["repartidas"],))
    assert visto["aberta"] is not None and visto["aberta"]["id"] == "mae", (
        "O ecrã voltou a pôr uma PARTE à frente da operadora no lugar da conta "
        "que ela tem em mãos: %r" % (visto["aberta"] or {}).get("id"))
    assert visto["aberta"]["totais"]["total"] == 11.35


def test_depois_de_a_mae_travar_as_partes_aparecem_todas(monkeypatch):
    """O outro lado, e é o que impede a correcção de esconder dinheiro a sério:
    assim que a mãe fica `separada`, as partes voltam ao ecrã."""
    from faturacao.venda import PedidoDividir, contas_repartidas, dividir_conta

    db = _db_com_a_mae_aberta(monkeypatch)
    _corre(dividir_conta("mae", PedidoDividir(partes=3),
                         operador=_operador(dispositivo_id=_PC)))

    grupos = _corre(contas_repartidas(
        "caixa-1", operador=_operador(dispositivo_id=_PC)))
    assert len(grupos) == 1 and len(grupos[0]["partes"]) == 3
    assert sorted(p["totais"]["total"] for p in grupos[0]["partes"]) == [3.78, 3.78, 3.79]
    dialogo = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert (dialogo["quantas"], dialogo["total"]) == (3, 11.35), (
        "As partes deixaram de contar para o Z — a mãe já não conta e elas "
        "também não.")


def test_uma_parte_cuja_mae_foi_apagada_a_mao_continua_a_aparecer(monkeypatch):
    """A pergunta é «a mãe já travou?», e uma mãe que não existe não pode
    responder que não: esconder o dinheiro de uma parte órfã era o defeito ao
    contrário."""
    db, _ = _monta(monkeypatch, "filha_orfa", "aberta", False)

    assert [v["id"] for v in _corre(_contas_do_balcao(db, _LOJA, _PC))] == ["conta"]


# --- RAIZ 3: LIBERTAR não pode fazer dinheiro desaparecer ----------------------


def test_libertar_a_reserva_nao_tira_a_conta_do_ultimo_conjunto_que_a_via(monkeypatch):
    """**O remédio que o sistema nomeia era o gatilho.**

    Mãe `separada` de 11,64 € com a reserva viva. O fecho recusa (409) e a
    mensagem manda o gestor às Reservas Fiscais Presas; ele carrega em LIBERTAR
    — a única saída que lhe é oferecida — e responde `libertada: True`. Medido
    a partir daí, antes desta ronda: balcão `null`,
    `/caixa/contas-esquecidas` 0, `/fiscal/reservas-presas` 0, o diálogo do
    fecho `quantas=0 total=0,00`, e `POST /pos/caixa/fechar` **200 com o Z
    assinado a dizer «por cobrar 0,00 €»** — com 11,64 € na base.

    Já não: a conta é por resolver por si própria (a mãe `separada` sem
    partes), e não por causa da reserva. Libertar deixa de a apagar do mapa."""
    from faturacao.fiscal import PedidoLibertarReserva, libertar_reserva_presa

    db, _ = _monta(monkeypatch, "separada_sem_partes", "aberta", True)
    antes = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert (antes["quantas"], antes["total"], antes["total_que_trava"]) == (
        1, _TOTAL, _TOTAL)

    resposta = _corre(libertar_reserva_presa(
        "conta", PedidoLibertarReserva(confirmado_no_vendus=True),
        gestor={"id": "g1", "nome": "Gestor", "perfil": "gestor"}))
    assert resposta["libertada"] is True

    depois = _corre(_contas_abertas_da_sessao(db, _SESSAO))
    assert (depois["quantas"], depois["total"]) == (1, _TOTAL), (
        "LIBERTAR voltou a apagar %s € do Z." % _TOTAL)
    # Já não trava o fecho — e é isso que se queria —, mas passa a contar como
    # dinheiro por receber, que é o que ela é.
    assert depois["total_que_trava"] == 0.0
    assert depois["total_por_cobrar"] == _TOTAL
    assert [c["id"] for c in _corre(_contas_esquecidas(db))] == ["conta"], (
        "E deixou de ter quem a arrume.")


def test_a_frase_do_libertar_so_nomeia_saidas_que_existem(monkeypatch):
    """`_MSG_LIBERTAR_A_SEGUIR` prometia três saídas — «a conta voltou a poder
    ser ALTERADA, CANCELADA ou FINALIZADA no POS». Exercitadas sobre a mãe
    `separada`: alterar → 409, cancelar → 409, `GET /pos/venda/aberta` →
    `null`. Três saídas nomeadas, zero executáveis."""
    from fastapi import HTTPException
    from faturacao.fiscal import PedidoLibertarReserva, libertar_reserva_presa
    from faturacao.venda import (
        PedidoJuntarLinha, cancelar_venda, juntar_linha, venda_aberta,
    )

    db, _ = _monta(monkeypatch, "separada_sem_partes", "aberta", True)
    resposta = _corre(libertar_reserva_presa(
        "conta", PedidoLibertarReserva(confirmado_no_vendus=True),
        gestor={"id": "g1", "nome": "Gestor", "perfil": "gestor"}))

    a_seguir = resposta["a_seguir"]
    assert "REPARTIDA" in a_seguir and "Contas por Resolver" in a_seguir, (
        "A frase voltou a não dizer onde é que esta conta se resolve: %r"
        % a_seguir)
    assert "alterada, cancelada ou finalizada" not in a_seguir, (
        "A frase voltou a prometer as três saídas que não existem.")

    # E as três, exercitadas — não citadas.
    op = _operador(dispositivo_id=_PC)
    with pytest.raises(HTTPException) as alterar:
        _corre(juntar_linha(
            "conta", PedidoJuntarLinha(produto_id="prod-1", quantidade=1), operador=op))
    assert alterar.value.status_code == 409
    with pytest.raises(HTTPException) as cancelar:
        _corre(cancelar_venda("conta", operador=op))
    assert cancelar.value.status_code == 409
    assert _corre(venda_aberta("caixa-1", operador=op)) is None
