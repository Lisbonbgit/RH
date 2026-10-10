"""Os campos opcionais de uma loja que se validam sozinhos, para o validador da loja.

Porta de src/Dominio/Lojas/CamposLoja.php do CRM autónomo (dossiê §5.2 e
§5.7). Cada função devolve `(valor normalizado, erro)`: vazio ("" ou só
espaços, também os Unicode — `texto.aparar`) ou `None` fica `None`, e o que não
for texto é um erro. O `validador_loja` (T2.5/T2.6) junta-as; as definições da
fábrica (T2.7) usam `texto` para a morada.

`DIAS` era o `ValidadorLoja::DIAS` do PHP: fica aqui, onde é preciso primeiro.
"""
import re

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
