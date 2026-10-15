"""As rotas entre a base (`crm_rotas`) e a API (plano F3 §3 e §4; T3.16).

O molde é o `formatar.py` das lojas (T2.10): só se escreve a base por aqui,
e o que vem da base lê-se chave a chave, pela ordem do plano.

- **Na base:** `documento_rota` (a rota nova, em `rascunho`, com a `versao`
  1, as horas das definições em vigor, a fábrica como início e fim —
  `None` —, sem paragens nem cálculo) e `documento_paragem` (a paragem nova,
  com os campos do terreno iniciais `pendente`/null/null: passa no
  `formatos.escritas_no_terreno` dos testes). Os instantes são do relógio do
  CRM (`relogio.instante`/`carimbo`), recebido por parâmetro: este módulo
  nunca lê o relógio nem o ambiente.
- **Na API:** `rota_api` (a rota completa, ou a **virtual** de um dia sem
  rota: `existe: false`, com os valores por omissão), com as paragens ativas
  por ordem (`dominio.rotas.seccoes`: `numero` só na secção "rota"), o aviso
  de cada uma, os links de navegação (`dominio.navegacao`) e a loja pela
  projeção `PROJECAO_LOJA_ROTA` (as janelas planas, como na ficha). O
  `calculo.atual` diz se as horas guardadas ainda servem: a assinatura
  gravada é a de agora (`horarios.entrada_calculo` + `assinatura`, só com a
  secção "rota"); uma loja que mudou de sítio, uma janela, a fábrica (quando
  a rota parte dela), a ordem ou as definições do dia tornam-nas velhas. Sem
  `calculo.atual`, o `fora_de_horario` não dá aviso (correção "T3.16 / T3.21
  / T3.32": as horas só valem com `atual`). `resumo_rota_api` é a linha do
  `GET /rotas`, lida sem o `calculo` (correção "T3.17 / T3.18").

Uma paragem reposta pelo terreno (`removida_em: null` com `ordem: null`,
correção "T3.3 / T3.16") lê-se sem erro: vai para o fim, com o número a
seguir, e a rota fica só de leitura (`editavel: false`, pelo
`bloqueio_de_escrita`).

Os dias (`data`, `hoje`) são `date` (`datas.ler_data`, `relogio.hoje`): outra
coisa é `TypeError`. Um documento estragado à mão (uma loja sem coordenadas
numéricas, uma janela a meio, um motivo desconhecido) é `ValueError` — um 500
—, nunca uma resposta com outra forma; um campo em falta é `KeyError`.
"""
import uuid
from datetime import date

from . import relogio
from .dominio import janelas, navegacao, rotas
from .dominio.datas import ler_data, texto_data
from .dominio.horarios import assinatura, entrada_calculo
from .dominio.numeros import e_inteiro_json
from .dominio.validador_loja import campos_de_janelas
from .dominio.validador_rota import TEMPO_SERVICO_MAXIMO, TEMPO_SERVICO_MINIMO
from .formatar import _coordenada, _dias

# O que a rota precisa de cada loja (`rotas_bd.lojas_da_rota`, T3.17): a
# secção e o aviso (`dias_fechada`), os links (`lat`/`lng`), a loja da API e a
# assinatura do cálculo (`janelas`). Nunca a morada, as notas nem a pessoa de
# contacto. O `id` é só para juntar à paragem (`loja_id`) e não sai na API.
PROJECAO_LOJA_ROTA = {"_id": 0, "id": 1, "nome": 1, "fase": 1, "lat": 1, "lng": 1, "telefone": 1, "janelas": 1, "dias_fechada": 1}

# A loja dentro de cada paragem da API (plano F3 §4), pela ordem.
CAMPOS_LOJA_API = ("nome", "fase", "lat", "lng", "telefone", *janelas.CAMPOS, "dias_fechada")

# O cálculo na API: o da base sem a `assinatura` (que é só para o `atual`).
CAMPOS_CALCULO_API = ("atual", "distancia_m", "duracao_s", "regresso_previsto", "depois_do_limite", "geometria", "calculado_em")

ESTADO_INICIAL = "rascunho"
VERSAO_INICIAL = 1


def documento_rota(data: date, membro_id, agora, definicoes) -> dict:
    """A rota nova como fica gravada em `crm_rotas`, pela ordem do plano F3 §3.

    `data` é o dia (`date`; outra coisa é `TypeError`), `membro_id` o
    `user_id` de quem a criou, `agora` uma datetime com fuso (o
    `relogio.agora()` do pedido) e `definicoes` as em vigor
    (`definicoes.em_vigor`), de onde vêm as horas de saída e de regresso. O
    `id` é um uuid4 novo; `inicio`/`fim` a `None` são a fábrica.
    """
    _exigir_dia(data, "data")
    return {
        "id": str(uuid.uuid4()),
        "data": texto_data(data),
        "estado": ESTADO_INICIAL,
        "versao": VERSAO_INICIAL,
        "hora_saida": definicoes["rota_hora_saida"],
        "hora_regresso_limite": definicoes["rota_hora_regresso"],
        "inicio": None,
        "fim": None,
        "evitar_portagens": False,
        "paragens": [],
        "calculo": None,
        "criado_em": relogio.instante(agora),
        "criado_por": membro_id,
        "atualizado_em": relogio.carimbo(agora),
        "atualizado_por": membro_id,
    }


def documento_paragem(loja, motivo, servico_min, ordem, membro_id, agora) -> dict:
    """A paragem nova de uma rota (o `$push` em `paragens`), pela ordem do
    plano F3 §3, com os campos do terreno iniciais (`pendente`/null/null).

    Da `loja` lê só o `id`. O `motivo` é um dos `rotas.MOTIVOS`, o
    `servico_min` um inteiro de 1 a 240 e a `ordem` um inteiro ≥ 0 (nunca um
    bool); o resto é erro de programação (`ValueError`): o validador já
    recusou com 422 o que vinha do pedido.
    """
    loja_id = loja["id"]
    if not isinstance(loja_id, str) or not loja_id:
        raise ValueError(f"O id da loja tem de ser texto: {loja_id!r}")
    if not isinstance(motivo, str) or motivo not in rotas.MOTIVOS:
        raise ValueError(f"Motivo desconhecido: {motivo!r}")
    if not e_inteiro_json(servico_min) or not TEMPO_SERVICO_MINIMO <= servico_min <= TEMPO_SERVICO_MAXIMO:
        raise ValueError(f"Tempo de serviço inválido: {servico_min!r}")
    if not e_inteiro_json(ordem) or ordem < 0:
        raise ValueError(f"Ordem de paragem inválida: {ordem!r}")
    return {
        "id": str(uuid.uuid4()),
        "loja_id": loja_id,
        "ordem": ordem,
        "motivo": motivo,
        "tempo_servico_min": servico_min,
        "manter_fechada": False,
        "nao_cabe": False,
        "chegada_prevista": None,
        "espera_min": None,
        "fora_de_horario": False,
        "adicionada_em": relogio.instante(agora),
        "adicionada_por": membro_id,
        "removida_em": None,
        "estado": "pendente",
        "resultado": None,
        "concluida_em": None,
    }


def rota_api(rota, *, data: date, hoje: date, lojas, definicoes, calculo_disponivel: bool) -> dict:
    """A rota da API (`GET /rotas/{data}` e as respostas das escritas), pela
    ordem do plano F3 §4, a partir do documento da base (ou de `None`: a rota
    virtual de um dia sem rota, `existe: false`, com os valores por omissão).

    `data` e `hoje` são `date`; `lojas` é a lista dos documentos das lojas da
    rota pela `PROJECAO_LOJA_ROTA` (as que faltam são lojas apagadas:
    `seccao "sem_loja"`, `loja` e `links` a `None`); `definicoes` as em vigor
    (as horas da rota virtual e a fábrica); `calculo_disponivel` diz se há
    chave do openrouteservice (`bool`). A `data` tem de ser a da rota
    (`ValueError`, senão). Não mexe no que recebe.
    """
    _exigir_dia(data, "data")
    _exigir_dia(hoje, "hoje")
    if type(calculo_disponivel) is not bool:
        raise TypeError("calculo_disponivel tem de ser True ou False.")
    if not isinstance(lojas, (list, tuple)):
        raise TypeError("As lojas da rota vêm numa lista.")
    lojas_por_id = {loja["id"]: loja for loja in lojas}

    if rota is None:
        estado = None
        hora_saida = definicoes["rota_hora_saida"]
        hora_regresso_limite = definicoes["rota_hora_regresso"]
        evitar_portagens = False
        inicio = _ponto_api(None, definicoes)
        fim = _ponto_api(None, definicoes)
        seccoes = []
        calculo = None
    else:
        if rota["data"] != texto_data(data):
            raise ValueError(f"A rota é do dia {rota['data']!r}, não de {texto_data(data)!r}.")
        estado = rota["estado"]
        hora_saida = rota["hora_saida"]
        hora_regresso_limite = rota["hora_regresso_limite"]
        evitar_portagens = rota["evitar_portagens"]
        inicio = _ponto_api(rota["inicio"], definicoes)
        fim = _ponto_api(rota["fim"], definicoes)
        seccoes = rotas.seccoes(rota["paragens"], lojas_por_id, data)
        calculo = _calculo_api(rota, seccoes, inicio, fim)

    atual = calculo is not None and calculo["atual"]
    return {
        "id": None if rota is None else rota["id"],
        "data": texto_data(data),
        "existe": rota is not None,
        "estado": estado,
        "estado_efetivo": rotas.estado_efetivo(estado, data, hoje),
        "editavel": rotas.bloqueio_de_escrita(rota, data, hoje) is None,
        "versao": None if rota is None else rota["versao"],
        "hoje": texto_data(hoje),
        "hora_saida": hora_saida,
        "hora_regresso_limite": hora_regresso_limite,
        "evitar_portagens": evitar_portagens,
        "inicio": inicio,
        "fim": fim,
        "limite_paragens": rotas.LIMITE_PARAGENS,
        "calculo_disponivel": calculo_disponivel,
        "calculo": calculo,
        "paragens": [
            _paragem_api(paragem, loja, seccao, numero, atual, evitar_portagens)
            for paragem, loja, seccao, numero in seccoes
        ],
        "blocos_google": navegacao.blocos_google(
            [(numero, loja["lat"], loja["lng"]) for _, loja, seccao, numero in seccoes if seccao == "rota"],
            evitar_portagens,
        ),
    }


def resumo_rota_api(rota, hoje: date) -> dict:
    """A linha de uma rota no `GET /rotas`: `{id, data, estado, estado_efetivo,
    paragens}`, com `paragens` a contar só as ativas. Basta o documento sem o
    `calculo` (a projeção do `rotas_entre`). Uma `data` que não é um dia
    `AAAA-MM-DD` é `ValueError`; um `hoje` que não é `date`, `TypeError`."""
    _exigir_dia(hoje, "hoje")
    data = ler_data(rota["data"])
    if data is None:
        raise ValueError(f"A data da rota na base não é um dia AAAA-MM-DD: {rota['data']!r}")
    return {
        "id": rota["id"],
        "data": rota["data"],
        "estado": rota["estado"],
        "estado_efetivo": rotas.estado_efetivo(rota["estado"], data, hoje),
        "paragens": len(rotas.ativas(rota["paragens"])),
    }


def loja_rota_api(loja) -> dict:
    """A loja dentro de uma paragem da API, pela ordem de `CAMPOS_LOJA_API`:
    só o que a `PROJECAO_LOJA_ROTA` traz, com as janelas planas
    (`campos_de_janelas`), as coordenadas em `float` e os dias pela ordem da
    semana sem repetidos (como o `loja_api` das lojas)."""
    return {
        "nome": loja["nome"],
        "fase": loja["fase"],
        "lat": _coordenada(loja["lat"], -90.0, 90.0),
        "lng": _coordenada(loja["lng"], -180.0, 180.0),
        "telefone": loja["telefone"],
        **campos_de_janelas(loja["janelas"]),
        "dias_fechada": _dias(loja["dias_fechada"]),
    }


def _paragem_api(paragem, loja, seccao, numero, calculo_atual: bool, evitar_portagens) -> dict:
    """Uma paragem da API (plano F3 §4), a partir da paragem da base e da
    linha de `rotas.seccoes`. Sem loja (apagada): `links` e `loja` a `None`."""
    loja_api = None if loja is None else loja_rota_api(loja)
    return {
        "id": paragem["id"],
        "loja_id": paragem["loja_id"],
        "numero": numero,
        "seccao": seccao,
        "ordem": paragem["ordem"],
        "motivo": paragem["motivo"],
        "tempo_servico_min": paragem["tempo_servico_min"],
        "manter_fechada": paragem["manter_fechada"],
        "nao_cabe": paragem["nao_cabe"],
        "chegada_prevista": paragem["chegada_prevista"],
        "espera_min": paragem["espera_min"],
        "fora_de_horario": paragem["fora_de_horario"],
        "aviso": rotas.aviso(paragem, seccao, calculo_atual),
        "estado": paragem["estado"],
        "resultado": paragem["resultado"],
        "links": None
        if loja_api is None
        else {
            "google": navegacao.link_google(loja_api["lat"], loja_api["lng"], evitar_portagens),
            "waze": navegacao.link_waze(loja_api["lat"], loja_api["lng"], evitar_portagens),
        },
        "loja": loja_api,
    }


def _ponto_api(ponto, definicoes) -> dict:
    """O início ou o fim resolvido: `{lat, lng, fabrica}`. `None` na base é a
    fábrica das definições em vigor (`fabrica: True`)."""
    if ponto is None:
        return {"lat": definicoes["fabrica_lat"], "lng": definicoes["fabrica_lng"], "fabrica": True}
    return {"lat": ponto["lat"], "lng": ponto["lng"], "fabrica": False}


def _calculo_api(rota, seccoes, inicio, fim):
    """O `calculo` da API: o da base sem a assinatura e com `atual`, que diz
    se a assinatura gravada é a da entrada de agora — a rota como está, só
    com as paragens da secção "rota" (as que o Directions leva, T3.21) pela
    ordem, e o início e o fim já resolvidos. `None` sem cálculo na base."""
    calculo = rota["calculo"]
    if calculo is None:
        return None
    incluidas = [(paragem, loja) for paragem, loja, seccao, _ in seccoes if seccao == "rota"]
    entrada = entrada_calculo(rota, incluidas, (inicio["lat"], inicio["lng"]), (fim["lat"], fim["lng"]))
    return {
        "atual": calculo["assinatura"] == assinatura(entrada),
        **{campo: calculo[campo] for campo in CAMPOS_CALCULO_API[1:]},
    }


def _exigir_dia(valor, nome: str) -> None:
    """Os dias são `date` (nunca texto nem `datetime`, que é uma subclasse:
    o instante UTC daria o dia errado)."""
    if type(valor) is not date:
        raise TypeError(f"{nome} tem de ser um datetime.date, não {type(valor).__name__}.")
