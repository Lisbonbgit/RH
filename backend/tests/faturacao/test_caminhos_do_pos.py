"""Guarda de regressão: cada chamada do ecrã do POS aponta para uma rota que
existe MESMO no servidor.

Porque este ficheiro existe, e o que ele custou: o `frontend/src/lib/pos.js`
nasceu com `baseURL = REACT_APP_BACKEND_URL + '/api'`, mas o módulo está
montado em `/api/faturacao` (ver `faturacao/__init__.py`). Resultado: as sete
chamadas do POS iam todas para `/api/pos/...`, um caminho que não existe. O
FastAPI respondia 404 com o literal `{"detail": "Not Found"}` — e era esse
"Not Found" cru, em inglês, que aparecia à funcionária ao tentar emparelhar o
PC da loja.

O que torna este defeito perigoso não é a correcção (é uma linha), é o
silêncio: **os ecrãs do POS desenham-se todos sem servidor nenhum**. O
emparelhamento, a grelha de caras, a caixa fechada — está tudo lá, bonito, em
claro e escuro. Foram revistos num browser a sério e passaram. Só que nenhuma
chamada chegava ao outro lado, e nada nos testes olhava para os dois lados ao
mesmo tempo: a suite do backend prova que as rotas existem, o build do
frontend prova que o JavaScript compila, e ninguém pergunta se os caminhos
que um escreve são os caminhos que o outro serve.

É essa pergunta, e só essa, que este ficheiro faz. Não liga à base de dados
nem à rede: lê o ficheiro do frontend como texto e confronta-o com o
inventário de rotas do `router` já construído.
"""
import re
from pathlib import Path

import pytest

from faturacao import router

# backend/tests/faturacao/este_ficheiro.py -> raiz do repositório
_RAIZ = Path(__file__).resolve().parents[3]
_POS_JS = _RAIZ / "frontend" / "src" / "lib" / "pos.js"

# `const API_URL = process.env.REACT_APP_BACKEND_URL + '/api/faturacao';`
# — é este sufixo que o defeito trocou, por isso é lido do ficheiro e nunca
# escrito à mão aqui: uma cópia da constante deixaria o teste a passar com o
# frontend errado, que é exactamente a forma de falhar que ele existe para
# apanhar.
_RE_BASE_URL = re.compile(
    r"const\s+API_URL\s*=\s*process\.env\.REACT_APP_BACKEND_URL\s*\+\s*['\"]([^'\"]+)['\"]"
)

# `api.post('/pos/entrar', ...)` e também a forma com template literal,
# `api.put(`/pos/venda/${vendaId}/linhas`, ...)`, que as Tasks 3 e 4 do Plano
# 2C vão usar.
_RE_CHAMADA = re.compile(r"\bapi\.(get|post|put|delete|patch)\(\s*(['\"`])([^'\"`]+)\2")


def _normaliza(caminho: str) -> str:
    """Reduz um caminho à sua FORMA, sem os nomes dos parâmetros: tanto o
    `${vendaId}` do JavaScript como o `{venda_id}` do FastAPI passam a `{}`.
    Sem isto, os dois lados nunca casariam em nenhuma rota com parâmetro — e
    o teste ficava a verificar só as rotas fáceis."""
    caminho = re.sub(r"\$\{[^}]*\}", "{}", caminho)
    return re.sub(r"\{[^}]*\}", "{}", caminho)


def _ler_pos_js() -> str:
    # Falha em vez de saltar (`pytest.skip`) de propósito: um guarda que se
    # desliga sozinho quando não encontra o que devia vigiar é pior do que
    # não existir — passava a verde para sempre e ninguém reparava.
    assert _POS_JS.exists(), (
        "Não encontrei %s — este guarda precisa dos dois lados (frontend e "
        "backend) para ter algum valor." % _POS_JS
    )
    return _POS_JS.read_text(encoding="utf-8")


def _caminhos_do_backend():
    return {_normaliza(route.path) for route in router.routes}


def test_base_url_do_pos_inclui_o_prefixo_do_modulo():
    """O `/faturacao` tem de estar no baseURL — é a linha exacta do defeito."""
    encontrado = _RE_BASE_URL.search(_ler_pos_js())
    assert encontrado, "Não encontrei a definição de API_URL em frontend/src/lib/pos.js"
    assert encontrado.group(1) == "/api/faturacao", (
        "O baseURL do POS é '%s', mas o módulo está montado em '/api/faturacao' "
        "(faturacao/__init__.py). Com este prefixo, TODAS as chamadas do POS "
        "respondem 404 'Not Found'." % encontrado.group(1)
    )


def test_o_pos_faz_pelo_menos_uma_chamada():
    """Rede de segurança do próprio teste: se a expressão regular deixar de
    casar (o ficheiro foi reescrito noutro estilo), o teste seguinte passaria
    a percorrer uma lista vazia e a dar verde sem verificar nada."""
    assert _RE_CHAMADA.findall(_ler_pos_js()), (
        "Não encontrei nenhuma chamada `api.<verbo>(...)` em pos.js — a "
        "expressão regular deste ficheiro deixou de servir e tem de ser "
        "actualizada, senão o guarda abaixo passa a verde sem verificar nada."
    )


def test_todas_as_chamadas_do_pos_apontam_para_rotas_que_existem():
    conteudo = _ler_pos_js()
    base = _RE_BASE_URL.search(conteudo)
    assert base, "Não encontrei a definição de API_URL em frontend/src/lib/pos.js"
    prefixo = base.group(1)

    existentes = _caminhos_do_backend()
    orfas = []
    for verbo, _aspas, caminho in _RE_CHAMADA.findall(conteudo):
        completo = _normaliza(prefixo + caminho)
        if completo not in existentes:
            orfas.append("%s %s" % (verbo.upper(), completo))

    assert orfas == [], (
        "Estas chamadas do POS apontam para caminhos que o servidor não "
        "serve — em produção respondem 404 'Not Found' à funcionária: %s"
        % ", ".join(sorted(orfas))
    )


@pytest.mark.parametrize(
    "caminho_partido",
    ["/api", "/api/faturacao/pos", "/faturacao"],
)
def test_o_guarda_apanha_um_prefixo_errado(caminho_partido):
    """Prova por mutação, feita aqui dentro e não à mão: com qualquer um
    destes prefixos (incluindo o '/api' que o defeito real tinha), as
    chamadas deixam de casar com rotas reais. Se este teste falhar, é o
    guarda de cima que deixou de valer alguma coisa."""
    conteudo = _ler_pos_js()
    existentes = _caminhos_do_backend()
    casam = [
        caminho
        for _verbo, _aspas, caminho in _RE_CHAMADA.findall(conteudo)
        if _normaliza(caminho_partido + caminho) in existentes
    ]
    assert casam == [], (
        "Com o prefixo '%s' estas chamadas ainda casavam com rotas reais (%s) "
        "— o guarda não distingue o prefixo certo do errado." % (caminho_partido, casam)
    )


# --- O backoffice, pela mesma razão -------------------------------------------
#
# A guarda acima nasceu do POS, mas o defeito que a motivou não tem nada de
# especificamente-POS: um caminho escrito num sítio, servido noutro, e nada a
# olhar para os dois ao mesmo tempo. O `lib/faturacao.js` tem 45 wrappers e
# estava sem rede nenhuma — incluindo o ecrã das reservas fiscais presas, que
# é a única forma de destrancar uma venda cuja fatura ficou por confirmar. Um
# caminho errado ali significa o gestor a olhar para um ecrã que responde 404
# enquanto a loja não consegue fechar a caixa.
#
# A forma é outra (`axios.get(`${API_URL}/faturacao/lojas`)`, com o prefixo
# dentro do template literal em vez de num baseURL), por isso a extracção é
# própria — mas a pergunta que se faz é exactamente a mesma.
_FATURACAO_JS = _RAIZ / "frontend" / "src" / "lib" / "faturacao.js"

_RE_CHAMADA_BACKOFFICE = re.compile(
    r"\baxios\.(get|post|put|delete|patch)\(\s*`\$\{API_URL\}([^`]*)`"
)


def _ler_faturacao_js() -> str:
    assert _FATURACAO_JS.exists(), (
        "Não encontrei %s — este guarda precisa dos dois lados." % _FATURACAO_JS
    )
    return _FATURACAO_JS.read_text(encoding="utf-8")


def _sem_query(caminho: str) -> str:
    """`/faturacao/dashboard?ano=${ano}` -> `/faturacao/dashboard`. O que se
    compara com o router é o CAMINHO; os parâmetros de consulta não fazem
    parte dele (o FastAPI declara-os na assinatura da função)."""
    return caminho.split("?", 1)[0]


def test_o_backoffice_faz_chamadas_que_este_guarda_reconhece():
    """Mesma rede de segurança do `test_o_pos_faz_pelo_menos_uma_chamada`: se a
    expressão regular deixar de casar, o teste seguinte percorria uma lista
    vazia e dava verde sem verificar nada."""
    achadas = _RE_CHAMADA_BACKOFFICE.findall(_ler_faturacao_js())
    assert len(achadas) >= 40, (
        "Só reconheci %d chamadas em lib/faturacao.js — o ficheiro tem dezenas. "
        "A expressão regular deste guarda deixou de servir e tem de ser "
        "actualizada." % len(achadas)
    )


def test_todas_as_chamadas_do_backoffice_apontam_para_rotas_que_existem():
    existentes = _caminhos_do_backend()
    orfas = []
    for verbo, caminho in _RE_CHAMADA_BACKOFFICE.findall(_ler_faturacao_js()):
        # O API_URL do backoffice é `REACT_APP_BACKEND_URL + '/api'` e o
        # `/faturacao` vem escrito em cada caminho — ao contrário do POS, onde
        # vive no baseURL. Duas convenções diferentes no mesmo repositório, o
        # que é precisamente o tipo de coisa que produz o defeito original.
        completo = _normaliza("/api" + _sem_query(caminho))
        if completo not in existentes:
            orfas.append("%s %s" % (verbo.upper(), completo))

    assert orfas == [], (
        "Estas chamadas do backoffice apontam para caminhos que o servidor não "
        "serve: %s" % ", ".join(sorted(orfas))
    )
