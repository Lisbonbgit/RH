"""**O voucher L'Açaí ao balcão** — o lado do POS.

A recompensa deixa de valer só num pedido feito e pago na app: passa a valer
também na caixa, lida pelo MESMO QR que já dá pontos. A app decide o desconto
(é uma regra de dinheiro e vive num sítio só), o POS aplica-o na linha e emite.

O que este ficheiro prende, por ordem de gravidade:

1. **Nada disto pode impedir uma fatura de sair** — app em baixo, tecto de
   espera esgotado ou resposta estranha = venda normal, sem desconto e sem a
   conta mudar um cêntimo;
2. **falhar fechado e em voz alta** — um produto sem `vendus_ref` é *sem
   desconto*, nunca um desconto errado, e grita no registo;
3. **a ponte entre os dois catálogos**, vista do lado do POS: o PRODUTO e não a
   categoria (as do POS são dois baldes de contabilidade, e a subcategoria
   «Açaís» tem o açaí E o Smoothie);
4. **a marca na linha** (`voucher_id`) e o desconto no `desconto_eur` da linha
   que a app escolheu — nunca noutra;
5. **o travão da conta a zero**: 0,00 € emite-se COM linha de voucher e
   continua a ser recusado sem ela.

Nenhum teste fala com a app a sério: o transporte do httpx é um
`MockTransport`, e sem `APP_LACAI_URL` no ambiente nem sequer há endereço.
"""
import json
import logging
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException

from faturacao import db as db_mod
from faturacao import fiscal as fiscal_mod
from faturacao import pontos_app
from faturacao.db import COLECOES
from faturacao.fiscal import PagamentoEntrada, PedidoFinalizarVenda, finalizar
from tests.faturacao.test_fiscal import (
    ClienteEmissaoVendusFalso,
    ColeccaoFalsa,
    DbFalsa,
    _configura_vendus_env,
    _corre,
    _linha,
    _operador,
    _tipo_pagamento,
    _unicos_de,
    _venda,
)
from tests.faturacao.test_os_pontos_da_app import (
    AGORA,
    _credito,
    _db_da_fila,
    app,  # noqa: F401 — fixture
)


# --- O cenário ------------------------------------------------------------------

# Os ids do Vendus MEDIDOS no catálogo do POS (2026-10-01), e é o do PRODUTO: o
# `vendus_ref` de cada produto desta casa guarda o `id` do artigo no Vendus, e a
# app guarda a lista desses ids na categoria dela (`categories.produtos_pos`).
#
# **Os dois juntos são o cenário que a ponte por CATEGORIA não sabia separar.**
# Ao balcão existe UM produto que é açaí (preço base 0,00 € — o tamanho e os
# toppings são personalizações); o Smoothie de 7,90 € vive na MESMA subcategoria
# «Açaís», e a subcategoria nem id do Vendus tem (é NOSSA). Ligar por aí dava um
# Smoothie de graça a quem tivesse um voucher de Açaí Small de 7,20 €.
_REF_ACAI = "145268982"
_REF_SMOOTHIE = "188237858"


def _db_do_voucher(vendas=None, produtos=None, sessoes=None, refs=None):
    if vendas is None:
        vendas = [_venda(linhas=[_linha()])]
    if produtos is None:
        produtos = [{"id": "prod-1", "nome": "Açaí", "vendus_ref": _REF_ACAI},
                    {"id": "prod-2", "nome": "Smoothie", "vendus_ref": _REF_SMOOTHIE}]
    if sessoes is None:
        sessoes = [{"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
                    "estado": "aberta"}]
    # As `categorias` não entram: desde que a ponte é o produto, este caminho não
    # as lê — é uma ida à base de dados a menos por venda, com a funcionária à
    # espera dentro dos 4 s.
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(vendas),
        COLECOES["produtos"]: ColeccaoFalsa(produtos),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(sessoes),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(
            refs, indices_unicos=_unicos_de("fat_refs_fiscais")),
    })


def _pedir(monkeypatch, db, venda_id="venda-1", ligacao_id="lig-1"):
    monkeypatch.setattr(pontos_app, "obter_db", lambda: db)
    return _corre(pontos_app.voucher_ao_balcao(
        venda_id, pontos_app.PedidoVoucher(ligacao_id=ligacao_id), operador=_operador()))


def _linhas_gravadas(db, venda_id="venda-1"):
    return _corre(db[COLECOES["vendas"]].find_one({"id": venda_id}))["linhas"]


# --- A ponte entre os dois catálogos, vista daqui --------------------------------


def test_cada_linha_viaja_com_o_vendus_ref_do_PRODUTO_o_preco_e_a_quantidade(
        monkeypatch, app):
    """O contrato do corpo, campo a campo, com os ids REAIS do catálogo.

    **A ponte é o produto e não a categoria**, e não é gosto: as categorias do
    POS são dois baldes de contabilidade («Venda ao Público», «Vendas
    Aplicações») e são elas que têm o id do Vendus; a família do produto vive na
    SUBcategoria, que não tem id nenhum. E a subcategoria ainda é grossa demais —
    **«Açaís» tem o açaí E o Smoothie**, e é isto que este teste prende: os dois
    viajam com ids DIFERENTES, e a app desconta só no primeiro.

    O `linha_id` vai porque duas linhas podem ser do mesmo produto e é uma delas
    que leva o desconto; o preço unitário é o da fatura (`_linha_vendus`), já
    com as personalizações somadas."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2,
                       "titulo": "Açaí Small grátis", "linha_id_alvo": "linha-1"})
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1", quantidade=2, opcoes=[{"nome": "Nutella", "preco": 1.0}]),
        _linha(id="linha-2", produto_id="prod-2", produto_nome="Smoothie",
               produto_preco=7.9),
    ])])
    _pedir(monkeypatch, db)

    pedido = app.pedidos[0]
    assert str(pedido.url) == "http://olacai-api:8001/api/pos-integracao/voucher"
    assert pedido.headers["X-Service-Key"] == "chave-de-teste"
    # O MESMO tecto de espera do `ler`: é a funcionária com o cliente à frente.
    assert pedido.extensions["timeout"]["read"] == 4.0
    assert app.corpo() == {
        "ligacao_id": "lig-1",
        "linhas": [
            {"linha_id": "linha-1", "produto_vendus_ref": _REF_ACAI,
             "unit_price": 9.99, "qty": 2},
            {"linha_id": "linha-2", "produto_vendus_ref": _REF_SMOOTHIE,
             "unit_price": 7.9, "qty": 1},
        ],
    }
    # E o desconto cai no AÇAÍ, nunca no Smoothie: a elegibilidade é da app
    # (mesma categoria lá E `unit_price >= valor`) e a linha também.
    linhas = _linhas_gravadas(db)
    assert (linhas[0]["desconto_eur"], linhas[0]["voucher_id"]) == (7.2, "vch-1")
    assert (linhas[1].get("desconto_eur"), linhas[1].get("voucher_id")) == (None, None)


def test_um_produto_SEM_vendus_ref_viaja_a_None_e_GRITA_no_registo(
        monkeypatch, app, caplog):
    """**Falha fechada e em voz alta, e sem partir a lista inteira.** Os 33
    produtos do catálogo têm o `vendus_ref` preenchido (medido), mas um criado à
    mão no backoffice não tem. Não se adivinha a correspondência — quem decide é
    a app — mas o sintoma de um `vendus_ref` por preencher é um voucher que não se
    aplica, e um voucher que não se aplica sem ninguém perceber porquê é o pior
    desfecho de todos.

    O `motivo` é a palavra da APP (o POS só a devolve ao cartão da caixa), e o
    açaí da linha ao lado viaja intacto: uma linha sem ponte não cala a conta."""
    app.responde(200, {"motivo": "categoria_sem_correspondencia"})
    db = _db_do_voucher(
        produtos=[{"id": "prod-1", "nome": "Açaí", "vendus_ref": _REF_ACAI},
                  {"id": "prod-2", "nome": "Água", "vendus_ref": None}],
        vendas=[_venda(linhas=[
            _linha(id="linha-1", produto_id="prod-2", produto_nome="Água 0,5L"),
            _linha(id="linha-2"),
        ])])
    with caplog.at_level(logging.ERROR):
        resposta = _pedir(monkeypatch, db)

    linhas = app.corpo()["linhas"]
    assert [li["produto_vendus_ref"] for li in linhas] == [None, _REF_ACAI]
    assert "Água 0,5L" in caplog.text and "vendus_ref" in caplog.text
    # E o motivo volta ao cartão da caixa, para a funcionária poder dizer ao
    # cliente porque é que o desconto não entrou.
    assert resposta["motivo"] == "categoria_sem_correspondencia"
    assert resposta["voucher_id"] is None


def test_um_produto_que_o_catalogo_NAO_conhece_viaja_a_None(monkeypatch, app):
    """A linha é de um produto que já não existe no catálogo (apagado depois de
    entrar na conta). Mesmo desfecho: `None`, e a app é que decide."""
    app.responde(200, {})
    db = _db_do_voucher(produtos=[{"id": "prod-que-foi-apagado",
                                   "vendus_ref": _REF_ACAI}])
    _pedir(monkeypatch, db)
    assert app.corpo()["linhas"][0]["produto_vendus_ref"] is None


# --- A marca na linha e o desconto ----------------------------------------------


def test_o_desconto_entra_no_desconto_eur_da_linha_ESCOLHIDA_e_marca_lha(monkeypatch, app):
    """O coração da Tarefa B: `desconto_eur` na linha alvo (daí para a frente é
    máquina que já existe — `_itens_vendus` converte-o na percentagem que
    reproduz o líquido ao cêntimo) e `voucher_id` a marcá-la.

    **Sem a marca, depois de emitida ninguém distingue** um desconto de voucher
    de um que a funcionária deu de cabeça: o talão não pode dizer «Oferta
    L'Açaí», os relatórios não sabem quanto custou a fidelidade ao balcão, e o
    travão da conta a zero não tem como saber que aquele 0,00 € é uma oferta."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2,
                       "titulo": "Açaí Médio grátis", "linha_id_alvo": "linha-2"})
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1"), _linha(id="linha-2")])])

    resposta = _pedir(monkeypatch, db)

    assert (resposta["voucher_id"], resposta["valor"], resposta["titulo"],
            resposta["linha_id_alvo"]) == ("vch-1", 7.2, "Açaí Médio grátis", "linha-2")
    linhas = _linhas_gravadas(db)
    assert (linhas[0].get("desconto_eur"), linhas[0].get("voucher_id")) == (None, None)
    assert (linhas[1]["desconto_eur"], linhas[1]["voucher_id"]) == (7.2, "vch-1")
    # E o total volta com a conta, senão o ecrã cobrava o de antes.
    assert resposta["venda"]["totais"]["total"] == round(8.99 + 8.99 - 7.2, 2)


def test_a_segunda_chamada_limpa_a_marca_antiga_antes_de_por_a_nova(monkeypatch, app):
    """A rota corre DUAS vezes — ao ler o QR e ao EMITIR — e a conta pode ter
    mudado pelo meio. O que a app responde AGORA é o que vale: se ela libertou o
    voucher e escolheu outro, a marca antiga não pode ficar para trás com o
    desconto agarrado."""
    app.responde(200, {"voucher_id": "vch-2", "valor": 5.0, "linha_id_alvo": "linha-2"})
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1", desconto_eur=7.2, voucher_id="vch-1"),
        _linha(id="linha-2"),
    ])])

    _pedir(monkeypatch, db)

    linhas = _linhas_gravadas(db)
    assert (linhas[0]["voucher_id"], linhas[0]["desconto_eur"]) == (None, None)
    assert (linhas[1]["voucher_id"], linhas[1]["desconto_eur"]) == ("vch-2", 5.0)


def test_sem_voucher_a_app_tira_a_marca_que_ja_la_estava(monkeypatch, app):
    """As linhas mudaram e o voucher deixou de servir: a app liberta-o e
    responde que não há nada. Deixar o desconto cá era oferecer um produto com
    um voucher que já ninguém vai consumir."""
    app.responde(200, {})
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1", desconto_eur=7.2, voucher_id="vch-1")])])

    resposta = _pedir(monkeypatch, db)

    assert resposta["voucher_id"] is None
    linhas = _linhas_gravadas(db)
    assert (linhas[0]["voucher_id"], linhas[0]["desconto_eur"]) == (None, None)


def test_sem_voucher_e_sem_marca_nenhuma_NAO_se_escreve_na_conta(monkeypatch, app):
    """O caso normal, a esmagadora maioria das contas. Escrever à mesma
    incrementava o `linhas_versao` e disputava a conta com o ecrã por nada (ver
    `venda._aplicar_as_linhas`)."""
    app.responde(200, {})
    db = _db_do_voucher()
    _pedir(monkeypatch, db)
    assert _corre(db[COLECOES["vendas"]].find_one({"id": "venda-1"})).get(
        "linhas_versao") is None


def test_a_linha_escolhida_desapareceu_da_conta_e_a_venda_segue_sem_desconto(
        monkeypatch, app, caplog):
    """A app escolheu uma linha que já não existe (removida entre a leitura e a
    escrita). Sem desconto, e a dizê-lo — nunca um desconto posto noutra linha
    qualquer."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2, "linha_id_alvo": "linha-fantasma"})
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1", desconto_eur=7.2, voucher_id="vch-velho")])])

    with caplog.at_level(logging.ERROR):
        resposta = _pedir(monkeypatch, db)

    assert (resposta["voucher_id"], resposta["motivo"]) == (None, "linha_desapareceu")
    assert "linha-fantasma" in caplog.text
    assert all(not li.get("voucher_id") for li in _linhas_gravadas(db))


def test_um_voucher_SEM_linha_alvo_ou_SEM_valor_e_contrato_partido(monkeypatch, app, caplog):
    """A regra de sempre: sem desconto, e a gritar — nunca um desconto errado."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 0, "linha_id_alvo": "linha-1"})
    db = _db_do_voucher()
    with caplog.at_level(logging.ERROR):
        resposta = _pedir(monkeypatch, db)
    assert (resposta["voucher_id"], resposta["motivo"]) == (None, "contrato_partido")
    assert all(not li.get("voucher_id") for li in _linhas_gravadas(db))


# --- A regra de ouro: nada disto pode impedir uma fatura de sair -----------------


@pytest.mark.parametrize(
    "preparar",
    [
        lambda a: a.rebenta(httpx.ConnectError("ligação recusada")),
        lambda a: a.rebenta(httpx.ReadTimeout("passou dos 4 s")),
        # Um erro de dedo na PORTA do `APP_LACAI_URL` (`8OO1` com letras)
        # levanta `httpx.InvalidURL`, que NÃO é `httpx.HTTPError` — é por isso
        # que o `except` é largo.
        lambda a: a.rebenta(httpx.InvalidURL("porta inválida")),
        lambda a: a.responde(500, None),
        lambda a: a.responde(401, {"detail": "chave errada"}),
        lambda a: a.responde(200, {"qualquer": "coisa"}),
        # Um 200 que nem sequer é um objecto (um proxy pelo meio, uma app a
        # responder outra coisa). É este que prende o `isinstance(corpo, dict)`:
        # sem ele, o `.get` levantava `AttributeError` e a funcionária lia
        # «Internal Server Error» ao balcão — a frase que este módulo inteiro
        # existe para não mostrar.
        lambda a: a.responde(200, ["isto", "não", "é", "um", "objecto"]),
    ],
    ids=["rede_em_baixo", "tecto_esgotado", "url_invalido", "erro_500",
         "chave_trocada", "200_fora_do_contrato", "200_que_nem_e_objecto"],
)
def test_a_app_em_baixo_e_venda_NORMAL_sem_desconto(monkeypatch, app, preparar):
    """A regra escrita da integração. A funcionária nunca vê um erro por causa
    disto: o cartão fica sem desconto e o EMITIR segue."""
    preparar(app)
    db = _db_do_voucher()
    resposta = _pedir(monkeypatch, db)
    assert resposta["voucher_id"] is None
    assert _linhas_gravadas(db)[0].get("desconto_eur") is None


def test_a_app_em_baixo_nao_TIRA_um_desconto_ja_aplicado(monkeypatch, app):
    """A conta fica EXACTAMENTE como estava — nem limpa o que já lá está.

    É a segunda chamada, no instante do EMITIR, com o dinheiro já contado: tirar
    o desconto aí mudava o total depois de a funcionária ter cobrado, a soma dos
    pagamentos deixava de bater e a fatura não saía. É precisamente o que a
    regra de ouro proíbe."""
    app.rebenta(httpx.ConnectError("em baixo"))
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1", desconto_eur=7.2, voucher_id="vch-1")])])

    resposta = _pedir(monkeypatch, db)

    assert resposta["voucher_id"] is None  # não se promete o que não se confirmou
    linhas = _linhas_gravadas(db)
    assert (linhas[0]["voucher_id"], linhas[0]["desconto_eur"]) == ("vch-1", 7.2)


def test_uma_conta_com_emissao_em_curso_nao_ganha_desconto_nenhum(monkeypatch, app):
    """Uma venda com reserva fiscal está CONGELADA (`venda._garante_sem_emissao`)
    — pode estar a virar Fatura Simplificada neste segundo. E recusa-se ANTES de
    falar com a app: uma recusa depois da chamada deixava do outro lado uma
    reserva de voucher por uma conta que ninguém ia cobrar."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2, "linha_id_alvo": "linha-1"})
    db = _db_do_voucher(refs=[{"ext_ref": "pos-loja-1-sessao-1-venda-1",
                               "venda_id": "venda-1"}])
    with pytest.raises(HTTPException) as e:
        _pedir(monkeypatch, db)
    assert e.value.status_code == 409
    assert app.pedidos == []


# --- O travão da conta a zero ----------------------------------------------------


@pytest.fixture
def _arranque_saudavel():
    """`finalizar` recusa-se (503) sem o índice de idempotência confirmado pelo
    `arrancar()` — e o autouse que faz isto vive DENTRO de `test_fiscal.py`, por
    isso não chega aqui. Este ficheiro testa a rota directamente e assume, como
    a suite já assumia, que o arranque correu bem."""
    db_mod.marcar_indice_idempotencia(True)
    yield
    db_mod.marcar_indice_idempotencia(None)


def _emitir(monkeypatch, db, pagamentos):
    _configura_vendus_env(monkeypatch)
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()
    return _corre(finalizar(
        "venda-1", PedidoFinalizarVenda(pagamentos=pagamentos), operador=_operador()))


def _db_do_emitir(linhas, **over):
    db = _db_do_voucher(vendas=[_venda(linhas=linhas, **over)])
    db._coleccoes[COLECOES["documentos"]] = ColeccaoFalsa(
        [], indices_unicos=_unicos_de("fat_documentos"))
    db._coleccoes[COLECOES["tipos_pagamento"]] = ColeccaoFalsa([_tipo_pagamento()])
    return db


def test_a_conta_a_zero_COM_linha_de_voucher_emite_sem_pagamento_nenhum(monkeypatch, _arranque_saudavel):
    """A decisão do dono: a conta pode ficar a 0,00 € e a Fatura Simplificada sai
    à mesma — zero euros, zero pontos.

    Sem pagamento nenhum, e é a única forma: o `PagamentoEntrada.valor` continua
    `gt=0`, porque um pagamento de 0,00 € não existe. A verificação que já lá
    estava — a soma dos pagamentos bate com o total — funciona sem se lhe tocar:
    soma de zero pagamentos é 0, e o total é 0."""
    db = _db_do_emitir([_linha(desconto_eur=8.99, voucher_id="vch-1")])
    resultado = _emitir(monkeypatch, db, [])
    assert resultado["estado"] == "emitida"
    assert ClienteEmissaoVendusFalso.instancias[0].chamadas_criar[0]["pagamentos"] == []


def test_a_conta_a_zero_SEM_linha_de_voucher_continua_a_ser_RECUSADA(monkeypatch, _arranque_saudavel):
    """**O travão, e é a parte que não se pode esquecer.** Abrir o zero a toda a
    gente deixava emitir a zero também com um desconto manual de 100 % — e esses
    não pedem PIN a ninguém."""
    db = _db_do_emitir([_linha(desconto_eur=8.99)])
    with pytest.raises(HTTPException) as e:
        _emitir(monkeypatch, db, [])
    assert e.value.status_code == 422
    assert "recompensa L'Açaí" in e.value.detail
    assert ClienteEmissaoVendusFalso.instancias == []  # nem se fala com o Vendus


def test_uma_conta_COM_VALOR_sem_pagamentos_continua_a_ser_RECUSADA(
        monkeypatch, _arranque_saudavel):
    """A protecção que saiu do modelo tem de continuar a existir algures.

    O `PedidoFinalizarVenda.pagamentos` deixou de ser `min_length=1` para a conta
    a zero poder finalizar sem pagamento nenhum. Se ninguém segurasse o resto,
    qualquer conta passava a poder ser emitida sem ninguém pagar nada — dinheiro
    a sair pela porta com uma Fatura Simplificada por cima.

    Quem segura é a soma dos pagamentos contra o total, que já lá estava: soma de
    zero pagamentos é 0, o total é 8,99, não batem, recusa. E a frase diz quanto
    falta, que é mais do que o erro de validação dizia."""
    db = _db_do_emitir([_linha()])          # 8,99 €, sem desconto nenhum
    with pytest.raises(HTTPException) as e:
        _emitir(monkeypatch, db, [])        # e sem pagamento nenhum
    assert e.value.status_code == 422
    assert "não bate com o total" in e.value.detail, e.value.detail
    assert ClienteEmissaoVendusFalso.instancias == []  # nem se fala com o Vendus


def test_uma_MARCA_orfa_sem_desconto_nao_destranca_a_conta_a_zero(
        monkeypatch, _arranque_saudavel):
    """A marca sozinha não chega. `PUT /pos/venda/{id}/linhas/{linha_id}` aceita
    `desconto_eur` e não conhece o `voucher_id`: a operadora pode limpar o
    desconto do voucher e deixar a marca para trás. Se o travão olhasse só para
    a marca, essa linha órfã destrancava a emissão a zero para um desconto
    manual de 100 % noutra linha — o buraco exacto que o travão existe para
    fechar."""
    # A marca ficou na linha; o zero veio de um desconto GLOBAL de 100 %, que
    # qualquer pessoa ao balcão pode dar e que não pede PIN a ninguém.
    db = _db_do_emitir([_linha(voucher_id="vch-1", desconto_eur=None)],
                       desconto_global_eur=8.99)
    with pytest.raises(HTTPException) as e:
        _emitir(monkeypatch, db, [])
    assert e.value.status_code == 422
    assert "recompensa L'Açaí" in e.value.detail


def test_uma_conta_COM_valor_continua_a_nao_se_finalizar_sem_pagamentos(monkeypatch, _arranque_saudavel):
    """O `min_length=1` da lista de pagamentos caiu (uma conta a zero precisa da
    lista vazia). O que segura isto é a rota, onde a soma tem de bater com o
    total — e a frase até diz quanto falta, o que a validação do pydantic não
    dizia."""
    db = _db_do_emitir([_linha()])
    with pytest.raises(HTTPException) as e:
        _emitir(monkeypatch, db, [])
    assert e.value.status_code == 422
    assert "8.99" in e.value.detail


def test_um_total_NEGATIVO_continua_a_ser_recusado(monkeypatch, _arranque_saudavel):
    """`total < 0` e não `<= 0`: o zero passou a ser legítimo, o negativo nunca."""
    db = _db_do_emitir([_linha(desconto_eur=8.99, voucher_id="vch-1")])
    _corre(db[COLECOES["vendas"]].update_one(
        {"id": "venda-1"}, {"$set": {"desconto_global_eur": 1.0}}))
    with pytest.raises(HTTPException) as e:
        _emitir(monkeypatch, db, [])
    assert e.value.status_code == 422
    assert "positivo" in e.value.detail


def test_o_desconto_do_voucher_chega_ao_VENDUS_pela_percentagem_de_sempre(monkeypatch, _arranque_saudavel):
    """Não há campo novo para o Vendus: o `desconto_eur` da linha entra na
    máquina que já existe, e `_itens_vendus` converte-o na percentagem que
    reproduz o líquido ao cêntimo — o único campo cuja semântica já foi
    confirmada contra a conta real."""
    db = _db_do_emitir([_linha(quantidade=2), _linha(id="l2", desconto_eur=7.2,
                                                     voucher_id="vch-1")])
    _emitir(monkeypatch, db, [PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro",
                                               valor=round(8.99 * 3 - 7.2, 2))])
    itens = ClienteEmissaoVendusFalso.instancias[0].chamadas_criar[0]["linhas"]
    assert "discount_amount" not in itens[1]
    assert round(8.99 * (1 - itens[1]["discount_percentage"] / 100.0), 2) == round(8.99 - 7.2, 2)


# --- O teste de CAMINHO ----------------------------------------------------------


def test_a_rota_do_voucher_esta_montada_no_router_e_e_ESTE_o_endereco():
    """**Afirmar o caminho que o código escreve nunca apanha um prefixo errado**
    — já matou o POS três vezes. A rota lê-se do router que o `server.py` monta,
    e é contra ESSE endereço que o ecrã tem de chamar: `/api/faturacao` e não
    `/api` (o módulo está montado com prefixo, `faturacao/__init__.py`).

    Sem isto, o decorador podia dizer `/pos/venda/{venda_id}/vouchers` — ou
    faltar de todo — e os testes acima ficavam todos verdes: chamam a função
    directamente."""
    from faturacao import router
    caminhos = {(metodo, r.path) for r in router.routes
                for metodo in getattr(r, "methods", ())}
    assert ("POST", "/api/faturacao/pos/venda/{venda_id}/voucher") in caminhos


# --- O que a revisão adversarial encontrou ---------------------------------------
#
# Cinco defeitos REAIS por cima de duas suites verdes, e a causa de fundo é uma
# só: **cada lado provou o seu contra um boneco do outro.** O teste do POS finge
# a resposta da app; o teste da app alimenta à mão um corpo que o POS nunca
# envia. Ninguém atravessou a fronteira — e por isso nenhuma das duas apanhou um
# contrato partido ao meio.


class _ColeccaoQueGuardaAProjeccao(ColeccaoFalsa):
    """O duplo da casa **aceita e IGNORA** a projecção do `find`
    (`ColeccaoFalsa.find`) — e é isso que deixa apagar `'vendus_ref': 1` da
    projecção dos produtos com as provas todas verdes. Em produção o efeito é
    o oposto de pequeno: TODOS os produtos chegam sem o campo e o desconto ao
    balcão deixa de existir para toda a gente. Guardar o que foi PEDIDO é a
    única forma de o afirmar."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.projeccoes = []

    def find(self, filtro=None, projecao=None):
        self.projeccoes.append(projecao)
        return super().find(filtro, projecao)


def test_a_projeccao_dos_produtos_PEDE_o_vendus_ref(monkeypatch, app):
    """**Achado 5 — suite verde, funcionalidade morta.** O `vendus_ref` é lido por
    PROJECÇÃO e nenhuma prova o afirmava: apagá-lo da selecção de campos deixava
    as provas todas verdes e matava a ponte entre os dois catálogos em produção.

    Afirma-se a projecção à mão (a alternativa era tirar a selecção de campos e
    ler o produto inteiro — mais dados na ida à base de dados que corre com a
    funcionária à espera) e, a seguir, que a ponte chegou mesmo à app: a
    projecção sozinha é um detalhe de implementação, o que importa é o campo no
    corpo.

    **E é UMA leitura, não duas.** Desde que a ponte é o produto, as `categorias`
    não servem aqui para nada — e quem espera por estes 4 s é a funcionária com o
    cliente à frente. Uma ida à base de dados que volte sem ninguém a precisar
    dela não aparece em nenhuma outra prova: por isso afirma-se também que a
    colecção das categorias NÃO foi tocada."""
    app.responde(200, {})
    produtos = _ColeccaoQueGuardaAProjeccao(
        [{"id": "prod-1", "nome": "Açaí", "vendus_ref": _REF_ACAI}])
    categorias = _ColeccaoQueGuardaAProjeccao(
        [{"id": "cat-1", "nome": "Venda ao Público", "vendus_ref": "1289461"}])
    db = _db_do_voucher()
    db._coleccoes[COLECOES["produtos"]] = produtos
    db._coleccoes[COLECOES["categorias"]] = categorias

    _pedir(monkeypatch, db)

    assert produtos.projeccoes == [{"_id": 0, "id": 1, "vendus_ref": 1}]
    assert categorias.projeccoes == [], "a ida às categorias não serve a ninguém"
    assert app.corpo()["linhas"][0]["produto_vendus_ref"] == _REF_ACAI


# --- O «Remover» ----------------------------------------------------------------


def test_o_REMOVER_manda_a_ligacao_a_NULO_e_tira_a_marca_e_o_desconto(monkeypatch, app):
    """**Achado 1 — o 422 por onde saía dinheiro.** O ecrã chama esta rota com
    `ligacao_id: null` para libertar o voucher (`lib/pos.js::pedirVoucherDaConta`
    e `PosFinalizar::removerOCliente`); com `min_length=1` o modelo recusava-o,
    o `catch` do ecrã engolia o 422 em silêncio e do lado do servidor não mudava
    nada — a marca e o desconto FICAVAM na linha.

    Os dois desfechos, os dois maus: a funcionária cobra os 7,20 €, carrega em
    EMITIR, o servidor recalcula um total de 0,00 €, a soma dos pagamentos não
    bate e **a fatura não sai**, com o cliente à frente; ou emite a 0,00 € sem
    pagamento nenhum e sem ligação de pontos, o `/creditar` nunca corre, o
    voucher nunca é consumido e volta a `active` — açaí de graça E recompensa
    devolvida."""
    db = _db_do_voucher(vendas=[_venda(linhas=[
        _linha(id="linha-1", desconto_eur=7.2, voucher_id="vch-1")])])

    resposta = _pedir(monkeypatch, db, ligacao_id=None)

    linhas = _linhas_gravadas(db)
    assert (linhas[0]["voucher_id"], linhas[0]["desconto_eur"]) == (None, None)
    # E o total volta com a conta, senão o ecrã continuava a mostrar o desconto.
    assert resposta["venda"]["totais"]["total"] == 8.99
    # Sem ligação não há a quem perguntar: a reserva do lado da app não se
    # consegue nomear daqui e morre sozinha em 15 minutos
    # (`services_vouchers.release_stale_reservations`).
    assert app.pedidos == []


# --- «Não sei» não é «não há» ----------------------------------------------------


def test_a_app_EM_BAIXO_diz_app_indisponivel_e_o_nao_ha_voucher_nao(monkeypatch, app):
    """**Achado 3 — falhar fechado em silêncio, que é a regra de ouro 2 ao
    contrário.** O `escolher_voucher` distingue `None` (a app não respondeu) de
    `{}` (não há voucher) e dizia-o na docstring; a rota deitava a diferença
    fora, e os dois davam o mesmo corpo com as chaves a `None`.

    O cenário: desconto aplicado, cartão a dizer «Açaí Médio grátis», a app cai,
    a funcionária carrega em EMITIR, esta rota responde 200 — e o ecrã apagava a
    recompensa e recusava a emissão com «A recompensa desta conta mudou», que é
    FALSO. Não mudou nada: foi a app que não respondeu."""
    db = _db_do_voucher()
    app.rebenta(httpx.ConnectError("em baixo"))
    assert _pedir(monkeypatch, db)["app_indisponivel"] is True

    app.responde(200, {})
    assert _pedir(monkeypatch, db)["app_indisponivel"] is False


# --- Avisar a app quando NÃO se aplicou ------------------------------------------


def _corpos(app):
    return [json.loads(p.content) for p in app.pedidos]


def test_a_linha_que_DESAPARECEU_avisa_a_app_para_libertar_o_voucher(monkeypatch, app):
    """**Achado 4 — cliente paga tudo e fica sem a recompensa.** A app já
    reservou o voucher e já armou o `/creditar` (a ligação guarda o
    `voucher_id`); aqui a linha alvo desapareceu e a conta fica sem desconto.
    Sem aviso, no EMITIR o POS volta a perguntar — mas se a app estiver em baixo
    nesse instante não há recálculo, a Fatura Simplificada sai ao preço cheio com
    a ligação dos pontos preenchida, e o `/creditar` consome o voucher.

    O aviso é a MESMA rota com as `linhas` vazias: é o contrato que a app já tem
    (nenhuma linha serve → liberta a reserva e põe o `voucher_id` da ligação a
    `None`), e não uma rota nova de nenhum dos lados."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2,
                       "linha_id_alvo": "linha-fantasma"})
    db = _db_do_voucher()

    resposta = _pedir(monkeypatch, db)

    assert resposta["motivo"] == "linha_desapareceu"
    assert _corpos(app)[-1] == {"ligacao_id": "lig-1", "linhas": []}
    assert len(app.pedidos) == 2


def test_o_CONTRATO_PARTIDO_tambem_avisa_a_app(monkeypatch, app):
    """O mesmo de cima pelo outro caminho: a app escolheu um voucher e mandou-o
    sem linha alvo (ou sem valor). Sem desconto, a gritar — e a libertar, porque
    a reserva do outro lado é igualmente real."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2, "linha_id_alvo": ""})
    db = _db_do_voucher()

    resposta = _pedir(monkeypatch, db)

    assert resposta["motivo"] == "contrato_partido"
    assert _corpos(app)[-1] == {"ligacao_id": "lig-1", "linhas": []}


def test_a_conta_que_FECHOU_debaixo_liberta_o_voucher_antes_de_subir_o_erro(
        monkeypatch, app):
    """A terceira saída: a escrita das linhas recusa-se (aqui, a conta deixou de
    estar aberta entre a leitura e a escrita — `venda._garante_aberta`). O
    desconto não entrou em lado nenhum e o voucher ficava reservado por uma venda
    que ninguém vai cobrar."""
    app.responde(200, {"voucher_id": "vch-1", "valor": 7.2, "linha_id_alvo": "linha-1"})
    db = _db_do_voucher()

    class _FechaAoEscrever(ColeccaoFalsa):
        """Fecha a conta entre a leitura da rota e a escrita de
        `_aplicar_as_linhas`: é o que a emissão de outro posto faz."""

        async def update_one(self, filtro, atualizacao):
            self._documentos[0]["estado"] = "emitida"
            return await super().update_one(filtro, atualizacao)

    db._coleccoes[COLECOES["vendas"]] = _FechaAoEscrever(
        [_venda(linhas=[_linha(id="linha-1")])])

    with pytest.raises(HTTPException) as e:
        _pedir(monkeypatch, db)

    assert e.value.status_code == 409
    assert _corpos(app)[-1] == {"ligacao_id": "lig-1", "linhas": []}


# --- O açaí OFERECIDO na fila dos pontos -----------------------------------------


def test_o_SEM_PONTOS_de_um_acai_oferecido_fecha_a_linha_em_FEITO(monkeypatch, app):
    """**Achado 2 — o painel do Faturação vermelho a cada oferta.** Uma conta a
    0,00 € por causa de um voucher é o caso NORMAL de um açaí oferecido, e a app
    responde-o em 200 com `sem_pontos` — a Fatura Simplificada saiu e o voucher
    foi consumido, só não há euros para converter em pontos.

    Fora do `_RESPOSTAS_FEITAS` não era recusa nem sem efeito: caía no último
    `_falhou` como falha TÉCNICA — esperas de 1, 2, 5, 10 e 30 min durante 24 h,
    ~13 chamadas inúteis à app, e no fim `falhado`. É precisamente o vermelho que
    a mudança de `sem_valor` para `sem_pontos` foi escrita para evitar."""
    db, fila = _db_da_fila(_credito())
    app.responde(200, {"estado": "sem_pontos", "pontos": 0, "voucher_id": "vch-1"})

    _corre(pontos_app.enviar(db, agora=AGORA))

    gravada = fila.linhas()[0]
    assert (gravada["estado"], gravada["pontos"]) == ("feito", 0)
    assert gravada.get("tentativas") in (None, 0), "não é falha técnica nenhuma"
    assert gravada["a_enviar_ate"] == pontos_app._NUNCA, "a reserva tem de ser largada"
    # E não se volta a bater à porta da app por uma oferta já resolvida.
    assert _corre(pontos_app.enviar(db, agora=AGORA + timedelta(days=1))) is None
    assert len(app.pedidos) == 1
