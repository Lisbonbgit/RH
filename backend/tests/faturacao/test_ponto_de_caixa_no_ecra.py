"""Guarda de regressão: o ecrã do resumo do turno só lê campos que o
servidor manda mesmo.

**Porque este ficheiro existe — o defeito aconteceu.** O
`PosResumoDoTurno.js` foi escrito a ler `resumo.base_tributavel` e
`resumo.iva_total` antes de esses campos existirem na resposta. No browser,
a linha de totais do mapa de imposto apareceu com **"€ 0,00" na base e no
IVA**, ao lado de linhas de 96,93 € e 6,80 € — porque `euros(undefined)`
pinta um zero perfeitamente legível. Não houve erro nenhum na consola, não
houve teste vermelho, e o ecrã ficou a dizer ao balcão que o turno não tinha
imposto nenhum.

É o modo de falhar mais perigoso de um ecrã de dinheiro: um campo que o
servidor não manda não fica em branco, fica a ZERO. E é invisível a quem lê
o código dos dois lados em separado — de um lado está escrito
`base_tributavel`, do outro está escrito `base_tributavel`, e só quem
comparar as duas listas repara que a segunda nunca existiu.

A técnica é a dos guardas irmãos (`test_caminhos_do_pos.py`,
`test_resumo_do_ecra.py`): ler o frontend e confrontá-lo com a verdade do
servidor. Aqui não é preciso correr JavaScript nenhum — o que se compara são
nomes de campos, e esses lêem-se do texto.
"""
import re
from pathlib import Path

import pytest

from faturacao.caixa import _resumo_do_turno

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_ECRA = _RAIZ / "frontend" / "src" / "pages" / "pos" / "PosResumoDoTurno.js"


def _ler(ficheiro: Path) -> str:
    if not ficheiro.exists():
        pytest.fail(
            "Não encontrei %s. Se o ecrã mudou de sítio, este guarda tem de "
            "ir atrás dele — não se apaga." % ficheiro
        )
    return ficheiro.read_text(encoding="utf-8")


def _turno_real():
    """Um turno a sério, passado pela função REAL do servidor — a mesma que
    responde ao Ponto de Caixa e ao Z. Nunca uma lista de nomes escrita à
    mão: essa envelhecia sozinha e o guarda passava a comparar o ecrã com
    uma cópia velha do servidor."""
    sessao = {"id": "sessao-1", "fundo": 50.0}
    movimentos = [
        {"id": "m1", "sessao_id": "sessao-1", "tipo": "entrada", "valor": 20.0},
        {"id": "m2", "sessao_id": "sessao-1", "tipo": "saida", "valor": 5.0},
    ]
    vendas = [{
        "id": "v1",
        "estado": "emitida",
        "linhas": [
            {"id": "l1", "produto_nome": "Açaí XL", "produto_preco": 10.20,
             "produto_tax_id": "INT", "quantidade": 1},
            {"id": "l2", "produto_nome": "Coca-Cola", "produto_preco": 1.15,
             "produto_tax_id": "NOR", "quantidade": 1},
        ],
        "desconto_global_pct": None,
        "desconto_global_eur": None,
        "pagamentos": [{"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro",
                        "tipo_fiscal": "NU", "valor": 11.35}],
    }]
    return _resumo_do_turno(sessao, movimentos, vendas)


def test_os_campos_que_o_ecra_le_do_resumo_existem_todos_na_resposta():
    """`resumo?.X` — os campos de topo. Um nome que o servidor não mande
    aparece no ecrã como "€ 0,00", nunca como erro."""
    resumo = _turno_real()
    lidos = set(re.findall(r"resumo\?\.(\w+)", _ler(_ECRA)))
    assert lidos, (
        "Não encontrei um único `resumo?.campo` no ecrã — ou ele deixou de "
        "ler a resposta do servidor, ou este guarda deixou de a saber ler. "
        "Nos dois casos, é para investigar, não para apagar."
    )
    em_falta = sorted(lidos - set(resumo))
    assert em_falta == [], (
        "O ecrã lê campos que o servidor não manda: %s. No browser isto não "
        "dá erro nenhum — dá € 0,00." % em_falta
    )


def test_os_campos_que_o_ecra_le_de_cada_linha_existem_nas_linhas_da_resposta():
    """`linha.X` — as células das duas tabelas (tipos de pagamento e mapa de
    imposto). O mesmo modo de falhar, uma camada abaixo."""
    resumo = _turno_real()
    assert resumo["pagamentos"] and resumo["mapa_imposto"], (
        "O turno de teste tem de produzir linhas nas DUAS tabelas — sem elas "
        "este guarda comparava o ecrã com o vazio e ficava verde por nada."
    )
    disponiveis = set(resumo["pagamentos"][0]) | set(resumo["mapa_imposto"][0])
    lidos = set(re.findall(r"\blinha\.(\w+)", _ler(_ECRA)))
    em_falta = sorted(lidos - disponiveis)
    assert em_falta == [], (
        "O ecrã lê campos que as linhas da resposta não têm: %s." % em_falta
    )


def test_o_ecra_nao_soma_dinheiro_nenhum():
    """A regra da casa: **a aritmética de dinheiro é do servidor** — o ecrã
    não soma euros, recebe-os somados.

    Um `reduce` sobre os totais das linhas seria a forma óbvia de pôr a
    última linha da tabela, e seria uma SEGUNDA verdade a viver por baixo da
    primeira: no dia em que a repartição do desconto global mudar de um
    cêntimo, o total do servidor e o total do browser deixam de bater, e o
    que a operadora lê é o do browser."""
    texto = _ler(_ECRA)
    # Só o código, sem os comentários — é deliberado falar de `reduce` na
    # documentação do ficheiro e este guarda não pode ficar refém disso.
    codigo = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    codigo = re.sub(r"^\s*//.*$", "", codigo, flags=re.M)
    for proibido in (".reduce(", "Number(resumo", "parseFloat"):
        assert proibido not in codigo, (
            "`%s` no ecrã do resumo do turno: isto é o browser a fazer contas "
            "com dinheiro. Os totais vêm somados do servidor "
            "(`caixa._resumo_do_turno`)." % proibido
        )
