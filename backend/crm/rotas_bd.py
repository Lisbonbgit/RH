"""Leitura e escrita das rotas em `crm_rotas` (plano F3 §1 e §3; T3.17).

O repositório fala a língua da base: os dias são o texto `AAAA-MM-DD` que
está gravado em `data`, a `base` vem por parâmetro (a rota HTTP passa
`bd.obter_db()`; os testes, o duplo do Motor) e nada aqui lê o relógio nem o
ambiente — o `agora` e o membro chegam de quem chama.

- **Ler:** `ler` (a rota de um dia, sem `_id`), `rotas_entre` (as de um
  intervalo fechado de dias, por `data` e SEM o `calculo`: a geometria tem
  dezenas de KB por rota, correção "T3.17 / T3.18"), `rotas_com_loja` (as que
  têm a loja numa paragem, ativa ou retirada, pelo índice `paragens.loja_id`)
  e `lojas_da_rota` (as lojas das paragens ativas, pela
  `formatar_rota.PROJECAO_LOJA_ROTA`).
- **Escrever:** `criar` (a rota nova; a mesma `data` duas vezes dá `False`,
  pelo índice único) e as duas escritas condicionais do escritório —
  `alterar` (um `$set` de campos de topo e de `paragens.<índice>.<campo do
  escritório>`) e `acrescentar_paragem` (um `$push` de uma paragem nova,
  com o terreno em `pendente`/null/null). As duas gravam numa só
  `find_one_and_update` com o filtro de guarda `{id, versao, estado ∈
  ESTADOS_EDITAVEIS, "paragens.estado" ∉ ESTADOS_COM_REGISTO}`: a versão
  lida tem de ser a gravada e a rota não pode ter nenhum registo do
  motorista (§1 "O terreno ganha"). Cada gravação que muda o plano sobe a
  `versao` e leva `atualizado_em` (`relogio.proximo_carimbo`: sempre maior
  que o anterior) e `atualizado_por`; as horas do Directions
  (`subir_versao=False`) são dados derivados e não mudam nada disso. As duas
  devolvem a rota como ficou (sem `_id`), ou `None` quando o filtro não
  casou — e aí `porque_falhou` relê a rota e diz porquê, por esta ordem
  (correção "T3.17 (porque_falhou: precedência)"): `nao_existe` → `em_curso`
  (o estado fora dos editáveis ou alguma paragem `feita`/`nao_feita`, mesmo
  retirada) → `conflito`.

O que o escritório nunca escreve é recusado aqui com `ValueError`, antes de
ir à base: os campos reservados de topo (`id`, `data`, `versao`,
`paragens`, `criado_*`, `atualizado_*`), uma paragem inteira, um caminho
sem índice ou posicional (`paragens.$…`), um campo do terreno ou imutável
de uma paragem (a regra do `dominio.rotas.caminhos_paragem`, aplicada outra
vez) e uma paragem nova que não nasça `pendente`. É a mesma regra do
verificador dos testes (`formatos.escritas_no_terreno`), repetida na última
barreira antes do Mongo.
"""
import logging

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from . import db as bd
from . import relogio
from .dominio import rotas
from .dominio.datas import ler_data
from .formatar_rota import PROJECAO_LOJA_ROTA

logger = logging.getLogger(__name__)

# As projeções: nunca o `_id` do Mongo; nas listas, também sem o `calculo`.
SEM_ID = {"_id": 0}
PROJECAO_RESUMO = {"_id": 0, "calculo": 0}

# Os motivos de `porque_falhou`, pela ordem da precedência.
NAO_EXISTE = "nao_existe"
EM_CURSO = "em_curso"
CONFLITO = "conflito"

# Os campos de topo que nenhum `$set` do escritório escreve: os fixos (`id`,
# `data`), os que o repositório escreve sozinho (`versao`, `atualizado_*`),
# os da criação e a lista `paragens` inteira (só se acrescenta, por `$push`).
CAMPOS_RESERVADOS = ("id", "data", "versao", "paragens", "criado_em", "criado_por", "atualizado_em", "atualizado_por")

# Com o que uma paragem nasce no terreno (o `formatar_rota.documento_paragem`
# escreve-o; a F4 muda-o).
TERRENO_INICIAL = {"estado": "pendente", "resultado": None, "concluida_em": None}

_SEM_VALOR = object()


# --- Ler ---------------------------------------------------------------------------------------


async def ler(base, data):
    """A rota do dia `data` (texto `AAAA-MM-DD`), sem `_id`, ou `None` se o
    dia não tem rota. Outro tipo é `TypeError`; um texto que não é um dia,
    `ValueError` (nunca uma pergunta à base que não casaria com nada)."""
    _exigir_dia(data, "data")
    return await _rotas(base).find_one({"data": data}, SEM_ID)


async def rotas_entre(base, de, ate) -> list:
    """As rotas com `de <= data <= ate` (os dois em texto `AAAA-MM-DD`), por
    `data` e sem o `calculo` (`PROJECAO_RESUMO`, para o `GET /rotas`). Um fim
    antes do início é uma lista vazia, não um erro: o validador já recusou
    isso com 422."""
    _exigir_dia(de, "de")
    _exigir_dia(ate, "ate")
    return await _rotas(base).find({"data": {"$gte": de, "$lte": ate}}, PROJECAO_RESUMO).sort("data", 1).to_list(None)


async def rotas_com_loja(base, loja_id) -> list:
    """As rotas em que a loja está numa paragem, ativa ou retirada (o índice
    `paragens.loja_id`), por `data` e sem o `calculo`. É a pergunta do
    `DELETE /lojas/{id}` (T3.24): quem decide se a loja está presa é a regra
    pura do domínio, sobre as paragens de cada rota."""
    if not isinstance(loja_id, str):
        raise TypeError(f"O id da loja tem de ser texto: {loja_id!r}")
    return await _rotas(base).find({"paragens.loja_id": loja_id}, PROJECAO_RESUMO).sort("data", 1).to_list(None)


async def lojas_da_rota(base, rota) -> list:
    """As lojas das paragens ativas de `rota` (uma rota lida da base, ou
    `None` — a virtual), pela `PROJECAO_LOJA_ROTA`, para o `rota_api`. Sem
    paragens ativas não vai à base. Uma loja apagada entretanto não vem, e o
    `rota_api` mostra a paragem como `sem_loja`."""
    if rota is None:
        return []
    ids = [paragem["loja_id"] for paragem in rotas.ativas(rota["paragens"])]
    if not ids:
        return []
    return await _lojas(base).find({"id": {"$in": ids}}, PROJECAO_LOJA_ROTA).to_list(None)


# --- Escrever ----------------------------------------------------------------------------------


async def criar(base, documento) -> bool:
    """Grava a rota nova (`formatar_rota.documento_rota`): `True` se ficou;
    `False` se o índice único recusou — a mesma `data` já tem rota (duas
    pessoas a adicionar a primeira paragem do mesmo dia: quem chama volta a
    ler e acrescenta). Grava uma cópia, para o dicionário de quem chama
    ficar sem o `_id` que o PyMongo acrescenta ao inserir."""
    if not isinstance(documento, dict):
        raise TypeError(f"A rota a gravar tem de ser um dicionário: {documento!r}")
    try:
        await _rotas(base).insert_one(dict(documento))
    except DuplicateKeyError:
        return False
    return True


async def alterar(base, rota, set_, *, subir_versao=True, membro_id, agora):
    """A escrita condicional do escritório sobre a `rota` lida: um só
    `find_one_and_update` com o filtro de guarda (a versão lida, um estado
    editável e nenhuma paragem com registo do motorista) e o `$set` de
    `set_` — campos de topo (`hora_saida`, `estado`, `calculo`…) e caminhos
    `paragens.<índice>.<campo do escritório>` (`dominio.rotas.caminhos_paragem`).

    Com `subir_versao` (o plano mudou): mais `$inc` da `versao` e, no `$set`,
    `atualizado_em` (`relogio.proximo_carimbo` sobre o `atualizado_em` da
    rota lida, com `agora`) e `atualizado_por` (`membro_id`). Sem ele (as
    horas do Directions, dados derivados): só o `$set`, e o `atualizado_em`
    da rota nem se lê.

    Devolve a rota como ficou (sem `_id`) ou `None` se o filtro não casou
    (`porque_falhou` diz porquê). `set_` vazio, um campo reservado, um
    caminho de paragem fora da regra ou um campo do terreno → `ValueError`
    sem escrever; `set_` que não é um dicionário → `TypeError`. Não mexe na
    `rota` nem no `set_` recebidos.
    """
    _exigir_set_do_escritorio(set_)
    atualizacao = {"$set": dict(set_)}
    if subir_versao:
        atualizacao["$set"].update(_autoria(rota, membro_id, agora))
        atualizacao["$inc"] = {"versao": 1}
    return await _escrever(base, rota, atualizacao)


async def acrescentar_paragem(base, rota, paragem, *, membro_id, agora):
    """Acrescenta uma paragem nova (`formatar_rota.documento_paragem`) ao fim
    da lista da `rota` lida: `$push` em `paragens`, `$inc` da `versao` e o
    `$set` SÓ de topo (`atualizado_em`/`atualizado_por`; nunca
    `paragens.N…`, que o Mongo recusa junto com o `$push`), com o mesmo
    filtro de guarda do `alterar`. Devolve a rota como ficou ou `None`.

    A paragem tem de nascer com o terreno inicial (`estado "pendente"`,
    `resultado` e `concluida_em` nulos): outra coisa é `ValueError` sem
    escrever; uma paragem que não é um dicionário, `TypeError`.
    """
    _exigir_paragem_nova(paragem)
    atualizacao = {
        "$push": {"paragens": paragem},
        "$set": _autoria(rota, membro_id, agora),
        "$inc": {"versao": 1},
    }
    return await _escrever(base, rota, atualizacao)


async def porque_falhou(base, rota_id, versao) -> str:
    """Porque é que uma escrita condicional não casou, relendo a rota, por
    esta ordem (correção "T3.17 (porque_falhou: precedência)"):

    - `"nao_existe"`: já não há rota com esse `id`;
    - `"em_curso"`: o estado está fora dos editáveis ou alguma paragem tem
      um registo do motorista (`feita`/`nao_feita`), mesmo retirada — ganha
      ao conflito, para o planeador passar a só leitura em vez de recarregar
      e tentar outra vez;
    - `"conflito"`: a `versao` gravada já não é a que a escrita levava. Se
      ainda for (a rota editável e sem registo: um caso que o filtro não
      explica), fica também `conflito` — a escrita falhou e o planeador tem
      de reler — e um aviso no registo.
    """
    rota = await _rotas(base).find_one({"id": rota_id}, PROJECAO_RESUMO)
    if rota is None:
        return NAO_EXISTE
    if _com_registo_do_terreno(rota):
        return EM_CURSO
    if rota["versao"] == versao:
        logger.warning(
            "[crm] rota %s: a escrita condicional falhou e a versão %s continua gravada numa rota editável",
            rota_id,
            versao,
        )
    return CONFLITO


# --- interno -----------------------------------------------------------------------------------


def _rotas(base):
    return base[bd.COLECOES["rotas"]]


def _lojas(base):
    return base[bd.COLECOES["lojas"]]


def _exigir_dia(valor, nome):
    if type(valor) is not str:
        raise TypeError(f"`{nome}` tem de ser o dia em texto AAAA-MM-DD: {valor!r}")
    if ler_data(valor) is None:
        raise ValueError(f"`{nome}` não é um dia AAAA-MM-DD: {valor!r}")


def _guarda(rota) -> dict:
    """O filtro de guarda de todas as escritas do escritório (plano F3 §1):
    a rota lida, com a versão lida, num estado editável e sem nenhuma
    paragem com registo do motorista (`$nin` numa lista: nenhum elemento)."""
    return {
        "id": rota["id"],
        "versao": rota["versao"],
        "estado": {"$in": list(rotas.ESTADOS_EDITAVEIS)},
        "paragens.estado": {"$nin": list(rotas.ESTADOS_COM_REGISTO)},
    }


def _autoria(rota, membro_id, agora) -> dict:
    return {
        "atualizado_em": relogio.proximo_carimbo(agora, rota["atualizado_em"]),
        "atualizado_por": membro_id,
    }


async def _escrever(base, rota, atualizacao):
    return await _rotas(base).find_one_and_update(
        _guarda(rota), atualizacao, projection=SEM_ID, return_document=ReturnDocument.AFTER
    )


def _com_registo_do_terreno(rota) -> bool:
    """A condição que o filtro de guarda impõe, lida da rota: a mesma regra
    do `dominio.rotas.bloqueio_de_escrita` para o `rota_em_curso`."""
    return rota.get("estado") not in rotas.ESTADOS_EDITAVEIS or any(
        paragem.get("estado") in rotas.ESTADOS_COM_REGISTO for paragem in rota["paragens"]
    )


def _exigir_set_do_escritorio(set_):
    if not isinstance(set_, dict):
        raise TypeError(f"Os campos a escrever vêm num dicionário: {set_!r}")
    if not set_:
        raise ValueError("Uma escrita sem campos: quem chama decide antes o 200 sem escrever.")
    for caminho, valor in set_.items():
        if not isinstance(caminho, str) or caminho.startswith("$") or caminho in CAMPOS_RESERVADOS:
            raise ValueError(f"O escritório não escreve o campo {caminho!r} de uma rota.")
        if caminho.startswith("paragens."):
            partes = caminho.split(".")
            if len(partes) != 3 or not (partes[1].isascii() and partes[1].isdigit()):
                raise ValueError(f"Caminho de paragem fora da regra paragens.<índice>.<campo>: {caminho!r}")
            # A regra do domínio, outra vez: ValueError com um campo do
            # terreno, um imutável (`id`, `loja_id`) ou um desconhecido.
            rotas.caminhos_paragem(int(partes[1]), {partes[2]: valor})


def _exigir_paragem_nova(paragem):
    if not isinstance(paragem, dict):
        raise TypeError(f"A paragem a acrescentar tem de ser um dicionário: {paragem!r}")
    terreno = {campo: paragem.get(campo, _SEM_VALOR) for campo in rotas.CAMPOS_DO_TERRENO}
    if terreno != TERRENO_INICIAL:
        raise ValueError("Uma paragem nova nasce pendente, sem resultado nem conclusão.")
