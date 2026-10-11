"""O pedido ao otimizador (VROOM do openrouteservice) e a leitura da resposta
(crm/dominio/vroom.py), F3 / T3.6.

Plano F3 §1 ("Pedido VROOM") e §0 regra 12: ao openrouteservice só vão
coordenadas, segundos, prioridades, índices numéricos 1..n e a constante
`"driving-car"` — nunca nomes, telefones, moradas ou uuids. O teste dos
canários prova-o com lojas e paragens completas (risco R4).

- um veículo `driving-car`, `start`/`end` = início/fim, `time_window` =
  [saída, regresso limite];
- por cada paragem um *job* `{id: 1..n, location: [lng, lat], service: s,
  priority, time_windows: [[a, b − s]…]}`, só com as janelas onde o serviço
  cabe; uma paragem sem nenhuma janela onde caiba é impossível e não vai;
- prioridades: entrega 100, as outras 1.

A resposta lê-se com um parser estrito (risco R3): o que não bater certo é
`RespostaInvalida` (→ 503 nas rotas, T3.22). Correções aplicadas:
- "T3.6 / T3.22": `routes: []` com todos em `unassigned` → `([], todos)`;
- "T3.6": cada passo de job traz `id` e também `job` (a chave antiga do
  VROOM); lê-se o `id`, cai-se para o `job` só sem `id`, e os dois diferentes
  são inválidos; os passos `start`/`end` ignoram-se e outro tipo é inválido;
- "T3.12 / T3.43": os testes sobre as fixtures (que o dono vai regravar)
  verificam só a forma e os conjuntos; os valores exatos (a ordem 2, 1, 3)
  vêm de respostas escritas no próprio teste.
"""
import ast
import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

import crm.dominio.vroom as vroom
from crm import formatar
from crm.dominio import horas, validador_loja
from crm.dominio.vroom import (
    ParagemCalculo,
    PedidoOtimizacao,
    RespostaInvalida,
    interpretar_otimizacao,
    paragem_calculo,
    pedido_otimizacao,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ors"
FICHEIRO = Path(vroom.__file__)

FABRICA = (38.7223, -9.1393)
COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6916, -9.216)

SAIDA = 28800  # 08:00
LIMITE = 68400  # 19:00


def _ler(nome):
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


def _pc(id_, ponto=COMERCIO, servico_s=600, janelas_s=None, motivo="amostra"):
    return ParagemCalculo(id_, ponto[0], ponto[1], servico_s, janelas_s, motivo)


def _paragem(id_="p", motivo="amostra", tempo=10, **mais):
    return {"id": id_, "loja_id": "l", "motivo": motivo, "tempo_servico_min": tempo, **mais}


def _loja(lat=38.7075, lng=-9.1364, janelas=(), **mais):
    return {"lat": lat, "lng": lng, "janelas": [dict(j) for j in janelas], **mais}


# --- paragem_calculo -------------------------------------------------------------------------


def test_paragem_calculo_junta_o_que_o_calculo_precisa():
    paragem = _paragem("p1", motivo="entrega", tempo=15)
    loja = _loja(38.7075, -9.1364, [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}])
    assert paragem_calculo(paragem, loja) == ParagemCalculo(
        id="p1", lat=38.7075, lng=-9.1364, servico_s=900, janelas_s=[(36000, 46800), (54000, 68400)], motivo="entrega"
    )


def test_os_campos_da_paragem_de_calculo():
    assert ParagemCalculo._fields == ("id", "lat", "lng", "servico_s", "janelas_s", "motivo")


def test_uma_loja_sem_janelas_nao_tem_restricao():
    resultado = paragem_calculo(_paragem(), _loja(janelas=[]))
    assert resultado.janelas_s is None


def test_o_servico_em_segundos_inteiros():
    for minutos in (1, 10, 240):
        resultado = paragem_calculo(_paragem(tempo=minutos), _loja())
        assert resultado.servico_s == minutos * 60
        assert type(resultado.servico_s) is int


def test_as_coordenadas_em_float():
    resultado = paragem_calculo(_paragem(), _loja(lat=39, lng=-9))
    assert (resultado.lat, resultado.lng) == (39.0, -9.0)
    assert type(resultado.lat) is float and type(resultado.lng) is float


class _Lido(dict):
    """Um dicionário que regista as chaves lidas e rebenta se alguém o percorrer todo."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lidas = []

    def __getitem__(self, chave):
        self.lidas.append(chave)
        return super().__getitem__(chave)

    def get(self, chave, omissao=None):
        self.lidas.append(chave)
        return super().get(chave, omissao)

    def __contains__(self, chave):
        self.lidas.append(chave)
        return super().__contains__(chave)

    def _tudo(self, *args, **kwargs):
        raise AssertionError("percorreu o documento inteiro")

    __iter__ = keys = items = values = copy = _tudo


def test_paragem_calculo_so_le_as_coordenadas_as_janelas_o_tempo_e_o_motivo():
    paragem = _Lido(
        _paragem("p1", adicionada_por="m", estado="pendente", chegada_prevista="09:00", notas="CANARIO", nome="CANARIO")
    )
    loja = _Lido(_loja(janelas=[{"inicio": "10:00", "fim": "13:00"}], nome="CANARIO", telefone="+351912345678", morada="x"))
    paragem_calculo(paragem, loja)
    assert set(loja.lidas) == {"lat", "lng", "janelas"}
    assert set(paragem.lidas) == {"id", "tempo_servico_min", "motivo"}


def test_paragem_calculo_nao_muda_o_que_recebe():
    paragem = _paragem("p1")
    loja = _loja(janelas=[{"inicio": "10:00", "fim": "13:00"}])
    copias = copy.deepcopy((paragem, loja))
    paragem_calculo(paragem, loja)
    assert (paragem, loja) == copias


@pytest.mark.parametrize("tempo", [0, 241, -10, 10.0, True, "10", None, 2**63])
def test_paragem_calculo_recusa_um_tempo_de_servico_fora_de_1_a_240(tempo):
    with pytest.raises(ValueError):
        paragem_calculo(_paragem(tempo=tempo), _loja())


@pytest.mark.parametrize("motivo", ["", "visita", "ENTREGA", None, 1, ["entrega"]])
def test_paragem_calculo_recusa_um_motivo_desconhecido(motivo):
    with pytest.raises(ValueError):
        paragem_calculo(_paragem(motivo=motivo), _loja())


@pytest.mark.parametrize("campo", ["lat", "lng"])
@pytest.mark.parametrize("valor", [None, True, "38.7", math.nan, math.inf, [38.7]])
def test_paragem_calculo_recusa_coordenadas_que_nao_sao_numeros(campo, valor):
    with pytest.raises(ValueError):
        paragem_calculo(_paragem(), {**_loja(), campo: valor})


@pytest.mark.parametrize("id_", [None, 1, ["p"], b"p"])
def test_paragem_calculo_recusa_um_id_que_nao_e_texto(id_):
    with pytest.raises(ValueError):
        paragem_calculo(_paragem(id_), _loja())


def test_paragem_calculo_recusa_janelas_estragadas():
    with pytest.raises(ValueError):
        paragem_calculo(_paragem(), _loja(janelas=[{"inicio": "13:00", "fim": "10:00"}]))


# --- pedido_otimizacao: o corpo ----------------------------------------------------------------


def test_o_corpo_do_pedido():
    paragens = [
        _pc("a", COMERCIO, 600, [(32400, 43200)], "entrega"),
        _pc("b", MARQUES, 600, None, "amostra"),
        _pc("c", BELEM, 900, None, "acompanhamento"),
    ]
    pedido = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE)
    assert pedido.corpo == {
        "jobs": [
            {"id": 1, "location": [-9.1364, 38.7075], "service": 600, "priority": 100, "time_windows": [[32400, 42600]]},
            {"id": 2, "location": [-9.15, 38.7253], "service": 600, "priority": 1},
            {"id": 3, "location": [-9.216, 38.6916], "service": 900, "priority": 1},
        ],
        "vehicles": [
            {"id": 1, "profile": "driving-car", "start": [-9.1393, 38.7223], "end": [-9.1393, 38.7223], "time_window": [28800, 68400]}
        ],
    }
    assert pedido.por_job == {1: "a", 2: "b", 3: "c"}
    assert pedido.impossiveis == []
    assert isinstance(pedido, PedidoOtimizacao)
    assert PedidoOtimizacao._fields == ("corpo", "por_job", "impossiveis")


def test_os_ids_dos_jobs_sao_inteiros_de_1_a_n_pela_ordem_recebida():
    paragens = [_pc(f"p{i}") for i in range(12)]
    pedido = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE)
    ids = [job["id"] for job in pedido.corpo["jobs"]]
    assert ids == list(range(1, 13))
    assert all(type(i) is int for i in ids)
    assert list(pedido.por_job.items()) == [(i + 1, f"p{i}") for i in range(12)]


def test_o_inicio_e_o_fim_do_veiculo_podem_ser_diferentes():
    pedido = pedido_otimizacao([_pc("a")], MARQUES, BELEM, SAIDA, LIMITE)
    veiculo = pedido.corpo["vehicles"][0]
    assert veiculo["start"] == [-9.15, 38.7253]
    assert veiculo["end"] == [-9.216, 38.6916]


def test_as_coordenadas_vao_como_lng_lat_arredondadas_meio_para_longe_do_zero_as_6_casas():
    """38,7223445 → 38,722345 e −9,1393005 → −9,139301; o `round` do Python dava
    38,722344 e −9,1393 (o binário destes números fica abaixo do meio)."""
    ponto = (38.7223445, -9.1393005)
    pedido = pedido_otimizacao([_pc("a", ponto)], ponto, ponto, SAIDA, LIMITE)
    assert pedido.corpo["jobs"][0]["location"] == [-9.139301, 38.722345]
    assert pedido.corpo["vehicles"][0]["start"] == [-9.139301, 38.722345]
    assert pedido.corpo["vehicles"][0]["end"] == [-9.139301, 38.722345]


def test_a_prioridade_da_entrega_e_100_e_a_das_outras_1():
    paragens = [_pc(m, motivo=m) for m in ("entrega", "amostra", "acompanhamento", "angariacao")]
    pedido = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE)
    assert [job["priority"] for job in pedido.corpo["jobs"]] == [100, 1, 1, 1]


def test_sem_janelas_o_job_nao_leva_time_windows():
    pedido = pedido_otimizacao([_pc("a", janelas_s=None)], FABRICA, FABRICA, SAIDA, LIMITE)
    assert "time_windows" not in pedido.corpo["jobs"][0]


def test_as_janelas_do_job_sao_as_do_inicio_do_servico():
    pedido = pedido_otimizacao(
        [_pc("a", servico_s=900, janelas_s=[(36000, 46800), (54000, 68400)])], FABRICA, FABRICA, SAIDA, LIMITE
    )
    assert pedido.corpo["jobs"][0]["time_windows"] == [[36000, 45900], [54000, 67500]]


def test_uma_janela_onde_o_servico_nao_cabe_nao_vai():
    pedido = pedido_otimizacao(
        [_pc("a", servico_s=600, janelas_s=[(36000, 36300), (54000, 68400)])], FABRICA, FABRICA, SAIDA, LIMITE
    )
    assert pedido.corpo["jobs"][0]["time_windows"] == [[54000, 67800]]


def test_uma_paragem_sem_nenhuma_janela_onde_o_servico_caiba_e_impossivel_e_nao_vai():
    paragens = [
        _pc("a"),
        _pc("b", servico_s=900, janelas_s=[(36000, 36600)]),  # 10 min de janela, 15 de serviço
        _pc("c", motivo="entrega"),
    ]
    pedido = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE)
    assert pedido.impossiveis == ["b"]
    assert [job["id"] for job in pedido.corpo["jobs"]] == [1, 2]
    assert pedido.por_job == {1: "a", 2: "c"}
    assert pedido.corpo["jobs"][1]["priority"] == 100
    assert "b" not in pedido.por_job.values()


def test_o_servico_que_enche_a_janela_ainda_vai():
    pedido = pedido_otimizacao([_pc("a", servico_s=600, janelas_s=[(36000, 36600)])], FABRICA, FABRICA, SAIDA, LIMITE)
    assert pedido.impossiveis == []
    assert pedido.corpo["jobs"][0]["time_windows"] == [[36000, 36000]]


def test_sem_jobs_nao_ha_pedido():
    assert pedido_otimizacao([], FABRICA, FABRICA, SAIDA, LIMITE) == PedidoOtimizacao(None, {}, [])


def test_so_com_impossiveis_nao_ha_pedido():
    paragens = [_pc("a", servico_s=900, janelas_s=[(36000, 36600)]), _pc("b", servico_s=900, janelas_s=[(40000, 40001)])]
    assert pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE) == PedidoOtimizacao(None, {}, ["a", "b"])


def test_o_corpo_e_json_sem_nan_e_so_com_inteiros_nos_segundos_e_nos_ids():
    paragens = [_pc("a", servico_s=600, janelas_s=[(36000, 46800)]), _pc("b")]
    corpo = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE).corpo
    json.dumps(corpo, allow_nan=False)
    for job in corpo["jobs"]:
        assert type(job["id"]) is int and type(job["service"]) is int and type(job["priority"]) is int
        for janela in job.get("time_windows", []):
            assert all(type(x) is int for x in janela)
    assert all(type(x) is int for x in corpo["vehicles"][0]["time_window"])
    assert type(corpo["vehicles"][0]["id"]) is int


def test_pedido_otimizacao_nao_muda_as_paragens_e_devolve_listas_novas():
    janelas = [(36000, 46800)]
    paragens = [_pc("a", janelas_s=janelas)]
    copia = copy.deepcopy(paragens)
    primeiro = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE)
    segundo = pedido_otimizacao(paragens, FABRICA, FABRICA, SAIDA, LIMITE)
    assert paragens == copia
    assert primeiro == segundo
    assert primeiro.corpo["jobs"][0]["time_windows"] is not segundo.corpo["jobs"][0]["time_windows"]
    assert primeiro.corpo["jobs"][0]["time_windows"] is not janelas


@pytest.mark.parametrize(
    "saida, limite",
    [(28800.0, LIMITE), (True, LIMITE), ("08:00", LIMITE), (None, LIMITE), (-1, LIMITE),
     (SAIDA, SAIDA), (LIMITE, SAIDA), (SAIDA, 86400), (SAIDA, 68400.0)],
)
def test_pedido_otimizacao_recusa_horas_do_veiculo_que_nao_sao_segundos_do_dia(saida, limite):
    with pytest.raises(ValueError):
        pedido_otimizacao([_pc("a")], FABRICA, FABRICA, saida, limite)


@pytest.mark.parametrize(
    "ponto",
    [None, (38.7,), (38.7, -9.1, 0), ("38.7", "-9.1"), (math.nan, -9.1), (38.7, math.inf), (True, -9.1),
     {"lat": 38.7, "lng": -9.1}, "38.7,-9.1"],
)
def test_pedido_otimizacao_recusa_um_inicio_ou_fim_que_nao_e_um_par_lat_lng(ponto):
    with pytest.raises(ValueError):
        pedido_otimizacao([_pc("a")], ponto, FABRICA, SAIDA, LIMITE)
    with pytest.raises(ValueError):
        pedido_otimizacao([_pc("a")], FABRICA, ponto, SAIDA, LIMITE)


@pytest.mark.parametrize("ponto", [(math.nan, -9.1), (38.7, math.inf), (True, -9.1), ("38.7", -9.1)])
def test_pedido_otimizacao_recusa_paragens_com_coordenadas_estragadas(ponto):
    with pytest.raises(ValueError):
        pedido_otimizacao([_pc("a", ponto)], FABRICA, FABRICA, SAIDA, LIMITE)


def test_pedido_otimizacao_recusa_paragens_repetidas():
    with pytest.raises(ValueError):
        pedido_otimizacao([_pc("a"), _pc("b"), _pc("a")], FABRICA, FABRICA, SAIDA, LIMITE)


def test_pedido_otimizacao_so_aceita_paragens_de_calculo():
    with pytest.raises(TypeError):
        pedido_otimizacao([{"id": "a", "lat": 38.7, "lng": -9.1}], FABRICA, FABRICA, SAIDA, LIMITE)


# --- Sem dados pessoais (canários) -----------------------------------------------------------------

MEMBRO = "0b5b0b8e-2f2a-4c55-9e0e-8f1c1d2e3f40"
REGIAO = "7d3c2b1a-9e8f-4a6b-8c5d-3e2f1a0b9c8d"
PARAGENS_IDS = (
    "5a1e6c7d-8b9f-4e0a-9b1c-2d3e4f5a6b7c",
    "6b2f7d8e-9c0a-4f1b-ac2d-3e4f5a6b7c8d",
    "7c3a8e9f-0d1b-4a2c-bd3e-4f5a6b7c8d9e",
)
CANARIOS_TEXTO = ("CANARIO-NOME", "+351912345678", "912345678", "Rua CANARIO", "CANARIO-PESSOA", "CANARIO-NOTAS", "CANARIOLANDIA", "1100-148")


def _loja_completa(numero, lat, lng, janelas):
    dados, erros = validador_loja.criacao(
        {
            "nome": f"CANARIO-NOME {numero}",
            "fase": "contactada",
            "regiao_id": REGIAO,
            "morada": "Rua CANARIO, 12",
            "codigo_postal": "1100-148",
            "localidade": "CANARIOLANDIA",
            "lat": lat,
            "lng": lng,
            "origem_coords": "pin_manual",
            "telefone": "+351912345678",
            "pessoa_contacto": "CANARIO-PESSOA",
            "notas": "CANARIO-NOTAS: ligar antes",
            **janelas,
            "dias_fechada": ["dom"],
        }
    )
    assert erros == {}
    return formatar.documento_loja(dados, MEMBRO, datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc))


def _paragem_completa(id_, loja, motivo, tempo, ordem):
    return {
        "id": id_, "loja_id": loja["id"], "ordem": ordem, "motivo": motivo, "tempo_servico_min": tempo,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-11T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None,
    }


def _cenario_completo():
    lojas = [
        _loja_completa(1, 38.7075, -9.1364, {"janela1_inicio": "09:00", "janela1_fim": "12:00"}),
        _loja_completa(2, 38.7253, -9.15, {}),
        _loja_completa(3, 38.6916, -9.216, {"janela1_inicio": "10:00", "janela1_fim": "13:00",
                                            "janela2_inicio": "15:00", "janela2_fim": "19:00"}),
        _loja_completa(4, 38.7, -9.2, {"janela1_inicio": "10:00", "janela1_fim": "10:05"}),  # impossível
    ]
    paragens = [
        _paragem_completa(PARAGENS_IDS[0], lojas[0], "entrega", 10, 0),
        _paragem_completa(PARAGENS_IDS[1], lojas[1], "amostra", 10, 1),
        _paragem_completa(PARAGENS_IDS[2], lojas[2], "acompanhamento", 15, 2),
        _paragem_completa("8d4b9f0a-1e2c-4b3d-8e4f-5a6b7c8d9e0f", lojas[3], "angariacao", 15, 3),
    ]
    return lojas, paragens


def _folhas(valor):
    if isinstance(valor, dict):
        for dentro in valor.values():
            yield from _folhas(dentro)
    elif isinstance(valor, list):
        for dentro in valor:
            yield from _folhas(dentro)
    else:
        yield valor


CHAVES_TOPO = {"jobs", "vehicles"}
CHAVES_JOB = {"id", "location", "service", "time_windows", "priority"}
CHAVES_JOB_OBRIGATORIAS = {"id", "location", "service", "priority"}
CHAVES_VEICULO = {"id", "profile", "start", "end", "time_window"}


def _so_numeros_e_chaves_conhecidas(corpo):
    """A lista branca recursiva das chaves e dos valores do pedido ao VROOM."""
    assert set(corpo) == CHAVES_TOPO
    assert isinstance(corpo["jobs"], list) and isinstance(corpo["vehicles"], list)
    for job in corpo["jobs"]:
        assert CHAVES_JOB_OBRIGATORIAS <= set(job) <= CHAVES_JOB
    assert len(corpo["vehicles"]) == 1
    assert set(corpo["vehicles"][0]) == CHAVES_VEICULO
    textos = [folha for folha in _folhas(corpo) if isinstance(folha, str)]
    assert textos == ["driving-car"]
    outros = [folha for folha in _folhas(corpo) if not isinstance(folha, str)]
    assert all(type(folha) in (int, float) and math.isfinite(folha) for folha in outros)


def test_o_pedido_nao_leva_nomes_telefones_moradas_nem_uuids():
    lojas, paragens = _cenario_completo()
    calculo = [paragem_calculo(p, l) for p, l in zip(paragens, lojas)]
    pedido = pedido_otimizacao(calculo, FABRICA, (38.71, -9.14), SAIDA, LIMITE)
    texto = json.dumps(pedido.corpo, allow_nan=False, ensure_ascii=False)

    proibidos = [*CANARIOS_TEXTO, MEMBRO, REGIAO, *(l["id"] for l in lojas), *(p["id"] for p in paragens), "2026-10"]
    assert [canario for canario in proibidos if canario in texto] == []
    assert [canario for canario in proibidos if canario.lower() in texto.lower()] == []
    _so_numeros_e_chaves_conhecidas(pedido.corpo)
    assert len(pedido.corpo["jobs"]) == 3
    assert pedido.impossiveis == [paragens[3]["id"]]


def test_a_lista_branca_apanha_um_texto_ou_uma_chave_a_mais():
    """Os verificadores do teste dos canários rebentam com o que devem (meta-teste)."""
    corpo = pedido_otimizacao([_pc("a")], FABRICA, FABRICA, SAIDA, LIMITE).corpo
    _so_numeros_e_chaves_conhecidas(corpo)
    estragados = [
        {**corpo, "extra": 1},
        {**corpo, "jobs": [{**corpo["jobs"][0], "description": "Café X"}]},
        {**corpo, "jobs": [{**corpo["jobs"][0], "id": "a"}]},
        {**corpo, "jobs": [{**corpo["jobs"][0], "priority": True}]},
        {**corpo, "vehicles": [{**corpo["vehicles"][0], "description": "carrinha"}]},
        {**corpo, "vehicles": [{**corpo["vehicles"][0], "start": [math.nan, 38.7]}]},
    ]
    for estragado in estragados:
        with pytest.raises(AssertionError):
            _so_numeros_e_chaves_conhecidas(estragado)


# --- interpretar_otimizacao -----------------------------------------------------------------------

POR_JOB = {1: "p1", 2: "p2", 3: "p3"}


def _passo(tipo, numero=None, **mais):
    passo = {"type": tipo, "location": [-9.1, 38.7], "arrival": 30000, "service": 600, "waiting_time": 0}
    if numero is not None:
        passo.update({"id": numero, "job": numero})
    return {**passo, **mais}


def _resposta(passos=None, nao_atribuidos=(), **mais):
    if passos is None:
        passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("job", 3), _passo("end")]
    return {
        "code": 0,
        "summary": {"cost": 1, "routes": 1, "unassigned": len(nao_atribuidos)},
        "unassigned": [{"id": n, "type": "job", "location": [-9.2, 38.69]} for n in nao_atribuidos],
        "routes": [{"vehicle": 1, "cost": 1, "steps": passos}],
        **mais,
    }


def test_le_a_ordem_dos_jobs_pelos_passos():
    assert interpretar_otimizacao(_resposta(), POR_JOB) == (["p2", "p1", "p3"], [])


def test_le_os_nao_atribuidos():
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("end")]
    assert interpretar_otimizacao(_resposta(passos, [3]), POR_JOB) == (["p2", "p1"], ["p3"])


def test_os_nao_atribuidos_vem_pela_ordem_do_pedido():
    passos = [_passo("start"), _passo("job", 2), _passo("end")]
    assert interpretar_otimizacao(_resposta(passos, [3, 1]), POR_JOB) == (["p2"], ["p1", "p3"])


def test_sem_rotas_quando_nenhum_job_cabe():
    """Correção "T3.6 / T3.22": o VROOM responde `code: 0`, `routes: []` e todos em `unassigned`."""
    resposta = {"code": 0, "summary": {"routes": 0, "unassigned": 3}, "routes": [],
                "unassigned": [{"id": 2, "type": "job", "location": [-9.1, 38.7]},
                               {"id": 1, "type": "job", "location": [-9.1, 38.7]},
                               {"id": 3, "type": "job", "location": [-9.1, 38.7]}]}
    assert interpretar_otimizacao(resposta, POR_JOB) == ([], ["p1", "p2", "p3"])


def test_uma_rota_so_com_o_inicio_e_o_fim():
    passos = [_passo("start"), _passo("end")]
    assert interpretar_otimizacao(_resposta(passos, [1, 2, 3]), POR_JOB) == ([], ["p1", "p2", "p3"])


def test_um_so_job():
    resposta = _resposta([_passo("start"), _passo("job", 1), _passo("end")])
    assert interpretar_otimizacao(resposta, {1: "x"}) == (["x"], [])


def test_le_o_id_do_passo():
    passos = [_passo("start"), {"type": "job", "id": 2}, {"type": "job", "id": 1}, {"type": "job", "id": 3}, _passo("end")]
    assert interpretar_otimizacao(_resposta(passos), POR_JOB) == (["p2", "p1", "p3"], [])


def test_sem_id_le_a_chave_antiga_job():
    """Correção "T3.6": o `job` só conta quando falta o `id`."""
    passos = [_passo("start"), {"type": "job", "job": 2}, {"type": "job", "job": 1}, {"type": "job", "id": 3}, _passo("end")]
    assert interpretar_otimizacao(_resposta(passos), POR_JOB) == (["p2", "p1", "p3"], [])


@pytest.mark.parametrize("job", [1, 3, True, "2", 2.0, None])
def test_o_id_e_o_job_diferentes_sao_invalidos(job):
    passos = [_passo("start"), {"type": "job", "id": 2, "job": job}, _passo("job", 1), _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_o_id_e_o_job_trocados_entre_passos_sao_invalidos():
    """Lidos só pelo `id` ou só pelo `job`, os dois dão uma ordem válida
    (2, 1, 3 ou 1, 2, 3): só a comparação dos dois apanha a resposta estragada."""
    passos = [_passo("start"), {"type": "job", "id": 2, "job": 1}, {"type": "job", "id": 1, "job": 2},
              _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_um_passo_de_job_sem_id_nem_job_e_invalido():
    passos = [_passo("start"), {"type": "job", "location": [-9.1, 38.7]}, _passo("job", 1), _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_os_passos_de_inicio_e_fim_ignoram_se_mesmo_com_ids():
    passos = [{"type": "start", "id": 99}, _passo("job", 2), _passo("job", 1), _passo("job", 3), {"type": "end", "job": 2}]
    assert interpretar_otimizacao(_resposta(passos), POR_JOB) == (["p2", "p1", "p3"], [])


@pytest.mark.parametrize("tipo", ["break", "pickup", "delivery", "shipment", "JOB", "", None, 1, ["job"]])
def test_um_passo_de_outro_tipo_e_invalido(tipo):
    passos = [_passo("start"), _passo("job", 2), {"type": tipo, "id": 9}, _passo("job", 1), _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_um_passo_sem_tipo_e_invalido():
    passos = [_passo("start"), {"id": 2, "job": 2}, _passo("job", 1), _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


@pytest.mark.parametrize("resposta", [None, [], "ok", 0, True, [{"code": 0}]])
def test_uma_resposta_que_nao_e_um_objeto_e_invalida(resposta):
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


@pytest.mark.parametrize("code", [1, 2, 3, -1, "0", 0.0, False, None])
def test_um_code_diferente_de_0_e_invalido(code):
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(code=code), POR_JOB)


def test_sem_code_e_invalido():
    resposta = _resposta()
    del resposta["code"]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


@pytest.mark.parametrize("rotas", [None, {}, "[]", 0, {"0": {}}])
def test_rotas_que_nao_sao_uma_lista_sao_invalidas(rotas):
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(routes=rotas), POR_JOB)


def test_sem_rotas_e_invalido():
    resposta = _resposta()
    del resposta["routes"]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


def test_mais_de_uma_rota_e_invalido():
    resposta = _resposta()
    rotas = [{"vehicle": 1, "steps": [_passo("job", 2), _passo("job", 1)]}, {"vehicle": 1, "steps": [_passo("job", 3)]}]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao({**resposta, "routes": rotas}, POR_JOB)


@pytest.mark.parametrize("rota", [None, [], "rota", 1])
def test_uma_rota_que_nao_e_um_objeto_e_invalida(rota):
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(routes=[rota]), POR_JOB)


@pytest.mark.parametrize("veiculo", [2, 0, True, "1", 1.0, None])
def test_uma_rota_de_outro_veiculo_e_invalida(veiculo):
    resposta = _resposta()
    resposta["routes"][0]["vehicle"] = veiculo
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


def test_uma_rota_sem_veiculo_e_invalida():
    resposta = _resposta()
    del resposta["routes"][0]["vehicle"]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


@pytest.mark.parametrize("passos", [None, {}, "start", 3])
def test_passos_que_nao_sao_uma_lista_sao_invalidos(passos):
    resposta = _resposta()
    resposta["routes"][0]["steps"] = passos
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


@pytest.mark.parametrize("passo", [None, "job", 2, ["job", 2]])
def test_um_passo_que_nao_e_um_objeto_e_invalido(passo):
    passos = [_passo("start"), passo, _passo("job", 2), _passo("job", 1), _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_um_job_desconhecido_e_invalido():
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("job", 3), _passo("job", 4), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_um_job_desconhecido_nos_nao_atribuidos_e_invalido():
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(nao_atribuidos=[7]), POR_JOB)


def test_um_job_repetido_nos_passos_e_invalido():
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("job", 2), _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_um_job_atribuido_e_nao_atribuido_e_invalido():
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(nao_atribuidos=[3]), POR_JOB)


def test_um_job_repetido_nos_nao_atribuidos_e_invalido():
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos, [3, 3]), POR_JOB)


@pytest.mark.parametrize("numero", [True, 1.0, "1", None, [1], -1, 0])
def test_um_job_com_um_id_que_nao_e_um_dos_inteiros_enviados_e_invalido(numero):
    """`True == 1` e `1.0 == 1` em Python (e têm o mesmo hash): sem verificar o
    tipo, o `True` apanhava o job 1 do `por_job`."""
    passos = [_passo("start"), _passo("job", 2), {"type": "job", "id": numero, "job": numero}, _passo("job", 3), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


@pytest.mark.parametrize("numero", [True, 3.0, "3"])
def test_um_nao_atribuido_com_um_id_que_nao_e_inteiro_e_invalido(numero):
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("end")]
    resposta = _resposta(passos)
    resposta["unassigned"] = [{"id": numero, "type": "job"}]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


def test_um_job_enviado_em_falta_e_invalido():
    """Atribuídos ∪ não atribuídos tem de ser exatamente o que se enviou."""
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("end")]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(passos), POR_JOB)


def test_sem_rotas_e_sem_todos_nos_nao_atribuidos_e_invalido():
    resposta = {"code": 0, "routes": [], "unassigned": [{"id": 1, "type": "job"}, {"id": 2, "type": "job"}]}
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


@pytest.mark.parametrize("nao_atribuidos", [None, {}, "3", 3])
def test_nao_atribuidos_que_nao_sao_uma_lista_sao_invalidos(nao_atribuidos):
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(_resposta(unassigned=nao_atribuidos), POR_JOB)


def test_sem_a_lista_dos_nao_atribuidos_e_invalido():
    resposta = _resposta()
    del resposta["unassigned"]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


@pytest.mark.parametrize("item", [None, 3, "3", [3], {"type": "job"}, {"id": 3, "type": "shipment"}, {"id": 3, "type": "break"}])
def test_um_nao_atribuido_que_nao_e_um_job_e_invalido(item):
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("end")]
    resposta = _resposta(passos)
    resposta["unassigned"] = [item]
    with pytest.raises(RespostaInvalida):
        interpretar_otimizacao(resposta, POR_JOB)


def test_um_nao_atribuido_sem_tipo_le_se_pelo_id():
    passos = [_passo("start"), _passo("job", 2), _passo("job", 1), _passo("end")]
    resposta = _resposta(passos)
    resposta["unassigned"] = [{"id": 3}]
    assert interpretar_otimizacao(resposta, POR_JOB) == (["p2", "p1"], ["p3"])


def test_as_chaves_desconhecidas_da_resposta_ignoram_se():
    resposta = {**_resposta(), "_origem": "manual — regravar", "metadata": {"service": "optimization"}}
    resposta["routes"][0]["geometry"] = "abc"
    assert interpretar_otimizacao(resposta, POR_JOB) == (["p2", "p1", "p3"], [])


def test_interpretar_nao_muda_a_resposta_e_devolve_listas_novas():
    resposta = _resposta(nao_atribuidos=[])
    copia = copy.deepcopy(resposta)
    primeira = interpretar_otimizacao(resposta, POR_JOB)
    segunda = interpretar_otimizacao(resposta, POR_JOB)
    assert resposta == copia
    assert primeira == segunda
    assert primeira[0] is not segunda[0] and primeira[1] is not segunda[1]


def test_a_resposta_invalida_traz_o_motivo_sem_nada_da_resposta():
    """O motivo vai para os registos (T3.21/T3.22): só textos fixos, sem
    coordenadas nem o que o ORS mandou."""
    estragadas = [
        {"code": "CANARIO", "routes": []},
        _resposta(passos=[{"type": "CANARIO-TIPO", "location": [-9.123456, 38.654321]}]),
        _resposta(passos=[{"type": "job", "id": "CANARIO-ID"}]),
        _resposta(passos=[{"type": "job", "id": 1, "job": "CANARIO-JOB"}]),
        _resposta(unassigned=[{"id": "CANARIO-ID", "location": [-9.123456, 38.654321]}]),
        {**_resposta(), "routes": [{"vehicle": "CANARIO-VEICULO", "steps": []}]},
    ]
    for resposta in estragadas:
        with pytest.raises(RespostaInvalida) as erro:
            interpretar_otimizacao(resposta, POR_JOB)
        motivo = erro.value.motivo
        assert isinstance(motivo, str) and motivo
        assert str(erro.value) == motivo
        assert "CANARIO" not in motivo and "38.65" not in motivo and "-9.12" not in motivo
        assert erro.value.__cause__ is None


def test_resposta_invalida_e_uma_excecao_com_o_motivo():
    erro = RespostaInvalida("a otimização deixou de fora um job enviado")
    assert isinstance(erro, Exception)
    assert erro.motivo == "a otimização deixou de fora um job enviado"
    assert str(erro) == erro.motivo


# --- As fixtures (forma e conjuntos; o dono vai regravá-las, T3.12) ---------------------------------


def test_cenarios_so_com_os_pontos_publicos_de_lisboa():
    cenarios = _ler("cenarios.json")
    assert cenarios["_origem"].startswith("manual")
    assert cenarios["pontos"] == {
        "fabrica": {"lat": 38.7223, "lng": -9.1393},
        "praca_do_comercio": {"lat": 38.7075, "lng": -9.1364},
        "marques_de_pombal": {"lat": 38.7253, "lng": -9.15},
        "torre_de_belem": {"lat": 38.6916, "lng": -9.216},
    }
    assert set(cenarios["otimizacao"]) == {"otimizacao-todas", "otimizacao-uma-nao-cabe"}


def _pedido_do_cenario(nome):
    """O pedido de um cenário, como o gravador (T3.12) o monta: a paragem é o nome do ponto."""
    cenarios = _ler("cenarios.json")
    pontos = cenarios["pontos"]
    cenario = cenarios["otimizacao"][nome]
    calculo = [
        paragem_calculo(
            {"id": p["ponto"], "motivo": p["motivo"], "tempo_servico_min": p["tempo_servico_min"]},
            {**pontos[p["ponto"]], "janelas": p["janelas"]},
        )
        for p in cenario["paragens"]
    ]
    inicio, fim = (pontos[cenario[c]] for c in ("inicio", "fim"))
    return pedido_otimizacao(
        calculo, (inicio["lat"], inicio["lng"]), (fim["lat"], fim["lng"]),
        horas.segundos(cenario["saida"]), horas.segundos(cenario["limite"]),
    )


@pytest.mark.parametrize("nome", ["otimizacao-todas", "otimizacao-uma-nao-cabe"])
def test_os_pedidos_dos_cenarios_so_levam_numeros(nome):
    pedido = _pedido_do_cenario(nome)
    _so_numeros_e_chaves_conhecidas(pedido.corpo)
    assert pedido.impossiveis == []
    assert len(pedido.corpo["jobs"]) == 3
    texto = json.dumps(pedido.corpo, allow_nan=False)
    assert all(ponto not in texto for ponto in ("fabrica", "praca", "marques", "torre"))


@pytest.mark.parametrize("nome", ["otimizacao-todas", "otimizacao-uma-nao-cabe"])
def test_as_respostas_gravadas_leem_se_e_batem_certo_com_o_pedido(nome):
    resposta = _ler(f"{nome}.json")
    assert resposta["_origem"].startswith(("manual — regravar", "gravado em "))
    pedido = _pedido_do_cenario(nome)
    ordem, nao_atribuidas = interpretar_otimizacao(resposta, pedido.por_job)
    assert set(ordem).isdisjoint(nao_atribuidas)
    assert sorted(ordem + nao_atribuidas) == sorted(pedido.por_job.values())
    assert len(ordem) + len(nao_atribuidas) == len(pedido.por_job)


def test_no_cenario_todas_cabem_todas():
    pedido = _pedido_do_cenario("otimizacao-todas")
    ordem, nao_atribuidas = interpretar_otimizacao(_ler("otimizacao-todas.json"), pedido.por_job)
    assert nao_atribuidas == []
    assert set(ordem) == {"praca_do_comercio", "marques_de_pombal", "torre_de_belem"}


def test_no_cenario_uma_nao_cabe_fica_de_fora_a_torre_de_belem():
    pedido = _pedido_do_cenario("otimizacao-uma-nao-cabe")
    ordem, nao_atribuidas = interpretar_otimizacao(_ler("otimizacao-uma-nao-cabe.json"), pedido.por_job)
    assert nao_atribuidas == ["torre_de_belem"]
    assert set(ordem) == {"praca_do_comercio", "marques_de_pombal"}


def test_os_passos_dos_jobs_das_fixtures_trazem_o_id_e_o_job():
    """Correção "T3.6": o formato real do ORS (o `id` e a chave antiga `job`)."""
    for nome in ("otimizacao-todas.json", "otimizacao-uma-nao-cabe.json"):
        passos = _ler(nome)["routes"][0]["steps"]
        assert {p["type"] for p in passos} <= {"start", "job", "end"}
        for passo in passos:
            if passo["type"] == "job":
                assert passo["id"] == passo["job"]
            else:
                assert "id" not in passo and "job" not in passo


# --- O módulo -----------------------------------------------------------------------------------


def test_vroom_nunca_chama_o_round_do_python():
    """As coordenadas arredondam-se com `numeros.arredondar` (meio-para-longe-do-zero)."""
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []
