"""O aviso do **DINHEIRO QUE SAIU DA GAVETA A MAIS** — montado e tocado, não
lido.

Um turno só pode tirar da gaveta o que lá pôs. Se as VENDAS EM DINHEIRO do
turno (as faturas menos as devoluções) ficam negativas, saiu dinheiro que
aquele turno nunca recebeu — e o resumo do turno não tinha um único campo que
o dissesse.

**Medido pela função REAL do servidor** (`caixa._resumo_do_turno`): fatura de
24,14 € paga 5,00 em dinheiro + 19,14 em Multibanco, açaí de 20,40 €
devolvido em **DINHEIRO** → `vendas_dinheiro = −15,40`. A operadora conta a
gaveta, bate certo, e vai para casa. O campo que explicava isto —
`nota_credito.devolucao.acima_do_recebido` — era gravado com o comentário «o
gestor encontra isso depois» e **não tinha um único leitor** em todo o
repositório.

**E o primeiro guarda mediu isto pelo número errado**: comparava o `fundo` com
o `esperado`, e o `esperado` inclui os movimentos de caixa. Falhava nos DOIS
sentidos, e os dois estão aqui MONTADOS:

- **mascarado** — os mesmos −15,40 € com um reforço de troco de 20,00 €: o
  esperado sobe para 54,60, o aviso apagava-se, e o ecrã ficava sem uma
  palavra. Nem «ABAIXO do fundo», nem a frase das devoluções — que estava
  pendurada no mesmo predicado e desaparecia com ele, pondo o
  `acima_do_recebido` de volta a campo só de escrita;
- **sangria** — sem devolução nenhuma, 24,14 € vendidos em dinheiro e uma
  saída de 30,00 € para o cofre: o ecrã acendia o aviso todo, com a frase
  «mostre isto ao gestor», por causa do depósito diário.

**Nenhum dos guardas da ronda anterior punha um movimento de caixa no
resumo** — todos passavam `movimentos=[]`, e é por isso que ninguém deu por
nada. Aqui os cenários têm entradas e saídas lá dentro.

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


def _venda_paga(pagamentos, id_="v1", linhas=None):
    return {
        "id": id_, "estado": "emitida",
        "linhas": linhas or [_linha("Açaí Regular", 10.20, _ACAI, quantidade=2),
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

# A fatura grande que põe a gaveta do TURNO em ordem sem apagar a devolução
# feita por um meio que a fatura pequena não recebeu.
_GRANDE = _venda_paga(
    [{"tipo_pagamento_id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
      "valor": 100.00}],
    id_="v-grande", linhas=[_linha("Caixa de açaí", 100.00, _ACAI)])
_PEQUENA = _venda_paga(
    [{"tipo_pagamento_id": "t-nu", "nome": "Dinheiro", "tipo_fiscal": "NU",
      "valor": 5.00},
     {"tipo_pagamento_id": "t-mb", "nome": "Multibanco", "tipo_fiscal": "CD",
      "valor": 6.29}],
    id_="v-pequena", linhas=[_linha("Açaí Regular", 9.85, _ACAI),
                             _linha("Água", 1.44, _REFRI)])
_DEVOLUCAO_PEQUENA = {
    "estado": "emitida",
    "linhas": [{"indice": 1, "titulo": "Açaí Regular", "tax_id": _ACAI,
                "quantidade": 1, "preco_unitario": 9.85, "total": 9.85}],
    "total": 9.85,
    "devolucao": {"tipo_pagamento_id": "t-nu", "nome": "Dinheiro",
                  "tipo_fiscal": "NU", "valor": 9.85,
                  "acima_do_recebido": 4.85},
}

_ENTRADA_DE_TROCO = [{"id": "m1", "tipo": "entrada", "valor": 20.00}]
_SANGRIA_PARA_O_COFRE = [{"id": "m1", "tipo": "saida", "valor": 30.00}]


def _resumo(vendas, notas, movimentos=()):
    return _resumo_do_turno({"id": "sessao-1", "fundo": 50.00},
                            list(movimentos), vendas, notas)


# Os resumos, saídos do SERVIDOR — o que fura a gaveta, o mesmo furo
# MASCARADO por um reforço de troco, a sangria de rotina que não é furo
# nenhum, a devolução por um meio errado com a gaveta do turno em ordem, o
# controlo em que a devolução cabe na gaveta e o turno sem devolução nenhuma.
_SAIU = _resumo([_MISTA], [_DEVOLUCAO_DO_ACAI])
_MASCARADO = _resumo([_MISTA], [_DEVOLUCAO_DO_ACAI], _ENTRADA_DE_TROCO)
_SANGRIA = _resumo([_EM_DINHEIRO], [], _SANGRIA_PARA_O_COFRE)
_SO_O_MEIO = _resumo([_GRANDE, _PEQUENA], [_DEVOLUCAO_PEQUENA], _ENTRADA_DE_TROCO)
_CABE = _resumo([_EM_DINHEIRO], [dict(
    _DEVOLUCAO_DO_ACAI,
    devolucao=dict(_DEVOLUCAO_DO_ACAI["devolucao"], acima_do_recebido=0.0))])
_SEM_DEVOLUCAO = _resumo([_EM_DINHEIRO], [])

_CENARIOS = [
    ("saiu", _SAIU),
    ("mascarado", _MASCARADO),
    ("sangria", _SANGRIA),
    ("so_o_meio", _SO_O_MEIO),
    ("cabe", _CABE),
    ("sem_devolucao", _SEM_DEVOLUCAO),
]


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
] + [
    "  ['%s', %s]," % (nome, json.dumps(resumo, ensure_ascii=False))
    for nome, resumo in _CENARIOS
] + [
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


_AVISO = "Saíram € 15,40 da gaveta a mais do que as vendas deste turno lá puseram"
_PORQUE = ("Saíram € 15,40 em devoluções por um meio de pagamento que essas "
           "faturas não receberam.")


def test_o_servidor_MEDE_o_que_saiu_da_gaveta_a_mais(ecra):
    """A reprodução, nos números do servidor: 15,40 € que aquele turno não
    recebeu, com as vendas em dinheiro NEGATIVAS."""
    assert _SAIU["vendas_dinheiro"] == -15.40
    assert _SAIU["esperado"] == 34.60
    assert _SAIU["tirado_da_gaveta_a_mais"] == 15.40
    assert _SAIU["devolucoes_acima_do_recebido"] == 15.40


def test_a_operadora_LE_que_saiu_dinheiro_que_o_turno_nao_recebeu(ecra):
    """Não é uma classe nem um campo escondido: é a frase que ela tem à frente
    antes de contar as notas."""
    visivel = ecra["saiu"]["visivel"]
    assert "Deve estar na gaveta € 34,60" in visivel
    assert _AVISO in visivel


def test_o_aviso_diz_PORQUE_e_que_o_dinheiro_saiu(ecra):
    """O leitor do `acima_do_recebido`, e é ele que separa uma acusação de uma
    explicação: «faltam 15,40 €» contra «saíram 15,40 € em devoluções por um
    meio que essas faturas não receberam»."""
    assert _PORQUE in ecra["saiu"]["visivel"]


def test_o_aviso_manda_contar_a_gaveta_na_mesma(ecra):
    """A instrução errada aqui era «não conte» ou «acerte à mão»: a contagem é
    o único facto do fecho, e continua a ser precisa."""
    assert "conte a gaveta na mesma e mostre isto ao gestor" in ecra["saiu"]["visivel"]


# --- O falso negativo: o vazamento MASCARADO por um reforço de troco ----------


def test_um_REFORCO_DE_TROCO_nao_apaga_o_aviso_do_ecra(ecra):
    """**O oitavo defeito, no ecrã.** A MESMA devolução, mais 20,00 € de troco
    metidos na gaveta: o `esperado` sobe para 54,60 € (acima do fundo de
    50,00) e o aviso apagava-se — com os 15,40 € ainda de fora, e sem uma
    palavra no ecrã. Bastava uma entrada de 15,40 € para o calar."""
    visivel = ecra["mascarado"]["visivel"]
    assert _MASCARADO["esperado"] == 54.60
    assert "Deve estar na gaveta € 54,60" in visivel
    assert _AVISO in visivel


def test_o_reforco_de_troco_tambem_nao_apaga_o_PORQUE(ecra):
    """A frase das devoluções estava pendurada no predicado do aviso e
    desaparecia com ele — o `acima_do_recebido` voltava a ser um campo só de
    escrita, que era exactamente o defeito que a ronda anterior fechou."""
    assert _MASCARADO["devolucoes_acima_do_recebido"] == 15.40
    assert _PORQUE in ecra["mascarado"]["visivel"]


# --- O falso positivo: a sangria de rotina -----------------------------------


def test_uma_SANGRIA_para_o_cofre_nao_acende_aviso_nenhum(ecra):
    """**O outro sentido.** Sem devolução nenhuma: 24,14 € vendidos em
    dinheiro e 30,00 € depositados no cofre. O ecrã acendia «A gaveta deve
    fechar € 5,86 ABAIXO do fundo de maneio» e mandava mostrar isto ao gestor
    — por causa do depósito diário. Numa loja com depósito diário isto acendia
    todas as noites, e a noite verdadeira era igual às outras."""
    visivel = ecra["sangria"]["visivel"]
    assert _SANGRIA["esperado"] == 44.14 and _SANGRIA["saidas"] == 30.00
    assert "Deve estar na gaveta € 44,14" in visivel
    assert "Saíram" not in visivel
    assert "mostre isto ao gestor" not in visivel


def test_a_frase_nunca_promete_uma_gaveta_ABAIXO_DO_FUNDO(ecra):
    """A frase antiga era falsa em número mal houvesse um movimento: com uma
    sangria por cima do vazamento a gaveta fecha 45,40 € abaixo do fundo, e
    ela anunciava 15,40. O ecrã deixou de falar do fundo — fala do que saiu."""
    for nome, _ in _CENARIOS:
        assert "ABAIXO do fundo" not in ecra[nome]["visivel"]


# --- As duas perguntas são INDEPENDENTES -------------------------------------


def test_o_PORQUE_aparece_com_a_gaveta_do_TURNO_em_ordem(ecra):
    """**menor 1.** Duas faturas — 100,00 € em dinheiro e outra paga 5,00 em
    dinheiro + 6,29 em Multibanco — com o açaí de 9,85 € devolvido em
    DINHEIRO. As vendas em dinheiro do turno são +95,15 € (a gaveta está bem)
    e ainda assim saíram 4,85 € por um meio que aquela fatura não recebeu."""
    visivel = ecra["so_o_meio"]["visivel"]
    assert _SO_O_MEIO["vendas_dinheiro"] == 95.15
    assert _SO_O_MEIO["tirado_da_gaveta_a_mais"] == 0.0
    assert _SO_O_MEIO["devolucoes_acima_do_recebido"] == 4.85
    assert ("Saíram € 4,85 em devoluções por um meio de pagamento que essas "
            "faturas não receberam." in visivel)
    # E o aviso da gaveta NÃO acende: são duas perguntas, e esta responde não.
    assert "da gaveta a mais" not in visivel


# --- O sinal da linha das vendas em dinheiro ---------------------------------


def test_a_linha_das_vendas_em_dinheiro_nunca_le_MAIS_colado_a_um_NEGATIVO(ecra):
    """**menor 3.** Lia-se «Vendas em dinheiro **+ € -15,40**» — um sinal de
    mais colado a um número negativo, na linha onde o vazamento aparece
    primeiro e a única que o mostra quando mais nada o mostra. Com pressa,
    lê-se ao contrário."""
    for nome, _ in _CENARIOS:
        assert "+ € -" not in ecra[nome]["visivel"]
    assert "Vendas em dinheiro − € 15,40" in ecra["saiu"]["visivel"]


def test_um_turno_normal_continua_a_ler_MAIS_nas_vendas_em_dinheiro(ecra):
    """O controlo do de cima: trocar o sinal de todas as linhas não era a
    correcção."""
    assert "Vendas em dinheiro + € 24,14" in ecra["sem_devolucao"]["visivel"]


# --- Os controlos ------------------------------------------------------------


def test_a_MESMA_devolucao_que_CABE_na_gaveta_nao_acende_aviso_nenhum(ecra):
    """**O controlo, e é o que impede este aviso de ser decoração.** A mesma
    fatura, o mesmo açaí devolvido em dinheiro — mas paga TODA em dinheiro:
    a gaveta recebeu os 24,14 € e a devolução cabe lá dentro."""
    visivel = ecra["cabe"]["visivel"]
    assert "Saíram" not in visivel
    assert "Deve estar na gaveta € 53,74" in visivel


def test_um_turno_SEM_devolucao_nenhuma_tambem_fica_calado(ecra):
    visivel = ecra["sem_devolucao"]["visivel"]
    assert "Saíram" not in visivel
    assert "Deve estar na gaveta € 74,14" in visivel


def test_os_SEIS_ecras_sao_diferentes(ecra):
    """A afirmação directa contra um aviso cravado ou um ramo morto: seis
    resumos, seis ecrãs."""
    assert len({ecra[nome]["visivel"] for nome, _ in _CENARIOS}) == 6
