"""O pedido ao otimizador (o VROOM do openrouteservice) e a leitura da resposta (F3).

Plano F3 §1 ("Pedido VROOM") e §0 regra 12. **Ao openrouteservice só vão
coordenadas, segundos, prioridades, índices numéricos 1..n e a constante
`"driving-car"`**, nunca nomes, telefones, moradas ou uuids (risco R4):

- `paragem_calculo` tira da paragem e da loja só o que o cálculo precisa
  (`ParagemCalculo`: o id fica do lado de cá, nunca vai no pedido);
- `pedido_otimizacao` monta o corpo só a partir de números. Um veículo
  `driving-car` com `start`/`end` = início/fim e `time_window` = [saída,
  regresso limite]; por cada paragem um *job* `{id: 1..n, location: [lng,
  lat], service, priority, time_windows}`. As janelas são as do início do
  serviço (`horas.janelas_vroom`, `[a, b − s]`); uma paragem sem nenhuma
  janela onde o serviço caiba é **impossível** e não vai (fica para a secção
  "Não cabe no horário"). Prioridades pelo `rotas.prioridade` (entrega 100,
  as outras 1).
- `interpretar_otimizacao` lê a resposta com um parser estrito (risco R3): o
  que não bater certo é `RespostaInvalida`, que as rotas tornam em 503 sem
  mudar nada (T3.22). O motivo é sempre um texto fixo, sem nada da resposta
  (vai para os registos).

As coordenadas vão como `[lng, lat]` (GeoJSON), arredondadas às 6 casas com
`numeros.arredondar` (meio-para-longe-do-zero, como se guardam).
"""
from typing import NamedTuple, Optional

from . import horas, rotas
from .numeros import arredondar, e_inteiro_json, e_numero_json
from .validador_rota import TEMPO_SERVICO_MAXIMO, TEMPO_SERVICO_MINIMO

PERFIL = "driving-car"

# A carrinha: um só veículo, com o id 1.
VEICULO = 1

CASAS_COORDENADAS = 6

SEGUNDOS_POR_DIA = 86400

# Os passos de uma rota do VROOM que não são paragens: ignoram-se.
_PASSOS_DOS_EXTREMOS = ("start", "end")


class RespostaInvalida(Exception):
    """A resposta do openrouteservice não tem a forma esperada (→ 503, nada muda).

    `motivo` é um texto fixo deste módulo: nunca leva valores da resposta
    (coordenadas, textos), porque vai para os registos.
    """

    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


class ParagemCalculo(NamedTuple):
    """O que o cálculo precisa de uma paragem: `id` da paragem (só do lado de
    cá), as coordenadas da loja, o serviço em segundos, as janelas em segundos
    (`None` = sem restrição) e o motivo (para a prioridade)."""

    id: str
    lat: float
    lng: float
    servico_s: int
    janelas_s: Optional[list]
    motivo: str


class PedidoOtimizacao(NamedTuple):
    """O corpo do POST `/optimization` (`None` sem *jobs*: não se chama o
    ORS), o mapa `{id do job: id da paragem}` e os ids das paragens
    impossíveis (pela ordem recebida), que não foram enviadas."""

    corpo: Optional[dict]
    por_job: dict
    impossiveis: list


def paragem_calculo(paragem, loja) -> ParagemCalculo:
    """A paragem de cálculo, lendo só `id`, `tempo_servico_min` e `motivo` da
    paragem e `lat`, `lng` e `janelas` da loja.

    O que não passou pelo validador (um tempo fora de 1..240, um motivo
    desconhecido, uma coordenada que não é número, janelas estragadas) é um
    erro de programação: `ValueError`.
    """
    id_ = paragem["id"]
    if not isinstance(id_, str):
        raise ValueError("O id da paragem tem de ser texto.")
    tempo = paragem["tempo_servico_min"]
    if not e_inteiro_json(tempo) or not TEMPO_SERVICO_MINIMO <= tempo <= TEMPO_SERVICO_MAXIMO:
        raise ValueError(f"Tempo de serviço inválido: {tempo!r}")
    motivo = paragem["motivo"]
    if not isinstance(motivo, str) or motivo not in rotas.MOTIVOS:
        raise ValueError(f"Motivo desconhecido: {motivo!r}")
    lat = _numero(loja["lat"], "latitude")
    lng = _numero(loja["lng"], "longitude")
    return ParagemCalculo(id_, lat, lng, tempo * 60, horas.janelas_em_segundos(loja["janelas"]), motivo)


def pedido_otimizacao(paragens, inicio, fim, saida_s, limite_s) -> PedidoOtimizacao:
    """O pedido ao VROOM para as `paragens` (`ParagemCalculo`), pela ordem recebida.

    `inicio` e `fim` são pares `(lat, lng)`; `saida_s` e `limite_s` segundos
    desde a meia-noite (`horas.segundos`), com a saída antes do limite. Os ids
    dos *jobs* são 1..n pela ordem das paragens enviadas (as impossíveis
    saltam-se). Sem nenhum *job*, `corpo` é `None`. Devolve estruturas novas.
    """
    for valor in (saida_s, limite_s):
        if not e_inteiro_json(valor) or not 0 <= valor < SEGUNDOS_POR_DIA:
            raise ValueError(f"Hora do veículo inválida em segundos: {valor!r}")
    if saida_s >= limite_s:
        raise ValueError("A saída tem de ser antes do regresso limite.")
    inicio_ = _ponto(inicio)
    fim_ = _ponto(fim)

    jobs = []
    por_job = {}
    impossiveis = []
    vistos = set()
    for paragem in paragens:
        if not isinstance(paragem, ParagemCalculo):
            raise TypeError("pedido_otimizacao recebe ParagemCalculo (paragem_calculo).")
        if paragem.id in vistos:
            raise ValueError(f"Paragem repetida no cálculo: {paragem.id!r}")
        vistos.add(paragem.id)

        janelas = horas.janelas_vroom(paragem.janelas_s, paragem.servico_s)
        if janelas == []:
            impossiveis.append(paragem.id)
            continue
        numero = len(jobs) + 1
        job = {
            "id": numero,
            "location": _ponto((paragem.lat, paragem.lng)),
            "service": paragem.servico_s,
            "priority": rotas.prioridade(paragem.motivo),
        }
        if janelas is not None:
            job["time_windows"] = janelas
        jobs.append(job)
        por_job[numero] = paragem.id

    if not jobs:
        return PedidoOtimizacao(None, {}, impossiveis)

    veiculo = {"id": VEICULO, "profile": PERFIL, "start": inicio_, "end": fim_, "time_window": [saida_s, limite_s]}
    return PedidoOtimizacao({"jobs": jobs, "vehicles": [veiculo]}, por_job, impossiveis)


def interpretar_otimizacao(resposta, por_job) -> tuple:
    """`(ordem, nao_atribuidas)`: os ids das paragens pela ordem dos passos da
    rota e os das não atribuídas (pela ordem do pedido).

    Estrito: `RespostaInvalida` quando a resposta não é um objeto; `code` não
    é o inteiro 0; `routes` não é uma lista ou tem mais de uma rota; a rota não
    é do veículo 1 ou os `steps` não são uma lista; um passo não é um objeto
    ou é de um tipo que não é `start`, `end` nem `job`; um *job* sem id, com
    um id que não é inteiro, desconhecido ou repetido; o `id` e o `job` de um
    passo diferentes; `unassigned` não é uma lista de *jobs*; ou os
    atribuídos ∪ não atribuídos não são exatamente os enviados.

    `routes: []` (nenhum *job* cabe) é válido, com todos em `unassigned`. Nos
    passos lê-se o `id` e só sem ele a chave antiga `job`.
    """
    if not isinstance(resposta, dict):
        raise RespostaInvalida("a resposta da otimização não é um objeto")
    codigo = resposta.get("code")
    if type(codigo) is not int or codigo != 0:
        raise RespostaInvalida("a otimização não respondeu com o código 0")

    rotas_ = resposta.get("routes")
    if not isinstance(rotas_, list):
        raise RespostaInvalida("a otimização não trouxe a lista das rotas")
    if len(rotas_) > 1:
        raise RespostaInvalida("a otimização devolveu mais de uma rota")

    atribuidos = []
    for rota in rotas_:
        atribuidos.extend(_jobs_da_rota(rota))

    lista = resposta.get("unassigned")
    if not isinstance(lista, list):
        raise RespostaInvalida("a otimização não trouxe a lista dos não atribuídos")
    nao_atribuidos = [_job_nao_atribuido(item) for item in lista]

    todos = atribuidos + nao_atribuidos
    if any(numero not in por_job for numero in todos):
        raise RespostaInvalida("a otimização falou de um job que não foi enviado")
    if len(set(todos)) != len(todos):
        raise RespostaInvalida("a otimização repetiu um job")
    if set(todos) != set(por_job):
        raise RespostaInvalida("a otimização deixou de fora um job enviado")

    return [por_job[numero] for numero in atribuidos], [por_job[numero] for numero in sorted(nao_atribuidos)]


def _jobs_da_rota(rota) -> list:
    """Os números dos *jobs* pela ordem dos passos da (única) rota."""
    if not isinstance(rota, dict):
        raise RespostaInvalida("a rota da otimização não é um objeto")
    veiculo = rota.get("vehicle")
    if type(veiculo) is not int or veiculo != VEICULO:
        raise RespostaInvalida("a rota da otimização não é do veículo 1")
    passos = rota.get("steps")
    if not isinstance(passos, list):
        raise RespostaInvalida("a rota da otimização não trouxe a lista dos passos")

    numeros = []
    for passo in passos:
        if not isinstance(passo, dict):
            raise RespostaInvalida("um passo da rota não é um objeto")
        tipo = passo.get("type")
        if isinstance(tipo, str) and tipo in _PASSOS_DOS_EXTREMOS:
            continue
        if not (isinstance(tipo, str) and tipo == "job"):
            raise RespostaInvalida("um passo da rota é de um tipo desconhecido")
        numeros.append(_numero_do_passo(passo))
    return numeros


def _numero_do_passo(passo) -> int:
    """O `id` do passo; só sem ele a chave antiga `job`. Os dois diferentes são inválidos."""
    if "id" in passo:
        numero = _inteiro(passo["id"])
        if "job" in passo and _inteiro(passo["job"]) != numero:
            raise RespostaInvalida("o id e o job de um passo não batem certo")
        return numero
    if "job" in passo:
        return _inteiro(passo["job"])
    raise RespostaInvalida("um passo da rota não diz que job é")


def _job_nao_atribuido(item) -> int:
    if not isinstance(item, dict) or "id" not in item:
        raise RespostaInvalida("um não atribuído não é um job")
    if "type" in item and not (isinstance(item["type"], str) and item["type"] == "job"):
        raise RespostaInvalida("um não atribuído não é um job")
    return _inteiro(item["id"])


def _inteiro(valor) -> int:
    # `True == 1` e `1.0 == 1` (com o mesmo hash): sem ver o tipo, apanhavam um job do `por_job`.
    if type(valor) is not int:
        raise RespostaInvalida("um job da otimização tem um id que não é um número inteiro")
    return valor


def _numero(valor, nome) -> float:
    if not e_numero_json(valor):
        raise ValueError(f"A {nome} tem de ser um número.")
    return float(valor)


def _ponto(par) -> list:
    """`(lat, lng)` → `[lng, lat]` às 6 casas, meio-para-longe-do-zero."""
    if not isinstance(par, (tuple, list)) or len(par) != 2:
        raise ValueError("Um ponto é um par (lat, lng).")
    lat, lng = par
    return [
        arredondar(_numero(lng, "longitude"), CASAS_COORDENADAS),
        arredondar(_numero(lat, "latitude"), CASAS_COORDENADAS),
    ]
