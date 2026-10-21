"""As definições que o admin pode mudar: a fábrica (F2) e as rotas (F3).

Porta de src/Dominio/Definicoes.php do CRM autónomo (dossiê §5.9). Os padrões
vivem aqui; a coleção `crm_definicoes` só guarda, em texto, o que o admin
alterou (`{chave, valor, atualizado_em, atualizado_por}`, upsert por `chave`,
T2.13). São a morada da fábrica (texto livre) e o ponto, que tem de ficar em
Portugal continental e se muda sempre com a latitude e a longitude juntas.

A F3 (plano F3, T3.5; §1 "Definições do CRM") junta as chaves das rotas, que
o autónomo não tem: a hora de saída e a de regresso por omissão ("HH:MM", hora
de Lisboa) e o tempo de serviço de cada motivo (`servico_<motivo>_min`,
minutos inteiros de 1 a 240, lidos pelo `rotas.servico_padrao`). Guardam-se em
texto como as da fábrica; o `combinar` devolve os minutos como `int`.

- `combinar(guardadas)`: as definições em vigor (os padrões com o que está
  guardado por cima), com as coordenadas e os minutos como números; é o que o
  `GET /definicoes` devolve e o centro do mapa (`/config`, T2.13).
- `alteracao(pedido)`: um PATCH → `(valores para gravar, erros)`.
- `coerencia(valores)`: o regresso depois da saída, sobre as definições em
  vigor juntas com os valores do pedido (a rota chama-a, T3.15).
"""
import re
from types import MappingProxyType

from . import campos_loja, janelas
from .geo import MENSAGEM_PORTUGAL, contem_latitude, contem_longitude
from .numeros import arredondar, e_inteiro_json, e_numero_json
from .validador_rota import MENSAGEM_TEMPO_SERVICO, TEMPO_SERVICO_MAXIMO, TEMPO_SERVICO_MINIMO

# Os valores por defeito, como se guardam (texto; coordenadas com 6 casas;
# minutos como `str(n)`), pela ordem em que aparecem no ecrã e nos erros. Só
# de leitura: é partilhado por todos os pedidos.
PADROES = MappingProxyType(
    {
        "fabrica_morada": "",
        "fabrica_lat": "38.722300",
        "fabrica_lng": "-9.139300",
        "rota_hora_saida": "08:00",
        "rota_hora_regresso": "19:00",
        "servico_entrega_min": "10",
        "servico_amostra_min": "10",
        "servico_acompanhamento_min": "15",
        "servico_angariacao_min": "15",
    }
)

# As chaves das rotas, pela ordem dos PADROES.
HORAS = ("rota_hora_saida", "rota_hora_regresso")
MINUTOS = ("servico_entrega_min", "servico_amostra_min", "servico_acompanhamento_min", "servico_angariacao_min")

# Igual à morada das lojas (campos_loja/validador_loja).
MORADA_MAXIMO = 255

MENSAGEM_DESCONHECIDA = "Esta definição não existe."
# As do plano F3 §4. O tempo de serviço tem o texto (e os limites) do de cada
# paragem (validador_rota, T3.4).
MENSAGEM_HORA = "Indique a hora no formato HH:MM."
MENSAGEM_COERENCIA = "A hora de regresso tem de ser depois da hora de saída."

# O único texto de minutos que se lê de volta: o `str(n)` que a alteracao
# grava (sem zeros à esquerda, sinais, espaços nem algarismos que não sejam
# ASCII, que o int() do Python aceitava).
_MINUTOS_GUARDADOS = re.compile(r"[1-9][0-9]{0,2}")

# O número no início de um texto, como o lê o `(float)` do PHP (zend_strtod):
# só os espaços " \t\n\r\v\f" antes, algarismos ASCII, um ponto, expoente só
# com algarismos; o resto do texto ignora-se. Nada de "inf", "nan", "1_000",
# hexadecimal nem algarismos Unicode, que o float() do Python aceitava.
_NUMERO_NO_INICIO = re.compile(r"[ \t\n\r\x0b\x0c]*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)")


def combinar(guardadas: dict) -> dict:
    """As definições em vigor: os padrões com o que está guardado por cima, e
    as coordenadas como números (`float`).

    `guardadas` é `{chave: valor}` como está na coleção (texto). As chaves que
    esta versão não conhece (ex.: gravadas por uma versão mais nova)
    ignoram-se. A morada sai tal e qual. Uma coordenada guardada lê-se como o
    `(float)` do PHP: o número no início do texto, ou 0,0 se não houver —
    nunca rebenta. Um número escrito à mão na base lê-se como o número; o que
    não for texto nem número é um erro de programação (`TypeError`).

    As horas das rotas saem em texto e os minutos como `int`. Um valor das
    rotas estragado (fora do formato que a alteracao grava, ou que nem é
    texto) volta ao padrão dessa chave, sem rebentar: não vem do autónomo,
    e um dia de trabalho não pode parar por uma linha mexida à mão.
    """
    valores = {**PADROES, **guardadas}

    return {
        "fabrica_morada": valores["fabrica_morada"],
        "fabrica_lat": _float_do_php(valores["fabrica_lat"]),
        "fabrica_lng": _float_do_php(valores["fabrica_lng"]),
        **{chave: _hora_guardada(valores[chave], PADROES[chave]) for chave in HORAS},
        **{chave: _minutos_guardados(valores[chave], PADROES[chave]) for chave in MINUTOS},
    }


def alteracao(pedido: dict):
    """Um PATCH: só as chaves enviadas → `(valores para gravar, erros)`.

    Ambos pela ordem dos `PADROES` e depois as chaves desconhecidas (pela
    ordem em que chegaram); os valores só se usam quando não há erros.

    - `fabrica_morada`: texto até 255 caracteres, aparado; vazia ou null
      fica "".
    - `fabrica_lat` / `fabrica_lng`: um número do JSON, arredondado às 6
      casas com que se guarda (meio-para-longe-do-zero) e só depois visto
      contra Portugal continental; guarda-se em texto com 6 casas ("%.6f").
      Vão sempre juntas: conta a chave, mesmo com null.
    - `rota_hora_saida` / `rota_hora_regresso`: "HH:MM" (`janelas.hora`),
      nunca vazia; guarda-se tal e qual. A alteracao não as compara entre si:
      isso é a `coerencia`, sobre os valores já juntos com os em vigor.
    - `servico_<motivo>_min`: um inteiro do JSON de 1 a 240 (nunca bool,
      `10.0` nem `"10"`); guarda-se em texto, `str(n)`.
    - Com erro, o valor é "" (como as coordenadas).
    - Uma chave que não seja dos `PADROES` dá "Esta definição não existe.".
    """
    valores = {}
    erros = {}

    for chave, valor in pedido.items():
        if chave in PADROES:
            valores[chave], erros[chave] = _VALIDAR[chave](valor)

    # O `+=` do PHP não substitui um erro que já lá esteja.
    for chave, erro in _falta_o_par(pedido).items():
        erros.setdefault(chave, erro)

    for chave in pedido:
        if chave not in PADROES:
            erros[chave] = MENSAGEM_DESCONHECIDA

    erros = {chave: erro for chave, erro in erros.items() if erro is not None}

    return _ordenar(valores), _ordenar(erros)


def coerencia(valores: dict) -> dict:
    """`{"rota_hora_regresso": erro}` se o regresso não for depois da saída
    (a mesma hora também é erro), senão `{}`.

    Recebe as definições em vigor juntas com os valores do pedido (só lê as
    duas horas), cada uma "HH:MM" válida: "HH:MM" tem largura fixa, por isso
    comparar o texto é comparar a hora. O resto (uma hora em falta ou mal
    escrita) é um erro de programação: `ValueError`.
    """
    saida = valores.get("rota_hora_saida")
    regresso = valores.get("rota_hora_regresso")
    for hora in (saida, regresso):
        if not _e_hora(hora):
            raise ValueError(f"A coerência compara horas já validadas (HH:MM), não {hora!r}.")
    if regresso <= saida:
        return {"rota_hora_regresso": MENSAGEM_COERENCIA}
    return {}


def _e_hora(valor) -> bool:
    """Uma hora "HH:MM" válida e não vazia (`janelas.hora`)."""
    return isinstance(valor, str) and janelas.hora(valor) == (valor, None)


def _e_minutos(valor) -> bool:
    """Um tempo de serviço válido: um inteiro do JSON de 1 a 240 (nunca um bool)."""
    return e_inteiro_json(valor) and TEMPO_SERVICO_MINIMO <= valor <= TEMPO_SERVICO_MAXIMO


def _hora(valor):
    """`(hora, erro)`: a hora tal e qual, ou "" com o erro (vazia também é erro)."""
    return (valor, None) if _e_hora(valor) else ("", MENSAGEM_HORA)


def _minutos(valor):
    """`(minutos em texto, erro)`: `str(n)`, ou "" com o erro."""
    return (str(valor), None) if _e_minutos(valor) else ("", MENSAGEM_TEMPO_SERVICO)


def _hora_guardada(valor, padrao: str) -> str:
    """Uma hora guardada, ou o padrão se estiver estragada."""
    return valor if _e_hora(valor) else padrao


def _minutos_guardados(valor, padrao: str) -> int:
    """Os minutos guardados como `int`, ou os do padrão se estiverem estragados."""
    if isinstance(valor, str) and _MINUTOS_GUARDADOS.fullmatch(valor) and _e_minutos(int(valor)):
        return int(valor)
    return int(padrao)


def _morada(valor):
    """`(morada, erro)`: vazia, null ou com erro fica "" (o `$morada ?? ''` do PHP)."""
    morada, erro = campos_loja.texto(valor, "A morada", MORADA_MAXIMO)
    return ("" if morada is None else morada), erro


def _coordenada(valor, nome: str, dentro):
    """`(texto com 6 casas, erro)`. Não sendo um número do JSON, o texto é ""."""
    if not e_numero_json(valor):
        return "", f"{nome} tem de ser um número."

    arredondada = arredondar(valor, 6)

    return _seis_casas(arredondada), (None if dentro(arredondada) else MENSAGEM_PORTUGAL)


def _seis_casas(numero: float) -> str:
    """O `sprintf('%.6F', …)` do PHP. O PHP escreve o −0,0 sem sinal
    ("0.000000"); o "%.6f" do Python escrevia "-0.000000": somar 0,0 tira-lho."""
    return "%.6f" % (numero + 0.0)


_VALIDAR = {
    "fabrica_morada": _morada,
    "fabrica_lat": lambda valor: _coordenada(valor, "A latitude", contem_latitude),
    "fabrica_lng": lambda valor: _coordenada(valor, "A longitude", contem_longitude),
    **{chave: _hora for chave in HORAS},
    **{chave: _minutos for chave in MINUTOS},
}


def _falta_o_par(pedido: dict) -> dict:
    """O ponto muda-se inteiro: a latitude sem a longitude (ou o contrário) dá erro na que falta."""
    lat = "fabrica_lat" in pedido
    lng = "fabrica_lng" in pedido

    if lat and not lng:
        return {"fabrica_lng": "Indique também a longitude."}
    if lng and not lat:
        return {"fabrica_lat": "Indique também a latitude."}
    return {}


def _ordenar(por_chave: dict) -> dict:
    """As chaves dos `PADROES` pela ordem deles, e depois as outras pela ordem
    em que estão (o `array_replace(array_intersect_key(PADROES, …), …)` do PHP)."""
    return {**{chave: por_chave[chave] for chave in PADROES if chave in por_chave}, **por_chave}


def _float_do_php(valor) -> float:
    """O `(float)` do PHP sobre um valor guardado: o número no início do texto
    (0,0 se não houver); um número escrito à mão na base fica o número."""
    if isinstance(valor, str):
        numero = _NUMERO_NO_INICIO.match(valor)
        return float(numero.group(1)) if numero else 0.0
    if type(valor) in (int, float):
        return float(valor)
    raise TypeError(f"uma definição guarda-se em texto, não {type(valor).__name__}")
