"""**Os relatórios: nove vistas, uma soma.**

O dono mandou os prints dos nove relatórios do Vendus. Eles são a mesma tabela
com a primeira coluna trocada — e é isso que este ficheiro guarda: que as nove
vistas do MESMO intervalo dão exactamente o mesmo total. Nove somas escritas em
nove sítios acabam a discordar, e a primeira vez que isso acontece é o dono a
perguntar qual delas está certa.

E guarda as três regras que decidem se os números servem:

1. a **nota de crédito subtrai** no dinheiro e conta à parte;
2. a hora é a de **Lisboa** — em UTC, a venda das 00h30 cai no dia anterior e o
   pico das 17h aparece às 16h;
3. um artigo **sem preço de custo não vale zero**: a linha fica sem Custos e
   sem Resultado, porque um zero ali faz o lucro parecer total.

O núcleo é puro: estas contas correm sem Mongo, sem HTTP e sem relógio.
"""
import pytest

from faturacao.relatorios import (
    DIMENSOES, agregar, centimos, em_lisboa, serie_diaria,
)


def _artigo(produto_id, nome, categoria_id, categoria_nome, quantidade,
            bruto_c, liquido_c, custo_c):
    return {
        "produto_id": produto_id, "produto_nome": nome,
        "categoria_id": categoria_id, "categoria_nome": categoria_nome,
        "quantidade": quantidade, "bruto_c": bruto_c, "liquido_c": liquido_c,
        "custo_c": custo_c,
    }


def _evento(id_, quando, artigos, tipo="FS", loja="loja-1", loja_nome="Alfragide",
            operador="op-1", operador_nome="Emily", nif=None, nome_cliente=None):
    return {
        "id": id_, "tipo": tipo, "quando": em_lisboa(quando),
        "loja_id": loja, "loja_nome": loja_nome,
        "operador_id": operador, "operador_nome": operador_nome,
        "cliente_nif": nif, "cliente_nome": nome_cliente,
        "bruto_c": sum(a["bruto_c"] for a in artigos),
        "liquido_c": sum(a["liquido_c"] for a in artigos),
        "custo_c": (None if any(a["custo_c"] is None for a in artigos)
                    else sum(a["custo_c"] for a in artigos)),
        "quantidade": sum(a["quantidade"] for a in artigos),
        "artigos": artigos,
    }


_ACAI = dict(produto_id="p-acai", nome="Açaí Regular", categoria_id="cat-1",
             categoria_nome="Venda ao Público")
_COLA = dict(produto_id="p-cola", nome="Coca-Cola", categoria_id="cat-2",
             categoria_nome="Bebidas")


def _fatura_do_acai_e_da_cola(id_, quando, tipo="FS"):
    return _evento(id_, quando, [
        _artigo(**_ACAI, quantidade=1, bruto_c=1020, liquido_c=903, custo_c=400),
        _artigo(**_COLA, quantidade=1, bruto_c=115, liquido_c=93, custo_c=50),
    ], tipo=tipo)


# --- As nove vistas somam o mesmo ---------------------------------------------


@pytest.mark.parametrize("dimensao", DIMENSOES)
def test_todas_as_vistas_dao_o_MESMO_total(dimensao):
    """A promessa que os nove relatórios fazem em conjunto: mudam de eixo, não
    de aritmética."""
    eventos = [
        _fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d2", "2026-08-11T20:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d3", "2026-08-11T21:00:00+00:00", tipo="NC"),
    ]
    total = agregar(eventos, dimensao)["total"]
    assert total["bruto"] == 11.35, dimensao
    assert total["liquido"] == 9.96, dimensao
    assert total["faturas"] == 2 and total["rectificacoes"] == 1, dimensao


def test_as_linhas_somam_a_linha_TOTAL():
    eventos = [
        _fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d2", "2026-08-11T20:00:00+00:00"),
    ]
    r = agregar(eventos, "produto")
    assert round(sum(l["bruto"] for l in r["linhas"]), 2) == r["total"]["bruto"]
    assert round(sum(l["liquido"] for l in r["linhas"]), 2) == r["total"]["liquido"]


# --- A nota de crédito --------------------------------------------------------


def test_a_nota_de_credito_SUBTRAI_e_conta_a_parte():
    eventos = [
        _fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d2", "2026-08-10T13:00:00+00:00", tipo="NC"),
    ]
    r = agregar(eventos, "loja")
    assert r["total"]["bruto"] == 0.0
    assert r["total"]["faturas"] == 1
    assert r["total"]["rectificacoes"] == 1, (
        "uma rectificação não se soma às vendas — são duas contagens, como o "
        "rodapé dos relatórios do Vendus diz"
    )


def test_uma_devolucao_baixa_a_QUANTIDADE_do_artigo():
    eventos = [
        _evento("d1", "2026-08-10T12:00:00+00:00",
                [_artigo(**_ACAI, quantidade=3, bruto_c=3060, liquido_c=2709, custo_c=1200)]),
        _evento("d2", "2026-08-10T13:00:00+00:00",
                [_artigo(**_ACAI, quantidade=1, bruto_c=1020, liquido_c=903, custo_c=400)],
                tipo="NC"),
    ]
    linha = agregar(eventos, "produto")["linhas"][0]
    assert linha["quantidade"] == 2
    assert linha["bruto"] == 20.40


# --- O fuso -------------------------------------------------------------------


def test_a_venda_das_00h30_de_LISBOA_cai_no_dia_certo():
    """23h30 UTC do dia 31 são 00h30 do dia 1 em Lisboa. Agrupado em cru, o
    dia 1 do mês aparecia sempre a menos."""
    eventos = [
        _fatura_do_acai_e_da_cola("d1", "2026-07-31T23:30:00+00:00"),
        _fatura_do_acai_e_da_cola("d2", "2026-08-01T10:00:00+00:00"),
    ]
    r = agregar(eventos, "dia")
    assert [l["rotulo"] for l in r["linhas"]] == ["2026-08-01"]
    assert r["linhas"][0]["faturas"] == 2


def test_a_hora_e_a_do_RELOGIO_da_loja():
    """O pico das 17h tem de aparecer às 17h — em Agosto, Lisboa está uma hora
    à frente do UTC."""
    eventos = [_fatura_do_acai_e_da_cola("d1", "2026-08-10T16:00:00+00:00")]
    assert agregar(eventos, "hora")["linhas"][0]["rotulo"] == "17h"


def test_os_dias_da_semana_sao_os_de_lisboa():
    # 2026-08-10 é uma segunda-feira.
    eventos = [_fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00")]
    assert agregar(eventos, "dia_semana")["linhas"][0]["rotulo"] == "Segunda-feira"


def test_o_mes_le_se_por_extenso():
    eventos = [_fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00")]
    assert agregar(eventos, "mes")["linhas"][0]["rotulo"] == "Agosto"


# --- Os custos ----------------------------------------------------------------


def test_um_artigo_SEM_custo_nao_vale_zero():
    """Um zero ali fazia o Resultado parecer lucro inteiro — a mentira mais
    cara que um relatório pode contar."""
    eventos = [_evento("d1", "2026-08-10T12:00:00+00:00", [
        _artigo(**_ACAI, quantidade=1, bruto_c=1020, liquido_c=903, custo_c=None),
    ])]
    linha = agregar(eventos, "produto")["linhas"][0]
    assert linha["custo"] is None
    assert linha["resultado"] is None
    assert linha["custo_incompleto"] is True
    assert linha["bruto"] == 10.20, "o que se vendeu continua a saber-se"


def test_o_custo_de_UM_artigo_nao_estraga_a_linha_do_outro():
    eventos = [_evento("d1", "2026-08-10T12:00:00+00:00", [
        _artigo(**_ACAI, quantidade=1, bruto_c=1020, liquido_c=903, custo_c=400),
        _artigo(**_COLA, quantidade=1, bruto_c=115, liquido_c=93, custo_c=None),
    ])]
    r = agregar(eventos, "produto")
    por_rotulo = {l["rotulo"]: l for l in r["linhas"]}
    assert por_rotulo["Açaí Regular"]["resultado"] == 5.03
    assert por_rotulo["Coca-Cola"]["resultado"] is None
    assert r["total"]["resultado"] is None, "o total herda a dúvida"


def test_o_resultado_e_as_vendas_SEM_iva_menos_o_custo():
    eventos = [_evento("d1", "2026-08-10T12:00:00+00:00", [
        _artigo(**_ACAI, quantidade=2, bruto_c=2040, liquido_c=1806, custo_c=800),
    ])]
    linha = agregar(eventos, "produto")["linhas"][0]
    assert linha["liquido"] == 18.06 and linha["custo"] == 8.00
    assert linha["resultado"] == 10.06


# --- As contagens -------------------------------------------------------------


def test_no_de_vendas_de_um_produto_conta_FATURAS_e_nao_linhas():
    """O print do dono: 967 de quantidade para 774 vendas. Uma fatura com o
    mesmo artigo duas vezes é UMA venda."""
    eventos = [_evento("d1", "2026-08-10T12:00:00+00:00", [
        _artigo(**_ACAI, quantidade=1, bruto_c=1020, liquido_c=903, custo_c=400),
        _artigo(**_ACAI, quantidade=1, bruto_c=1020, liquido_c=903, custo_c=400),
    ])]
    linha = agregar(eventos, "produto")["linhas"][0]
    assert linha["quantidade"] == 2
    assert linha["faturas"] == 1


# --- A ordem e o que se mostra ------------------------------------------------


def test_as_vistas_de_dinheiro_ordenam_pelo_maior():
    eventos = [_fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00")]
    assert [l["rotulo"] for l in agregar(eventos, "produto")["linhas"]] == [
        "Açaí Regular", "Coca-Cola"]


def test_as_vistas_de_TEMPO_ordenam_pelo_tempo():
    eventos = [
        _fatura_do_acai_e_da_cola("d1", "2026-08-12T12:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d2", "2026-08-10T12:00:00+00:00"),
    ]
    assert [l["rotulo"] for l in agregar(eventos, "dia")["linhas"]] == [
        "2026-08-10", "2026-08-12"]


@pytest.mark.parametrize("dimensao, tem", [
    ("produto", True), ("categoria", True), ("cliente", True), ("dia", True),
    ("loja", False), ("utilizador", False), ("hora", False),
    ("dia_semana", False), ("mes", False),
])
def test_a_coluna_quantidade_aparece_onde_os_prints_a_mostram(dimensao, tem):
    eventos = [_fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00")]
    linha = agregar(eventos, dimensao)["linhas"][0]
    assert (linha["quantidade"] is not None) is tem, dimensao


def test_um_cliente_sem_NIF_le_se_Consumidor_Final():
    eventos = [_fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00")]
    assert agregar(eventos, "cliente")["linhas"][0]["rotulo"] == "Consumidor Final"


def test_uma_dimensao_inventada_rebenta_em_vez_de_devolver_vazio():
    with pytest.raises(ValueError):
        agregar([], "cor-do-copo")


# --- O gráfico ----------------------------------------------------------------


def test_a_serie_diaria_soma_por_dia_de_lisboa_com_as_NC_a_descontar():
    eventos = [
        _fatura_do_acai_e_da_cola("d1", "2026-08-10T12:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d2", "2026-08-10T13:00:00+00:00"),
        _fatura_do_acai_e_da_cola("d3", "2026-08-11T13:00:00+00:00", tipo="NC"),
    ]
    assert serie_diaria(eventos) == [
        {"rotulo": "2026-08-10", "valor": 22.70},
        {"rotulo": "2026-08-11", "valor": -11.35},
    ]


def test_centimos_nao_perde_o_meio_centimo():
    assert centimos(10.205) in (1020, 1021)  # o que interessa é ser INTEIRO
    assert centimos(0.1) + centimos(0.2) == centimos(0.3)
