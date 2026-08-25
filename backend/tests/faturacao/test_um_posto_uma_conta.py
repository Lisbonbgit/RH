"""**O conjunto que a PORTA recusa é o conjunto que o ECRÃ mostra — o MESMO,
não um igual.**

O defeito que este ficheiro fecha, medido pelas rotas reais numa loja com duas
caixas activas. 8,99 € picados na caixa Balcão; o PC passa para a caixa Drive
(o ecrã «Qual caixa?» do `PosApp.js` é o caminho normal quando o localStorage
não traz caixa)::

    1. conta na caixa Balcão: total=8.99 EUR  caixa=caixa-1
    2. GET /pos/venda/aberta?caixa_id=caixa-2 -> None
       GET /pos/venda/repartidas?caixa_id=caixa-2 -> []
       GET /fiscal/reservas-presas -> 0
       GET /pos/caixa/contas-esquecidas -> []
       POST /pos/venda -> 409 «Acabe a que está à frente: cobre-a ou cancele-a»
    3. corrida em duas caixas -> ['201', '201']
       contas abertas neste posto: 2

Sete toques até ficar sem saída, e as três saídas que a mensagem nomeia
(cobrar, cancelar, entregar ao gestor) exigem todas uma conta no ecrã — que não
está lá. Se o gestor desactivar a caixa Balcão, `GET /pos/caixa/estado` passa a
404 e o beco fica permanente.

**Já se tentou alinhar dois conjuntos três vezes, e as três divergiram.** Havia
quatro respostas à mesma pergunta: `_conta_por_resolver` varria as sessões
abertas da LOJA, `venda_aberta` varria UMA sessão, `contas_repartidas` também,
e a chave do índice único era `"{sessao_id}|{dispositivo_id}"`. Enquanto
houvesse uma caixa e uma conta, os quatro concordavam.

Por isso o que este ficheiro guarda não é «esta função devolve o mesmo que
aquela». É que **existe UMA função** — `venda.py::_contas_do_balcao` — e que o
âmbito dela **não é um parâmetro**: quem a chama não escolhe a caixa, e por isso
não a pode escolher diferente. Os testes de invariante aqui em baixo fazem as
duas perguntas (a porta recusa? o ecrã mostra?) a cada arranjo do balcão e
exigem a MESMA resposta — é a forma de isto ficar vermelho se alguém voltar a
partir o conjunto em dois.

Duplo de base de dados de `test_venda.py` (reutilizado, nunca reescrito):
`find`/`find_one` filtram a sério, as leituras devolvem cópias, e o índice
único parcial de `db.py` é feito cumprir no `insert_one`/`update_one` — é isso
que dá às corridas aqui em baixo alguma coisa de verdadeiro para medir.
Nenhum teste liga a uma base de dados nem à rede.
"""
import asyncio
import json
import subprocess

import pytest
from fastapi import HTTPException

from faturacao import caixa as caixa_mod
from faturacao import fiscal as fiscal_mod
from faturacao import venda as venda_mod
from faturacao.caixa import PedidoFecharCaixa, fechar_caixa
from faturacao.db import COLECOES
from .test_arredondamento_do_ecra import (
    _LIB_POS,
    _corpo_da_funcao,
    _corpo_da_seta,
    _ler,
    _node,
)
from faturacao.venda import (
    PedidoJuntarLinha,
    PedidoNovaVenda,
    abrir_venda,
    contas_repartidas,
    juntar_linha,
    venda_aberta,
)

# O duplo de base de dados e os construtores de documentos vivem em
# test_venda.py e importam-se de lá. Uma segunda cópia deles aqui era um duplo
# a divergir do outro em silêncio — exactamente a forma de falhar que este
# ficheiro existe para apanhar, só que nos testes.
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


# --- O balcão, montado ---------------------------------------------------------
#
# Duas caixas ACTIVAS na mesma loja, cada uma com a sua sessão aberta, e um PC
# só. É a configuração das lojas com Balcão + Drive, e é a mais pequena em que
# os quatro conjuntos de antes davam respostas diferentes.

_LOJA = "loja-1"
_PC = "pc-balcao"


def _duas_caixas(registo, vendas=None, refs=None, sessoes=None, **over):
    return _db(
        registo,
        caixas=[_caixa(id="caixa-1", nome="Balcão"), _caixa(id="caixa-2", nome="Drive")],
        sessoes=[
            _sessao(id="sessao-1", caixa_id="caixa-1"),
            _sessao(id="sessao-2", caixa_id="caixa-2"),
        ] if sessoes is None else sessoes,
        vendas=vendas,
        refs=refs,
        produtos=[_produto()],
        com_indice_do_posto=True,
        **over,
    )


def _liga(db, monkeypatch):
    """O `obter_db` dos três módulos que estas rotas atravessam."""
    for modulo in (venda_mod, caixa_mod, fiscal_mod):
        monkeypatch.setattr(modulo, "obter_db", lambda: db)


def _conta(**over):
    """Uma conta do balcão como `abrir_venda` a grava — incluindo a etiqueta
    do posto, que é a chave do índice único parcial. Sem ela, um teste da
    corrida ficava verde com o índice apagado."""
    v = _venda(
        id="v-balcao",
        caixa_id="caixa-1",
        sessao_id="sessao-1",
        dispositivo_id=_PC,
        linhas=[_linha()],
        entregue_ao_gestor_em=None,
        entregue_ao_gestor_por=None,
        criada_em="2026-08-21T10:00:00+00:00",
    )
    v["posto_em_curso"] = "%s|%s" % (_LOJA, _PC)
    v.update(over)
    return v


def _parte(**over):
    """Uma parte de uma conta repartida (`venda.py::_nova_parte`): herda a
    sessão, a caixa e o dispositivo da mãe, e NÃO leva etiqueta do posto — as
    partes são várias por posto, de propósito."""
    v = _venda(
        id="v-parte-1",
        caixa_id="caixa-1",
        sessao_id="sessao-1",
        dispositivo_id=_PC,
        conta_mae_id="v-mae",
        linhas=[_linha(quantidade=0.5)],
        entregue_ao_gestor_em=None,
        criada_em="2026-08-21T10:05:00+00:00",
    )
    v.update(over)
    return v


def _mae_separada(**over):
    v = _venda(
        id="v-mae",
        caixa_id="caixa-1",
        sessao_id="sessao-1",
        dispositivo_id=_PC,
        estado="separada",
        linhas=[_linha()],
        criada_em="2026-08-21T10:04:00+00:00",
    )
    v.update(over)
    return v


# --- As duas perguntas, feitas às ROTAS ----------------------------------------


def _a_porta_recusa(vendas, refs, monkeypatch, caixa_id="caixa-2", sessoes=None):
    """`POST /pos/venda` na caixa em que o ecrã está: recusou?

    Base de dados NOVA em cada pergunta — o `abrir_venda` escreve, e uma base
    partilhada com a pergunta do ecrã media o balcão depois de esta ter mexido
    nele."""
    db = _duas_caixas([], vendas=[dict(v) for v in vendas],
                      refs=[dict(r) for r in refs], sessoes=sessoes)
    _liga(db, monkeypatch)
    try:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id=caixa_id), operador=_op()))
        return None
    except HTTPException as e:
        return e


def _o_ecra_mostra(vendas, refs, monkeypatch, caixa_id="caixa-2", sessoes=None):
    """`GET /pos/venda/aberta` + `GET /pos/venda/repartidas` na MESMA caixa:
    o que é que a operadora tem à frente?"""
    db = _duas_caixas([], vendas=[dict(v) for v in vendas],
                      refs=[dict(r) for r in refs], sessoes=sessoes)
    _liga(db, monkeypatch)
    conta = _corre(venda_aberta(caixa_id=caixa_id, operador=_op()))
    grupos = _corre(contas_repartidas(caixa_id=caixa_id, operador=_op()))
    return conta, grupos


def _op(**over):
    o = _operador(dispositivo_id=_PC)
    o.update(over)
    return o


# --- A INVARIANTE --------------------------------------------------------------
#
# «O conjunto de contas que IMPEDE abrir uma conta nova é EXACTAMENTE o
# conjunto que a operadora consegue ver e resolver no ecrã em que está.»


# Cada arranjo: (nome, vendas, reservas, o ecrã tem de mostrar alguma coisa?).
# O ecrã está SEMPRE na caixa Drive (caixa-2) — é a troca de caixa que fazia o
# beco, e é o arranjo que os quatro conjuntos de antes respondiam de quatro
# maneiras.
_ARRANJOS = [
    (
        "o balcão livre",
        [], [], False,
    ),
    (
        "uma conta na MESMA caixa em que o ecrã está",
        [_conta(caixa_id="caixa-2", sessao_id="sessao-2")], [], True,
    ),
    (
        "uma conta na OUTRA caixa do mesmo posto",
        [_conta()], [], True,
    ),
    (
        "uma conta TRAVADA na outra caixa (reserva fiscal viva)",
        [_conta()], [_reserva(venda_id="v-balcao")], True,
    ),
    (
        "as partes por cobrar de uma conta repartida na outra caixa",
        [_mae_separada(), _parte(), _parte(id="v-parte-2")], [], True,
    ),
    (
        "uma conta de OUTRO posto",
        [_conta(id="v-outro", dispositivo_id="pc-drive",
                posto_em_curso="%s|pc-drive" % _LOJA)], [], False,
    ),
    (
        "uma conta já ENTREGUE AO GESTOR",
        [_conta(entregue_ao_gestor_em="2026-08-21T10:10:00+00:00",
                posto_em_curso=None)], [], False,
    ),
    (
        "uma conta já emitida",
        [_conta(estado="emitida", posto_em_curso=None)], [], False,
    ),
    (
        "uma conta já cancelada",
        [_conta(estado="cancelada", posto_em_curso=None)], [], False,
    ),
]


@pytest.mark.parametrize(
    "nome,vendas,refs,ha_conta", _ARRANJOS, ids=[a[0] for a in _ARRANJOS])
def test_a_porta_recusa_exactamente_o_que_o_ecra_mostra(
    nome, vendas, refs, ha_conta, monkeypatch
):
    """**A invariante, corrida arranjo a arranjo.** Não se compara uma função
    com outra: fazem-se as duas perguntas às ROTAS e exige-se a mesma resposta.

    O arranjo que estava partido é «uma conta na OUTRA caixa do mesmo posto»:
    a porta recusava (o âmbito dela era a loja) e o ecrã não mostrava nada (o
    âmbito dele era uma sessão). Sete toques até ficar sem saída."""
    recusa = _a_porta_recusa(vendas, refs, monkeypatch)
    conta, grupos = _o_ecra_mostra(vendas, refs, monkeypatch)

    porta_recusou = recusa is not None
    ecra_mostrou = conta is not None or len(grupos) > 0

    assert porta_recusou == ha_conta, (
        "%s: a porta %s. Uma conta que prende o posto tem de o prender, e uma "
        "que não prende tem de deixar passar." % (
            nome, "recusou e não devia" if porta_recusou else "deixou passar e não devia")
    )
    assert ecra_mostrou == ha_conta, (
        "%s: o ecrã %s. O que a porta conta tem de estar à frente da operadora "
        "— senão as saídas que a recusa nomeia (cobrar, cancelar, entregar ao "
        "gestor) não se executam com dedo nenhum." % (
            nome, "mostrou e não devia" if ecra_mostrou else "não mostrou nada")
    )
    assert porta_recusou == ecra_mostrou, (
        "%s: a porta diz %r e o ecrã diz %r. São dois conjuntos outra vez — e "
        "é a quarta vez." % (nome, porta_recusou, ecra_mostrou)
    )


def test_a_conta_da_outra_caixa_vem_com_a_caixa_dela_a_vista(monkeypatch):
    """O ecrã tem de poder DIZER onde ela ficou. A conta chega com o
    `caixa_id` dela (que não é o da caixa em que o ecrã está) — sem isso, a
    operadora vê uma conta que não sabe de onde vem."""
    conta, _ = _o_ecra_mostra([_conta()], [], monkeypatch, caixa_id="caixa-2")
    assert conta is not None, (
        "A conta de 8,99 € da caixa Balcão não apareceu no ecrã posto na caixa "
        "Drive — é o beco medido: a porta recusa-a e a operadora não lhe chega."
    )
    assert conta["caixa_id"] == "caixa-1"
    assert conta["totais"]["total"] == 8.99


def test_a_recusa_da_porta_diz_em_que_caixa_ficou_a_conta(monkeypatch):
    """A mensagem manda «acabe a que está à frente». Quando ela está à frente
    noutra caixa, tem de o dizer — senão a instrução é a mesma que não se
    conseguia cumprir, só que agora com a conta visível."""
    recusa = _a_porta_recusa([_conta()], [], monkeypatch, caixa_id="caixa-2")
    assert recusa is not None and recusa.status_code == 409
    assert "Balcão" in recusa.detail, (
        "A recusa não nomeia a caixa onde a conta ficou (%r). O nome da caixa é "
        "o que a operadora precisa de ler para saber onde a foi buscar."
        % recusa.detail
    )


def test_a_conta_na_mesma_caixa_nao_ganha_uma_nota_sobre_caixas(monkeypatch):
    """O caso normal — uma caixa só — não pode passar a falar de caixas. Numa
    loja com uma caixa, «ela ficou na caixa Balcão» é ruído sobre a única
    caixa que existe."""
    recusa = _a_porta_recusa(
        [_conta(caixa_id="caixa-2", sessao_id="sessao-2")], [], monkeypatch,
        caixa_id="caixa-2")
    assert recusa is not None
    assert "Drive" not in recusa.detail, (
        "A recusa nomeou a caixa em que a operadora JÁ está: %r" % recusa.detail)


# --- A CORRIDA, que atravessava o índice ---------------------------------------


def test_dois_toques_em_caixas_diferentes_dao_uma_conta_so(monkeypatch):
    """**A corrida do duplo toque, agora entre CAIXAS.** Dois `POST /pos/venda`
    simultâneos do mesmo PC em caixas diferentes davam 201 + 201: as chaves do
    índice diferiam no `sessao_id`, e a porta era da loja. Ficavam duas contas
    abertas neste posto — uma delas invisível, que é o defeito inteiro outra
    vez.

    O duplo cede o event loop em cada ida à base de dados (`ceder=True`), como
    o Motor contra o Mongo real: sem isso as duas rotas corriam uma depois da
    outra e este teste media o caminho sequencial."""
    db = _duas_caixas([], ceder=True)
    _liga(db, monkeypatch)

    async def as_duas():
        return await asyncio.gather(
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()),
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()),
            return_exceptions=True,
        )

    saidas = _corre(as_duas())
    criadas = [s for s in saidas if isinstance(s, dict)]
    recusas = [s for s in saidas if isinstance(s, HTTPException)]
    abertas = [
        d for d in db[COLECOES["vendas"]]._documentos if d.get("estado") == "aberta"
    ]

    assert len(criadas) == 1 and len(recusas) == 1, (
        "Os dois toques passaram (%d criadas, %d recusas): o índice único não "
        "atravessa as caixas, e este posto ficou com duas contas em curso."
        % (len(criadas), len(recusas))
    )
    assert recusas[0].status_code == 409
    assert len(abertas) == 1, "Ficaram %d contas abertas neste posto." % len(abertas)


def test_dois_toques_na_MESMA_caixa_continuam_a_dar_uma_conta_so(monkeypatch):
    """A garantia que já existia, e que a mudança de chave não pode perder."""
    db = _duas_caixas([], ceder=True)
    _liga(db, monkeypatch)

    async def as_duas():
        return await asyncio.gather(
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()),
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()),
            return_exceptions=True,
        )

    saidas = _corre(as_duas())
    assert len([s for s in saidas if isinstance(s, dict)]) == 1
    assert len([s for s in saidas if isinstance(s, HTTPException)]) == 1


def test_dois_postos_diferentes_abrem_cada_um_a_sua(monkeypatch):
    """E o índice não pode passar a prender POSTOS diferentes um ao outro: o
    PC Balcão e o PC Drive-Thru atendem dois clientes ao mesmo tempo, que é
    para isso que a loja tem dois PCs."""
    db = _duas_caixas([], ceder=True)
    _liga(db, monkeypatch)

    async def as_duas():
        return await asyncio.gather(
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"), operador=_op()),
            abrir_venda(PedidoNovaVenda(caixa_id="caixa-1"),
                        operador=_op(dispositivo_id="pc-drive")),
            return_exceptions=True,
        )

    saidas = _corre(as_duas())
    assert [type(s) for s in saidas] == [dict, dict], (
        "Um dos dois postos foi recusado: %s" % saidas)


# --- O turno que fecha, e a etiqueta que fica para trás -------------------------


def test_uma_conta_de_um_turno_FECHADO_nao_tranca_o_posto(monkeypatch):
    """**A outra ponta da mesma decisão, e a que não pode ficar por medir.**

    A chave do índice passou a ser do POSTO (`"{loja_id}|{dispositivo_id}"`), e
    não da sessão. Uma conta que fique `aberta` quando o turno fecha continua a
    ter a etiqueta — e, sem mais nada, trancava este PC na manhã seguinte com
    um 409 que a porta não sabe explicar: a leitura dela só varre sessões
    ABERTAS, por isso responderia «o balcão está livre» ao mesmo tempo que o
    índice recusava. Um beco novo no lugar do velho.

    Por isso o fecho tira a etiqueta às contas que deixa abertas (elas passam a
    ser do gestor, `GET /caixa/contas-esquecidas`), e é isso que aqui se corre:
    fecha-se a caixa com uma conta aberta lá dentro e abre-se a conta seguinte
    na caixa que ficou."""
    db = _duas_caixas([], vendas=[_conta()])
    _liga(db, monkeypatch)

    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))

    esquecida = _corre(db[COLECOES["vendas"]].find_one({"id": "v-balcao"}))
    assert esquecida["estado"] == "aberta", (
        "O fecho mexeu no ESTADO da conta esquecida — não é o que se pediu: o "
        "dinheiro dela continua por receber e o Z regista-o assim.")
    assert "posto_em_curso" not in esquecida, (
        "A conta do turno fechado ficou com a etiqueta do posto. O índice único "
        "conta-a como «a conta em curso deste PC» e o `abrir_venda` de amanhã "
        "apanha um DuplicateKeyError que a porta não sabe explicar."
    )

    nova = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))
    assert nova["estado"] == "aberta"


def test_a_recusa_do_posto_nomeia_a_saida_que_existe_num_fecho_a_MEIO(monkeypatch):
    """**O beco que a mensagem não sabia nomear, e é a quarta vez que ele muda
    de sítio.**

    A caixa-1 ficou em `a_fechar` — um fecho que morreu a meio, que é o caso
    para que `caixa._sessao_por_fechar` existe. A etiqueta do posto só é
    largada DEPOIS do Z estar escrito
    (`caixa._largar_o_posto_das_contas_abertas`), por isso ela ainda lá está; e
    `_contas_do_balcao` só varre sessões `aberta`, por isso a leitura diz «o
    balcão está livre» ao mesmo tempo que o índice recusa. O mesmo PC a atender
    na caixa-2 apanha o 409 mudo.

    Medido, as duas saídas que as mensagens nomeavam eram inexecutáveis: a
    porta dizia «turno JÁ FECHADO … peça ao gestor», e o gestor respondia 409
    («a caixa está a FECHAR o turno neste momento» —
    `caixa.arrumar_conta_esquecida`, e está certo que recuse: o Z está a somar
    a lista onde esta conta entra). A saída real — voltar a carregar em FECHAR
    CAIXA naquela caixa — não era nomeada por nenhuma das duas.

    Na janela normal de um fecho isto dura milissegundos. Num fecho que morra a
    meio é PERMANENTE, e é aí que a frase tem de servir para alguma coisa."""
    sessoes = [
        _sessao(id="sessao-1", caixa_id="caixa-1", estado="a_fechar"),
        _sessao(id="sessao-2", caixa_id="caixa-2"),
    ]
    db = _duas_caixas([], vendas=[_conta()], sessoes=sessoes)
    _liga(db, monkeypatch)

    assert _corre(venda_mod._contas_do_balcao(db, _LOJA, _PC)) == [], (
        "A reprodução deixou de reproduzir: a leitura do balcão passou a ver a "
        "conta da sessão em `a_fechar`, e o 409 mudo deixou de acontecer.")

    with pytest.raises(HTTPException) as e:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))
    recusa = e.value.detail
    assert e.value.status_code == 409
    assert "FECHAR CAIXA" in recusa, (
        "A recusa não nomeia o gesto que a desfaz. A operadora fica com um PC "
        "trancado e uma instrução que ninguém consegue executar.")
    assert "Balcão" in recusa, (
        "A recusa não diz QUAL caixa fechar — e este PC pode estar a atender "
        "noutra, como está aqui.")
    assert "gestor" not in recusa, (
        "Continua a mandar chamar o gestor, que é exactamente quem NÃO pode "
        "resolver esta: `arrumar_conta_esquecida` recusa com a sessão a fechar.")

    # E a saída nomeada executa-se mesmo, que é a única prova que conta.
    _corre(fechar_caixa(
        PedidoFecharCaixa(caixa_id="caixa-1", contado=50.0), operador=_op()))
    nova = _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))
    assert nova["estado"] == "aberta"


def test_o_gestor_continua_a_ser_a_saida_quando_o_turno_esta_mesmo_FECHADO(monkeypatch):
    """A outra metade, e a que a correcção não pode comer: com a sessão
    `fechada`, a conta é mesmo de um turno arrumado, ninguém no POS lhe chega,
    e quem a resolve é o gestor. A frase de sempre tem de continuar a sair."""
    sessoes = [
        _sessao(id="sessao-1", caixa_id="caixa-1", estado="fechada"),
        _sessao(id="sessao-2", caixa_id="caixa-2"),
    ]
    db = _duas_caixas([], vendas=[_conta()], sessoes=sessoes)
    _liga(db, monkeypatch)

    with pytest.raises(HTTPException) as e:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))
    assert e.value.detail == venda_mod._MSG_ETIQUETA_PRESA, (
        "A recusa do turno JÁ FECHADO mudou de frase: essa conta é do gestor, "
        "e mandar a operadora fechar uma caixa que já está fechada é o erro ao "
        "contrário.")


def test_a_conta_de_um_turno_fechado_nao_aparece_no_ecra_do_balcao(monkeypatch):
    """E não volta ao balcão: a pergunta do ecrã é sobre o cliente que está à
    frente, e uma conta de ontem é dinheiro do passado — é do gestor
    (`GET /caixa/contas-esquecidas`), como sempre foi."""
    sessoes = [
        _sessao(id="sessao-1", caixa_id="caixa-1", estado="fechada"),
        _sessao(id="sessao-2", caixa_id="caixa-2"),
    ]
    conta, grupos = _o_ecra_mostra(
        [_conta(posto_em_curso=None)], [], monkeypatch,
        caixa_id="caixa-2", sessoes=sessoes)
    assert conta is None and grupos == []
    assert _a_porta_recusa(
        [_conta(posto_em_curso=None)], [], monkeypatch,
        caixa_id="caixa-2", sessoes=sessoes) is None


# --- A caixa que o gestor desactiva --------------------------------------------


def test_a_caixa_da_conta_desactivada_nao_deixa_o_dinheiro_sem_caminho(monkeypatch):
    """A pergunta das duas pontas: e se o gestor desactivar a caixa onde a
    conta ficou?

    Com o âmbito do POSTO, a conta continua a chegar ao ecrã pela caixa que
    está aberta — a leitura dela não passa pela caixa da conta — e as três
    saídas continuam a executar-se. Com o âmbito da sessão da caixa do ecrã,
    era preciso voltar à caixa Balcão, cujo `GET /pos/caixa/estado` responde
    404: o beco ficava permanente e o dinheiro sem caminho."""
    db = _duas_caixas([], vendas=[_conta()])
    # O gestor desactiva a caixa Balcão. A sessão dela fica aberta — desactivar
    # uma caixa não fecha o turno.
    caixas = db[COLECOES["caixas"]]._documentos
    for c in caixas:
        if c["id"] == "caixa-1":
            c["ativa"] = False
    _liga(db, monkeypatch)

    conta = _corre(venda_aberta(caixa_id="caixa-2", operador=_op()))
    assert conta is not None and conta["id"] == "v-balcao", (
        "A conta ficou fora do alcance do único ecrã que a operadora consegue "
        "abrir — é dinheiro sem caminho nenhum.")

    # E continua a aceitar escritas: a sessão DELA é que decide, e essa está
    # aberta (`_garante_sessao_desta_venda_aberta`).
    depois = _corre(juntar_linha(
        "v-balcao", PedidoJuntarLinha(produto_id="prod-1", quantidade=1),
        operador=_op()))
    assert len(depois["linhas"]) == 2


# --- Uma função, não duas -------------------------------------------------------


def test_ha_UMA_funcao_e_o_ambito_dela_nao_e_um_parametro():
    """**O que impede a quarta divergência.** Enquanto o âmbito fosse um
    argumento, dois chamadores podiam passar argumentos diferentes — e foi
    exactamente isso que aconteceu três vezes (a porta passava as sessões da
    loja, o ecrã passava uma sessão).

    `_contas_do_balcao` recebe a LOJA e o DISPOSITIVO, os dois do token do
    operador, e mais nada: não há um `caixa_id` nem um `sessao_ids` que se
    possa passar diferente. Guardado pela assinatura, que é o sítio onde a
    diferença voltaria a entrar."""
    import inspect

    parametros = list(
        inspect.signature(venda_mod._contas_do_balcao).parameters)
    assert parametros == ["db", "loja_id", "dispositivo_id"], (
        "A assinatura de `_contas_do_balcao` mudou para %s. Se o âmbito voltou "
        "a ser um argumento (uma caixa, uma sessão, uma lista de sessões), a "
        "porta e o ecrã voltam a poder pedir conjuntos diferentes — que é a "
        "raiz que este ficheiro fecha." % parametros
    )


def test_as_tres_rotas_perguntam_pela_MESMA_funcao(monkeypatch):
    """E chamam-na mesmo — corrido, não afirmado. Substitui-se
    `_contas_do_balcao` por um espião e confirma-se que as três rotas passam
    por ele com os MESMOS argumentos."""
    db = _duas_caixas([], vendas=[_conta()])
    _liga(db, monkeypatch)

    chamadas = []
    original = venda_mod._contas_do_balcao

    async def espiao(db_, loja_id, dispositivo_id):
        chamadas.append((loja_id, dispositivo_id))
        return await original(db_, loja_id, dispositivo_id)

    monkeypatch.setattr(venda_mod, "_contas_do_balcao", espiao)

    _corre(venda_aberta(caixa_id="caixa-2", operador=_op()))
    _corre(contas_repartidas(caixa_id="caixa-2", operador=_op()))
    try:
        _corre(abrir_venda(PedidoNovaVenda(caixa_id="caixa-2"), operador=_op()))
    except HTTPException:
        pass

    assert chamadas == [(_LOJA, _PC)] * 3, (
        "As três rotas não fizeram a MESMA pergunta: %s" % chamadas)

# --- A GRELHA VIVA e a porta que recusa ----------------------------------------
#
# O menor que caía da mesma raiz: `razaoDaGrelhaMorta({venda: null, partes: []})`
# devolve `null`, logo a grelha fica VIVA e o painel convida ao toque — e isso
# está CERTO, desde que nesse estado a rota aceite mesmo. Enquanto a porta e o
# ecrã fossem dois conjuntos, não aceitava: com a conta presa noutra caixa, o
# ecrã respondia `null`/`[]`, a grelha acendia-se, e a recusa só aparecia
# depois do dedo, com o cliente à frente.
#
# Não se corrige na função — ela está certa. Corrige-se na raiz, e é aqui que
# se prende: para cada arranjo, corre-se o JavaScript do ecrã COM O QUE AS
# ROTAS DEVOLVERAM, e exige-se que uma grelha viva sem conta à frente
# corresponda a uma porta que aceita.

def _grelha_morta(venda, partes, tmp_path):
    """Corre `razaoDaGrelhaMorta` em Node, tal como está no `lib/pos.js` — a
    técnica (e os utilitários) do `test_arredondamento_do_ecra.py`."""
    lib = _ler(_LIB_POS)
    guiao = tmp_path / "grelha.js"
    guiao.write_text("\n".join([
        _corpo_da_seta(lib, "const centimosPos = (valor) =>", _LIB_POS),
        _corpo_da_funcao(
            lib, "export const numeroPos = (valor) =>", _LIB_POS
        ).replace("export ", "", 1),
        _corpo_da_seta(lib, "const eurosPos = (valor) =>", _LIB_POS),
        _corpo_da_seta(
            lib, "export const contaTravada = (venda) =>", _LIB_POS
        ).replace("export ", "", 1),
        _corpo_da_seta(
            lib, "export const MSG_CONTA_TRAVADA_CURTA =", _LIB_POS
        ).replace("export ", "", 1),
        _corpo_da_seta(
            lib, "export const partesAbertas = (partes) =>", _LIB_POS
        ).replace("export ", "", 1),
        _corpo_da_funcao(
            lib, "export const razaoDeNaoComecar = (porCobrar) =>", _LIB_POS
        ).replace("export ", "", 1),
        _corpo_da_funcao(
            lib, "export const razaoDaGrelhaMorta = ({ venda, partes, aSeparar }) =>", _LIB_POS
        ).replace("export ", "", 1),
        "const entrada = %s;" % json.dumps({"venda": venda, "partes": partes}),
        "process.stdout.write(JSON.stringify(razaoDaGrelhaMorta(entrada)));",
    ]), encoding="utf-8")
    resultado = subprocess.run(
        [_node(), str(guiao)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if resultado.returncode != 0:
        pytest.fail("O JavaScript do ecrã não correu:\n%s"
                    % resultado.stderr.decode("utf-8", "replace"))
    return json.loads(resultado.stdout.decode("utf-8"))


@pytest.mark.parametrize(
    "nome,vendas,refs,ha_conta", _ARRANJOS, ids=[a[0] for a in _ARRANJOS])
def test_a_grelha_so_convida_ao_toque_quando_a_rota_o_aceita(
    nome, vendas, refs, ha_conta, monkeypatch, tmp_path
):
    """**A cortesia e a garantia dizem o mesmo, arranjo a arranjo.**

    Se a grelha está viva e não há conta à frente, o toque seguinte chama
    `POST /pos/venda` — e essa chamada TEM de passar. Era aqui que o menor
    vivia: com a conta presa noutra caixa, o ecrã acendia os cartões e a rota
    respondia 409 depois do dedo."""
    recusa = _a_porta_recusa(vendas, refs, monkeypatch)
    conta, grupos = _o_ecra_mostra(vendas, refs, monkeypatch)
    partes = [p for g in grupos for p in g["partes"]]

    razao = _grelha_morta(conta, partes, tmp_path)

    if razao is None and conta is None:
        assert recusa is None, (
            "%s: a grelha está VIVA com o painel vazio — «Toque num produto à "
            "esquerda para começar a conta» — e a rota responde %d. A recusa "
            "aparece depois do dedo, com o cliente à frente."
            % (nome, recusa.status_code if recusa else 0)
        )
    if recusa is not None:
        assert razao is not None or conta is not None, (
            "%s: a rota recusa e o ecrã não tem nem conta à frente nem razão "
            "para a grelha estar morta — é o beco, tal e qual." % nome
        )
