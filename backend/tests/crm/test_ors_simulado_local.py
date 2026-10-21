"""O simulador local do openrouteservice (backend/ors_simulado_local.py), F3 / T3.13.

Plano F3 §1 ("Testes do ORS"), §0 regras 2 e 12 e riscos R2 e R14; correções
"T3.7 (+ T3.13, T3.21)" (um troço de comprimento zero vem sem `distance` nem
`duration`, como no ORS) e "T3.7 / T3.9 / T3.13 / T3.21" (a linha codifica-se
com o `polilinha.codificar` do domínio).

O simulador serve a pré-visualização local (T3.43) sem chave nem rede: uma app
FastAPI que só escuta em 127.0.0.1 e responde ao `/optimization` e ao
`/v2/directions/driving-car/json` com a forma do ORS, mas com contas simples e
determinísticas (sem relógio nem acaso):

- distância = haversine × 1,3; 11 m/s; a evitar portagens, a duração × 1,15;
- o VROOM é um vizinho mais próximo guloso, por prioridade e depois
  distância, que respeita as janelas (espera pela abertura), o serviço e o fim
  da janela do veículo, contando o regresso; o que nunca cabe fica em
  `unassigned`;
- o Directions dá os `segments` e a linha reta entre os pontos.

Tudo com o `TestClient` (dentro do processo). Os valores exatos escrevem-se à
mão neste ficheiro: pontos no mesmo meridiano, onde a haversine é `R × Δφ`
(`_metros`, `_segundos`), sem o `geo.distancia_metros`. Um fixture `autouse`
corta o transporte verdadeiro do httpx e os `socket` (DNS e ligações): nenhum
teste sai para a rede.
"""
import ast
import json
import logging
import math
import socket
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import crm
import gravar_respostas_ors as gravador
import ors_simulado_local as simulador
from crm.dominio import polilinha, vroom
from crm.dominio.directions import interpretar_direcoes, pedido_direcoes
from crm.dominio.vroom import RespostaInvalida, interpretar_otimizacao

BACKEND = Path(__file__).resolve().parents[2]
FICHEIRO = BACKEND / "ors_simulado_local.py"
FIXTURES = Path(__file__).parent / "fixtures" / "ors"

# Uma chave canária: o simulador só verifica que o cabeçalho vem, e nunca a devolve.
CHAVE = "canaria-do-simulador-0123456789abcdef"

OTIMIZACAO = "/optimization"
DIRECOES = "/v2/directions/driving-car/json"

MENSAGEM_ANFITRIAO = "Recusado: o simulador só escuta em 127.0.0.1."

# Pontos no meridiano −8 (Portugal continental): a distância é R × Δφ.
LNG = -8.0
RAIO_TERRA_M = 6_371_000

SAIDA = 28800  # 08:00
LIMITE = 68400  # 19:00


# --- A guarda contra a rede ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    """O `TestClient` corre a app dentro do processo; o transporte verdadeiro do
    httpx e os `socket` (ligações e DNS) levantam e ficam registados."""
    tentativas = []

    def _sem_rede(*_args, **_kwargs):
        tentativas.append("rede")
        raise AssertionError("o teste do simulador tentou a rede")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _sem_rede)
    monkeypatch.setattr(socket, "create_connection", _sem_rede)
    monkeypatch.setattr(socket, "getaddrinfo", _sem_rede)
    yield
    assert tentativas == []


@pytest.fixture
def cliente():
    return TestClient(simulador.app)


# --- Ajudas ----------------------------------------------------------------------------------


def _metros(dlat):
    """A distância simulada entre dois pontos do mesmo meridiano, `dlat` graus aparte."""
    return RAIO_TERRA_M * math.radians(dlat) * 1.3


def _segundos(dlat):
    """Os segundos inteiros do VROOM simulado (11 m/s, meio-para-cima)."""
    return math.floor(_metros(dlat) / 11 + 0.5)


def _ponto(lat):
    return [LNG, lat]


def _job(id_, lat, servico=0, prioridade=1, janelas=None):
    job = {"id": id_, "location": _ponto(lat), "service": servico, "priority": prioridade}
    if janelas is not None:
        job["time_windows"] = janelas
    return job


def _veiculo(saida=SAIDA, limite=LIMITE, inicio=38.0, fim=38.0, id_=1):
    return {"id": id_, "profile": "driving-car", "start": _ponto(inicio), "end": _ponto(fim), "time_window": [saida, limite]}


def _corpo(jobs, **veiculo):
    return {"jobs": jobs, "vehicles": [_veiculo(**veiculo)]}


def _post(cliente, caminho, corpo, chave=CHAVE):
    cabecalhos = {} if chave is None else {"Authorization": chave}
    if isinstance(corpo, bytes):
        return cliente.post(caminho, content=corpo, headers={**cabecalhos, "Content-Type": "application/json"})
    return cliente.post(caminho, json=corpo, headers=cabecalhos)


def _otimizar(cliente, corpo):
    resposta = _post(cliente, OTIMIZACAO, corpo)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _direcoes(cliente, corpo):
    resposta = _post(cliente, DIRECOES, corpo)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _ordem(resposta):
    assert len(resposta["routes"]) == 1
    return [passo["id"] for passo in resposta["routes"][0]["steps"] if passo["type"] == "job"]


def _nao_atribuidos(resposta):
    return [item["id"] for item in resposta["unassigned"]]


def _pedido_direcoes(lats, evitar=False, **extra):
    corpo = {"coordinates": [_ponto(lat) for lat in lats], "instructions": True, "geometry": True, "elevation": False, "units": "m"}
    if evitar:
        corpo["options"] = {"avoid_features": ["tollways"]}
    corpo.update(extra)
    return corpo


def _cenarios():
    return json.loads((FIXTURES / "cenarios.json").read_text(encoding="utf-8"))


def test_as_contas_a_mao_batem_com_os_valores_escritos():
    """As ajudas do teste conferem com números escritos à mão (e não só umas com as outras)."""
    assert _metros(0.1) == pytest.approx(14455.3405, abs=1e-4)
    assert [_segundos(d) for d in (0.02, 0.05, 0.1, 0.2, 0.25)] == [263, 657, 1314, 2628, 3285]


# --- O modelo: distância e duração -----------------------------------------------------------


def test_distancia_e_a_haversine_vezes_1_3():
    assert simulador.distancia_m(_ponto(38.0), _ponto(38.1)) == pytest.approx(_metros(0.1), rel=1e-9)
    assert simulador.distancia_m(_ponto(38.1), _ponto(38.0)) == pytest.approx(_metros(0.1), rel=1e-9)
    assert simulador.distancia_m(_ponto(38.0), _ponto(38.0)) == 0.0
    # Ao longo de um paralelo a ordem [lng, lat] conta: 0,1° de longitude a 38° N é menos de 0,1° de latitude.
    assert simulador.distancia_m([-8.0, 38.0], [-8.1, 38.0]) == pytest.approx(
        2 * RAIO_TERRA_M * math.asin(math.cos(math.radians(38.0)) * math.sin(math.radians(0.05))) * 1.3, rel=1e-9
    )


def test_duracao_a_11_metros_por_segundo_e_mais_15_por_cento_a_evitar_portagens():
    assert simulador.duracao_s(1100.0) == pytest.approx(100.0)
    assert simulador.duracao_s(1100.0, evitar_portagens=True) == pytest.approx(115.0)
    assert simulador.duracao_s(0.0, evitar_portagens=True) == 0.0


# --- Saúde, rotas e o cabeçalho Authorization ------------------------------------------------


def test_saude_sem_chave(cliente):
    resposta = cliente.get("/saude")
    assert resposta.status_code == 200
    assert resposta.json() == {"estado": "ok", "simulador": True}


def test_so_ha_as_tres_rotas(cliente):
    rotas = {(metodo, rota.path) for rota in simulador.app.routes if isinstance(rota, APIRoute) for metodo in rota.methods}
    assert rotas == {("GET", "/saude"), ("POST", OTIMIZACAO), ("POST", DIRECOES)}
    for caminho in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(caminho).status_code == 404
    assert _post(cliente, "/v2/directions/foot-walking/json", _pedido_direcoes([38.0, 38.1])).status_code == 404


@pytest.mark.parametrize("caminho", [OTIMIZACAO, DIRECOES])
@pytest.mark.parametrize("chave", [None, "", "   ", "\t"])
def test_sem_authorization_da_401(cliente, caminho, chave):
    corpo = _corpo([_job(1, 38.1)]) if caminho == OTIMIZACAO else _pedido_direcoes([38.0, 38.1])
    resposta = _post(cliente, caminho, corpo, chave=chave)
    assert resposta.status_code == 401
    assert isinstance(resposta.json()["error"], str)


@pytest.mark.parametrize("caminho", [OTIMIZACAO, DIRECOES])
def test_qualquer_authorization_nao_vazio_serve(cliente, caminho):
    corpo = _corpo([_job(1, 38.1)]) if caminho == OTIMIZACAO else _pedido_direcoes([38.0, 38.1])
    for chave in ("simulador-local", "outra-chave", CHAVE):
        assert _post(cliente, caminho, corpo, chave=chave).status_code == 200


def test_a_401_vem_antes_de_ler_o_corpo(cliente):
    assert _post(cliente, OTIMIZACAO, b"isto nao e json", chave=None).status_code == 401
    assert _post(cliente, DIRECOES, b"isto nao e json", chave=None).status_code == 401


@pytest.mark.parametrize("caminho", [OTIMIZACAO, DIRECOES])
@pytest.mark.parametrize("consulta", ["?api_key=" + CHAVE, "?x=1", "?"])
def test_nada_no_url_nem_a_chave(cliente, caminho, consulta):
    """A chave vai só no cabeçalho (§0, regra 12): o simulador recusa o que vier
    no URL, para a pré-visualização apanhar um cliente que a pusesse lá."""
    corpo = _corpo([_job(1, 38.1)]) if caminho == OTIMIZACAO else _pedido_direcoes([38.0, 38.1])
    resposta = cliente.post(caminho + consulta, json=corpo, headers={"Authorization": CHAVE})
    if consulta == "?":
        # Um "?" sozinho não traz parâmetros: o httpx nem o envia.
        assert resposta.status_code == 200
        return
    assert resposta.status_code == 400
    assert CHAVE not in resposta.text


def test_a_chave_nunca_volta_nas_respostas_nem_nos_registos(cliente, caplog):
    caplog.set_level(logging.DEBUG)
    for nome in ("httpx", "httpcore", "uvicorn", "fastapi"):
        caplog.set_level(logging.DEBUG, logger=nome)
    respostas = [
        _post(cliente, OTIMIZACAO, _corpo([_job(1, 38.1)])),
        _post(cliente, OTIMIZACAO, {"jobs": "x"}),
        _post(cliente, OTIMIZACAO, b"{"),
        _post(cliente, DIRECOES, _pedido_direcoes([38.0, 38.1])),
        _post(cliente, DIRECOES, {"coordinates": [[CHAVE, 38.0], [LNG, 38.1]]}),
        _post(cliente, DIRECOES, b"{"),
    ]
    assert [r.status_code for r in respostas] == [200, 400, 400, 200, 400, 400]
    for resposta in respostas:
        assert CHAVE not in resposta.text
    assert CHAVE not in caplog.text


def test_os_registos_so_tem_o_metodo_o_caminho_e_o_estado(cliente, caplog):
    """Uma chave posta por engano no URL nunca fica nos registos do simulador."""
    caplog.set_level(logging.DEBUG)
    cliente.post(OTIMIZACAO + "?api_key=" + CHAVE, json=_corpo([_job(1, 38.1)]), headers={"Authorization": "x"})
    _post(cliente, DIRECOES, _pedido_direcoes([38.0, 38.1]))
    _post(cliente, DIRECOES, _pedido_direcoes([38.0, 38.1]), chave=None)
    mensagens = [registo.getMessage() for registo in caplog.records if registo.name == "uvicorn.error"]
    assert mensagens == [
        f"POST {OTIMIZACAO} → 400",
        f"POST {DIRECOES} → 200",
        f"POST {DIRECOES} → 401",
    ]
    assert CHAVE not in caplog.text
    assert "api_key" not in caplog.text


# --- O VROOM simulado: tempos exatos ---------------------------------------------------------


def test_um_job_sem_janelas(cliente):
    resposta = _otimizar(cliente, _corpo([_job(1, 38.1, servico=600)]))
    ida = _segundos(0.1)
    assert resposta["code"] == 0
    assert resposta["unassigned"] == []
    rota = resposta["routes"][0]
    assert rota["vehicle"] == 1
    assert rota["steps"] == [
        {"type": "start", "location": _ponto(38.0), "setup": 0, "service": 0, "waiting_time": 0,
         "arrival": SAIDA, "duration": 0, "violations": []},
        {"type": "job", "id": 1, "job": 1, "location": _ponto(38.1), "setup": 0, "service": 600, "waiting_time": 0,
         "arrival": SAIDA + ida, "duration": ida, "violations": []},
        {"type": "end", "location": _ponto(38.0), "setup": 0, "service": 0, "waiting_time": 0,
         "arrival": SAIDA + ida + 600 + ida, "duration": 2 * ida, "violations": []},
    ]
    for chave, valor in {"cost": 2 * ida, "setup": 0, "service": 600, "duration": 2 * ida, "waiting_time": 0, "priority": 1}.items():
        assert rota[chave] == valor, chave
        assert resposta["summary"][chave] == valor, chave
    assert resposta["summary"]["routes"] == 1
    assert resposta["summary"]["unassigned"] == 0


def test_as_viagens_do_vroom_arredondam_ao_segundo_mais_perto(cliente):
    """0,02° no meridiano são 262,82 s: o VROOM simulado conta 263 (cortar dava 262)."""
    passos = _otimizar(cliente, _corpo([_job(1, 38.02)]))["routes"][0]["steps"]
    assert [passo["arrival"] for passo in passos] == [SAIDA, SAIDA + 263, SAIDA + 526]


def test_espera_pela_abertura_da_janela(cliente):
    resposta = _otimizar(cliente, _corpo([_job(1, 38.1, servico=600, janelas=[[32400, 36000]])]))
    ida = _segundos(0.1)
    job, fim = resposta["routes"][0]["steps"][1:]
    assert job["arrival"] == SAIDA + ida
    assert job["waiting_time"] == 32400 - (SAIDA + ida)
    assert fim["arrival"] == 32400 + 600 + ida
    assert resposta["summary"]["waiting_time"] == 32400 - (SAIDA + ida)


@pytest.mark.parametrize("janelas", [[[28800, 29000], [36000, 40000]], [[36000, 40000], [28800, 29000]]])
def test_espera_pela_segunda_janela_quando_a_primeira_ja_passou(cliente, janelas):
    resposta = _otimizar(cliente, _corpo([_job(1, 38.1, servico=600, janelas=janelas)]))
    job = resposta["routes"][0]["steps"][1]
    assert job["waiting_time"] == 36000 - (SAIDA + _segundos(0.1))


def test_um_job_com_a_janela_ja_passada_vai_para_unassigned(cliente):
    resposta = _otimizar(cliente, _corpo([_job(1, 38.1, janelas=[[0, 100]])]))
    assert resposta["code"] == 0
    assert resposta["routes"] == []
    assert resposta["unassigned"] == [{"id": 1, "type": "job", "location": _ponto(38.1)}]
    assert resposta["summary"]["routes"] == 0
    assert resposta["summary"]["unassigned"] == 1
    assert interpretar_otimizacao(resposta, {1: "a"}) == ([], ["a"])


def test_chegar_no_ultimo_segundo_da_janela_ainda_conta(cliente):
    chegada = SAIDA + _segundos(0.1)
    assert _ordem(_otimizar(cliente, _corpo([_job(1, 38.1, janelas=[[SAIDA, chegada]])]))) == [1]
    assert _nao_atribuidos(_otimizar(cliente, _corpo([_job(1, 38.1, janelas=[[SAIDA, chegada - 1]])]))) == [1]


def test_o_servico_conta_para_a_chegada_seguinte(cliente):
    """O 1 (entrega) vai primeiro e leva 10 min; o 2 só chega depois disso."""
    chegada_2 = SAIDA + _segundos(0.1) + 600 + _segundos(0.1)
    jobs = [_job(1, 38.1, servico=600, prioridade=100), _job(2, 38.2, janelas=[[SAIDA, chegada_2]])]
    assert _ordem(_otimizar(cliente, _corpo(jobs))) == [1, 2]
    jobs[1]["time_windows"] = [[SAIDA, chegada_2 - 1]]
    resposta = _otimizar(cliente, _corpo(jobs))
    assert _ordem(resposta) == [1]
    assert _nao_atribuidos(resposta) == [2]


def test_o_regresso_conta_para_o_fim_da_janela_do_veiculo(cliente):
    regresso = SAIDA + _segundos(0.1) + 600 + _segundos(0.1)
    assert _ordem(_otimizar(cliente, _corpo([_job(1, 38.1, servico=600)], limite=regresso))) == [1]
    resposta = _otimizar(cliente, _corpo([_job(1, 38.1, servico=600)], limite=regresso - 1))
    assert resposta["routes"] == []
    assert _nao_atribuidos(resposta) == [1]


def test_o_regresso_e_ao_fim_do_veiculo_e_nao_ao_inicio(cliente):
    resposta = _otimizar(cliente, _corpo([_job(1, 38.1)], inicio=38.0, fim=38.3))
    fim = resposta["routes"][0]["steps"][-1]
    assert fim["location"] == _ponto(38.3)
    assert fim["arrival"] == SAIDA + _segundos(0.1) + _segundos(0.2)


def test_sem_janela_no_veiculo_sai_a_zero_e_nao_tem_limite(cliente):
    corpo = _corpo([_job(1, 38.1)])
    del corpo["vehicles"][0]["time_window"]
    passos = _otimizar(cliente, corpo)["routes"][0]["steps"]
    assert [passo["arrival"] for passo in passos] == [0, _segundos(0.1), 2 * _segundos(0.1)]


def test_o_veiculo_e_o_do_pedido(cliente):
    assert _otimizar(cliente, _corpo([_job(1, 38.1)], id_=7))["routes"][0]["vehicle"] == 7


# --- O VROOM simulado: a escolha gulosa ------------------------------------------------------


def test_a_entrega_vai_primeiro_mesmo_mais_longe(cliente):
    jobs = [_job(1, 38.05, prioridade=1), _job(2, 38.3, prioridade=100)]
    resposta = _otimizar(cliente, _corpo(jobs))
    assert _ordem(resposta) == [2, 1]
    assert resposta["summary"]["priority"] == 101


def test_vizinho_mais_proximo_a_partir_de_onde_a_carrinha_esta(cliente):
    """Da partida (38,0) o mais perto é o 2 (38,1); daí é o 3 (38,3: 0,2°) e não o
    1 (37,85: 0,25°), embora o 1 esteja mais perto da partida do que o 3."""
    jobs = [_job(1, 37.85), _job(2, 38.1), _job(3, 38.3)]
    assert _ordem(_otimizar(cliente, _corpo(jobs))) == [2, 3, 1]


def test_empate_na_distancia_pela_ordem_do_pedido(cliente):
    assert _ordem(_otimizar(cliente, _corpo([_job(7, 38.1), _job(3, 38.1)]))) == [7, 3]
    assert _ordem(_otimizar(cliente, _corpo([_job(3, 38.1), _job(7, 38.1)]))) == [3, 7]


def test_nao_atribuidos_pela_ordem_do_pedido(cliente):
    resposta = _otimizar(cliente, _corpo([_job(5, 38.1, janelas=[[0, 1]]), _job(4, 38.1), _job(2, 38.2, janelas=[[0, 1]])]))
    assert _ordem(resposta) == [4]
    assert resposta["unassigned"] == [
        {"id": 5, "type": "job", "location": _ponto(38.1)},
        {"id": 2, "type": "job", "location": _ponto(38.2)},
    ]
    assert interpretar_otimizacao(resposta, {5: "c", 4: "b", 2: "a"}) == (["b"], ["a", "c"])


# --- O VROOM simulado: os pedidos do domínio -------------------------------------------------


def test_os_cenarios_passam_as_verificacoes_do_gravador(cliente):
    """As respostas do simulador aos 3 pedidos sem erro do `cenarios.json` passam
    as mesmas verificações que o gravador (T3.12) faz às do ORS verdadeiro: lidas
    pelo `interpretar_*`, nenhuma de fora no "todas", só a Torre de Belém no
    "uma-nao-cabe" e todos os troços com distância e duração."""
    lista = gravador.pedidos(_cenarios())
    assert [p.nome for p in lista] == ["otimizacao-todas", "otimizacao-uma-nao-cabe", "direcoes-tres-paragens", "direcoes-erro-2010"]
    for pedido in lista:
        resposta = _post(cliente, pedido.caminho, pedido.corpo)
        assert resposta.status_code == 200, pedido.nome
        if not pedido.espera_erro:
            pedido.conferir(resposta.json())


def _pedido_do_cenario(nome):
    cenarios = _cenarios()
    pontos = cenarios["pontos"]
    cenario = cenarios["otimizacao"][nome]
    paragens = [
        vroom.paragem_calculo(
            {"id": p["ponto"], "motivo": p["motivo"], "tempo_servico_min": p["tempo_servico_min"]},
            {**pontos[p["ponto"]], "janelas": p["janelas"]},
        )
        for p in cenario["paragens"]
    ]
    inicio = (pontos[cenario["inicio"]]["lat"], pontos[cenario["inicio"]]["lng"])
    return vroom.pedido_otimizacao(paragens, inicio, inicio, 28800, 68400)


def test_o_cenario_todas_pela_prioridade_e_depois_pelo_mais_perto(cliente):
    """A entrega na Praça do Comércio primeiro (espera pelas 09:00), depois o
    Marquês (mais perto do Comércio) e por fim Belém."""
    pedido = _pedido_do_cenario("otimizacao-todas")
    resposta = _otimizar(cliente, pedido.corpo)
    assert interpretar_otimizacao(resposta, pedido.por_job) == (
        ["praca_do_comercio", "marques_de_pombal", "torre_de_belem"],
        [],
    )
    comercio = resposta["routes"][0]["steps"][1]
    assert comercio["arrival"] + comercio["waiting_time"] == 32400


def test_o_cenario_uma_nao_cabe(cliente):
    pedido = _pedido_do_cenario("otimizacao-uma-nao-cabe")
    resposta = _otimizar(cliente, pedido.corpo)
    assert interpretar_otimizacao(resposta, pedido.por_job) == (["praca_do_comercio", "marques_de_pombal"], ["torre_de_belem"])


# --- O Directions simulado -------------------------------------------------------------------


def test_troços_e_resumo_com_uma_casa_decimal(cliente):
    resposta = _direcoes(cliente, _pedido_direcoes([38.0, 38.1, 38.3]))
    rota = resposta["routes"][0]
    assert [(s["distance"], s["duration"]) for s in rota["segments"]] == [(14455.3, 1314.1), (28910.7, 2628.2)]
    assert rota["summary"] == {"distance": 43366.0, "duration": 3942.4}
    assert rota["way_points"] == [0, 1, 2]
    assert rota["bbox"] == [LNG, 38.0, LNG, 38.3]
    assert resposta["bbox"] == [LNG, 38.0, LNG, 38.3]
    trocos = interpretar_direcoes(resposta, 3)
    assert trocos.duracoes == [1314.1, 2628.2]
    assert trocos.distancias == [14455.3, 28910.7]
    assert (trocos.distancia_m, trocos.duracao_s) == (43366, 3942)


def test_cada_troco_tem_os_passos_de_partida_e_chegada(cliente):
    rota = _direcoes(cliente, _pedido_direcoes([38.0, 38.1, 38.3]))["routes"][0]
    for indice, segmento in enumerate(rota["segments"]):
        partida, chegada = segmento["steps"]
        assert (partida["distance"], partida["duration"]) == (segmento["distance"], segmento["duration"])
        assert partida["way_points"] == [indice, indice + 1]
        assert chegada["way_points"] == [indice + 1, indice + 1]
        assert "distance" not in chegada and "duration" not in chegada
        assert isinstance(partida["instruction"], str) and isinstance(chegada["instruction"], str)


def test_a_evitar_portagens_a_duracao_sobe_15_por_cento(cliente):
    rota = _direcoes(cliente, _pedido_direcoes([38.0, 38.1, 38.3], evitar=True))["routes"][0]
    assert [(s["distance"], s["duration"]) for s in rota["segments"]] == [(14455.3, 1511.2), (28910.7, 3022.5)]
    assert rota["summary"] == {"distance": 43366.0, "duration": 4533.7}


def test_outras_opcoes_a_evitar_nao_mudam_a_duracao(cliente):
    rota = _direcoes(cliente, _pedido_direcoes([38.0, 38.1], options={"avoid_features": ["ferries"]}))["routes"][0]
    assert rota["segments"][0]["duration"] == 1314.1


def test_um_troco_de_comprimento_zero_vem_sem_distancia_nem_duracao(cliente):
    """Como o ORS (correção "T3.7 (+ T3.13, T3.21)"): duas lojas no mesmo sítio."""
    resposta = _direcoes(cliente, _pedido_direcoes([38.0, 38.1, 38.1, 38.0]))
    meio = resposta["routes"][0]["segments"][1]
    assert "distance" not in meio and "duration" not in meio
    assert all("distance" not in passo and "duration" not in passo for passo in meio["steps"])
    trocos = interpretar_direcoes(resposta, 4)
    assert trocos.duracoes == [1314.1, 0.0, 1314.1]
    assert trocos.distancias == [14455.3, 0.0, 14455.3]


def test_uma_rota_toda_no_mesmo_sitio_vem_sem_totais(cliente):
    resposta = _direcoes(cliente, _pedido_direcoes([38.0, 38.0]))
    rota = resposta["routes"][0]
    assert rota["summary"] == {}
    assert len(rota["segments"]) == 1 and "distance" not in rota["segments"][0]
    trocos = interpretar_direcoes(resposta, 2)
    assert (trocos.distancia_m, trocos.duracao_s, trocos.duracoes) == (0, 0, [0.0])
    assert polilinha.descodificar(trocos.geometria) == [(38.0, LNG), (38.0, LNG)]


@pytest.mark.parametrize(
    "pontos",
    [
        [(38.722345, -9.139301), (38.7253, -9.15), (41.149999, -8.611111), (38.722345, -9.139301)],
        [(37.019356, -7.930440), (37.019356, -7.930440), (42.154302, -8.198765)],
    ],
)
def test_a_linha_e_reta_entre_os_pontos_pedidos(cliente, pontos):
    """`descodificar(codificar(p)) ≈ p` a 1e-5: a linha passa pelos pontos do pedido, pela ordem."""
    corpo = pedido_direcoes(pontos, False)
    rota = _direcoes(cliente, corpo)["routes"][0]
    linha = polilinha.descodificar(rota["geometry"])
    assert len(linha) == len(pontos)
    for (lat, lng), (lat_linha, lng_linha) in zip(pontos, linha):
        assert abs(lat - lat_linha) <= 1e-5 and abs(lng - lng_linha) <= 1e-5
    assert rota["geometry"] == polilinha.codificar([(lat, lng) for lng, lat in corpo["coordinates"]])


def test_sem_instructions_nao_ha_troços(cliente):
    """Como o ORS (risco R2): sem `instructions`, a rota vem sem `segments`."""
    resposta = _direcoes(cliente, _pedido_direcoes([38.0, 38.1], instructions=False))
    assert "segments" not in resposta["routes"][0]
    with pytest.raises(RespostaInvalida):
        interpretar_direcoes(resposta, 2)


def test_sem_geometry_nao_ha_linha(cliente):
    resposta = _direcoes(cliente, _pedido_direcoes([38.0, 38.1], geometry=False))
    assert "geometry" not in resposta["routes"][0]


def test_por_omissao_traz_os_troços_e_a_linha(cliente):
    rota = _direcoes(cliente, {"coordinates": [_ponto(38.0), _ponto(38.1)]})["routes"][0]
    assert len(rota["segments"]) == 1
    assert len(polilinha.descodificar(rota["geometry"])) == 2


def test_o_pedido_do_dominio_com_portagens(cliente):
    corpo = pedido_direcoes([(38.0, LNG), (38.1, LNG)], True)
    trocos = interpretar_direcoes(_direcoes(cliente, corpo), 2)
    assert trocos.duracoes == [1511.2]


def test_o_simulador_nao_sabe_onde_ha_estradas(cliente):
    """O ponto no rio do cenário do 2010 dá uma rota: o simulador nunca dá o 2010
    (é só o ORS verdadeiro que o prova, pelo gravador)."""
    cenarios = _cenarios()
    pontos = [(cenarios["pontos"][p]["lat"], cenarios["pontos"][p]["lng"]) for p in cenarios["direcoes"]["direcoes-erro-2010"]["pontos"]]
    assert interpretar_direcoes(_direcoes(cliente, pedido_direcoes(pontos, False)), 4).distancia_m > 0


# --- Marcado como simulador e determinístico -------------------------------------------------


def test_as_respostas_dizem_que_sao_do_simulador(cliente):
    """Risco R14: nunca se confunde com o ORS verdadeiro."""
    for resposta in (_otimizar(cliente, _corpo([_job(1, 38.1)])), _direcoes(cliente, _pedido_direcoes([38.0, 38.1]))):
        assert resposta["metadata"]["simulador"] is True
        assert "simulador" in resposta["metadata"]["attribution"]


def test_deterministico(cliente):
    corpo = _pedido_do_cenario("otimizacao-todas").corpo
    primeira = _post(cliente, OTIMIZACAO, corpo).content
    assert _post(cliente, OTIMIZACAO, corpo).content == primeira
    corpo = _pedido_direcoes([38.0, 38.1, 38.3], evitar=True)
    primeira = _post(cliente, DIRECOES, corpo).content
    assert _post(cliente, DIRECOES, corpo).content == primeira


# --- Pedidos inválidos -----------------------------------------------------------------------


def _com(base, **mudancas):
    novo = json.loads(json.dumps(base))
    for chave, valor in mudancas.items():
        if valor is _APAGAR:
            del novo[chave]
        else:
            novo[chave] = valor
    return novo


_APAGAR = object()
_JOB = _job(1, 38.1, servico=600, janelas=[[28800, 36000]])
_VEICULO = _veiculo()

OTIMIZACOES_INVALIDAS = {
    "não é JSON": b"{isto",
    "NaN": b'{"jobs": [{"id": 1, "location": [NaN, 38.1]}], "vehicles": []}',
    "lista": [1, 2],
    "sem jobs": {"vehicles": [_VEICULO]},
    "jobs vazio": {"jobs": [], "vehicles": [_VEICULO]},
    "jobs em texto": {"jobs": "x", "vehicles": [_VEICULO]},
    "job em texto": {"jobs": ["x"], "vehicles": [_VEICULO]},
    "sem vehicles": {"jobs": [_JOB]},
    "vehicles vazio": {"jobs": [_JOB], "vehicles": []},
    "duas carrinhas": {"jobs": [_JOB], "vehicles": [_VEICULO, _com(_VEICULO, id=2)]},
    "veículo em texto": {"jobs": [_JOB], "vehicles": ["x"]},
    "veículo sem id": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, id=_APAGAR)]},
    "veículo id bool": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, id=True)]},
    "outro perfil": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, profile="foot-walking")]},
    "sem perfil": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, profile=_APAGAR)]},
    "sem start": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, start=_APAGAR)]},
    "sem end": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, end=_APAGAR)]},
    "start lat lng trocado fora do mundo": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, start=[38.0, -98.0])]},
    "janela do veículo ao contrário": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, time_window=[5, 4])]},
    "janela do veículo decimal": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, time_window=[1.5, 4])]},
    "janela do veículo com 3": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, time_window=[1, 2, 3])]},
    "janela do veículo negativa": {"jobs": [_JOB], "vehicles": [_com(_VEICULO, time_window=[-1, 4])]},
    "job sem id": {"jobs": [_com(_JOB, id=_APAGAR)], "vehicles": [_VEICULO]},
    "job id bool": {"jobs": [_com(_JOB, id=True)], "vehicles": [_VEICULO]},
    "job id texto": {"jobs": [_com(_JOB, id="1")], "vehicles": [_VEICULO]},
    "job id decimal": {"jobs": [_com(_JOB, id=1.0)], "vehicles": [_VEICULO]},
    "jobs repetidos": {"jobs": [_JOB, _com(_JOB)], "vehicles": [_VEICULO]},
    "sem location": {"jobs": [_com(_JOB, location=_APAGAR)], "vehicles": [_VEICULO]},
    "location com 1": {"jobs": [_com(_JOB, location=[LNG])], "vehicles": [_VEICULO]},
    "location em texto": {"jobs": [_com(_JOB, location=["a", 38.1])], "vehicles": [_VEICULO]},
    "location bool": {"jobs": [_com(_JOB, location=[True, 38.1])], "vehicles": [_VEICULO]},
    "latitude 95": {"jobs": [_com(_JOB, location=[LNG, 95])], "vehicles": [_VEICULO]},
    "longitude -181": {"jobs": [_com(_JOB, location=[-181, 38.1])], "vehicles": [_VEICULO]},
    "serviço negativo": {"jobs": [_com(_JOB, service=-1)], "vehicles": [_VEICULO]},
    "serviço decimal": {"jobs": [_com(_JOB, service=1.5)], "vehicles": [_VEICULO]},
    "prioridade 101": {"jobs": [_com(_JOB, priority=101)], "vehicles": [_VEICULO]},
    "prioridade -1": {"jobs": [_com(_JOB, priority=-1)], "vehicles": [_VEICULO]},
    "prioridade bool": {"jobs": [_com(_JOB, priority=True)], "vehicles": [_VEICULO]},
    "janelas vazias": {"jobs": [_com(_JOB, time_windows=[])], "vehicles": [_VEICULO]},
    "janela ao contrário": {"jobs": [_com(_JOB, time_windows=[[10, 5]])], "vehicles": [_VEICULO]},
    "janela com 3": {"jobs": [_com(_JOB, time_windows=[[1, 2, 3]])], "vehicles": [_VEICULO]},
    "janelas em texto": {"jobs": [_com(_JOB, time_windows="manhã")], "vehicles": [_VEICULO]},
}


@pytest.mark.parametrize("nome", list(OTIMIZACOES_INVALIDAS))
def test_otimizacao_invalida_da_400_na_forma_do_vroom(cliente, nome):
    resposta = _post(cliente, OTIMIZACAO, OTIMIZACOES_INVALIDAS[nome])
    assert resposta.status_code == 400
    corpo = resposta.json()
    assert set(corpo) == {"code", "error"}
    assert corpo["code"] == 2
    assert isinstance(corpo["error"], str) and corpo["error"]


def test_o_pedido_valido_de_base_e_aceite(cliente):
    """O molde dos inválidos (`_JOB`, `_VEICULO`) é aceite: cada inválido só muda uma coisa."""
    assert _ordem(_otimizar(cliente, {"jobs": [_JOB], "vehicles": [_VEICULO]})) == [1]
    assert _direcoes(cliente, _DIRECOES)["routes"]


_DIRECOES = _pedido_direcoes([38.0, 38.1])

DIRECOES_INVALIDAS = {
    "não é JSON": (b"{isto", 2000),
    "NaN": (b'{"coordinates": [[NaN, 38.0], [-8.0, 38.1]]}', 2000),
    "lista": ([1, 2], 2000),
    "sem coordinates": ({"instructions": True}, 2001),
    "coordinates em texto": (_com(_DIRECOES, coordinates="x"), 2003),
    "um só ponto": (_com(_DIRECOES, coordinates=[_ponto(38.0)]), 2003),
    "51 pontos": (_com(_DIRECOES, coordinates=[_ponto(38.0 + i / 100) for i in range(51)]), 2004),
    "ponto com 3": (_com(_DIRECOES, coordinates=[[LNG, 38.0, 1], _ponto(38.1)]), 2003),
    "ponto em texto": (_com(_DIRECOES, coordinates=[["-8", 38.0], _ponto(38.1)]), 2003),
    "ponto bool": (_com(_DIRECOES, coordinates=[[True, 38.0], _ponto(38.1)]), 2003),
    "ponto objeto": (_com(_DIRECOES, coordinates=[{"lat": 38.0, "lng": LNG}, _ponto(38.1)]), 2003),
    "latitude 91": (_com(_DIRECOES, coordinates=[[LNG, 91], _ponto(38.1)]), 2003),
    "longitude 181": (_com(_DIRECOES, coordinates=[[181, 38.0], _ponto(38.1)]), 2003),
    "instructions em texto": (_com(_DIRECOES, instructions="sim"), 2003),
    "geometry 1": (_com(_DIRECOES, geometry=1), 2003),
    "elevation": (_com(_DIRECOES, elevation=True), 2003),
    "units km": (_com(_DIRECOES, units="km"), 2003),
    "options em texto": (_com(_DIRECOES, options="x"), 2003),
    "avoid_features em texto": (_com(_DIRECOES, options={"avoid_features": "tollways"}), 2003),
    "avoid_features com número": (_com(_DIRECOES, options={"avoid_features": [1]}), 2003),
}


@pytest.mark.parametrize("nome", list(DIRECOES_INVALIDAS))
def test_directions_invalido_da_400_na_forma_do_ors(cliente, nome):
    corpo, codigo = DIRECOES_INVALIDAS[nome]
    resposta = _post(cliente, DIRECOES, corpo)
    assert resposta.status_code == 400
    erro = resposta.json()["error"]
    assert set(erro) == {"code", "message"}
    assert erro["code"] == codigo
    assert isinstance(erro["message"], str) and erro["message"]


def test_cinquenta_pontos_ainda_servem(cliente):
    corpo = _com(_DIRECOES, coordinates=[_ponto(38.0 + i / 100) for i in range(50)])
    assert len(interpretar_direcoes(_direcoes(cliente, corpo), 50).duracoes) == 49


# --- Só em 127.0.0.1: a guarda do anfitrião --------------------------------------------------


@pytest.fixture
def arranques(monkeypatch):
    """O `uvicorn.run` falso: regista em vez de arrancar."""
    chamadas = []
    monkeypatch.setattr(simulador.uvicorn, "run", lambda *args, **kwargs: chamadas.append((args, kwargs)))
    return chamadas


def test_por_omissao_escuta_em_127_0_0_1_na_porta_8013(arranques):
    simulador.principal([])
    assert len(arranques) == 1
    args, kwargs = arranques[0]
    assert args == (simulador.app,)
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8013
    # Sem o registo de acesso do uvicorn, que escrevia o URL com os parâmetros.
    assert kwargs["access_log"] is False


@pytest.mark.parametrize("anfitriao", ["127.0.0.1", "localhost", "::1"])
def test_os_anfitrioes_locais_servem(arranques, anfitriao):
    simulador.principal(["--host", anfitriao, "--porta", "8020"])
    assert [(kwargs["host"], kwargs["port"]) for _, kwargs in arranques] == [(anfitriao, 8020)]


@pytest.mark.parametrize(
    "anfitriao",
    ["0.0.0.0", "::", "", " 127.0.0.1", "127.0.0.2", "192.168.1.10", "10.0.0.1", "LOCALHOST",
     "localhost.localdomain", "[::1]", "0", "lisbonb.com", "rh.lisbonb.com"],
)
def test_outro_anfitriao_e_recusado_sem_arrancar(arranques, anfitriao):
    with pytest.raises(SystemExit) as excinfo:
        simulador.principal(["--host", anfitriao])
    assert excinfo.value.code == MENSAGEM_ANFITRIAO
    assert arranques == []


@pytest.mark.parametrize("porta", ["0", "65536", "-1", "abc", "8013.5"])
def test_porta_invalida(arranques, porta, capsys):
    with pytest.raises(SystemExit) as excinfo:
        simulador.principal(["--porta", porta])
    assert excinfo.value.code == 2
    assert arranques == []


# --- Fora do portal, sem relógio, sem rede ---------------------------------------------------


def test_o_simulador_nao_entra_no_portal():
    """Nem o server.py nem o pacote `crm` o importam, e o router do CRM não tem
    as rotas do ORS: o simulador só existe na pré-visualização local."""
    fontes = [BACKEND / "server.py", *sorted((BACKEND / "crm").rglob("*.py"))]
    for fonte in fontes:
        assert "ors_simulado_local" not in fonte.read_text(encoding="utf-8"), fonte.name
    caminhos = {rota.path for rota in crm.router.routes}
    assert not any("/optimization" in caminho or "/v2/directions" in caminho for caminho in caminhos)


PROIBIDOS = {"datetime", "time", "random", "zoneinfo", "uuid", "secrets", "os", "httpx", "requests", "urllib",
             "socket", "http", "aiohttp", "dotenv"}


def test_sem_relogio_sem_acaso_sem_ambiente_e_sem_clientes_de_rede():
    importados = set()
    for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            importados.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")
            importados.update(f"{no.module}.{alias.name}" for alias in no.names)
    raizes = {nome.split(".")[0] for nome in importados}
    assert not raizes & PROIBIDOS
    assert "crm.relogio" not in importados


def test_nunca_chama_o_round():
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []


def test_a_linha_usa_o_codificar_do_dominio(cliente, monkeypatch):
    """Correção "T3.7 / T3.9 / T3.13 / T3.21": uma só implementação da polyline,
    a do `crm.dominio.polilinha`."""
    chamadas = []
    original = polilinha.codificar

    def _codificar(pontos, *args, **kwargs):
        chamadas.append(list(pontos))
        return original(pontos, *args, **kwargs)

    monkeypatch.setattr(polilinha, "codificar", _codificar)
    _direcoes(cliente, _pedido_direcoes([38.0, 38.1]))
    assert chamadas == [[(38.0, LNG), (38.1, LNG)]]
