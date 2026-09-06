"""Guarda de regressão: cada chamada do ecrã de bolso aponta para uma rota que
existe MESMO no servidor.

É o mesmo guarda que o POS tem (`tests/faturacao/test_caminhos_do_pos.py`), e
existe pela mesma razão — que ali custou o balcão de uma loja parado com um
`{"detail":"Not Found"}` em inglês à frente da funcionária. O `lib/pos.js`
nasceu com o prefixo errado no `baseURL`, as sete chamadas foram todas para
caminhos inexistentes, e **nada deu por isso**: o ecrã desenha-se na mesma sem
servidor nenhum, o build compila, e a suite do backend prova que as rotas
existem sem nunca perguntar se são as que o frontend escreve.

O Bolso está exposto ao mesmo erro e um pouco mais: as rotas dele não vivem
num router montado com prefixo (como o `faturacao`), vivem no `api_router` do
`server.py`, e o `baseURL` do frontend tem de trazer o `/api/bolso` inteiro.
"""
import os
import re
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402

_RAIZ = Path(__file__).resolve().parents[3]
_BOLSO_JS = _RAIZ / "frontend" / "src" / "lib" / "bolso.js"

_RE_BASE_URL = re.compile(
    r"const\s+API_URL\s*=\s*process\.env\.REACT_APP_BACKEND_URL\s*\+\s*['\"]([^'\"]+)['\"]"
)
_RE_CHAMADA = re.compile(r"\bapi\.(get|post|put|delete|patch)\(\s*(['\"`])([^'\"`]+)\2")


def _normaliza(caminho: str) -> str:
    caminho = re.sub(r"\$\{[^}]*\}", "{}", caminho)
    return re.sub(r"\{[^}]*\}", "{}", caminho)


def _ler() -> str:
    # Falha em vez de saltar: um guarda que se desliga sozinho quando não
    # encontra o que devia vigiar passa a verde para sempre.
    assert _BOLSO_JS.exists(), "Não encontrei %s" % _BOLSO_JS
    return _BOLSO_JS.read_text(encoding="utf-8")


def _caminhos_do_servidor():
    return {
        (metodo, _normaliza(rota.path))
        for rota in server.app.routes
        for metodo in getattr(rota, "methods", ())
    }


def test_o_base_url_do_bolso_traz_o_prefixo_inteiro():
    achado = _RE_BASE_URL.search(_ler())
    assert achado, "Não encontrei a definição de API_URL em frontend/src/lib/bolso.js"
    assert achado.group(1) == "/api/bolso", (
        "O baseURL do Bolso é '%s'. As rotas estão em '/api/bolso' (server.py) "
        "— com outro prefixo, TODAS as chamadas respondem 404." % achado.group(1)
    )


def test_o_bolso_faz_pelo_menos_uma_chamada():
    """Rede de segurança do próprio teste: se a expressão regular deixar de
    casar, o teste seguinte percorria uma lista vazia e dava verde sem
    verificar nada."""
    assert _RE_CHAMADA.findall(_ler()), (
        "Não encontrei nenhuma chamada `api.<verbo>(...)` em bolso.js — a "
        "expressão regular deixou de servir e tem de ser actualizada."
    )


def test_todas_as_chamadas_do_bolso_apontam_para_rotas_que_existem():
    conteudo = _ler()
    prefixo = _RE_BASE_URL.search(conteudo).group(1)
    existentes = _caminhos_do_servidor()

    orfas = [
        "%s %s" % (verbo.upper(), _normaliza(prefixo + caminho))
        for verbo, _aspas, caminho in _RE_CHAMADA.findall(conteudo)
        if (verbo.upper(), _normaliza(prefixo + caminho)) not in existentes
    ]
    assert not orfas, (
        "Estas chamadas do ecrã de bolso não têm rota no servidor e respondem "
        "404 ou 405: %s" % ", ".join(orfas)
    )
