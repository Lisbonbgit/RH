"""Cada variável de ambiente que o CRM lê tem o nome no backend/.env.example
(plano T2.16; dossiê §9; desenho §4.4 e §8: "no repositório só os nomes").

O `.env.example` é partilhado com o Matheus (plano §0, regra 6): o CRM só
acrescenta um bloco no fim, com os nomes e SEM valores. Os valores reais vão
para o `backend/.env` do servidor, pelas mãos do dono (dossiê §14), e o
docker-compose passa esse ficheiro inteiro ao backend (`env_file`).

A lista não se escreve só à mão: procura-se no código do pacote `crm`, pela
árvore sintática, cada leitura do ambiente (`os.environ.get(…)`,
`os.environ[…]`, `… in os.environ`, `os.getenv(…)`), com o nome literal ou
numa constante do módulo (`VARIAVEL_CHAVE = "…"`). Uma leitura que não se
consiga resolver falha o teste em vez de passar em silêncio. Assim, quando a
F3 ler `CRM_ORS_CHAVE`, este teste fica vermelho até o nome entrar no
`.env.example`.

As mensagens de falha mostram só nomes, nunca valores do `.env.example`
(plano §0, regra 8).
"""
import ast
import re
from collections import Counter
from pathlib import Path

import pytest

from crm import config_mapa
from crm.servicos import geoapify

BACKEND = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = BACKEND / ".env.example"
PACOTE_CRM = BACKEND / "crm"

PREFIXO_CRM = "CRM_"
CABECALHO_DO_BLOCO = "CRM Purple House"

# O que o pacote `crm` lê do ambiente na F2. Uma variável nova no código falha
# `test_o_pacote_crm_le_exatamente_estas_variaveis` até entrar aqui E no
# `.env.example`.
LIDAS_PELO_CRM = {
    "ADMIN_EMAIL",  # crm.auth: o admin master (já existia no portal)
    "CRON_KEY",  # crm.auth.exigir_cron_key (já existia, partilhada com o Financeiro)
    config_mapa.VARIAVEL_CHAVE,  # chave dos mosaicos (vai ao browser)
    geoapify.VARIAVEL_CHAVE_SERVIDOR,  # chave da pesquisa de morada (só no servidor)
    geoapify.VARIAVEL_URL,  # opcional: por omissão https://api.geoapify.com
}

_ATRIBUICAO = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)")
_METODOS_QUE_LEEM = ("get", "setdefault", "pop")


def _atribuicoes(texto):
    """`[(número da linha, nome, valor)]` de cada `NOME=valor` que não está
    comentado, pela ordem do ficheiro."""
    resultado = []
    for numero, linha in enumerate(texto.splitlines(), start=1):
        encontrado = _ATRIBUICAO.fullmatch(linha.strip())
        if encontrado:
            resultado.append((numero, encontrado.group(1), encontrado.group(2)))
    return resultado


def _e_o_ambiente(no):
    """`os.environ` (ou `x.environ`, para apanhar `import os as x`) ou
    `environ` sozinho (`from os import environ`)."""
    return (isinstance(no, ast.Attribute) and no.attr == "environ") or (
        isinstance(no, ast.Name) and no.id == "environ"
    )


def _e_o_getenv(no):
    return (isinstance(no, ast.Attribute) and no.attr == "getenv") or (isinstance(no, ast.Name) and no.id == "getenv")


def _variaveis_lidas(codigo, origem="<código>"):
    """Os nomes das variáveis de ambiente que `codigo` lê. `ValueError` com a
    linha se uma leitura não tiver o nome literal ou numa constante de texto
    do módulo, ou se o ambiente for usado de outra forma (`dict(os.environ)`,
    `os.environ.items()`): o teste não pode dizer que nome é."""
    arvore = ast.parse(codigo)
    constantes = {
        alvo.id: no.value.value
        for no in arvore.body
        if isinstance(no, ast.Assign) and isinstance(no.value, ast.Constant) and isinstance(no.value.value, str)
        for alvo in no.targets
        if isinstance(alvo, ast.Name)
    }
    pais = {filho: pai for pai in ast.walk(arvore) for filho in ast.iter_child_nodes(pai)}

    def _falha(no):
        return ValueError(f"{origem}:{no.lineno}: leitura do ambiente sem nome que este teste consiga ler")

    def _nome(argumento):
        if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
            return argumento.value
        if isinstance(argumento, ast.Name) and argumento.id in constantes:
            return constantes[argumento.id]
        raise _falha(argumento)

    nomes = set()
    for no in ast.walk(arvore):
        pai = pais.get(no)
        avo = pais.get(pai)
        if _e_o_ambiente(no):
            if (
                isinstance(pai, ast.Attribute)
                and pai.attr in _METODOS_QUE_LEEM
                and isinstance(avo, ast.Call)
                and avo.func is pai
                and avo.args
            ):
                nomes.add(_nome(avo.args[0]))
            elif isinstance(pai, ast.Subscript) and pai.value is no:
                nomes.add(_nome(pai.slice))
            elif (
                isinstance(pai, ast.Compare)
                and len(pai.ops) == 1
                and isinstance(pai.ops[0], (ast.In, ast.NotIn))
                and pai.comparators[0] is no
            ):
                nomes.add(_nome(pai.left))
            else:
                raise _falha(no)
        elif _e_o_getenv(no):
            if isinstance(pai, ast.Call) and pai.func is no and pai.args:
                nomes.add(_nome(pai.args[0]))
            else:
                raise _falha(no)
    return nomes


def _lidas_pelo_pacote_crm():
    nomes = set()
    for ficheiro in sorted(PACOTE_CRM.rglob("*.py")):
        if "__pycache__" not in ficheiro.parts:
            nomes |= _variaveis_lidas(ficheiro.read_text(encoding="utf-8"), str(ficheiro.relative_to(BACKEND)))
    return nomes


def _do_env_example():
    return _atribuicoes(ENV_EXAMPLE.read_text(encoding="utf-8"))


# --- Os auxiliares leem o que devem (meta-testes) ----------------------------------------


def test_le_as_leituras_do_ambiente_com_nome_literal_ou_constante_do_modulo():
    codigo = (
        "import os\n"
        "import os as sistema\n"
        "from os import environ, getenv\n"
        'VARIAVEL_B = "NOME_B"\n'
        "def f():\n"
        '    os.environ.get("A")\n'
        '    os.environ.get(VARIAVEL_B, "")\n'
        '    os.environ["C"]\n'
        '    os.getenv("D")\n'
        '    "E" in os.environ\n'
        '    environ.get("F")\n'
        '    getenv("G")\n'
        '    sistema.environ.setdefault("H", "x")\n'
        '    "I" not in os.environ\n'
        '    os.environ.pop("J", None)\n'
    )
    assert _variaveis_lidas(codigo) == {"A", "NOME_B", "C", "D", "E", "F", "G", "H", "I", "J"}


@pytest.mark.parametrize(
    "linha",
    [
        "os.environ.get(nome)",  # nome vindo de fora
        'os.environ.get(f"CRM_{nome}")',
        "os.environ.get(VARIAVEL_NUMERO)",  # constante que não é texto
        "dict(os.environ)",
        "os.environ.items()",
        "os.environ.get()",
        "os.getenv(nome)",
        "ler = os.getenv",
        "os.environ[nome]",
    ],
)
def test_uma_leitura_que_nao_se_resolve_falha_em_vez_de_passar_em_silencio(linha):
    codigo = f"import os\nVARIAVEL_NUMERO = 3\ndef f(nome):\n    {linha}\n"
    with pytest.raises(ValueError, match=r"^x\.py:4: "):
        _variaveis_lidas(codigo, "x.py")


def test_codigo_sem_leituras_do_ambiente_nao_le_nada():
    assert _variaveis_lidas('import os\nCAMINHO = os.path.join("a", "b")\n"""os.environ.get("X")"""\n') == set()


def test_le_as_atribuicoes_e_ignora_comentarios_e_linhas_em_branco():
    texto = "# A=1\n\nB=\n  C=valor com espacos\n#D=\nE=x=y\nnao e atribuicao\n# ===\n"
    assert _atribuicoes(texto) == [(3, "B", ""), (4, "C", "valor com espacos"), (6, "E", "x=y")]


# --- O pacote crm e o backend/.env.example -----------------------------------------------


def test_os_nomes_das_variaveis_da_geoapify():
    """Os nomes do plano (T2.16) e do desenho §4.4, tal e qual."""
    assert config_mapa.VARIAVEL_CHAVE == "CRM_GEOAPIFY_CHAVE_MOSAICOS"
    assert geoapify.VARIAVEL_CHAVE_SERVIDOR == "CRM_GEOAPIFY_CHAVE_SERVIDOR"
    assert geoapify.VARIAVEL_URL == "CRM_GEOAPIFY_URL"


def test_o_pacote_crm_le_exatamente_estas_variaveis():
    """Prova também que a procura não está vazia por engano: encontra as cinco."""
    assert _lidas_pelo_pacote_crm() == LIDAS_PELO_CRM


def test_cada_variavel_que_o_crm_le_tem_o_nome_no_env_example():
    nomes = {nome for _, nome, _ in _do_env_example()}
    faltam = sorted(LIDAS_PELO_CRM - nomes)
    assert faltam == [], "Acrescentar ao bloco do CRM no fim do backend/.env.example (só o nome, sem valor)"


def test_o_env_example_so_tem_variaveis_crm_que_o_pacote_le():
    """Nem nomes a mais (um `CRM_ORS_CHAVE` antes da F3, o
    `CRM_MONGO_TESTE_URL` do ensaio local) nem repetidos."""
    do_crm = [nome for _, nome, _ in _do_env_example() if nome.startswith(PREFIXO_CRM)]
    repetidos = sorted(nome for nome, vezes in Counter(do_crm).items() if vezes > 1)
    assert repetidos == []
    assert set(do_crm) == {nome for nome in LIDAS_PELO_CRM if nome.startswith(PREFIXO_CRM)}


def test_as_variaveis_do_crm_vao_sem_valor():
    """Só os nomes: nenhuma chave entra no git (sem chaves, o CRM usa os
    mosaicos OSM e a pesquisa de morada responde 503)."""
    com_valor = sorted(nome for _, nome, valor in _do_env_example() if nome.startswith(PREFIXO_CRM) and valor != "")
    assert com_valor == []


def test_o_bloco_do_crm_fica_no_fim_do_ficheiro_com_um_cabecalho():
    """Plano T2.16: "bloco no fim com comentário pt-PT". As variáveis do CRM
    vêm todas depois da última do resto do portal, e antes da primeira há o
    cabeçalho do bloco."""
    atribuicoes = _do_env_example()
    linhas_crm = [numero for numero, nome, _ in atribuicoes if nome.startswith(PREFIXO_CRM)]
    linhas_resto = [numero for numero, nome, _ in atribuicoes if not nome.startswith(PREFIXO_CRM)]
    assert linhas_crm and linhas_resto
    assert min(linhas_crm) > max(linhas_resto), "as variáveis do CRM têm de ficar todas no bloco do fim"
    linhas = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    entre = linhas[max(linhas_resto) : min(linhas_crm) - 1]
    cabecalhos = [linha for linha in entre if linha.startswith("#") and CABECALHO_DO_BLOCO in linha]
    assert len(cabecalhos) == 1
