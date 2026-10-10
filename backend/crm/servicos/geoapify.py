"""Os pedidos à Geoapify e as respostas no formato da API do CRM.

Porta de src/Servicos/Geoapify.php do CRM autónomo (plano T2.14; dossiê §8).
Funções puras, sem rede: o cliente assíncrono e as rotas `/morada` são da
T2.15, que dá a estas funções o URL base (`CRM_GEOAPIFY_URL`), a chave do
servidor (`CRM_GEOAPIFY_CHAVE_SERVIDOR`) e o JSON que a Geoapify devolver.

- Pesquisa (autocomplete): só Portugal, em português, até 5 resultados, em
  `format=json`; com um ponto, os mais perto dele vêm primeiro
  (`bias=proximity:lng,lat`).
- Inversa: a morada de um ponto.
- As coordenadas vão com até 6 casas decimais (cerca de 10 cm), sem zeros no
  fim: o `number_format($v, 6, '.', '')` do PHP, que arredonda
  meio-para-longe-do-zero e, desde o PHP 8.0, nunca escreve "-0".
- O URL é o do `http_build_query(…, PHP_QUERY_RFC3986)`: cada nome e valor
  passa pelo `rawurlencode` (espaço → `%20`, só `A-Za-z0-9-_.~` ficam).

Cada resultado passa a `{rotulo, morada, codigo_postal, localidade, lat,
lng}`, por esta ordem: o rótulo mostra-se na lista de sugestões e o resto
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
"""
import re
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from crm.dominio.geo import contem_latitude, contem_longitude
from crm.dominio.numeros import arredondar

LOCALIDADE = ("city", "town", "village", "county")

LIMITE_PESQUISA = 5

# Os caracteres que o trim() do PHP tira sem segundo argumento.
_TRIM_DO_PHP = " \t\n\r\x00\x0b"

_CODIGO_POSTAL = re.compile(r"[0-9]{4}-[0-9]{3}")


def url_pesquisa(url_base: str, chave: str, texto: str, perto: Optional[Dict] = None) -> str:
    """O URL do autocomplete da Geoapify para o texto (que vai tal e qual:
    quem o apara e valida é a rota).

    `url_base` é o `CRM_GEOAPIFY_URL` (https://api.geoapify.com), com ou sem
    barras no fim; `perto` é o ponto `{"lat", "lng"}` de onde se pesquisa,
    só como bias (números já validados pela rota).
    """
    parametros = [("text", texto), ("filter", "countrycode:pt")]

    if perto is not None:
        parametros.append(("bias", f"proximity:{_coordenada(perto['lng'])},{_coordenada(perto['lat'])}"))

    parametros += [("lang", "pt"), ("limit", str(LIMITE_PESQUISA)), ("format", "json"), ("apiKey", chave)]

    return _url(url_base, "autocomplete", parametros)


def url_inversa(url_base: str, chave: str, lat: float, lng: float) -> str:
    """O URL da geocodificação inversa da Geoapify para o ponto (números já
    validados pela rota)."""
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
    objeto, `[]`. Não corta a lista: o limite de 5 vai no pedido."""
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
    """O `rawurlencode` do PHP (RFC 3986), como em `config_mapa._codificar`:
    os bytes que não são UTF-8 de uma variável de ambiente chegam ao Python
    como surrogates (surrogateescape) e voltam a ser esses bytes."""
    return quote(valor.encode("utf-8", "surrogateescape"), safe="")


def _coordenada(valor) -> str:
    """Até 6 casas decimais, sem zeros no fim: 38.7223, -9.5, 39 (o
    `number_format` do PHP + `rtrim`). Somar 0,0 tira o sinal ao -0,0 de um
    negativo que arredonda a zero, como o PHP 8. Um valor que não seja um
    número do JSON dá `ValueError` (do `arredondar`)."""
    return ("%.6f" % (arredondar(valor, 6) + 0.0)).rstrip("0").rstrip(".")


def _texto(valor) -> Optional[str]:
    """Um texto sem espaços nas pontas (os do `trim()` do PHP); o que não for
    texto, ou ficar vazio, é `None`."""
    if not isinstance(valor, str):
        return None

    texto = valor.strip(_TRIM_DO_PHP)

    return texto if texto != "" else None
