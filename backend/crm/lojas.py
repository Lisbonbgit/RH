"""`/api/crm/lojas` — as lojas do mapa: listar, ler, criar (T2.10), editar
(T2.11) e apagar os enganos (T2.12).

Plano T2.10, T2.11 e T2.12; dossiê §5.2, §5.5, §5.10, §5.11, §5.12 e §6. Porta
de src/Http/Controladores/LojasControlador.php (`listar`, `ver`, `criar`,
`alterar`, `apagar`) e do LojasRepositorio.php do CRM autónomo. As regras do
corpo estão em `dominio/validador_loja.py` (T2.5, T2.6), os duplicados em
`dominio/geo.py` (T2.3), as janelas em `dominio/janelas.py` (T2.4) e a forma
do documento e da resposta em `formatar.py`: aqui só se lê, grava e responde.

Só o escritório (admin e utilizador do CRM): o motorista ganha o POST na F4
(plano §1, "Perfis por rota").

- `GET /lojas` → `[{id, nome, fase, regiao_id, lat, lng, telefone}]` (o
  resumo para o mapa; os filtros aplicam-se no cliente), pelo nome sem
  maiúsculas nem acentos (`texto.chave_comparacao`, a collation do
  `ORDER BY nome, id` do autónomo) e depois pelo `id`.
- `GET /lojas/{loja_id}` → a loja completa, ou 404 "Loja não encontrada.".
- `POST /lojas` (os campos da loja + `confirmar_duplicado?`) → 201 com a loja
  completa. As outras chaves do corpo (`id`, `criado_por`, `fase_desde`,
  `atualizado_em`, `loc`, `janelas`…) ignoram-se: o servidor decide-as.

Ordem das verificações do POST, a do autónomo: o corpo (422 com os campos,
sem ler a base) → a região existe (422 em `regiao_id` "A região não
existe.") → outra loja a menos de 50 m (409 `duplicado`, com as lojas da mais
perto para a mais longe, e nada se grava), salvo com `"confirmar_duplicado":
true` — só o booleano JSON: `"true"`, `1` e `null` não confirmam → a escrita.

Sem transações (o autónomo lia a região com bloqueio partilhado na transação
que gravava a loja). Corridas residuais aceites (plano §9; dossiê §3): uma
região apagada entre a verificação e o `insert_one` deixa um `regiao_id`
órfão (os filtros do mapa toleram-no, T2.25); e dois pedidos no mesmo
instante e no mesmo sítio gravam-se os dois — o duplicado é um aviso, não uma
regra da base (também era assim no autónomo).

`PATCH /lojas/{loja_id}` (só os campos alterados + o `atualizado_em` da loja
carregada + `confirmar_duplicado?`) → a loja completa, com o `atualizado_em`
novo. Ordem das verificações, a do `LojasControlador::alterar` (correções do
plano, linha "T2.11"):

1. o corpo: os erros dos campos (`validador_loja.alteracao`) e, no fim, o do
   `atualizado_em` que não é um carimbo — tudo num só 422, sem ler a base;
2. ler a loja (404);
3. a versão lida é a do pedido? Senão 409 `conflito`. É a comparação
   antecipada (o autónomo bloqueava a linha): tudo o que vem a seguir é
   calculado sobre a loja que o cliente viu, e nunca um 422 de janelas ou um
   409 duplicado sobre as horas ou o sítio de outra versão;
4. as janelas contra as horas que a loja já tem, só se o pedido mexer numa
   hora (422 nas horas);
5. a região existe (422 em `regiao_id`);
6. outra loja a menos de 50 m, só se as coordenadas mudarem nas 6 casas que
   a base guarda (409 `duplicado`, sem contar a própria), salvo com
   `"confirmar_duplicado": true`;
7. a atualização condicional `{"id", "atualizado_em": versao}` — a rede para
   as corridas: se não apanhar nada, relê-se (inexistente → 404, existente →
   409 `conflito`). A versão nova é `relogio.proximo_carimbo(agora, versao)`:
   muda sempre e é sempre maior.

Sem transações (plano §1): a loja grava-se primeiro e a interação
`mudanca_fase` depois. Se a interação falhar, a loja não se desfaz: fica uma
linha `[crm]` no registo (sem dados pessoais) e responde-se 200 na mesma.

`DELETE /lojas/{loja_id}` (sem corpo) → `{apagada: true}`. Só os enganos: uma
loja com histórico (interações que não sejam `mudanca_fase`) dá 409
`loja_com_historico`, e usa-se a fase perdida. Ordem, a do
`LojasControlador::apagar` sem transações (o autónomo bloqueava a linha e as
interações iam com ela pelo `ON DELETE CASCADE`):

1. ler a loja (404) — interações órfãs de um id que não existe nem se olham;
2. há histórico? (`_pode_apagar`; 409, e nada se escreve);
3. `delete_one` da loja; `deleted_count 0` (apagada por outra pessoa entre a
   leitura e esta escrita) → 404;
4. só depois, `delete_many` das `mudanca_fase` dela — e só dessas: uma visita
   que chegue numa corrida entre 2 e 3 fica, órfã, e nunca se apaga histórico
   verdadeiro. Se o `delete_many` falhar, a loja já foi: responde-se 200 na
   mesma e fica uma linha `[crm]` no registo (sem dados pessoais).
"""
import logging
import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends

from . import db as bd
from . import relogio
from .auth import ESCRITORIO
from .dominio import janelas, validador_loja
from .dominio.geo import encontrar_duplicados, filtro_candidatos
from .dominio.texto import chave_comparacao
from .dominio.validador_loja import campos_de_janelas, janelas_para_lista
from .erros import erro, nao_encontrado, validacao
from .formatar import CAMPOS_RESUMO, documento_localizacao, documento_loja, loja_api, resumo_loja_api
from .pedidos import corpo_json

logger = logging.getLogger(__name__)

router = APIRouter()

# A loja completa: tudo menos o `_id` (o `loc` e a lista das janelas o
# `loja_api` não os copia).
PROJECAO_LOJA = {"_id": 0}

# O resumo do mapa.
PROJECAO_RESUMO = {"_id": 0, **{campo: 1 for campo in CAMPOS_RESUMO}}

# O que a regra dos 50 m mede em cada candidato (`geo.encontrar_duplicados`).
PROJECAO_CANDIDATO = {"_id": 0, "id": 1, "nome": 1, "lat": 1, "lng": 1}

# Para saber se a região existe, basta o `id`.
PROJECAO_ID = {"_id": 0, "id": 1}

# Teto das listas: o volume esperado é de centenas de lojas (plano §3), e no
# círculo de 60 m dos duplicados, umas poucas; o teto só trava um caso
# patológico.
LIMITE_LISTA = 5000

MENSAGEM_NAO_ENCONTRADA = "Loja não encontrada."
MENSAGEM_REGIAO_NAO_EXISTE = "A região não existe."
MENSAGEM_SEM_VERSAO = "Indique o atualizado_em que recebeu com a loja."
MENSAGEM_CONFLITO = "Alterado por outra pessoa — recarregar"
MENSAGEM_COM_HISTORICO = "Esta loja tem histórico — mude a fase para perdida em vez de a apagar."

# O tipo da interação que cada mudança de fase grava. As outras (visita,
# chamada, amostra, entrega, nota; F4/F5) são o histórico real da loja.
MUDANCA_FASE = "mudanca_fase"


def _colecao():
    return bd.obter_db()[bd.COLECOES["lojas"]]


@router.get("/lojas")
async def listar_lojas(membro: Dict = Depends(ESCRITORIO)) -> List[Dict]:
    """O resumo de todas, pelo nome (sem maiúsculas nem acentos) e pelo `id`."""
    lojas = await _colecao().find({}, PROJECAO_RESUMO).to_list(LIMITE_LISTA)
    lojas.sort(key=lambda loja: (chave_comparacao(loja["nome"]), loja["id"]))
    return [resumo_loja_api(loja) for loja in lojas]


@router.post("/lojas", status_code=201)
async def criar_loja(membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """Os campos da loja + `confirmar_duplicado?` → 201 com a loja completa."""
    dados, erros = validador_loja.criacao(corpo)
    if erros:
        raise validacao(erros)

    # Só o true confirma (em Python, `1 == True`: por isso `is`).
    confirmado = corpo.get("confirmar_duplicado") is True
    agora = relogio.agora()
    base = bd.obter_db()

    await _exigir_regiao(base, dados["regiao_id"])

    lojas = base[bd.COLECOES["lojas"]]
    if not confirmado:
        await _recusar_duplicados(lojas, dados["lat"], dados["lng"])

    loja = documento_loja(dados, membro["user_id"], agora)
    # O insert_one acrescenta `_id` (ObjectId) a `loja`; não sai na resposta,
    # porque o `loja_api` só copia as chaves da API.
    await lojas.insert_one(loja)
    return loja_api(loja)


@router.get("/lojas/{loja_id}")
async def ler_loja(loja_id: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """A loja completa, ou 404."""
    loja = await _colecao().find_one({"id": loja_id}, PROJECAO_LOJA)
    if loja is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
    return loja_api(loja)


@router.patch("/lojas/{loja_id}")
async def alterar_loja(loja_id: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """Só os campos alterados + `atualizado_em` + `confirmar_duplicado?` → a
    loja completa, com o `atualizado_em` novo (ordem das verificações no
    docstring do módulo)."""
    alteracoes, erros = validador_loja.alteracao(corpo)
    # O próprio texto, se for um carimbo exato; nunca um operador do Mongo.
    versao = relogio.ler_carimbo(corpo.get("atualizado_em"))
    if versao is None:
        erros = {**erros, "atualizado_em": MENSAGEM_SEM_VERSAO}
    if erros:
        raise validacao(erros)

    confirmado = corpo.get("confirmar_duplicado") is True
    agora = relogio.agora()
    base = bd.obter_db()
    lojas = base[bd.COLECOES["lojas"]]

    antes = await lojas.find_one({"id": loja_id}, PROJECAO_LOJA)
    if antes is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
    if antes["atualizado_em"] != versao:
        raise _conflito()

    janelas_novas = _janelas_alteradas(antes, alteracoes)
    await _exigir_regiao(base, alteracoes.get("regiao_id"))
    if not confirmado and _mudou_de_sitio(antes, alteracoes):
        await _recusar_duplicados(lojas, alteracoes["lat"], alteracoes["lng"], excluir_id=loja_id)

    fase_nova = _fase_nova(antes, alteracoes)
    novos = _valores_novos(alteracoes, janelas_novas, fase_nova, agora, versao)

    # Sem upsert: uma loja apagada entretanto não volta.
    resultado = await lojas.update_one({"id": loja_id, "atualizado_em": versao}, {"$set": novos})
    if resultado.matched_count == 0:
        if await lojas.find_one({"id": loja_id}, PROJECAO_ID) is None:
            raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
        raise _conflito()

    if fase_nova is not None:
        await _registar_mudanca_de_fase(base, loja_id, antes["fase"], fase_nova, membro["user_id"], agora)

    # A loja como ficou gravada: a que se leu, com a versão do pedido, mais o
    # `$set` que a atualização condicional aplicou (sem reler a base).
    return loja_api({**antes, **novos})


@router.delete("/lojas/{loja_id}")
async def apagar_loja(loja_id: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """→ `{apagada: true}`, ou 409 `loja_com_historico` (ordem e corridas no
    docstring do módulo). Não lê o corpo."""
    base = bd.obter_db()
    lojas = base[bd.COLECOES["lojas"]]
    if await lojas.find_one({"id": loja_id}, PROJECAO_ID) is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
    if not await _pode_apagar(base, loja_id):
        raise erro(409, "loja_com_historico", MENSAGEM_COM_HISTORICO)
    resultado = await lojas.delete_one({"id": loja_id})
    if resultado.deleted_count == 0:
        # Apagada por outra pessoa entre a leitura e esta escrita: quem a
        # apagou é que leva as mudanças de fase.
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
    await _apagar_mudancas_de_fase(base, loja_id)
    return {"apagada": True}


def _conflito():
    return erro(409, "conflito", MENSAGEM_CONFLITO)


async def _exigir_regiao(base, regiao_id) -> None:
    """A região tem de existir (`None` = sem região; 422 em `regiao_id`).

    O `regiao_id` validado é um uuid4 em texto (nunca um operador do Mongo).
    Sem transações, uma região apagada entre esta verificação e a escrita da
    loja deixa um `regiao_id` órfão (corrida residual aceite, dossiê §3).
    """
    if regiao_id is not None and await base[bd.COLECOES["regioes"]].find_one({"id": regiao_id}, PROJECAO_ID) is None:
        raise validacao({"regiao_id": MENSAGEM_REGIAO_NAO_EXISTE})


async def _recusar_duplicados(lojas, lat, lng, excluir_id=None) -> None:
    """As outras lojas a menos de 50 m do ponto (sem contar a `excluir_id`, a
    que se está a editar) → 409 `duplicado` com elas, da mais perto para a
    mais longe. O pré-filtro pelo índice `2dsphere` (círculo de 60 m) e
    depois a regra exata dos 50 m em Python (T2.3)."""
    candidatos = await lojas.find(filtro_candidatos(lat, lng, excluir_id), PROJECAO_CANDIDATO).to_list(LIMITE_LISTA)
    duplicados = encontrar_duplicados(candidatos, lat, lng, excluir_id)
    if duplicados:
        raise erro(409, "duplicado", f"Já existe {duplicados[0]['nome']} aqui — é a mesma?", lojas=duplicados)


def _janelas_alteradas(antes: Dict, alteracoes: Dict):
    """As janelas da loja alterada, em lista, se o pedido mexer numa hora;
    senão `None` (e as guardadas nem se leem: uma loja que não muda as horas
    nunca recebe um erro sobre elas — `semMexerNasJanelasNaoSeVerificamAsGuardadas`).

    As horas enviadas (já validadas uma a uma pelo `validador_loja`) juntam-se
    às guardadas e o conjunto tem de ser coerente: senão 422 nas horas, pela
    ordem do `janelas.erros` (o `exigirJanelas` do autónomo não as
    reordenava).
    """
    horas = {campo: alteracoes[campo] for campo in janelas.CAMPOS if campo in alteracoes}
    if not horas:
        return None
    juntas = {**campos_de_janelas(antes["janelas"]), **horas}
    erros = janelas.erros(juntas)
    if erros:
        raise validacao(erros)
    return janelas_para_lista(juntas)


def _seis_casas(coordenada) -> str:
    """A coordenada com as 6 casas que a base guarda (o `sprintf('%.6F')` do
    autónomo). O `+ 0.0` lê também um inteiro escrito à mão (um 39 é
    "39.000000") e tira o sinal a um −0,0."""
    return "%.6f" % (coordenada + 0.0)


def _mudou_de_sitio(antes: Dict, alteracoes: Dict) -> bool:
    """O pedido traz outras coordenadas, comparadas nas 6 casas que a base
    guarda (o `mudouDeSitio` do autónomo)? A localização vem sempre completa
    (`validador_loja.alteracao`), e já arredondada a 6 casas."""
    return "lat" in alteracoes and (
        _seis_casas(alteracoes["lat"]) != _seis_casas(antes["lat"])
        or _seis_casas(alteracoes["lng"]) != _seis_casas(antes["lng"])
    )


def _fase_nova(antes: Dict, alteracoes: Dict):
    """A fase para onde a loja passa, ou `None` se o pedido não a muda (sem a
    fase, ou com a mesma). É o ÚNICO sítio onde se decide que a fase de uma
    loja muda: com ela mudam o `fase_desde` e o histórico (`mudanca_fase`).
    F4/F5: efeitos de resultados aqui (a fase "só sobe" das visitas, amostras
    e entregas; "Não interessado" → perdida, exceto cliente).
    """
    fase = alteracoes.get("fase", antes["fase"])
    return fase if fase != antes["fase"] else None


def _valores_novos(alteracoes: Dict, janelas_novas, fase_nova, agora, versao: str) -> Dict:
    """O `$set` da alteração: só os campos que vieram, como a base os guarda.

    As coordenadas vão SEMPRE com o `loc` (`documento_localizacao`, plano §3)
    e as horas planas passam a `janelas` em lista. Com a fase nova, o
    `fase_desde` passa ao instante do pedido. O `atualizado_em` muda sempre:
    é o carimbo do pedido ou, com o relógio atrasado, o microssegundo a seguir
    à versão anterior (`relogio.proximo_carimbo`). Nunca vazio.
    """
    novos = {
        campo: valor for campo, valor in alteracoes.items() if campo not in ("lat", "lng") + janelas.CAMPOS
    }
    if fase_nova is not None:
        novos["fase_desde"] = relogio.instante(agora)
    if "lat" in alteracoes:
        novos.update(documento_localizacao(alteracoes["lat"], alteracoes["lng"]))
    if janelas_novas is not None:
        novos["janelas"] = janelas_novas
    novos["atualizado_em"] = relogio.proximo_carimbo(agora, versao)
    return novos


async def _registar_mudanca_de_fase(base, loja_id: str, antiga: str, nova: str, utilizador_id, agora) -> None:
    """Grava no histórico a interação `mudanca_fase` "<antiga>→<nova>" de quem
    a mudou, no instante do pedido (o mesmo do `fase_desde`), DEPOIS de a loja
    estar gravada.

    Sem transações: se falhar, a loja já mudou e não se desfaz. Fica uma
    linha `[crm]` no registo só com o id da loja, as fases e o tipo da
    exceção — nunca a mensagem dela (pode trazer o documento), nem quem a
    mudou, nem o nome da loja.
    """
    resultado = f"{antiga}→{nova}"
    interacao = {
        "id": str(uuid.uuid4()),
        "loja_id": loja_id,
        "tipo": MUDANCA_FASE,
        "resultado": resultado,
        "notas": None,
        "paragem_id": None,
        "utilizador_id": utilizador_id,
        "ocorrida_em": relogio.instante(agora),
    }
    try:
        await base[bd.COLECOES["interacoes"]].insert_one(interacao)
    except Exception as e:  # noqa: BLE001 — a loja já está gravada (ver docstring)
        logger.error(
            "[crm] loja %s: a mudança de fase %s ficou gravada, mas não entrou no histórico (%s)",
            loja_id,
            resultado,
            type(e).__name__,
        )


async def _pode_apagar(base, loja_id: str) -> bool:
    """Se a loja se pode apagar: só os enganos, sem histórico (o `podeApagar`
    do autónomo, `SELECT 1 … WHERE loja_id = ? AND tipo <> 'mudanca_fase'
    LIMIT 1`, aqui pelo índice `(loja_id, ocorrida_em)`). As mudanças de fase
    não contam (vão com a loja); qualquer outra interação conta — visita,
    chamada, amostra, entrega, nota, e também uma sem `tipo` (o `$ne` do Mongo
    apanha-a): na dúvida, não se apaga histórico. Com histórico, usa-se a
    fase perdida (spec §5).

    F5: bloquear se houver encomendas ou paragens (plano §7, "Ganchos"; o
    "Etapa 2: recusar também…" do autónomo).
    """
    historico = {"loja_id": loja_id, "tipo": {"$ne": MUDANCA_FASE}}
    return await base[bd.COLECOES["interacoes"]].find_one(historico, PROJECAO_ID) is None


async def _apagar_mudancas_de_fase(base, loja_id: str) -> None:
    """Leva as `mudanca_fase` da loja já apagada (o `ON DELETE CASCADE` do
    autónomo), e SÓ essas: uma interação de outro tipo que chegue numa corrida
    entre o `_pode_apagar` e o `delete_one` fica, órfã — nunca se apaga
    histórico verdadeiro (corrida residual aceite, dossiê §5.12).

    Sem transações: se falhar, a loja já foi e não volta. As mudanças de fase
    ficam órfãs (nenhum ecrã as mostra: a linha do tempo é por loja), e fica
    uma linha `[crm]` no registo só com o id da loja e o tipo da exceção —
    nunca a mensagem dela, nem quem apagou.
    """
    try:
        await base[bd.COLECOES["interacoes"]].delete_many({"loja_id": loja_id, "tipo": MUDANCA_FASE})
    except Exception as e:  # noqa: BLE001 — a loja já está apagada (ver docstring)
        logger.error(
            "[crm] loja %s: apagada, mas as mudanças de fase ficaram no histórico (%s)",
            loja_id,
            type(e).__name__,
        )
