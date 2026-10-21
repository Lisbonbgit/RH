"""O cliente do openrouteservice: a otimização (VROOM) e o Directions.

Plano F3, T3.11 (§1 "openrouteservice" e "Testes do ORS"; §0, regras 2, 8 e
12; risco R1) e dossiê §8. O molde é o cliente da Geoapify (`geoapify.py`,
fim do ficheiro): reutiliza o `ler_json` e o `silenciar_registos` de lá.

- `otimizar(pedido)` faz um POST a `{base}/optimization` e `direcoes(pedido)`
  a `{base}/v2/directions/driving-car/json` (a base com ou sem barras no
  fim). O corpo é `json.dumps(pedido, allow_nan=False)`: um NaN é um engano
  do código (`ValueError`), nunca uma `FalhaOrs`. Os pedidos são os de
  `dominio.vroom.pedido_otimizacao` e `dominio.directions.pedido_direcoes`,
  só com coordenadas, segundos, prioridades e índices (§0, regra 12).
- A chave (`CRM_ORS_CHAVE`) vai SÓ no cabeçalho `Authorization`, tal e qual
  (sem `Bearer`, sem aparar): nunca no URL, no corpo, nas mensagens das
  falhas nem nos registos. Este módulo nunca regista nada: quem chama
  regista só o `motivo`. Os registos `httpx`/`httpcore` voltam a WARNING
  antes de cada pedido (`geoapify.silenciar_registos`).
- A chave e o URL leem-se do ambiente a cada chamada (`chave()`,
  `url_base()`), ou vêm por parâmetro (`chave=`, `url=`). Sem chave,
  `FalhaOrs(tipo="sem_chave")` sem pedido nenhum.
- `url_base()` só aceita `https://…` ou `http://` para `127.0.0.1`,
  `localhost` ou `[::1]` (o simulador local): um `http://` para fora mandava
  a chave sem cifra, e um URL com utilizador trocava o `Authorization`. O
  resto é `FalhaOrs("CRM_ORS_URL recusado", "indisponivel")`, sem pedido
  (correção "T3.11 (CRM_ORS_URL e a chave em texto claro)").
- Não segue redireções. Tempos: 3 s para ligar; 15 s ao todo na otimização
  e 10 s no Directions (`asyncio.wait_for`, porque os tempos do httpx são
  por fase).
- As respostas (`interpretar_resposta`): 2xx com um objeto JSON → `dict`;
  uma lista, um corpo que não é JSON ou um NaN → `indisponivel`.
- Os erros (`interpretar_erro`, função pura): 429 → `limite`; um corpo
  `{"error": {"code": 2010, "message": "… coordinate N: …"}}` (ou o antigo
  "… point N: …") → `ponto_sem_estrada` com `indice == N` (o ORS conta as
  coordenadas a partir de 0; quem traduz o índice para a paragem é a rota);
  um 2010 sem número, o erro na forma do VROOM (`{"code": 3, "error":
  "<texto>"}`, com coordenadas no texto, que nunca sai daqui) e qualquer
  outro estado (401, 403 = quota diária esgotada ou chave inválida, 500…)
  → `indisponivel` com o motivo "estado HTTP N". Na otimização, um 2010
  dá também a mensagem geral (`indice_2010=False`): o índice não diria que
  paragem é; o "Recalcular horas" identifica-a (correção "T3.11").
- As falhas da rede (qualquer `Exception` do pedido, como na Geoapify: o
  `httpx.InvalidURL` não herda de `HTTPError` e as mensagens do httpx podem
  trazer o pedido) → `indisponivel` com "sem resposta (<Tipo>)". A
  `FalhaOrs` lança-se fora do `except`, sem a exceção do httpx como causa
  nem contexto.
- Os testes trocam `_transporte` por um `httpx.MockTransport`; `None` é o
  transporte normal do httpx. O `conftest.py` instala por omissão uma guarda
  que regista o pedido, responde 599 e faz o teste falhar no fim.
"""
import asyncio
import json
import os
import re
from typing import NamedTuple, Optional
from urllib.parse import urlsplit

import httpx

from crm.servicos import geoapify

VARIAVEL_CHAVE = "CRM_ORS_CHAVE"
VARIAVEL_URL = "CRM_ORS_URL"
URL_POR_OMISSAO = "https://api.openrouteservice.org"

CAMINHO_OTIMIZACAO = "/optimization"
CAMINHO_DIRECOES = "/v2/directions/driving-car/json"

# 3 s para ligar; 15 s ao todo na otimização e 10 s no Directions (plano §1:
# o `otimizar` da T3.22 fica abaixo dos 25 s, contra os 35 s do cliente).
TEMPO_OTIMIZACAO = httpx.Timeout(15.0, connect=3.0)
TOTAL_OTIMIZACAO_S = 15.0
TEMPO_DIRECOES = httpx.Timeout(10.0, connect=3.0)
TOTAL_DIRECOES_S = 10.0

TIPOS = ("sem_chave", "indisponivel", "limite", "ponto_sem_estrada")

# O código do Directions para um ponto longe de qualquer estrada.
CODIGO_PONTO_SEM_ESTRADA = 2010

# Os anfitriões a que a chave pode ir sem cifra (só o simulador local).
ANFITRIOES_LOCAIS = ("127.0.0.1", "localhost", "::1")

# Os caracteres que um URL base pode ter (RFC 3986 sem `?`, `#` nem espaços,
# e sem `@`: assim nunca há um utilizador no URL a trocar o `Authorization`).
# O `urlsplit` ignora um espaço ou uma quebra de linha nas pontas, por isso o
# texto confere-se antes, tal e qual.
_CARACTERES_DE_URL = re.compile(r"[A-Za-z0-9\-._~%!$&'()*+,;=:/\[\]]+")

# "… of specified coordinate N: …" (ORS atual) e "Could not find point N: …"
# (antigo): só algarismos ASCII (o `\\d` apanhava os de outras escritas) e no
# máximo 6, para um número gigante não contar.
_PONTO_DO_2010 = re.compile(r"\b(?:coordinate|point)\s+([0-9]{1,6})\b", re.IGNORECASE)

# Os testes trocam isto por um `httpx.MockTransport`; `None` é o transporte
# normal do httpx.
_transporte = None


class FalhaOrs(Exception):
    """O openrouteservice não deu uma resposta que sirva. O `motivo` é para
    os registos e nunca traz a chave, o URL, o corpo nem coordenadas: só o
    estado HTTP ou o tipo da exceção. O `tipo` é um de `TIPOS`; `indice` só
    vem com `ponto_sem_estrada` (a coordenada, a contar de 0)."""

    def __init__(self, motivo: str, tipo: str, indice: Optional[int] = None):
        if tipo not in TIPOS:
            raise ValueError(f"Tipo de FalhaOrs desconhecido: {tipo!r}.")
        super().__init__(motivo)
        self.motivo = motivo
        self.tipo = tipo
        self.indice = indice

    def __repr__(self) -> str:
        return f"FalhaOrs(motivo={self.motivo!r}, tipo={self.tipo!r}, indice={self.indice!r})"


class RespostaOrs(NamedTuple):
    """A resposta tal como veio: o estado HTTP e o corpo em bytes."""

    estado: int
    corpo: bytes


def chave() -> str:
    """A chave, lida do ambiente a cada chamada ("" sem ela). Só a chave vazia
    conta como "sem chave" (como a da Geoapify)."""
    return os.environ.get(VARIAVEL_CHAVE, "")


def url_base() -> str:
    """O `CRM_ORS_URL`, lido a cada chamada; sem ele, ou vazio, o
    openrouteservice (`URL_POR_OMISSAO`). Um URL que não seja `https://…`
    nem `http://` para um anfitrião local é `FalhaOrs("CRM_ORS_URL
    recusado")`."""
    valor = os.environ.get(VARIAVEL_URL) or URL_POR_OMISSAO
    _conferir_url(valor)
    return valor


def url_aceite(valor) -> bool:
    """`https://` para qualquer anfitrião, ou `http://` só para `127.0.0.1`,
    `localhost` e `[::1]`; sempre sem utilizador, sem `?` nem `#`, sem
    espaços nem caracteres de controlo, com um anfitrião e uma porta válida.
    Um caminho (`https://ors.teste:8443/ors`) pode ficar."""
    if not isinstance(valor, str) or not _CARACTERES_DE_URL.fullmatch(valor):
        return False
    try:
        partes = urlsplit(valor)
        partes.port  # noqa: B018 — levanta ValueError com uma porta inválida
    except ValueError:
        return False
    if not partes.hostname:
        return False
    if partes.scheme == "https":
        return True
    return partes.scheme == "http" and partes.hostname in ANFITRIOES_LOCAIS


def _conferir_url(valor: str) -> None:
    if not url_aceite(valor):
        raise FalhaOrs("CRM_ORS_URL recusado", "indisponivel")


def _servico(nome: str):
    """`(caminho, tempos do httpx, total em segundos)` do serviço. As
    constantes leem-se aqui, a cada chamada (os testes encurtam o total)."""
    if nome == "otimizacao":
        return CAMINHO_OTIMIZACAO, TEMPO_OTIMIZACAO, TOTAL_OTIMIZACAO_S
    if nome == "direcoes":
        return CAMINHO_DIRECOES, TEMPO_DIRECOES, TOTAL_DIRECOES_S
    raise ValueError(f"Serviço do openrouteservice desconhecido: {nome!r}.")


def _corpo(pedido) -> bytes:
    """O corpo do POST. O que não é um objeto é um engano do código
    (`TypeError`), e um NaN ou infinito também (`ValueError`): nunca uma
    `FalhaOrs`, que daria um 503 a esconder o engano."""
    if not isinstance(pedido, dict):
        raise TypeError("O pedido ao openrouteservice tem de ser um dicionário.")
    return json.dumps(pedido, allow_nan=False).encode("utf-8")


def _chave(valor) -> str:
    """A chave por parâmetro (`None` = a do ambiente). Vazia → `sem_chave`."""
    if valor is None:
        valor = chave()
    elif not isinstance(valor, str):
        raise TypeError("A chave do openrouteservice tem de ser texto.")
    if valor == "":
        raise FalhaOrs("sem chave", "sem_chave")
    return valor


def _url(valor) -> str:
    """O URL base por parâmetro (`None` = o do ambiente), conferido."""
    if valor is None:
        return url_base()
    if not isinstance(valor, str):
        raise TypeError("O URL do openrouteservice tem de ser texto.")
    _conferir_url(valor)
    return valor


async def enviar(servico: str, pedido: dict, chave: Optional[str] = None, url: Optional[str] = None) -> RespostaOrs:
    """POST do `pedido` ao `servico` ("otimizacao" ou "direcoes"); devolve o
    estado e o corpo tal como vieram, sem os interpretar.

    Lança `FalhaOrs` sem chave (sem pedido), com um URL base recusado (sem
    pedido), sem resposta a tempo ou com qualquer exceção do pedido."""
    caminho, tempo, total = _servico(servico)
    corpo = _corpo(pedido)
    cabecalhos = {"Authorization": _chave(chave), "Content-Type": "application/json", "Accept": "application/json"}
    destino = _url(url).rstrip("/") + caminho

    geoapify.silenciar_registos()
    motivo = None
    resposta = None

    try:
        async with httpx.AsyncClient(timeout=tempo, transport=_transporte, follow_redirects=False) as cliente:
            resposta = await asyncio.wait_for(cliente.post(destino, content=corpo, headers=cabecalhos), total)
    except Exception as exc:  # noqa: BLE001 — ver a docstring do módulo (InvalidURL, o pedido na mensagem)
        motivo = f"sem resposta ({type(exc).__name__})"

    if motivo is not None:
        raise FalhaOrs(motivo, "indisponivel")

    return RespostaOrs(resposta.status_code, resposta.content)


async def otimizar(pedido: dict, chave: Optional[str] = None, url: Optional[str] = None) -> dict:
    """POST a `/optimization`; devolve o objeto JSON da resposta. Um 2010
    aqui é `indisponivel` (a mensagem geral)."""
    resposta = await enviar("otimizacao", pedido, chave=chave, url=url)
    return interpretar_resposta(resposta.estado, resposta.corpo, indice_2010=False)


async def direcoes(pedido: dict, chave: Optional[str] = None, url: Optional[str] = None) -> dict:
    """POST a `/v2/directions/driving-car/json`; devolve o objeto JSON da
    resposta. Um 2010 é `ponto_sem_estrada` com o índice da coordenada."""
    resposta = await enviar("direcoes", pedido, chave=chave, url=url)
    return interpretar_resposta(resposta.estado, resposta.corpo)


def interpretar_resposta(estado: int, corpo: bytes, indice_2010: bool = True) -> dict:
    """O objeto JSON de um 2xx, ou a `FalhaOrs` que lhe corresponde
    (lançada). Com `indice_2010` falso, um `ponto_sem_estrada` passa a
    `indisponivel` sem índice, com o mesmo motivo."""
    if 200 <= estado <= 299:
        motivo = None
        dados = None

        try:
            dados = geoapify.ler_json(bytes(corpo))
        except ValueError as exc:
            motivo = f"resposta que não é JSON ({type(exc).__name__})"

        if motivo is None and not isinstance(dados, dict):
            motivo = "resposta que não é um objeto JSON"

        if motivo is None:
            return dados

        raise FalhaOrs(motivo, "indisponivel")

    falha = interpretar_erro(estado, corpo)

    if not indice_2010 and falha.tipo == "ponto_sem_estrada":
        falha = FalhaOrs(falha.motivo, "indisponivel")

    raise falha


def interpretar_erro(estado: int, corpo: bytes) -> FalhaOrs:
    """A `FalhaOrs` (devolvida, não lançada) de um estado fora de 2xx:

    - 429 → `limite`, seja qual for o corpo;
    - `{"error": {"code": 2010, "message": "… coordinate N: …"}}` (ou "…
      point N: …") → `ponto_sem_estrada` com `indice == N` e o motivo
      "estado HTTP N (código 2010)";
    - o resto (um 2010 sem número, o erro na forma do VROOM, um corpo que não
      é JSON, 401, 403, 500, 3xx…) → `indisponivel` com "estado HTTP N".

    O motivo nunca traz o corpo. Um estado que não é um inteiro ou um corpo
    que não é bytes são enganos do código (`TypeError`)."""
    if type(estado) is not int:
        raise TypeError("O estado HTTP tem de ser um inteiro.")
    if not isinstance(corpo, (bytes, bytearray)):
        raise TypeError("O corpo da resposta tem de ser bytes.")

    motivo = f"estado HTTP {estado}"

    if estado == 429:
        return FalhaOrs(motivo, "limite")

    indice = _indice_do_2010(corpo)

    if indice is not None:
        return FalhaOrs(f"{motivo} (código {CODIGO_PONTO_SEM_ESTRADA})", "ponto_sem_estrada", indice)

    return FalhaOrs(motivo, "indisponivel")


def _indice_do_2010(corpo) -> Optional[int]:
    """O número da coordenada de um erro 2010 do Directions, ou `None`: o
    `code` tem de ser o inteiro 2010 (nem texto, nem `bool`, nem 2010.0) e a
    `message` um texto com "coordinate N" ou "point N"."""
    try:
        dados = geoapify.ler_json(bytes(corpo))
    except ValueError:
        return None

    erro = dados.get("error") if isinstance(dados, dict) else None

    if not isinstance(erro, dict):
        return None

    codigo = erro.get("code")
    mensagem = erro.get("message")

    if type(codigo) is not int or codigo != CODIGO_PONTO_SEM_ESTRADA or not isinstance(mensagem, str):
        return None

    encontrado = _PONTO_DO_2010.search(mensagem)

    return int(encontrado.group(1)) if encontrado else None
