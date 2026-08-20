"""O texto do pedido da cozinha — lógica pura, sem I/O.

O agente de impressão (Plano 3) ainda não existe; isto só constrói o texto
que ele vai imprimir, para não haver nada a mexer aqui quando ele chegar.
"""
from faturacao.talao import pedido_da_cozinha


def test_o_pedido_sai_no_formato_que_o_dono_escreveu():
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "respostas_texto": [{"grupo_id": "g0", "nome_grupo": "Nome", "texto": "Maria"}],
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0, "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Leite condensado", "preco": 0},
            {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
            {"id": "o2", "grupo_id": "g2", "nome": "Nutella", "preco": 0.95},
        ],
    }]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n"
        "\n"
        "1 Açaí Small — MARIA\n"
        "Levar\n"
        "\n"
        "1x Leite condensado\n"
        "2x Nutella\n"
    )


def test_opcao_PAGA_de_grupo_escondido_vai_com_a_dose_e_nao_ao_servico():
    """A cozinha tem de fazer as duas doses que a fatura cobra.

    O interruptor `sai_na_fatura` esconde o que não custa nada, nunca um euro
    — a mesma regra do título da fatura (`precos._descricao_das_opcoes`) e do
    resumo do ecrã do POS. Estava escrita neste ficheiro ("as opções SEM
    preço de grupos que não vão à fatura") mas não estava no código, que só
    olhava para o interruptor: com um grupo de toppings desligado por engano,
    o "Extra caramelo" pago descia às indicações de serviço, dito uma vez e
    sem dose. A cozinha punha UMA colher, a Fatura Simplificada cobrava duas
    ("Extra caramelo 2×"), e o cliente reclamava com toda a razão."""
    venda = {"linhas": [{
        "produto_nome": "Açaí Small", "quantidade": 1,
        "opcoes": [
            {"id": "o0", "grupo_id": "g1", "nome": "Levar", "preco": 0, "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Extra caramelo", "preco": 0.5,
             "sai_na_fatura": False},
            {"id": "o1", "grupo_id": "g2", "nome": "Extra caramelo", "preco": 0.5,
             "sai_na_fatura": False},
        ],
    }]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n"
        "\n"
        "1 Açaí Small\n"
        "Levar\n"
        "\n"
        "2x Extra caramelo\n"
    )


def test_uma_linha_sem_nome_nem_opcoes_sai_na_mesma():
    venda = {"linhas": [{"produto_nome": "Café Expresso", "quantidade": 2}]}
    assert pedido_da_cozinha(venda) == "Pedido\n\n2 Café Expresso\n"


def test_duas_linhas_ficam_separadas():
    venda = {"linhas": [
        {"produto_nome": "Café Expresso", "quantidade": 1},
        {"produto_nome": "Água 50cl", "quantidade": 1},
    ]}
    assert pedido_da_cozinha(venda) == (
        "Pedido\n\n1 Café Expresso\n\n1 Água 50cl\n"
    )
