"""As cinco fases do funil e a ordem das regras automáticas
(crm/dominio/fases.py).

Porta de src/Dominio/Fases.php, com todos os casos do
tests/Unit/Dominio/FasesTest.php do CRM autónomo (mesmos nomes nos `ids`).
Só valem os nomes exatos da ORDEM: o `in_array(…, true)` do PHP passa a
`isinstance(x, str) and x in ORDEM` (dossiê §2.1 e §5.1).

A ORDEM do browser (frontend/src/lib/crm/fases.js) é comparada com esta pelo
test_consistencia_frontend.py (T2.20).
"""
import pytest

from crm.dominio.fases import ORDEM, fase_valida


def test_a_ordem_vai_de_perdida_a_cliente():
    assert ORDEM == ("perdida", "potencial", "contactada", "amostra", "cliente")


def test_a_ordem_nao_se_altera_por_engano():
    # Um tuplo: as regras automáticas (F4/F5) sobem nesta ordem, e ninguém lhe
    # pode juntar ou trocar fases em tempo de execução.
    assert isinstance(ORDEM, tuple)


@pytest.mark.parametrize(
    "fase",
    ["perdida", "potencial", "contactada", "amostra", "cliente"],
    ids=["perdida", "potencial", "contactada", "amostra", "cliente"],
)
def test_cada_fase_da_ordem_e_valida(fase):
    assert fase_valida(fase) is True


@pytest.mark.parametrize(
    "fase",
    ["Cliente", " cliente ", "arquivada", "", None, 1, ["cliente"]],
    ids=["maiúscula", "com espaços", "desconhecida", "vazia", "nula", "número da posição", "lista"],
)
def test_recusa_o_que_nao_for_uma_fase_conhecida(fase):
    assert fase_valida(fase) is False


@pytest.mark.parametrize(
    "fase",
    ["cliente\n", "CLIENTE", "cliénte", True, 0, 4.0, ("cliente",), {"fase": "cliente"}],
    ids=[
        "mudança de linha no fim",
        "tudo em maiúsculas",
        "com acento",
        "verdadeiro",
        "posição zero",
        "posição em número decimal",
        "tuplo",
        "objeto",
    ],
)
def test_recusa_tambem_as_armadilhas_do_python(fase):
    # Nem o "\n" final (que o `$` das expressões regulares deixaria passar),
    # nem um bool (que em Python é um int), nem uma posição na ORDEM.
    assert fase_valida(fase) is False
