"""As sugestões de lojas para aproveitar a viagem (crm/dominio/sugestoes.py), F3 / T3.9.

Plano F3 §1 ("Sugestões"): calculadas no servidor, em dois grupos, **contactada**
e depois **potencial**. Entram as lojas a ≤ 5 km em linha reta de qualquer
paragem ativa (`geo.distancia_metros`) e, com `calculo.atual`, também as que
estão a ≤ 3 km da linha desenhada (o corredor, a polyline descodificada). Ficam
de fora a perdida, a amostra e o cliente, as lojas fechadas nesse dia da semana,
as que já estão na rota e as que não têm coordenadas. Cada grupo mostra no
máximo 30, com `mais = N − 30`.

`sugerir(lojas, lojas_das_paragens, ids_na_rota, data, linha=None)` →
`{"sem_paragens", "no_caminho", "grupos": [{"fase", "lojas": [{id, nome, fase,
lat, lng, distancia_m, no_caminho}], "mais"}]}`.

`distancia_a_linha(lat, lng, linha, limite=inf)` é a distância ao troço mais
perto, numa projeção equirretangular local (±1 % contra a haversine até 5 km),
com rejeição por caixa: um troço a mais de `limite` metros num dos eixos nem se
mede. Nunca deixa de fora um ponto dentro do limite (100 pontos ao acaso contra
a força bruta).

Correção "T3.7 / T3.9 / T3.13 / T3.21": a linha vem do `polilinha.descodificar`
(e os testes codificam com o `polilinha.codificar`, que nasceu na T3.7).

Os pontos constroem-se à mão: `_deslocar(ponto, norte_m, este_m)` anda em metros
pelo `geo.METROS_POR_GRAU` (um grau de latitude) e pelo cosseno da latitude (um
grau de longitude); a distância haversine a um ponto deslocado só para norte é
exata ao micrómetro, por isso serve para "5000 m exatos".
"""
import ast
import copy
import math
import random
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import crm.dominio.sugestoes as sugestoes
from crm.dominio.geo import METROS_POR_GRAU, distancia_metros
from crm.dominio.polilinha import codificar, descodificar
from crm.dominio.sugestoes import (
    CORREDOR_M,
    FASES_SUGERIDAS,
    LIMITE_POR_GRUPO,
    RAIO_SUGESTOES_M,
    distancia_a_linha,
    sugerir,
)

FICHEIRO = Path(sugestoes.__file__)

# Pontos públicos de Lisboa (os dos cenários do ORS, T3.6).
A = (38.7223, -9.1393)  # Rossio: a paragem A
B = (38.7253, -9.15)  # Marquês: a paragem B, a ~1 km de A

SEGUNDA = date(2026, 10, 12)
TERCA = date(2026, 10, 13)

CHAVES_DA_SUGESTAO = ["id", "nome", "fase", "lat", "lng", "distancia_m", "no_caminho"]
GRUPO_VAZIO_CONTACTADA = {"fase": "contactada", "lojas": [], "mais": 0}
GRUPO_VAZIO_POTENCIAL = {"fase": "potencial", "lojas": [], "mais": 0}


def _deslocar(ponto, norte_m=0.0, este_m=0.0):
    """O ponto `norte_m` metros para norte e `este_m` para este (negativos: sul e oeste)."""
    lat, lng = ponto
    return (lat + norte_m / METROS_POR_GRAU, lng + este_m / (METROS_POR_GRAU * math.cos(math.radians(lat))))


def _loja(id_, nome, fase, ponto, dias_fechada=(), **extra):
    lat, lng = ponto if ponto is not None else (None, None)
    return {"id": id_, "nome": nome, "fase": fase, "lat": lat, "lng": lng, "dias_fechada": list(dias_fechada), **extra}


def _metros(ponto, loja):
    return distancia_metros(ponto[0], ponto[1], loja["lat"], loja["lng"])


PARAGENS = [_loja("p-a", "Paragem A", "contactada", A), _loja("p-b", "Paragem B", "cliente", B)]
SO_A = PARAGENS[:1]  # para medir distâncias só a A (a B, a ~1 km, fica mais perto de quem está a norte de A)
NA_ROTA = frozenset({"p-a", "p-b"})

# A linha da rota: de A, 20 km para este, em 3 pontos.
LINHA = [A, _deslocar(A, este_m=10_000), _deslocar(A, este_m=20_000)]


def _sugerir(lojas, data=SEGUNDA, linha=None, paragens=PARAGENS, ids=NA_ROTA):
    return sugerir(lojas, paragens, ids, data, linha)


def _grupo(resultado, fase):
    [grupo] = [g for g in resultado["grupos"] if g["fase"] == fase]
    return grupo


def _ids(resultado, fase):
    return [loja["id"] for loja in _grupo(resultado, fase)["lojas"]]


# --- Sem paragens ---------------------------------------------------------------------------------


def test_sem_paragens_e_a_resposta_fixa():
    lojas = [_loja("c", "Café", "contactada", _deslocar(A, 100))]
    assert sugerir(lojas, [], set(), SEGUNDA) == {"sem_paragens": True, "no_caminho": False, "grupos": []}


def test_sem_paragens_a_linha_nao_conta():
    lojas = [_loja("c", "Café", "contactada", _deslocar(A, 100))]
    assert sugerir(lojas, [], set(), SEGUNDA, LINHA) == {"sem_paragens": True, "no_caminho": False, "grupos": []}


def test_paragens_cujas_lojas_nao_tem_coordenadas_contam_como_sem_paragens():
    paragens = [
        _loja("p", "P", "contactada", None),
        {"id": "q", "lat": math.nan, "lng": -9.1},
        {"id": "r", "lat": True, "lng": -9.1},
        {"id": "s", "lat": 38.7, "lng": "-9.1"},
        {"id": "t"},
    ]
    lojas = [_loja("c", "Café", "contactada", _deslocar(A, 100))]
    assert sugerir(lojas, paragens, {"p", "q", "r", "s", "t"}, SEGUNDA) == {
        "sem_paragens": True,
        "no_caminho": False,
        "grupos": [],
    }


def test_basta_uma_paragem_com_coordenadas():
    paragens = [{"id": "q", "lat": None, "lng": None}, _loja("p-a", "Paragem A", "contactada", A)]
    resultado = sugerir([_loja("c", "Café", "contactada", _deslocar(A, 100))], paragens, {"q", "p-a"}, SEGUNDA)
    assert resultado["sem_paragens"] is False
    assert _ids(resultado, "contactada") == ["c"]


# --- A resposta com paragens ----------------------------------------------------------------------


def test_a_forma_da_resposta_com_paragens():
    cafe = _loja("c", "Café", "contactada", _deslocar(A, 1000))
    padaria = _loja("p", "Padaria", "potencial", _deslocar(B, 2000))
    assert _sugerir([padaria, cafe]) == {
        "sem_paragens": False,
        "no_caminho": False,
        "grupos": [
            {
                "fase": "contactada",
                "lojas": [
                    {
                        "id": "c",
                        "nome": "Café",
                        "fase": "contactada",
                        "lat": cafe["lat"],
                        "lng": cafe["lng"],
                        "distancia_m": 1000,
                        "no_caminho": False,
                    }
                ],
                "mais": 0,
            },
            {
                "fase": "potencial",
                "lojas": [
                    {
                        "id": "p",
                        "nome": "Padaria",
                        "fase": "potencial",
                        "lat": padaria["lat"],
                        "lng": padaria["lng"],
                        "distancia_m": 2000,
                        "no_caminho": False,
                    }
                ],
                "mais": 0,
            },
        ],
    }


def test_os_grupos_sao_contactada_e_depois_potencial_mesmo_vazios():
    resultado = _sugerir([_loja("p", "Padaria", "potencial", _deslocar(A, 100))])
    assert [g["fase"] for g in resultado["grupos"]] == ["contactada", "potencial"]
    assert resultado["grupos"][0] == GRUPO_VAZIO_CONTACTADA
    assert _ids(resultado, "potencial") == ["p"]


def test_os_grupos_sao_contactada_e_depois_potencial_seja_qual_for_a_ordem_das_lojas():
    lojas = [_loja("p", "Padaria", "potencial", _deslocar(A, 100)), _loja("c", "Café", "contactada", _deslocar(A, 3000))]
    resultado = _sugerir(lojas)
    assert [g["fase"] for g in resultado["grupos"]] == ["contactada", "potencial"]
    assert [[l["id"] for l in g["lojas"]] for g in resultado["grupos"]] == [["c"], ["p"]]


def test_as_fases_sugeridas_sao_so_estas_duas_por_esta_ordem():
    assert FASES_SUGERIDAS == ("contactada", "potencial")


def test_sem_nenhuma_loja_perto_os_dois_grupos_vem_vazios():
    resultado = _sugerir([_loja("c", "Café", "contactada", _deslocar(A, 20_000))])
    assert resultado == {"sem_paragens": False, "no_caminho": False, "grupos": [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]}


def test_sem_lojas_nenhumas_os_dois_grupos_vem_vazios():
    assert _sugerir([])["grupos"] == [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]


# --- A ordem dentro de cada grupo -----------------------------------------------------------------


def test_cada_grupo_vem_pela_distancia_depois_pelo_nome_sem_acentos_e_depois_pelo_id():
    lojas = [
        _loja("z", "Zinco", "contactada", _deslocar(A, 1000.0)),
        _loja("b", "Ébano", "contactada", _deslocar(A, 1000.3)),
        _loja("aaa", "Aaa", "contactada", _deslocar(A, 1001)),
        _loja("a", "ebano", "contactada", _deslocar(A, 1000.1)),
        _loja("q", "Água", "contactada", _deslocar(A, 500)),
    ]
    resultado = _sugerir(lojas)
    # Os metros mostrados mandam (1000,0, 1000,1 e 1000,3 são todos "1000"); depois "ebano" < "zinco"
    # (sem o acento nem a maiúscula) e, com o mesmo nome, o id "a" < "b"; o "Aaa" a 1001 m fica atrás.
    assert _ids(resultado, "contactada") == ["q", "a", "b", "z", "aaa"]
    assert [l["distancia_m"] for l in _grupo(resultado, "contactada")["lojas"]] == [500, 1000, 1000, 1000, 1001]


def test_a_ordem_e_por_grupo():
    lojas = [
        _loja("p1", "Padaria", "potencial", _deslocar(A, 100)),
        _loja("c1", "Café", "contactada", _deslocar(A, 3000)),
        _loja("c2", "Bar", "contactada", _deslocar(A, 2000)),
        _loja("p2", "Mercearia", "potencial", _deslocar(A, 50)),
    ]
    resultado = _sugerir(lojas)
    assert _ids(resultado, "contactada") == ["c2", "c1"]
    assert _ids(resultado, "potencial") == ["p2", "p1"]


# --- O raio de 5 km -------------------------------------------------------------------------------


def test_a_5000_m_exatos_entra():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 5000))
    assert _metros(A, loja) == pytest.approx(5000, abs=1e-6)
    resultado = _sugerir([loja], paragens=SO_A)
    assert _ids(resultado, "contactada") == ["c"]
    assert _grupo(resultado, "contactada")["lojas"][0]["distancia_m"] == 5000


def test_a_5000_5_m_nao_entra():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 5000.5))
    assert _metros(A, loja) == pytest.approx(5000.5, abs=1e-6)
    assert _ids(_sugerir([loja], paragens=SO_A), "contactada") == []


@pytest.mark.parametrize(
    "metros, entra, mostrado",
    [(4999.4, True, 4999), (4999.5, True, 5000), (5000.4, True, 5000), (5000.5, False, None), (5001, False, None)],
)
def test_o_raio_conta_os_metros_mostrados_arredondados_meio_para_longe_do_zero(metros, entra, mostrado):
    """O que se mostra decide: "5000 m" entra, "5001 m" não (e o `round` do Python daria 5000 para 5000,5)."""
    loja = _loja("c", "Café", "contactada", _deslocar(A, metros))
    resultado = _sugerir([loja], paragens=SO_A)
    assert _ids(resultado, "contactada") == (["c"] if entra else [])
    if entra:
        assert _grupo(resultado, "contactada")["lojas"][0]["distancia_m"] == mostrado


def test_o_raio_e_5_km():
    assert RAIO_SUGESTOES_M == 5000


def test_a_distancia_e_a_minima_a_qualquer_paragem_ativa():
    loja = _loja("c", "Café", "contactada", _deslocar(B, 3000))
    a_a, a_b = _metros(A, loja), _metros(B, loja)
    assert a_b < a_a
    [sugerida] = _grupo(_sugerir([loja]), "contactada")["lojas"]
    assert sugerida["distancia_m"] == 3000
    assert sugerida["distancia_m"] == int(math.floor(a_b + 0.5))


def test_entra_quem_esta_a_menos_de_5_km_de_qualquer_paragem_mesmo_longe_da_primeira():
    loja = _loja("c", "Café", "contactada", _deslocar(B, este_m=-4500))
    assert _metros(A, loja) > 5000
    assert _metros(B, loja) == pytest.approx(4500, abs=0.01)
    [sugerida] = _grupo(_sugerir([loja]), "contactada")["lojas"]
    assert sugerida["distancia_m"] == 4500


def test_distancia_m_e_um_inteiro():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 1234.56))
    [sugerida] = _grupo(_sugerir([loja]), "contactada")["lojas"]
    assert type(sugerida["distancia_m"]) is int
    assert sugerida["distancia_m"] == 1235


# --- Excluídas ------------------------------------------------------------------------------------


@pytest.mark.parametrize("fase", ["perdida", "amostra", "cliente", None, "", "Contactada", " potencial", "outra", 1])
def test_so_as_contactadas_e_as_potenciais_entram(fase):
    resultado = _sugerir([_loja("x", "X", fase, _deslocar(A, 100))])
    assert resultado["grupos"] == [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]


def test_a_amostra_e_o_cliente_ficam_de_fora_mesmo_ao_lado_das_paragens():
    lojas = [_loja("am", "Amostra", "amostra", _deslocar(A, 10)), _loja("cl", "Cliente", "cliente", _deslocar(B, 10))]
    assert _sugerir(lojas)["grupos"] == [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]


def test_uma_loja_sem_fase_no_documento_fica_de_fora():
    assert _sugerir([{"id": "x", "nome": "X", "lat": A[0], "lng": A[1]}])["grupos"] == [
        GRUPO_VAZIO_CONTACTADA,
        GRUPO_VAZIO_POTENCIAL,
    ]


def test_a_loja_fechada_nesse_dia_da_semana_fica_de_fora():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 100), dias_fechada=["seg"])
    assert _ids(_sugerir([loja], SEGUNDA), "contactada") == []
    assert _ids(_sugerir([loja], TERCA), "contactada") == ["c"]


def test_a_potencial_fechada_nesse_dia_tambem_fica_de_fora():
    loja = _loja("p", "Padaria", "potencial", _deslocar(A, 100), dias_fechada=["dom", "seg"])
    assert _ids(_sugerir([loja], SEGUNDA), "potencial") == []
    assert _ids(_sugerir([loja], TERCA), "potencial") == ["p"]


@pytest.mark.parametrize("dias", [[], None])
def test_sem_dias_fechada_a_loja_entra_em_qualquer_dia(dias):
    loja = {"id": "c", "nome": "Café", "fase": "contactada", "lat": A[0], "lng": A[1] + 0.001, "dias_fechada": dias}
    for n in range(7):
        assert _ids(_sugerir([loja], date(2026, 10, 12 + n)), "contactada") == ["c"]


def test_a_loja_que_ja_esta_na_rota_fica_de_fora():
    # As lojas das paragens chegam também na lista de todas as lojas: nunca se sugerem a si próprias.
    lojas = [*PARAGENS, _loja("c", "Café", "contactada", _deslocar(A, 100))]
    resultado = _sugerir(lojas)
    assert _ids(resultado, "contactada") == ["c"]
    assert _ids(resultado, "potencial") == []


def test_os_ids_na_rota_e_que_mandam():
    """Uma paragem cuja loja já não tem coordenadas (ou foi apagada) continua a contar como "já na rota"."""
    loja = _loja("c", "Café", "contactada", _deslocar(A, 100))
    assert _ids(_sugerir([loja], ids={"p-a", "p-b", "c"}), "contactada") == []
    assert _ids(_sugerir([loja], ids=["c"]), "contactada") == []
    assert _ids(_sugerir([loja], ids=()), "contactada") == ["c"]


@pytest.mark.parametrize(
    "lat, lng",
    [(None, -9.1393), (38.7223, None), (None, None), (math.nan, -9.1393), (38.7223, math.inf), (True, -9.1393),
     (38.7223, False), ("38.7223", -9.1393), (38.7223, "-9.1393"), ([38.7223], -9.1393)],
)
def test_sem_coordenadas_validas_a_loja_fica_de_fora(lat, lng):
    loja = {"id": "c", "nome": "Café", "fase": "contactada", "lat": lat, "lng": lng, "dias_fechada": []}
    assert _sugerir([loja], linha=LINHA)["grupos"] == [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]


def test_sem_as_chaves_das_coordenadas_a_loja_fica_de_fora():
    assert _sugerir([{"id": "c", "nome": "Café", "fase": "contactada"}])["grupos"] == [
        GRUPO_VAZIO_CONTACTADA,
        GRUPO_VAZIO_POTENCIAL,
    ]


def test_as_excluidas_nao_contam_para_o_mais():
    lojas = [_loja(f"c{n}", f"Café {n}", "contactada", _deslocar(A, 100 + n)) for n in range(LIMITE_POR_GRUPO)]
    lojas += [_loja("perdida", "Perdida", "perdida", _deslocar(A, 10)), _loja("longe", "Longe", "contactada", _deslocar(A, 9000))]
    grupo = _grupo(_sugerir(lojas), "contactada")
    assert len(grupo["lojas"]) == LIMITE_POR_GRUPO
    assert grupo["mais"] == 0


# --- O corredor (3 km da linha) -------------------------------------------------------------------


def test_no_caminho_a_2_9_km_da_linha_e_a_8_km_das_paragens():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 2900, 7460))
    assert min(_metros(A, loja), _metros(B, loja)) == pytest.approx(8000, abs=100)
    resultado = _sugerir([loja], linha=LINHA)
    assert resultado["no_caminho"] is True
    [sugerida] = _grupo(resultado, "contactada")["lojas"]
    assert sugerida == {
        "id": "c",
        "nome": "Café",
        "fase": "contactada",
        "lat": loja["lat"],
        "lng": loja["lng"],
        "distancia_m": 2900,
        "no_caminho": True,
    }
    assert list(sugerida) == CHAVES_DA_SUGESTAO


def test_a_3_1_km_da_linha_nao_entra():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 3100, 7460))
    resultado = _sugerir([loja], linha=LINHA)
    assert resultado["no_caminho"] is True
    assert resultado["grupos"] == [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]


def test_sem_linha_a_loja_no_caminho_nao_entra_e_no_caminho_e_falso():
    """O corredor só existe com `calculo.atual` (quem chama passa a linha só nesse caso)."""
    loja = _loja("c", "Café", "contactada", _deslocar(A, 2900, 7460))
    resultado = _sugerir([loja])
    assert resultado == {"sem_paragens": False, "no_caminho": False, "grupos": [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]}


@pytest.mark.parametrize("linha", [[], ()])
def test_uma_linha_vazia_nao_e_corredor(linha):
    loja = _loja("c", "Café", "contactada", _deslocar(A, 2900, 7460))
    resultado = _sugerir([loja], linha=linha)
    assert resultado == {"sem_paragens": False, "no_caminho": False, "grupos": [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]}


def test_perto_pelos_dois_lados_fica_com_a_menor_distancia_e_no_caminho_falso():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 1000, 4000))
    assert _metros(A, loja) == pytest.approx(math.hypot(1000, 4000), abs=1)
    [sugerida] = _grupo(_sugerir([loja], linha=LINHA), "contactada")["lojas"]
    assert sugerida["distancia_m"] == 1000
    assert sugerida["no_caminho"] is False


def test_perto_de_uma_paragem_mas_longe_da_linha_mostra_a_distancia_a_paragem():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 4000, 1000))
    assert distancia_a_linha(loja["lat"], loja["lng"], LINHA) == pytest.approx(4000, abs=1e-6)  # fora do corredor
    [sugerida] = _grupo(_sugerir([loja], linha=LINHA), "contactada")["lojas"]
    assert sugerida["distancia_m"] == int(math.floor(_metros(A, loja) + 0.5)) == 4123
    assert sugerida["no_caminho"] is False


def test_a_distancia_mostrada_nunca_passa_dos_5_km():
    semente = random.Random(39)
    lojas = [
        _loja(f"c{n}", f"Café {n}", "contactada", _deslocar(A, semente.uniform(-7000, 7000), semente.uniform(-5000, 25_000)))
        for n in range(200)
    ]
    for linha in (None, LINHA):
        for grupo in _sugerir(lojas, linha=linha)["grupos"]:
            assert all(0 <= l["distancia_m"] <= RAIO_SUGESTOES_M for l in grupo["lojas"])
            assert all(l["distancia_m"] <= CORREDOR_M for l in grupo["lojas"] if l["no_caminho"])


def test_no_caminho_tambem_para_as_potenciais():
    loja = _loja("p", "Padaria", "potencial", _deslocar(A, -2500, 15_000))
    resultado = _sugerir([loja], linha=LINHA)
    [sugerida] = _grupo(resultado, "potencial")["lojas"]
    assert (sugerida["distancia_m"], sugerida["no_caminho"]) == (2500, True)
    assert _grupo(resultado, "contactada")["lojas"] == []


@pytest.mark.parametrize("metros, entra, mostrado", [(2999.6, True, 3000), (3000.4, True, 3000), (3000.5, False, None)])
def test_o_corredor_conta_os_metros_mostrados(metros, entra, mostrado):
    loja = _loja("c", "Café", "contactada", _deslocar(A, metros, 7460))
    resultado = _sugerir([loja], linha=LINHA)
    assert _ids(resultado, "contactada") == (["c"] if entra else [])
    if entra:
        assert _grupo(resultado, "contactada")["lojas"][0]["distancia_m"] == mostrado


def test_o_corredor_e_3_km():
    assert CORREDOR_M == 3000


def test_a_linha_e_a_polyline_descodificada():
    """O que chega é o `polilinha.descodificar(calculo.geometria)`: 5 casas, sem elevação."""
    linha = descodificar(codificar(LINHA))
    assert linha != LINHA  # as 5 casas mudam os pontos ao centímetro…
    loja = _loja("c", "Café", "contactada", _deslocar(A, 2900, 7460))
    resultado = _sugerir([loja], linha=linha)
    [sugerida] = _grupo(resultado, "contactada")["lojas"]
    assert (sugerida["distancia_m"], sugerida["no_caminho"]) == (2900, True)  # …mas não os metros mostrados


def test_a_linha_pode_vir_em_listas_ou_tuplos():
    loja = _loja("c", "Café", "contactada", _deslocar(A, 2900, 7460))
    for linha in ([list(p) for p in LINHA], tuple(LINHA), tuple(tuple(p) for p in LINHA)):
        assert _ids(_sugerir([loja], linha=linha), "contactada") == ["c"]


def test_as_excluidas_tambem_ficam_de_fora_do_corredor():
    lojas = [
        _loja("perdida", "Perdida", "perdida", _deslocar(A, 100, 10_000)),
        _loja("amostra", "Amostra", "amostra", _deslocar(A, 100, 10_000)),
        _loja("fechada", "Fechada", "contactada", _deslocar(A, 100, 10_000), dias_fechada=["seg"]),
        _loja("p-a", "Paragem A", "contactada", _deslocar(A, 100, 10_000)),
    ]
    assert _sugerir(lojas, linha=LINHA)["grupos"] == [GRUPO_VAZIO_CONTACTADA, GRUPO_VAZIO_POTENCIAL]


def test_a_ordem_no_grupo_mistura_as_do_raio_e_as_do_caminho_pela_distancia():
    lojas = [
        _loja("raio", "Raio", "contactada", _deslocar(A, 2000)),
        _loja("caminho", "Caminho", "contactada", _deslocar(A, 1500, 10_000)),
    ]
    grupo = _grupo(_sugerir(lojas, linha=LINHA, paragens=SO_A), "contactada")
    assert [(l["id"], l["distancia_m"], l["no_caminho"]) for l in grupo["lojas"]] == [("caminho", 1500, True), ("raio", 2000, False)]


# --- O limite de 30 por grupo ---------------------------------------------------------------------


def test_no_maximo_30_por_grupo_com_o_mais():
    contactadas = [_loja(f"c{n:02d}", f"Café {n}", "contactada", _deslocar(A, 100 * n)) for n in range(1, 36)]
    potenciais = [_loja(f"p{n:02d}", f"Padaria {n}", "potencial", _deslocar(B, 100 * n)) for n in range(1, 32)]
    resultado = _sugerir([*reversed(potenciais), *contactadas])
    contactada, potencial = resultado["grupos"]
    assert (len(contactada["lojas"]), contactada["mais"]) == (30, 5)
    assert (len(potencial["lojas"]), potencial["mais"]) == (30, 1)
    # Mostram-se as 30 mais perto, pela ordem.
    assert [l["id"] for l in contactada["lojas"]] == [f"c{n:02d}" for n in range(1, 31)]
    assert [l["id"] for l in potencial["lojas"]] == [f"p{n:02d}" for n in range(1, 31)]


def test_30_certas_nao_tem_mais():
    lojas = [_loja(f"c{n:02d}", f"Café {n}", "contactada", _deslocar(A, 100 * n)) for n in range(1, 31)]
    grupo = _grupo(_sugerir(lojas), "contactada")
    assert (len(grupo["lojas"]), grupo["mais"]) == (30, 0)


def test_o_limite_por_grupo_e_30():
    assert LIMITE_POR_GRUPO == 30


# --- O que sai ------------------------------------------------------------------------------------


def test_cada_sugestao_leva_so_estas_chaves_nunca_o_telefone():
    loja = _loja(
        "c", "Café", "contactada", _deslocar(A, 100),
        telefone="+351912345678", pessoa_contacto="CANARIO-PESSOA", notas="CANARIO-NOTAS", regiao_id="r1", morada="Rua X",
    )
    [sugerida] = _grupo(_sugerir([loja]), "contactada")["lojas"]
    assert list(sugerida) == CHAVES_DA_SUGESTAO
    assert "CANARIO" not in repr(sugerida) and "912345678" not in repr(sugerida)


def test_as_coordenadas_saem_tal_como_entraram():
    loja = _loja("c", "Café", "contactada", (38.722345, -9.139301))
    [sugerida] = _grupo(_sugerir([loja]), "contactada")["lojas"]
    assert (sugerida["lat"], sugerida["lng"]) == (38.722345, -9.139301)
    assert type(sugerida["lat"]) is float and type(sugerida["lng"]) is float


def test_aceita_coordenadas_inteiras():
    loja = {"id": "c", "nome": "Café", "fase": "contactada", "lat": 39, "lng": -9, "dias_fechada": []}
    paragens = [{"id": "p", "lat": 39, "lng": -9}]
    [sugerida] = _grupo(sugerir([loja], paragens, {"p"}, SEGUNDA, [(39, -9), (39, -8)]), "contactada")["lojas"]
    assert sugerida == {"id": "c", "nome": "Café", "fase": "contactada", "lat": 39, "lng": -9, "distancia_m": 0, "no_caminho": False}


def test_devolve_estruturas_novas_e_nao_muda_a_entrada():
    lojas = [_loja("c", "Café", "contactada", _deslocar(A, 100)), _loja("p", "Padaria", "potencial", _deslocar(A, 2900, 7460))]
    paragens = copy.deepcopy(PARAGENS)
    ids = {"p-a", "p-b"}
    linha = [list(p) for p in LINHA]
    copia = copy.deepcopy((lojas, paragens, ids, linha))
    primeiro = sugerir(lojas, paragens, ids, SEGUNDA, linha)
    segundo = sugerir(lojas, paragens, ids, SEGUNDA, linha)
    assert (lojas, paragens, ids, linha) == copia
    assert primeiro == segundo
    assert primeiro is not segundo
    assert primeiro["grupos"] is not segundo["grupos"]
    assert all(l is not loja for grupo in primeiro["grupos"] for l in grupo["lojas"] for loja in lojas)


# --- O que não se aceita --------------------------------------------------------------------------


@pytest.mark.parametrize("valor", [None, "abc", 3, {"id": "c"}, {("c",)}, (l for l in [])])
def test_as_lojas_e_as_lojas_das_paragens_tem_de_vir_numa_lista(valor):
    with pytest.raises(TypeError):
        sugerir(valor, PARAGENS, NA_ROTA, SEGUNDA)
    with pytest.raises(TypeError):
        sugerir([], valor, NA_ROTA, SEGUNDA)


@pytest.mark.parametrize("elemento", [("c", 38.7, -9.1), "c", None, 3, ["c"]])
def test_cada_loja_tem_de_ser_um_dicionario(elemento):
    with pytest.raises(TypeError):
        sugerir([elemento], PARAGENS, NA_ROTA, SEGUNDA)
    with pytest.raises(TypeError):
        sugerir([], [elemento], NA_ROTA, SEGUNDA)


@pytest.mark.parametrize("ids", ["p-a", None, 3])
def test_os_ids_na_rota_sao_um_conjunto_ou_uma_lista(ids):
    with pytest.raises(TypeError):
        sugerir([], PARAGENS, ids, SEGUNDA)


@pytest.mark.parametrize(
    "data",
    ["2026-10-12", None, 20261012, datetime(2026, 10, 12, tzinfo=timezone.utc), datetime(2026, 10, 12), ("2026", "10", "12")],
)
def test_a_data_tem_de_ser_um_date(data):
    with pytest.raises(TypeError):
        sugerir([], PARAGENS, NA_ROTA, data)


@pytest.mark.parametrize("linha", ["abc", 3, {(38.7, -9.1)}, (p for p in [(38.7, -9.1)]), {"lat": 38.7}])
def test_a_linha_tem_de_ser_uma_lista_de_pontos(linha):
    with pytest.raises(TypeError):
        sugerir([], PARAGENS, NA_ROTA, SEGUNDA, linha)


@pytest.mark.parametrize(
    "linha",
    [[(38.7,)], [(38.7, -9.1, 0)], [(38.7, "x")], [(math.nan, -9.1)], [(38.7, math.inf)], [(True, -9.1)], [(91, -9.1)],
     [(38.7, -181)], ["38.7,-9.1"], [None], [A, (38.7,)]],
)
def test_um_ponto_da_linha_estragado(linha):
    with pytest.raises(ValueError):
        sugerir([], PARAGENS, NA_ROTA, SEGUNDA, linha)


# --- distancia_a_linha ----------------------------------------------------------------------------

TROCO = [A, _deslocar(A, este_m=2000)]  # 2 km para este


def test_perpendicular_a_um_troco():
    ponto = _deslocar(A, 1000, 1000)
    assert distancia_a_linha(*ponto, TROCO) == pytest.approx(1000, abs=1e-6)
    # ±1 % contra a haversine ao pé da perpendicular.
    assert distancia_a_linha(*ponto, TROCO) == pytest.approx(distancia_metros(*ponto, *_deslocar(A, este_m=1000)), rel=1e-2)


def test_a_ponta_de_um_troco():
    depois = _deslocar(A, 300, 2400)
    antes = _deslocar(A, -300, -400)
    # O cosseno é o da latitude do ponto, 300 m a norte ou a sul: a componente este encurta ~0,004 %.
    assert distancia_a_linha(*depois, TROCO) == pytest.approx(500, rel=1e-3)
    assert distancia_a_linha(*antes, TROCO) == pytest.approx(500, rel=1e-3)
    assert distancia_a_linha(*depois, TROCO) == pytest.approx(distancia_metros(*depois, *TROCO[1]), rel=1e-2)
    assert distancia_a_linha(*antes, TROCO) == pytest.approx(distancia_metros(*antes, *TROCO[0]), rel=1e-2)


def test_um_troco_degenerado_e_a_distancia_ao_ponto():
    ponto = _deslocar(A, 300, 400)
    assert distancia_a_linha(*ponto, [A, A]) == pytest.approx(500, rel=1e-3)
    assert distancia_a_linha(*ponto, [A, A, A]) == pytest.approx(500, rel=1e-3)
    assert distancia_a_linha(*ponto, [A, A]) == pytest.approx(distancia_metros(*ponto, *A), rel=1e-2)


def test_uma_linha_com_um_so_ponto_e_a_distancia_a_esse_ponto():
    ponto = _deslocar(A, 300, 400)
    assert distancia_a_linha(*ponto, [A]) == pytest.approx(500, rel=1e-3)
    assert distancia_a_linha(*ponto, [A]) == pytest.approx(distancia_a_linha(*ponto, [A, A]), abs=1e-9)


@pytest.mark.parametrize("linha", [[], ()])
def test_sem_linha_a_distancia_e_infinita(linha):
    assert distancia_a_linha(*A, linha) == math.inf


def test_em_cima_da_linha_da_zero():
    assert distancia_a_linha(*A, TROCO) == pytest.approx(0, abs=1e-6)
    assert distancia_a_linha(*_deslocar(A, este_m=700), TROCO) == pytest.approx(0, abs=1e-6)
    assert distancia_a_linha(*TROCO[1], TROCO) == pytest.approx(0, abs=1e-6)


def test_com_varios_trocos_conta_o_mais_perto():
    linha = [A, _deslocar(A, este_m=2000), _deslocar(A, 2000, 2000), _deslocar(A, 2000, 0)]  # um U aberto para oeste
    assert distancia_a_linha(*_deslocar(A, 1000, 1000), linha) == pytest.approx(1000, rel=1e-3)  # os três lados a 1 km
    assert distancia_a_linha(*_deslocar(A, 1000, 1500), linha) == pytest.approx(500, rel=1e-3)  # o lado direito
    assert distancia_a_linha(*_deslocar(A, 1900, 300), linha) == pytest.approx(100, rel=1e-3)  # o lado de cima
    # Pela abertura do U, o mais perto são os cantos (0, 0) e (2000, 0): a hipotenusa 800–1000.
    assert distancia_a_linha(*_deslocar(A, 1000, -800), linha) == pytest.approx(math.hypot(800, 1000), rel=1e-3)


def test_um_grau_de_longitude_encurta_com_a_latitude():
    """A projeção usa o cosseno da latitude: 1 km para este mede 1 km, e não os metros de 1 km de latitude."""
    ponto = _deslocar(A, este_m=1000)
    assert distancia_a_linha(*ponto, [A]) == pytest.approx(1000, abs=1e-6)
    assert distancia_a_linha(*ponto, [A]) == pytest.approx(distancia_metros(*ponto, *A), rel=1e-4)


def test_contra_a_haversine_ate_5_km():
    """A projeção equirretangular local dá ±1 % contra a haversine até 5 km (o raio das sugestões)."""
    semente = random.Random(59)
    for _ in range(300):
        distancia = semente.uniform(0, 5000)
        angulo = semente.uniform(0, 2 * math.pi)
        ponto = _deslocar(A, distancia * math.cos(angulo), distancia * math.sin(angulo))
        assert distancia_a_linha(*ponto, [A]) == pytest.approx(distancia_metros(*ponto, *A), rel=1e-2, abs=0.01)


def test_a_rejeicao_por_caixa_nunca_deixa_de_fora_um_ponto_dentro_de_3_km():
    """100 pontos ao acaso contra a força bruta (o mesmo cálculo sem rejeitar nada, `limite=inf`)."""
    semente = random.Random(2026)
    linha = [_deslocar(A, semente.uniform(0, 10_000), semente.uniform(0, 10_000)) for _ in range(40)]
    dentro = rejeitados = 0
    for _ in range(100):
        lat, lng = _deslocar(A, semente.uniform(-6000, 16_000), semente.uniform(-6000, 16_000))
        bruta = distancia_a_linha(lat, lng, linha, math.inf)
        com_caixa = distancia_a_linha(lat, lng, linha, CORREDOR_M)
        if bruta <= CORREDOR_M:
            dentro += 1
            assert com_caixa == pytest.approx(bruta, abs=1e-6)
        else:
            # Acima do limite o valor só diz "passa do limite": um troço mais perto pode ter sido rejeitado.
            assert com_caixa > CORREDOR_M
            assert com_caixa >= bruta - 1e-6
            rejeitados += com_caixa == math.inf or com_caixa > bruta + 1e-6
    assert dentro >= 20 and rejeitados >= 5  # o cenário tem dos dois


def test_o_limite_rejeita_um_troco_longe_num_dos_eixos():
    ponto = _deslocar(A, 4000, 1000)
    assert distancia_a_linha(*ponto, TROCO) == pytest.approx(4000, abs=1e-6)
    assert distancia_a_linha(*ponto, TROCO, 3000) == math.inf
    assert distancia_a_linha(*ponto, TROCO, 4001) == pytest.approx(4000, abs=1e-6)


def test_o_limite_e_por_omissao_infinito():
    ponto = _deslocar(A, 40_000, 1000)
    assert distancia_a_linha(*ponto, TROCO) == pytest.approx(40_000, rel=1e-3)


def test_a_linha_da_distancia_pode_vir_em_listas():
    ponto = _deslocar(A, 1000, 1000)
    assert distancia_a_linha(*ponto, [list(p) for p in TROCO]) == pytest.approx(1000, abs=1e-6)


@pytest.mark.parametrize("limite", [-1, "3000", None, True, math.nan, [3000]])
def test_o_limite_tem_de_ser_um_numero_nao_negativo(limite):
    with pytest.raises(ValueError):
        distancia_a_linha(*A, TROCO, limite)


@pytest.mark.parametrize("linha", ["abc", 3, None, {(38.7, -9.1)}, (p for p in [(38.7, -9.1)])])
def test_a_linha_da_distancia_tem_de_ser_uma_lista(linha):
    with pytest.raises(TypeError):
        distancia_a_linha(*A, linha)


@pytest.mark.parametrize("linha", [[(38.7,)], [(38.7, "x")], [(math.nan, -9.1)], [(True, -9.1)], [(91, -9.1)], [None]])
def test_um_ponto_estragado_na_distancia(linha):
    with pytest.raises(ValueError):
        distancia_a_linha(*A, linha)


@pytest.mark.parametrize("lat, lng", [(math.nan, -9.1), (38.7, math.inf), (True, -9.1), ("38.7", -9.1), (91, -9.1), (38.7, None)])
def test_o_ponto_da_distancia_tem_de_ser_valido(lat, lng):
    with pytest.raises(ValueError):
        distancia_a_linha(lat, lng, TROCO)


# --- O módulo -------------------------------------------------------------------------------------


def test_sugestoes_nunca_chama_o_round_do_python():
    """O `round` arredonda para o par (5000,5 → 5000): usa-se `numeros.arredondar`."""
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []


def test_sugestoes_nao_le_o_relogio_nem_a_rede():
    """A data vem de fora e nada sai: o módulo é puro."""
    nomes = set()
    for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes |= {alias.name.split(".")[0] for alias in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module.split(".")[0])
    assert nomes & {"relogio", "time", "zoneinfo", "pytz", "os", "httpx", "requests", "urllib", "socket", "dotenv", "random"} == set()
