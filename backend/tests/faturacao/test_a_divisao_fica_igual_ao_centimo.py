"""**Dividir 23,40 € por dois dá 11,70 e 11,70** — e não 11,71 e 11,69.

O dono apanhou-o no ecrã, em modo de testes, e é uma daquelas coisas que só se
vê com o número à frente: a soma estava certa, ninguém perdia dinheiro, mas
23,40 divide-se ao meio sem resto e o POS prometia um valor que ninguém faz de
cabeça.

A causa era a repartição ser feita **linha a linha** — a única forma de cada
parte sair como uma fatura com artigos — e cada linha ímpar dar o seu cêntimo à
primeira pessoa: com duas linhas ímpares, dois cêntimos empilhados nela.

A regra que ele pediu, nas palavras dele: «se o valor for par, fica a divisão
igual; se der número ímpar, a primeira pessoa paga mais e as restantes pagam
menos». É exactamente `repartir_centimos(total, n)` — e o que passou a
acontecer é escolher-se QUEM leva cada fatia (`reparticao.ordem_das_fatias`)
para cada pessoa aterrar nesse alvo. As fatias são as mesmas; muda a pessoa a
quem cada uma calha.

Este ficheiro mede a promessa inteira, e não um caso: para centenas de contas
com descontos de linha e globais pelo meio, **cada parte tem de valer
exactamente o que o total dividido por N lhe dá**.
"""
import random

import pytest

from faturacao import venda as venda_mod
from faturacao.reparticao import repartir_centimos
from faturacao.venda import PedidoDividir, _centimos, dividir_conta

from .test_venda import _corre, _db, _linha, _operador, _venda


def _divide(linhas, n, monkeypatch, **conta):
    db = _db([], vendas=[_venda(linhas=linhas, **conta)])
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    r = _corre(dividir_conta("venda-1", PedidoDividir(partes=n), operador=_operador()))
    return [_centimos(p["totais"]["total"]) for p in r["partes"]]


def _artigo(i, preco, quantidade=1, **over):
    return _linha(id="l%d" % i, produto_nome="Artigo %d" % i, produto_preco=preco,
                  quantidade=quantidade, **over)


# --- O caso do dono -----------------------------------------------------------


@pytest.mark.parametrize("nome, precos", [
    ("dois artigos ímpares", [8.99, 14.41]),
    ("três artigos", [8.99, 7.20, 7.21]),
    ("quatro artigos", [3.80, 8.99, 3.41, 7.20]),
    ("um artigo só", [23.40]),
    ("dois pares", [11.70, 11.70]),
])
def test_2340_por_dois_da_1170_a_cada_um(nome, precos, monkeypatch):
    """O ecrã que ele viu dizia 11,71. Cada um destes cestos soma 23,40 € e
    todos eles davam 11,71/11,69 antes desta correcção — menos os dois últimos,
    que davam certo por acaso (uma linha só, ou linhas pares)."""
    partes = _divide([_artigo(i, p) for i, p in enumerate(precos)], 2, monkeypatch)
    assert partes == [1170, 1170], "%s: %s" % (nome, partes)


def test_uma_conta_indivisivel_poe_o_centimo_na_PRIMEIRA_pessoa(monkeypatch):
    """8,99 € por três: 3,00 + 3,00 + 2,99. É a regra que o dono disse — quem
    paga o cêntimo a mais é a primeira, nunca a última."""
    assert _divide([_artigo(0, 8.99)], 3, monkeypatch) == [300, 300, 299]


def test_o_centimo_a_mais_e_sempre_do_princípio_da_fila(monkeypatch):
    """Dois cêntimos a distribuir por quatro pessoas: vão para as duas
    primeiras, e não para duas quaisquer."""
    partes = _divide([_artigo(0, 8.99), _artigo(1, 1.51)], 4, monkeypatch)
    assert partes == [263, 263, 262, 262], partes


# --- A promessa inteira, medida ----------------------------------------------


def _cesto(rnd):
    linhas = []
    for i in range(rnd.randint(1, 5)):
        over = {}
        sorte = rnd.random()
        if sorte < 0.2:
            over["desconto_pct"] = rnd.choice([5, 10, 12.5, 33])
        elif sorte < 0.3:
            over["desconto_eur"] = round(rnd.uniform(0.01, 2.0), 2)
        linhas.append(_artigo(i, round(rnd.uniform(0.05, 99.99), 2),
                              quantidade=rnd.randint(1, 3), **over))
    conta = {}
    sorte = rnd.random()
    if sorte < 0.2:
        conta["desconto_global_pct"] = rnd.choice([5, 10, 20])
    elif sorte < 0.3:
        conta["desconto_global_eur"] = round(rnd.uniform(0.01, 5.0), 2)
    return linhas, conta


def test_cada_parte_vale_o_que_o_total_dividido_por_N_lhe_da(monkeypatch):
    """**A propriedade, e não um caso.** Trezentas contas ao acaso — com
    descontos de linha em % e em €, e descontos globais por cima — divididas
    por 2 a 6 pessoas. Para cada uma, as partes têm de ser EXACTAMENTE
    `repartir_centimos(total, n)`: a mesma lista que o balcão diz em voz alta.

    A semente é fixa de propósito: um teste que muda de casos a cada corrida
    ora apanha o defeito ora não, e um guarda que falha uma vez em dez é um
    guarda que se aprende a ignorar."""
    rnd = random.Random(20260825)
    falhas = []
    for _ in range(300):
        linhas, conta = _cesto(rnd)
        n = rnd.randint(2, 6)
        try:
            partes = _divide(linhas, n, monkeypatch, **conta)
        except Exception as e:  # 422 de uma conta que não se divide assim
            if getattr(e, "status_code", None) == 422:
                continue
            raise
        total = sum(partes)
        esperado = repartir_centimos(total, n)
        if partes != esperado:
            falhas.append((n, total, partes, esperado))
    assert not falhas, (
        "%d contas em que as partes não são o total dividido por N. "
        "Primeiras: %s" % (len(falhas), falhas[:3])
    )


def test_ninguem_paga_mais_de_um_centimo_acima_de_outra_pessoa(monkeypatch):
    """A leitura humana da mesma propriedade, e a que se explica ao balcão:
    entre a pessoa que paga mais e a que paga menos nunca vai mais do que um
    cêntimo."""
    rnd = random.Random(20260826)
    piores = 0
    for _ in range(200):
        linhas, conta = _cesto(rnd)
        n = rnd.randint(2, 6)
        try:
            partes = _divide(linhas, n, monkeypatch, **conta)
        except Exception as e:
            if getattr(e, "status_code", None) == 422:
                continue
            raise
        piores = max(piores, max(partes) - min(partes))
    assert piores <= 1, "houve uma conta com %d cêntimos de diferença" % piores
