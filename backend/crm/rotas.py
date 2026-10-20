"""`/api/crm/rotas` — as rotas de um dia (F3: planear rota, versão simples).

Plano F3 §4; T3.18 (ler), T3.19 (adicionar uma loja), T3.20 (alterar a
rota do dia) e T3.21 (as horas pelo Directions). Só o escritório
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
- `GET /rotas/{data}/sugestoes` → `{sem_paragens, no_caminho, grupos}` do
  `dominio.sugestoes` (T3.9): as lojas contactadas e depois as potenciais a
  ≤ 5 km de qualquer paragem ativa com loja e, com `calculo.atual`, também
  as a ≤ 3 km da linha gravada (o corredor; a atualidade é a mesma conta do
  `rota_api`, com as definições em vigor a resolver a fábrica). Lê a rota,
  as lojas das paragens ativas (`lojas_da_rota`) e, só com paragens, todas
  as lojas pela `PROJECAO_LOJA_SUGESTAO` (nunca o telefone); sem cálculo
  não lê as definições. As lojas das paragens ativas (também as fechadas,
  as `nao_cabe` e as sem loja) nunca se sugerem; uma retirada volta a ser
  sugerida. Sem rota ou sem paragens com loja → `sem_paragens: true`, sem
  ler as lojas. Só leitura: uma rota passada ou com registo do motorista
  responde na mesma; nunca chama o openrouteservice. 422 em `data`, como o
  `GET /rotas/{data}`.
- `POST /rotas/{data}/paragens` `{loja_id, motivo?, versao?}` → **201** com
  a rota completa. Sem rota nesse dia, cria-a em `rascunho` (versão 1) já
  com a primeira paragem, numa só `insert_one`; com rota, `$push` da paragem
  no fim (`ordem = n` ativas) com a versão + 1; uma loja retirada antes é
  reativada na mesma paragem (o mesmo `id`, pelos caminhos
  `paragens.<índice>.<campo do escritório>`, sem `$push`), com o motivo, o
  tempo e os sinais repostos e as horas a `None`; se volta à secção "rota"
  (não fecha nesse dia), o `calculo` gravado limpa-se na mesma escrita
  (correção "F3-MAT-1": com o mesmo `id`, a entrada podia voltar a ser a do
  cálculo gravado e a API dizia `atual: true` com a paragem sem hora). O
  motivo vem do corpo ou,
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
- `PATCH /rotas/{data}` `{versao, hora_saida?, hora_regresso_limite?, inicio?,
  fim?, evitar_portagens?, ordem?, paragens?, retirar?, estado?}` → 200 com
  a rota completa. As definições do dia, a ordem, as paragens, retirar e
  "Guardar rota" (`estado: "planeada"`) gravam-se numa só
  `find_one_and_update` (`rotas_bd.alterar`: o filtro de guarda com a
  `versao` recebida e o cálculo lido, o `$set` só do que muda e o `$inc` da
  versão). O que já
  está gravado com o mesmo valor não se escreve e, sem nada a mudar (também
  um PATCH só com a `versao`), responde 200 sem escrever e sem subir a
  versão. Por campo: as horas comparam-se com as guardadas
  (`coerencia_horas`, só quando o pedido traz uma hora); `inicio`/`fim`
  como ponto ou `null` (a fábrica); a `ordem` é leniente (`rotas.nova_ordem`:
  as ativas em falta vão para o fim, pela ordem delas) e só as posições que
  mudam se escrevem; `paragens.<id>.motivo` sem tempo põe o padrão do
  motivo novo nas definições em vigor (com tempo, o enviado ganha; o mesmo
  motivo não mexe no tempo); `retirar` põe `removida_em` de agora e
  `ordem` nula e renumera as que ficam 0..k−1 (os ids de `retirar` saem da
  `ordem`: correção "T3.4 / T3.20"). Uma escrita que deixe a rota sem
  paragens incluídas (nenhuma na secção "rota") limpa o `calculo` na mesma
  escrita, se havia um (correção "T3.20 / T3.27"), e as horas das ativas
  que as tenham, como o recalcular e o otimizar (correção "F3-MAT-2"; as
  retiradas não se tocam). Pela ordem das
  verificações do plano §4: 400 → 422 (`data` e corpo, juntos) → 404 "Ainda
  não há rota para este dia." (uma rota só nasce com a primeira paragem;
  também num dia passado) → 409 `rota_fechada` → 409 `rota_em_curso` → 409
  `conflito` → 422 contra a rota (um id que não é de uma paragem ativa, em
  `ordem`, `paragens.<id>` ou `retirar`; a coerência das horas) → a escrita
  condicional. Se não casar, `rotas_bd.porque_falhou` decide, sem nova
  tentativa: `nao_existe` → 404, `em_curso` → 409 `rota_em_curso`, senão
  409 `conflito`.
- `POST /rotas/{data}/recalcular` `{versao}` → 200 com a rota completa e as
  horas do Directions (`calculo.atual: true`). As horas vêm **só do
  Directions** (§1 "Horas"): um POST `/v2/directions/driving-car/json`
  (`servicos.ors.direcoes`) com as coordenadas `[início] + incluídas + [fim]`
  — as paragens da secção "rota" pela ordem (`rotas.seccoes`: sem as
  fechadas sem "Manter", as `nao_cabe` e as `sem_loja`), o início e o fim
  próprios da rota ou a fábrica das definições em vigor — e `avoid_features`
  com `evitar_portagens`; ao openrouteservice só vão coordenadas e
  constantes (§0, regra 12). Os troços (`directions.interpretar_direcoes`)
  dão as chegadas, as esperas e os avisos (`horarios.calcular_horarios`) e
  gravam-se numa só `find_one_and_update` **sem subir a versão**
  (`rotas_bd.alterar(..., subir_versao=False)`: dados derivados, com o filtro
  da versão e do cálculo lidos): por paragem ativa,
  `paragens.N.chegada_prevista|espera_min|fora_de_horario` só do que muda
  (as excluídas ficam a `None`/`None`/`False`)
  e o `calculo` inteiro (a assinatura da entrada, os totais, o regresso, a
  geometria e `calculado_em` de agora). Sem paragens incluídas não se chama
  o openrouteservice: o `calculo` que havia limpa-se (`calculo: None`) e as
  ativas ficam sem horas (correção "F3-MAT-2": também sem cálculo gravado),
  e sem nada a limpar responde-se 200 sem escrever. Pela ordem das
  verificações do plano §4: 400 → 422 (`data` e `versao`, juntos) → 404
  "Ainda não há rota
  para este dia." → 409 `rota_fechada` → 409 `rota_em_curso` → 409
  `conflito` → 503 `calculo_indisponivel` (nada muda; `tipo` no erro:
  `sem_chave` sem pedido nenhum, `limite` no 429, `ponto_sem_estrada` num
  2010 — a mensagem diz a paragem N da secção "rota", o início ou o fim —,
  `indisponivel` no resto; fica um aviso no registo só com o motivo) → a
  escrita condicional → a falha, como no PATCH.
- `POST /rotas/{data}/otimizar` `{versao}` → 200 com a rota completa pela
  melhor ordem, e a versão + 1. Primeiro o VROOM (um POST `/optimization`,
  `servicos.ors.otimizar`, pelo `dominio.vroom`): vão todas as paragens
  ativas com loja — as da secção "rota" e as `nao_cabe` de um cálculo
  anterior —, pela ordem gravada, e ficam de fora só as fechadas nesse dia
  sem "Manter" e as `sem_loja` (correções "T3.22" e "T3.22 / §1"); um *job*
  por paragem (`id` 1..n, `[lng, lat]`, o serviço em segundos, a prioridade
  100 na entrega e 1 nas outras, as janelas `[a, b − s]`), as impossíveis
  (nenhuma janela leva o serviço) não se enviam e sem nenhum *job* não se
  chama nada. **Depois sempre o Directions**, só com as atribuídas e pela
  ordem devolvida; sem nenhuma atribuída (`routes: []`, ou nenhum *job*)
  não se chama e o `calculo` fica `None` (correção "T3.6 / T3.22"). É
  **atómico**: uma falha em qualquer dos dois é o 503 `calculo_indisponivel`
  (com o aviso "(otimizar)" no registo) e nada muda; num 2010 do Directions
  a mensagem diz o número ATUAL da paragem na rota gravada (a ordem nova
  ainda não está gravada), ou a geral se ela não tiver número. Uma só
  `find_one_and_update` (`rotas_bd.alterar`, com o `$inc` da versão: o
  plano muda): a `ordem` — a do VROOM, as não atribuídas, as impossíveis,
  as fechadas e as `sem_loja` (`rotas.nova_ordem`) —, os sinais `nao_cabe`
  de todas as enviadas (`True` nas não atribuídas e nas impossíveis, `False`
  nas atribuídas), as horas das atribuídas (nenhumas nas outras ativas) e o
  `calculo`; só o que muda, e sem nada a mudar 200 sem escrever e sem subir
  a versão. As verificações pela ordem do recalcular, e a falha da escrita
  como no PATCH.

O "hoje" é o dia em Lisboa do relógio do CRM, lido UMA vez por pedido (ao
ler, `relogio.hoje()`; ao escrever, `relogio.agora()` e o seu
`relogio.hoje(agora)`): a validação, os instantes gravados e a resposta usam
o mesmo instante (à meia-noite não se valida com um dia e grava com outro).
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends

from . import db as bd
from . import relogio, rotas_bd
from .auth import ESCRITORIO
from .definicoes import em_vigor
from .dominio import directions, horarios, polilinha, rotas, sugestoes, validador_rota, vroom
from .dominio.datas import texto_data
from .dominio.horas import segundos
from .dominio.vroom import RespostaInvalida
from .erros import erro, nao_encontrado, validacao
from .formatar_rota import PROJECAO_LOJA_ROTA, documento_paragem, documento_rota, resumo_rota_api, rota_api
from .lojas import MENSAGEM_CONFLITO, MENSAGEM_NAO_ENCONTRADA
from .pedidos import corpo_json
from .servicos import ors
from .servicos.ors import FalhaOrs

logger = logging.getLogger(__name__)

router = APIRouter()

# As mensagens dos 409 das rotas (plano F3 §4), pelo código de `erros.ESTADOS`.
MENSAGEM_JA_NA_ROTA = "Esta loja já está na rota deste dia."
MENSAGEM_ROTA_CHEIA = f"Uma rota tem no máximo {rotas.LIMITE_PARAGENS} paragens."
MENSAGEM_ROTA_FECHADA = "Este dia já passou — a rota só se pode ver."
MENSAGEM_ROTA_EM_CURSO = "A rota já tem registos do motorista — no escritório só se pode ver."
MENSAGENS_DO_BLOQUEIO = {"rota_fechada": MENSAGEM_ROTA_FECHADA, "rota_em_curso": MENSAGEM_ROTA_EM_CURSO}
# O 404 do `PATCH` (código `nao_encontrado`, plano F3 §4): uma rota só nasce
# com a primeira paragem.
MENSAGEM_SEM_ROTA = "Ainda não há rota para este dia."

# As mensagens do 503 `calculo_indisponivel` (plano F3 §1 "Mensagens das
# falhas do ORS" e §4), pelo `tipo` da `FalhaOrs`.
MENSAGEM_CALCULO_INDISPONIVEL = "Cálculo automático indisponível — ordene à mão"
MENSAGEM_CALCULO_LIMITE = (
    "Cálculo automático indisponível por agora (limite de pedidos) — espere um minuto ou ordene à mão"
)
MENSAGEM_PARAGEM_SEM_ESTRADA = "A paragem {numero} não fica perto de uma estrada — corrija a localização da loja"
MENSAGEM_INICIO_SEM_ESTRADA = "O ponto de início não fica perto de uma estrada — escolha outro ponto"
MENSAGEM_FIM_SEM_ESTRADA = "O ponto de fim não fica perto de uma estrada — escolha outro ponto"

# Os campos de topo que o `PATCH` escreve tal e qual (pela ordem do validador).
CAMPOS_DO_DIA = ("hora_saida", "hora_regresso_limite", "inicio", "fim", "evitar_portagens", "estado")

# As horas de uma paragem que o Directions não leva (fechada sem "Manter",
# `nao_cabe`, sem loja): nenhuma.
SEM_HORAS = {"chegada_prevista": None, "espera_min": None, "fora_de_horario": False}

# As lojas de todas as sugestões leem-se só com isto (plano, T3.23): nunca o
# telefone, a morada, as notas nem a pessoa de contacto.
PROJECAO_LOJA_SUGESTAO = {"_id": 0, "id": 1, "nome": 1, "fase": 1, "lat": 1, "lng": 1, "dias_fechada": 1}

# As secções cujas paragens vão ao VROOM no otimizar: as da rota e as que não
# couberam no cálculo anterior (correção "T3.22 / §1"); as fechadas sem
# "Manter" e as `sem_loja` ficam de fora.
SECCOES_PARA_O_VROOM = ("rota", "nao_cabe")

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


@router.get("/rotas/{data}/sugestoes")
async def sugestoes_da_rota(data: str, membro: Dict = Depends(ESCRITORIO)) -> Dict:
    """As lojas para aproveitar a viagem do dia `data` (`dominio.sugestoes`):
    perto das paragens ativas e, com o cálculo atual, no caminho da linha."""
    hoje = relogio.hoje()
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    if erros:
        raise validacao(erros)
    base = bd.obter_db()
    rota = await rotas_bd.ler(base, texto_data(dia))
    lojas_das_paragens = await rotas_bd.lojas_da_rota(base, rota)
    if not lojas_das_paragens:
        return sugestoes.sugerir([], [], [], dia)
    todas = await base[bd.COLECOES["lojas"]].find({}, PROJECAO_LOJA_SUGESTAO).to_list(None)
    ids_na_rota = [paragem["loja_id"] for paragem in rotas.ativas(rota["paragens"])]
    linha = await _linha_da_rota(base, rota, lojas_das_paragens, dia)
    return sugestoes.sugerir(todas, lojas_das_paragens, ids_na_rota, dia, linha)


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
        depois = await _gravar_paragem(base, rota, loja, motivo, servico, len(ativas), dia, membro_id, agora)
        if depois is not None:
            break
        if await rotas_bd.porque_falhou(base, rota["id"], rota["versao"]) == rotas_bd.EM_CURSO:
            raise erro(409, "rota_em_curso", MENSAGEM_ROTA_EM_CURSO)
    else:
        raise _conflito()

    lojas = await rotas_bd.lojas_da_rota(base, depois)
    return _resposta(depois, dia, hoje, lojas, definicoes)


@router.patch("/rotas/{data}")
async def alterar_rota(data: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{versao, hora_saida?, hora_regresso_limite?, inicio?, fim?,
    evitar_portagens?, ordem?, paragens?, retirar?, estado?}` → 200 com a
    rota do dia como ficou (a ordem das verificações está no docstring do
    módulo)."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    dados, erros_do_corpo = validador_rota.alteracao(corpo)
    erros.update(erros_do_corpo)
    if erros:
        raise validacao(erros)

    base = bd.obter_db()
    rota = await rotas_bd.ler(base, texto_data(dia))
    if rota is None:
        raise nao_encontrado(MENSAGEM_SEM_ROTA)
    bloqueio = rotas.bloqueio_de_escrita(rota, dia, hoje)
    if bloqueio is not None:
        raise erro(409, bloqueio, MENSAGENS_DO_BLOQUEIO[bloqueio])
    if rota["versao"] != dados["versao"]:
        raise _conflito()
    erros = _contra_a_rota(rota, dados)
    if erros:
        raise validacao(erros)

    lojas = await rotas_bd.lojas_da_rota(base, rota)
    definicoes = await em_vigor(base)
    set_ = _alteracoes(rota, dados, definicoes, agora)
    if set_:
        paragens = _paragens_depois(rota, set_)
        if not _com_incluidas(paragens, lojas, dia):
            _sem_horas_nem_calculo(set_, rota, rotas.ativas(paragens))
    if not set_:
        return _resposta(rota, dia, hoje, lojas, definicoes)
    depois = await rotas_bd.alterar(base, rota, set_, membro_id=membro["user_id"], agora=agora)
    if depois is None:
        raise await _erro_da_escrita(base, rota)
    return _resposta(depois, dia, hoje, lojas, definicoes)


@router.post("/rotas/{data}/recalcular")
async def recalcular_rota(data: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{versao}` → 200 com a rota do dia e as horas do Directions (a ordem
    das verificações está no docstring do módulo). A versão não muda."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    dados, erros_do_corpo = validador_rota.so_versao(corpo)
    erros.update(erros_do_corpo)
    if erros:
        raise validacao(erros)

    base = bd.obter_db()
    rota = await rotas_bd.ler(base, texto_data(dia))
    if rota is None:
        raise nao_encontrado(MENSAGEM_SEM_ROTA)
    bloqueio = rotas.bloqueio_de_escrita(rota, dia, hoje)
    if bloqueio is not None:
        raise erro(409, bloqueio, MENSAGENS_DO_BLOQUEIO[bloqueio])
    if rota["versao"] != dados["versao"]:
        raise _conflito()

    lojas = await rotas_bd.lojas_da_rota(base, rota)
    definicoes = await em_vigor(base)
    seccoes = rotas.seccoes(rota["paragens"], {loja["id"]: loja for loja in lojas}, dia)
    incluidas = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao == "rota"]
    if incluidas:
        set_ = await _horas_pelo_directions(rota, seccoes, incluidas, definicoes, agora)
    else:
        set_ = {}
        _sem_horas_nem_calculo(set_, rota, [paragem for paragem, _, _, _ in seccoes])
        if not set_:
            return _resposta(rota, dia, hoje, lojas, definicoes)
    depois = await rotas_bd.alterar(base, rota, set_, subir_versao=False, membro_id=membro["user_id"], agora=agora)
    if depois is None:
        raise await _erro_da_escrita(base, rota)
    return _resposta(depois, dia, hoje, lojas, definicoes)


@router.post("/rotas/{data}/otimizar")
async def otimizar_rota(data: str, membro: Dict = Depends(ESCRITORIO), corpo: Dict = Depends(corpo_json)) -> Dict:
    """`{versao}` → 200 com a rota do dia pela melhor ordem do VROOM, os
    sinais `nao_cabe` e as horas do Directions (a ordem das verificações está
    no docstring do módulo). A versão sobe."""
    agora = relogio.agora()
    hoje = relogio.hoje(agora)
    dia, erros = validador_rota.data_do_caminho(data, hoje)
    dados, erros_do_corpo = validador_rota.so_versao(corpo)
    erros.update(erros_do_corpo)
    if erros:
        raise validacao(erros)

    base = bd.obter_db()
    rota = await rotas_bd.ler(base, texto_data(dia))
    if rota is None:
        raise nao_encontrado(MENSAGEM_SEM_ROTA)
    bloqueio = rotas.bloqueio_de_escrita(rota, dia, hoje)
    if bloqueio is not None:
        raise erro(409, bloqueio, MENSAGENS_DO_BLOQUEIO[bloqueio])
    if rota["versao"] != dados["versao"]:
        raise _conflito()

    lojas = await rotas_bd.lojas_da_rota(base, rota)
    definicoes = await em_vigor(base)
    seccoes = rotas.seccoes(rota["paragens"], {loja["id"]: loja for loja in lojas}, dia)
    set_ = await _melhor_ordem(rota, seccoes, definicoes, agora)
    if not set_:
        return _resposta(rota, dia, hoje, lojas, definicoes)
    depois = await rotas_bd.alterar(base, rota, set_, membro_id=membro["user_id"], agora=agora)
    if depois is None:
        raise await _erro_da_escrita(base, rota)
    return _resposta(depois, dia, hoje, lojas, definicoes)


async def _horas_pelo_directions(rota, seccoes, incluidas, definicoes, agora) -> Dict:
    """O `$set` do recalcular sobre a `rota` lida: um pedido ao Directions com
    `[início] + incluídas + [fim]` (`_trocos_e_horas`), as chegadas e as
    esperas do domínio pelos caminhos `paragens.<índice>.<campo>` (só o que
    muda; as excluídas sem horas) e o `calculo` inteiro."""
    inicio = _ponto_resolvido(rota["inicio"], definicoes)
    fim = _ponto_resolvido(rota["fim"], definicoes)
    trocos, horas = await _trocos_e_horas(rota, incluidas, inicio, fim, "recalcular")
    set_ = {}
    _horas_no_set(set_, rota, [paragem for paragem, _, _, _ in seccoes], horas.por_paragem)
    set_["calculo"] = _documento_calculo(rota, incluidas, inicio, fim, trocos, horas, agora)
    return set_


async def _melhor_ordem(rota, seccoes, definicoes, agora) -> Dict:
    """O `$set` do otimizar sobre a `rota` lida: só o que muda, e `{}` sem
    nada a mudar.

    Ao VROOM vão todas as paragens ativas com loja — as da secção "rota" e as
    `nao_cabe` de um cálculo anterior —, pela ordem gravada; ficam de fora só
    as fechadas nesse dia sem "Manter" e as `sem_loja` (correções "T3.22" e
    "T3.22 / §1"). As impossíveis (nenhuma janela leva o serviço) não se
    enviam (`vroom.pedido_otimizacao`) e sem nenhum *job* não se chama o
    openrouteservice. Depois, o Directions só com as atribuídas, pela ordem
    devolvida (`_trocos_e_horas`); sem nenhuma atribuída (`routes: []`, ou
    nenhum *job*) não se chama e o `calculo` fica `None` (correção "T3.6 /
    T3.22"). Tudo ou nada: uma falha em qualquer dos dois é o 503 antes de se
    escrever o que quer que seja.

    No `$set`: a `ordem` nova — a do VROOM, as não atribuídas, as impossíveis,
    as fechadas e as `sem_loja` (`rotas.nova_ordem`), pelos caminhos por
    índice —, os sinais `nao_cabe` de todas as enviadas (`True` nas não
    atribuídas e nas impossíveis, `False` nas atribuídas), as horas das
    atribuídas e nenhumas nas outras ativas, e o `calculo`.
    """
    inicio = _ponto_resolvido(rota["inicio"], definicoes)
    fim = _ponto_resolvido(rota["fim"], definicoes)
    enviaveis = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao in SECCOES_PARA_O_VROOM]
    pedido = vroom.pedido_otimizacao(
        [vroom.paragem_calculo(paragem, loja) for paragem, loja in enviaveis],
        inicio,
        fim,
        segundos(rota["hora_saida"]),
        segundos(rota["hora_regresso_limite"]),
    )
    ordem_vroom, nao_atribuidas = ([], []) if pedido.corpo is None else await _ordem_pelo_vroom(rota, pedido)
    nao_cabem = [*nao_atribuidas, *pedido.impossiveis]

    enviada = {paragem["id"]: (paragem, loja) for paragem, loja in enviaveis}
    atribuidas = [enviada[id_] for id_ in ordem_vroom]
    por_paragem, calculo = {}, None
    if atribuidas:
        numero_atual = {paragem["id"]: numero for paragem, _, _, numero in seccoes}
        numeros = [numero_atual[paragem["id"]] for paragem, _ in atribuidas]
        trocos, horas = await _trocos_e_horas(rota, atribuidas, inicio, fim, "otimizar", numeros)
        por_paragem = horas.por_paragem
        calculo = _documento_calculo(rota, atribuidas, inicio, fim, trocos, horas, agora)

    set_ = {}
    indice = {paragem["id"]: i for i, paragem in enumerate(rota["paragens"])}
    ativas = [paragem for paragem, _, _, _ in seccoes]
    por_id = {paragem["id"]: paragem for paragem in ativas}
    de_fora = [
        paragem["id"]
        for qual in ("fechada", "sem_loja")
        for paragem, _, seccao, _ in seccoes
        if seccao == qual
    ]
    for posicao, id_ in enumerate(rotas.nova_ordem(ativas, [*ordem_vroom, *nao_cabem, *de_fora])):
        if por_id[id_]["ordem"] != posicao:
            set_.update(rotas.caminhos_paragem(indice[id_], {"ordem": posicao}))
    fora = set(nao_cabem)
    for paragem, _ in enviaveis:
        nao_cabe = paragem["id"] in fora
        if paragem["nao_cabe"] != nao_cabe:
            set_.update(rotas.caminhos_paragem(indice[paragem["id"]], {"nao_cabe": nao_cabe}))
    _horas_no_set(set_, rota, ativas, por_paragem)
    if calculo is not None:
        set_["calculo"] = calculo
    elif rota["calculo"] is not None:
        set_["calculo"] = None
    return set_


async def _ordem_pelo_vroom(rota, pedido) -> tuple:
    """`(ordem, nao_atribuidas)` — ids de paragens — do VROOM para o `pedido`
    (`vroom.PedidoOtimizacao` com corpo): um POST `/optimization`
    (`servicos.ors.otimizar`) e o parser estrito
    (`vroom.interpretar_otimizacao`). Uma falha do openrouteservice, ou uma
    resposta sem a forma esperada, é o 503 `calculo_indisponivel` (lançado
    fora do `except`, sem a exceção como causa) com um aviso no registo; na
    otimização não há coordenada a apontar, por isso só o `tipo` conta."""
    falha = None
    try:
        return vroom.interpretar_otimizacao(await ors.otimizar(pedido.corpo), pedido.por_job)
    except FalhaOrs as excecao:
        falha = (excecao.tipo, excecao.motivo)
    except RespostaInvalida as excecao:
        falha = ("indisponivel", excecao.motivo)
    tipo, motivo = falha
    _registar_falha(rota, "otimizar", motivo)
    raise _calculo_indisponivel(tipo, None, 0)


async def _trocos_e_horas(rota, incluidas, inicio, fim, operacao, numeros=None) -> tuple:
    """`(trocos, horas)` do Directions para `[início] + incluídas + [fim]`: o
    pedido (`directions.pedido_direcoes`: só coordenadas e constantes), o
    POST (`servicos.ors.direcoes`), os troços (`directions.interpretar_direcoes`)
    e as chegadas, as esperas e os avisos (`horarios.calcular_horarios`). Uma
    falha do openrouteservice, ou uma resposta sem a forma esperada, é o 503
    `calculo_indisponivel` (lançado fora do `except`, sem a exceção como
    causa) com um aviso no registo da `operacao`; `numeros` dá o número atual
    de cada incluída para a mensagem do 2010, quando não é a sua posição."""
    pontos = [inicio, *((loja["lat"], loja["lng"]) for _, loja in incluidas), fim]
    pedido = directions.pedido_direcoes(pontos, rota["evitar_portagens"])

    falha = None
    try:
        trocos = directions.interpretar_direcoes(await ors.direcoes(pedido), len(pontos))
    except FalhaOrs as excecao:
        falha = (excecao.tipo, excecao.indice, excecao.motivo)
    except RespostaInvalida as excecao:
        falha = ("indisponivel", None, excecao.motivo)
    if falha is not None:
        tipo, indice, motivo = falha
        _registar_falha(rota, operacao, motivo)
        raise _calculo_indisponivel(tipo, indice, len(pontos), numeros)

    horas = horarios.calcular_horarios(
        segundos(rota["hora_saida"]),
        segundos(rota["hora_regresso_limite"]),
        [vroom.paragem_calculo(paragem, loja) for paragem, loja in incluidas],
        trocos.duracoes,
    )
    return trocos, horas


def _horas_no_set(set_, rota, ativas, por_paragem) -> None:
    """Junta ao `set_` as horas de cada paragem ativa pelos caminhos
    `paragens.<índice>.<campo>`: as de `por_paragem` (pelo id) nas que o
    Directions levou e nenhumas (`SEM_HORAS`) nas outras — só o que difere do
    gravado. As retiradas não se tocam."""
    indice = {paragem["id"]: i for i, paragem in enumerate(rota["paragens"])}
    for paragem in ativas:
        horas = por_paragem.get(paragem["id"], SEM_HORAS)
        mudam = {campo: valor for campo, valor in horas.items() if valor != paragem[campo]}
        set_.update(rotas.caminhos_paragem(indice[paragem["id"]], mudam))


def _documento_calculo(rota, incluidas, inicio, fim, trocos, horas, agora) -> Dict:
    """O `calculo` que fica gravado: a assinatura da entrada (a mesma conta do
    `rota_api`, por isso `calculo.atual: true` na resposta), os totais dos
    troços, o regresso, a linha e `calculado_em` de agora."""
    return {
        "assinatura": horarios.assinatura(horarios.entrada_calculo(rota, incluidas, inicio, fim)),
        "distancia_m": trocos.distancia_m,
        "duracao_s": trocos.duracao_s,
        "regresso_previsto": horas.regresso_previsto,
        "depois_do_limite": horas.depois_do_limite,
        "geometria": trocos.geometria,
        "calculado_em": relogio.instante(agora),
    }


def _registar_falha(rota, operacao, motivo) -> None:
    """O aviso no registo de uma falha do openrouteservice: só o dia, a
    operação (`recalcular`/`otimizar`) e o motivo fixo — nunca coordenadas,
    nomes, ids nem a chave."""
    logger.warning("[crm] rota %s: o openrouteservice falhou (%s) — %s", rota["data"], operacao, motivo)


async def _linha_da_rota(base, rota, lojas, dia):
    """A linha da rota para o corredor das sugestões: a geometria do `calculo`
    descodificada, só se o cálculo ainda é o atual — a mesma conta do
    `rota_api`: a assinatura gravada é a de `entrada_calculo` da rota como
    está, só com a secção "rota" pela ordem e o início e o fim resolvidos
    pelas definições em vigor. `None` sem cálculo (as definições nem se
    leem) ou com um cálculo velho."""
    calculo = rota["calculo"]
    if calculo is None:
        return None
    definicoes = await em_vigor(base)
    seccoes = rotas.seccoes(rota["paragens"], {loja["id"]: loja for loja in lojas}, dia)
    incluidas = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao == "rota"]
    inicio = _ponto_resolvido(rota["inicio"], definicoes)
    fim = _ponto_resolvido(rota["fim"], definicoes)
    if calculo["assinatura"] != horarios.assinatura(horarios.entrada_calculo(rota, incluidas, inicio, fim)):
        return None
    return polilinha.descodificar(calculo["geometria"])


def _ponto_resolvido(ponto, definicoes) -> tuple:
    """`(lat, lng)` do início ou do fim: o ponto da rota, ou a fábrica das
    definições em vigor quando é `None` (como o `rota_api` o resolve)."""
    if ponto is None:
        return (definicoes["fabrica_lat"], definicoes["fabrica_lng"])
    return (ponto["lat"], ponto["lng"])


def _calculo_indisponivel(tipo, indice, n_pontos, numeros=None):
    """O 503 `calculo_indisponivel` com a mensagem do `tipo` (plano F3 §1):
    `limite` → a do limite; `ponto_sem_estrada` → o ponto de início (a
    coordenada 0), o de fim (a última) ou a paragem N — as coordenadas 1..n
    são as paragens enviadas ao Directions, pela ordem, e N é o número atual
    de cada uma na rota gravada: a própria posição no recalcular (vai pela
    secção "rota") ou `numeros[i − 1]` no otimizar, cuja ordem ainda não está
    gravada (correção "T3.22"; sem número atual, a mensagem geral); um
    índice que não é de nenhum ponto, `sem_chave` e `indisponivel` → a geral."""
    mensagem = MENSAGEM_CALCULO_INDISPONIVEL
    if tipo == "limite":
        mensagem = MENSAGEM_CALCULO_LIMITE
    elif tipo == "ponto_sem_estrada":
        if indice == 0:
            mensagem = MENSAGEM_INICIO_SEM_ESTRADA
        elif indice == n_pontos - 1:
            mensagem = MENSAGEM_FIM_SEM_ESTRADA
        elif type(indice) is int and 0 < indice < n_pontos - 1:
            numero = indice if numeros is None else numeros[indice - 1]
            if numero is not None:
                mensagem = MENSAGEM_PARAGEM_SEM_ESTRADA.format(numero=numero)
        else:
            tipo = "indisponivel"
    return erro(503, "calculo_indisponivel", mensagem, tipo=tipo)


async def _erro_da_escrita(base, rota):
    """A escrita condicional não casou: `rotas_bd.porque_falhou` decide, sem
    nova tentativa — `nao_existe` → 404, `em_curso` → 409 `rota_em_curso`,
    senão 409 `conflito`."""
    motivo = await rotas_bd.porque_falhou(base, rota["id"], rota["versao"])
    if motivo == rotas_bd.NAO_EXISTE:
        return nao_encontrado(MENSAGEM_SEM_ROTA)
    if motivo == rotas_bd.EM_CURSO:
        return erro(409, "rota_em_curso", MENSAGEM_ROTA_EM_CURSO)
    return _conflito()


def _contra_a_rota(rota, dados) -> Dict:
    """Os 422 que só se veem com a rota lida (plano F3 §4), pela ordem das
    chaves: a coerência das horas (os valores do pedido juntos com os
    guardados; só quando o pedido traz uma hora) e os ids de `ordem`,
    `paragens.<id>` e `retirar` que não são de uma paragem ativa."""
    erros = {}
    if "hora_saida" in dados or "hora_regresso_limite" in dados:
        erros.update(validador_rota.coerencia_horas(
            dados.get("hora_saida", rota["hora_saida"]),
            dados.get("hora_regresso_limite", rota["hora_regresso_limite"]),
        ))
    na_rota = {paragem["id"] for paragem in rotas.ativas(rota["paragens"])}
    if any(id_ not in na_rota for id_ in dados.get("ordem", ())):
        erros["ordem"] = validador_rota.MENSAGEM_NAO_ESTA_NA_ROTA
    for id_ in dados.get("paragens", {}):
        if id_ not in na_rota:
            erros[f"paragens.{id_}"] = validador_rota.MENSAGEM_NAO_ESTA_NA_ROTA
    if any(id_ not in na_rota for id_ in dados.get("retirar", ())):
        erros["retirar"] = validador_rota.MENSAGEM_NAO_ESTA_NA_ROTA
    return erros


def _alteracoes(rota, dados, definicoes, agora) -> Dict:
    """O `$set` do PATCH sobre a `rota` lida: só o que muda. Os campos de
    topo tal e qual; por paragem, pelos caminhos `paragens.<índice>.<campo>`
    (`rotas.caminhos_paragem`): o motivo novo com o tempo padrão dele (o
    tempo enviado ganha), os sinais, o retirar (`removida_em` de agora e
    `ordem` nula) e as posições novas da ordem (`rotas.nova_ordem` sobre as
    ativas que ficam) que diferem das gravadas."""
    set_ = {}
    for campo in CAMPOS_DO_DIA:
        if campo in dados and dados[campo] != rota[campo]:
            set_[campo] = dados[campo]

    indice = {paragem["id"]: i for i, paragem in enumerate(rota["paragens"])}
    por_id = {paragem["id"]: paragem for paragem in rota["paragens"]}
    for id_, alteracoes in dados.get("paragens", {}).items():
        paragem = por_id[id_]
        campos = {}
        if "motivo" in alteracoes and alteracoes["motivo"] != paragem["motivo"]:
            campos["motivo"] = alteracoes["motivo"]
            campos["tempo_servico_min"] = rotas.servico_padrao(alteracoes["motivo"], definicoes)
        if "tempo_servico_min" in alteracoes:
            campos["tempo_servico_min"] = alteracoes["tempo_servico_min"]
        for sinal in ("manter_fechada", "nao_cabe"):
            if sinal in alteracoes:
                campos[sinal] = alteracoes[sinal]
        mudam = {campo: valor for campo, valor in campos.items() if valor != paragem[campo]}
        set_.update(rotas.caminhos_paragem(indice[id_], mudam))

    retirar = dados.get("retirar", [])
    for id_ in retirar:
        set_.update(rotas.caminhos_paragem(indice[id_], {"removida_em": relogio.instante(agora), "ordem": None}))
    if retirar or "ordem" in dados:
        ficam = [paragem for paragem in rotas.ativas(rota["paragens"]) if paragem["id"] not in retirar]
        for posicao, id_ in enumerate(rotas.nova_ordem(ficam, dados.get("ordem", []))):
            if por_id[id_]["ordem"] != posicao:
                set_.update(rotas.caminhos_paragem(indice[id_], {"ordem": posicao}))
    return set_


def _paragens_depois(rota, set_) -> list:
    """As paragens da `rota` lida com o `set_` aplicado (em memória, em
    cópias; a rota lida não muda)."""
    paragens = [dict(paragem) for paragem in rota["paragens"]]
    for caminho, valor in set_.items():
        if caminho.startswith("paragens."):
            _, i, campo = caminho.split(".")
            paragens[int(i)][campo] = valor
    return paragens


def _com_incluidas(paragens, lojas, dia) -> bool:
    """Fica alguma paragem na secção "rota" (`rotas.seccoes`: ativa, com
    loja, não fechada sem "Manter" e sem `nao_cabe`)? É o que o Directions
    levaria; sem nenhuma, `_sem_horas_nem_calculo`."""
    lojas_por_id = {loja["id"]: loja for loja in lojas}
    return any(seccao == "rota" for _, _, seccao, _ in rotas.seccoes(paragens, lojas_por_id, dia))


def _sem_horas_nem_calculo(set_, rota, ativas) -> None:
    """Junta ao `set_` o que uma rota sem paragens incluídas não pode ter: as
    horas das `ativas` (`SEM_HORAS`, só nas que as têm; correção "F3-MAT-2",
    como o otimizar e o recalcular com incluídas) e o `calculo` gravado
    (`None`, só se havia um; correção "T3.20 / T3.27"). As retiradas não se
    tocam."""
    _horas_no_set(set_, rota, ativas, {})
    if rota["calculo"] is not None:
        set_["calculo"] = None


async def _gravar_paragem(base, rota, loja, motivo, servico, ordem, dia, membro_id, agora):
    """A escrita condicional da paragem na `rota` lida: a reativação de uma
    paragem retirada da mesma loja (a primeira, pela posição na lista; só há
    uma, porque adicionar outra vez reativa em vez de acrescentar) pelos
    caminhos do escritório, ou o `$push` de uma paragem nova no fim. Devolve
    a rota como ficou, ou `None` se o filtro de guarda não casou.

    Uma reativação que volta à secção "rota" (a loja não fecha no `dia`; os
    sinais voltam a `False`) limpa o `calculo` gravado na mesma escrita
    (correção "F3-MAT-1"): a paragem fica sem horas, como uma nova, mas com
    o mesmo `id` — se a entrada voltar a ser a do cálculo gravado (retirada
    e reposta antes de outro recálculo), a assinatura batia e a API dizia
    `atual: true` com uma paragem da rota sem hora. Na secção "fechada" não
    entra no Directions, e o cálculo fica."""
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
    set_ = rotas.caminhos_paragem(retirada, campos)
    if rota["calculo"] is not None and not rotas.fechada_neste_dia(loja, dia):
        set_["calculo"] = None
    return await rotas_bd.alterar(base, rota, set_, membro_id=membro_id, agora=agora)


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
