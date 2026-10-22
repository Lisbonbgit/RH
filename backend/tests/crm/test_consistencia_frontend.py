"""O que existe nos dois lados tem de ser igual nos dois lados.

As fases do browser (frontend/src/lib/crm/fases.js) têm de ser as do servidor
(crm/dominio/fases.py), pela mesma ordem: os pinos, os filtros e o formulário
usam as do JavaScript, e a API só aceita as do Python. Porta do
tests/Unit/FasesConsistenciaTest.php do CRM autónomo (plano, correção
"T2.20 (consistência fases frontend↔backend)").

O JavaScript é lido como texto (não há forma de o executar aqui), e a lista
nunca se copia para este teste: uma cópia deixava-o verde com um dos lados
mudado. Por isso o fases.js mantém a ORDEM numa só linha
(`export const ORDEM = Object.freeze([...]);`) e cada fase de FASES numa linha
que começa por `<fase>: Object.freeze({ id: '<fase>', rotulo: …, cor: …`.

Se o ficheiro do frontend não estiver lá, os testes falham em vez de saltar,
como o tests/faturacao/test_caminhos_do_pos.py: um guarda que se desliga
sozinho passava a verde para sempre.

O GPS (T2.22) segue a mesma regra: o gps.js tem uma só linha
`export const LIMITE_PRECISAO_M = <inteiro>;`, igual a geo.LIMITE_PRECISAO_M,
e uma só linha `export const MENSAGEM_LOCALIZACAO_IMPRECISA = '<texto>';`,
igual a geo.MENSAGEM_GPS. A mais, a mensagem da morada sugerida do morada.js
(MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL), que o ecrã mostra no lugar da do 503
do servidor (crm/morada.py, INVERSA_INDISPONIVEL), também numa só linha. A da
pesquisa de moradas (MENSAGEM_MORADA_INDISPONIVEL) saiu do frontend na G11 do
plano do mapa Google, com a pesquisa da Geoapify (a pesquisa é a da Google).

As rotas (F3 / T3.27) também: o rota.js tem uma só linha
`export const MOTIVOS = Object.freeze([...]);`, igual a dominio.rotas.MOTIVOS;
uma só linha `export const MOTIVO_POR_FASE = Object.freeze({ fase: 'motivo', … });`,
igual a dominio.rotas.MOTIVO_POR_FASE (também pela ordem); e uma só linha
`export const LIMITE_PARAGENS = <inteiro>;`, igual a dominio.rotas.LIMITE_PARAGENS.
O rota.test.js faz a mesma comparação no outro sentido (lê o rotas.py).
"""
import re
from pathlib import Path

import pytest

from crm import morada
from crm.dominio import geo, rotas
from crm.dominio.fases import ORDEM

# backend/tests/crm/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_LIB_CRM = _RAIZ / "frontend" / "src" / "lib" / "crm"
FASES_JS = _LIB_CRM / "fases.js"
GPS_JS = _LIB_CRM / "gps.js"
MORADA_JS = _LIB_CRM / "morada.js"
ROTA_JS = _LIB_CRM / "rota.js"

_RE_LINHA_ORDEM = re.compile(r"^export const ORDEM = Object\.freeze\(\[([^\]\n]*)\]\);$", re.M)
_RE_NOME = re.compile(r"'([^']*)'")
_RE_CHAVE_FASES = re.compile(r"^\s*([a-z]+): Object\.freeze\(\{ id: ", re.M)
# Um item de uma lista ou de um mapa de uma linha: só um texto entre plicas, sem escapes.
_RE_ITEM_TEXTO = re.compile(r"'([a-z_]+)'")
_RE_ITEM_PAR = re.compile(r"([a-z_]+): '([a-z_]+)'")


def _ler(caminho: Path) -> str:
    assert caminho.exists(), (
        "Não encontrei %s — este guarda precisa dos dois lados (frontend e backend)." % caminho
    )
    return caminho.read_text(encoding="utf-8")


def _ordens_do_js(texto: str) -> list:
    """Os nomes de cada linha `export const ORDEM = Object.freeze([...]);`."""
    return [tuple(_RE_NOME.findall(m.group(1))) for m in _RE_LINHA_ORDEM.finditer(texto)]


def _inteiros_do_js(texto: str, nome: str) -> list:
    """Os valores de cada linha `export const <nome> = <inteiro>;`."""
    padrao = re.compile(r"^export const %s = ([0-9]+);$" % re.escape(nome), re.M)
    return [int(m.group(1)) for m in padrao.finditer(texto)]


def _textos_do_js(texto: str, nome: str) -> list:
    """Os textos de cada linha `export const <nome> = '<texto>';` (ou entre aspas
    duplas), sem escapes: com uma barra o texto lido já não seria o do ecrã."""
    padrao = re.compile(
        r"""^export const %s = (?:'([^'\\\n]*)'|"([^"\\\n]*)");$""" % re.escape(nome), re.M
    )
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in padrao.finditer(texto)]


def _itens(conteudo: str, padrao):
    """Os itens de `a, b, c` que casam por inteiro com `padrao`, ou `None` se
    algum não casar (um nome, um número, aspas duplas, um comentário)."""
    itens = [item.strip() for item in conteudo.split(",")]
    casados = [padrao.fullmatch(item) for item in itens]
    if any(casado is None for casado in casados):
        return None
    return tuple(casado.groups() if casado.re.groups > 1 else casado.group(1) for casado in casados)


def _listas_do_js(texto: str, nome: str) -> list:
    """Os textos de cada linha `export const <nome> = Object.freeze(['a', 'b']);`
    (`None` numa linha com outra coisa entre os parênteses retos)."""
    padrao = re.compile(r"^export const %s = Object\.freeze\(\[([^\]\n]*)\]\);$" % re.escape(nome), re.M)
    return [_itens(m.group(1), _RE_ITEM_TEXTO) for m in padrao.finditer(texto)]


def _mapas_do_js(texto: str, nome: str) -> list:
    """Os pares de cada linha `export const <nome> = Object.freeze({ a: 'x', b: 'y' });`,
    pela ordem (`None` numa linha com outra coisa entre as chavetas)."""
    padrao = re.compile(r"^export const %s = Object\.freeze\(\{ ([^{}\n]*) \}\);$" % re.escape(nome), re.M)
    return [_itens(m.group(1), _RE_ITEM_PAR) for m in padrao.finditer(texto)]


# --- O leitor (provado primeiro, para um verde nunca vir de um regex cego) ---


def test_o_leitor_encontra_a_ordem_numa_so_linha():
    texto = "// x\nexport const ORDEM = Object.freeze(['a', 'b']);\nexport const FUNIL = Object.freeze(['b', 'a']);\n"
    assert _ordens_do_js(texto) == [("a", "b")]


@pytest.mark.parametrize(
    "texto",
    [
        "export const ORDEM = Object.freeze([\n  'a',\n  'b',\n]);\n",
        "export const ORDEM = ['a', 'b'];\n",
        "  export const ORDEM = Object.freeze(['a', 'b']);\n",
        "export const ORDEM = Object.freeze(['a', 'b']); // fim\n",
    ],
    ids=["partida em varias linhas", "sem freeze", "indentada", "com comentario no fim"],
)
def test_o_leitor_nao_aceita_outra_forma_da_linha(texto):
    assert _ordens_do_js(texto) == []


def test_o_leitor_encontra_um_inteiro_numa_so_linha():
    texto = "// x\nexport const LIMITE_PRECISAO_M = 50;\nexport const LIMITE_PRECISAO_M_MAXIMO = 7;\n"
    assert _inteiros_do_js(texto, "LIMITE_PRECISAO_M") == [50]


@pytest.mark.parametrize(
    "texto",
    [
        "export const LIMITE_PRECISAO_M =\n  50;\n",
        "export const LIMITE_PRECISAO_M = 50.0;\n",
        "export const LIMITE_PRECISAO_M = 5e1;\n",
        "export const LIMITE_PRECISAO_M = '50';\n",
        "  export const LIMITE_PRECISAO_M = 50;\n",
        "export const LIMITE_PRECISAO_M = 50; // fim\n",
        "const LIMITE_PRECISAO_M = 50;\n",
        "export const LIMITE_PRECISAO = 50;\n",
    ],
    ids=[
        "partida em duas linhas",
        "com casas decimais",
        "com expoente",
        "em texto",
        "indentada",
        "com comentario no fim",
        "sem export",
        "outro nome",
    ],
)
def test_o_leitor_de_inteiros_nao_aceita_outra_forma_da_linha(texto):
    assert _inteiros_do_js(texto, "LIMITE_PRECISAO_M") == []


def test_o_leitor_encontra_um_texto_numa_so_linha():
    simples = "export const MENSAGEM = 'Localização imprecisa — ajuste o pino';\nexport const MENSAGEM_B = 'x';\n"
    assert _textos_do_js(simples, "MENSAGEM") == ["Localização imprecisa — ajuste o pino"]
    duplas = "export const MENSAGEM = \"use 'Estou nesta loja'\";\n"
    assert _textos_do_js(duplas, "MENSAGEM") == ["use 'Estou nesta loja'"]


@pytest.mark.parametrize(
    "texto",
    [
        "export const MENSAGEM =\n  'abc';\n",
        "export const MENSAGEM = 'a\\'b';\n",
        "export const MENSAGEM = `abc`;\n",
        "export const MENSAGEM = 'abc\";\n",
        "  export const MENSAGEM = 'abc';\n",
        "export const MENSAGEM = 'abc'; // fim\n",
        "export const MENSAGEM = 'abc' + 'd';\n",
    ],
    ids=[
        "partida em duas linhas",
        "com escape",
        "template",
        "aspas trocadas",
        "indentada",
        "com comentario no fim",
        "concatenada",
    ],
)
def test_o_leitor_de_textos_nao_aceita_outra_forma_da_linha(texto):
    assert _textos_do_js(texto, "MENSAGEM") == []


def test_o_leitor_encontra_uma_lista_de_textos_numa_so_linha():
    texto = "// x\nexport const MOTIVOS = Object.freeze(['a', 'b_c']);\nexport const MOTIVOS_B = Object.freeze(['z']);\n"
    assert _listas_do_js(texto, "MOTIVOS") == [("a", "b_c")]


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("export const MOTIVOS = Object.freeze([\n  'a',\n  'b',\n]);\n", []),
        ("export const MOTIVOS = ['a', 'b'];\n", []),
        ("  export const MOTIVOS = Object.freeze(['a', 'b']);\n", []),
        ("export const MOTIVOS = Object.freeze(['a', 'b']); // fim\n", []),
        ("export const MOTIVOS = Object.freeze(['a', B, 'c']);\n", [None]),
        ("export const MOTIVOS = Object.freeze(['a', \"b\"]);\n", [None]),
        ("export const MOTIVOS = Object.freeze(['a', 'b',]);\n", [None]),
        ("export const MOTIVOS = Object.freeze(['a', ...B]);\n", [None]),
    ],
    ids=[
        "partida em varias linhas",
        "sem freeze",
        "indentada",
        "com comentario no fim",
        "com um nome",
        "com aspas duplas",
        "com virgula no fim",
        "com espalhamento",
    ],
)
def test_o_leitor_de_listas_nao_aceita_outra_forma(texto, esperado):
    assert _listas_do_js(texto, "MOTIVOS") == esperado


def test_o_leitor_encontra_um_mapa_numa_so_linha_pela_ordem():
    texto = (
        "// x\nexport const MOTIVO_POR_FASE = Object.freeze({ b: 'x', a: 'y_z' });\n"
        "export const MOTIVO_POR_FASE_B = Object.freeze({ c: 'w' });\n"
    )
    assert _mapas_do_js(texto, "MOTIVO_POR_FASE") == [(("b", "x"), ("a", "y_z"))]


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("export const M = Object.freeze({\n  a: 'x',\n});\n", []),
        ("export const M = { a: 'x' };\n", []),
        ("export const M = Object.freeze({a: 'x'});\n", []),
        ("  export const M = Object.freeze({ a: 'x' });\n", []),
        ("export const M = Object.freeze({ a: 'x' }); // fim\n", []),
        ("export const M = Object.freeze({ a: 'x', b: Y });\n", [None]),
        ("export const M = Object.freeze({ a: 'x', 'b': 'y' });\n", [None]),
        ("export const M = Object.freeze({ a: \"x\" });\n", [None]),
        ("export const M = Object.freeze({ a: 'x', ...B });\n", [None]),
    ],
    ids=[
        "partida em varias linhas",
        "sem freeze",
        "sem espacos dentro das chavetas",
        "indentada",
        "com comentario no fim",
        "com um nome",
        "com chave entre plicas",
        "com aspas duplas",
        "com espalhamento",
    ],
)
def test_o_leitor_de_mapas_nao_aceita_outra_forma(texto, esperado):
    assert _mapas_do_js(texto, "M") == esperado


# --- As fases ---


def test_a_ordem_do_js_e_igual_a_do_servidor():
    ordens = _ordens_do_js(_ler(FASES_JS))
    assert len(ordens) == 1, (
        'fases.js tem de ter uma só linha "export const ORDEM = Object.freeze([...]);"'
    )
    assert ordens[0] == ORDEM


@pytest.mark.parametrize("fase", ORDEM, ids=list(ORDEM))
def test_cada_fase_da_ordem_tem_rotulo_e_cor_no_js(fase):
    padrao = re.compile(
        r"^\s*%s: Object\.freeze\(\{ id: '%s', rotulo: '[^']+', cor: '#[0-9a-f]{6}', " % (fase, fase),
        re.M,
    )
    assert padrao.search(_ler(FASES_JS)), "fases.js: falta a fase %s em FASES" % fase


def test_fases_do_js_tem_as_mesmas_fases_da_ordem_pela_mesma_ordem():
    assert tuple(_RE_CHAVE_FASES.findall(_ler(FASES_JS))) == ORDEM


# --- O GPS (T2.22) ---


def test_o_limite_da_precisao_do_js_e_o_do_servidor():
    valores = _inteiros_do_js(_ler(GPS_JS), "LIMITE_PRECISAO_M")
    assert len(valores) == 1, 'gps.js tem de ter uma só linha "export const LIMITE_PRECISAO_M = <n>;"'
    assert valores[0] == geo.LIMITE_PRECISAO_M


def test_a_mensagem_da_localizacao_imprecisa_do_js_e_a_do_servidor():
    textos = _textos_do_js(_ler(GPS_JS), "MENSAGEM_LOCALIZACAO_IMPRECISA")
    assert len(textos) == 1, (
        "gps.js tem de ter uma só linha \"export const MENSAGEM_LOCALIZACAO_IMPRECISA = '<texto>';\""
    )
    assert textos[0] == geo.MENSAGEM_GPS


# --- A morada (extra da T2.22: as mensagens do 503 nos dois lados) ---


@pytest.mark.parametrize(
    "nome_js, mensagem_do_servidor",
    [
        ("MENSAGEM_MORADA_SUGERIDA_INDISPONIVEL", morada.INVERSA_INDISPONIVEL),
    ],
    ids=["inversa"],
)
def test_as_mensagens_da_morada_do_js_sao_as_do_servidor(nome_js, mensagem_do_servidor):
    textos = _textos_do_js(_ler(MORADA_JS), nome_js)
    assert len(textos) == 1, "morada.js tem de ter uma só linha \"export const %s = '<texto>';\"" % nome_js
    assert textos[0] == mensagem_do_servidor


# --- As rotas (F3 / T3.27) ---


def test_os_motivos_do_js_sao_os_do_servidor():
    listas = _listas_do_js(_ler(ROTA_JS), "MOTIVOS")
    assert len(listas) == 1, 'rota.js tem de ter uma só linha "export const MOTIVOS = Object.freeze([...]);"'
    assert listas[0] == rotas.MOTIVOS


def test_o_motivo_por_fase_do_js_e_o_do_servidor_pela_mesma_ordem():
    mapas = _mapas_do_js(_ler(ROTA_JS), "MOTIVO_POR_FASE")
    assert len(mapas) == 1, (
        "rota.js tem de ter uma só linha \"export const MOTIVO_POR_FASE = Object.freeze({ fase: 'motivo', … });\""
    )
    assert mapas[0] == tuple(rotas.MOTIVO_POR_FASE.items())
    # As fases são as do servidor, pela ordem delas (o MOTIVO_POR_FASE cobre-as todas).
    assert tuple(fase for fase, _ in mapas[0]) == ORDEM


def test_o_limite_de_paragens_do_js_e_o_do_servidor():
    valores = _inteiros_do_js(_ler(ROTA_JS), "LIMITE_PARAGENS")
    assert len(valores) == 1, 'rota.js tem de ter uma só linha "export const LIMITE_PARAGENS = <n>;"'
    assert valores[0] == rotas.LIMITE_PARAGENS
