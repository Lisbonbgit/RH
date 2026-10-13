"""Simulador local do openrouteservice, para a pré-visualização (plano F3, T3.13). **Só local.**

    cd backend && .venv/bin/python ors_simulado_local.py [--porta 8013] [--host 127.0.0.1]

Serve o planeador na pré-visualização local (T3.43) sem chave verdadeira nem
rede: o `backend/.env.local` aponta o `CRM_ORS_URL` para aqui
(`http://127.0.0.1:8013`) com a `CRM_ORS_CHAVE=simulador-local`. Nunca entra no
portal (nem o `server.py` nem o pacote `crm` o importam) e nunca vai à rede.

- **Só escuta em 127.0.0.1** (§0, regra 12): o `--host` só aceita
  `127.0.0.1`, `localhost` e `::1`; o resto sai com "Recusado: o simulador só
  escuta em 127.0.0.1." antes de arrancar.
- **As rotas:** `GET /saude` → `{"estado": "ok", "simulador": true}`;
  `POST /optimization` (o VROOM) e `POST /v2/directions/driving-car/json`. As
  duas exigem um `Authorization` não vazio (sem ele, 401), para provar que o
  cliente o envia, e recusam qualquer parâmetro no URL (400): a chave vai só no
  cabeçalho. O simulador nunca devolve nem regista o valor do cabeçalho.
- **As contas** (determinísticas, sem relógio nem acaso): distância =
  haversine (`geo.distancia_metros`) × 1,3; 11 m/s (~40 km/h); a evitar
  portagens (`options.avoid_features` com `"tollways"`), a duração × 1,15.
- **VROOM:** um vizinho mais próximo guloso. A carrinha sai do `start` na
  abertura da sua `time_window` e, a cada passo, escolhe entre os *jobs* que
  ainda cabem o de maior prioridade e, entre esses, o mais perto de onde está
  (empate: a ordem do pedido). Um *job* cabe se a chegada não passar do fim de
  nenhuma das suas janelas (a do início do serviço, como no VROOM: espera pela
  abertura, também pela 2.ª) e se, depois do serviço, ainda voltar ao `end`
  até ao fim da janela do veículo. O que nunca cabe fica em `unassigned`
  (pela ordem do pedido); sem nenhum atribuído, `routes: []`. Os tempos de
  viagem do VROOM são segundos inteiros (meio-para-longe-do-zero).
- **Directions:** um troço por cada par de pontos seguidos, em linha reta, com
  a distância e a duração a 1 casa decimal; um troço de comprimento zero vem
  **sem** `distance` nem `duration` (e um resumo a zero sem elas), como no ORS
  (correção "T3.7 (+ T3.13, T3.21)"). Sem `instructions` não há `segments`,
  como no ORS (risco R2); sem `geometry` não há linha. A linha passa pelos
  pontos pedidos, pela ordem, codificada pelo `polilinha.codificar` do domínio
  (precisão 5; correção "T3.7 / T3.9 / T3.13 / T3.21"). O simulador não sabe
  onde há estradas: nunca dá o erro 2010.
- **Pedidos inválidos:** 400 na forma de cada serviço — o VROOM `{"code": 2,
  "error": …}` e o Directions `{"error": {"code": 2000/2001/2003/2004,
  "message": …}}` —, com mensagens fixas, sem valores do pedido. Só aceita a
  forma que o `vroom.pedido_otimizacao` e o `directions.pedido_direcoes`
  mandam: um veículo `driving-car` com `start` e `end`, até 50 pontos no
  Directions, `units` `"m"` e sem elevação.
- **Marcado como simulador** (risco R14): `metadata.simulador: true` e a
  atribuição "simulador local …" nas respostas; as linhas retas também se veem
  no mapa.
- **Os registos** só têm o método, o caminho e o estado de cada pedido: o
  uvicorn arranca sem o registo de acesso, que escrevia o URL com os
  parâmetros (uma chave posta por engano no URL ficava no registo).

Os testes (`tests/crm/test_ors_simulado_local.py`) usam o `TestClient`, dentro
do processo, e nunca arrancam o servidor.
"""
import argparse
import logging
import math
from typing import NamedTuple, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from crm.dominio import directions, geo, polilinha, vroom
from crm.dominio.numeros import arredondar, e_inteiro_json, e_numero_json
from crm.servicos import geoapify

PORTA_POR_OMISSAO = 8013
ANFITRIAO_POR_OMISSAO = "127.0.0.1"
ANFITRIOES_LOCAIS = ("127.0.0.1", "localhost", "::1")
MENSAGEM_ANFITRIAO = "Recusado: o simulador só escuta em 127.0.0.1."

CAMINHO_OTIMIZACAO = "/optimization"
CAMINHO_DIRECOES = f"/v2/directions/{vroom.PERFIL}/json"

# O modelo: a estrada é 30 % mais comprida do que a linha reta; 11 m/s ≈ 40 km/h.
FATOR_ESTRADA = 1.3
VELOCIDADE_M_S = 11
FATOR_PORTAGENS = 1.15
PORTAGENS = directions.PORTAGENS

CASAS_DIRECOES = 1
PRIORIDADE_MAXIMA = 100
LATITUDE_MAXIMA = 90
LONGITUDE_MAXIMA = 180

# Os códigos de erro do ORS: o VROOM dá 2 a um pedido mal formado; o Directions
# 2000 (JSON), 2001 (parâmetro em falta), 2003 (valor inválido) e 2004 (acima do limite).
CODIGO_ENTRADA_VROOM = 2
CODIGO_JSON = 2000
CODIGO_EM_FALTA = 2001
CODIGO_VALOR = 2003
CODIGO_LIMITE = 2004

# Os passos de um troço do Directions: partida (11) e chegada (10), como no ORS.
TIPO_PARTIDA = 11
TIPO_CHEGADA = 10

ATRIBUICAO = "simulador local do openrouteservice (linhas retas) — não é o openrouteservice"

# O registo de cada pedido (método, caminho e estado, nunca o URL inteiro nem os cabeçalhos).
# É o do uvicorn, que o arranque deixa em INFO; o registo de acesso do uvicorn fica desligado.
_registo = logging.getLogger("uvicorn.error")

MENSAGEM_SEM_CHAVE = "Falta o cabeçalho Authorization (simulador local)."
MENSAGEM_URL = "A chave e os parâmetros não vão no URL: o simulador só aceita o corpo JSON e o cabeçalho Authorization."
MENSAGEM_JSON = "O pedido não é um objeto JSON."


class PedidoInvalido(Exception):
    """Um pedido que o ORS recusaria (→ 400). A `mensagem` é um texto fixo deste
    módulo, nunca com valores do pedido."""

    def __init__(self, mensagem, codigo=CODIGO_VALOR):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


# --- O modelo --------------------------------------------------------------------------------


def distancia_m(origem, destino) -> float:
    """A distância pela "estrada" simulada, em metros, entre dois pontos
    `[lng, lat]` (a ordem do ORS): a haversine × 1,3."""
    return geo.distancia_metros(origem[1], origem[0], destino[1], destino[0]) * FATOR_ESTRADA


def duracao_s(distancia, evitar_portagens=False) -> float:
    """Os segundos para andar `distancia` metros a 11 m/s; × 1,15 a evitar portagens."""
    duracao = distancia / VELOCIDADE_M_S
    return duracao * FATOR_PORTAGENS if evitar_portagens else duracao


def _viagem_s(origem, destino) -> int:
    """Os segundos inteiros de uma viagem no VROOM simulado."""
    return int(arredondar(duracao_s(distancia_m(origem, destino))))


# --- O VROOM ---------------------------------------------------------------------------------


class _Job(NamedTuple):
    id: int
    local: list
    servico: int
    prioridade: int
    janelas: Optional[list]


class _Veiculo(NamedTuple):
    id: int
    inicio: list
    fim: list
    saida: int
    limite: Optional[int]


def otimizar(corpo) -> dict:
    """A resposta do VROOM simulado para o corpo de um `POST /optimization`
    (já lido do JSON). `PedidoInvalido` se o ORS o recusasse."""
    jobs, veiculo = _ler_otimizacao(corpo)

    local, tempo = veiculo.inicio, veiculo.saida
    viagem_total = servico_total = espera_total = prioridade_total = 0
    passos = [_passo("start", veiculo.inicio, tempo, 0)]
    restantes = list(jobs)

    while True:
        escolha = None
        for indice, job in enumerate(restantes):
            chegada = tempo + _viagem_s(local, job.local)
            inicio = _inicio_do_servico(chegada, job.janelas)
            if inicio is None:
                continue
            if veiculo.limite is not None and inicio + job.servico + _viagem_s(job.local, veiculo.fim) > veiculo.limite:
                continue
            chave = (-job.prioridade, distancia_m(local, job.local), indice)
            if escolha is None or chave < escolha[0]:
                escolha = (chave, indice, chegada, inicio)
        if escolha is None:
            break

        _, indice, chegada, inicio = escolha
        job = restantes.pop(indice)
        viagem_total += chegada - tempo
        servico_total += job.servico
        espera_total += inicio - chegada
        prioridade_total += job.prioridade
        passos.append(_passo("job", job.local, chegada, viagem_total, job.servico, inicio - chegada, job.id))
        local, tempo = job.local, inicio + job.servico

    nao_atribuidos = [{"id": job.id, "type": "job", "location": list(job.local)} for job in restantes]
    rotas = []
    if len(passos) > 1:
        regresso = _viagem_s(local, veiculo.fim)
        viagem_total += regresso
        passos.append(_passo("end", veiculo.fim, tempo + regresso, viagem_total))
        totais = _totais(viagem_total, servico_total, espera_total, prioridade_total)
        rotas.append({"vehicle": veiculo.id, **totais, "steps": passos, "violations": []})
    else:
        totais = _totais(0, 0, 0, 0)

    resumo = {
        "cost": totais["cost"],
        "routes": len(rotas),
        "unassigned": len(nao_atribuidos),
        **{chave: valor for chave, valor in totais.items() if chave != "cost"},
        "violations": [],
        "computing_times": {"loading": 0, "solving": 0, "routing": 0},
    }
    return {
        "code": 0,
        "summary": resumo,
        "unassigned": nao_atribuidos,
        "routes": rotas,
        "metadata": {"service": "optimization", "attribution": ATRIBUICAO, "simulador": True},
    }


def _inicio_do_servico(chegada, janelas):
    """O início do serviço mais cedo: à chegada, ou à abertura da 1.ª janela
    que ainda não fechou. `None` se todas já fecharam (sem janelas: à chegada)."""
    if janelas is None:
        return chegada
    possiveis = [max(chegada, abertura) for abertura, fecho in janelas if chegada <= fecho]
    return min(possiveis) if possiveis else None


def _passo(tipo, local, chegada, viagem, servico=0, espera=0, id_=None) -> dict:
    passo = {"type": tipo}
    if id_ is not None:
        passo.update({"id": id_, "job": id_})
    passo.update({
        "location": list(local),
        "setup": 0,
        "service": servico,
        "waiting_time": espera,
        "arrival": chegada,
        "duration": viagem,
        "violations": [],
    })
    return passo


def _totais(viagem, servico, espera, prioridade) -> dict:
    return {"cost": viagem, "setup": 0, "service": servico, "duration": viagem, "waiting_time": espera, "priority": prioridade}


def _ler_otimizacao(corpo):
    if not isinstance(corpo, dict):
        raise PedidoInvalido(MENSAGEM_JSON)

    lista = corpo.get("jobs")
    if not isinstance(lista, list) or not lista:
        raise PedidoInvalido("O pedido tem de trazer a lista dos jobs, com pelo menos um.")
    jobs = [_ler_job(job) for job in lista]
    if len({job.id for job in jobs}) != len(jobs):
        raise PedidoInvalido("Há jobs com o mesmo id.")

    veiculos = corpo.get("vehicles")
    if not isinstance(veiculos, list) or len(veiculos) != 1:
        raise PedidoInvalido("O simulador só tem uma carrinha: a lista dos vehicles leva exatamente um.")
    return jobs, _ler_veiculo(veiculos[0])


def _ler_job(job) -> _Job:
    if not isinstance(job, dict):
        raise PedidoInvalido("Um job tem de ser um objeto.")
    if not e_inteiro_json(job.get("id")):
        raise PedidoInvalido("O id de um job tem de ser um número inteiro.")
    if "location" not in job:
        raise PedidoInvalido("Um job tem de trazer a location.")
    servico = job.get("service", 0)
    if not e_inteiro_json(servico) or servico < 0:
        raise PedidoInvalido("O service de um job tem de ser um número inteiro de segundos ≥ 0.")
    prioridade = job.get("priority", 0)
    if not e_inteiro_json(prioridade) or not 0 <= prioridade <= PRIORIDADE_MAXIMA:
        raise PedidoInvalido("A priority de um job tem de ser um número inteiro de 0 a 100.")
    janelas = None
    if "time_windows" in job:
        janelas = job["time_windows"]
        if not isinstance(janelas, list) or not janelas:
            raise PedidoInvalido("As time_windows de um job têm de ser uma lista com pelo menos uma janela.")
        janelas = [_janela(janela) for janela in janelas]
    return _Job(job["id"], _ponto(job["location"]), servico, prioridade, janelas)


def _ler_veiculo(veiculo) -> _Veiculo:
    if not isinstance(veiculo, dict):
        raise PedidoInvalido("Um vehicle tem de ser um objeto.")
    if not e_inteiro_json(veiculo.get("id")):
        raise PedidoInvalido("O id do vehicle tem de ser um número inteiro.")
    perfil = veiculo.get("profile")
    if not (isinstance(perfil, str) and perfil == vroom.PERFIL):
        raise PedidoInvalido("O simulador só conhece o perfil driving-car.")
    if "start" not in veiculo or "end" not in veiculo:
        raise PedidoInvalido("O simulador precisa do start e do end do vehicle.")
    saida, limite = 0, None
    if "time_window" in veiculo:
        saida, limite = _janela(veiculo["time_window"])
    return _Veiculo(veiculo["id"], _ponto(veiculo["start"]), _ponto(veiculo["end"]), saida, limite)


def _janela(janela) -> tuple:
    if not isinstance(janela, list) or len(janela) != 2 or not all(e_inteiro_json(valor) for valor in janela):
        raise PedidoInvalido("Uma janela é um par de números inteiros de segundos.")
    abertura, fecho = janela
    if not 0 <= abertura <= fecho:
        raise PedidoInvalido("Uma janela tem de abrir antes de fechar, em segundos ≥ 0.")
    return abertura, fecho


# --- O Directions ----------------------------------------------------------------------------


def direcoes(corpo) -> dict:
    """A resposta do Directions simulado para o corpo de um `POST
    /v2/directions/driving-car/json` (já lido do JSON). `PedidoInvalido`
    (com o código do ORS) se o ORS o recusasse."""
    pontos, com_trocos, com_linha, evitar_portagens = _ler_direcoes(corpo)

    distancias = [distancia_m(origem, destino) for origem, destino in zip(pontos, pontos[1:])]
    duracoes = [duracao_s(distancia, evitar_portagens) for distancia in distancias]
    caixa = [
        min(ponto[0] for ponto in pontos),
        min(ponto[1] for ponto in pontos),
        max(ponto[0] for ponto in pontos),
        max(ponto[1] for ponto in pontos),
    ]

    rota = {"summary": _medidas(math.fsum(distancias), math.fsum(duracoes))}
    if com_trocos:
        rota["segments"] = [_troco(indice, distancia, duracao) for indice, (distancia, duracao) in enumerate(zip(distancias, duracoes))]
    rota["bbox"] = caixa
    if com_linha:
        rota["geometry"] = polilinha.codificar([(lat, lng) for lng, lat in pontos])
    rota["way_points"] = list(range(len(pontos)))

    return {
        "bbox": list(caixa),
        "routes": [rota],
        "metadata": {"attribution": ATRIBUICAO, "service": "routing", "simulador": True},
    }


def _medidas(distancia, duracao) -> dict:
    """A distância e a duração a 1 casa; a que dá 0 fica de fora, como no ORS."""
    medidas = {"distance": arredondar(distancia, CASAS_DIRECOES), "duration": arredondar(duracao, CASAS_DIRECOES)}
    return {chave: valor for chave, valor in medidas.items() if valor != 0}


def _troco(indice, distancia, duracao) -> dict:
    medidas = _medidas(distancia, duracao)
    partida = {
        **medidas,
        "type": TIPO_PARTIDA,
        "instruction": "Siga em linha reta (simulador local)",
        "name": "-",
        "way_points": [indice, indice + 1],
    }
    chegada = {
        "type": TIPO_CHEGADA,
        "instruction": "Chegou ao destino (simulador local)",
        "name": "-",
        "way_points": [indice + 1, indice + 1],
    }
    return {**medidas, "steps": [partida, chegada]}


def _ler_direcoes(corpo):
    if not isinstance(corpo, dict):
        raise PedidoInvalido(MENSAGEM_JSON, CODIGO_JSON)
    if "coordinates" not in corpo:
        raise PedidoInvalido("Falta o parâmetro coordinates.", CODIGO_EM_FALTA)

    coordenadas = corpo["coordinates"]
    if not isinstance(coordenadas, list) or len(coordenadas) < directions.MINIMO_PONTOS:
        raise PedidoInvalido("As coordinates têm de ser uma lista com pelo menos 2 pontos.")
    if len(coordenadas) > directions.MAXIMO_PONTOS:
        raise PedidoInvalido("O Directions aceita no máximo 50 pontos.", CODIGO_LIMITE)
    pontos = [_ponto(ponto, CODIGO_VALOR) for ponto in coordenadas]

    com_trocos = _booleano(corpo, "instructions", True)
    com_linha = _booleano(corpo, "geometry", True)
    if _booleano(corpo, "elevation", False):
        raise PedidoInvalido("O simulador não dá a elevação (a polyline mudava de forma).")
    if "units" in corpo and not (isinstance(corpo["units"], str) and corpo["units"] == directions.UNIDADES):
        raise PedidoInvalido("O simulador só conta em metros (units \"m\").")

    evitar_portagens = False
    if "options" in corpo:
        opcoes = corpo["options"]
        if not isinstance(opcoes, dict):
            raise PedidoInvalido("As options têm de ser um objeto.")
        evitar = opcoes.get("avoid_features", [])
        if not isinstance(evitar, list) or not all(isinstance(item, str) for item in evitar):
            raise PedidoInvalido("As avoid_features têm de ser uma lista de textos.")
        evitar_portagens = PORTAGENS in evitar
    return pontos, com_trocos, com_linha, evitar_portagens


def _booleano(corpo, chave, omissao) -> bool:
    if chave not in corpo:
        return omissao
    valor = corpo[chave]
    if type(valor) is not bool:
        raise PedidoInvalido(f"O parâmetro {chave} tem de ser true ou false.")
    return valor


def _ponto(valor, codigo=CODIGO_VALOR) -> list:
    """Um ponto `[lng, lat]` de dois números do JSON dentro do mundo (uma cópia)."""
    if (
        not isinstance(valor, list)
        or len(valor) != 2
        or not all(e_numero_json(numero) for numero in valor)
        or not -LONGITUDE_MAXIMA <= valor[0] <= LONGITUDE_MAXIMA
        or not -LATITUDE_MAXIMA <= valor[1] <= LATITUDE_MAXIMA
    ):
        raise PedidoInvalido("Um ponto é [longitude, latitude], em números dentro do mundo.", codigo)
    return list(valor)


# --- A app -----------------------------------------------------------------------------------

app = FastAPI(title="Simulador local do openrouteservice", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/saude")
def saude():
    """Diz que o simulador está a correr (e que é o simulador)."""
    return {"estado": "ok", "simulador": True}


@app.post(CAMINHO_OTIMIZACAO)
async def rota_otimizacao(request: Request):
    return await _responder(request, otimizar, _erro_vroom)


@app.post(CAMINHO_DIRECOES)
async def rota_direcoes(request: Request):
    return await _responder(request, direcoes, _erro_directions)


async def _responder(request, calcular, erro):
    resposta = await _resposta(request, calcular, erro)
    _registo.info("%s %s → %d", request.method, request.url.path, resposta.status_code)
    return resposta


async def _resposta(request, calcular, erro):
    """A ordem do ORS: primeiro a chave (401), depois o URL e o corpo (400)."""
    if not request.headers.get("authorization", "").strip():
        return JSONResponse({"error": MENSAGEM_SEM_CHAVE}, status_code=401)
    if request.url.query:
        return erro(PedidoInvalido(MENSAGEM_URL))
    try:
        corpo = geoapify.ler_json(await request.body())
    except ValueError:
        return erro(PedidoInvalido(MENSAGEM_JSON, CODIGO_JSON))
    try:
        resposta = calcular(corpo)
    except PedidoInvalido as falha:
        return erro(falha)
    return JSONResponse(resposta)


def _erro_vroom(falha) -> JSONResponse:
    return JSONResponse({"code": CODIGO_ENTRADA_VROOM, "error": falha.mensagem}, status_code=400)


def _erro_directions(falha) -> JSONResponse:
    return JSONResponse({"error": {"code": falha.codigo, "message": falha.mensagem}}, status_code=400)


# --- O comando -------------------------------------------------------------------------------


def principal(argv=None) -> None:
    """Arranca o simulador em primeiro plano (quem o chama põe-no em segundo plano)."""
    argumentos = _leitor().parse_args(argv)
    if argumentos.host not in ANFITRIOES_LOCAIS:
        raise SystemExit(MENSAGEM_ANFITRIAO)
    uvicorn.run(app, host=argumentos.host, port=argumentos.porta, log_level="info", access_log=False)


def _leitor():
    leitor = argparse.ArgumentParser(
        prog="ors_simulado_local.py",
        description="Simulador local do openrouteservice, só para a pré-visualização (linhas retas, sem chave verdadeira).",
    )
    leitor.add_argument("--porta", type=_porta, default=PORTA_POR_OMISSAO, help="porta (por omissão 8013)")
    leitor.add_argument("--host", default=ANFITRIAO_POR_OMISSAO, help="só 127.0.0.1, localhost ou ::1")
    return leitor


def _porta(texto) -> int:
    try:
        valor = int(texto)
    except ValueError:
        raise argparse.ArgumentTypeError("a porta é um número inteiro de 1 a 65535") from None
    if not 1 <= valor <= 65535:
        raise argparse.ArgumentTypeError("a porta é um número inteiro de 1 a 65535")
    return valor


if __name__ == "__main__":
    principal()
