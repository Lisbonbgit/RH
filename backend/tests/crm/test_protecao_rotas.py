"""Guarda de regressão: cada rota do CRM está numa família explícita e tem a
guarda dessa família — nenhuma fica aberta por esquecimento (plano T1.8;
desenho §3.3; dossiê §4, "Famílias de rotas").

Molde de tests/faturacao/test_protecao_rotas.py (a mesma função recursiva
`_dependencias`), com uma diferença: aqui uma rota é o par (método, caminho),
porque o mesmo caminho tem métodos com guardas diferentes — `GET /regioes`
para o escritório e `POST /regioes` só para o admin (F2).

Quatro famílias; cada rota está em exatamente uma:
- PÚBLICA (`ROTAS_PUBLICAS`): `GET /saude`, que não toca na base. Sem sessão.
- QUALQUER SESSÃO VÁLIDA (`ROTAS_DE_SESSAO`): `GET /eu`. Depende de
  `utilizador_atual` e NUNCA de `membro_crm_atual`: quem não é membro recebe
  `membro: false`, nunca 403.
- TAREFAS AGENDADAS (`ROTAS_DE_CRON`, vazia até à F5): `/api/crm/cron/*`, sem
  sessão. A guarda é a dependência `crm.auth.exigir_cron_key` (a `CRON_KEY`
  comparada com `secrets.compare_digest` e fechada quando a variável falta,
  com testes próprios em test_cron_key.py), exigida AQUI em cada rota desta
  lista — pela própria função, não por um nome ou atributo: "sem sessão" não
  chega, porque uma rota de cron sem a chave ficava aberta a toda a gente
  (revisão da F0/F1, AC-1). Qualquer caminho `/api/crm/cron/` tem de estar
  nesta lista, e só esses.
- MEMBRO COM PERFIL (`PERFIS_POR_ROTA`): todas as outras. Dependem de
  `membro_crm_atual` através de exatamente UMA guarda `exigir_perfil(...)`,
  com `perfis_crm` igual ao da tabela.

Em todas: o corpo lê-se com `crm.pedidos.corpo_json` e nunca por um modelo
(o FastAPI lê esses corpos ANTES das dependências), e `corpo_json` só depois
da guarda — um pedido sem sessão e com JSON partido dá 401/403, nunca 400
(plano §1, "Corpos JSON"; correções, linha "T1.3 / T2.15").

Uma rota nova falha o teste (1) até ser classificada aqui. Cada tarefa que
cria rotas classifica-as nesta tabela no passo "teste primeiro" (correções do
plano, linha "T2.9–T2.15 vs T2.16"). Acrescentar em consciência, nunca só
para o teste passar: uma rota em ROTAS_PUBLICAS ou ROTAS_DE_CRON fica aberta
a quem não tem sessão. A tabela confere-se ainda com a §4 do plano, escrita
como regra por recurso (`_perfis_pela_regra_da_api`, T2.16).

A lógica está em `_classificar(router, …)` e é provada primeiro contra
routers descartáveis (correções do plano, linha "T1.8"): um teste que passa à
primeira contra o router verdadeiro não prova que apanha uma rota sem guarda.
"""
from collections import Counter, namedtuple
from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import crm
from crm.auth import ESCRITORIO, SO_ADMIN, exigir_cron_key, exigir_perfil, membro_crm_atual
from crm.pedidos import corpo_json
from faturacao.auth import utilizador_atual

PREFIXO = "/api/crm"
PREFIXO_CRON = "/api/crm/cron/"

ROTAS_PUBLICAS = {("GET", "/api/crm/saude")}
ROTAS_DE_SESSAO = {("GET", "/api/crm/eu")}
# F5: as tarefas agendadas (`/api/crm/cron/*`), cada uma com a guarda
# `crm.auth.exigir_cron_key` (`CRON_KEY` + `secrets.compare_digest`, fechada
# sem a variável). Vazia, mas o teste (4) já obriga qualquer caminho
# `/api/crm/cron/` a estar aqui, e com essa guarda.
ROTAS_DE_CRON = set()

# Os perfis de rota da F1–F2 (plano §1). Escritos à mão de propósito, e não
# copiados de SO_ADMIN.perfis_crm: comparar a guarda consigo mesma não provava
# nada. O motorista só ganha rotas na F4.
PERFIS_ADMIN = frozenset({"admin"})
PERFIS_ESCRITORIO = frozenset({"admin", "utilizador"})

PERFIS_POR_ROTA = {
    # Membros (T1.6, T1.7): só o admin do CRM.
    ("GET", "/api/crm/membros"): PERFIS_ADMIN,
    ("GET", "/api/crm/membros/candidatos"): PERFIS_ADMIN,
    ("POST", "/api/crm/membros"): PERFIS_ADMIN,
    ("PATCH", "/api/crm/membros/{membro_id}"): PERFIS_ADMIN,
    ("DELETE", "/api/crm/membros/{membro_id}"): PERFIS_ADMIN,
    # Regiões (T2.9): o escritório lê-as (filtros do mapa, região da loja);
    # só o admin as cria, lhes muda o nome e a ordem e as apaga.
    ("GET", "/api/crm/regioes"): PERFIS_ESCRITORIO,
    ("POST", "/api/crm/regioes"): PERFIS_ADMIN,
    ("PATCH", "/api/crm/regioes/{regiao_id}"): PERFIS_ADMIN,
    ("DELETE", "/api/crm/regioes/{regiao_id}"): PERFIS_ADMIN,
    # Lojas (T2.10): o escritório lista-as, lê-as e cria-as (desenho §3.3;
    # o motorista só ganha o POST na F4).
    ("GET", "/api/crm/lojas"): PERFIS_ESCRITORIO,
    ("POST", "/api/crm/lojas"): PERFIS_ESCRITORIO,
    ("GET", "/api/crm/lojas/{loja_id}"): PERFIS_ESCRITORIO,
    # Editar uma loja (T2.11): o escritório (a fase num toque, a ficha); as
    # correções do terreno (motorista) chegam na F4.
    ("PATCH", "/api/crm/lojas/{loja_id}"): PERFIS_ESCRITORIO,
    # Apagar uma loja (T2.12): o escritório, só os enganos (sem histórico).
    ("DELETE", "/api/crm/lojas/{loja_id}"): PERFIS_ESCRITORIO,
    # Definições da fábrica (T2.13): só o admin as vê e as muda.
    ("GET", "/api/crm/definicoes"): PERFIS_ADMIN,
    ("PATCH", "/api/crm/definicoes"): PERFIS_ADMIN,
    # Configuração do mapa (T2.13): todo o escritório abre o mapa; leva a
    # chave dos mosaicos, por isso nunca é pública.
    ("GET", "/api/crm/config"): PERFIS_ESCRITORIO,
    # Pesquisa de morada e morada sugerida (T2.15): o escritório, ao criar e
    # corrigir lojas; gastam créditos da chave do servidor, por isso nunca
    # são públicas (o motorista só ganha rotas na F4).
    ("GET", "/api/crm/morada/pesquisa"): PERFIS_ESCRITORIO,
    ("GET", "/api/crm/morada/inversa"): PERFIS_ESCRITORIO,
    # Rotas (F3, T3.18): a lista dos dias e a rota de um dia, para o
    # escritório (plano F3 §4: todas as rotas novas são para o escritório; o
    # motorista só ganha rotas na F4).
    ("GET", "/api/crm/rotas"): PERFIS_ESCRITORIO,
    ("GET", "/api/crm/rotas/{data}"): PERFIS_ESCRITORIO,
    # Adicionar uma loja à rota de um dia (T3.19): o escritório, pelo cartão
    # do mapa e pelo planeador.
    ("POST", "/api/crm/rotas/{data}/paragens"): PERFIS_ESCRITORIO,
    # Alterar a rota de um dia (T3.20): as definições do dia, a ordem, as
    # paragens, retirar e "Guardar rota", pelo planeador do escritório.
    ("PATCH", "/api/crm/rotas/{data}"): PERFIS_ESCRITORIO,
    # Recalcular as horas da rota pelo Directions do openrouteservice (T3.21):
    # o planeador do escritório (gasta a quota da chave do servidor).
    ("POST", "/api/crm/rotas/{data}/recalcular"): PERFIS_ESCRITORIO,
}

# Os motivos de `_classificar` (os meta-testes comparam-nos tal e qual).
USA_SESSAO = "usa a sessão do portal, e esta família não pode"
SEM_UTILIZADOR_ATUAL = "não depende de utilizador_atual"
USA_MEMBRO = "depende de membro_crm_atual: um não-membro levava 403"
SEM_MEMBRO = "não depende de membro_crm_atual"
GUARDA_SEM_MEMBRO = "a guarda de perfil não assenta em membro_crm_atual"
CORPO_ANTES_DA_GUARDA = "lê o corpo (corpo_json) antes da guarda: sem sessão e com JSON partido dava 400"
CORPO_POR_MODELO = "corpo declarado por modelo, que o FastAPI lê antes da sessão: usar corpo_json"
CRON_FORA_DA_LISTA = "caminho /api/crm/cron/ fora de ROTAS_DE_CRON"
CRON_SEM_O_CAMINHO = "em ROTAS_DE_CRON sem ser um caminho /api/crm/cron/"
SEM_CRON_KEY = "não exige a CRON_KEY (crm.auth.exigir_cron_key): ficava aberta a toda a gente"
REPETIDA = "declarada mais de uma vez no router: só a primeira responde"


def _numero_de_guardas(n):
    return f"{n} guardas de perfil: tem de ser exatamente uma"


def _perfis_errados(tem, pede):
    return f"guarda com os perfis {sorted(tem)}, a tabela pede {sorted(pede)}"


def _varias_familias(nomes):
    return "em mais de uma família: " + ", ".join(nomes)


Classificacao = namedtuple("Classificacao", "por_classificar sem_rota guarda_errada")
TUDO_CERTO = Classificacao([], [], [])


def _dependencias(dependente):
    """Todos os `call` das dependências, recursivamente (molde de
    tests/faturacao/test_protecao_rotas.py), pela ordem em que o FastAPI os
    chama: as sub-dependências de cada uma, depois ela, pela ordem em que
    estão declaradas. Por isso a ordem diz também quem responde primeiro (a
    sessão ou o corpo)."""
    chamadas = []

    def _procura(d):
        for sub in d.dependencies:
            _procura(sub)
            chamadas.append(sub.call)

    if dependente is not None:
        _procura(dependente)
    return chamadas


def _pares(router):
    """`[((método, caminho), rota)]`, um por método. Uma rota sem métodos
    (WebSocket, Mount) entra como "SEM_METODO", que nenhuma lista tem: fica
    por classificar."""
    return [
        ((metodo, getattr(rota, "path", repr(rota))), rota)
        for rota in router.routes
        for metodo in sorted(getattr(rota, "methods", None) or {"SEM_METODO"})
    ]


def _guardas(dependente):
    """Os nós das guardas de perfil (os que têm `perfis_crm`), a qualquer
    profundidade e com repetições."""
    nos = []

    def _procura(d):
        for sub in d.dependencies:
            if getattr(sub.call, "perfis_crm", None) is not None:
                nos.append(sub)
            _procura(sub)

    if dependente is not None:
        _procura(dependente)
    return nos


def _motivos(familia, rota, perfis):
    """O que está errado na guarda de `rota` para a sua `familia`
    ("publica", "sessao", "cron" ou "perfil"; `perfis` só na última)."""
    dependente = getattr(rota, "dependant", None)
    chamadas = _dependencias(dependente)
    guardas = _guardas(dependente)
    motivos = []
    if getattr(rota, "body_field", None) is not None:
        motivos.append(CORPO_POR_MODELO)
    protecao = None  # o que tem de responder antes de o corpo ser lido
    if familia in ("publica", "cron"):
        if utilizador_atual in chamadas or membro_crm_atual in chamadas or guardas:
            motivos.append(USA_SESSAO)
        if familia == "cron":
            if exigir_cron_key not in chamadas:
                motivos.append(SEM_CRON_KEY)
            protecao = exigir_cron_key
    elif familia == "sessao":
        if utilizador_atual not in chamadas:
            motivos.append(SEM_UTILIZADOR_ATUAL)
        if membro_crm_atual in chamadas or guardas:
            motivos.append(USA_MEMBRO)
        protecao = utilizador_atual
    else:
        if membro_crm_atual not in chamadas:
            motivos.append(SEM_MEMBRO)
        if len(guardas) != 1:
            motivos.append(_numero_de_guardas(len(guardas)))
        else:
            guarda = guardas[0]
            if guarda.call.perfis_crm != frozenset(perfis):
                motivos.append(_perfis_errados(guarda.call.perfis_crm, perfis))
            if membro_crm_atual not in _dependencias(guarda):
                motivos.append(GUARDA_SEM_MEMBRO)
            protecao = guarda.call
    if corpo_json in chamadas and protecao in chamadas and chamadas.index(corpo_json) < chamadas.index(protecao):
        motivos.append(CORPO_ANTES_DA_GUARDA)
    return motivos


def _classificar(
    router,
    publicas=ROTAS_PUBLICAS,
    de_sessao=ROTAS_DE_SESSAO,
    de_cron=ROTAS_DE_CRON,
    perfis_por_rota=PERFIS_POR_ROTA,
):
    """Compara as rotas de `router` com as quatro listas (por omissão, as
    deste ficheiro) e devolve `Classificacao`:
    - `por_classificar`: pares (método, caminho) do router que não estão em
      lista nenhuma;
    - `sem_rota`: pares das listas que o router não tem;
    - `guarda_errada`: `(método, caminho, motivo)` de cada rota classificada
      cuja guarda não é a da sua família.
    Tudo ordenado e sem repetições, para as mensagens de falha serem estáveis.
    """
    familias = {}
    for nome, lista in (("publica", publicas), ("sessao", de_sessao), ("cron", de_cron), ("perfil", perfis_por_rota)):
        for par in lista:
            familias.setdefault(par, []).append(nome)
    pares = _pares(router)
    vezes = Counter(par for par, _ in pares)
    por_classificar, guarda_errada = set(), set()
    for par, rota in pares:
        metodo, caminho = par
        nomes = familias.get(par)
        if not nomes:
            por_classificar.add(par)
            continue
        motivos = []
        if vezes[par] > 1:
            motivos.append(REPETIDA)
        if len(nomes) > 1:
            motivos.append(_varias_familias(nomes))
        else:
            familia = nomes[0]
            if caminho.startswith(PREFIXO_CRON) and familia != "cron":
                motivos.append(CRON_FORA_DA_LISTA)
            if familia == "cron" and not caminho.startswith(PREFIXO_CRON):
                motivos.append(CRON_SEM_O_CAMINHO)
            motivos += _motivos(familia, rota, perfis_por_rota.get(par))
        guarda_errada.update((metodo, caminho, motivo) for motivo in motivos)
    sem_rota = set(familias) - {par for par, _ in pares}
    return Classificacao(sorted(por_classificar), sorted(sem_rota), sorted(guarda_errada))


# --- Meta-testes: `_classificar` apanha o que deve, num router descartável -------------


async def _resposta():
    return {}


class _Corpo(BaseModel):
    nome: str


async def _resposta_com_modelo(corpo: _Corpo):
    return {}


def _router(*rotas):
    """Um router descartável com o prefixo do CRM. Cada rota é
    `(método, caminho sem o prefixo, [dependências pela ordem], endpoint?)`."""
    router = APIRouter(prefix=PREFIXO)
    for metodo, caminho, dependencias, *endpoint in rotas:
        router.add_api_route(
            caminho,
            endpoint[0] if endpoint else _resposta,
            methods=[metodo],
            dependencies=[Depends(d) for d in dependencias],
        )
    return router


def _classificar_com(router, publicas=(), sessao=(), cron=(), perfis=None):
    """`_classificar` com listas próprias (vazias por omissão)."""
    return _classificar(router, set(publicas), set(sessao), set(cron), dict(perfis or {}))


def _errada(metodo, caminho, *motivos):
    return [(metodo, PREFIXO + caminho, m) for m in motivos]


def test_meta_apanha_a_rota_sem_guarda_e_a_guarda_com_o_perfil_errado():
    """Correções do plano, linha "T1.8": uma rota sem guarda (e por
    classificar) e uma `exigir_perfil("admin")` onde a tabela pede
    admin+utilizador. É o meta-teste que falha primeiro."""
    router = _router(
        ("GET", "/sem-guarda", []),
        ("GET", "/perfil-errado", [exigir_perfil("admin")]),
    )
    resultado = _classificar_com(router, perfis={("GET", "/api/crm/perfil-errado"): PERFIS_ESCRITORIO})
    assert resultado == Classificacao(
        [("GET", "/api/crm/sem-guarda")],
        [],
        _errada("GET", "/perfil-errado", _perfis_errados(PERFIS_ADMIN, PERFIS_ESCRITORIO)),
    )


def test_meta_rota_na_tabela_dos_perfis_mas_sem_guarda_nenhuma():
    resultado = _classificar_com(_router(("GET", "/x", [])), perfis={("GET", "/api/crm/x"): PERFIS_ADMIN})
    assert resultado == Classificacao([], [], sorted(_errada("GET", "/x", SEM_MEMBRO, _numero_de_guardas(0))))


def test_meta_membro_sem_guarda_de_perfil_deixava_entrar_qualquer_perfil():
    """Só `membro_crm_atual`: o motorista também entrava."""
    resultado = _classificar_com(
        _router(("GET", "/x", [membro_crm_atual])), perfis={("GET", "/api/crm/x"): PERFIS_ADMIN}
    )
    assert resultado == Classificacao([], [], _errada("GET", "/x", _numero_de_guardas(0)))


def test_meta_duas_guardas_de_perfil():
    resultado = _classificar_com(
        _router(("GET", "/x", [SO_ADMIN, ESCRITORIO])), perfis={("GET", "/api/crm/x"): PERFIS_ADMIN}
    )
    assert resultado == Classificacao([], [], _errada("GET", "/x", _numero_de_guardas(2)))


def test_meta_guarda_que_nao_assenta_em_membro_crm_atual():
    """Uma função qualquer com `perfis_crm` não é uma guarda do CRM."""

    async def guarda_falsa(utilizador: Dict = Depends(utilizador_atual)):
        return utilizador

    guarda_falsa.perfis_crm = PERFIS_ADMIN
    resultado = _classificar_com(
        _router(("GET", "/x", [membro_crm_atual, guarda_falsa])), perfis={("GET", "/api/crm/x"): PERFIS_ADMIN}
    )
    assert resultado == Classificacao([], [], _errada("GET", "/x", GUARDA_SEM_MEMBRO))


def test_meta_corpo_lido_antes_da_guarda():
    router = _router(
        ("POST", "/antes", [corpo_json, SO_ADMIN]),
        ("POST", "/depois", [SO_ADMIN, corpo_json]),
        ("POST", "/sessao-antes", [corpo_json, utilizador_atual]),
        ("POST", "/sessao-depois", [utilizador_atual, corpo_json]),
    )
    resultado = _classificar_com(
        router,
        sessao={("POST", "/api/crm/sessao-antes"), ("POST", "/api/crm/sessao-depois")},
        perfis={("POST", "/api/crm/antes"): PERFIS_ADMIN, ("POST", "/api/crm/depois"): PERFIS_ADMIN},
    )
    assert resultado == Classificacao(
        [], [], _errada("POST", "/antes", CORPO_ANTES_DA_GUARDA) + _errada("POST", "/sessao-antes", CORPO_ANTES_DA_GUARDA)
    )


def test_meta_corpo_declarado_por_modelo():
    resultado = _classificar_com(
        _router(("POST", "/x", [SO_ADMIN], _resposta_com_modelo)), perfis={("POST", "/api/crm/x"): PERFIS_ADMIN}
    )
    assert resultado == Classificacao([], [], _errada("POST", "/x", CORPO_POR_MODELO))


def test_meta_publica_ou_de_cron_com_sessao():
    router = _router(("GET", "/publica", [utilizador_atual]), ("POST", "/cron/tarefa", [exigir_cron_key, SO_ADMIN]))
    resultado = _classificar_com(
        router, publicas={("GET", "/api/crm/publica")}, cron={("POST", "/api/crm/cron/tarefa")}
    )
    assert resultado == Classificacao(
        [], [], _errada("GET", "/publica", USA_SESSAO) + _errada("POST", "/cron/tarefa", USA_SESSAO)
    )


def test_meta_de_sessao_sem_utilizador_atual_ou_com_membro_crm_atual():
    router = _router(
        ("GET", "/com-membro", [membro_crm_atual]),
        ("GET", "/com-perfil", [ESCRITORIO]),
        ("GET", "/sem-sessao", []),
    )
    resultado = _classificar_com(
        router,
        sessao={("GET", "/api/crm/com-membro"), ("GET", "/api/crm/com-perfil"), ("GET", "/api/crm/sem-sessao")},
    )
    assert resultado == Classificacao(
        [],
        [],
        _errada("GET", "/com-membro", USA_MEMBRO)
        + _errada("GET", "/com-perfil", USA_MEMBRO)
        + _errada("GET", "/sem-sessao", SEM_UTILIZADOR_ATUAL),
    )


def test_meta_caminhos_de_cron_so_em_rotas_de_cron():
    router = _router(
        ("GET", "/cron/publica", []),
        ("POST", "/cron/admin", [SO_ADMIN]),
        ("GET", "/tarefa", [exigir_cron_key]),
    )
    resultado = _classificar_com(
        router,
        publicas={("GET", "/api/crm/cron/publica")},
        cron={("GET", "/api/crm/tarefa")},
        perfis={("POST", "/api/crm/cron/admin"): PERFIS_ADMIN},
    )
    assert resultado == Classificacao(
        [],
        [],
        _errada("GET", "/cron/publica", CRON_FORA_DA_LISTA)
        + _errada("GET", "/tarefa", CRON_SEM_O_CAMINHO)
        + _errada("POST", "/cron/admin", CRON_FORA_DA_LISTA),
    )


def test_meta_cron_sem_a_cron_key_ou_com_o_corpo_antes_dela():
    """Revisão da F0/F1, AC-1: estar "sem sessão" é o que a família pede, mas
    não chega — sem a guarda da `CRON_KEY` a rota fica pública. Uma função
    com o mesmo nome (ou que só verifica a chave "à mão" no corpo da rota)
    não conta: tem de ser `crm.auth.exigir_cron_key`."""

    async def exigir_cron_key_falsa(key: str = ""):
        return None

    exigir_cron_key_falsa.__name__ = exigir_cron_key_falsa.__qualname__ = "exigir_cron_key"

    async def com_a_chave_como_parametro(_: None = Depends(exigir_cron_key), corpo: Dict = Depends(corpo_json)):
        return {}

    router = _router(
        ("POST", "/cron/sem-chave", []),
        ("POST", "/cron/falsa", [exigir_cron_key_falsa]),
        ("POST", "/cron/corpo-antes", [corpo_json, exigir_cron_key]),
        ("POST", "/cron/certa", [exigir_cron_key]),
        ("POST", "/cron/certa-com-corpo", [], com_a_chave_como_parametro),
    )
    cron = {
        ("POST", "/api/crm/cron/sem-chave"),
        ("POST", "/api/crm/cron/falsa"),
        ("POST", "/api/crm/cron/corpo-antes"),
        ("POST", "/api/crm/cron/certa"),
        ("POST", "/api/crm/cron/certa-com-corpo"),
    }
    resultado = _classificar_com(router, cron=cron)
    assert resultado == Classificacao(
        [],
        [],
        sorted(
            _errada("POST", "/cron/sem-chave", SEM_CRON_KEY)
            + _errada("POST", "/cron/falsa", SEM_CRON_KEY)
            + _errada("POST", "/cron/corpo-antes", CORPO_ANTES_DA_GUARDA)
        ),
    )


def test_meta_listas_com_rotas_que_o_router_nao_tem():
    resultado = _classificar_com(
        _router(("GET", "/x", [])),
        publicas={("GET", "/api/crm/x")},
        sessao={("GET", "/api/crm/fantasma")},
        perfis={("DELETE", "/api/crm/x"): PERFIS_ADMIN},
    )
    assert resultado == Classificacao([], [("DELETE", "/api/crm/x"), ("GET", "/api/crm/fantasma")], [])


def test_meta_cada_metodo_e_uma_rota():
    """Uma rota declarada com dois métodos: classificar um não chega."""
    router = APIRouter(prefix=PREFIXO)
    router.add_api_route("/x", _resposta, methods=["GET", "POST"], dependencies=[Depends(ESCRITORIO)])
    resultado = _classificar_com(router, perfis={("GET", "/api/crm/x"): PERFIS_ESCRITORIO})
    assert resultado == Classificacao([("POST", "/api/crm/x")], [], [])


def test_meta_rota_repetida_ou_em_duas_familias():
    router = _router(("GET", "/x", [SO_ADMIN]), ("GET", "/x", []), ("GET", "/y", []))
    resultado = _classificar_com(
        router,
        publicas={("GET", "/api/crm/y")},
        perfis={("GET", "/api/crm/x"): PERFIS_ADMIN, ("GET", "/api/crm/y"): PERFIS_ADMIN},
    )
    assert resultado == Classificacao(
        [],
        [],
        sorted(
            _errada("GET", "/x", REPETIDA, SEM_MEMBRO, _numero_de_guardas(0))
            + _errada("GET", "/y", _varias_familias(["publica", "perfil"]))
        ),
    )


def test_meta_router_bem_classificado_nao_tem_queixas():
    """O contrário: uma rota de cada família com a guarda certa — também com a
    guarda declarada como parâmetro, como nas rotas reais, e o corpo depois
    dela — não dá nada a apontar."""

    async def escrita(admin: Dict = Depends(SO_ADMIN), corpo: Dict = Depends(corpo_json)):
        return {}

    router = _router(
        ("GET", "/publica", []),
        ("GET", "/sessao", [utilizador_atual]),
        ("POST", "/cron/tarefa", [exigir_cron_key]),
        ("GET", "/escritorio", [ESCRITORIO]),
        ("POST", "/escrita", [], escrita),
    )
    resultado = _classificar_com(
        router,
        publicas={("GET", "/api/crm/publica")},
        sessao={("GET", "/api/crm/sessao")},
        cron={("POST", "/api/crm/cron/tarefa")},
        perfis={("GET", "/api/crm/escritorio"): PERFIS_ESCRITORIO, ("POST", "/api/crm/escrita"): PERFIS_ADMIN},
    )
    assert resultado == TUDO_CERTO


# --- O router verdadeiro do CRM -----------------------------------------------------


def _erradas(familia):
    """As queixas de `_classificar(crm.router)` sobre as rotas de `familia`."""
    return [e for e in _classificar(crm.router).guarda_errada if (e[0], e[1]) in familia]


def test_1_as_rotas_do_router_sao_exatamente_as_das_quatro_listas():
    resultado = _classificar(crm.router)
    assert resultado.por_classificar == [], (
        "Rotas do CRM por classificar: pô-las numa das listas deste ficheiro "
        "(quase sempre em PERFIS_POR_ROTA, com os perfis da §4 do plano)"
    )
    assert resultado.sem_rota == [], "Nas listas deste ficheiro, mas não no router do CRM"
    assert {par for par, _ in _pares(crm.router)} == (
        ROTAS_PUBLICAS | ROTAS_DE_SESSAO | ROTAS_DE_CRON | set(PERFIS_POR_ROTA)
    )


def test_as_quatro_listas_nao_se_cruzam():
    listas = [ROTAS_PUBLICAS, ROTAS_DE_SESSAO, ROTAS_DE_CRON, set(PERFIS_POR_ROTA)]
    for i, uma in enumerate(listas):
        for outra in listas[i + 1:]:
            assert uma & outra == set()


def test_2_as_publicas_nao_usam_a_sessao():
    assert ROTAS_PUBLICAS
    assert _erradas(ROTAS_PUBLICAS) == []


def test_3_as_de_sessao_dependem_de_utilizador_atual_e_nunca_de_membro_crm_atual():
    assert ROTAS_DE_SESSAO
    assert _erradas(ROTAS_DE_SESSAO) == []


def test_4_caminhos_de_cron_so_em_rotas_de_cron_sem_sessao_e_com_a_cron_key():
    do_router = {par for par, _ in _pares(crm.router) if par[1].startswith(PREFIXO_CRON)}
    assert do_router <= ROTAS_DE_CRON
    assert all(caminho.startswith(PREFIXO_CRON) for _, caminho in ROTAS_DE_CRON)
    assert _erradas(ROTAS_DE_CRON) == []


def test_5_as_outras_dependem_de_membro_crm_atual_com_uma_so_guarda_de_perfil():
    assert PERFIS_POR_ROTA
    assert _erradas(set(PERFIS_POR_ROTA)) == []


def test_os_perfis_da_tabela_sao_os_da_f1_e_f2():
    """SO_ADMIN ou ESCRITORIO. O motorista não usa rotas da F1–F2: as
    permissões do terreno (F4) acrescentam aqui os seus conjuntos."""
    fora = {par: perfis for par, perfis in PERFIS_POR_ROTA.items() if perfis not in (PERFIS_ADMIN, PERFIS_ESCRITORIO)}
    assert fora == {}
    assert SO_ADMIN.perfis_crm == PERFIS_ADMIN
    assert ESCRITORIO.perfis_crm == PERFIS_ESCRITORIO


def _perfis_pela_regra_da_api(metodo, caminho):
    """A coluna "Família / perfis" da §4 do plano (API da F1–F2), escrita como
    uma regra por recurso e não como lista: membros e definições, só o admin;
    as regiões, o escritório lê e só o admin escreve; lojas, `/config` e
    morada, o escritório; as rotas (F3 §4, a partir da T3.18), o escritório.
    `None` para um recurso que a regra não conhece."""
    recurso = caminho[len(PREFIXO):].split("/")[1]
    if recurso in ("membros", "definicoes"):
        return PERFIS_ADMIN
    if recurso == "regioes":
        return PERFIS_ESCRITORIO if metodo == "GET" else PERFIS_ADMIN
    if recurso in ("lojas", "config", "morada", "rotas"):
        return PERFIS_ESCRITORIO
    return None


def test_a_tabela_segue_a_regra_da_api_do_plano():
    """Revisão final da tabela contra a §4 do plano (T2.16; correções, linha
    "T2.9–T2.15 vs T2.16"). Os testes (1) e (5) comparam o router com a
    tabela: se o código e a tabela mudassem juntos (abrir o `POST /regioes`
    ao escritório nos dois sítios), só esta regra, escrita de outra forma,
    dava pela diferença. Um recurso novo (F3+: rotas, encomendas; F4: o
    motorista) acrescenta aqui a sua regra, com os perfis do plano dessa
    fase."""
    sem_regra = sorted(par for par in PERFIS_POR_ROTA if _perfis_pela_regra_da_api(*par) is None)
    assert sem_regra == [], "Recurso sem regra: acrescentá-la em _perfis_pela_regra_da_api"
    fora_da_regra = sorted(par for par, perfis in PERFIS_POR_ROTA.items() if perfis != _perfis_pela_regra_da_api(*par))
    assert fora_da_regra == []


def test_o_router_do_crm_nao_tem_nada_a_apontar():
    assert _classificar(crm.router) == TUDO_CERTO
