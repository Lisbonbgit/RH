"""As lojas entre a base (`crm_lojas`) e a API (plano §3 e §4; dossiê §3 e §6).

Porta de src/Http/Formatar.php (`loja`, `resumoLoja`) e da parte do
`LojasRepositorio::criar` que monta a linha nova, para o modelo do portal:

- **Na base** (`documento_loja`): `id` uuid4 em texto, os 20 campos do
  `validador_loja`, `lat`/`lng` em `float` e SEMPRE juntos do `loc` GeoJSON
  (`documento_localizacao`, `[lng, lat]`), as janelas numa lista `[{inicio,
  fim}]` (0 a 2, por ordem; `validador_loja.janelas_para_lista`), os dias pela
  ordem da semana, os quatro temporizadores a null (F4/F5), quem a criou e os
  instantes do relógio do CRM: `fase_desde == criado_em` (a fase começa
  agora) e `atualizado_em`, com microssegundos, a versão do bloqueio otimista
  (T2.11).
- **Na API** (`loja_api`, `resumo_loja_api`): as janelas planas
  (`janela1_inicio`…, `validador_loja.campos_de_janelas`), sem `_id`, `loc`
  nem a lista das janelas; `lat`/`lng` em `float` (o `(float)` do PHP: um 39
  escrito à mão sai 39.0) e `precisao_m` em `int`; os dias pela ordem da
  semana e sem repetidos (o que o SET do MariaDB fazia). Os instantes já estão
  gravados no formato da API e passam tal e qual.

Os documentos só os escreve o `documento_loja` (e o seed, T2.18, por ele): um
documento estragado à mão (uma janela a meio, um dia desconhecido, uma
coordenada em texto) é `ValueError` — um 500 —, nunca uma resposta com outra
forma, com que o frontend não contava. Um campo em falta é `KeyError`, exceto
o `instagram` e o `site` (2026-10-13): as lojas gravadas antes não os têm,
leem-se com `.get` e vêm a `null` — sem migração.
"""
import math
import uuid

from . import relogio
from .dominio.campos_loja import DIAS
from .dominio.validador_loja import campos_de_janelas, janelas_para_lista

# A loja completa da API, pela ordem do plano §4 ("Loja completa (API)"), com o
# `instagram` e o `site` (2026-10-13) a seguir à pessoa de contacto.
CAMPOS_API = (
    "id", "nome", "fase", "fase_desde", "regiao_id", "morada", "codigo_postal", "localidade",
    "lat", "lng", "origem_coords", "precisao_m", "telefone", "pessoa_contacto", "instagram", "site", "notas",
    "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim", "dias_fechada",
    "visita_pendente_motivo", "visita_pendente_desde", "ultima_interacao_em", "ultima_visita_ou_entrega_em",
    "criado_por", "criado_em", "atualizado_em",
)

# O resumo de cada loja no mapa (GET /lojas): o que o pino, os filtros e o
# botão Ligar precisam.
CAMPOS_RESUMO = ("id", "nome", "fase", "regiao_id", "lat", "lng", "telefone")

# Os temporizadores da F4/F5 (dossiê §5.11): já existem no documento, a null.
_TEMPORIZADORES = (
    "visita_pendente_motivo", "visita_pendente_desde", "ultima_interacao_em", "ultima_visita_ou_entrega_em",
)


def _coordenada(valor, minimo: float, maximo: float) -> float:
    """Um número finito (nunca um bool) entre `minimo` e `maximo`, em float."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"Uma coordenada tem de ser um número, não {type(valor).__name__}.")
    try:
        numero = float(valor)
    except OverflowError:  # um inteiro que nem num float cabe
        raise ValueError("Coordenada fora do mundo.") from None
    if not math.isfinite(numero) or not minimo <= numero <= maximo:
        raise ValueError(f"Coordenada fora do mundo: {numero!r}.")
    return numero


def _precisao(valor):
    """`None`, ou metros inteiros. O Mongo devolve um int64 como `Int64` (um
    int) e o mongosh escreve os números como double: um 7.0 é 7."""
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"A precisão tem de ser um número inteiro, não {type(valor).__name__}.")
    if isinstance(valor, float) and not valor.is_integer():
        raise ValueError(f"A precisão tem de ser um número inteiro de metros, não {valor!r}.")
    return int(valor)


def _dias(valor) -> list:
    """Uma lista NOVA com os dias pela ordem da semana e sem repetidos; um dia
    desconhecido, ou o que não for uma lista, é `ValueError`."""
    if not isinstance(valor, list):
        raise ValueError("Os dias fechada da base têm de ser uma lista.")
    desconhecidos = [dia for dia in valor if not isinstance(dia, str) or dia not in DIAS]
    if desconhecidos:
        raise ValueError(f"Dias fechada desconhecidos na base: {desconhecidos!r}.")
    return [dia for dia in DIAS if dia in valor]


def documento_localizacao(lat, lng) -> dict:
    """`{lat, lng, loc}`: as coordenadas e o ponto GeoJSON (`[lng, lat]`) que o
    índice `2dsphere` usa (pré-filtro dos duplicados, T2.3), escritos SEMPRE
    juntos (plano §3) — na loja nova e no `$set` de uma alteração (T2.11).

    Recebe as coordenadas já validadas (`validador_loja`: Portugal, 6 casas). O
    Mongo recusa gravar um `loc` fora do mundo (WriteError, T2.8): o que não for
    um número finito em [−90, 90] × [−180, 180] é `ValueError` antes disso.
    """
    lat = _coordenada(lat, -90.0, 90.0)
    lng = _coordenada(lng, -180.0, 180.0)
    return {"lat": lat, "lng": lng, "loc": {"type": "Point", "coordinates": [lng, lat]}}


def documento_loja(dados: dict, criado_por, agora) -> dict:
    """A loja nova como fica gravada em `crm_lojas`, pela ordem do plano §3.

    `dados` são os 20 campos do `validador_loja.criacao` SEM erros (as janelas
    a meio são `ValueError`: nunca se gravam); `criado_por` é o `user_id` do
    portal de quem a criou; `agora` uma datetime com fuso (o `relogio.agora()`
    do pedido): `fase_desde` e `criado_em` são o `relogio.instante(agora)` e
    `atualizado_em` o `relogio.carimbo(agora)`, o mesmo instante com
    microssegundos. O `id` é um uuid4 novo. Não mexe em `dados` nem partilha
    listas com eles.
    """
    criado_em = relogio.instante(agora)
    localizacao = documento_localizacao(dados["lat"], dados["lng"])
    return {
        "id": str(uuid.uuid4()),
        "nome": dados["nome"],
        "fase": dados["fase"],
        "fase_desde": criado_em,
        "regiao_id": dados["regiao_id"],
        "morada": dados["morada"],
        "codigo_postal": dados["codigo_postal"],
        "localidade": dados["localidade"],
        **localizacao,
        "origem_coords": dados["origem_coords"],
        "precisao_m": dados["precisao_m"],
        "telefone": dados["telefone"],
        "pessoa_contacto": dados["pessoa_contacto"],
        "instagram": dados["instagram"],
        "site": dados["site"],
        "notas": dados["notas"],
        "janelas": janelas_para_lista(dados),
        "dias_fechada": _dias(dados["dias_fechada"]),
        **dict.fromkeys(_TEMPORIZADORES),
        "criado_por": criado_por,
        "criado_em": criado_em,
        "atualizado_em": relogio.carimbo(agora),
    }


def loja_api(doc: dict) -> dict:
    """A loja completa da API (GET /lojas/{id} e o 201 do POST), pela ordem de
    `CAMPOS_API`, a partir do documento da base (o `_id` e o `loc` ignoram-se)."""
    return {
        "id": doc["id"],
        "nome": doc["nome"],
        "fase": doc["fase"],
        "fase_desde": doc["fase_desde"],
        "regiao_id": doc["regiao_id"],
        "morada": doc["morada"],
        "codigo_postal": doc["codigo_postal"],
        "localidade": doc["localidade"],
        "lat": _coordenada(doc["lat"], -90.0, 90.0),
        "lng": _coordenada(doc["lng"], -180.0, 180.0),
        "origem_coords": doc["origem_coords"],
        "precisao_m": _precisao(doc["precisao_m"]),
        "telefone": doc["telefone"],
        "pessoa_contacto": doc["pessoa_contacto"],
        # Entraram em 2026-10-13 sem migração: um documento de antes não os tem.
        "instagram": doc.get("instagram"),
        "site": doc.get("site"),
        "notas": doc["notas"],
        **campos_de_janelas(doc["janelas"]),
        "dias_fechada": _dias(doc["dias_fechada"]),
        **{campo: doc[campo] for campo in _TEMPORIZADORES},
        "criado_por": doc["criado_por"],
        "criado_em": doc["criado_em"],
        "atualizado_em": doc["atualizado_em"],
    }


def resumo_loja_api(doc: dict) -> dict:
    """O resumo de uma loja para o mapa, pela ordem de `CAMPOS_RESUMO`. Basta
    o documento com esses campos (a projeção do GET /lojas)."""
    return {
        "id": doc["id"],
        "nome": doc["nome"],
        "fase": doc["fase"],
        "regiao_id": doc["regiao_id"],
        "lat": _coordenada(doc["lat"], -90.0, 90.0),
        "lng": _coordenada(doc["lng"], -180.0, 180.0),
        "telefone": doc["telefone"],
    }
