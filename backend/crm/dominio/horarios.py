"""As chegadas, as esperas e os avisos da rota, e a assinatura do cálculo (F3).

Plano F3 §1 ("Chegadas", "Horas"). As horas vêm **só do Directions**: das
durações dos troços (`directions.Trocos.duracoes`: do início à 1.ª paragem,
…, da última ao fim), da hora de saída e, por paragem, do tempo de serviço e
das janelas de receção (`vroom.ParagemCalculo`):

- chegada = partida anterior + duração do troço;
- se chegar antes da janela, espera pela abertura, também pela 2.ª janela do
  dia, sem aviso. O serviço tem de acabar dentro da janela (`início + serviço
  ≤ fim`): é a regra do VROOM (`horas.janelas_vroom`, `[a, b − s]` = o
  último início possível), e o início é o mais cedo possível;
- `fora_de_horario` só quando nenhuma janela do dia leva o serviço. Aí
  serve-se à chegada, sem espera;
- o regresso previsto vem no fim, com `depois_do_limite` quando passa da hora
  limite, contada pelo minuto que se mostra (19:00:20 é "19:00" e não passa
  das 19:00);
- uma hora a partir das 24:00 (depois de arredondar ao minuto) é `None`, com
  o aviso: a chegada fica `fora_de_horario` e o regresso `depois_do_limite`.

A espera é a diferença entre os minutos mostrados (o início do serviço menos
a chegada, cada um arredondado como a hora), por isso a chegada mostrada mais
a espera dá sempre a hora da abertura.

As contas fazem-se em segundos desde a meia-noite local (`horas`), nunca com
instantes: a data da rota nem entra, e as horas não mudam nos dias de mudança
de hora. Os troços somam-se sem o erro do float (`Fraction` do número tal
como se escreve, como o `numeros.arredondar`): 982,3 + 600 + 814,1 + 600 +
93,6 depois das 08:00 dá 08:51:30 certinho ("08:52") e não 08:51:29,999…
("08:51"), e um serviço que acaba no fecho da janela cabe.

`entrada_calculo` junta tudo o que decide as horas (e só isso: nunca nomes,
telefones, notas, o motivo nem a data) e `assinatura` dá o sha256 dela, que
fica em `calculo.assinatura`. As horas guardadas só servem (`calculo.atual`)
enquanto a assinatura da rota, tal como está, for a mesma: uma loja que mudou
de sítio, uma janela, a fábrica, a ordem, a saída, o limite ou as portagens
tornam-nas velhas.
"""
import hashlib
import json
from fractions import Fraction
from typing import NamedTuple, Optional

from . import horas
from .numeros import arredondar, e_inteiro_json, e_numero_json
from .vroom import ParagemCalculo, paragem_calculo

# A versão da forma da entrada: mudá-la torna velhas todas as horas guardadas.
VERSAO_ENTRADA = 1

CASAS_COORDENADAS = 6

SEGUNDOS_POR_DIA = 86400


class Horarios(NamedTuple):
    """As horas de uma rota: por paragem (pelo id, pela ordem recebida)
    `{chegada_prevista: "HH:MM"|None, espera_min: int, fora_de_horario: bool}`;
    o regresso em segundos desde a meia-noite (`float`, pode passar das 24:00),
    em "HH:MM" (`None` a partir das 24:00) e se passa da hora limite."""

    por_paragem: dict
    regresso_s: float
    regresso_previsto: Optional[str]
    depois_do_limite: bool


def calcular_horarios(saida_s, limite_s, paragens, duracoes) -> Horarios:
    """As horas da rota pela ordem das `paragens` (`ParagemCalculo`), com as
    `duracoes` dos troços em segundos (uma a mais do que as paragens).

    `saida_s` e `limite_s` são segundos do dia (`horas.segundos`); o limite só
    decide o aviso, por isso não se exige que seja depois da saída (isso é do
    validador e do VROOM). O que não é uma lista ou um tuplo é `TypeError`;
    um troço a mais ou a menos, uma duração que não é um número ≥ 0, uma
    paragem repetida ou com o serviço ou as janelas estragadas são
    `ValueError`. Devolve estruturas novas e não muda o que recebe.
    """
    _segundos_do_dia(saida_s, "saída")
    _segundos_do_dia(limite_s, "hora limite")
    if not isinstance(paragens, (list, tuple)) or not isinstance(duracoes, (list, tuple)):
        raise TypeError("calcular_horarios recebe listas de paragens e de durações.")
    if len(duracoes) != len(paragens) + 1:
        raise ValueError("Tem de haver um troço a mais do que as paragens (do início ao fim).")
    trocos = [_exato(duracao) for duracao in duracoes]

    por_paragem = {}
    relogio = Fraction(saida_s)
    for paragem, troco in zip(paragens, trocos):
        if not isinstance(paragem, ParagemCalculo):
            raise TypeError("calcular_horarios recebe ParagemCalculo (vroom.paragem_calculo).")
        if paragem.id in por_paragem:
            raise ValueError(f"Paragem repetida no cálculo: {paragem.id!r}")
        chegada = relogio + troco
        chegada_prevista = horas.hora_de_segundos(float(chegada))
        inicio = _inicio_do_servico(chegada, horas.janelas_vroom(paragem.janelas_s, paragem.servico_s))
        fora = inicio is None or chegada_prevista is None
        if inicio is None:
            inicio = chegada
        por_paragem[paragem.id] = {
            "chegada_prevista": chegada_prevista,
            "espera_min": _minuto(inicio) - _minuto(chegada),
            "fora_de_horario": fora,
        }
        relogio = inicio + paragem.servico_s

    regresso = relogio + trocos[-1]
    regresso_previsto = horas.hora_de_segundos(float(regresso))
    depois = regresso_previsto is None or horas.segundos(regresso_previsto) > limite_s
    return Horarios(por_paragem, float(regresso), regresso_previsto, depois)


def _inicio_do_servico(chegada, janelas):
    """O início do serviço mais cedo possível (à chegada ou à abertura de uma
    janela), ou `None` quando nenhuma janela o leva. `janelas` são as do
    `horas.janelas_vroom`: `[abertura, último início]`; `None` = sem restrição."""
    if janelas is None:
        return chegada
    possiveis = [max(chegada, abertura) for abertura, ultimo in janelas if max(chegada, abertura) <= ultimo]
    return min(possiveis) if possiveis else None


def _minuto(segundos) -> int:
    # O minuto como se mostra: o mesmo arredondamento do `horas.hora_de_segundos`.
    return horas.minutos_de_segundos(float(segundos))


def _exato(duracao) -> Fraction:
    """Uma duração do Directions (número do JSON ≥ 0) como fração exata do
    número tal como se escreve (0,1 é 1/10, e não o binário mais perto)."""
    if not e_numero_json(duracao) or duracao < 0:
        raise ValueError(f"Duração de troço inválida: {duracao!r}")
    return Fraction(repr(duracao))


def _segundos_do_dia(valor, nome):
    if not e_inteiro_json(valor) or not 0 <= valor < SEGUNDOS_POR_DIA:
        raise ValueError(f"A {nome} tem de ser um inteiro de segundos do dia: {valor!r}")


def entrada_calculo(rota, incluidas_com_lojas, inicio, fim) -> dict:
    """Tudo o que decide as horas da rota, e só isso:

    `{"v": 1, "saida", "limite", "inicio": [lat, lng], "fim": [lat, lng],
    "evitar_portagens", "paragens": [[id, lat, lng, serviço_min, [[início_s,
    fim_s]…]]…]}`, com as horas em segundos, as coordenadas em texto com 6
    casas (meio-para-longe-do-zero, como se guardam) e as janelas de receção
    (`[]` = sem restrição).

    Da `rota` só lê `hora_saida`, `hora_regresso_limite` e `evitar_portagens`
    (nunca a data); `incluidas_com_lojas` são os pares `(paragem, loja)` que
    entram no cálculo, pela ordem da rota, e de cada um só se lê o que o
    `vroom.paragem_calculo` lê; `inicio` e `fim` são pares `(lat, lng)` já
    resolvidos (a fábrica quando a rota não tem ponto). O que não é uma lista
    de pares é `TypeError`; uma hora, um ponto, as portagens ou uma paragem
    estragados são `ValueError`. Devolve estruturas novas.
    """
    evitar = rota["evitar_portagens"]
    if type(evitar) is not bool:
        raise ValueError("evitar_portagens tem de ser True ou False.")
    saida = horas.segundos(rota["hora_saida"])
    limite = horas.segundos(rota["hora_regresso_limite"])
    if not isinstance(incluidas_com_lojas, (list, tuple)):
        raise TypeError("entrada_calculo recebe uma lista de pares (paragem, loja).")
    paragens = []
    for par in incluidas_com_lojas:
        if not isinstance(par, (list, tuple)) or len(par) != 2:
            raise TypeError("Cada paragem incluída é um par (paragem, loja).")
        calculo = paragem_calculo(*par)
        paragens.append([
            calculo.id,
            _coordenada(calculo.lat),
            _coordenada(calculo.lng),
            calculo.servico_s // horas.SEGUNDOS_POR_MINUTO,
            [[abertura, fecho] for abertura, fecho in calculo.janelas_s or []],
        ])
    return {
        "v": VERSAO_ENTRADA,
        "saida": saida,
        "limite": limite,
        "inicio": _ponto(inicio),
        "fim": _ponto(fim),
        "evitar_portagens": evitar,
        "paragens": paragens,
    }


def _ponto(par) -> list:
    if not isinstance(par, (list, tuple)) or len(par) != 2:
        raise ValueError("Um ponto é um par (lat, lng).")
    return [_coordenada(par[0]), _coordenada(par[1])]


def _coordenada(valor) -> str:
    if not e_numero_json(valor):
        raise ValueError("Uma coordenada tem de ser um número.")
    return f"{arredondar(valor, CASAS_COORDENADAS):.{CASAS_COORDENADAS}f}"


def assinatura(entrada) -> str:
    """`"sha256:<64 hex>"` do JSON canónico da `entrada` (chaves por ordem,
    sem espaços, UTF-8 sem escapes). Um NaN é `ValueError`; o que não é um
    objeto é `TypeError`."""
    if not isinstance(entrada, dict):
        raise TypeError("A assinatura é de uma entrada do cálculo (um objeto).")
    texto = json.dumps(entrada, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()
