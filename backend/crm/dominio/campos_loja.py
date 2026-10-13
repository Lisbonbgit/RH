"""Os campos opcionais de uma loja que se validam sozinhos, para o validador da loja.

Porta de src/Dominio/Lojas/CamposLoja.php do CRM autónomo (dossiê §5.2 e
§5.7). Cada função devolve `(valor normalizado, erro)`: vazio ("" ou só
espaços, também os Unicode — `texto.aparar`) ou `None` fica `None`, e o que não
for texto é um erro. O `validador_loja` (T2.5/T2.6) junta-as; as definições da
fábrica (T2.7) usam `texto` para a morada.

`DIAS` era o `ValidadorLoja::DIAS` do PHP: fica aqui, onde é preciso primeiro.

`site` e `instagram` (2026-10-13, a pedido do dono; dossiê §5.2) não têm par
no PHP: o site é uma URL http(s) (um domínio sem esquema ganha `https://`) e
o Instagram guarda-se sempre como o endereço do perfil,
`https://www.instagram.com/<perfil>/`, venha um `@perfil`, um `perfil` ou um
endereço. Nos dois, o que não é texto dá a mensagem do campo (como no
telefone).
"""
import re
from urllib.parse import urlsplit, urlunsplit

from .texto import aparar

# Pela ordem da semana: os dias fechada guardam-se por esta ordem.
DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")

_TELEFONE = "O telefone tem de ter 9 a 15 algarismos (aceita + e espaços)."
_TELEFONE_MINIMO = 9
_TELEFONE_MAXIMO = 15

# As notas eram uma coluna TEXT do MariaDB: até 65 535 bytes (UTF-8).
_NOTAS_MAXIMO_BYTES = 65535

# Sempre `[0-9]` e `fullmatch` (plano §10): o `\d` aceita algarismos árabes e
# o `$` um "\n" final.
_CODIGO_POSTAL = re.compile(r"[0-9]{4}-[0-9]{3}")
_TELEFONE_FORMATO = re.compile(r"\+?[0-9]+( [0-9]+)*")

# O site guarda-se até aqui, contando o `https://` que se junta a um domínio
# sem esquema. O `formularioLoja.test.js` lê esta linha: fica numa só.
SITE_MAXIMO = 255

_SITE = "O site tem de ser um endereço válido (ex.: https://exemplo.pt)."
# Um endereço válido mas comprido de mais diz o limite (como o `texto()`), e
# não que "não é válido": o campo da ficha deixa escrever 255 e o `https://`
# que se junta a um domínio sem esquema pode passá-lo.
_SITE_COMPRIDO = f"O site tem no máximo {SITE_MAXIMO} caracteres."
_INSTAGRAM = "O Instagram tem de ser um perfil válido (ex.: @purplehouse)."

# Num endereço, um espaço (também os Unicode: o `\s` do Python em texto, mais
# os dois que ele não apanha, como no `texto.aparar`) ou um carácter de
# controlo ASCII é sempre erro. O `urlsplit` tirava calado o TAB, o CR e o LF.
_ESPACO_OU_CONTROLO = re.compile(r"[\s\u180e\ufeff\x00-\x1f\x7f]")
# "esquema://" no início (o que o `urlsplit` lê como esquema); sem isto,
# junta-se `https://` — e um `mailto:` ou `javascript:` sem `//` cai no
# `https://mailto:…`, que é recusado pela máquina.
_ESQUEMA = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_ESQUEMAS_DO_SITE = ("http", "https")
# A máquina do site, sobre o `hostname` do `urlsplit` (já em minúsculas):
# etiquetas de letras (também acentuadas: `[^\W_]` é uma letra ou um
# algarismo Unicode), algarismos e hífens, até 63 e sem hífen nas pontas, e
# um domínio de topo só com letras, pelo menos 2. Um IP, um ponto final ou
# "localhost" ficam de fora: o site de uma loja tem um domínio.
_ETIQUETA = r"[^\W_](?:(?:[^\W_]|-){0,61}[^\W_])?"
_MAQUINA = re.compile(r"(?:" + _ETIQUETA + r"\.)+[^\W\d_]{2,63}")

# O perfil do Instagram: letras ASCII, algarismos, ponto e sublinhado, 1 a 30,
# sem acabar em ponto nem ter dois pontos seguidos (o Instagram não os
# permite; um "@perfil." colado ao ponto final de uma frase dava um endereço
# que não existe).
_INSTAGRAM_PERFIL = re.compile(r"(?!.*\.\.)[A-Za-z0-9._]{0,29}[A-Za-z0-9_]")
_INSTAGRAM_DOMINIO = r"(?:https?://)?(?:www\.|m\.)?instagram\.com"
# O endereço de um perfil: o domínio, uma barra, o perfil, uma barra opcional
# e, de um link de partilha, a query e o fragmento, que se ignoram. Uma
# publicação (`/p/…`) ou os reels (`/perfil/reels/`) não encaixam.
_INSTAGRAM_URL = re.compile(_INSTAGRAM_DOMINIO + r"/([^/?#]+)/?(?:[?#].*)?", re.IGNORECASE)
# Só o domínio, sem perfil: é erro, e não o perfil "instagram.com".
_INSTAGRAM_SEM_PERFIL = re.compile(_INSTAGRAM_DOMINIO + r"/?(?:[?#].*)?", re.IGNORECASE)


def texto(valor, rotulo: str, maximo: int):
    """Um texto de uma coluna VARCHAR do autónomo, sem espaços nas pontas, até `maximo` caracteres.

    Conta caracteres (o `mb_strlen` do PHP), não bytes: "é" conta um.
    """
    aparado, erro = _aparado(valor)
    if aparado is not None and len(aparado) > maximo:
        return None, f"{rotulo} tem no máximo {maximo} caracteres."
    return aparado, erro


def notas(valor):
    """As notas, sem espaços nas pontas, até 65 535 bytes em UTF-8 (o `strlen` do PHP).

    O `json.loads` aceita um "\\ud800" sozinho (o `json_decode` do PHP
    recusava), que o `encode("utf-8")` não sabe escrever: conta-se com
    `surrogatepass` (3 bytes) para nunca rebentar aqui.
    """
    aparadas, erro = _aparado(valor)
    if aparadas is not None and len(aparadas.encode("utf-8", "surrogatepass")) > _NOTAS_MAXIMO_BYTES:
        return None, "As notas são demasiado compridas."
    return aparadas, erro


def codigo_postal(valor):
    """O código postal "0000-000", só com algarismos ASCII. O que não for texto dá a mesma mensagem."""
    codigo, erro = _aparado(valor)
    if erro is not None or (codigo is not None and _CODIGO_POSTAL.fullmatch(codigo) is None):
        return None, "O código postal tem de ter o formato 0000-000."
    return codigo, None


def telefone(valor):
    """9 a 15 algarismos, com um + opcional no início e espaços entre eles.

    Os espaços seguidos ficam um só e o espaço depois do + sai ("+ 351 912…"
    → "+351 912…"), por esta ordem: "+  351" também fica "+351". Tabulações,
    hífens, parênteses, dois +, ou um número JSON em vez de texto são erro.
    """
    numero, erro = _aparado(valor)
    if erro is not None:
        return None, _TELEFONE
    if numero is None:
        return None, None

    numero = re.sub(r"^\+ ", "+", re.sub(r" {2,}", " ", numero))
    algarismos = len(re.sub(r"[^0-9]", "", numero))
    valido = (
        _TELEFONE_FORMATO.fullmatch(numero) is not None
        and _TELEFONE_MINIMO <= algarismos <= _TELEFONE_MAXIMO
    )
    return (numero, None) if valido else (None, _TELEFONE)


def site(valor):
    """Uma URL http(s) até `SITE_MAXIMO` caracteres, normalizada: `(url, None)` ou `(None, erro)`.

    Aparado; um domínio sem esquema ("exemplo.pt/loja") ganha `https://`; o
    esquema e a máquina ficam em minúsculas e o caminho, a query e o
    fragmento como vieram. Erro: espaços ou controlo, outro esquema, sem
    máquina ou com uma que não é um domínio (`_MAQUINA`), utilizador/senha ou
    porto inválido (a mensagem do site); um endereço válido com mais de
    `SITE_MAXIMO` depois de normalizar diz o limite (`_SITE_COMPRIDO`). O que
    não for texto dá a mensagem do site.
    """
    endereco, erro = _aparado(valor)
    if erro is not None:
        return None, _SITE
    if endereco is None:
        return None, None
    if _ESPACO_OU_CONTROLO.search(endereco):
        return None, _SITE
    if _ESQUEMA.match(endereco) is None:
        endereco = "https://" + endereco

    try:
        partes = urlsplit(endereco)
        partes.port  # noqa: B018 — levanta ValueError se o porto não for um número no intervalo
    except ValueError:
        return None, _SITE

    maquina_valida = partes.hostname is not None and _MAQUINA.fullmatch(partes.hostname) is not None
    if partes.scheme not in _ESQUEMAS_DO_SITE or partes.username is not None or not maquina_valida:
        return None, _SITE

    normalizado = urlunsplit((partes.scheme, partes.netloc.lower(), partes.path, partes.query, partes.fragment))
    if len(normalizado) > SITE_MAXIMO:
        return None, _SITE_COMPRIDO
    return normalizado, None


def instagram(valor):
    """Um perfil do Instagram, guardado como `https://www.instagram.com/<perfil>/`: `(url, None)` ou `(None, erro)`.

    Aceita "@perfil", "perfil" ou o endereço do perfil (`_INSTAGRAM_URL`: com
    ou sem esquema, `www.` ou `m.`, barra final, query e fragmento de um link
    de partilha). O perfil (`_INSTAGRAM_PERFIL`) fica como foi escrito, com
    as maiúsculas. Erro: espaços ou controlo, só o domínio sem perfil, um
    perfil fora das regras (hífen, acento, 31 caracteres, uma barra, a acabar
    em ponto ou com dois pontos seguidos) ou outro sítio. O que não for texto
    dá a mensagem do Instagram.
    """
    escrito, erro = _aparado(valor)
    if erro is not None:
        return None, _INSTAGRAM
    if escrito is None:
        return None, None
    if _ESPACO_OU_CONTROLO.search(escrito) or _INSTAGRAM_SEM_PERFIL.fullmatch(escrito) is not None:
        return None, _INSTAGRAM

    endereco = _INSTAGRAM_URL.fullmatch(escrito)
    perfil = endereco.group(1) if endereco is not None else escrito
    if perfil.startswith("@"):
        perfil = perfil[1:]
    if _INSTAGRAM_PERFIL.fullmatch(perfil) is None:
        return None, _INSTAGRAM
    return f"https://www.instagram.com/{perfil}/", None


def dias_fechada(valor):
    """Uma lista de `DIAS`, sem repetidos, devolvida (nova) pela ordem da semana. `None` → `[]`.

    Só uma lista JSON conta (o `array_is_list` passa a `isinstance(x, list)`,
    plano §10): um objeto é sempre erro, mesmo `{}` ou `{"0": "sab"}`, que o
    `json_decode` associativo do PHP transformava em lista.
    """
    if valor is None:
        return [], None
    if not isinstance(valor, list) or not all(isinstance(dia, str) and dia in DIAS for dia in valor):
        return None, "Os dias têm de ser seg, ter, qua, qui, sex, sab ou dom."
    if len(set(valor)) != len(valor):
        return None, "Há dias repetidos."
    return [dia for dia in DIAS if dia in valor], None


def _aparado(valor):
    """Um texto sem espaços nas pontas; vazio ou `None` fica `None`. O que não for texto é um erro."""
    if valor is None:
        return None, None
    if not isinstance(valor, str):
        return None, "Tem de ser texto."
    aparado = aparar(valor)
    return (aparado or None), None
