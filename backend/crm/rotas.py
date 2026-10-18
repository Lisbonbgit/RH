"""`/api/crm/rotas` — as rotas de um dia (F3: planear rota, versão simples).

Plano F3 §4; T3.18 (ler) e T3.19 (adicionar uma loja). Só o escritório
(admin e utilizador do CRM): o motorista dá 403 `sem_permissao`, quem não é
membro 403 `sem_acesso_crm` e, sem sessão, os 401/403 herdados do portal. Os
parâmetros (`data`, `de`, `ate`) e os corpos leem-se como texto e validam-se
no domínio (`dominio/validador_rota`, T3.4); a forma das respostas e dos
documentos está em `formatar_rota` (T3.16) e as leituras e as escritas
condicionais em `rotas_bd` (T3.17): aqui só se valida, lê, decide e responde.

- `GET /rotas?de=&ate=` → `{hoje, de, ate, rotas: [{id, data, estado,
  estado_efetivo, paragens}]}`, por `data`, com `paragens` a contar só as
  ativas. Sem `de`/`ate`, cada extremo por si é o da omissão (hoje − 14 e
  hoje + 60); os dois dias devolvem-se já resolvidos. A lista lê-se sem o
  `calculo` (a geometria tem dezenas de KB por rota, correção "T3.17 /
  T3.18"). 422 em `de`/`ate` (formato, fim antes do início, mais de 120
  dias), sem tocar na base.
- `GET /rotas/{data}` → a rota completa (`rota_api`), com as lojas das
  paragens ativas juntadas pela `PROJECAO_LOJA_ROTA`, ou a rota **virtual**
  de um dia sem rota (`existe: false`, com as horas e a fábrica das
  definições em vigor). Um dia anterior a hoje lê-se `concluida` e só de
  leitura (`editavel: false`), com ou sem rota (o fecho simples da F3).
  `calculo_disponivel` diz se há `CRM_ORS_CHAVE` (`ors.chave()`; ler nunca
  chama o openrouteservice). 422 em `data` (formato, ou mais de um ano a
  partir de hoje), sem tocar na base.
- `POST /rotas/{data}/paragens` `{loja_id, motivo?, versao?}` → **201** com
  a rota completa. Sem rota nesse dia, cria-a em `rascunho` (versão 1) já
  com a primeira paragem, numa só `insert_one`; com rota, `$push` da paragem
  no fim (`ordem = n` ativas) com a versão + 1; uma loja retirada antes é
  reativada na mesma paragem (o mesmo `id`, pelos caminhos
  `paragens.<índice>.<campo do escritório>`, sem `$push`), com o motivo, o
  tempo e os sinais repostos e as horas a `None`. O motivo vem do corpo ou,
  em falta, da fase da loja (`rotas.motivo_por_fase`); o tempo de serviço é
  o padrão do motivo nas definições em vigor. Pela ordem das verificações
  do plano §4: 400 → 422 (`data` e corpo, juntos) → 404 "Loja não
  encontrada." → 409 `rota_fechada` (um dia anterior a hoje) → 409
  `rota_em_curso` (a rota fora dos estados editáveis ou com algum registo
  do motorista, mesmo numa paragem retirada) → 409 `conflito` (só com
  `versao` no corpo: `null` quer dizer "julgo que ainda não há rota") → 409
  `ja_na_rota` → 409 `rota_cheia` (48 ativas) → a escrita condicional. Sem
  `versao` (o cartão do mapa não a conhece), uma escrita que não casa relê a
  rota e tenta de novo, até `TENTATIVAS_SEM_VERSAO` vezes, e só depois dá
  409 `conflito`; se entretanto o motorista registou algo
  (`rotas_bd.porque_falhou` → `em_curso`), 409 `rota_em_curso` logo. Duas
  pessoas a criar a rota do mesmo dia: a segunda `insert_one` falha pelo
  índice único de `data` e volta-se a ler (sem versão, acrescenta-se; com
  `versao: null`, é um `conflito`).

O "hoje" é o dia em Lisboa do relógio do CRM, lido UMA vez por pedido (ao
ler, `relogio.hoje()`; ao escrever, `relogio.agora()` e o seu
`relogio.hoje(agora)`): a validação, os instantes gravados e a resposta usam
o mesmo instante (à meia-noite não se valida com um dia e grava com outro).
"""
from typing import Dict, Optional

from fastapi import APIRouter, Depends

from . import db as bd
from . import relogio, rotas_bd
from .auth import ESCRITORIO
from .definicoes import em_vigor
from .dominio import rotas, validador_rota
from .dominio.datas import texto_data
from .erros import erro, nao_encontrado, validacao
from .formatar_rota import PROJECAO_LOJA_ROTA, documento_paragem, documento_rota, resumo_rota_api, rota_api
from .lojas import MENSAGEM_CONFLITO, MENSAGEM_NAO_ENCONTRADA
from .pedidos import corpo_json
from .servicos import ors

router = APIRouter()

# As mensagens dos 409 das rotas (plano F3 §4), pelo código de `erros.ESTADOS`.
MENSAGEM_JA_NA_ROTA = "Esta loja já está na rota deste dia."
MENSAGEM_ROTA_CHEIA = f"Uma rota tem no máximo {rotas.LIMITE_PARAGENS} paragens."
MENSAGEM_ROTA_FECHADA = "Este dia já passou — a rota só se pode ver."
MENSAGEM_ROTA_EM_CURSO = "A rota já tem registos do motorista — no escritório só se pode ver."
MENSAGENS_DO_BLOQUEIO = {"rota_fechada": MENSAGEM_ROTA_FECHADA, "rota_em_curso": MENSAGEM_ROTA_EM_CURSO}

# Sem `versao` no corpo, quantas vezes se lê e tenta gravar antes do 409 `conflito`.
TENTATIVAS_SEM_VERSAO = 3


@router.get("/rotas")
async def listar_rotas(
    membro: Dict = Depends(ESCRITORIO),
    de: Optional[str] = None,
    ate: Optional[str] = None,
) -> Dict:
    """As rotas dos dias `de`..`ate` (por omissão hoje − 14 / hoje + 60), por
    `data`, cada uma só com o resumo."""
    hoje = relogio.hoje()
    dias, erros = validador_rota.intervalo(de, ate, hoje)
    if erros:
        raise validacao(erros)
    inicio, fim = dias
    rotas_lidas = await rotas_bd.rotas_entre(bd.obter_db(), texto_data(inicio), texto_data(fim))
    return {
        "hoje": texto_data(hoje),
        "de": texto_data(inicio),
        "ate": texto_data(fim),
        "rotas": [resumo_rota_api(rota, hoje) for rota in rotas_lidas],
    }


@router.get("/rotas/{data}")
async def ver_rota(data: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """A rota do dia `data`, completa e com as lojas, ou a virtual de um dia
    sem rota."""
    hoje = relogio.hoje()
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    if erros:
        raise validacao(erros)
    base = bd.obter_db()
    rota = await rotas_bd.ler(base, texto_data(dia))
    lojas = await rotas_bd.lojas_da_rota(base, rota)
    definicoes = await em_vigor(base)
    return _resposta(rota, dia, hoje, lojas, definicoes)


@router.post("/rotas/{data}/paragens", status_code=201)
async def adicionar_paragem(data: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{loja_id, motivo?, versao?}` → 201 com a rota do dia como ficou (a
    ordem das verificações está no docstring do módulo)."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    dados, erros_do_corpo = validador_rota.adicao(corpo)
    erros.update(erros_do_corpo)
    if erros:
        raise validacao(erros)

    base = bd.obter_db()
    loja = await base[bd.COLECOES["lojas"]].find_one({"id": dados["loja_id"]}, PROJECAO_LOJA_ROTA)
    if loja is None:
        raise nao_encontrado(MENSAGEM_NAO_ENCONTRADA)
    definicoes = await em_vigor(base)
    motivo = dados["motivo"] if dados["motivo"] is not None else rotas.motivo_por_fase(loja["fase"])
    servico = rotas.servico_padrao(motivo, definicoes)
    membro_id = membro["user_id"]
    texto = texto_data(dia)

    for _ in range(1 if dados["com_versao"] else TENTATIVAS_SEM_VERSAO):
        rota = await rotas_bd.ler(base, texto)
        bloqueio = rotas.bloqueio_de_escrita(rota, dia, hoje)
        if bloqueio is not None:
            raise erro(409, bloqueio, MENSAGENS_DO_BLOQUEIO[bloqueio])
        if dados["com_versao"] and (None if rota is None else rota["versao"]) != dados["versao"]:
            raise _conflito()
        if rota is None:
            nova = documento_rota(dia, membro_id, agora, definicoes)
            nova["paragens"].append(documento_paragem(loja, motivo, servico, 0, membro_id, agora))
            if await rotas_bd.criar(base, nova):
                depois = nova
                break
            continue  # outra pessoa criou a rota deste dia entretanto: reler
        ativas = rotas.ativas(rota["paragens"])
        if any(paragem["loja_id"] == loja["id"] for paragem in ativas):
            raise erro(409, "ja_na_rota", MENSAGEM_JA_NA_ROTA)
        if len(ativas) >= rotas.LIMITE_PARAGENS:
            raise erro(409, "rota_cheia", MENSAGEM_ROTA_CHEIA)
        depois = await _gravar_paragem(base, rota, loja, motivo, servico, len(ativas), membro_id, agora)
        if depois is not None:
            break
        if await rotas_bd.porque_falhou(base, rota["id"], rota["versao"]) == rotas_bd.EM_CURSO:
            raise erro(409, "rota_em_curso", MENSAGEM_ROTA_EM_CURSO)
    else:
        raise _conflito()

    lojas = await rotas_bd.lojas_da_rota(base, depois)
    return _resposta(depois, dia, hoje, lojas, definicoes)


async def _gravar_paragem(base, rota, loja, motivo, servico, ordem, membro_id, agora):
    """A escrita condicional da paragem na `rota` lida: a reativação de uma
    paragem retirada da mesma loja (a primeira, pela posição na lista; só há
    uma, porque adicionar outra vez reativa em vez de acrescentar) pelos
    caminhos do escritório, ou o `$push` de uma paragem nova no fim. Devolve
    a rota como ficou, ou `None` se o filtro de guarda não casou."""
    paragem = documento_paragem(loja, motivo, servico, ordem, membro_id, agora)
    retirada = next(
        (i for i, p in enumerate(rota["paragens"]) if p["loja_id"] == loja["id"] and p.get("removida_em") is not None),
        None,
    )
    if retirada is None:
        return await rotas_bd.acrescentar_paragem(base, rota, paragem, membro_id=membro_id, agora=agora)
    # A paragem reativada fica tal e qual uma nova, salvo o `id`, o `loja_id`
    # e o terreno, que não se tocam: só os campos do escritório.
    campos = {campo: paragem[campo] for campo in rotas.CAMPOS_DO_ESCRITORIO}
    return await rotas_bd.alterar(base, rota, rotas.caminhos_paragem(retirada, campos), membro_id=membro_id, agora=agora)


def _conflito():
    return erro(409, "conflito", MENSAGEM_CONFLITO)


def _resposta(rota, dia, hoje, lojas, definicoes) -> Dict:
    return rota_api(
        rota,
        data=dia,
        hoje=hoje,
        lojas=lojas,
        definicoes=definicoes,
        calculo_disponivel=bool(ors.chave()),
    )
