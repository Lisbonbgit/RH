"""**Uma falha do Vendus não pode apagar vendas.**

O caminho que este ficheiro defende, por inteiro:
`_fin_vendus_fetch_store_days` lê os documentos de uma loja e devolve
`(by_day, complete, erro)`. Quem a chama (`_fin_vendus_run_account`) só manda
gravar quando `complete` é verdade, e quem grava (`_fin_vendus_write_store`)
começa por `delete_many` do intervalo INTEIRO — sempre, sem condição nenhuma.

Ou seja: **`complete=True` com uma leitura falhada é o mesmo que mandar apagar
as vendas daqueles dias.** Com o cron rápido de hora a hora sobre a janela por
omissão de 3 dias, era isso que acontecia, com o relatório a responder
`errors: []`.

Estes testes correm contra a função REAL do `server.py` — não contra uma cópia
dela. É por isso que importam o módulo: o `AsyncIOMotorClient` não liga a nada
ao ser construído, por isso o import não toca no Mongo (medido: 0,7 s, sem uma
única thread nova). O que se substitui é só a porta de saída para a rede,
`_fin_vendus_http`, que é o sítio exacto onde a falha nasce.
"""
import os

import pytest

# Antes do import: o `server.py` lê `MONGO_URL`/`DB_NAME` do ambiente à
# importação (`os.environ['MONGO_URL']`) e rebenta sem eles. Não se liga a
# nada — o cliente do Motor é preguiçoso — mas a variável tem de existir.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _doc(dia="2026-08-20", bruto=100.0, liquido=88.5, tipo="FS", estado="N"):
    """Um documento como a API do Vendus o devolve, no mínimo que esta
    função lê."""
    return {
        "id": "d1",
        "type": tipo,
        "status": estado,
        "date": f"{dia} 14:30:00",
        "amount_gross": bruto,
        "amount_net": liquido,
    }


def _ler(monkeypatch, respostas, with_cost=False):
    """Corre a função real com uma porta de rede de mentira.

    `respostas` é a lista do que o Vendus devolve, pedido a pedido — uma
    entrada por chamada, na ordem em que forem feitas.
    """
    chamadas = []

    def falso_http(key, path, tries=3):
        chamadas.append(path)
        return respostas[len(chamadas) - 1] if len(chamadas) <= len(respostas) else None

    monkeypatch.setattr(server, "_fin_vendus_http", falso_http)
    resultado = server._fin_vendus_fetch_store_days(
        "chave", "loja-1", "2026-08-18", "2026-08-20", with_cost, {}
    )
    return resultado, chamadas


def test_falha_logo_na_primeira_pagina_nao_e_leitura_completa(monkeypatch):
    """O pior caso, e o que apagava tudo: a primeira página falha, `by_day`
    fica vazio, e um `complete=True` aqui fazia o `write_store` apagar o
    intervalo e não inserir nada em troca."""
    (by_day, completa, erro), _ = _ler(monkeypatch, [None])

    assert completa is False, (
        "uma leitura falhada NÃO pode dizer-se completa — quem grava apaga o "
        "intervalo inteiro antes de escrever"
    )
    assert by_day == {}
    assert erro and "nada gravado" in erro


def test_falha_a_meio_da_paginacao_tambem_nao_e_completa(monkeypatch):
    """Uma página cheia lida e a seguinte a falhar: o que se leu está certo,
    mas está INCOMPLETO — e gravá-lo substituía o total do dia por uma parte
    dele. Subcontar em silêncio é o mesmo estrago mais devagar."""
    pagina_cheia = [_doc(bruto=10.0, liquido=9.0) for _ in range(100)]
    (by_day, completa, erro), chamadas = _ler(monkeypatch, [pagina_cheia, None])

    assert completa is False
    assert erro and "página 2" in erro
    assert len(chamadas) == 2, "tem de ter mesmo tentado a segunda página"
    # O que se leu não se deita fora — é devolvido para quem quiser olhar —,
    # mas vai acompanhado do `complete=False` que impede a gravação.
    assert by_day["2026-08-20"][0] == pytest.approx(1000.0)


def test_uma_resposta_que_nao_e_lista_conta_como_falha(monkeypatch):
    """O Vendus pode responder 200 com um corpo de erro (um dict). Cai na
    mesma regra: não são documentos, logo não se leu nada."""
    (_, completa, erro), _ = _ler(monkeypatch, [{"errors": ["chave inválida"]}])

    assert completa is False
    assert erro


def test_a_leitura_normal_continua_completa(monkeypatch):
    """A rede de segurança não pode travar o caminho de sempre: uma página
    curta é o fim natural das páginas, e isso é uma leitura COMPLETA."""
    (by_day, completa, erro), chamadas = _ler(
        monkeypatch, [[_doc(bruto=100.0, liquido=88.5)]]
    )

    assert completa is True
    assert erro is None
    assert len(chamadas) == 1, "uma página curta não pede a página seguinte"
    assert by_day["2026-08-20"][0] == pytest.approx(100.0)
    assert by_day["2026-08-20"][1] == pytest.approx(88.5)


def test_uma_loja_sem_vendas_no_intervalo_continua_completa(monkeypatch):
    """O outro caso legítimo de leitura vazia — a loja não vendeu nada nestes
    dias — tem de continuar a distinguir-se da falha. Se este teste passar a
    dizer `False`, o cron deixa de conseguir limpar dias que ficaram a zero."""
    (by_day, completa, erro), _ = _ler(monkeypatch, [[]])

    assert completa is True
    assert erro is None
    assert by_day == {}


def test_falha_a_ler_as_linhas_de_um_documento_nao_grava_custo_a_zero(monkeypatch):
    """Com `with_cost` (a passagem noturna), cada documento pede as suas
    linhas. Uma falha aí punha o CMV daquele documento a zero em silêncio — e
    o CMV é o que alimenta o DRE. Nenhum custo é melhor do que um custo baixo
    de mais que fica gravado."""
    (_, completa, erro), _ = _ler(
        monkeypatch, [[_doc()], None], with_cost=True
    )

    assert completa is False
    assert erro and "CMV" in erro
