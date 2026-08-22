"""O separador **Faturação**: a lista dos documentos e a fatura aberta.

Mesmo duplo de base de dados de `test_venda.py` — importado de lá e NÃO
copiado: uma segunda cópia daquele casamento de filtros (`$in`, `$nin`,
`$regex`, o índice único parcial do posto) divergia da primeira e punha estes
testes a medir um Mongo que não é o do módulo. Nenhum teste liga a uma base de
dados nem à rede.

A regra central: **os valores de teste EXPÕEM a diferença.** Nada aqui vale
0,30 € nem 8,50 €. As faturas são feitas de 10,20 € (13 %) e 1,15 € (23 %) —
duas taxas no mesmo talão, que é o caso do cardápio real (açaí a 13 %,
refrigerante a 23 %) — e os descontos são de 0,29 €, que é um número que não
se reparte bem por duas linhas e por isso apanha quem o reparta mal.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import documentos as doc_mod
from faturacao import venda as venda_mod
from faturacao.db import COLECOES
from faturacao.documentos import (
    PedidoCopiar,
    copiar_para_venda,
    listar_documentos,
    obter_documento,
    talao_do_documento,
)

from .test_venda import (
    ColeccaoFalsa,
    DbFalsa,
    _caixa,
    _chave_do_posto,
    _corre,
    _operador,
    _produto,
    _sessao,
)


# --- O cenário: duas faturas reais de uma loja de açaí -------------------------
#
# `_TAXA_ACAI` e `_TAXA_REFRI` não são inventados aqui: são os dois códigos que
# `precos._TAXAS` mapeia para 13 % e 23 %, as duas taxas que o cardápio das
# lojas usa (memória do dono: comida e águas 13 % INT, refrigerantes 23 % NOR).
_ACAI = 10.20
_REFRI = 1.15
_TOPPING = 0.29


def _linha(**over):
    li = {
        "id": "linha-1",
        "produto_id": "prod-acai",
        "produto_nome": "Açaí Regular",
        "produto_preco": _ACAI,
        "produto_tax_id": "INT",
        "produto_vendus_ref": None,
        "quantidade": 1,
        "opcoes": [],
        "respostas_texto": [],
        "preco_override": None,
        "tax_override": None,
        "desconto_pct": None,
        "desconto_eur": None,
    }
    li.update(over)
    return li


def _venda_emitida(**over):
    v = {
        "id": "venda-1",
        "loja_id": "loja-1",
        "caixa_id": "caixa-1",
        "sessao_id": "sessao-1",
        "operador_id": "op-1",
        "dispositivo_id": "pc-1",
        "linhas": [
            _linha(
                id="linha-acai",
                opcoes=[{
                    "id": "op-nutella", "grupo_id": "g-toppings",
                    "nome": "Nutella", "preco": _TOPPING, "sai_na_fatura": True,
                }],
                respostas_texto=[{
                    "grupo_id": "g-nome", "nome_grupo": "Nome", "texto": "Rafaela",
                }],
            ),
            _linha(
                id="linha-refri", produto_id="prod-refri", produto_nome="Coca-Cola",
                produto_preco=_REFRI, produto_tax_id="NOR",
            ),
        ],
        "desconto_global_pct": None,
        "desconto_global_eur": None,
        "estado": "emitida",
        "criada_em": "2026-08-21T21:40:00+00:00",
        "pagamentos": [{
            "tipo_pagamento_id": "tp-1", "nome": "Multibanco",
            "tipo_fiscal": "CD", "valor": 11.64,
        }],
        "cliente_nif": None,
    }
    v.update(over)
    return v


def _documento(**over):
    d = {
        "id": "doc-1",
        "vendus_document_id": 8801,
        "atcud": "JFT7-1824",
        "numero": "FS 05P2026/1824",
        "total": 11.64,
        "total_bruto": 11.64,
        "total_liquido": 9.96,
        "tipo": "FS",
        "modo": "normal",
        "ext_ref": "pos-loja-1-sessao-1-venda-1",
        "venda_id": "venda-1",
        "loja_id": "loja-1",
        "emitido_em": "2026-08-21T21:41:00+00:00",
    }
    d.update(over)
    return d


def _grupo_toppings(**over):
    g = {
        "id": "g-toppings",
        "nome": "Toppings",
        "sai_na_fatura": True,
        "opcoes": [
            {"id": "op-nutella", "nome": "Nutella", "preco": _TOPPING, "ativa": True},
        ],
    }
    g.update(over)
    return g


def _db(registo, documentos=None, vendas=None, produtos=None, grupos=None,
        caixas=None, sessoes=None, com_indice_do_posto=False):
    return DbFalsa({
        COLECOES["documentos"]: ColeccaoFalsa(registo, documentos),
        COLECOES["vendas"]: ColeccaoFalsa(
            registo, vendas,
            unico=_chave_do_posto if com_indice_do_posto else None),
        COLECOES["produtos"]: ColeccaoFalsa(registo, produtos),
        COLECOES["grupos_personalizacao"]: ColeccaoFalsa(registo, grupos),
        COLECOES["caixas"]: ColeccaoFalsa(registo, caixas),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(
            registo, [_sessao()] if sessoes is None else sessoes),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(registo, []),
    })


def _ligar(monkeypatch, db):
    """O mesmo `db` para os dois módulos: `copiar_para_venda` chama as rotas
    reais de `venda.py`, e essas vão buscar a base pelo `obter_db` DELAS."""
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)


# --- A lista ------------------------------------------------------------------


def test_a_lista_traz_o_que_a_operadora_precisa_para_encontrar_a_fatura(monkeypatch):
    """Número, hora, total, o que o cliente levou e como pagou.

    As três coisas que ele diz ao voltar — «paguei onze e sessenta e quatro»,
    «era um açaí», «paguei em multibanco» — têm de estar todas na LINHA da
    lista, senão a operadora abre faturas uma a uma com a fila à frente."""
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    resposta = _corre(listar_documentos(operador=_operador()))
    (linha,) = resposta["documentos"]
    assert linha["numero"] == "FS 05P2026/1824"
    assert linha["emitido_em"] == "2026-08-21T21:41:00+00:00"
    assert linha["total"] == 11.64
    assert linha["artigos"] == [
        {"nome": "Açaí Regular", "quantidade": 1},
        {"nome": "Coca-Cola", "quantidade": 1},
    ]
    assert linha["mais_artigos"] == 0
    assert linha["pagamentos"] == [{"nome": "Multibanco", "valor": 11.64}]
    assert linha["modo"] == "normal"
    assert linha["tem_venda"] is True


def test_a_lista_vem_da_mais_recente_para_a_mais_antiga(monkeypatch):
    """A fatura que o cliente veio buscar é quase sempre das últimas.

    Com o `.sort("emitido_em", -1)` apagado, a ordem certa vinha por acaso da
    ordem de inserção — o `CursorFalso` de `test_venda.py` ordena a sério
    precisamente para isso não passar."""
    antiga = _documento(id="doc-antigo", numero="FS 05P2026/1800",
                        ext_ref="e-1", venda_id="venda-antiga",
                        emitido_em="2026-08-20T10:00:00+00:00")
    db = _db(
        [],
        # Inseridos pela ordem ERRADA de propósito.
        documentos=[antiga, _documento()],
        vendas=[_venda_emitida(), _venda_emitida(id="venda-antiga")],
    )
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    numeros = [d["numero"] for d in _corre(
        listar_documentos(operador=_operador()))["documentos"]]
    assert numeros == ["FS 05P2026/1824", "FS 05P2026/1800"]


def test_a_lista_NAO_e_so_o_turno_a_decorrer(monkeypatch):
    """«O cliente voltou amanhã» é o caso real, e é o que uma lista limitada à
    sessão aberta falha SEMPRE: às 9h da manhã está vazia.

    O documento de ontem é de OUTRA sessão (`ext_ref` de `sessao-0`) e a venda
    dele também — e aparece na mesma."""
    ontem = _documento(
        id="doc-ontem", numero="FS 05P2026/1799", venda_id="venda-ontem",
        ext_ref="pos-loja-1-sessao-0-venda-ontem",
        emitido_em="2026-08-20T22:50:00+00:00")
    db = _db(
        [],
        documentos=[_documento(), ontem],
        vendas=[_venda_emitida(), _venda_emitida(id="venda-ontem", sessao_id="sessao-0")],
    )
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    numeros = [d["numero"] for d in _corre(
        listar_documentos(operador=_operador()))["documentos"]]
    assert "FS 05P2026/1799" in numeros


def test_a_lista_nao_mostra_faturas_de_outra_loja(monkeypatch):
    """O âmbito é a loja do TOKEN, e é a única fronteira que este ecrã tem.
    Sem ela, o PC de Cascais lia as faturas de Lisboa."""
    db = _db(
        [],
        documentos=[_documento(), _documento(
            id="doc-outra", numero="FS OUTRA/1", loja_id="loja-2",
            venda_id="venda-outra", ext_ref="e-2")],
        vendas=[_venda_emitida(), _venda_emitida(id="venda-outra", loja_id="loja-2")],
    )
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    numeros = [d["numero"] for d in _corre(
        listar_documentos(operador=_operador()))["documentos"]]
    assert numeros == ["FS 05P2026/1824"]


def test_a_lista_diz_quando_ha_mais_do_que_o_tecto(monkeypatch):
    """Uma lista truncada que não se assume é uma lista que mente sobre o que
    não encontrou: a operadora procura, não encontra, e conclui que a fatura
    não existe.

    `ha_mais` é medido (lê-se um documento a mais do que o tecto) e não
    inferido de a lista ter vindo cheia — que dá a resposta errada
    exactamente quando há `_LIMITE_LISTA` documentos e nem um a mais."""
    quantos = doc_mod._LIMITE_LISTA + 1
    documentos = [
        _documento(id="doc-%03d" % i, numero="FS 05P2026/%d" % (2000 + i),
                   venda_id="venda-%03d" % i, ext_ref="e-%03d" % i,
                   emitido_em="2026-08-21T%02d:%02d:00+00:00" % (i // 60, i % 60))
        for i in range(quantos)
    ]
    db = _db([], documentos=documentos, vendas=[])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    resposta = _corre(listar_documentos(operador=_operador()))
    assert len(resposta["documentos"]) == doc_mod._LIMITE_LISTA
    assert resposta["limite"] == doc_mod._LIMITE_LISTA
    assert resposta["ha_mais"] is True


def test_com_o_tecto_certo_a_lista_nao_grita_que_ha_mais(monkeypatch):
    documentos = [
        _documento(id="doc-%03d" % i, numero="FS 05P2026/%d" % (2000 + i),
                   venda_id="venda-%03d" % i, ext_ref="e-%03d" % i,
                   emitido_em="2026-08-21T%02d:%02d:00+00:00" % (i // 60, i % 60))
        for i in range(doc_mod._LIMITE_LISTA)
    ]
    db = _db([], documentos=documentos, vendas=[])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    assert _corre(listar_documentos(operador=_operador()))["ha_mais"] is False


def test_uma_fatura_cuja_venda_desapareceu_continua_na_lista(monkeypatch):
    """O DOCUMENTO existe, tem número e ATCUD. Escondê-lo por causa da venda
    era esconder um documento fiscal real — e a lista tem de dizer que não
    consegue mostrar o que lá foi, em vez de desenhar uma fatura vazia como se
    o cliente não tivesse levado nada."""
    db = _db([], documentos=[_documento()], vendas=[])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    (linha,) = _corre(listar_documentos(operador=_operador()))["documentos"]
    assert linha["numero"] == "FS 05P2026/1824"
    assert linha["tem_venda"] is False
    assert linha["artigos"] == []


def test_a_lista_conta_os_artigos_que_nao_couberam(monkeypatch):
    linhas = [
        _linha(id="li-%d" % i, produto_nome="Artigo %d" % i)
        for i in range(doc_mod._ARTIGOS_NO_RESUMO + 2)
    ]
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida(linhas=linhas)])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    (linha,) = _corre(listar_documentos(operador=_operador()))["documentos"]
    assert len(linha["artigos"]) == doc_mod._ARTIGOS_NO_RESUMO
    assert linha["mais_artigos"] == 2


def test_o_mesmo_artigo_repetido_agrega_se_numa_linha_so(monkeypatch):
    """«1× Coca-Cola · 1× Coca-Cola · 1× Coca-Cola +2» é a mesma informação que
    «5× Coca-Cola», e ilegível — foi assim que apareceu no ecrã, e o «+2»
    escondia que os outros dois eram o mesmo refrigerante.

    Mesma regra de `precos._descricao_das_opcoes` e de `talao._doses`, e a
    ordem é a da PRIMEIRA aparição: agregar não pode reordenar."""
    db = _db(
        [],
        documentos=[_documento()],
        vendas=[_venda_emitida(linhas=[
            _linha(id="li-%d" % i, produto_id="prod-refri",
                   produto_nome="Coca-Cola", produto_preco=_REFRI,
                   produto_tax_id="NOR")
            for i in range(5)
        ] + [_linha(id="li-acai")])],
    )
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    (linha,) = _corre(listar_documentos(operador=_operador()))["documentos"]
    assert linha["artigos"] == [
        {"nome": "Coca-Cola", "quantidade": 5.0},
        {"nome": "Açaí Regular", "quantidade": 1.0},
    ]
    assert linha["mais_artigos"] == 0


def test_uma_quantidade_ilegivel_nao_apaga_o_artigo_da_lista(monkeypatch):
    """O que não se pode perder é a EXISTÊNCIA do artigo — a mesma regra de
    `por_resolver._total_da_venda`. Um `None` na quantidade não pode tirar o
    açaí da linha por que a operadora reconhece a fatura."""
    db = _db([], documentos=[_documento()],
             vendas=[_venda_emitida(linhas=[_linha(quantidade=None)])])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    (linha,) = _corre(listar_documentos(operador=_operador()))["documentos"]
    assert [a["nome"] for a in linha["artigos"]] == ["Açaí Regular"]


# --- A fatura aberta ----------------------------------------------------------


def test_a_fatura_aberta_mostra_as_linhas_como_saíram_no_papel(monkeypatch):
    """O «Produto» é o título que foi entregue à AT — com os toppings entre
    parêntesis. O cliente que confere o que pagou pagou a Nutella."""
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    fatura = _corre(obter_documento("doc-1", operador=_operador()))
    acai, refri = fatura["linhas"]
    assert acai["titulo"] == "Açaí Regular (Nutella)"
    # 10,20 € + 0,29 € do topping — o preço unitário JÁ com a personalização,
    # exactamente como `precos.linha_de_venda` o construiu para o Vendus.
    assert acai["preco_unitario"] == 10.49
    assert acai["quantidade"] == 1
    assert acai["total"] == 10.49
    assert refri["titulo"] == "Coca-Cola"
    assert refri["total"] == 1.15


def test_o_mapa_de_imposto_da_fatura_fecha_ao_centimo(monkeypatch):
    """Duas taxas no mesmo talão — 13 % no açaí, 23 % no refrigerante — e
    `base + iva == total` em cada linha, por construção.

    É o mesmo `mapa_imposto.mapa_de_imposto` do Z, com uma lista de uma venda:
    não há aqui segunda repartição nenhuma que possa discordar da emissão."""
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    fatura = _corre(obter_documento("doc-1", operador=_operador()))
    mapa = {linha["taxa"]: linha for linha in fatura["mapa_imposto"]}
    assert set(mapa) == {13, 23}
    for taxa, linha in mapa.items():
        assert round(linha["base"] + linha["iva"], 2) == linha["total"], taxa
    assert mapa[13]["total"] == 10.49
    assert mapa[23]["total"] == 1.15
    totais = fatura["totais_imposto"]
    assert round(totais["base"] + totais["iva"], 2) == totais["total"] == 11.64


def test_o_total_da_fatura_e_o_do_DOCUMENTO_e_nao_uma_soma_do_ecra(monkeypatch):
    """O número que a AT tem é o do documento. A soma das linhas vai à mesma na
    resposta, e quando os dois batem ninguém tem de saber que são dois."""
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    fatura = _corre(obter_documento("doc-1", operador=_operador()))
    assert fatura["total"] == 11.64
    assert fatura["total_das_linhas"] == 11.64
    assert fatura["total_divergente"] is False


def test_quando_o_documento_e_as_linhas_NAO_batem_a_fatura_di_lo(monkeypatch):
    """Nunca devia acontecer — as linhas são as que foram enviadas e a
    repartição do desconto global é exacta ao cêntimo. É precisamente por isso
    que uma divergência tem de APARECER: se um dia aparecer, aconteceu alguma
    coisa que ninguém previu, e escolher um dos dois números em silêncio
    escondia-a para sempre.

    Um cêntimo de diferença chega — é o tamanho do erro que este ecrã existe
    para apanhar."""
    db = _db(
        [],
        documentos=[_documento(total=11.63)],
        vendas=[_venda_emitida()],
    )
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    fatura = _corre(obter_documento("doc-1", operador=_operador()))
    assert fatura["total"] == 11.63
    assert fatura["total_das_linhas"] == 11.64
    assert fatura["total_divergente"] is True


def test_o_desconto_global_reparte_se_e_o_mapa_continua_a_fechar(monkeypatch):
    """0,29 € de desconto sobre uma conta de 11,64 € com duas taxas.

    É o número que apanha quem reparta mal: 29 cêntimos não se dividem em duas
    partes iguais, e a fatia de cada linha tem de ser proporcional ao que ela
    vale — senão a base declarada por taxa deixa de bater com o total do
    documento."""
    venda = _venda_emitida(desconto_global_eur=_TOPPING)
    db = _db([], documentos=[_documento(total=11.35)], vendas=[venda])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    fatura = _corre(obter_documento("doc-1", operador=_operador()))
    assert fatura["total_das_linhas"] == 11.35
    assert fatura["total_divergente"] is False
    totais = fatura["totais_imposto"]
    assert round(totais["base"] + totais["iva"], 2) == totais["total"] == 11.35


def test_a_linha_com_desconto_DIZ_para_onde_foram_os_centimos(monkeypatch):
    """«Preço/Uni. € 10,20 · Qtd. 1 · Preço € 9,94» lê-se como um erro de soma
    se a fatura não disser em lado nenhum que houve desconto — e quem confere um
    talão pára ali. O valor é somado no SERVIDOR, em cêntimos inteiros.

    0,29 € de desconto global sobre 11,35 €: 0,26 € caem no açaí e 0,03 € no
    refrigerante — proporcional, e não metade para cada um."""
    venda = _venda_emitida(desconto_global_eur=_TOPPING, linhas=[
        _linha(id="li-acai"),
        _linha(id="li-refri", produto_id="prod-refri", produto_nome="Coca-Cola",
               produto_preco=_REFRI, produto_tax_id="NOR"),
    ])
    db = _db([], documentos=[_documento(total=11.06)], vendas=[venda])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    acai, refri = _corre(obter_documento("doc-1", operador=_operador()))["linhas"]
    assert (acai["preco_unitario"], acai["desconto"], acai["total"]) == (10.20, 0.26, 9.94)
    assert (refri["preco_unitario"], refri["desconto"], refri["total"]) == (1.15, 0.03, 1.12)


def test_uma_linha_sem_desconto_traz_o_campo_a_zero(monkeypatch):
    """Sempre presente, nunca ausente — o ecrã não pode ter de adivinhar se a
    falta da chave quer dizer «não houve desconto» ou «versão antiga da API»."""
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)
    for linha in _corre(obter_documento("doc-1", operador=_operador()))["linhas"]:
        assert linha["desconto"] == 0.0


def test_a_fatura_sem_NIF_e_de_consumidor_final(monkeypatch):
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)
    assert _corre(obter_documento("doc-1", operador=_operador()))["cliente_nif"] is None


def test_a_fatura_com_NIF_mostra_o_NIF(monkeypatch):
    db = _db([], documentos=[_documento()],
             vendas=[_venda_emitida(cliente_nif="517542510")])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)
    assert _corre(
        obter_documento("doc-1", operador=_operador()))["cliente_nif"] == "517542510"


def test_a_fatura_de_outra_loja_e_404(monkeypatch):
    """404 e não 403: o id vem do browser, e um 403 confirmava a quem
    perguntasse que aquele documento existe."""
    db = _db([], documentos=[_documento(loja_id="loja-2")], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(obter_documento("doc-1", operador=_operador()))
    assert e.value.status_code == 404


def test_a_fatura_cuja_venda_desapareceu_abre_na_mesma(monkeypatch):
    db = _db([], documentos=[_documento()], vendas=[])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    fatura = _corre(obter_documento("doc-1", operador=_operador()))
    assert fatura["numero"] == "FS 05P2026/1824"
    assert fatura["tem_venda"] is False
    assert fatura["linhas"] == []
    assert fatura["mapa_imposto"] == []
    # Sem linhas não há divergência que se possa afirmar — «não sei» não se
    # desenha como «não bate».
    assert fatura["total_divergente"] is False


def test_a_fatura_carrega_o_modo_em_que_foi_emitida(monkeypatch):
    """Um documento emitido em `tests` não vale nada, e continua a não valer
    nada amanhã, com o servidor já em `normal`. O carimbo é do DOCUMENTO."""
    db = _db([], documentos=[_documento(modo="tests")], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)
    assert _corre(obter_documento("doc-1", operador=_operador()))["modo"] == "tests"


# --- O talão (reimprimir) -----------------------------------------------------


def test_o_talao_guardado_sai_em_base64_pronto_para_a_impressora(monkeypatch):
    """O caminho do servidor até ao ponto em que os bytes estão prontos. O
    agente de impressão ainda não existe; quando existir, liga-se aqui."""
    bytes_escpos = b"\x1b@L'ACAI\nFS 05P2026/1824\n"
    db = _db([], documentos=[_documento(talao_escpos=bytes_escpos)],
             vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    resposta = _corre(talao_do_documento("doc-1", operador=_operador()))
    assert resposta["formato"] == "escpos-base64"
    import base64
    assert base64.b64decode(resposta["talao"]) == bytes_escpos


def test_sem_talao_guardado_a_resposta_e_409_e_diz_o_que_falta(monkeypatch):
    """409 e não 404: o DOCUMENTO existe (um 404 mandava a operadora
    procurá-lo outra vez); o que não existe é o papel.

    **E hoje é este o caso de TODOS os documentos**: `vendus/emissao.py` traz o
    `talao_escpos` na resposta da emissão e `fiscal._gravar_documento` não o
    grava. Ver o relatório — falta uma linha no núcleo fiscal."""
    db = _db([], documentos=[_documento()], vendas=[_venda_emitida()])
    monkeypatch.setattr(doc_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as e:
        _corre(talao_do_documento("doc-1", operador=_operador()))
    assert e.value.status_code == 409
    assert "talão" in e.value.detail


def test_o_documento_gravado_HOJE_nao_tem_talao_nenhum():
    """**O pressuposto, verificado em vez de acreditado.**

    O trabalho foi pedido com «o talão certificado já está guardado com a
    fatura». Não está: `fiscal._gravar_documento` constrói o documento campo a
    campo e `talao_escpos` não está na lista, por isso os bytes que o Vendus
    devolve são deitados fora no instante em que a fatura é gravada.

    Este teste lê o CÓDIGO DE PRODUÇÃO e não uma cópia — se alguém acrescentar
    a linha que falta, ele fica vermelho e é isso que se quer: nessa altura o
    botão de reimprimir passa a ter bytes, e esta afirmação deixa de ser
    verdade."""
    import inspect

    from faturacao.fiscal import _gravar_documento

    corpo = inspect.getsource(_gravar_documento)
    inicio = corpo.index("documento = {")
    fim = corpo.index("try:", inicio)
    assert "talao_escpos" not in corpo[inicio:fim], (
        "O `talao_escpos` passou a ser gravado em fat_documentos — óptimo. "
        "Apague este teste e ligue o botão «Imprimir» do separador Faturação."
    )


# --- Copiar para a venda ------------------------------------------------------


def _db_para_copiar(vendas=None, grupos=None, produtos=None, **over):
    return _db(
        [],
        documentos=[_documento()],
        vendas=[_venda_emitida()] if vendas is None else vendas,
        produtos=[
            _produto(id="prod-acai", nome="Açaí Regular", preco=_ACAI, tax_id="INT"),
            _produto(id="prod-refri", nome="Coca-Cola", preco=_REFRI, tax_id="NOR"),
        ] if produtos is None else produtos,
        grupos=[_grupo_toppings()] if grupos is None else grupos,
        caixas=[_caixa()],
        com_indice_do_posto=True,
        **over,
    )


def test_copiar_abre_uma_conta_nova_com_as_mesmas_linhas(monkeypatch):
    db = _db_para_copiar()
    _ligar(monkeypatch, db)

    resposta = _corre(copiar_para_venda(
        "doc-1", PedidoCopiar(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-1")))
    nova = resposta["venda"]
    assert nova["id"] != "venda-1"
    assert nova["estado"] == "aberta"
    assert [li["produto_nome"] for li in nova["linhas"]] == ["Açaí Regular", "Coca-Cola"]
    assert resposta["nao_copiados"] == []
    assert resposta["copiada_de"]["numero"] == "FS 05P2026/1824"


def test_copiar_leva_as_personalizacoes_e_o_nome_no_copo(monkeypatch):
    """É isto que faz a cópia valer a pena num açaí: o cliente não pede «um
    açaí», pede o dele — com Nutella e com o nome escrito no copo."""
    db = _db_para_copiar()
    _ligar(monkeypatch, db)

    nova = _corre(copiar_para_venda(
        "doc-1", PedidoCopiar(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-1")))["venda"]
    acai = nova["linhas"][0]
    assert [o["nome"] for o in acai["opcoes"]] == ["Nutella"]
    assert [r["texto"] for r in acai["respostas_texto"]] == ["Rafaela"]


def test_a_copia_paga_os_precos_de_HOJE_e_nao_os_da_fatura(monkeypatch):
    """O açaí subiu de 10,20 € para 11,15 € e a Nutella de 0,29 € para 0,45 €.

    O produto é relido do catálogo por `juntar_linha` (isso já vinha de
    graça); a OPÇÃO é a metade que passava despercebida — as `opcoes` viajam
    gravadas na linha antiga com o preço do dia em que foram vendidas, e
    `precos.linha_de_venda` soma-as tal e qual."""
    db = _db_para_copiar(
        produtos=[
            _produto(id="prod-acai", nome="Açaí Regular", preco=11.15, tax_id="INT"),
            _produto(id="prod-refri", nome="Coca-Cola", preco=_REFRI, tax_id="NOR"),
        ],
        grupos=[_grupo_toppings(opcoes=[
            {"id": "op-nutella", "nome": "Nutella", "preco": 0.45, "ativa": True},
        ])],
    )
    _ligar(monkeypatch, db)

    nova = _corre(copiar_para_venda(
        "doc-1", PedidoCopiar(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-1")))["venda"]
    acai = nova["linhas"][0]
    assert acai["produto_preco"] == 11.15
    assert [o["preco"] for o in acai["opcoes"]] == [0.45]
    # 11,15 + 0,45 + 1,15 = 12,75 — e nem um cêntimo dos preços de ontem.
    assert nova["totais"]["total"] == 12.75


def test_a_copia_NAO_leva_o_desconto_nem_os_overrides_da_fatura(monkeypatch):
    """Um desconto é uma decisão daquela venda, não uma propriedade do pedido.
    Repeti-lo às cegas era dar dinheiro sem que ninguém o tivesse decidido
    hoje — e um `preco_override` era vender ao preço de uma cortesia antiga."""
    venda = _venda_emitida(
        desconto_global_eur=_TOPPING,
        linhas=[_linha(preco_override=0.01, desconto_pct=50.0)],
    )
    db = _db_para_copiar(vendas=[venda])
    _ligar(monkeypatch, db)

    nova = _corre(copiar_para_venda(
        "doc-1", PedidoCopiar(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-1")))["venda"]
    (linha,) = nova["linhas"]
    assert linha["preco_override"] is None
    assert linha["desconto_pct"] is None
    assert linha["desconto_eur"] is None
    assert nova["desconto_global_eur"] is None
    assert nova["totais"]["total"] == _ACAI


def test_copiar_com_o_posto_ocupado_e_409_ANTES_de_criar_o_que_quer_que_seja(monkeypatch):
    """**Um PC atende UM cliente de cada vez** — a regra do dono, e é
    `venda.abrir_venda` que a impõe. A recusa dela sobe daqui tal e qual, e
    nenhuma venda nova fica para trás.

    Afirma-se a FRASE da porta e não só o 409: a primeira versão deste teste
    contentava-se com o código, e um mutante que ENGOLIA o 409 de
    `abrir_venda` continuava verde — a cópia acabava por falhar mais à frente,
    por outra razão, com o mesmo 409 e uma frase que mandava a operadora
    procurar artigos em vez de acabar a conta que tem à frente. A frase é a de
    `venda.py`, importada de lá: uma cópia escrita aqui ficava verde no dia em
    que as duas divergissem."""
    from faturacao.venda import _MSG_CONTA_POR_RESOLVER

    em_curso = _venda_emitida(
        id="venda-em-curso", estado="aberta", linhas=[_linha()],
        posto_em_curso="loja-1|pc-1", entregue_ao_gestor_em=None,
        criada_em="2026-08-22T10:00:00+00:00")
    db = _db_para_copiar(vendas=[_venda_emitida(), em_curso])
    _ligar(monkeypatch, db)

    quantas_antes = len(db[COLECOES["vendas"]]._documentos)
    with pytest.raises(HTTPException) as e:
        _corre(copiar_para_venda(
            "doc-1", PedidoCopiar(caixa_id="caixa-1"),
            operador=_operador(dispositivo_id="pc-1")))
    assert e.value.status_code == 409
    assert e.value.detail.startswith(_MSG_CONTA_POR_RESOLVER)
    assert len(db[COLECOES["vendas"]]._documentos) == quantas_antes


def test_um_artigo_que_ja_nao_existe_no_catalogo_e_NOMEADO_e_nao_rebenta(monkeypatch):
    """Uma cópia meia feita sem dizer o que lhe falta é um pedido errado a
    caminho da cozinha. O que não se pode copiar diz-se pelo nome."""
    db = _db_para_copiar(produtos=[
        _produto(id="prod-acai", nome="Açaí Regular", preco=_ACAI, tax_id="INT"),
    ])
    _ligar(monkeypatch, db)

    resposta = _corre(copiar_para_venda(
        "doc-1", PedidoCopiar(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-1")))
    assert [li["produto_nome"] for li in resposta["venda"]["linhas"]] == ["Açaí Regular"]
    assert any("Coca-Cola" in aviso for aviso in resposta["nao_copiados"])


def test_um_topping_desactivado_e_NOMEADO_e_nao_viaja_com_o_preco_antigo(monkeypatch):
    """Deixá-lo passar com o preço antigo era cobrar por uma coisa que o
    catálogo já não tem; deixá-lo passar sem preço era dá-la de graça."""
    db = _db_para_copiar(grupos=[_grupo_toppings(opcoes=[
        {"id": "op-nutella", "nome": "Nutella", "preco": _TOPPING, "ativa": False},
    ])])
    _ligar(monkeypatch, db)

    resposta = _corre(copiar_para_venda(
        "doc-1", PedidoCopiar(caixa_id="caixa-1"),
        operador=_operador(dispositivo_id="pc-1")))
    acai = resposta["venda"]["linhas"][0]
    assert acai["opcoes"] == []
    assert acai["produto_preco"] == _ACAI
    assert any("Nutella" in aviso for aviso in resposta["nao_copiados"])
    # E o total não leva os 0,29 € de um topping que já não existe.
    assert resposta["venda"]["totais"]["total"] == round(_ACAI + _REFRI, 2)


def test_uma_copia_sem_um_unico_artigo_vivo_e_recusada_sem_deixar_conta_presa(monkeypatch):
    """Uma conta vazia a prender o posto é pior do que uma recusa: a operadora
    fica sem poder abrir a do cliente seguinte e sem perceber porquê."""
    db = _db_para_copiar(produtos=[])
    _ligar(monkeypatch, db)

    with pytest.raises(HTTPException) as e:
        _corre(copiar_para_venda(
            "doc-1", PedidoCopiar(caixa_id="caixa-1"),
            operador=_operador(dispositivo_id="pc-1")))
    assert e.value.status_code == 409
    abertas = [
        v for v in db[COLECOES["vendas"]]._documentos if v.get("estado") == "aberta"
    ]
    assert abertas == []


def test_copiar_uma_fatura_de_outra_loja_e_404(monkeypatch):
    db = _db_para_copiar()
    db[COLECOES["documentos"]]._documentos[0]["loja_id"] = "loja-2"
    _ligar(monkeypatch, db)

    with pytest.raises(HTTPException) as e:
        _corre(copiar_para_venda(
            "doc-1", PedidoCopiar(caixa_id="caixa-1"),
            operador=_operador(dispositivo_id="pc-1")))
    assert e.value.status_code == 404


def test_copiar_uma_fatura_cuja_venda_desapareceu_e_409_e_nao_500(monkeypatch):
    db = _db_para_copiar(vendas=[])
    _ligar(monkeypatch, db)

    with pytest.raises(HTTPException) as e:
        _corre(copiar_para_venda(
            "doc-1", PedidoCopiar(caixa_id="caixa-1"),
            operador=_operador(dispositivo_id="pc-1")))
    assert e.value.status_code == 409


def test_copiar_com_a_caixa_fechada_nao_abre_conta_nenhuma(monkeypatch):
    """`abrir_venda` resolve a sessão pela caixa e recusa sem sessão aberta —
    e é a mesma recusa de sempre, não uma segunda escrita aqui."""
    db = _db_para_copiar(sessoes=[])
    _ligar(monkeypatch, db)

    with pytest.raises(HTTPException):
        _corre(copiar_para_venda(
            "doc-1", PedidoCopiar(caixa_id="caixa-1"),
            operador=_operador(dispositivo_id="pc-1")))
    assert [v for v in db[COLECOES["vendas"]]._documentos
            if v.get("estado") == "aberta"] == []
