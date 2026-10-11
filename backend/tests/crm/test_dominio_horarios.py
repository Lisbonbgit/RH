"""As chegadas, as esperas e os avisos da rota, e a assinatura do cálculo
(crm/dominio/horarios.py), F3 / T3.8.

Plano F3 §1 ("Chegadas", "Horas"), a partir das durações dos troços do
Directions (`directions.Trocos.duracoes`):

- chegada = partida anterior + duração do troço;
- se chegar antes da janela, espera pela abertura (também pela 2.ª janela,
  sem aviso); o serviço tem de acabar dentro da janela (`início + serviço ≤
  fim`), mas as horas contam-se pelas janelas de receção, nunca pelas do
  VROOM (`[a, b − s]`) como se fossem de receção;
- `fora_de_horario` só quando nenhuma janela do dia leva o serviço, e aí
  serve-se à chegada, sem espera;
- o regresso previsto vem no fim, com o aviso se passar do limite;
- uma hora a partir das 24:00 fica `None`, com o aviso.

As horas contam-se em segundos desde a meia-noite local, a partir do texto
"HH:MM": a data da rota não entra (mudança de hora). `calculo.assinatura` é o
sha256 da entrada do cálculo (`entrada_calculo`), que diz se as horas
guardadas ainda servem: muda com tudo o que muda as horas e com nada mais
(nem o nome, o telefone, as notas ou o motivo com o mesmo serviço).

Os valores esperados escrevem-se à mão neste ficheiro (segundos por
`_s("HH:MM")`, sem o `horas.segundos`).
"""
import ast
import copy
import hashlib
import json
import math
import random
import re
from pathlib import Path

import pytest

import crm.dominio.horarios as horarios
from crm.dominio.directions import interpretar_direcoes
from crm.dominio.horarios import Horarios, assinatura, calcular_horarios, entrada_calculo
from crm.dominio.vroom import ParagemCalculo, paragem_calculo

from .test_dominio_vroom import CANARIOS_TEXTO, MEMBRO, REGIAO, _cenario_completo, _Lido

FIXTURES = Path(__file__).parent / "fixtures" / "ors"
FICHEIRO = Path(horarios.__file__)

FABRICA = (38.7223, -9.1393)
COMERCIO = (38.7075, -9.1364)
MARQUES = (38.7253, -9.15)
BELEM = (38.6916, -9.216)

P1 = "5a1e6c7d-8b9f-4e0a-9b1c-2d3e4f5a6b7c"
P2 = "6b2f7d8e-9c0a-4f1b-ac2d-3e4f5a6b7c8d"
P3 = "7c3a8e9f-0d1b-4a2c-bd3e-4f5a6b7c8d9e"


def _s(texto):
    """"HH:MM" → segundos, à mão (o teste não depende do `horas.segundos`)."""
    horas_, minutos = texto.split(":")
    return int(horas_) * 3600 + int(minutos) * 60


SAIDA = _s("08:00")
LIMITE = _s("19:00")
MANHA_E_TARDE = [(_s("10:00"), _s("13:00")), (_s("15:00"), _s("19:00"))]


def _pc(id_="a", servico_min=10, janelas=None, ponto=COMERCIO, motivo="amostra"):
    return ParagemCalculo(id_, ponto[0], ponto[1], servico_min * 60, janelas, motivo)


def _uma(chegada, servico_min=10, janelas=None, regresso_s=600, limite=LIMITE):
    """Uma só paragem a que se chega à hora `chegada` ("HH:MM" ou segundos), saindo às 08:00."""
    chegada_s = _s(chegada) if isinstance(chegada, str) else chegada
    return calcular_horarios(SAIDA, limite, [_pc("a", servico_min, janelas)], [chegada_s - SAIDA, regresso_s])


def _linha(chegada, espera, fora=False):
    return {"chegada_prevista": chegada, "espera_min": espera, "fora_de_horario": fora}


# --- calcular_horarios: os cenários do plano ------------------------------------------------------


def test_os_campos_dos_horarios():
    assert Horarios._fields == ("por_paragem", "regresso_s", "regresso_previsto", "depois_do_limite")


def test_cenario_1_sem_janelas_chega_e_segue():
    """Troços [1800, 900, 1200] e serviços de 10 min: 08:30, 08:55, regresso 09:25."""
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("b")], [1800, 900, 1200])
    assert resultado == Horarios(
        por_paragem={"a": _linha("08:30", 0), "b": _linha("08:55", 0)},
        regresso_s=float(_s("09:25")),
        regresso_previsto="09:25",
        depois_do_limite=False,
    )


def test_a_ordem_e_as_chaves_de_cada_paragem():
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("b"), _pc("a"), _pc("c")], [60, 60, 60, 60])
    assert list(resultado.por_paragem) == ["b", "a", "c"]
    for linha in resultado.por_paragem.values():
        assert list(linha) == ["chegada_prevista", "espera_min", "fora_de_horario"]
        assert type(linha["chegada_prevista"]) is str
        assert type(linha["espera_min"]) is int
        assert type(linha["fora_de_horario"]) is bool
    assert type(resultado.regresso_s) is float
    assert type(resultado.depois_do_limite) is bool


def test_cenario_2_chega_antes_da_janela_e_espera_pela_abertura():
    """Janela 10:00–13:00 e chegada às 09:10: espera 50 e serve das 10:00 às 10:10."""
    resultado = _uma("09:10", janelas=[(_s("10:00"), _s("13:00"))], regresso_s=1200)
    assert resultado.por_paragem == {"a": _linha("09:10", 50)}
    assert resultado.regresso_previsto == "10:30"


def test_a_espera_atrasa_as_paragens_seguintes():
    resultado = calcular_horarios(
        SAIDA, LIMITE, [_pc("a", 10, [(_s("10:00"), _s("13:00"))]), _pc("b", 15)], [_s("09:10") - SAIDA, 600, 900]
    )
    assert resultado.por_paragem == {"a": _linha("09:10", 50), "b": _linha("10:20", 0)}
    assert resultado.regresso_previsto == "10:50"


def test_cenario_3_entre_as_duas_janelas_espera_pela_segunda_sem_aviso():
    """Duas janelas (10–13, 15–19) e chegada às 13:10: espera 110, sem aviso."""
    resultado = _uma("13:10", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("13:10", 110)}
    assert resultado.regresso_previsto == "15:20"


def test_cenario_4_o_servico_nao_cabe_no_fim_da_primeira_e_espera_pela_segunda():
    """Chegada às 12:55 com 10 min: 13:05 > 13:00, por isso espera pela 2.ª (125 min)."""
    resultado = _uma("12:55", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("12:55", 125)}
    assert resultado.regresso_previsto == "15:20"


def test_cenario_5_o_servico_que_acaba_no_fecho_ainda_cabe():
    """Chegada às 12:50 com 10 min: cabe (13:00 ≤ 13:00)."""
    resultado = _uma("12:50", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("12:50", 0)}
    assert resultado.regresso_previsto == "13:10"


def test_um_segundo_depois_ja_nao_cabe_na_primeira():
    resultado = _uma(_s("12:50") + 1, janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("12:50", 130)}
    assert resultado.regresso_previsto == "15:20"


def test_cenario_6_depois_da_ultima_janela_fica_fora_de_horario_e_serve_se_a_chegada():
    """Chegada às 19:00 com as janelas a acabar às 19:00: fora de horário, espera 0."""
    resultado = _uma("19:00", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("19:00", 0, fora=True)}
    assert resultado.regresso_previsto == "19:20"


def test_fora_de_horario_serve_se_a_chegada_mesmo_antes_da_abertura():
    """Uma janela mais curta do que o serviço nunca o leva: não se espera por ela."""
    resultado = calcular_horarios(
        SAIDA, LIMITE, [_pc("a", 10, [(_s("10:00"), _s("10:05"))]), _pc("b")], [_s("09:00") - SAIDA, 600, 600]
    )
    assert resultado.por_paragem == {"a": _linha("09:00", 0, fora=True), "b": _linha("09:20", 0)}


def test_dentro_da_janela_nao_espera():
    resultado = _uma("10:30", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("10:30", 0)}


def test_a_chegar_antes_da_primeira_espera_pela_primeira():
    resultado = _uma("09:00", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("09:00", 60)}


def test_a_chegar_na_abertura_nao_espera():
    resultado = _uma("15:00", janelas=MANHA_E_TARDE)
    assert resultado.por_paragem == {"a": _linha("15:00", 0)}


def test_espera_pela_janela_mais_cedo_mesmo_com_as_janelas_fora_de_ordem():
    resultado = _uma("09:00", janelas=list(reversed(MANHA_E_TARDE)))
    assert resultado.por_paragem == {"a": _linha("09:00", 60)}


def test_sem_janelas_nunca_espera_nem_fica_fora_de_horario():
    for chegada in ("08:10", "13:10", "22:00", "23:59"):
        assert _uma(chegada, janelas=None).por_paragem == {"a": _linha(chegada, 0)}


def test_o_servico_de_cada_paragem_conta():
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a", 1), _pc("b", 240)], [600, 600, 600])
    assert resultado.por_paragem == {"a": _linha("08:10", 0), "b": _linha("08:21", 0)}
    assert resultado.regresso_previsto == "12:31"


def test_cenario_7_o_regresso_depois_do_limite():
    """Regresso às 19:40 com o limite às 19:00."""
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [_s("18:00") - SAIDA, 90 * 60])
    assert resultado.regresso_previsto == "19:40"
    assert resultado.regresso_s == float(_s("19:40"))
    assert resultado.depois_do_limite is True


def test_o_regresso_a_hora_limite_nao_passa_do_limite():
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [_s("18:00") - SAIDA, 50 * 60])
    assert (resultado.regresso_previsto, resultado.depois_do_limite) == ("19:00", False)


def test_o_limite_conta_pelo_minuto_mostrado():
    """19:00:20 mostra-se "19:00" e não passa do limite; 19:00:30 já é "19:01"."""
    vinte = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [_s("18:00") - SAIDA, 50 * 60 + 20])
    trinta = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [_s("18:00") - SAIDA, 50 * 60 + 30])
    assert (vinte.regresso_previsto, vinte.depois_do_limite) == ("19:00", False)
    assert (trinta.regresso_previsto, trinta.depois_do_limite) == ("19:01", True)


def test_o_limite_e_o_que_vem_no_pedido():
    resultado = calcular_horarios(SAIDA, _s("09:00"), [_pc("a")], [1800, 1800])
    assert (resultado.regresso_previsto, resultado.depois_do_limite) == ("09:10", True)
    resultado = calcular_horarios(SAIDA, _s("09:10"), [_pc("a")], [1800, 1800])
    assert (resultado.regresso_previsto, resultado.depois_do_limite) == ("09:10", False)


def test_cenario_8_uma_chegada_depois_das_24h_fica_sem_hora_e_com_aviso():
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("b", janelas=MANHA_E_TARDE)], [_s("23:50") - SAIDA, 1200, 600])
    assert resultado.por_paragem == {"a": _linha("23:50", 0), "b": _linha(None, 0, fora=True)}
    assert resultado.regresso_previsto is None
    assert resultado.depois_do_limite is True
    assert resultado.regresso_s == float(_s("23:50") + 600 + 1200 + 600 + 600)


def test_depois_das_24h_tambem_sem_janelas_fica_fora_de_horario():
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("b")], [_s("23:55") - SAIDA, 3600, 600])
    assert resultado.por_paragem == {"a": _linha("23:55", 0), "b": _linha(None, 0, fora=True)}
    assert (resultado.regresso_previsto, resultado.depois_do_limite) == (None, True)


def test_as_24h_contam_depois_de_arredondar_ao_minuto():
    """86 369 s ainda é "23:59"; 86 370 s arredonda para as 24:00 e fica sem hora."""
    assert _uma(86369).por_paragem == {"a": _linha("23:59", 0)}
    assert _uma(86370).por_paragem == {"a": _linha(None, 0, fora=True)}


def test_so_o_regresso_depois_das_24h():
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [_s("23:00") - SAIDA, 3600])
    assert resultado.por_paragem == {"a": _linha("23:00", 0)}
    assert (resultado.regresso_previsto, resultado.depois_do_limite) == (None, True)


@pytest.mark.parametrize("troco, hora", [(1830, "08:31"), (1764, "08:29"), (1770, "08:30"), (1829, "08:30"), (90, "08:02")])
def test_cenario_9_o_minuto_arredonda_meio_para_longe_do_zero(troco, hora):
    """30,5 min depois das 08:00 → "08:31" (o `round` dava "08:30"); 29,4 → "08:29"."""
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [troco, 0])
    assert resultado.por_paragem["a"]["chegada_prevista"] == hora


@pytest.mark.parametrize("chegada_s, hora, espera", [
    (_s("09:56") + 30, "09:57", 3),
    (_s("09:57") + 30, "09:58", 2),
    (_s("09:59") + 29, "09:59", 1),
    (_s("09:59") + 30, "10:00", 0),
    (_s("09:10") + 1, "09:10", 50),
])
def test_a_espera_e_a_diferenca_entre_os_minutos_mostrados(chegada_s, hora, espera):
    """A chegada mostrada mais a espera dá sempre a hora da abertura."""
    resultado = _uma(chegada_s, janelas=[(_s("10:00"), _s("13:00"))])
    assert resultado.por_paragem == {"a": _linha(hora, espera)}


def test_a_chegada_mostrada_mais_a_espera_da_a_abertura_em_qualquer_segundo():
    gerador = random.Random(20261011)
    for _ in range(2000):
        chegada = gerador.randint(_s("08:00"), _s("13:00")) + gerador.choice([0, 0.5, 0.25, 0.75])
        linha = _uma(chegada, janelas=[(_s("10:00"), _s("13:00"))], servico_min=1).por_paragem["a"]
        minuto = _s(linha["chegada_prevista"]) // 60
        if chegada < _s("10:00"):
            assert minuto + linha["espera_min"] == 600
        else:
            assert linha["espera_min"] == 0


@pytest.mark.parametrize("duracoes", [[1800, 600], [1800, 600, 600, 600], [], [1800]])
def test_cenario_10_um_troco_a_mais_ou_a_menos_e_um_erro(duracoes):
    with pytest.raises(ValueError):
        calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("b")], duracoes)


def test_sem_paragens_e_so_a_ida_e_volta():
    resultado = calcular_horarios(SAIDA, LIMITE, [], [1800])
    assert resultado == Horarios({}, float(_s("08:30")), "08:30", False)


# --- calcular_horarios: as contas sem o erro do float ------------------------------------------------


def test_o_regresso_soma_os_trocos_sem_o_erro_do_float():
    """982,3 + 600 + 814,1 + 600 + 93,6 depois das 08:00 dá 08:51:30 certinho → "08:52".

    Somados em float davam 31 889,999… s → "08:51".
    """
    assert 28800 + 982.3 + 600 + 814.1 + 600 + 93.6 < 31890  # a armadilha existe
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("b")], [982.3, 814.1, 93.6])
    assert resultado.regresso_s == 31890.0
    assert resultado.regresso_previsto == "08:52"


def test_o_servico_que_acaba_no_fecho_cabe_mesmo_depois_de_somar_decimais():
    """A 3.ª paragem chega às 09:40 certinho (em float, 09:40:00,000…01) e o serviço de 10 min
    acaba às 09:50, no fecho da janela: cabe."""
    assert 28800 + 2836.9 + 600 + 1834.3 + 600 + 128.8 > 34800  # a armadilha existe
    paragens = [_pc("a"), _pc("b"), _pc("c", 10, [(_s("09:00"), _s("09:50"))])]
    resultado = calcular_horarios(SAIDA, LIMITE, paragens, [2836.9, 1834.3, 128.8, 600])
    assert resultado.por_paragem["c"] == _linha("09:40", 0)


def test_os_trocos_do_directions_com_um_ponto_repetido():
    """Correção "T3.7 (+ T3.13, T3.21)": duas lojas nas mesmas coordenadas — o troço
    entre elas vem sem duração (0): as chegadas seguem-se, sem espera."""
    resposta = json.loads((FIXTURES / "direcoes-ponto-repetido.json").read_text(encoding="utf-8"))
    trocos = interpretar_direcoes(resposta, 4)
    resultado = calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("b")], trocos.duracoes)
    assert resultado.por_paragem == {"a": _linha("08:06", 0), "b": _linha("08:16", 0)}
    assert resultado.regresso_previsto == "08:32"


def test_aceita_trocos_em_tuplo_e_inteiros_ou_decimais():
    a = calcular_horarios(SAIDA, LIMITE, (_pc("a"),), (1800, 600))
    b = calcular_horarios(SAIDA, LIMITE, [_pc("a")], [1800.0, 600.0])
    assert a == b


# --- calcular_horarios: o que recebe ------------------------------------------------------------


@pytest.mark.parametrize("valor", [True, 28800.0, "08:00", None, -1, 86400, 2**63])
def test_recusa_uma_saida_que_nao_e_segundos_do_dia(valor):
    with pytest.raises(ValueError):
        calcular_horarios(valor, LIMITE, [_pc("a")], [600, 600])


@pytest.mark.parametrize("valor", [True, 68400.0, "19:00", None, -1, 86400])
def test_recusa_um_limite_que_nao_e_segundos_do_dia(valor):
    with pytest.raises(ValueError):
        calcular_horarios(SAIDA, valor, [_pc("a")], [600, 600])


@pytest.mark.parametrize("troco", [-1, -0.5, math.nan, math.inf, True, "600", None, [600]])
def test_recusa_trocos_que_nao_sao_duracoes(troco):
    with pytest.raises(ValueError):
        calcular_horarios(SAIDA, LIMITE, [_pc("a")], [600, troco])


def test_recusa_paragens_e_trocos_que_nao_sao_listas():
    with pytest.raises(TypeError):
        calcular_horarios(SAIDA, LIMITE, (p for p in [_pc("a")]), [600, 600])
    with pytest.raises(TypeError):
        calcular_horarios(SAIDA, LIMITE, [_pc("a")], (d for d in [600, 600]))
    with pytest.raises(TypeError):
        calcular_horarios(SAIDA, LIMITE, [_pc("a")], "600")


def test_so_aceita_paragens_de_calculo():
    with pytest.raises(TypeError):
        calcular_horarios(SAIDA, LIMITE, [{"id": "a", "servico_s": 600, "janelas_s": None}], [600, 600])


def test_recusa_paragens_repetidas():
    with pytest.raises(ValueError):
        calcular_horarios(SAIDA, LIMITE, [_pc("a"), _pc("a")], [600, 600, 600])


@pytest.mark.parametrize("janelas", [[(36000.0, 46800)], [(36000,)], [("10:00", "13:00")], "36000", [(True, 46800)]])
def test_recusa_janelas_que_nao_sao_pares_de_segundos(janelas):
    with pytest.raises(ValueError):
        calcular_horarios(SAIDA, LIMITE, [_pc("a", janelas=janelas)], [600, 600])


@pytest.mark.parametrize("servico_s", [True, 600.0, -60, "600", None])
def test_recusa_um_servico_que_nao_e_segundos(servico_s):
    paragem = ParagemCalculo("a", COMERCIO[0], COMERCIO[1], servico_s, None, "amostra")
    with pytest.raises(ValueError):
        calcular_horarios(SAIDA, LIMITE, [paragem], [600, 600])


def test_nao_muda_o_que_recebe_e_devolve_estruturas_novas():
    paragens = [_pc("a", janelas=list(MANHA_E_TARDE)), _pc("b")]
    duracoes = [600.5, 700, 800]
    copias = copy.deepcopy((paragens, duracoes))
    um = calcular_horarios(SAIDA, LIMITE, paragens, duracoes)
    outro = calcular_horarios(SAIDA, LIMITE, paragens, duracoes)
    assert (paragens, duracoes) == copias
    assert um == outro
    assert um.por_paragem is not outro.por_paragem
    assert um.por_paragem["a"] is not outro.por_paragem["a"]


# --- Cenário 11: a mudança de hora (a data não entra) ----------------------------------------------


def _paragem(id_, motivo="amostra", tempo=10, **mais):
    return {
        "id": id_, "loja_id": "l-" + id_, "ordem": 0, "motivo": motivo, "tempo_servico_min": tempo,
        "manter_fechada": False, "nao_cabe": False, "chegada_prevista": None, "espera_min": None,
        "fora_de_horario": False, "adicionada_em": "2026-10-11T09:00:00Z", "adicionada_por": MEMBRO,
        "removida_em": None, "estado": "pendente", "resultado": None, "concluida_em": None, **mais,
    }


def _loja(ponto, janelas=(), **mais):
    return {
        "id": "loja", "nome": "Café A", "telefone": "+351911111111", "notas": "",
        "lat": ponto[0], "lng": ponto[1], "janelas": [dict(j) for j in janelas], **mais,
    }


def _rota(data="2026-10-12", hora_saida="08:00", hora_regresso_limite="19:00", evitar_portagens=False, **mais):
    return {
        "id": "rota", "data": data, "estado": "rascunho", "versao": 3, "hora_saida": hora_saida,
        "hora_regresso_limite": hora_regresso_limite, "inicio": None, "fim": None,
        "evitar_portagens": evitar_portagens, "paragens": [], "calculo": None, **mais,
    }


JANELAS_COMERCIO = [{"inicio": "10:00", "fim": "13:00"}, {"inicio": "15:00", "fim": "19:00"}]


def _incluidas():
    return [
        (_paragem(P1, "entrega", 10), _loja(COMERCIO, JANELAS_COMERCIO)),
        (_paragem(P2, "acompanhamento", 15), _loja(MARQUES)),
    ]


@pytest.mark.parametrize("hora_saida, hora_regresso_limite", [("00:30", "03:30"), ("01:30", "05:00"), ("08:00", "19:00")])
def test_cenario_11_a_mudanca_de_hora_nao_mexe_nas_horas(hora_saida, hora_regresso_limite):
    """A 2026-03-29 (01:00 → 02:00 em Lisboa), a 2026-10-25 (02:00 → 01:00) e a 2026-10-24
    a entrada e as horas são as mesmas: contam-se pelo texto do relógio."""
    entradas, assinaturas, resultados = [], [], []
    for data in ("2026-03-29", "2026-10-25", "2026-10-24"):
        rota = _rota(data, hora_saida, hora_regresso_limite)
        incluidas = [(_paragem(P1), _loja(COMERCIO)), (_paragem(P2), _loja(MARQUES))]
        entrada = entrada_calculo(rota, incluidas, FABRICA, FABRICA)
        entradas.append(entrada)
        assinaturas.append(assinatura(entrada))
        calculo = [paragem_calculo(p, l) for p, l in incluidas]
        resultados.append(calcular_horarios(_s(rota["hora_saida"]), _s(rota["hora_regresso_limite"]), calculo, [1800, 1800, 1800]))
    assert entradas[0] == entradas[1] == entradas[2]
    assert len(set(assinaturas)) == 1
    assert resultados[0] == resultados[1] == resultados[2]
    saida = _s(hora_saida)
    assert resultados[0].por_paragem[P1]["chegada_prevista"] == _hora(saida + 1800)
    assert resultados[0].por_paragem[P2]["chegada_prevista"] == _hora(saida + 1800 + 600 + 1800)
    assert resultados[0].regresso_previsto == _hora(saida + 1800 + 600 + 1800 + 600 + 1800)


def _hora(segundos):
    return f"{segundos // 3600:02d}:{segundos % 3600 // 60:02d}"


def test_na_noite_da_mudanca_as_horas_seguem_o_texto():
    """00:30 + 30 min = "01:00" e + 10 + 30 min = "01:40", que a 2026-03-29 nem existe em Lisboa."""
    resultado = calcular_horarios(_s("00:30"), _s("03:30"), [_pc("a"), _pc("b")], [1800, 1800, 1800])
    assert resultado.por_paragem == {"a": _linha("01:00", 0), "b": _linha("01:40", 0)}
    assert resultado.regresso_previsto == "02:20"


def test_entrada_calculo_so_le_as_horas_e_as_portagens_da_rota():
    rota = _Lido(_rota())
    paragem = _Lido(_paragem(P1))
    loja = _Lido(_loja(COMERCIO, JANELAS_COMERCIO))
    entrada_calculo(rota, [(paragem, loja)], FABRICA, FABRICA)
    assert set(rota.lidas) == {"hora_saida", "hora_regresso_limite", "evitar_portagens"}
    assert set(paragem.lidas) == {"id", "tempo_servico_min", "motivo"}
    assert set(loja.lidas) == {"lat", "lng", "janelas"}


# --- entrada_calculo ------------------------------------------------------------------------------

ENTRADA_FIXA = {
    "v": 1,
    "saida": 28800,
    "limite": 68400,
    "inicio": ["38.722300", "-9.139300"],
    "fim": ["38.722300", "-9.139300"],
    "evitar_portagens": False,
    "paragens": [
        [P1, "38.707500", "-9.136400", 10, [[36000, 46800], [54000, 68400]]],
        [P2, "38.725300", "-9.150000", 15, []],
    ],
}

# O JSON canónico da ENTRADA_FIXA escrito à mão: chaves por ordem, sem espaços.
TEXTO_FIXO = (
    '{"evitar_portagens":false,"fim":["38.722300","-9.139300"],"inicio":["38.722300","-9.139300"],'
    '"limite":68400,"paragens":[["5a1e6c7d-8b9f-4e0a-9b1c-2d3e4f5a6b7c","38.707500","-9.136400",10,'
    '[[36000,46800],[54000,68400]]],["6b2f7d8e-9c0a-4f1b-ac2d-3e4f5a6b7c8d","38.725300","-9.150000",15,[]]],'
    '"saida":28800,"v":1}'
)
ASSINATURA_FIXA = "sha256:b9e8385064243bc3e17b7cf6c82210e1e8cfc3f1b96598de1bbd8dfb0eb65373"


def test_a_entrada_do_calculo():
    assert entrada_calculo(_rota(), _incluidas(), FABRICA, FABRICA) == ENTRADA_FIXA


def test_a_entrada_leva_o_inicio_e_o_fim_e_as_portagens():
    entrada = entrada_calculo(_rota(evitar_portagens=True), _incluidas(), FABRICA, BELEM)
    assert entrada["inicio"] == ["38.722300", "-9.139300"]
    assert entrada["fim"] == ["38.691600", "-9.216000"]
    assert entrada["evitar_portagens"] is True


def test_as_coordenadas_arredondam_meio_para_longe_do_zero_as_6_casas():
    """38,7223445 → "38.722345" e −9,1393005 → "-9.139301" (o `round` e o "%.6f" davam 38.722344 e -9.139300)."""
    ponto = (38.7223445, -9.1393005)
    entrada = entrada_calculo(_rota(), [(_paragem(P1), _loja(ponto))], ponto, ponto)
    assert entrada["inicio"] == entrada["fim"] == ["38.722345", "-9.139301"]
    assert entrada["paragens"][0][1:3] == ["38.722345", "-9.139301"]


def test_as_coordenadas_inteiras_tambem_levam_6_casas():
    entrada = entrada_calculo(_rota(), [(_paragem(P1), _loja((39, -9)))], [39, -9], (39.0, -9.0))
    assert entrada["inicio"] == entrada["fim"] == entrada["paragens"][0][1:3] == ["39.000000", "-9.000000"]


def test_sem_paragens_incluidas():
    entrada = entrada_calculo(_rota(), [], FABRICA, FABRICA)
    assert entrada["paragens"] == []


def test_a_entrada_e_so_numeros_texto_e_booleanos_do_json():
    entrada = entrada_calculo(_rota(), _incluidas(), FABRICA, FABRICA)
    assert json.loads(json.dumps(entrada, allow_nan=False)) == entrada


def test_a_entrada_nao_leva_nomes_telefones_notas_datas_nem_os_ids_das_lojas():
    lojas, paragens = _cenario_completo()
    entrada = entrada_calculo(_rota(), list(zip(paragens, lojas)), FABRICA, FABRICA)
    texto = json.dumps(entrada, ensure_ascii=False)
    proibidos = [*CANARIOS_TEXTO, MEMBRO, REGIAO, *(l["id"] for l in lojas), "2026-10", "entrega", "amostra"]
    assert [canario for canario in proibidos if canario.lower() in texto.lower()] == []
    assert [linha[0] for linha in entrada["paragens"]] == [p["id"] for p in paragens]


def test_entrada_calculo_nao_muda_o_que_recebe_e_devolve_estruturas_novas():
    rota, incluidas = _rota(), _incluidas()
    copias = copy.deepcopy((rota, incluidas))
    um = entrada_calculo(rota, incluidas, list(FABRICA), FABRICA)
    outro = entrada_calculo(rota, incluidas, list(FABRICA), FABRICA)
    assert (rota, incluidas) == copias
    assert um == outro
    assert um["paragens"] is not outro["paragens"]
    assert um["inicio"] is not outro["inicio"]


@pytest.mark.parametrize("evitar", [None, 1, 0, "false", "true"])
def test_entrada_calculo_recusa_portagens_que_nao_sao_booleanas(evitar):
    with pytest.raises(ValueError):
        entrada_calculo(_rota(evitar_portagens=evitar), _incluidas(), FABRICA, FABRICA)


@pytest.mark.parametrize("campo", ["hora_saida", "hora_regresso_limite"])
@pytest.mark.parametrize("hora", ["8:00", "", None, "24:00", 28800])
def test_entrada_calculo_recusa_horas_estragadas(campo, hora):
    with pytest.raises(ValueError):
        entrada_calculo(_rota(**{campo: hora}), _incluidas(), FABRICA, FABRICA)


@pytest.mark.parametrize("ponto", [{"lat": 38.7, "lng": -9.1}, (38.7,), (38.7, -9.1, 0), "38.7,-9.1", (math.nan, -9.1), (38.7, True), None])
def test_entrada_calculo_recusa_um_inicio_ou_fim_que_nao_e_um_par_lat_lng(ponto):
    with pytest.raises(ValueError):
        entrada_calculo(_rota(), _incluidas(), ponto, FABRICA)
    with pytest.raises(ValueError):
        entrada_calculo(_rota(), _incluidas(), FABRICA, ponto)


def test_entrada_calculo_recusa_incluidas_que_nao_sao_pares():
    paragem, loja = _incluidas()[0]
    with pytest.raises(TypeError):
        entrada_calculo(_rota(), (x for x in [(paragem, loja)]), FABRICA, FABRICA)
    with pytest.raises(TypeError):
        entrada_calculo(_rota(), [paragem], FABRICA, FABRICA)
    with pytest.raises(TypeError):
        entrada_calculo(_rota(), [(paragem, loja, loja)], FABRICA, FABRICA)


def test_entrada_calculo_recusa_paragens_estragadas():
    with pytest.raises(ValueError):
        entrada_calculo(_rota(), [(_paragem(P1, tempo=0), _loja(COMERCIO))], FABRICA, FABRICA)
    with pytest.raises(ValueError):
        entrada_calculo(_rota(), [(_paragem(P1), _loja(COMERCIO, [{"inicio": "13:00", "fim": "10:00"}]))], FABRICA, FABRICA)


# --- assinatura -----------------------------------------------------------------------------------


def test_a_assinatura_e_o_sha256_do_json_canonico():
    assert assinatura(ENTRADA_FIXA) == "sha256:" + hashlib.sha256(TEXTO_FIXO.encode("utf-8")).hexdigest()
    assert assinatura(ENTRADA_FIXA) == ASSINATURA_FIXA


def test_a_assinatura_da_rota():
    assert assinatura(entrada_calculo(_rota(), _incluidas(), FABRICA, FABRICA)) == ASSINATURA_FIXA


def test_a_forma_da_assinatura():
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", assinatura(ENTRADA_FIXA))


def test_a_assinatura_nao_depende_da_ordem_das_chaves():
    assert assinatura({"a": 1, "b": [2, {"c": 3, "d": 4}]}) == assinatura({"b": [2, {"d": 4, "c": 3}], "a": 1})


def test_a_assinatura_le_o_texto_em_utf8_sem_escapes():
    esperado = "sha256:" + hashlib.sha256('{"nome":"Café ç","v":1}'.encode("utf-8")).hexdigest()
    assert assinatura({"v": 1, "nome": "Café ç"}) == esperado


def test_a_assinatura_recusa_o_que_nao_e_json():
    with pytest.raises(ValueError):
        assinatura({"v": 1, "x": math.nan})
    with pytest.raises(TypeError):
        assinatura([ENTRADA_FIXA])
    with pytest.raises(TypeError):
        assinatura(json.dumps(ENTRADA_FIXA))


def test_a_assinatura_nao_muda_a_entrada():
    entrada = copy.deepcopy(ENTRADA_FIXA)
    assinatura(entrada)
    assert entrada == ENTRADA_FIXA


def _variante(rota=None, incluidas=None, inicio=FABRICA, fim=FABRICA):
    return assinatura(entrada_calculo(rota or _rota(), _incluidas() if incluidas is None else incluidas, inicio, fim))


def _trocar_loja(i, **campos):
    incluidas = _incluidas()
    paragem, loja = incluidas[i]
    incluidas[i] = (paragem, {**loja, **campos})
    return incluidas


def _trocar_paragem(i, **campos):
    incluidas = _incluidas()
    paragem, loja = incluidas[i]
    incluidas[i] = ({**paragem, **campos}, loja)
    return incluidas


def test_a_assinatura_muda_com_tudo_o_que_muda_as_horas():
    base = _variante()
    variantes = {
        "a ordem": _variante(incluidas=list(reversed(_incluidas()))),
        "a latitude na 6.ª casa": _variante(incluidas=_trocar_loja(0, lat=38.707501)),
        "a longitude na 6.ª casa": _variante(incluidas=_trocar_loja(1, lng=-9.150001)),
        "o serviço": _variante(incluidas=_trocar_paragem(0, tempo_servico_min=11)),
        "uma janela": _variante(incluidas=_trocar_loja(0, janelas=[{"inicio": "10:00", "fim": "13:01"}, JANELAS_COMERCIO[1]])),
        "a 2.ª janela a menos": _variante(incluidas=_trocar_loja(0, janelas=JANELAS_COMERCIO[:1])),
        "uma janela a mais": _variante(incluidas=_trocar_loja(1, janelas=JANELAS_COMERCIO[:1])),
        "a saída": _variante(rota=_rota(hora_saida="08:01")),
        "o limite": _variante(rota=_rota(hora_regresso_limite="18:59")),
        "o início": _variante(inicio=(38.722301, -9.1393)),
        "o fim": _variante(fim=(38.7223, -9.139301)),
        "as portagens": _variante(rota=_rota(evitar_portagens=True)),
        "outra paragem (id)": _variante(incluidas=_trocar_paragem(1, id=P3)),
        "uma paragem a menos": _variante(incluidas=_incluidas()[:1]),
    }
    assert base not in variantes.values()
    assert len(set(variantes.values())) == len(variantes)


def test_o_inicio_e_o_fim_trocados_mudam_a_assinatura():
    assert _variante(inicio=FABRICA, fim=BELEM) != _variante(inicio=BELEM, fim=FABRICA)


def test_a_assinatura_nao_muda_com_o_que_nao_mexe_nas_horas():
    base = _variante()
    iguais = {
        "o nome": _variante(incluidas=_trocar_loja(0, nome="Outro nome")),
        "o telefone": _variante(incluidas=_trocar_loja(0, telefone="+351922222222")),
        "as notas": _variante(incluidas=_trocar_loja(1, notas="Ligar antes")),
        "a fase e os dias fechada": _variante(incluidas=_trocar_loja(0, fase="cliente", dias_fechada=["seg"])),
        "o motivo com o mesmo serviço": _variante(incluidas=_trocar_paragem(0, motivo="amostra")),
        "o motivo e o resto da paragem": _variante(
            incluidas=_trocar_paragem(1, motivo="angariacao", chegada_prevista="09:00", espera_min=3,
                                      fora_de_horario=True, ordem=7, adicionada_em="2026-10-12T10:00:00Z")
        ),
        "a data e o resto da rota": _variante(rota=_rota("2026-10-25", versao=9, estado="planeada", id="outra",
                                                         calculo={"assinatura": "x"})),
        "a 7.ª casa das coordenadas": _variante(incluidas=_trocar_loja(0, lat=38.70750004), inicio=(38.72230004, -9.1393)),
        "o início em lista": _variante(inicio=list(FABRICA), fim=list(FABRICA)),
        "as incluídas num tuplo": _variante(incluidas=tuple(_incluidas())),
    }
    assert {nome: valor for nome, valor in iguais.items() if valor != base} == {}


def test_a_assinatura_da_entrada_igual_e_igual():
    assert _variante() == _variante()


# --- O módulo -----------------------------------------------------------------------------------


def _importacoes(codigo):
    nomes = set()
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Import):
            nomes |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom):
            nomes.add((no.module or "").split(".")[0])
            nomes |= {alias.name for alias in no.names}
    return nomes


def test_horarios_nunca_passa_por_instantes_nem_pelo_relogio():
    """As horas nunca passam por instantes (plano §1): nem `datetime`, `zoneinfo`, `time` nem o `relogio`."""
    assert _importacoes(FICHEIRO.read_text(encoding="utf-8")) & {"datetime", "zoneinfo", "time", "pytz", "relogio"} == set()


def test_o_varrimento_das_importacoes_ve_as_formas():
    assert _importacoes("import datetime\nfrom zoneinfo import ZoneInfo\nfrom .. import relogio\n") >= {"datetime", "zoneinfo", "relogio"}


def test_horarios_nunca_chama_o_round_do_python():
    """O `round` arredonda para o par (30,5 min → 30): usa-se `numeros.arredondar` (pelo `horas`)."""
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []
