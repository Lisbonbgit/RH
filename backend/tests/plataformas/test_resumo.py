"""Os números do email de segunda-feira.

O que se defende aqui é sobretudo o que o relatório NÃO pode dizer: um total
que junta uma semana com uma quinzena, um zero onde faltou um relatório, ou
uma comparação entre duas semanas que não têm as mesmas plataformas dentro.
"""
from datetime import date

from plataformas import resumo

# Segunda-feira, 31 de Agosto de 2026 — o dia em que o email sai.
SEGUNDA = date(2026, 8, 31)
SEMANA = ("2026-08-24", "2026-08-30")
SEMANA_ANTES = ("2026-08-17", "2026-08-23")
QUINZENA = ("2026-08-01", "2026-08-15")


def registo(plataforma, inicio, fim, *, liquido=None, pedidos=None,
            problemas=None, lojas=None, tipo=None, loja="Loja Única",
            comissao=None):
    """Um relatório de UMA loja — que é como as plataformas os mandam."""
    from plataformas.leitura import chave_da_loja
    return {
        "id": "%s:%s..%s:%s" % (plataforma, inicio, fim, chave_da_loja(loja)),
        "plataforma": plataforma,
        "loja": loja,
        "loja_chave": chave_da_loja(loja),
        "tipo": tipo or ("quinzena" if plataforma == "glovo" else "semana"),
        "periodo_inicio": inicio,
        "periodo_fim": fim,
        "valores": {"liquido": liquido, "bruto": None, "pedidos": pedidos,
                    "comissao": comissao, "taxas": None, "ajustes": None,
                    "iva": None, "moeda": "EUR"},
        "lojas": lojas or [],
        "problemas": problemas or [],
        "notas": None,
        "origem": {"assunto": "Relatório", "data": inicio},
    }


def montar(registos, hoje=SEGUNDA, avisos=None):
    return resumo.montar_relatorio(hoje=hoje, ate="08:00", registos=registos,
                                   avisos=avisos)


def linha(dados, chave):
    return next(l for l in dados["plataformas"] if l["chave"] == chave)


# --- O que falta não vira zero ----------------------------------------------

def test_sem_relatorio_nenhum_nao_ha_um_unico_zero():
    dados = montar([])
    for chave in ("uber", "bolt", "glovo"):
        l = linha(dados, chave)
        assert l["estado"] == "nao_recebido"
        assert l["valores"]["liquido"] is None
        assert l["valores"]["pedidos"] is None
    assert dados["total_da_semana"]["liquido"] is None
    assert dados["total_da_semana"]["completo"] is False


def test_uma_plataforma_em_falta_marca_o_total_como_parcial():
    dados = montar([registo("uber", *SEMANA, liquido=1000.0, pedidos=200)])
    total = dados["total_da_semana"]
    assert total["liquido"] == 1000.0
    assert total["completo"] is False
    assert total["em_falta"] == ["Bolt Food"]
    assert linha(dados, "bolt")["estado"] == "nao_recebido"


def test_com_as_duas_o_total_esta_completo():
    dados = montar([
        registo("uber", *SEMANA, liquido=1000.50, pedidos=200),
        registo("bolt", *SEMANA, liquido=499.50, pedidos=80),
    ])
    total = dados["total_da_semana"]
    assert total["liquido"] == 1500.0
    assert total["pedidos"] == 280
    assert total["completo"] is True and total["em_falta"] == []


# --- A Glovo não entra no total da semana -----------------------------------

def test_a_glovo_NAO_e_somada_ao_total_da_semana():
    """Somar uma quinzena a uma semana dá um número que não é de período
    nenhum. A Glovo tem o seu bloco, com o seu período e a sua data."""
    dados = montar([
        registo("uber", *SEMANA, liquido=1000.0),
        registo("bolt", *SEMANA, liquido=500.0),
        registo("glovo", *QUINZENA, liquido=9999.0),
    ])
    assert dados["total_da_semana"]["liquido"] == 1500.0
    assert linha(dados, "glovo")["valores"]["liquido"] == 9999.0


def test_a_glovo_tem_sempre_calendario_mesmo_sem_relatorio():
    dados = montar([])
    assert linha(dados, "glovo")["estado"] == "nao_recebido"
    # ... e o bloco de calendário está lá na mesma, com datas reais.
    assert dados["glovo"]["em_curso"]["inicio"] == "2026-08-16"
    assert dados["glovo"]["fechada"]["pagamento"] == "2026-09-05"


# --- Os períodos ------------------------------------------------------------

def test_um_registo_de_outro_periodo_nao_e_apanhado():
    """O relatório da semana passada não pode aparecer como se fosse o desta:
    seria a mesma coisa que enviar duas vezes os mesmos números."""
    dados = montar([registo("uber", *SEMANA_ANTES, liquido=800.0)])
    assert linha(dados, "uber")["estado"] == "nao_recebido"
    assert linha(dados, "uber")["valores"]["liquido"] is None


def test_um_registo_com_o_fim_trocado_nao_e_apanhado():
    dados = montar([registo("uber", "2026-08-24", "2026-08-29", liquido=800.0)])
    assert linha(dados, "uber")["estado"] == "nao_recebido"


def test_a_semana_do_email_e_a_que_acabou_ontem():
    dados = montar([])
    assert dados["semana"]["inicio"] == "2026-08-24"
    assert dados["semana"]["fim"] == "2026-08-30"
    assert dados["semana"]["pagamento"] == "2026-08-31"  # hoje


def test_o_periodo_anterior_de_uma_quinzena_pergunta_ao_calendario():
    """Recuar quinze dias à mão saltava para o dia 17 de Julho. A quinzena
    anterior a 1–15 de Agosto é 16–31 de Julho, que tem dezasseis dias."""
    anterior = resumo._periodo_anterior("quinzena", "2026-08-01", "2026-08-15")
    assert anterior == {"inicio": "2026-07-16", "fim": "2026-07-31"}


# --- Comparações ------------------------------------------------------------

def test_sem_semana_anterior_a_variacao_e_None_e_nao_zero():
    dados = montar([registo("uber", *SEMANA, liquido=1000.0)])
    assert linha(dados, "uber")["variacao"] is None


def test_com_semana_anterior_a_variacao_e_calculada():
    dados = montar([
        registo("uber", *SEMANA, liquido=1200.0),
        registo("uber", *SEMANA_ANTES, liquido=1000.0),
    ])
    l = linha(dados, "uber")
    assert l["anterior"]["liquido"] == 1000.0
    assert l["variacao"] == 20.0


def test_uma_queda_da_variacao_negativa():
    dados = montar([
        registo("uber", *SEMANA, liquido=750.0),
        registo("uber", *SEMANA_ANTES, liquido=1000.0),
    ])
    assert linha(dados, "uber")["variacao"] == -25.0


def test_um_anterior_a_zero_nao_produz_variacao():
    """Dividir por zero não dá percentagem nenhuma, e "+100%" sobre zero não
    quer dizer coisa nenhuma a quem lê."""
    assert resumo.variacao(500.0, 0.0) is None
    assert resumo.variacao(500.0, None) is None
    assert resumo.variacao(None, 500.0) is None


def test_o_total_so_se_compara_quando_as_DUAS_semanas_tem_as_mesmas_plataformas():
    """Esta semana só a Uber, a passada as duas: a diferença mede a Bolt que
    faltou, não uma queda das vendas. O email não pode mostrar isso como queda."""
    dados = montar([
        registo("uber", *SEMANA, liquido=1000.0),
        registo("uber", *SEMANA_ANTES, liquido=1000.0),
        registo("bolt", *SEMANA_ANTES, liquido=500.0),
    ])
    total = dados["total_da_semana"]
    assert total["completo"] is False
    assert total["variacao"] is None


def test_com_tudo_nas_duas_semanas_o_total_compara_se():
    dados = montar([
        registo("uber", *SEMANA, liquido=1100.0),
        registo("bolt", *SEMANA, liquido=550.0),
        registo("uber", *SEMANA_ANTES, liquido=1000.0),
        registo("bolt", *SEMANA_ANTES, liquido=500.0),
    ])
    total = dados["total_da_semana"]
    assert total["completo"] is True
    assert total["anterior"] == 1500.0
    assert total["variacao"] == 10.0


# --- Problemas e avisos -----------------------------------------------------

def test_os_problemas_saem_com_o_nome_da_plataforma():
    dados = montar([
        registo("uber", *SEMANA, liquido=10.0, problemas=["3 pedidos cancelados"]),
        registo("bolt", *SEMANA, liquido=10.0, problemas=["Taxa de marketing 45 €"]),
    ])
    assert dados["problemas"] == [
        {"plataforma": "Uber Eats", "texto": "3 pedidos cancelados"},
        {"plataforma": "Bolt Food", "texto": "Taxa de marketing 45 €"},
    ]


def test_os_avisos_da_leitura_chegam_ao_relatorio():
    dados = montar([], avisos=["A caixa não respondeu."])
    assert dados["avisos"] == ["A caixa não respondeu."]


def test_as_lojas_do_relatorio_passam_tal_e_qual():
    dados = montar([registo("uber", *SEMANA, liquido=100.0, loja="Alfragide")])
    assert linha(dados, "uber")["lojas"][0]["nome"] == "Alfragide"


# --- Um relatório por LOJA: as somas ----------------------------------------
#
# As plataformas mandam um email por loja — a Uber quatro por semana, a Glovo
# cinco por quinzena. Este bloco existe porque a primeira versão guardava-os
# todos com a mesma chave: ficava o último, e o email mostrava o valor de UMA
# loja como se fosse o da semana inteira.

def test_as_lojas_somam_se_em_vez_de_se_comerem_umas_as_outras():
    dados = montar([
        registo("uber", *SEMANA, loja="L'açaí Amadora", liquido=293.39, pedidos=25),
        registo("uber", *SEMANA, loja="L'açaí Alfragide", liquido=1720.10, pedidos=151),
        registo("uber", *SEMANA, loja="L'açai Oeiras", liquido=964.42, pedidos=84),
    ])
    l = linha(dados, "uber")
    assert l["valores"]["liquido"] == 2977.91
    assert l["valores"]["pedidos"] == 260
    assert l["lojas_que_reportaram"] == 3
    assert [x["nome"] for x in l["lojas"]] == [
        "L'açaí Alfragide", "L'açai Oeiras", "L'açaí Amadora"]  # da maior p/ a menor


def test_a_soma_e_em_centimos_e_nao_deixa_resto():
    """`0.29 + 1.15 + 10.20` em vírgula flutuante dá 11,639999999999999, e
    isto vai num email a dizer quanto se vai receber."""
    dados = montar([registo("uber", *SEMANA, loja="A", liquido=0.29),
                    registo("uber", *SEMANA, loja="B", liquido=1.15),
                    registo("uber", *SEMANA, loja="C", liquido=10.20)])
    assert linha(dados, "uber")["valores"]["liquido"] == 11.64


def test_uma_loja_sem_valor_nao_conta_como_zero_na_soma():
    dados = montar([registo("uber", *SEMANA, loja="A", liquido=100.0),
                    registo("uber", *SEMANA, loja="B", liquido=None)])
    l = linha(dados, "uber")
    assert l["valores"]["liquido"] == 100.0     # a soma é de quem disse
    assert l["lojas_que_reportaram"] == 2       # mas foram dois relatórios


def test_se_NENHUMA_loja_disser_o_valor_o_estado_e_sem_valores():
    """A Bolt manda o relatório sem números quando os links não se conseguem
    ler. «Recebido sem valores» não é «não recebido» — e nenhum dos dois é
    zero."""
    dados = montar([registo("bolt", *SEMANA, loja="A", liquido=None)])
    l = linha(dados, "bolt")
    assert l["estado"] == "sem_valores"
    assert l["valores"]["liquido"] is None


def test_uma_loja_que_reportou_na_semana_passada_e_agora_nao_e_assinalada():
    """O total mais pequeno é por FALTA de um relatório, não por menos vendas.
    Sem este aviso lê-se como quebra de vendas."""
    dados = montar([
        registo("uber", *SEMANA, loja="Amadora", liquido=100.0),
        registo("uber", *SEMANA_ANTES, loja="Amadora", liquido=90.0),
        registo("uber", *SEMANA_ANTES, loja="Oeiras", liquido=200.0),
    ])
    l = linha(dados, "uber")
    assert l["lojas_em_falta"] == ["Oeiras"]
    assert l["comparavel"] is False
    assert l["variacao"] is None
    assert any("Oeiras" in p["texto"] for p in dados["problemas"])


def test_com_as_MESMAS_lojas_nas_duas_semanas_ja_se_compara():
    dados = montar([
        registo("uber", *SEMANA, loja="Amadora", liquido=110.0),
        registo("uber", *SEMANA, loja="Oeiras", liquido=110.0),
        registo("uber", *SEMANA_ANTES, loja="Amadora", liquido=100.0),
        registo("uber", *SEMANA_ANTES, loja="Oeiras", liquido=100.0),
    ])
    l = linha(dados, "uber")
    assert l["comparavel"] is True and l["variacao"] == 10.0
