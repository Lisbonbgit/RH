"""Os pedidos à Geoapify e as respostas no formato da API do CRM.

Porta de src/Servicos/Geoapify.php do CRM autónomo (plano T2.14; dossiê §8):
o URL e a normalização são funções puras, sem rede. No fim do ficheiro está
o cliente assíncrono (T2.15, porta do ClienteHttpCurl), que a rota
`/morada/inversa` (crm/morada.py) usa com o URL base (`CRM_GEOAPIFY_URL`) e
a chave do servidor (`CRM_GEOAPIFY_CHAVE_SERVIDOR`), lidos a cada pedido.

Desde a G18 do plano do mapa Google, a Geoapify fica só para a morada
sugerida do ponto do GPS: a pesquisa de moradas (o URL do autocomplete e o
seu limite de 5) saiu, porque é a da própria Google, no browser.

- Inversa: a morada de um ponto, em português, em `format=json`.
- As coordenadas vão com até 6 casas decimais (cerca de 10 cm), sem zeros no
  fim: o `number_format($v, 6, '.', '')` do PHP, que arredonda
  meio-para-longe-do-zero e, desde o PHP 8.0, nunca escreve "-0".
- O URL é o do `http_build_query(…, PHP_QUERY_RFC3986)`: cada nome e valor
  passa pelo `rawurlencode` (espaço → `%20`, só `A-Za-z0-9-_.~` ficam).

Cada resultado passa a `{rotulo, morada, codigo_postal, localidade, lat,
lng}`, por esta ordem: o rótulo mostra-se na "Morada sugerida" e o resto
preenche a loja.

- rotulo: o `formatted`.
- morada: a rua com o número de polícia ("Rua Augusta 24"). Sem rua fica
  `None`: o `address_line1` pode ser o nome de um sítio, e o nome e o
  telefone das lojas são sempre escritos pela pessoa (dossiê §0 e §5.15).
- codigo_postal: só no formato 0000-000 (a Geoapify às vezes só traz os 4
  primeiros algarismos).
- localidade: city, ou town, ou village, ou county.
- lat/lng: sempre `float` (um inteiro do JSON também).
- Ficam de fora os resultados sem coordenadas, sem rótulo, de outro país ou
  fora de Portugal continental (a carrinha não serve as ilhas; a loja não se
  poderia gravar).

Fidelidade ao PHP (conferida no PHP 8.4.26; dossiê §8):

- os textos aparam-se com o `trim()` do PHP, que só tira
  `" \\t\\n\\r\\0\\x0B"`, e não com o `texto.aparar` das escritas (que tira
  também os espaços Unicode e o U+FEFF): um rótulo com um espaço sem quebra
  nas pontas fica com ele. A pessoa revê a sugestão, e a loja, ao gravar,
  passa pelo validador, que apara;
- o país compara-se com o `strtolower` do PHP, que só mexe no ASCII;
- uma coordenada só conta se for um número do JSON (nunca um bool, um texto,
  NaN ou infinito) e estiver na caixa de Portugal continental;
- um `results` que seja um objeto JSON percorre-se pelos valores (o
  `json_decode(…, true)` do PHP fazia dele um array); uma resposta que não
  seja um objeto não tem resultados.

O cliente (T2.15) — a chave do servidor nunca vai para os registos:

- GET com `Accept: application/json`, sem seguir redireções, com 3 s para
  ligar, 5 s por leitura e 5 s para o pedido inteiro (o `CURLOPT_TIMEOUT_MS`
  do autónomo era o total; os tempos do httpx são por fase).
- Estado fora de 2xx, falha da rede, tempo esgotado, um URL base mal escrito
  ou uma resposta que o `json_decode` do PHP recusaria → `FalhaServicoExterno`,
  cujo `motivo` diz só o código HTTP ou o tipo da exceção. Apanha-se
  `Exception` e não só `httpx.HTTPError`: o `httpx.InvalidURL` (porta com
  letras no `CRM_GEOAPIFY_URL`) não herda dela, e as mensagens do httpx
  trazem o URL com a chave. A falha lança-se fora do `except`, sem arrastar
  a exceção do httpx como causa nem contexto.
- O httpx regista em INFO cada pedido com o URL inteiro: os registos `httpx`
  e `httpcore` ficam em WARNING à importação e outra vez antes de cada
  pedido (em todo o processo do portal; plano §1, "Geoapify").
- Os testes trocam `_transporte` por um `httpx.MockTransport` (molde de
  faturacao/pontos_app.py); `None` é o transporte normal do httpx.
"""
import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

import httpx

from crm.dominio.geo import contem_latitude, contem_longitude
from crm.dominio.numeros import arredondar

LOCALIDADE = ("city", "town", "village", "county")

# Os caracteres que o trim() do PHP tira sem segundo argumento.
_TRIM_DO_PHP = " \t\n\r\x00\x0b"

_CODIGO_POSTAL = re.compile(r"[0-9]{4}-[0-9]{3}")


def url_inversa(url_base: str, chave: str, lat: float, lng: float) -> str:
    """O URL da geocodificação inversa da Geoapify para o ponto (números já
    validados pela rota).

    `url_base` é o `CRM_GEOAPIFY_URL` (https://api.geoapify.com), com ou sem
    barras no fim.
    """
    parametros = [
        ("lat", _coordenada(lat)),
        ("lon", _coordenada(lng)),
        ("lang", "pt"),
        ("format", "json"),
        ("apiKey", chave),
    ]

    return _url(url_base, "reverse", parametros)


def normalizar_autocomplete(resposta) -> List[Dict]:
    """As sugestões válidas do JSON da Geoapify (já descodificado), pela
    ordem dela. Sem `results`, ou com um que não seja uma lista nem um
    objeto, `[]`. Não corta a lista.

    Ficou com o nome da pesquisa (o `normalizarAutocomplete` do autónomo),
    que saiu na G18: o `normalizar_inversa` assenta nele, porque o reverse da
    Geoapify responde no mesmo formato (`format=json`, uma lista `results`)
    que o autocomplete, e as respostas gravadas das duas provam-no."""
    resultados = resposta.get("results") if isinstance(resposta, dict) else None

    if isinstance(resultados, dict):
        resultados = list(resultados.values())

    if not isinstance(resultados, list):
        return []

    sugestoes = []

    for resultado in resultados:
        sugestao = _normalizar(resultado) if isinstance(resultado, dict) else None

        if sugestao is not None:
            sugestoes.append(sugestao)

    return sugestoes


def normalizar_inversa(resposta) -> Optional[Dict]:
    """O primeiro resultado válido da geocodificação inversa, ou `None`."""
    sugestoes = normalizar_autocomplete(resposta)

    return sugestoes[0] if sugestoes else None


def _normalizar(resultado: Dict) -> Optional[Dict]:
    lat = resultado.get("lat")
    lng = resultado.get("lon")
    pais = _texto(resultado.get("country_code"))
    rotulo = _texto(resultado.get("formatted"))

    # O contem_* só aceita números do JSON (o is_int || is_float do PHP, sem
    # bool, NaN nem infinito, que de qualquer modo ficavam fora da caixa).
    em_portugal = contem_latitude(lat) and contem_longitude(lng) and pais is not None and _e_pt(pais)

    if not em_portugal or rotulo is None:
        return None

    return {
        "rotulo": rotulo,
        "morada": _morada(resultado),
        "codigo_postal": _codigo_postal(resultado.get("postcode")),
        "localidade": _localidade(resultado),
        "lat": float(lat),
        "lng": float(lng),
    }


def _e_pt(pais: str) -> bool:
    """`strtolower($pais) === 'pt'`: o strtolower do PHP só mexe no ASCII, e
    um carácter que não seja ASCII nunca dá "pt"."""
    return pais.isascii() and pais.lower() == "pt"


def _morada(resultado: Dict) -> Optional[str]:
    rua = _texto(resultado.get("street"))
    numero = _texto(resultado.get("housenumber"))

    if rua is None:
        return None

    return rua if numero is None else f"{rua} {numero}"


def _codigo_postal(valor) -> Optional[str]:
    codigo = _texto(valor)

    return codigo if codigo is not None and _CODIGO_POSTAL.fullmatch(codigo) else None


def _localidade(resultado: Dict) -> Optional[str]:
    for campo in LOCALIDADE:
        localidade = _texto(resultado.get(campo))

        if localidade is not None:
            return localidade

    return None


def _url(url_base: str, servico: str, parametros: Sequence[Tuple[str, str]]) -> str:
    consulta = "&".join(f"{_rawurlencode(nome)}={_rawurlencode(valor)}" for nome, valor in parametros)

    return f"{url_base.rstrip('/')}/v1/geocode/{servico}?{consulta}"


def _rawurlencode(valor: str) -> str:
    """O `rawurlencode` do PHP (RFC 3986): os bytes que não são UTF-8 de uma
    variável de ambiente (a chave) chegam ao Python como surrogates
    (surrogateescape) e voltam a ser esses bytes."""
    return quote(valor.encode("utf-8", "surrogateescape"), safe="")


def _coordenada(valor) -> str:
    """Até 6 casas decimais, sem zeros no fim: 38.7223, -9.5, 39 (o
    `number_format` do PHP + `rtrim`). Somar 0,0 tira o sinal ao -0,0 de um
    negativo que arredonda a zero, como o PHP 8. Um valor que não seja um
    número do JSON dá `ValueError` (do `arredondar`)."""
    return ("%.6f" % (arredondar(valor, 6) + 0.0)).rstrip("0").rstrip(".")


def trim_do_php(texto: str) -> str:
    """O `trim()` do PHP sem segundo argumento: só tira `" \\t\\n\\r\\0\\x0B"`
    das pontas (nem os espaços Unicode nem o U+FEFF, ao contrário do
    `texto.aparar`)."""
    return texto.strip(_TRIM_DO_PHP)


def _texto(valor) -> Optional[str]:
    """Um texto sem espaços nas pontas (os do `trim()` do PHP); o que não for
    texto, ou ficar vazio, é `None`."""
    if not isinstance(valor, str):
        return None

    texto = trim_do_php(valor)

    return texto if texto != "" else None


# --- O cliente (T2.15) -------------------------------------------------------------------

VARIAVEL_CHAVE_SERVIDOR = "CRM_GEOAPIFY_CHAVE_SERVIDOR"
VARIAVEL_URL = "CRM_GEOAPIFY_URL"
URL_POR_OMISSAO = "https://api.geoapify.com"

# 3 s para ligar e 5 s para cada leitura (o TEMPO_LIGACAO_MS e o TEMPO_LIMITE_MS
# do ClienteHttpCurl) e 5 s para o pedido inteiro, como o CURLOPT_TIMEOUT_MS.
TEMPO_LIMITE = httpx.Timeout(5.0, connect=3.0)
TEMPO_TOTAL_SEGUNDOS = 5.0

CABECALHOS = {"Accept": "application/json"}

# Os níveis de listas e objetos que o `json_decode($corpo, true, 512)` do PHP
# 8.4 aceita: 511 (com 512 dá "Maximum stack depth exceeded").
PROFUNDIDADE_MAXIMA = 511

# Os registos que escreveriam o URL do pedido, com a chave.
REGISTOS_SILENCIADOS = ("httpx", "httpcore")

# Os testes trocam isto por um `httpx.MockTransport`; `None` é o transporte
# normal do httpx.
_transporte = None


class FalhaServicoExterno(Exception):
    """A Geoapify não deu uma resposta que sirva (a `FalhaServicoExterno` do
    autónomo). O `motivo` é para os registos e nunca traz o URL nem a chave:
    só o código HTTP ou o tipo da exceção."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def chave_servidor() -> str:
    """A chave do servidor, lida do ambiente a cada chamada ("" sem ela). Só
    a chave vazia conta como "sem chave" (o `$chave === ''` do autónomo)."""
    return os.environ.get(VARIAVEL_CHAVE_SERVIDOR, "")


def url_base() -> str:
    """O `CRM_GEOAPIFY_URL`, lido a cada chamada; sem ele, ou vazio, a
    Geoapify (`URL_POR_OMISSAO`)."""
    return os.environ.get(VARIAVEL_URL) or URL_POR_OMISSAO


def silenciar_registos() -> None:
    """Põe os registos `httpx` e `httpcore` em WARNING, se estiverem abaixo
    (um nível mais alto, posto por outro módulo, fica)."""
    for nome in REGISTOS_SILENCIADOS:
        registo = logging.getLogger(nome)

        if registo.level < logging.WARNING:
            registo.setLevel(logging.WARNING)


silenciar_registos()


def ler_json(corpo: bytes):
    """O corpo lido como o `json_decode($corpo, true, 512, JSON_THROW_ON_ERROR)`
    + `is_array` do ClienteHttpCurl: um objeto ou uma lista JSON em UTF-8.
    O resto dá `ValueError` — também o que o `json` do Python aceitava e o
    PHP não: NaN e infinitos escritos por extenso, UTF-16, mais de 511
    níveis (ou o RecursionError de muitos mais) e surrogates sozinhos (que,
    deixados passar, partiam a resposta da rota com 500)."""
    try:
        dados = json.loads(corpo.decode("utf-8"), parse_constant=_recusar_constante)
    except RecursionError:
        raise ValueError("JSON com demasiados níveis.") from None

    if not isinstance(dados, (dict, list)):
        raise ValueError("O JSON não é um objeto nem uma lista.")

    _conferir(dados)

    return dados


def _recusar_constante(nome: str):
    raise ValueError(f"{nome} não é JSON.")


def _conferir(dados) -> None:
    """Os níveis (até `PROFUNDIDADE_MAXIMA`) e os textos (UTF-8 válido, sem
    surrogates sozinhos), sem recursão."""
    pendentes = [(dados, 1)]

    while pendentes:
        valor, nivel = pendentes.pop()

        if isinstance(valor, (dict, list)):
            if nivel > PROFUNDIDADE_MAXIMA:
                raise ValueError("JSON com demasiados níveis.")

            if isinstance(valor, dict):
                for chave in valor:
                    chave.encode("utf-8")

            filhos = valor.values() if isinstance(valor, dict) else valor
            pendentes.extend((filho, nivel + 1) for filho in filhos)
        elif isinstance(valor, str):
            # Um surrogate sozinho (`"\ud800"`) dá UnicodeEncodeError, um ValueError.
            valor.encode("utf-8")


async def obter_json(url: str):
    """GET ao `url` (com a chave); devolve o JSON (objeto ou lista).

    Lança `FalhaServicoExterno` com estado fora de 2xx, sem resposta a tempo,
    com qualquer exceção do pedido, ou com um corpo que não é JSON. Nunca
    regista nada: quem chama regista o `motivo`."""
    silenciar_registos()
    motivo = None
    resposta = None

    try:
        async with httpx.AsyncClient(timeout=TEMPO_LIMITE, transport=_transporte, follow_redirects=False) as cliente:
            resposta = await asyncio.wait_for(cliente.get(url, headers=CABECALHOS), TEMPO_TOTAL_SEGUNDOS)
    except Exception as exc:  # noqa: BLE001 — ver a docstring do módulo (InvalidURL, a chave na mensagem)
        motivo = f"sem resposta ({type(exc).__name__})"

    if motivo is None and not 200 <= resposta.status_code <= 299:
        motivo = f"estado HTTP {resposta.status_code}"

    if motivo is None:
        try:
            return ler_json(resposta.content)
        except ValueError as exc:
            motivo = f"resposta que não é JSON ({type(exc).__name__})"

    raise FalhaServicoExterno(motivo)
