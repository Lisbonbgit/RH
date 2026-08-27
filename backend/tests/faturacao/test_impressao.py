"""A FILA DE IMPRESSÃO — e sobretudo a garantia de não imprimir duas vezes.

Mesmo duplo de base de dados de `test_venda.py`, importado de lá e não
copiado: é ele que faz cumprir o índice ÚNICO (`unico=`) e que CEDE o event
loop em cada operação (`ceder=True`) — sem essas duas coisas, um teste de
corrida fica verde a medir o caminho sequencial, e o índice que decide a
corrida real pode estar apagado sem ninguém dar por isso. Nenhum teste liga a
uma base de dados nem à rede.

**A regra que este ficheiro mede, e que decide o desenho todo:**

> Um talão a mais é papel. Um talão a menos é um cliente sem documento.

Por isso os testes não são simétricos. O que se afirma no caminho da falha é
que o trabalho VOLTA à fila e sai OUTRA VEZ — não que ele não repete. A
repetição é a escolha, e está aqui guardada com todas as letras
(`test_o_programa_morre_depois_de_buscar_...`); quem um dia a inverter tem de
passar por cima de um teste que diz porquê.

**O tempo é um parâmetro, nunca o relógio.** Tudo o que decide por tempo
(o arrendamento a expirar, a validade a passar, o programa a deixar de
responder) troca `impressao._agora` por um instante escrito à mão. Um teste
que esperasse 60 segundos a sério não se corre, e um que dormisse 0,1 s a
fingir media outra coisa.
"""
import asyncio
import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from faturacao import escpos
from faturacao import impressao as imp
from faturacao.db import COLECOES
from faturacao.impressao import (
    CADUCADO,
    CAIXA,
    COZINHA,
    FALHADO,
    GAVETA,
    IMPRESSO,
    PENDENTE,
    RESERVADO,
    PedidoFalhou,
    PedidoRecibo,
    abrir_gaveta,
    enfileirar,
    enfileirar_venda_emitida,
    enfileirar_z,
    estado_da_impressao,
    imprimir_pedido,
    imprimir_segunda_via,
    marcar_falhou,
    marcar_impresso,
    marcar_falhados_vistos,
    pagina_de_teste,
    PedidoPaginaDeTeste,
    recolher,
)

from .test_venda import ColeccaoFalsa, DbFalsa, _corre


_T0 = datetime(2026, 8, 22, 19, 0, 0, tzinfo=timezone.utc)


def _relogio(monkeypatch, momento):
    """Põe `impressao._agora` a devolver este instante — e nada mais do
    módulo passa a saber que horas são."""
    monkeypatch.setattr(imp, "_agora", lambda: momento)


# A chave do índice ÚNICO de `db.py` sobre `fat_trabalhos_impressao`, escrita
# aqui como o Mongo a aplicaria. É a mesma condição e não uma paráfrase — o
# `test_indices.py` prende a declaração ao que este duplo faz cumprir.
def _chave_do_trabalho(doc):
    return doc.get("chave")


def _db(trabalhos=None, dispositivos=None, vendas=None, documentos=None,
        lojas=None, ceder=False):
    registo = []
    return DbFalsa({
        COLECOES["trabalhos_impressao"]: ColeccaoFalsa(
            registo, trabalhos, unico=_chave_do_trabalho, ceder=ceder),
        COLECOES["dispositivos"]: ColeccaoFalsa(registo, dispositivos, ceder=ceder),
        COLECOES["vendas"]: ColeccaoFalsa(registo, vendas, ceder=ceder),
        COLECOES["documentos"]: ColeccaoFalsa(registo, documentos, ceder=ceder),
        COLECOES["lojas"]: ColeccaoFalsa(registo, lojas, ceder=ceder),
    })


def _fila(db):
    return db[COLECOES["trabalhos_impressao"]]._documentos


def _dispositivo(**over):
    d = {"id": "pc-1", "loja_id": "loja-1", "estado": "activo", "nome": "PC Balcão"}
    d.update(over)
    return d


def _operador(**over):
    o = {"operador_id": "op-1", "nome": "Rafaela", "loja_id": "loja-1",
         "dispositivo_id": "pc-1"}
    o.update(over)
    return o


def _venda(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "dispositivo_id": "pc-1",
        "estado": "emitida",
        "linhas": [{
            "produto_nome": "Açaí Regular", "quantidade": 1,
            "respostas_texto": [{"grupo_id": "g-nome", "texto": "Rafaela"}],
            "opcoes": [
                {"id": "o1", "grupo_id": "g1", "nome": "Levar", "preco": 0,
                 "sai_na_fatura": False},
                {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
            ],
        }],
    }
    v.update(over)
    return v


# O talão CERTIFICADO tal como o Vendus o devolve — bytes ESC/POS que este
# sistema nunca escreveu e nunca deve reescrever.
_TALAO_DO_VENDUS = b"\x1b@FS 2026/123\nATCUD:XPTO-123\n\x1dV\x00"


def _documento(**over):
    d = {"id": "doc-1", "loja_id": "loja-1", "venda_id": "venda-1",
         "numero": "FS 2026/123", "talao_escpos": _TALAO_DO_VENDUS}
    d.update(over)
    return d


def _por_na_fila(db, monkeypatch, momento=_T0, **kwargs):
    _relogio(monkeypatch, momento)
    argumentos = {"loja_id": "loja-1", "impressora": CAIXA, "tipo": imp.TALAO,
                  "dados": b"papel", "chave": "k-1"}
    argumentos.update(kwargs)
    return _corre(enfileirar(db, **argumentos))


# --- 1. Pôr na fila -----------------------------------------------------------


def test_o_trabalho_entra_pendente_com_os_bytes_e_a_validade(monkeypatch):
    db = _db()
    trabalho_id = _por_na_fila(db, monkeypatch, dados=b"ola", impressora=COZINHA)
    assert trabalho_id
    (trabalho,) = _fila(db)
    assert trabalho["estado"] == PENDENTE
    assert trabalho["impressora"] == COZINHA
    assert base64.b64decode(trabalho["bytes_b64"]) == b"ola"
    assert trabalho["tentativas"] == 0
    assert trabalho["validade_ate"] == (_T0 + timedelta(minutes=30)).isoformat()


def test_as_tentativas_nascem_a_ZERO_e_nunca_ausentes(monkeypatch):
    """A entrega compara-as na condição da escrita (`recolher`), e no Mongo um
    campo AUSENTE não casa com uma igualdade a 0 — sem isto o trabalho ficava
    por entregar para sempre, e em silêncio."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    assert _fila(db)[0]["tentativas"] == 0


def test_a_MESMA_chave_nao_entra_duas_vezes_na_fila(monkeypatch):
    """A idempotência da CRIAÇÃO. A emissão é idempotente por desenho — uma
    segunda tentativa da mesma venda encontra o documento já gravado e
    devolve-o tal e qual —, e sem o índice único de `chave` essa segunda
    passagem enfileirava um segundo talão do mesmo cliente."""
    db = _db()
    primeiro = _por_na_fila(db, monkeypatch, chave="talao:doc-1")
    segundo = _por_na_fila(db, monkeypatch, chave="talao:doc-1")
    assert primeiro is not None
    assert segundo is None
    assert len(_fila(db)) == 1


def test_uma_chave_NOVA_entra_de_propósito(monkeypatch):
    """A segunda via, a gaveta e o pedido pedido à mão trazem um uuid: ali,
    dois toques no botão são duas coisas."""
    db = _db()
    _por_na_fila(db, monkeypatch, chave="gaveta:a")
    _por_na_fila(db, monkeypatch, chave="gaveta:b")
    assert len(_fila(db)) == 2


def test_um_trabalho_SEM_bytes_nao_entra(monkeypatch):
    """Papel em branco a sair, e a operadora a pensar que o sistema imprimiu."""
    db = _db()
    assert _por_na_fila(db, monkeypatch, dados=b"") is None
    assert _fila(db) == []


def test_uma_impressora_que_nao_existe_nao_entra(monkeypatch):
    db = _db()
    assert _por_na_fila(db, monkeypatch, impressora="etiquetas") is None
    assert _fila(db) == []


def test_o_MONGO_EM_BAIXO_nao_rebenta_para_fora(monkeypatch):
    """**A regra que sustenta tudo: o papel, nunca o registo.**

    Um `enfileirar` que levantasse dentro do `finalizar` transformava uma
    emissão bem sucedida — com Fatura Simplificada REAL já entregue à
    Autoridade Tributária — num erro no ecrã. E o ecrã lê um erro com a venda
    aparentemente por emitir como "não saiu nada, pode repetir"."""
    class Explode:
        async def insert_one(self, doc):
            raise RuntimeError("Atlas em baixo")

    db = DbFalsa({COLECOES["trabalhos_impressao"]: Explode()})
    _relogio(monkeypatch, _T0)
    assert _corre(enfileirar(
        db, loja_id="loja-1", impressora=CAIXA, tipo=imp.TALAO,
        dados=b"papel", chave="k")) is None


# --- 2. O que a emissão enfileira ---------------------------------------------


def test_uma_venda_emitida_faz_sair_UM_papel_so_e_e_o_do_CLIENTE(monkeypatch):
    """Emitir a fatura é dar o papel ao CLIENTE, e mais nada.

    «Não tem nada a ver com fatura. O staff é o único que faz a impressão do
    pedido» — o dono. A ficha da cozinha sai pelo botão «Imprimir Pedido»
    (`imprimir_pedido`), e sai quando o staff quiser: antes de haver fatura,
    com a conta ainda aberta, e as vezes que forem precisas."""
    db = _db()
    _relogio(monkeypatch, _T0)
    _corre(enfileirar_venda_emitida(db, _venda(), _documento()))
    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == CAIXA
    assert trabalho["tipo"] == imp.TALAO


def test_uma_conta_dividida_por_TRES_nao_manda_TRES_fichas_a_cozinha(monkeypatch):
    """Cada parte é uma venda que finaliza — e é por isso que a ficha não
    podia continuar agarrada à emissão: três partes eram três fichas do MESMO
    copo, e a cozinha fazia três açaís para uma pessoa (ou, no melhor caso,
    deitava dois papéis fora e deixava de confiar no que sai)."""
    db = _db()
    _relogio(monkeypatch, _T0)
    for parte in ("a", "b", "c"):
        _corre(enfileirar_venda_emitida(
            db,
            _venda(id="venda-1%s" % parte, conta_mae_id="venda-1"),
            _documento(id="doc-1%s" % parte),
        ))
    assert [t["impressora"] for t in _fila(db)] == [CAIXA, CAIXA, CAIXA]


def test_o_talao_do_cliente_vai_TAL_E_QUAL_veio_do_vendus(monkeypatch):
    """Bytes ESC/POS **certificados**. Não se lhes acrescenta um comando à
    frente nem um corte atrás: quem mexe num talão certificado assume a
    responsabilidade do que sai, e este sistema não a quer."""
    db = _db()
    _relogio(monkeypatch, _T0)
    _corre(enfileirar_venda_emitida(db, _venda(), _documento()))
    talao = [t for t in _fila(db) if t["impressora"] == CAIXA][0]
    assert base64.b64decode(talao["bytes_b64"]) == _TALAO_DO_VENDUS


def test_a_MESMA_emissao_a_passar_duas_vezes_nao_faz_dois_taloes(monkeypatch):
    """O retry do POS, a retoma de uma reserva incerta, a reconciliação de uma
    reserva presa — os três chegam ao mesmo documento e passam por aqui."""
    db = _db()
    _relogio(monkeypatch, _T0)
    _corre(enfileirar_venda_emitida(db, _venda(), _documento()))
    _corre(enfileirar_venda_emitida(db, _venda(), _documento()))
    assert len(_fila(db)) == 1


def test_uma_fatura_SEM_talao_guardado_nao_enfileira_papel_em_branco(monkeypatch):
    """Emitida antes de o talão passar a ser guardado, ou com o `output` do
    Vendus ilegível. O documento fiscal está bom; o que não há é papel."""
    db = _db()
    _relogio(monkeypatch, _T0)
    _corre(enfileirar_venda_emitida(db, _venda(), _documento(talao_escpos=b"")))
    assert _fila(db) == []


def test_o_Z_enfileira_uma_vez_so_por_fecho(monkeypatch):
    """Uma retoma de um fecho que morreu a meio não faz sair um segundo Z."""
    db = _db()
    _relogio(monkeypatch, _T0)
    z = {"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
         "fundo": 50.0, "esperado": 58.99, "contado": 58.99, "diferenca": 0.0}
    _corre(enfileirar_z(db, z))
    _corre(enfileirar_z(db, z))
    assert len(_fila(db)) == 1
    assert _fila(db)[0]["impressora"] == CAIXA


# --- 3. A entrega -------------------------------------------------------------


def _recolher(db, monkeypatch, momento=_T0, dispositivo=None):
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    return _corre(recolher(dispositivo=dispositivo or _dispositivo()))


def test_a_entrega_e_pela_ordem_de_CHEGADA(monkeypatch):
    """A operadora que fez três contas seguidas vê os três pedidos sair pela
    ordem em que os fez, que é a ordem por que a cozinha os vai fazer."""
    db = _db()
    for i, instante in enumerate([_T0 + timedelta(seconds=s) for s in (30, 10, 20)]):
        _por_na_fila(db, monkeypatch, momento=instante, chave="k%d" % i,
                     dados=("papel-%d" % i).encode())
    entregues = _recolher(db, monkeypatch, _T0 + timedelta(minutes=1))["trabalhos"]
    assert [base64.b64decode(t["bytes_b64"]) for t in entregues] == [
        b"papel-1", b"papel-2", b"papel-0",
    ]


def test_a_entrega_marca_o_trabalho_RESERVADO_e_conta_a_tentativa(monkeypatch):
    db = _db()
    _por_na_fila(db, monkeypatch)
    entregues = _recolher(db, monkeypatch)["trabalhos"]
    assert len(entregues) == 1
    trabalho = _fila(db)[0]
    assert trabalho["estado"] == RESERVADO
    assert trabalho["tentativas"] == 1
    assert trabalho["recibo"] == entregues[0]["recibo"]
    assert trabalho["reservado_por"] == "pc-1"


def test_o_que_ja_esta_entregue_nao_se_entrega_outra_vez(monkeypatch):
    db = _db()
    _por_na_fila(db, monkeypatch)
    assert len(_recolher(db, monkeypatch)["trabalhos"]) == 1
    assert _recolher(db, monkeypatch, _T0 + timedelta(seconds=5))["trabalhos"] == []


def test_a_entrega_tem_TECTO(monkeypatch):
    """Uma fila acumulada não devolve uma resposta de megabytes ao PC da loja
    de uma assentada."""
    db = _db()
    for i in range(imp._QUANTOS_DE_CADA_VEZ + 3):
        _por_na_fila(db, monkeypatch, momento=_T0 + timedelta(seconds=i),
                     chave="k%d" % i)
    entregues = _recolher(db, monkeypatch, _T0 + timedelta(minutes=1))["trabalhos"]
    assert len(entregues) == imp._QUANTOS_DE_CADA_VEZ
    # O tecto medido em números escritos à mão, e não contra a própria
    # constante: posta a 1, o PC da loja passa a precisar de uma volta inteira
    # por talão; posta aos milhares, uma fila acumulada devolve megabytes de
    # ESC/POS de uma assentada — e nenhuma das duas era apanhada por aqui.
    assert 2 <= imp._QUANTOS_DE_CADA_VEZ <= 20


def test_cada_loja_so_leva_o_seu_papel(monkeypatch):
    db = _db()
    _por_na_fila(db, monkeypatch, chave="k1", loja_id="loja-1", dados=b"da-1")
    _por_na_fila(db, monkeypatch, chave="k2", loja_id="loja-2", dados=b"da-2")
    entregues = _recolher(db, monkeypatch)["trabalhos"]
    assert [base64.b64decode(t["bytes_b64"]) for t in entregues] == [b"da-1"]


def test_DOIS_programas_ao_mesmo_tempo_nao_levam_o_MESMO_talao(monkeypatch):
    """**A corrida, decidida onde tem de ser.**

    Um PC de reserva ligado por engano, ou o mesmo programa a perguntar duas
    vezes porque a primeira resposta se perdeu. O que impede os dois de
    imprimirem o mesmo papel é a escrita CONDICIONADA ao que se leu — e é o
    `matched_count` que decide, nunca a leitura de cima.

    O duplo CEDE o event loop em cada operação (`ceder=True`), que é o que faz
    esta corrida ser uma corrida: sem isso, as duas recolhas corriam uma
    depois da outra até ao fim e o teste ficava verde a medir o caminho
    sequencial."""
    db = _db(ceder=True)
    _por_na_fila(db, monkeypatch, dados=b"o-unico")
    _relogio(monkeypatch, _T0 + timedelta(seconds=1))
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    async def duas():
        return await asyncio.gather(
            recolher(dispositivo=_dispositivo(id="pc-1")),
            recolher(dispositivo=_dispositivo(id="pc-2")),
        )

    primeira, segunda = _corre(duas())
    entregues = primeira["trabalhos"] + segunda["trabalhos"]
    assert len(entregues) == 1, (
        "O mesmo talão foi entregue a dois programas — os dois vão imprimi-lo."
    )
    assert _fila(db)[0]["tentativas"] == 1


def test_a_recolha_deixa_a_MARCA_de_que_esta_loja_tem_programa(monkeypatch):
    """E é uma marca PRÓPRIA (`ultima_recolha_em`), não a `ultima_atividade_em`
    que qualquer browser do POS também actualiza: confundi-las fazia o ecrã
    dizer que havia programa numa loja onde só há o Chrome aberto."""
    db = _db(dispositivos=[_dispositivo()])
    _por_na_fila(db, monkeypatch)
    _recolher(db, monkeypatch, _T0 + timedelta(seconds=5))
    (dispositivo,) = db[COLECOES["dispositivos"]]._documentos
    assert dispositivo["ultima_recolha_em"] == (_T0 + timedelta(seconds=5)).isoformat()
    assert "ultima_atividade_em" not in dispositivo


# --- 4. A confirmação ---------------------------------------------------------


def _confirmar(db, monkeypatch, trabalho_id, recibo, dispositivo=None):
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    return _corre(marcar_impresso(
        trabalho_id, PedidoRecibo(recibo=recibo),
        dispositivo=dispositivo or _dispositivo()))


def test_o_papel_saiu_e_o_trabalho_fica_IMPRESSO(monkeypatch):
    db = _db()
    _por_na_fila(db, monkeypatch)
    (entregue,) = _recolher(db, monkeypatch)["trabalhos"]
    _relogio(monkeypatch, _T0 + timedelta(seconds=3))
    _confirmar(db, monkeypatch, entregue["id"], entregue["recibo"])
    assert _fila(db)[0]["estado"] == IMPRESSO


def test_uma_confirmacao_com_o_recibo_ERRADO_nao_marca_nada(monkeypatch):
    """Quem confirma tem de ser quem recebeu."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    (entregue,) = _recolher(db, monkeypatch)["trabalhos"]
    with pytest.raises(HTTPException) as erro:
        _confirmar(db, monkeypatch, entregue["id"], "recibo-inventado")
    assert erro.value.status_code == 409
    assert _fila(db)[0]["estado"] == RESERVADO


def test_uma_confirmacao_ATRASADA_de_um_trabalho_ja_devolvido_a_fila_e_recusada(
    monkeypatch,
):
    """O programa buscou, ficou preso, o arrendamento expirou, o trabalho
    voltou à fila e foi entregue a outro. A confirmação do primeiro chega
    agora — e dar por impresso um trabalho que outro programa tem nas mãos
    era exactamente o caminho para o cliente ficar sem papel."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    (primeira,) = _recolher(db, monkeypatch)["trabalhos"]
    depois = _T0 + timedelta(seconds=imp._ARRENDAMENTO_SEGUNDOS + 1)
    (segunda,) = _recolher(db, monkeypatch, depois)["trabalhos"]
    assert segunda["recibo"] != primeira["recibo"]
    with pytest.raises(HTTPException) as erro:
        _confirmar(db, monkeypatch, primeira["id"], primeira["recibo"])
    assert erro.value.status_code == 409
    assert _fila(db)[0]["estado"] == RESERVADO
    assert _fila(db)[0]["recibo"] == segunda["recibo"]


def test_um_trabalho_de_OUTRA_loja_nao_se_confirma(monkeypatch):
    db = _db()
    _por_na_fila(db, monkeypatch)
    (entregue,) = _recolher(db, monkeypatch)["trabalhos"]
    with pytest.raises(HTTPException) as erro:
        _confirmar(db, monkeypatch, entregue["id"], entregue["recibo"],
                   dispositivo=_dispositivo(id="pc-9", loja_id="loja-2"))
    assert erro.value.status_code == 404


# --- 5. A recuperação: duas vezes em vez de nenhuma ---------------------------


def test_o_programa_morre_depois_de_buscar_e_o_talao_SAI_OUTRA_VEZ(monkeypatch):
    """**A decisão central deste módulo, guardada com todas as letras.**

    O programa vai buscar o trabalho e cala-se: o PC reiniciou, a rede caiu, o
    Windows foi actualizar-se. Não há forma de saber se o papel saiu — a
    impressora não faz parte da transacção.

    Passado o arrendamento, o trabalho **volta à fila e é entregue de novo**.
    Se ele tinha mesmo imprimido, sai um segundo talão: papel a mais. A
    alternativa era dá-lo por impresso e arriscar o cliente sem documento — a
    obrigação legal por cumprir e o QR da fidelização que ele não lê.

    Quem inverter isto está a passar por cima deste teste, e é para isso que
    ele existe."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    (primeira,) = _recolher(db, monkeypatch)["trabalhos"]
    assert _fila(db)[0]["estado"] == RESERVADO

    depois = _T0 + timedelta(seconds=imp._ARRENDAMENTO_SEGUNDOS + 1)
    entregues = _recolher(db, monkeypatch, depois)["trabalhos"]
    assert len(entregues) == 1, "O talão ficou preso: o cliente não leva papel."
    assert entregues[0]["id"] == primeira["id"]
    assert _fila(db)[0]["tentativas"] == 2


def test_dentro_do_arrendamento_o_trabalho_NAO_volta_a_ser_entregue(monkeypatch):
    """A outra metade: enquanto o programa ainda pode estar a imprimir, ninguém
    lho tira. Sem isto, uma volta da fila de 2 em 2 segundos entregava o mesmo
    talão trinta vezes por minuto.

    **Os segundos à mão, pela mesma razão do `_AGENTE_VIVO_SEGUNDOS`:** um
    teste feito com `imp._ARRENDAMENTO_SEGUNDOS - 1` nunca pode falhar pelo
    valor da constante, e posta a 1 segundo ficava toda a suite verde com a
    fila a entregar o mesmo talão de 3 em 3 segundos ao programa que já o está
    a imprimir — o "duas vezes" a deixar de ser a excepção e a passar a ser o
    normal."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    _recolher(db, monkeypatch)
    for segundos in (3, 30):
        assert _recolher(db, monkeypatch, _T0 + timedelta(seconds=segundos))["trabalhos"] == [], (
            "Ao fim de %d segundos o talão foi entregue a um SEGUNDO programa "
            "— o primeiro ainda o pode estar a imprimir." % segundos)


def _queixar_se(db, monkeypatch, entregue, momento):
    """O programa da loja diz que não conseguiu imprimir. É o caminho a sério
    da impressora sem papel — e o que faz o limite de tentativas contar em
    segundos e não em minutos: o trabalho volta à fila NO INSTANTE."""
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    return _corre(marcar_falhou(
        entregue["id"],
        PedidoFalhou(recibo=entregue["recibo"], erro="Sem papel"),
        dispositivo=_dispositivo()))


def test_mas_NAO_infinitamente(monkeypatch):
    """Uma impressora avariada com um trabalho a repetir-se para sempre não
    produz papel nenhum: produz uma fila que cresce toda a noite e vomita
    duzentos talões na manhã seguinte, quando alguém a arranjar.

    O limite não tira ao cliente a hipótese de ter o papel — o talão fica
    guardado com a fatura e reimprime-se num toque. O que tira é a repetição
    cega.

    **A validade ilegível é o que põe este limite à prova**, e não é um truque
    de teste: o tecto normal de um trabalho é a VALIDADE (30 minutos), e com
    ela o limite de tentativas nunca chega a ser preciso pelo arrendamento. Um
    trabalho cuja data não se percebe — gravado por uma versão antiga, ou
    estragado — não caduca nunca (é a escolha do módulo: papel a mais, não a
    menos), e aí este limite é a última rede que existe."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    _fila(db)[0]["validade_ate"] = "não é uma data"
    momento = _T0
    for _ in range(imp._MAX_TENTATIVAS):
        assert len(_recolher(db, monkeypatch, momento)["trabalhos"]) == 1
        momento = momento + timedelta(seconds=imp._ARRENDAMENTO_SEGUNDOS + 1)
    assert _recolher(db, monkeypatch, momento)["trabalhos"] == []
    trabalho = _fila(db)[0]
    assert trabalho["estado"] == FALHADO
    assert str(imp._MAX_TENTATIVAS) in trabalho["erro"]


def test_e_o_que_desistiu_e_VISIVEL(monkeypatch):
    """Uma fila que desiste em silêncio é pior do que uma fila que insiste."""
    db = _db(dispositivos=[_dispositivo()], trabalhos=[])
    _por_na_fila(db, monkeypatch)
    momento = _T0
    for _ in range(imp._MAX_TENTATIVAS):
        (entregue,) = _recolher(db, monkeypatch, momento)["trabalhos"]
        _queixar_se(db, monkeypatch, entregue, momento)
        momento = momento + timedelta(seconds=3)
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    estado = _corre(estado_da_impressao(operador=_operador()))
    assert estado["falhados"] == 1


def test_o_programa_diz_que_FALHOU_e_o_trabalho_volta_a_fila_JA(monkeypatch):
    """**Isto não é prova de que não saiu papel**, e não se finge que é: uma
    falha no `EndDocPrinter` acontece com os bytes já entregues ao spooler.
    Por isso volta à fila — a escolha de sempre — e conta como tentativa.

    O que isto dá em relação a deixar o arrendamento expirar é o INSTANTE:
    numa impressora a que alguém acabou de pôr papel, é a diferença entre o
    talão sair já e o cliente esperar mais um minuto."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    (entregue,) = _recolher(db, monkeypatch)["trabalhos"]
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _relogio(monkeypatch, _T0 + timedelta(seconds=2))
    _corre(marcar_falhou(
        entregue["id"], PedidoFalhou(recibo=entregue["recibo"], erro="Sem papel"),
        dispositivo=_dispositivo()))
    assert _fila(db)[0]["estado"] == PENDENTE
    assert _fila(db)[0]["erro"] == "Sem papel"
    assert len(_recolher(db, monkeypatch, _T0 + timedelta(seconds=3))["trabalhos"]) == 1


def test_falhar_a_ULTIMA_tentativa_desiste(monkeypatch):
    db = _db()
    _por_na_fila(db, monkeypatch)
    momento = _T0
    for _ in range(imp._MAX_TENTATIVAS - 1):
        (entregue,) = _recolher(db, monkeypatch, momento)["trabalhos"]
        _queixar_se(db, monkeypatch, entregue, momento)
        momento = momento + timedelta(seconds=3)
    (entregue,) = _recolher(db, monkeypatch, momento)["trabalhos"]
    _queixar_se(db, monkeypatch, entregue, momento)
    assert _fila(db)[0]["estado"] == FALHADO


def test_uma_QUEIXA_atrasada_de_um_trabalho_ja_entregue_a_OUTRO_e_recusada(
    monkeypatch,
):
    """A irmã do `test_uma_confirmacao_ATRASADA_...`, pela MESMA linha e pela
    mesma razão — e a única das três rotas que estava sem guarda.

    O programa recebeu o talão, a impressora encravou, a queixa ficou presa na
    rede. O arrendamento expirou, o trabalho foi entregue **outra vez** e está
    a ser impresso neste instante — e é agora que a queixa velha chega.

    Sem o `recibo` na condição da escrita ela é ACEITE: atira para pendente um
    trabalho que outro programa tem nas mãos, a confirmação do dono actual
    leva 409, e o **mesmo talão sai duas vezes**. Na gaveta, é a gaveta do
    dinheiro a abrir duas vezes, com o cliente à frente dela."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    (primeira,) = _recolher(db, monkeypatch)["trabalhos"]
    depois = _T0 + timedelta(seconds=90)
    (segunda,) = _recolher(db, monkeypatch, depois)["trabalhos"]
    assert segunda["recibo"] != primeira["recibo"]

    with pytest.raises(HTTPException) as erro:
        _queixar_se(db, monkeypatch, primeira, depois)
    assert erro.value.status_code == 409

    assert _fila(db)[0]["estado"] == RESERVADO, (
        "A queixa velha atirou de volta à fila um trabalho que OUTRO programa "
        "tem nas mãos — o mesmo talão vai sair duas vezes.")
    assert _fila(db)[0]["recibo"] == segunda["recibo"]

    # E a prova de que quem o tem nas mãos continua a poder fechá-lo: sem o
    # `recibo` na condição, era esta confirmação que levava 409.
    _confirmar(db, monkeypatch, segunda["id"], segunda["recibo"])
    assert _fila(db)[0]["estado"] == IMPRESSO


# --- 6. O que ficou de ontem --------------------------------------------------


def test_os_taloes_de_ONTEM_nao_saem_de_manha(monkeypatch):
    """Uma loja que abre de manhã não quer vinte talões de ontem à noite a
    sair — e a operadora que os visse sair não voltava a confiar na
    impressora."""
    db = _db()
    _por_na_fila(db, monkeypatch, momento=_T0)
    amanha = _T0 + timedelta(hours=14)
    assert _recolher(db, monkeypatch, amanha)["trabalhos"] == []
    assert _fila(db)[0]["estado"] == CADUCADO


def test_um_papel_encravado_que_alguem_desencrava_ainda_sai(monkeypatch):
    """Vinte minutos é papel encravado a ser desencravado, não é ontem."""
    db = _db()
    _por_na_fila(db, monkeypatch, momento=_T0)
    daqui_a_pouco = _T0 + timedelta(minutes=20)
    assert len(_recolher(db, monkeypatch, daqui_a_pouco)["trabalhos"]) == 1


def test_a_GAVETA_caduca_em_dois_minutos_e_o_talao_nao(monkeypatch):
    """**Aqui a validade não é cortesia, é segurança.** Um impulso de abertura
    que chegasse dez minutos atrasado abria a gaveta do dinheiro com ninguém à
    frente dela."""
    db = _db()
    _por_na_fila(db, monkeypatch, chave="g", tipo=GAVETA, dados=escpos.abrir_gaveta())
    _por_na_fila(db, monkeypatch, chave="t", tipo=imp.TALAO, dados=b"papel")
    daqui_a_cinco = _T0 + timedelta(minutes=5)
    entregues = _recolher(db, monkeypatch, daqui_a_cinco)["trabalhos"]
    assert [t["tipo"] for t in entregues] == [imp.TALAO]
    estados = {t["tipo"]: t["estado"] for t in _fila(db)}
    assert estados[GAVETA] == CADUCADO


def test_um_trabalho_com_a_validade_ILEGIVEL_nao_se_deita_fora(monkeypatch):
    """Gravado por uma versão que não escrevia o campo, ou com a data
    estragada. É papel que alguém está à espera, e deitá-lo fora por não se
    perceber a data era escolher o estrago que este módulo recusa."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    _fila(db)[0]["validade_ate"] = "não é uma data"
    assert len(_recolher(db, monkeypatch, _T0 + timedelta(days=3))["trabalhos"]) == 1


# --- 7. O ecrã: há programa a ouvir? -----------------------------------------


def _estado(db, monkeypatch, momento=_T0):
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    return _corre(estado_da_impressao(operador=_operador()))


def test_uma_loja_onde_NINGUEM_instalou_o_programa_diz_que_nao_ha(monkeypatch):
    """**A pergunta mais importante deste ficheiro do lado do balcão.** Sem
    ela, o «Imprimir» ficava bonito, o trabalho entrava na fila, caducava
    trinta minutos depois e ninguém sabia de nada — a operadora dava o cliente
    por servido e o papel nunca existiu."""
    db = _db(dispositivos=[_dispositivo()])
    assert _estado(db, monkeypatch)["ha_programa"] is False


def test_com_o_programa_a_perguntar_o_ecra_sabe_que_ha(monkeypatch):
    db = _db(dispositivos=[_dispositivo()])
    _recolher(db, monkeypatch, _T0)
    estado = _estado(db, monkeypatch, _T0 + timedelta(seconds=10))
    assert estado["ha_programa"] is True
    assert estado["ultima_recolha_em"] == _T0.isoformat()


def test_um_programa_que_se_CALOU_deixa_de_contar(monkeypatch):
    """O PC desligou-se, o serviço morreu, alguém fechou o programa. Um botão
    que continuasse a parecer bom era a mesma mentira, com mais um passo.

    **Os dois números estão escritos à mão, e é de propósito** — o mesmo que
    já se fez ao `_MAX_TENTATIVAS` e ao `nucleo.FALHAS_ATE_AVISAR`. Este teste
    era `imp._AGENTE_VIVO_SEGUNDOS + 1`, e por isso NUNCA podia falhar pelo
    valor da constante: posta a 99999, ficava verde — e o POS dizia «há
    programa de impressão a responder nesta loja» vinte e sete horas depois de
    o PC estar desligado, que é ao certo a mentira que a docstring desta rota
    diz existir para impedir. Posta a 5, um soluço de rede apagava os botões
    de impressão a meio de uma venda."""
    db = _db(dispositivos=[_dispositivo()])
    _recolher(db, monkeypatch, _T0)
    assert _estado(db, monkeypatch, _T0 + timedelta(seconds=60))["ha_programa"] is True, (
        "Um minuto sem perguntar é um pico de rede, não um PC desligado — e um "
        "botão que se apaga sozinho a meio de uma venda não se volta a usar.")
    assert _estado(db, monkeypatch, _T0 + timedelta(minutes=5))["ha_programa"] is False, (
        "Cinco minutos calado é o programa morto. Um botão que continue a "
        "parecer bom deixa a operadora a dar o cliente por servido sem papel.")


def test_o_que_esta_por_sair_conta_se_e_o_que_ja_caducou_nao(monkeypatch):
    """Mostrar como "à espera" um trabalho que já passou a validade era
    prometer um papel que não vai sair."""
    db = _db(dispositivos=[_dispositivo()])
    _por_na_fila(db, monkeypatch, momento=_T0, chave="velho")
    _por_na_fila(db, monkeypatch, momento=_T0 + timedelta(minutes=59), chave="novo")
    estado = _estado(db, monkeypatch, _T0 + timedelta(minutes=60))
    assert estado["por_sair"] == 1


# --- 8. Os botões do POS ------------------------------------------------------


def test_a_gaveta_enfileira_o_impulso_e_nao_papel(monkeypatch):
    """A gaveta abre PELA IMPRESSORA, e um `documento("")` para a abrir gastava
    8 cm de papel de cada vez que a operadora precisasse de trocos."""
    db = _db()
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    resposta = _corre(abrir_gaveta(operador=_operador()))
    assert resposta["aceite"] is True
    (trabalho,) = _fila(db)
    assert trabalho["tipo"] == GAVETA
    assert trabalho["impressora"] == CAIXA
    assert base64.b64decode(trabalho["bytes_b64"]) == escpos.abrir_gaveta()


def test_dois_toques_na_gaveta_sao_dois_pedidos(monkeypatch):
    db = _db()
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _corre(abrir_gaveta(operador=_operador()))
    _corre(abrir_gaveta(operador=_operador()))
    assert len(_fila(db)) == 2


def test_o_imprimir_pedido_manda_a_ficha_para_a_COZINHA(monkeypatch):
    """E leva o texto de `talao.pedido_da_cozinha`, e não uma segunda escrita
    dele: o nome em maiúsculas, o serviço, as doses à frente do topping."""
    from faturacao.talao import pedido_da_cozinha

    venda = _venda(estado="aberta")
    db = _db(vendas=[venda])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _corre(imprimir_pedido("venda-1", operador=_operador()))
    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == COZINHA
    saiu = base64.b64decode(trabalho["bytes_b64"])
    assert saiu == escpos.documento(pedido_da_cozinha(venda))
    assert "RAFAELA".encode("cp858") in saiu


def test_o_imprimir_pedido_numa_conta_VAZIA_nao_poe_PAPEL_EM_BRANCO_na_fila(monkeypatch):
    """**A guarda do `enfileirar` não apanha este, e é por isso que existe
    outra.**

    «Um trabalho sem bytes não é um trabalho» não chega aqui: o CABEÇALHO tem
    bytes. Medido — uma venda com `linhas: []` devolvia `aceite=True` e punha
    na fila 96 bytes com «PEDIDO COZINHA / #AZIA 10:05 / ====» e mais nada. É
    a mesma frase que o módulo já escreveu para o talão vazio: era papel em
    branco a sair e a operadora a pensar que o sistema imprimiu.

    E basta tocar no botão antes de picar o primeiro copo — o ecrã só o
    desligava por não haver programa a ouvir."""
    db = _db(vendas=[_venda(estado="aberta", linhas=[])])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as excinfo:
        _corre(imprimir_pedido("venda-1", operador=_operador()))
    assert excinfo.value.status_code == 422
    assert _fila(db) == []


def test_uma_quantidade_IMPOSSIVEL_ja_gravada_nao_rebenta_o_botao(monkeypatch):
    """**A ficha inteira desaparecia por causa de uma linha.**

    `imprimir_pedido` não tem `try` nenhum: um `nan` gravado na quantidade
    (que a API aceitava — ver `test_venda`) levantava `ValueError` dentro do
    `talao._quantidade`, dava 500 no ecrã, e aquela conta nunca mais mandava
    ficha à cozinha. A entrada está fechada, mas as linhas que já entraram
    continuam gravadas.

    O papel sai, com `?` na quantidade que não se sabe e o resto do pedido
    todo lá dentro."""
    venda = _venda(estado="aberta")
    venda["linhas"] = [
        dict(venda["linhas"][0], quantidade=float("nan")),
        {"produto_nome": "Café Expresso", "quantidade": 2},
    ]
    db = _db(vendas=[venda])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    assert _corre(imprimir_pedido("venda-1", operador=_operador()))["aceite"]
    saiu = base64.b64decode(_fila(db)[0]["bytes_b64"]).decode("cp858")
    assert "? x Açaí Regular" in saiu
    assert "2 x Café Expresso" in saiu


def test_a_ficha_sai_com_a_conta_ABERTA_e_sem_documento_nenhum(monkeypatch):
    """**É como um balcão trabalha:** pica-se, manda-se para a cozinha,
    cobra-se no fim. O cliente ainda está a decidir o resto do pedido e o
    copo já está a ser feito.

    Este caminho não pode exigir fatura, nem documento, nem estado nenhum: a
    fila não sabe de dinheiro, e a única coisa que este botão produz é papel.
    A base de dados aqui não tem UM documento — se a rota fosse buscar
    algum, este teste apanhava-o."""
    db = _db(vendas=[_venda(estado="aberta")], documentos=[])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    resposta = _corre(imprimir_pedido("venda-1", operador=_operador()))
    assert resposta["aceite"] is True
    (trabalho,) = _fila(db)
    assert trabalho["impressora"] == COZINHA
    assert trabalho["tipo"] == imp.PEDIDO


def test_a_ficha_da_cozinha_sai_as_VEZES_QUE_FOREM_PRECISAS(monkeypatch):
    """O dono confirmou-o: no balcão o papel encrava e a cozinha perde a
    ficha. O botão fica sempre disponível e não se desliga depois da
    primeira — três toques são três fichas, e cada uma entra na fila com
    chave própria (é o `uuid` de `imprimir_pedido`, e é de propósito)."""
    db = _db(vendas=[_venda(estado="aberta")])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    for _ in range(3):
        assert _corre(imprimir_pedido("venda-1", operador=_operador()))["aceite"]
    assert [t["impressora"] for t in _fila(db)] == [COZINHA, COZINHA, COZINHA]


def test_nao_se_imprime_o_pedido_de_uma_conta_de_OUTRA_loja(monkeypatch):
    db = _db(vendas=[_venda(loja_id="loja-2")])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(imprimir_pedido("venda-1", operador=_operador()))
    assert erro.value.status_code == 404
    assert _fila(db) == []


def test_a_segunda_via_e_o_MESMO_papel_e_nao_volta_ao_vendus(monkeypatch):
    """Byte a byte o talão certificado que ficou guardado com a fatura — o
    mesmo ATCUD e o mesmo QR. Ir outra vez ao Vendus era uma chamada de rede
    por reimpressão, e uma reimpressão que falhava com a internet da loja em
    baixo, quando o papel já estava cá dentro."""
    db = _db(documentos=[_documento()])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _corre(imprimir_segunda_via("doc-1", operador=_operador()))
    (trabalho,) = _fila(db)
    assert base64.b64decode(trabalho["bytes_b64"]) == _TALAO_DO_VENDUS
    assert trabalho["impressora"] == CAIXA


def test_uma_fatura_antiga_SEM_talao_diz_porque_nao_ha_papel(monkeypatch):
    db = _db(documentos=[_documento(talao_escpos=None)])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(imprimir_segunda_via("doc-1", operador=_operador()))
    assert erro.value.status_code == 422
    assert "documento fiscal está bom" in erro.value.detail
    assert _fila(db) == []


def test_nao_se_reimprime_a_fatura_de_OUTRA_loja(monkeypatch):
    db = _db(documentos=[_documento(loja_id="loja-2")])
    _relogio(monkeypatch, _T0)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    with pytest.raises(HTTPException) as erro:
        _corre(imprimir_segunda_via("doc-1", operador=_operador()))
    assert erro.value.status_code == 404


# --- 9. A PÁGINA DE TESTE -----------------------------------------------------
#
# **É o único teste que existe para a metade Windows deste sistema.** Num Mac
# não há forma de provar que os bytes entram na impressora; esta página é a
# prova, e sai do servidor para não haver duas cópias do ESC/POS.


def _pagina(db, monkeypatch, impressora=CAIXA, dispositivo=None):
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    return _corre(pagina_de_teste(
        PedidoPaginaDeTeste(impressora=impressora),
        dispositivo=dispositivo or _dispositivo(),
    ))


def test_a_pagina_de_teste_NAO_passa_pela_fila(monkeypatch):
    """O que esta página tem de provar é o ÚLTIMO salto — que estes bytes
    entram naquela impressora em cru. Se saísse da fila e não aparecesse
    papel, ficavam três suspeitos em vez de um."""
    db = _db(lojas=[{"id": "loja-1", "nome": "Colombo"}])
    resposta = _pagina(db, monkeypatch)
    assert _fila(db) == []
    assert base64.b64decode(resposta["bytes_b64"])


def test_a_pagina_de_teste_e_a_MESMA_que_o_escpos_constroi(monkeypatch):
    """Byte a byte. Uma cópia dentro do `.exe` fazia com que afinar a tabela
    de caracteres corrigisse os talões e não a página que os devia
    diagnosticar."""
    db = _db(lojas=[{"id": "loja-1", "nome": "Colombo"}])
    resposta = _pagina(db, monkeypatch)
    assert base64.b64decode(resposta["bytes_b64"]) == escpos.pagina_de_teste(
        CAIXA, loja="Colombo")


def test_a_pagina_diz_QUAL_das_duas_impressoras_e(monkeypatch):
    """É a diferença entre «não imprimiu» e «imprimiu na impressora da
    cozinha»."""
    db = _db(lojas=[{"id": "loja-1", "nome": "Colombo"}])
    saiu = base64.b64decode(_pagina(db, monkeypatch, COZINHA)["bytes_b64"])
    assert b"cozinha" in saiu
    assert b"caixa" not in saiu


def test_uma_impressora_inventada_cai_na_CAIXA_em_vez_de_rebentar(monkeypatch):
    """Este botão é o que uma pessoa carrega quando NADA está a funcionar. Um
    500 aqui tirava-lhe a única ferramenta de diagnóstico que tem."""
    db = _db(lojas=[{"id": "loja-1", "nome": "Colombo"}])
    saiu = base64.b64decode(_pagina(db, monkeypatch, "gaveta")["bytes_b64"])
    assert saiu == escpos.pagina_de_teste(CAIXA, loja="Colombo")


def test_sem_loja_gravada_a_pagina_sai_na_mesma(monkeypatch):
    """Uma loja apagada não pode tirar a página de diagnóstico ao PC — sai com
    o id em vez do nome, que ainda diz a quem está à frente onde ela aponta."""
    db = _db(lojas=[])
    saiu = base64.b64decode(_pagina(db, monkeypatch)["bytes_b64"])
    assert b"loja-1" in saiu


# --- 6b. E o que ficou de ontem RESERVADO ------------------------------------
#
# O caminho que faltava, e é o da vida real: o PC da loja desliga-se com o
# trabalho JÁ ENTREGUE. O trabalho fica RESERVADO; ninguém o confirma; o
# arrendamento expira. Os guardas do bloco 6 acima só percorrem trabalhos
# PENDENTES — e um trabalho que volta de RESERVADO a PENDENTE era entregue na
# MESMA chamada, sem se voltar a olhar para a validade.


def test_os_taloes_de_ontem_RESERVADOS_tambem_nao_saem_de_manha(monkeypatch):
    """O PC foi abaixo com o talão nas mãos. De manhã ele não pode sair na
    mesma: são os mesmos vinte talões da noite, com o mesmo estrago — só que
    por outro caminho."""
    db = _db()
    _por_na_fila(db, monkeypatch, momento=_T0)
    (entregue,) = _recolher(db, monkeypatch)["trabalhos"]
    assert _fila(db)[0]["estado"] == RESERVADO, "o PC recebeu-o e desligou-se"

    amanha = _T0 + timedelta(hours=14)
    assert _recolher(db, monkeypatch, amanha)["trabalhos"] == [], (
        "O talão de ontem à noite saiu de manhã: voltou de RESERVADO a "
        "PENDENTE e foi entregue na mesma chamada, sem ninguém olhar para a "
        "validade.")
    assert _fila(db)[0]["estado"] == CADUCADO
    assert entregue  # o id que saiu na primeira entrega


def test_a_GAVETA_reservada_tambem_caduca_aos_dois_minutos(monkeypatch):
    """**Aqui a validade não é cortesia, é segurança.** Uma gaveta entregue a
    um PC que se desligou não pode voltar a ser entregue cinco minutos depois:
    é a gaveta do dinheiro a abrir sem ninguém à frente dela.

    Este teste percorre os minutos um a um porque é assim que o defeito se
    vê. Ao minuto 2 a entrega ainda é legítima — é o INSTANTE da validade, e a
    comparação é `validade < agora`, a mesma do caminho PENDENTE. Os minutos 3
    e 4 é que eram a gaveta a abrir sozinha, e eram entregues."""
    db = _db()
    _por_na_fila(db, monkeypatch, chave="g", tipo=GAVETA, dados=escpos.abrir_gaveta())

    entregas = []
    for minuto in range(5):
        momento = _T0 + timedelta(minutes=minuto)
        if _recolher(db, monkeypatch, momento)["trabalhos"]:
            entregas.append(minuto)

    assert entregas == [0, 1, 2], (
        "A gaveta foi entregue nos minutos %s — a validade são 2 minutos e "
        "depois disso já não há ninguém à frente dela." % entregas)
    assert _fila(db)[0]["estado"] == CADUCADO


class _CursorEngasgado:
    """Leu num instante; entrega o que leu só quando o portão abrir.

    É o servidor a engasgar-se ENTRE o ler e o escrever — o intervalo em que
    as escritas condicionais deste módulo ganham ou perdem, e que o duplo, a
    ceder de operação em operação, nunca produz sozinho: as duas voltas andam
    em passo certo e nunca se cruzam nos pontos que interessam."""

    def __init__(self, cursor, chegou, portao):
        self._cursor = cursor
        self._chegou = chegou
        self._portao = portao

    def sort(self, *args, **kwargs):
        self._cursor.sort(*args, **kwargs)
        return self

    async def to_list(self, n=None):
        itens = await self._cursor.to_list(n)
        self._chegou.set()
        await self._portao.wait()
        return itens


def _engasgar_a_leitura(monkeypatch, db, filtro_do_estado):
    """A PRIMEIRA leitura da fila cujo filtro procure este `estado` fica presa
    até o portão abrir. Devolve `(chegou, portao)`: o `chegou` é o que torna
    isto determinista — o teste espera por ele em vez de contar `sleep(0)`, e
    sem essa espera a ordem das duas voltas depende de quantos `await` cada
    uma tem pelo caminho (e um deles trancava a outra para sempre)."""
    coleccao = db[COLECOES["trabalhos_impressao"]]
    find_original = coleccao.find
    chegou, portao = asyncio.Event(), asyncio.Event()
    usado = []

    def find_engasgado(filtro=None, projecao=None):
        cursor = find_original(filtro, projecao)
        if not usado and (filtro or {}).get("estado") == filtro_do_estado:
            usado.append(True)
            return _CursorEngasgado(cursor, chegou, portao)
        return cursor

    monkeypatch.setattr(coleccao, "find", find_engasgado)
    return chegou, portao


def test_uma_arrumacao_LENTA_nao_devolve_a_fila_um_talao_ja_entregue(monkeypatch):
    """O `recibo` na condição de `_arrumar_a_fila`, e é isto que ele guarda.

    Uma volta da fila LÊ a fila e ESCREVE a seguir. Entre as duas coisas o
    servidor pode engasgar-se — e nesse intervalo o outro programa arrumou o
    mesmo trabalho, levou-o, e está a imprimi-lo. A escrita atrasada chega com
    uma fotografia velha: sem o `recibo` na condição, o estado `RESERVADO`
    ainda casa (só que é a reserva DE OUTRO), o trabalho volta à fila e sai
    segunda vez enquanto o primeiro papel ainda está a sair.

    O engasgo é encenado à mão (o `portao`) porque é a única forma de o
    provar: com o duplo a ceder o event loop de operação em operação, as duas
    voltas andam em passo certo e nunca se cruzam neste ponto — e uma corrida
    que nunca acontece deixa a linha por defender. Tirada a comparação do
    `recibo`, este teste fica vermelho e mais nenhum."""
    db = _db(ceder=True)
    _por_na_fila(db, monkeypatch)
    (primeira,) = _recolher(db, monkeypatch)["trabalhos"]

    _relogio(monkeypatch, _T0 + timedelta(seconds=imp._ARRENDAMENTO_SEGUNDOS + 1))
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    chegou, portao = _engasgar_a_leitura(
        monkeypatch, db, {"$in": [PENDENTE, RESERVADO]})

    async def cenario():
        lenta = asyncio.ensure_future(recolher(dispositivo=_dispositivo(id="pc-1")))
        await chegou.wait()  # leu a fila (o trabalho é do primeiro recibo)
        outra = await recolher(dispositivo=_dispositivo(id="pc-2"))
        portao.set()
        return outra, await lenta

    depressa, atrasada = _corre(cenario())
    saidos = len(depressa["trabalhos"]) + len(atrasada["trabalhos"])
    assert saidos == 1, (
        "O mesmo talão foi entregue %d vezes: a arrumação atrasada devolveu à "
        "fila um trabalho que já era de outro programa." % saidos)
    assert _fila(db)[0]["estado"] == RESERVADO
    assert _fila(db)[0]["recibo"] != primeira["recibo"]


def test_uma_ENTREGA_atrasada_nao_apaga_a_contagem_das_tentativas(monkeypatch):
    """As `tentativas` na condição da entrega, e é isto que elas guardam.

    A entrega lê os candidatos e escreve a seguir. Se se engasgar no meio, o
    trabalho pode ter sido entregue a OUTRO programa e ter voltado à fila
    entretanto — e a escrita atrasada chega com a contagem velha. Sem as
    `tentativas` na condição, ela casa na mesma: a contagem volta atrás e o
    trabalho é entregue outra vez.

    Uma contagem que se perde é o limite de tentativas a deixar de existir, e
    o limite é o que impede a impressora avariada de acumular a noite inteira
    e vomitar tudo de manhã."""
    db = _db(ceder=True)
    _por_na_fila(db, monkeypatch)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _relogio(monkeypatch, _T0)

    chegou, portao = _engasgar_a_leitura(monkeypatch, db, PENDENTE)

    async def cenario():
        lenta = asyncio.ensure_future(recolher(dispositivo=_dispositivo(id="pc-1")))
        await chegou.wait()  # leu os candidatos: PENDENTE, tentativas=0

        # Entretanto o outro programa leva-o, e o arrendamento expira.
        depressa = await recolher(dispositivo=_dispositivo(id="pc-2"))
        await imp._arrumar_a_fila(
            db, "loja-1", _T0 + timedelta(seconds=imp._ARRENDAMENTO_SEGUNDOS + 1))

        portao.set()
        return depressa, await lenta

    depressa, atrasada = _corre(cenario())
    assert len(depressa["trabalhos"]) == 1
    assert atrasada["trabalhos"] == [], (
        "A entrega atrasada levou um trabalho que já não era o que ela leu.")
    trabalho = _fila(db)[0]
    assert trabalho["estado"] == PENDENTE
    assert trabalho["tentativas"] == 1, (
        "A contagem das tentativas voltou atrás (%s) — o limite deixa de "
        "existir e a fila repete para sempre." % trabalho["tentativas"])


def test_insiste_CINCO_MINUTOS_com_a_impressora_sem_papel(monkeypatch):
    """O número do limite, medido em TEMPO — que é a unidade da promessa.

    Os testes do limite acima percorrem `range(imp._MAX_TENTATIVAS)`: usam a
    própria constante, e por isso nenhum deles pode falhar pelo VALOR dela.
    Este mede o que a documentação prometeu à loja — «cinco minutos para pôr
    papel» — encenando exactamente o que acontece: o programa diz que falhou,
    o trabalho volta à fila NO INSTANTE, e ele volta a perguntar 3 segundos
    depois. Com cinco tentativas isto dava QUINZE SEGUNDOS."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    monkeypatch.setattr(imp, "obter_db", lambda: db)

    momento = _T0
    entregas = 0
    while entregas < 500:
        trabalhos = _recolher(db, monkeypatch, momento)["trabalhos"]
        if not trabalhos:
            break
        entregas += 1
        (entregue,) = trabalhos
        _relogio(monkeypatch, momento)
        monkeypatch.setattr(imp, "obter_db", lambda: db)
        _corre(marcar_falhou(
            entregue["id"],
            PedidoFalhou(recibo=entregue["recibo"], erro="Sem papel"),
            dispositivo=_dispositivo()))
        momento = momento + timedelta(seconds=3)

    insistiu = (momento - _T0).total_seconds()
    assert 280 <= insistiu <= 320, (
        "A fila insistiu %d segundos com a impressora sem papel — a promessa "
        "à loja são cinco minutos (300 s)." % insistiu)
    assert _fila(db)[0]["estado"] == FALHADO


# --- 10. O aviso que se pode desligar ----------------------------------------


def _falhar_ate_desistir(db, monkeypatch):
    """Deixa UM trabalho em `falhado`, pelo caminho da impressora sem papel."""
    _por_na_fila(db, monkeypatch, chave="k-%d" % len(_fila(db)))
    momento = _T0
    for _ in range(imp._MAX_TENTATIVAS):
        entregues = _recolher(db, monkeypatch, momento)["trabalhos"]
        if not entregues:
            break
        _queixar_se(db, monkeypatch, entregues[0], momento)
        momento = momento + timedelta(seconds=3)
    return momento


def test_o_aviso_dos_papeis_que_nao_sairam_DESLIGA_SE(monkeypatch):
    """Sem isto, o aviso ficava no ecrã do balcão SETE DIAS — até o TTL do
    Mongo apagar o trabalho — e não havia nada em lado nenhum que o tirasse de
    lá. A operadora reimprimia o papel, resolvia o assunto, e continuava a ver
    a mesma frase a semana inteira. Um aviso que não se desliga é um aviso que
    se aprende a ignorar."""
    db = _db(dispositivos=[_dispositivo()])
    momento = _falhar_ate_desistir(db, monkeypatch)
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    assert _corre(estado_da_impressao(operador=_operador()))["falhados"] == 1

    assert _corre(marcar_falhados_vistos(operador=_operador()))["vistos"] == 1
    assert _corre(estado_da_impressao(operador=_operador()))["falhados"] == 0


def test_dar_por_visto_NAO_apaga_nem_resolve_nada(monkeypatch):
    """O papel continua por sair e continua a reimprimir-se pelo separador
    Faturação: o que se desligou foi o aviso, não o problema."""
    db = _db(dispositivos=[_dispositivo()])
    momento = _falhar_ate_desistir(db, monkeypatch)
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _corre(marcar_falhados_vistos(operador=_operador()))

    trabalho = _fila(db)[0]
    assert trabalho["estado"] == FALHADO
    assert trabalho["erro"] == "Sem papel"
    assert trabalho["bytes_b64"]


def test_um_papel_que_falhe_DEPOIS_volta_a_avisar(monkeypatch):
    """Dar por visto é sobre os papéis que se viram, não sobre os que hão-de
    vir — senão o primeiro toque calava a impressora para sempre."""
    db = _db(dispositivos=[_dispositivo()])
    momento = _falhar_ate_desistir(db, monkeypatch)
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    _corre(marcar_falhados_vistos(operador=_operador()))
    assert _corre(estado_da_impressao(operador=_operador()))["falhados"] == 0

    _falhar_ate_desistir(db, monkeypatch)
    _relogio(monkeypatch, momento)
    monkeypatch.setattr(imp, "obter_db", lambda: db)
    assert _corre(estado_da_impressao(operador=_operador()))["falhados"] == 1


# --- 11. Uma data mal gravada não pára a loja de imprimir ---------------------
#
# O `_quando` promete que um instante que não se perceba conta como AUSENTE e
# nunca como "agora". Uma data SEM FUSO percebe-se — `fromisoformat` aceita-a
# de bom grado — e é aí que a promessa se parte: ela atravessa o guarda e vai
# comparar-se três linhas à frente com um instante que tem fuso,
# `TypeError: can't compare offset-naive and offset-aware datetimes`.
#
# **É o pior estrago deste módulo.** Uma linha má na colecção e a rota que faz
# sair o papel responde 500 a TODAS as perguntas seguintes: a loja inteira
# deixa de imprimir, e o ecrã que devia explicar porquê rebenta também. Hoje
# não é alcançável (tudo o que se grava passa por `_iso(_agora())`) — mas o
# guarda existe precisamente para um valor gravado mau não fazer mal.


def test_uma_data_SEM_FUSO_conta_como_ausente_como_a_docstring_promete():
    """Os cinco chamadores passam todos por aqui: é uma linha só."""
    assert imp._quando("2026-08-22T19:00:00") is None
    # E o que TEM fuso continua a ler-se, senão o guarda apagava tudo.
    assert imp._quando(_T0.isoformat()) == _T0


def test_uma_VALIDADE_sem_fuso_nao_derruba_a_recolha(monkeypatch):
    """`validade_ate` mau: sem isto, a loja inteira deixa de imprimir."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    _fila(db)[0]["validade_ate"] = "2026-08-22T19:30:00"
    # Ilegível não caduca — o mesmo que já valia para "não é uma data".
    assert len(_recolher(db, monkeypatch)["trabalhos"]) == 1


def test_um_ARRENDAMENTO_sem_fuso_nao_derruba_a_recolha(monkeypatch):
    """`reservado_em` mau, pelo caminho RESERVADO do `_arrumar_a_fila`."""
    db = _db()
    _por_na_fila(db, monkeypatch)
    _recolher(db, monkeypatch)
    _fila(db)[0]["reservado_em"] = "2026-08-22T19:00:00"
    # Sem instante legível o arrendamento conta como ACABADO: volta à fila e
    # sai. Papel a mais em vez de um trabalho preso para sempre.
    assert len(_recolher(db, monkeypatch, _T0 + timedelta(seconds=1))["trabalhos"]) == 1


def test_uma_RECOLHA_sem_fuso_nao_derruba_o_ECRA(monkeypatch):
    """`ultima_recolha_em` mau: é o ecrã que devia explicar a avaria a
    rebentar por cima dela."""
    db = _db(dispositivos=[_dispositivo(ultima_recolha_em="2026-08-22T19:00:00")])
    assert _estado(db, monkeypatch)["ha_programa"] is False
