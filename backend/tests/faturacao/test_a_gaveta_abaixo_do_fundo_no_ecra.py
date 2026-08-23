"""O aviso da **GAVETA ABAIXO DO FUNDO** — montado e tocado, não lido.

Um turno só pode tirar da gaveta o que lá pôs. Se o «deve estar na gaveta»
cair abaixo do fundo de maneio com que a caixa abriu, saiu dinheiro que
aquele turno nunca recebeu — e o resumo do turno não tinha um único campo que
o dissesse.

**Medido pela função REAL do servidor** (`caixa._resumo_do_turno`): fatura de
24,14 € paga 5,00 em dinheiro + 19,14 em Multibanco, açaí de 20,40 €
devolvido em **DINHEIRO** → `vendas_dinheiro = −15,40`, `esperado = 34,60`
com fundo de 50,00. **15,40 € abaixo do fundo.** A operadora conta a gaveta,
encontra 34,60 €, a diferença dá zero, e ela vai para casa. O campo que
explicava isto — `nota_credito.devolucao.acima_do_recebido` — era gravado com
o comentário «o gestor encontra isso depois» e **não tinha um único leitor**
em todo o repositório.

Os números deste ficheiro saem do SERVIDOR a sério: monta-se o ecrã com o que
`_resumo_do_turno` respondeu, e não com um dicionário escrito à mão que podia
divergir dele. É a mesma disciplina de `test_ponto_de_caixa_no_ecra.py`, mas
com o ecrã MONTADO — um guarda de texto sobre este aviso passava com ele
escrito dentro de um ramo que nunca acende.
"""
import json

import pytest

from faturacao.caixa import _resumo_do_turno

from .test_a_faixa_do_modo_no_ecra import _montar_no_node


_ACAI = "INT"
_REFRI = "NOR"


def _linha(nome, preco, tax_id, quantidade=1):
    return {"id": "linha-%s" % nome, "produto_nome": nome,
            "produto_preco": preco, "produto_tax_id": tax_id,
            "quantidade": quantidade}


def _venda_paga(pagamentos):
    return {
        "id": "v1", "estado": "emitida",
        "linhas": [_linha("Açaí Regular", 10.20, _ACAI, quantidade=2),
                   _linha("Água", 0.29, _ACAI),
                   _linha("Coca-Cola", 1.15, _REFRI, quantidade=3)],
        "pagamentos": pagamentos,
        "desconto_global_pct": None, "desconto_global_eur": None,
    }


_MISTA = _venda_paga([
    {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
     "valor": 5.00},
    {"tipo_pagamento_id": "t-mb", "nome": "Multibanco", "tipo_fiscal": "CD",
     "valor": 19.14},
])
_EM_DINHEIRO = _venda_paga([
    {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
     "valor": 24.14},
])
_DEVOLUCAO_DO_ACAI = {
    "estado": "emitida",
    "linhas": [{"indice": 1, "titulo": "Açaí Regular", "tax_id": _ACAI,
                "quantidade": 2, "preco_unitario": 10.20, "total": 20.40}],
    "total": 20.40,
    "devolucao": {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                  "tipo_fiscal": "NU", "valor": 20.40,
                  "acima_do_recebido": 15.40},
}


def _resumo(venda, notas):
    return _resumo_do_turno({"id": "sessao-1", "fundo": 50.00}, [], [venda], notas)


# Os três resumos, saídos do SERVIDOR — o que fura o fundo, o controlo em que
# a mesma devolução cabe na gaveta, e o turno sem devolução nenhuma.
_ABAIXO = _resumo(_MISTA, [_DEVOLUCAO_DO_ACAI])
_CABE = _resumo(_EM_DINHEIRO, [dict(
    _DEVOLUCAO_DO_ACAI,
    devolucao=dict(_DEVOLUCAO_DO_ACAI["devolucao"], acima_do_recebido=0.0))])
_SEM_DEVOLUCAO = _resumo(_EM_DINHEIRO, [])


_COMPONENTES = "\n".join([
    "const Div = (props) => React.createElement('div', null, props.children);",
    "global.__componentes = new Proxy({}, { get: (_, nome) => (",
    "  nome === '__esModule' ? true : Div) });",
])

_GUIAO = "\n".join([
    _COMPONENTES,
    "const path2 = require('path');",
    # O preâmbulo substitui os ecrãs do POS por marcas vazias — é o que deixa
    # montar o `PosApp` sem montar tudo o que está por baixo dele. Aqui é
    # ESTE ecrã que se quer medir, por isso sai da lista antes de o carregar.
    "SUBSTITUIDOS.delete(path2.join(POS, 'PosResumoDoTurno.js'));",
    "const Resumo = carregar(path2.join(POS, 'PosResumoDoTurno.js')).default;",
    "const saida = {};",
    "for (const [nome, resumo] of [",
    "  ['abaixo', %s]," % json.dumps(_ABAIXO, ensure_ascii=False),
    "  ['cabe', %s]," % json.dumps(_CABE, ensure_ascii=False),
    "  ['sem_devolucao', %s]," % json.dumps(_SEM_DEVOLUCAO, ensure_ascii=False),
    "]) {",
    "  saida[nome] = await montar(React.createElement(Resumo, { resumo }));",
    "}",
    "process.stdout.write(JSON.stringify(saida));",
])


@pytest.fixture(scope="module")
def ecra(tmp_path_factory):
    return _montar_no_node(
        "(async () => {\n%s\n})().catch((e) => {"
        " process.stderr.write(String(e && e.stack || e)); process.exit(1); });"
        % _GUIAO,
        tmp_path_factory.mktemp("gaveta"), "montar-gaveta.js",
    )


def test_o_servidor_MEDE_a_gaveta_abaixo_do_fundo(ecra):
    """A reprodução, nos números do servidor: 15,40 € abaixo de um fundo de
    50,00, e o esperado a 34,60 € com as vendas em dinheiro NEGATIVAS."""
    assert _ABAIXO["vendas_dinheiro"] == -15.40
    assert _ABAIXO["esperado"] == 34.60
    assert _ABAIXO["gaveta_abaixo_do_fundo"] == 15.40
    assert _ABAIXO["devolucoes_acima_do_recebido"] == 15.40


def test_a_operadora_LE_que_a_gaveta_vai_fechar_abaixo_do_fundo(ecra):
    """Não é uma classe nem um campo escondido: é a frase que ela tem à frente
    antes de contar as notas."""
    visivel = ecra["abaixo"]["visivel"]
    assert "Deve estar na gaveta € 34,60" in visivel
    assert "A gaveta deve fechar € 15,40 ABAIXO do fundo de maneio" in visivel


def test_o_aviso_diz_PORQUE_e_que_ela_ficou_abaixo(ecra):
    """O leitor do `acima_do_recebido`, e é ele que separa uma acusação de uma
    explicação: «faltam 15,40 €» contra «saíram 15,40 € em devoluções por um
    meio que essas faturas não receberam»."""
    visivel = ecra["abaixo"]["visivel"]
    assert (
        "Saíram € 15,40 em devoluções por um meio de pagamento que essas "
        "faturas não receberam." in visivel
    )


def test_o_aviso_manda_contar_a_gaveta_na_mesma(ecra):
    """A instrução errada aqui era «não conte» ou «acerte à mão»: a contagem é
    o único facto do fecho, e continua a ser precisa."""
    assert "conte a gaveta na mesma e mostre isto ao gestor" in ecra["abaixo"]["visivel"]


def test_a_MESMA_devolucao_que_CABE_na_gaveta_nao_acende_aviso_nenhum(ecra):
    """**O controlo, e é o que impede este aviso de ser decoração.** A mesma
    fatura, o mesmo açaí devolvido em dinheiro — mas paga TODA em dinheiro:
    a gaveta recebeu os 24,14 € e a devolução cabe lá dentro."""
    visivel = ecra["cabe"]["visivel"]
    assert "ABAIXO do fundo de maneio" not in visivel
    # E o resto do bloco continua inteiro, com a gaveta acima do fundo.
    assert "Deve estar na gaveta € 53,74" in visivel


def test_um_turno_SEM_devolucao_nenhuma_tambem_fica_calado(ecra):
    visivel = ecra["sem_devolucao"]["visivel"]
    assert "ABAIXO do fundo de maneio" not in visivel
    assert "Deve estar na gaveta € 74,14" in visivel


def test_os_TRES_ecras_sao_diferentes(ecra):
    """A afirmação directa contra um aviso cravado ou um ramo morto: três
    resumos, três ecrãs."""
    assert len({ecra[n]["visivel"] for n in ("abaixo", "cabe", "sem_devolucao")}) == 3
