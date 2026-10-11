"""A polyline codificada (crm/dominio/polilinha.py), F3 / T3.7.

O Directions do openrouteservice devolve a linha da rota como uma polyline
codificada (o algoritmo da Google, precisão 5). A F3 guarda-a tal como vem em
`calculo.geometria` e descodifica-a para as sugestões no caminho (T3.9).

Correção "T3.7 / T3.9 / T3.13 / T3.21": o `codificar` nasce já aqui (e não
no simulador da T3.13), com o exemplo da Google nos dois sentidos e a ida e
volta `descodificar(codificar(p)) ≈ p` a 1e-5. O simulador, a T3.9 e os
testes das rotas importam-no daqui.

O arredondamento ao codificar é o das coordenadas guardadas (meio-para-longe-
do-zero, pelo texto do número, como o `numeros.arredondar`), nunca o `round`
do Python (que vai para o par) nem o corte (`int`).
"""
import ast
import copy
import math
import random
from pathlib import Path

import pytest

import crm.dominio.polilinha as polilinha
from crm.dominio.polilinha import codificar, descodificar

FICHEIRO = Path(polilinha.__file__)

# O exemplo da documentação da Google ("Encoded Polyline Algorithm Format").
EXEMPLO_GOOGLE = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
PONTOS_GOOGLE = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


# --- descodificar ---------------------------------------------------------------------------


def test_descodifica_o_exemplo_da_google():
    assert descodificar(EXEMPLO_GOOGLE) == PONTOS_GOOGLE


def test_descodifica_em_tuplos_de_floats():
    pontos = descodificar(EXEMPLO_GOOGLE)
    assert isinstance(pontos, list)
    assert all(type(ponto) is tuple and len(ponto) == 2 for ponto in pontos)
    assert all(type(valor) is float for ponto in pontos for valor in ponto)


def test_o_texto_vazio_nao_tem_pontos():
    assert descodificar("") == []


def test_um_so_ponto():
    assert descodificar("_p~iF~ps|U") == [(38.5, -120.2)]


def test_a_precisao_por_omissao_e_5():
    assert polilinha.PRECISAO == 5
    assert descodificar(EXEMPLO_GOOGLE, 5) == descodificar(EXEMPLO_GOOGLE)


def test_descodifica_com_a_precisao_6():
    """Os mesmos inteiros, divididos por 10⁶ em vez de 10⁵ (a polyline do OSRM e do Valhalla)."""
    assert descodificar(EXEMPLO_GOOGLE, 6) == [(3.85, -12.02), (4.07, -12.095), (4.3252, -12.6453)]


def test_descodifica_lisboa():
    """A linha de uma rota curta em Lisboa (fábrica → Marquês → Comércio), que o fixture do Directions usa."""
    assert descodificar("k}ikFr_xv@sDvVwGj\\kCvL") == [(38.7223, -9.1393), (38.7232, -9.1431), (38.7246, -9.1478), (38.7253, -9.15)]


def test_descodificar_devolve_uma_lista_nova_a_cada_chamada():
    primeira = descodificar(EXEMPLO_GOOGLE)
    segunda = descodificar(EXEMPLO_GOOGLE)
    assert primeira == segunda and primeira is not segunda


@pytest.mark.parametrize(
    "texto",
    [" ", "_p~iF~ps|U ", "_p~iF~ps|U\x7f", "_p~iF~ps|Ué", "=", "_p~iF\n~ps|U", "\x00",
     # Estes, lidos sem a verificação, davam um par completo (o bit 0x20 desligado):
     "\x7f\x7f", "\x00\x01", "_p~iF~ps|U\x7f\x7f", "\x80\x80"],
)
def test_um_caracter_fora_de_63_a_126_e_recusado(texto):
    with pytest.raises(ValueError):
        descodificar(texto)


@pytest.mark.parametrize("texto", [EXEMPLO_GOOGLE[:-1], "_", "_p~iF~ps|", "~"])
def test_um_pedaco_cortado_e_recusado(texto):
    """O último carácter de um valor tem o bit de continuação (0x20) desligado;
    um texto que acaba a meio de um valor está cortado."""
    with pytest.raises(ValueError):
        descodificar(texto)


@pytest.mark.parametrize("texto", ["_p~iF", "_p~iF~ps|U_ulL", "?"])
def test_uma_latitude_sem_longitude_e_recusada(texto):
    with pytest.raises(ValueError):
        descodificar(texto)


def test_um_valor_com_mais_de_12_blocos_e_recusado():
    """Uma coordenada a 5 casas cabe em 6 blocos de 5 bits; mais de 12 (60 bits)
    é uma resposta estragada. Sem limite, um texto de continuações sem fim fazia
    um inteiro enorme (e o trabalho crescia ao quadrado)."""
    with pytest.raises(ValueError):
        descodificar("~" * 12 + "?" + "?")
    with pytest.raises(ValueError):
        descodificar("~" * 10_000)


def test_um_valor_com_12_blocos_ainda_se_le():
    pontos = descodificar(("~" * 11 + "?") * 2)
    assert len(pontos) == 1
    assert all(math.isfinite(valor) for valor in pontos[0])


@pytest.mark.parametrize("texto", [None, b"_p~iF~ps|U", 123, ["_p~iF~ps|U"], ("_",)])
def test_descodificar_so_aceita_texto(texto):
    with pytest.raises(TypeError):
        descodificar(texto)


@pytest.mark.parametrize("precisao", [-1, 11, True, False, 5.0, "5", None])
def test_descodificar_recusa_uma_precisao_que_nao_e_um_inteiro_de_0_a_10(precisao):
    with pytest.raises(ValueError):
        descodificar(EXEMPLO_GOOGLE, precisao)


@pytest.mark.parametrize("precisao", [0, 1, 6, 10])
def test_as_precisoes_aceites(precisao):
    assert len(descodificar(EXEMPLO_GOOGLE, precisao)) == 3


# --- codificar ------------------------------------------------------------------------------


def test_codifica_o_exemplo_da_google():
    assert codificar(PONTOS_GOOGLE) == EXEMPLO_GOOGLE


def test_codifica_uma_lista_vazia_num_texto_vazio():
    assert codificar([]) == ""
    assert codificar(()) == ""


def test_codifica_um_so_ponto():
    assert codificar([(38.5, -120.2)]) == "_p~iF~ps|U"


def test_aceita_pares_em_tuplos_ou_listas_e_inteiros():
    assert codificar([[38.5, -120.2], (40.7, -120.95), [43.252, -126.453]]) == EXEMPLO_GOOGLE
    assert descodificar(codificar([(38, -9)])) == [(38.0, -9.0)]


def test_codifica_com_a_precisao_6():
    texto = codificar(PONTOS_GOOGLE, 6)
    assert texto != EXEMPLO_GOOGLE
    assert descodificar(texto, 6) == PONTOS_GOOGLE
    assert descodificar(texto, 5) == [(385.0, -1202.0), (407.0, -1209.5), (432.52, -1264.53)]


def test_arredonda_meio_para_longe_do_zero_pelo_texto_do_numero():
    """Como as coordenadas se guardam (`numeros.arredondar`): 38,7223445 → 38,722345
    e −9,1393005 → −9,139301 às 6 casas. O `round` do Python dava 38,722344 e
    −9,1393 (o binário destes números fica abaixo do meio) e o `int` cortava."""
    assert descodificar(codificar([(38.7223445, -9.1393005)], 6), 6) == [(38.722345, -9.139301)]
    assert descodificar(codificar([(0.000005, -0.000005)])) == [(0.00001, -0.00001)]
    assert descodificar(codificar([(0.0000049, -0.0000049)])) == [(0.0, 0.0)]


def test_os_negativos_e_os_positivos_nos_dois_sentidos():
    pontos = [(0.0, 0.0), (-0.00001, 0.00001), (0.00001, -0.00001), (-90.0, 180.0), (90.0, -180.0), (0.0, 0.0)]
    assert descodificar(codificar(pontos)) == pontos


def test_codificar_nao_muda_os_pontos():
    pontos = [[38.5, -120.2], [40.7, -120.95]]
    copia = copy.deepcopy(pontos)
    codificar(pontos)
    assert pontos == copia


@pytest.mark.parametrize("pontos", [None, "38.5,-120.2", {"lat": 38.5, "lng": -120.2}, 38.5, (p for p in PONTOS_GOOGLE)])
def test_codificar_so_aceita_uma_lista_de_pares(pontos):
    with pytest.raises(TypeError):
        codificar(pontos)


@pytest.mark.parametrize(
    "par",
    [None, (38.5,), (38.5, -120.2, 0), {"lat": 38.5, "lng": -120.2}, ("38.5", "-120.2"), (math.nan, 0.0),
     (0.0, math.inf), (-math.inf, 0.0), (True, 0.0), (0.0, False), "ab", 2**1100],
)
def test_codificar_recusa_um_ponto_que_nao_e_um_par_de_numeros(par):
    with pytest.raises(ValueError):
        codificar([(38.5, -120.2), par])


@pytest.mark.parametrize("par", [(90.000001, 0.0), (-90.000001, 0.0), (0.0, 180.000001), (0.0, -180.000001), (1e300, 0.0)])
def test_codificar_recusa_um_ponto_fora_do_mundo(par):
    with pytest.raises(ValueError):
        codificar([par])


@pytest.mark.parametrize("precisao", [-1, 11, True, 5.0, "5", None])
def test_codificar_recusa_uma_precisao_que_nao_e_um_inteiro_de_0_a_10(precisao):
    with pytest.raises(ValueError):
        codificar(PONTOS_GOOGLE, precisao)


# --- Ida e volta ----------------------------------------------------------------------------


def test_ida_e_volta_com_pontos_ao_acaso_no_mundo():
    """`descodificar(codificar(p)) ≈ p` a 1e-5 (meia unidade da 5.ª casa)."""
    acaso = random.Random(20261011)
    pontos = [(acaso.uniform(-90, 90), acaso.uniform(-180, 180)) for _ in range(1000)]
    volta = descodificar(codificar(pontos))
    assert len(volta) == len(pontos)
    for (lat, lng), (lat_v, lng_v) in zip(pontos, volta):
        assert abs(lat - lat_v) <= 1e-5 and abs(lng - lng_v) <= 1e-5


def test_ida_e_volta_exata_com_pontos_de_portugal_a_5_casas():
    acaso = random.Random(7)
    pontos = [(round(acaso.uniform(36.8, 42.2), 5), round(acaso.uniform(-9.6, -6.1), 5)) for _ in range(500)]
    assert descodificar(codificar(pontos)) == pontos


def test_ida_e_volta_exata_a_6_casas():
    acaso = random.Random(11)
    pontos = [(round(acaso.uniform(-90, 90), 6), round(acaso.uniform(-180, 180), 6)) for _ in range(500)]
    assert descodificar(codificar(pontos, 6), 6) == pontos


def test_ida_e_volta_com_pontos_repetidos():
    """Duas lojas nas mesmas coordenadas: o troço entre elas tem diferença zero."""
    pontos = [(38.7223, -9.1393), (38.7075, -9.1364), (38.7075, -9.1364), (38.7223, -9.1393)]
    assert descodificar(codificar(pontos)) == pontos


# --- O módulo -------------------------------------------------------------------------------


def test_polilinha_nunca_chama_o_round_do_python():
    chamadas = [
        no for no in ast.walk(ast.parse(FICHEIRO.read_text(encoding="utf-8")))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "round"
    ]
    assert chamadas == []
