"""**«Mais Vendidos» e «Mais Rentáveis»** — os dois cartões que estiveram
mudos desde que o painel existe.

Devolviam lista vazia FIXA, com um comentário a explicar porquê: o
`fat_documentos` guarda o documento da venda e não as linhas dos artigos. O
comentário estava certo quando foi escrito e ficou desactualizado sem ninguém
dar por isso — o POS próprio entrou ao serviço, as linhas passaram a existir
em `fat_vendas`, e o motor dos Relatórios já as sabia ler. O painel é que
continuou a dizer «Sem informação disponível» com as faturas a entrarem na
Autoridade Tributária ao lado.

**As três coisas que estes testes prendem:**

1. **os dois cartões e o cartão «Hoje» somam as MESMAS faturas.** São dois
   caminhos diferentes até ao mesmo dinheiro — um pelo `total_bruto` do
   documento, outro pelas linhas da venda — e o dia em que discordarem, o
   painel mostra um total e um top que não batem, sem nenhum deles parecer
   errado;
2. **um artigo sem preço de custo não entra no top da margem.** Entrar com
   custo zero fazia o açaí parecer lucro inteiro: é a mentira mais cara que
   este painel podia contar, e a única que ninguém contestaria;
3. **ordenam-se por coisas DIFERENTES** — quantidade e resultado. Ordenados os
   dois por euros, eram a mesma lista duas vezes.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from faturacao import dashboard as dashboard_mod
from faturacao import relatorios as rel_mod
from faturacao.dashboard import (
    TOP_ARTIGOS, calcula_dashboard, obter_dashboard, topos_de_artigos,
)
from faturacao.db import COLECOES

from .test_relatorios_rota import _DOC_FS, _DOC_NC, _NOTA, _PRODUTOS, _VENDA, _linha
from .test_venda import ColeccaoFalsa, DbFalsa

# O relógio destes testes. As faturas das fixtures são de 10 de agosto ao
# meio-dia UTC; "agora" é o fim desse mesmo dia em Lisboa, para elas caírem
# todas dentro do "hoje" do painel.
AGORA = datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc)


def _corre(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# --- a aritmética, sem base de dados nenhuma ---------------------------------

def _artigo(nome, quantidade, bruto_c, liquido_c, custo_c):
    return {"produto_id": "p-" + nome, "produto_nome": nome,
            "categoria_id": "cat", "categoria_nome": "Cat",
            "quantidade": quantidade, "bruto_c": bruto_c,
            "liquido_c": liquido_c, "custo_c": custo_c}


def _evento(artigos, id_="d1", tipo="FS"):
    return {
        "id": id_, "tipo": tipo, "quando": AGORA,
        "loja_id": "loja-1", "loja_nome": "Alfragide",
        "cliente_nif": None, "cliente_nome": None,
        "operador_id": "op-1", "operador_nome": "Emily",
        "bruto_c": sum(a["bruto_c"] for a in artigos),
        "liquido_c": sum(a["liquido_c"] for a in artigos),
        "custo_c": (None if any(a["custo_c"] is None for a in artigos)
                    else sum(a["custo_c"] for a in artigos)),
        "quantidade": sum(a["quantidade"] for a in artigos),
        "artigos": artigos,
    }


def test_sem_eventos_os_dois_cartoes_ficam_vazios():
    """O caso de sempre — e continua a ser o certo. Um painel sem vendas não
    inventa um top; o ecrã mostra o estado vazio."""
    topos = topos_de_artigos([])
    assert topos["mais_vendidos"] == []
    assert topos["mais_rentaveis"] == []
    assert topos["artigos_sem_custo"] == 0
    assert topos["artigos_vendidos"] == 0


def test_os_mais_vendidos_ordenam_se_pela_QUANTIDADE_e_nao_pelo_dinheiro():
    """A pergunta do cartão é «o que é que mais sai da loja?».

    O açaí caro vendeu 2 e rendeu 40 €; a água barata vendeu 9 e rendeu 9 €.
    Ordenado por dinheiro, a água nunca aparecia — e é ela que se acaba no
    frigorífico ao sábado."""
    topos = topos_de_artigos([_evento([
        _artigo("Açaí", 2, 4000, 3540, 1600),
        _artigo("Água", 9, 900, 732, 270),
    ])])
    assert [a["nome"] for a in topos["mais_vendidos"]] == ["Água", "Açaí"]
    assert topos["mais_vendidos"][0]["quantidade"] == 9
    assert topos["mais_vendidos"][0]["valor"] == 9.00


def test_os_mais_rentaveis_ordenam_se_pelo_RESULTADO_e_nao_pela_quantidade():
    """A outra pergunta: «o que é que dá mais dinheiro ao fim do dia?».

    A água vende-se nove vezes e deixa 4,62 €; o açaí vende-se duas e deixa
    19,40 €. São listas diferentes de propósito."""
    topos = topos_de_artigos([_evento([
        _artigo("Açaí", 2, 4000, 3540, 1600),
        _artigo("Água", 9, 900, 732, 270),
    ])])
    assert [a["nome"] for a in topos["mais_rentaveis"]] == ["Açaí", "Água"]
    assert topos["mais_rentaveis"][0]["resultado"] == 19.40
    assert topos["mais_rentaveis"][1]["resultado"] == 4.62


def test_o_artigo_SEM_PRECO_DE_CUSTO_fica_fora_da_margem_e_conta_se():
    """A regra de ouro: sem custo não há margem, e um zero ali era lucro
    inventado. O artigo continua no «Mais Vendidos» — vendeu-se de facto —
    e some do «Mais Rentáveis», que é onde a falta importa."""
    topos = topos_de_artigos([_evento([
        _artigo("Açaí", 2, 4000, 3540, 1600),
        _artigo("Talheres", 5, 500, 407, None),
    ])])
    assert [a["nome"] for a in topos["mais_vendidos"]] == ["Talheres", "Açaí"]
    assert [a["nome"] for a in topos["mais_rentaveis"]] == ["Açaí"]
    assert topos["artigos_sem_custo"] == 1
    assert topos["artigos_vendidos"] == 2


def test_com_NENHUM_custo_preenchido_o_cartao_da_margem_fica_vazio_MAS_diz_quantos():
    """É o estado real das cinco lojas no dia em que isto se escreveu: 0 de 33
    artigos com preço de custo. Sem o `artigos_sem_custo`, o ecrã só podia
    dizer «Sem informação disponível» — que não explica nada e não se resolve.
    """
    topos = topos_de_artigos([_evento([
        _artigo("Açaí", 2, 4000, 3540, None),
        _artigo("Água", 9, 900, 732, None),
    ])])
    assert topos["mais_rentaveis"] == []
    assert topos["artigos_sem_custo"] == 2
    assert len(topos["mais_vendidos"]) == 2


def test_a_margem_e_sempre_SEM_IVA_mesmo_com_o_painel_a_mostrar_o_bruto():
    """O IVA não é dinheiro do negócio — é dinheiro do Estado a passar pela
    caixa. Uma margem calculada por cima dele dizia que cada açaí dá mais 13%
    do que dá. O `com_iva` só muda a COLUNA DE VENDAS."""
    eventos = [_evento([_artigo("Açaí", 1, 2000, 1770, 800)])]
    com = topos_de_artigos(eventos, com_iva=True)
    sem = topos_de_artigos(eventos, com_iva=False)
    assert com["mais_vendidos"][0]["valor"] == 20.00
    assert sem["mais_vendidos"][0]["valor"] == 17.70
    assert com["mais_rentaveis"][0]["resultado"] == sem["mais_rentaveis"][0]["resultado"] == 9.70
    # 9,70 sobre 17,70 de vendas — a percentagem sai da mesma base.
    assert com["mais_rentaveis"][0]["margem_pct"] == 54.8


def test_a_nota_de_credito_SUBTRAI_do_artigo_devolvido():
    """Uma devolução não é uma venda. Somada como positiva, o artigo devolvido
    subia no top — o painel premiava o que correu mal."""
    vendidos = topos_de_artigos([
        _evento([_artigo("Açaí", 3, 6000, 5310, 2400)], id_="d1"),
        _evento([_artigo("Açaí", 1, 2000, 1770, 800)], id_="d2", tipo="NC"),
    ])["mais_vendidos"]
    assert vendidos[0]["quantidade"] == 2
    assert vendidos[0]["valor"] == 40.00


def test_um_artigo_TODO_devolvido_nao_aparece_como_mais_vendido():
    """Vendeu um, devolveram-no: a quantidade líquida é zero. Um zero no topo
    dos mais vendidos é ruído — e um negativo seria pior."""
    topos = topos_de_artigos([
        _evento([_artigo("Açaí", 1, 2000, 1770, 800)], id_="d1"),
        _evento([_artigo("Açaí", 1, 2000, 1770, 800)], id_="d2", tipo="NC"),
    ])
    assert topos["mais_vendidos"] == []


def test_cada_cartao_para_nas_cinco_linhas_que_o_ecra_mostra():
    topos = topos_de_artigos([_evento([
        _artigo("Artigo %d" % i, i + 1, 100 * (i + 1), 90 * (i + 1), 10 * (i + 1))
        for i in range(9)
    ])])
    assert len(topos["mais_vendidos"]) == TOP_ARTIGOS == 5
    assert len(topos["mais_rentaveis"]) == TOP_ARTIGOS
    # O corte é pelo topo e não pelo fundo: o mais vendido de todos tem de lá
    # estar. Uma fatia ao contrário passava num teste que só contasse linhas.
    assert topos["mais_vendidos"][0]["nome"] == "Artigo 8"


def test_dois_artigos_com_a_MESMA_quantidade_nao_trocam_de_lugar():
    """Sem desempate, a ordem vinha de um dicionário e o cartão mudava sozinho
    de recarga para recarga — com os mesmos números lá dentro."""
    eventos = [_evento([
        _artigo("Bola", 3, 300, 265, 100),
        _artigo("Anel", 3, 900, 796, 300),
    ])]
    # Duas vezes, com a lista de artigos ao contrário: a saída tem de ser a
    # mesma. O dinheiro desempata (Anel rendeu mais), e não a ordem de entrada.
    primeira = [a["nome"] for a in topos_de_artigos(eventos)["mais_vendidos"]]
    eventos[0]["artigos"].reverse()
    assert primeira == [a["nome"] for a in topos_de_artigos(eventos)["mais_vendidos"]]
    assert primeira == ["Anel", "Bola"]


def test_calcula_dashboard_sem_eventos_nao_inventa_um_top():
    """A função é PURA e não sabe ir buscar linhas a lado nenhum. Chamada só
    com documentos — como qualquer teste dos cartões faz — os dois cartões de
    artigos ficam vazios em vez de estimarem um top a partir do total."""
    doc = dict(_DOC_FS)
    resultado = calcula_dashboard([doc], [{"id": "loja-1", "nome": "Alfragide"}], AGORA)
    assert resultado["mais_vendidos"] == []
    assert resultado["mais_rentaveis"] == []
    assert resultado["cartoes"]["hoje"]["valor"] == 11.35


# --- da base de dados até ao cartão -----------------------------------------

def _db(monkeypatch, documentos=None, notas=None, produtos=None):
    """A mesma cena dos testes dos Relatórios: uma fatura com um açaí a 10,20 €
    (IVA 13%, custo 4,00 €) e uma Coca-Cola a 1,15 € (IVA 23%, SEM custo)."""
    registo = []
    db = DbFalsa({
        COLECOES["documentos"]: ColeccaoFalsa(
            registo, documentos if documentos is not None else [dict(_DOC_FS)]),
        COLECOES["vendas"]: ColeccaoFalsa(registo, [dict(_VENDA)]),
        COLECOES["notas_credito"]: ColeccaoFalsa(registo, notas or []),
        COLECOES["produtos"]: ColeccaoFalsa(
            registo, [dict(p) for p in (produtos or _PRODUTOS)]),
        COLECOES["categorias"]: ColeccaoFalsa(registo, [
            {"id": "cat-1", "nome": "Venda ao Público"}, {"id": "cat-2", "nome": "Bebidas"}]),
        COLECOES["lojas"]: ColeccaoFalsa(registo, [{"id": "loja-1", "nome": "Alfragide"}]),
        COLECOES["utilizadores"]: ColeccaoFalsa(registo, []),
        COLECOES["clientes"]: ColeccaoFalsa(registo, []),
    })
    monkeypatch.setattr(dashboard_mod, "obter_db", lambda: db)
    monkeypatch.setattr(rel_mod, "obter_db", lambda: db)
    monkeypatch.setattr(dashboard_mod, "datetime", _RelogioParado)
    return db


class _RelogioParado(datetime):
    """`datetime.now(tz)` congelado no dia das faturas — o resto do módulo
    continua a usar o `datetime` verdadeiro (é uma subclasse)."""
    @classmethod
    def now(cls, tz=None):
        return AGORA.astimezone(tz) if tz else AGORA


def test_o_endpoint_acende_os_dois_cartoes_a_partir_das_LINHAS_da_venda(monkeypatch):
    _db(monkeypatch)
    r = _corre(obter_dashboard(com_iva=True, _={}))

    assert [a["nome"] for a in r["mais_vendidos"]] == ["Açaí Regular", "Coca-Cola"]
    assert r["mais_vendidos"][0]["valor"] == 10.20
    assert r["mais_vendidos"][0]["quantidade"] == 1
    # Só o açaí tem preço de custo (4,00 €); 9,03 € de vendas sem IVA menos
    # 4,00 € dão 5,03 € de margem. A Coca-Cola não tem custo e fica de fora.
    assert [a["nome"] for a in r["mais_rentaveis"]] == ["Açaí Regular"]
    assert r["mais_rentaveis"][0]["resultado"] == 5.03
    assert r["artigos_sem_custo"] == 1
    assert r["artigos_vendidos"] == 2


def test_o_TOTAL_dos_artigos_bate_com_o_cartao_HOJE(monkeypatch):
    """**O teste que interessa.** São dois caminhos diferentes até ao mesmo
    dinheiro: o cartão soma o `total_bruto` do documento, o top soma as linhas
    da venda uma a uma. O dia em que discordarem, o dono vê um total e um top
    que não batem — e nenhum dos dois parece errado."""
    _db(monkeypatch)
    r = _corre(obter_dashboard(com_iva=True, _={}))
    assert sum(a["valor"] for a in r["mais_vendidos"]) == r["cartoes"]["hoje"]["valor"]


def test_a_fatura_de_ONTEM_nao_entra_no_top_de_HOJE(monkeypatch):
    """Os cartões dizem «Hoje» e têm de o cumprir. O documento vem da mesma
    consulta que alimenta os gráficos — essa vai até ao ano passado."""
    ontem = dict(_DOC_FS, id="d-ontem", emitido_em="2026-08-09T12:00:00+00:00")
    _db(monkeypatch, documentos=[ontem])
    r = _corre(obter_dashboard(com_iva=True, _={}))
    assert r["mais_vendidos"] == []
    assert r["cartoes"]["hoje"]["valor"] == 0.0


def test_uma_fatura_ANULADA_nao_poe_artigos_no_top(monkeypatch):
    """O `_valor_documento` já lhe dava zero euros. Sem o mesmo crivo nos
    artigos, o dinheiro dela desaparecia do cartão e os artigos ficavam — um
    top de coisas que ninguém comprou."""
    _db(monkeypatch, documentos=[dict(_DOC_FS, anulado=True)])
    r = _corre(obter_dashboard(com_iva=True, _={}))
    assert r["mais_vendidos"] == []
    assert r["cartoes"]["hoje"]["valor"] == 0.0


def test_a_nota_de_credito_do_dia_desconta_no_top(monkeypatch):
    """A nota credita SÓ a Coca-Cola (a linha de índice 1 da fatura). Ela sai
    do top; o açaí fica."""
    _db(monkeypatch, documentos=[dict(_DOC_FS), dict(_DOC_NC)], notas=[dict(_NOTA)])
    r = _corre(obter_dashboard(com_iva=True, _={}))
    assert [a["nome"] for a in r["mais_vendidos"]] == ["Açaí Regular"]
    assert sum(a["valor"] for a in r["mais_vendidos"]) == r["cartoes"]["hoje"]["valor"] == 10.20


def test_com_os_custos_TODOS_preenchidos_o_cartao_da_margem_enche(monkeypatch):
    """O que o dono vai ver assim que preencher os preços de custo — e a prova
    de que o cartão acende sozinho, sem mais nenhuma mudança de código."""
    _db(monkeypatch, produtos=[
        {"id": "p-acai", "nome": "Açaí Regular", "categoria_id": "cat-1", "preco_custo": 4.00},
        {"id": "p-cola", "nome": "Coca-Cola", "categoria_id": "cat-2", "preco_custo": 0.40},
    ])
    r = _corre(obter_dashboard(com_iva=True, _={}))
    assert [a["nome"] for a in r["mais_rentaveis"]] == ["Açaí Regular", "Coca-Cola"]
    assert r["mais_rentaveis"][1]["resultado"] == 0.53
    assert r["artigos_sem_custo"] == 0


# --- uma venda estragada não leva o painel com ela ---------------------------

def test_uma_venda_QUE_NAO_SE_REPARTE_nao_derruba_o_painel(monkeypatch):
    """Repartir a fatura pelos artigos passa por `_linha_vendus`, que levanta
    um 422 numa linha com dados impossíveis — um produto que ficou sem preço.

    Este é o PRIMEIRO ecrã do módulo, aberto todos os dias com cinco lojas a
    faturar: uma venda estragada de há meses não pode tirá-lo do ar. É o mesmo
    travão que `fiscal._total_da_venda` já leva."""
    partida = dict(_VENDA, linhas=[dict(_linha("l1", "p-acai", "Açaí Regular", 10.20),
                                        produto_preco=None, preco_override=None)])
    db = _db(monkeypatch)
    db._coleccoes[COLECOES["vendas"]] = ColeccaoFalsa([], [partida])

    r = _corre(obter_dashboard(com_iva=True, _={}))

    assert r["cartoes"]["hoje"]["valor"] == 11.35, "o dinheiro do cartão não se perde"
    assert r["mais_vendidos"] == []
    # E DIZ-SE. O dinheiro está no cartão «Hoje» e não está no top: dois
    # números certos lado a lado, sem legenda, dão uma leitura falsa.
    assert r["documentos_por_repartir"] == 1


def test_com_tudo_saudavel_nao_ha_nada_por_repartir(monkeypatch):
    _db(monkeypatch)
    assert _corre(obter_dashboard(com_iva=True, _={}))["documentos_por_repartir"] == 0


# --- o que uma devolução faz ao cartão da margem -----------------------------

def test_um_artigo_TODO_devolvido_nao_entra_no_cartao_da_margem():
    """Vendeu um, devolveram-no: margem 0,00 € sobre vendas de 0,00 €. Uma
    linha a zero num top de rentabilidade é ruído — e a percentagem nem se
    consegue calcular."""
    topos = topos_de_artigos([
        _evento([_artigo("Açaí", 1, 2000, 1770, 800)], id_="d1"),
        _evento([_artigo("Açaí", 1, 2000, 1770, 800)], id_="d2", tipo="NC"),
    ])
    assert topos["mais_rentaveis"] == []


def test_devolver_MAIS_do_que_se_vendeu_hoje_nao_poe_um_prejuizo_no_topo():
    """A devolução de ontem entra no dia de hoje. Sem o crivo, o cartão «Mais
    Rentáveis» abria com uma margem negativa em primeiro lugar."""
    topos = topos_de_artigos([
        _evento([_artigo("Açaí", 1, 2000, 1770, 800)], id_="d1"),
        _evento([_artigo("Açaí", 2, 4000, 3540, 1600)], id_="d2", tipo="NC"),
    ])
    assert topos["mais_rentaveis"] == []
    assert topos["mais_vendidos"] == []


def test_um_artigo_VENDIDO_ABAIXO_DO_CUSTO_continua_a_aparecer():
    """O crivo é `quantidade > 0` e não `resultado > 0`, de propósito: vender
    a perder é a única coisa que este cartão não pode esconder. Fica no fundo
    da lista, com o prejuízo escrito."""
    topos = topos_de_artigos([_evento([
        _artigo("Açaí", 2, 4000, 3540, 1600),
        _artigo("Promoção", 1, 500, 442, 900),
    ])])
    assert [a["nome"] for a in topos["mais_rentaveis"]] == ["Açaí", "Promoção"]
    assert topos["mais_rentaveis"][-1]["resultado"] == -4.58


# --- «Vinte e cinco açaís de qual tamanho?» -----------------------------------

def _com_tamanho(nome, tamanho, quantidade, bruto_c, liquido_c, custo_c):
    a = _artigo(nome, quantidade, bruto_c, liquido_c, custo_c)
    a["variante"] = tamanho
    return a


def test_o_mais_vendido_reparte_se_pelos_TAMANHOS(tmp_path=None):
    """O dono, a olhar para o cartão: «no mais vendido devia ter também os
    tamanhos, pois só está Açaí».

    No nosso catálogo o açaí é UM produto e o tamanho é uma personalização
    dele. «Açaí 25» é verdade e não responde a nada — vinte e cinco de qual?"""
    topos = topos_de_artigos([_evento([
        _com_tamanho("Açaí", "Regular", 12, 10788, 9547, 4800),
        _com_tamanho("Açaí", "Mini", 7, 4095, 3624, 2800),
        _com_tamanho("Açaí", "Supreme", 4, 5640, 4991, 1600),
    ])])
    linha = topos["mais_vendidos"][0]
    assert linha["quantidade"] == 23
    assert [t["nome"] for t in linha["tamanhos"]] == ["Regular", "Mini", "Supreme"]
    assert [t["quantidade"] for t in linha["tamanhos"]] == [12, 7, 4]


def test_as_parcelas_SOMAM_a_quantidade_da_linha():
    """**A igualdade que interessa.** São duas somas sobre os mesmos artigos —
    a de `agregar` e esta — e o dia em que divergirem o cartão mostra um total
    e umas parcelas que não batem, sem nenhum deles parecer errado."""
    topos = topos_de_artigos([_evento([
        _com_tamanho("Açaí", "Regular", 12, 10788, 9547, 4800),
        _com_tamanho("Açaí", "Mini", 7, 4095, 3624, 2800),
    ])])
    linha = topos["mais_vendidos"][0]
    assert sum(t["quantidade"] for t in linha["tamanhos"]) == linha["quantidade"]


def test_uma_DEVOLUCAO_desconta_no_tamanho_que_foi_devolvido():
    """Somada como positiva, o tamanho devolvido subia no cartão — o painel
    premiava o que correu mal. E descontada no tamanho errado, o Mini crescia
    e o Supreme ficava por descontar."""
    topos = topos_de_artigos([
        _evento([_com_tamanho("Açaí", "Regular", 5, 4495, 3978, 2000),
                 _com_tamanho("Açaí", "Mini", 3, 1755, 1553, 1200)], id_="d1"),
        _evento([_com_tamanho("Açaí", "Regular", 2, 1798, 1591, 800)],
                id_="d2", tipo="NC"),
    ])
    linha = topos["mais_vendidos"][0]
    assert {t["nome"]: t["quantidade"] for t in linha["tamanhos"]} == {
        "Regular": 3, "Mini": 3}
    assert sum(t["quantidade"] for t in linha["tamanhos"]) == linha["quantidade"] == 6


def test_um_tamanho_TODO_devolvido_desaparece_das_parcelas():
    """Zero não é uma parcela — é ruído por baixo de uma linha que já é curta."""
    topos = topos_de_artigos([
        _evento([_com_tamanho("Açaí", "Regular", 5, 4495, 3978, 2000),
                 _com_tamanho("Açaí", "Mini", 1, 585, 518, 400)], id_="d1"),
        _evento([_com_tamanho("Açaí", "Mini", 1, 585, 518, 400)], id_="d2", tipo="NC"),
    ])
    tamanhos = topos["mais_vendidos"][0]["tamanhos"]
    assert [t["nome"] for t in tamanhos] == ["Regular"]


def test_um_artigo_SEM_tamanho_nao_ganha_parcela_nenhuma():
    """Uma água não tem tamanho. Uma parcela «(sem tamanho)» debaixo de cada
    linha era ruído em todas as linhas menos uma."""
    topos = topos_de_artigos([_evento([_artigo("Água 50cl", 3, 435, 385, 120)])])
    assert topos["mais_vendidos"][0]["tamanhos"] == []


def test_os_tamanhos_de_um_produto_NAO_aparecem_debaixo_de_outro():
    """A repartição é por produto. Sem isso, os tamanhos do açaí apareciam
    debaixo da água — e ninguém percebia porquê."""
    topos = topos_de_artigos([_evento([
        _com_tamanho("Açaí", "Mini", 2, 1170, 1035, 800),
        _artigo("Água 50cl", 9, 1305, 1155, 360),
    ])])
    por_nome = {a["nome"]: a for a in topos["mais_vendidos"]}
    assert por_nome["Água 50cl"]["tamanhos"] == []
    assert [t["nome"] for t in por_nome["Açaí"]["tamanhos"]] == ["Mini"]


def test_o_TAMANHO_chega_ao_cartao_a_partir_da_LINHA_DA_VENDA(monkeypatch):
    """De ponta a ponta: a opção escolhida ao balcão, carimbada na linha, e o
    tamanho a aparecer no cartão.

    O elo que isto prende é o `nome_grupo` — é ele que diz que «Mini» pertence
    ao grupo do tamanho e não aos toppings. Sem ele (linhas gravadas antes de
    existir), o artigo fica sem tamanho, e não com um tamanho adivinhado pelo
    nome da opção."""
    venda = dict(_VENDA, linhas=[dict(
        _linha("l1", "p-acai", "Açaí Regular", 10.20),
        # O topping vem PRIMEIRO de propósito: sem a pergunta «este grupo é
        # de tamanho?», o cartão dizia que se venderam 1 «Nutella» de açaí.
        opcoes=[{"id": "o-nut", "grupo_id": "g-top", "nome": "Nutella",
                 "preco": 0, "nome_grupo": "Toppings", "sai_na_fatura": True},
                {"id": "o-mini", "grupo_id": "g-tam", "nome": "Mini",
                 "preco": 0, "nome_grupo": "Tamanho", "sai_na_fatura": True}],
    )])
    db = _db(monkeypatch)
    db._coleccoes[COLECOES["vendas"]] = ColeccaoFalsa([], [venda])

    r = _corre(obter_dashboard(com_iva=True, _={}))

    acai = next(a for a in r["mais_vendidos"] if a["nome"] == "Açaí Regular")
    assert [t["nome"] for t in acai["tamanhos"]] == ["Mini"]
    assert acai["tamanhos"][0]["quantidade"] == acai["quantidade"] == 1


def test_a_NOTA_DE_CREDITO_desconta_no_TAMANHO_que_a_fatura_vendeu(monkeypatch):
    """A nota não tem opções nenhumas: as linhas dela só apontam para o índice
    da linha na fatura de origem. O tamanho tem de sair DE LÁ.

    Sem isso, a devolução descontava a quantidade do produto mas não a de
    nenhum tamanho — as parcelas deixavam de somar o total, e o cartão
    mostrava «Açaí 0» com «Mini 1» por baixo."""
    venda = dict(_VENDA, linhas=[dict(
        _linha("l1", "p-acai", "Açaí Regular", 10.20, quantidade=3),
        opcoes=[{"id": "o-mini", "grupo_id": "g-tam", "nome": "Mini",
                 "preco": 0, "nome_grupo": "Tamanho", "sai_na_fatura": True}],
    )])
    nota = dict(_NOTA, linhas=[{"indice": 1, "titulo": "Açaí Regular",
                                "tax_id": "INT", "quantidade": 1, "total": 10.20}])
    db = _db(monkeypatch, documentos=[dict(_DOC_FS), dict(_DOC_NC)], notas=[nota])
    db._coleccoes[COLECOES["vendas"]] = ColeccaoFalsa([], [venda])

    r = _corre(obter_dashboard(com_iva=True, _={}))

    # Vendeu três Minis, devolveu um: ficam DOIS — e a parcela tem de descer
    # com o total. Escrito com três e não com um de propósito: com um, a linha
    # inteira desaparecia e o teste ficava verde mesmo que a nota não tocasse
    # em tamanho nenhum.
    acai = next(a for a in r["mais_vendidos"] if a["nome"] == "Açaí Regular")
    assert acai["quantidade"] == 2
    assert [(t["nome"], t["quantidade"]) for t in acai["tamanhos"]] == [("Mini", 2)]
