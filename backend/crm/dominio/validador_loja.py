"""A validação dos campos de uma loja que vêm da API.

Porta de src/Dominio/Lojas/ValidadorLoja.php do CRM autónomo (dossiê §5.2).
Devolve `(dados, erros)`: os dados normalizados só se usam quando não há
erros; os erros são `{campo: mensagem pt-PT}`, pela ordem de `CAMPOS`, e os
dados também vêm por essa ordem. As outras chaves do pedido (`id`,
`fase_desde`, `atualizado_em`, `confirmar_duplicado`…) ignoram-se: quem as usa
é a rota. Se a região existe vê-se na base (T2.10), antes dos duplicados.

Normalização: textos sem espaços nas pontas (também os Unicode,
`texto.aparar`) e "" → `None`; lat/lng arredondadas a 6 casas
meio-para-longe-do-zero; `precisao_m` em metros inteiros e só com origem
`gps` (nas outras fica `None`); `dias_fechada` pela ordem da semana.

Adaptação do portal (plano T2.5): `regiao_id` é `None` ou o uuid4 em texto
de uma região (o `str(uuid.uuid4())` com que o portal grava os ids), e não o
inteiro ≥ 1 do autónomo. Como é texto exato, nunca chega ao `find` um
operador do Mongo (`{"$ne": None}`).

A alteração (só as chaves enviadas, a localização sempre junta) chega na T2.6.
"""
import re

from . import campos_loja, janelas
from .fases import fase_valida
from .geo import MENSAGEM_GPS, MENSAGEM_PORTUGAL, contem_latitude, contem_longitude, precisao_aceitavel
from .numeros import arredondar, e_numero_json
from .texto import aparar

# Os campos da loja que a API aceita, pela ordem da tabela (dossiê §5.2).
CAMPOS = (
    "nome", "fase", "regiao_id", "morada", "codigo_postal", "localidade",
    "lat", "lng", "origem_coords", "precisao_m", "telefone", "pessoa_contacto", "notas",
    "janela1_inicio", "janela1_fim", "janela2_inicio", "janela2_fim", "dias_fechada",
)

ORIGENS = ("pin_manual", "gps", "geocoder")

# Tamanho da coluna `nome` do autónomo, em caracteres.
NOME_MAXIMO = 150

# Os textos opcionais das colunas VARCHAR do autónomo: (rótulo na mensagem, tamanho em caracteres).
TEXTOS = {
    "morada": ("A morada", 255),
    "localidade": ("A localidade", 100),
    "pessoa_contacto": ("A pessoa de contacto", 100),
}

# Validam-se juntos (a precisão depende da origem); numa alteração vão sempre juntos (T2.6).
_LOCALIZACAO = ("lat", "lng", "origem_coords", "precisao_m")

# Um uuid4 em minúsculas, como o `str(uuid.uuid4())`: a versão 4 e a variante
# 8, 9, a ou b. `[0-9a-f]` e `fullmatch`, nunca `\d` nem `$` (plano §10).
_UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def criacao(dados: dict):
    """Uma loja nova: `(dados, erros)`, com os 18 campos (os que faltam a `None`).

    Obrigatórios: nome, fase e o pino (lat, lng, origem_coords). As janelas
    só se comparam (`janelas.erros`) quando nenhuma das quatro horas tem erro.
    """
    normalizados, erros = _validar({**dict.fromkeys(CAMPOS), **_so_campos(dados)})

    if not any(campo in erros for campo in janelas.CAMPOS):
        erros = _ordenar({**erros, **janelas.erros(normalizados)})

    return normalizados, erros


def _validar(campos: dict):
    """Os campos enviados, validados: `(dados, erros)` pela ordem de `CAMPOS`.

    Os da localização validam-se juntos, se vier algum deles.
    """
    dados = {}
    erros = {}

    for campo, valor in campos.items():
        if campo not in _LOCALIZACAO:
            dados[campo], erros[campo] = _campo(campo, valor)

    if any(campo in campos for campo in _LOCALIZACAO):
        localizacao, erros_localizacao = _localizacao(campos)
        dados.update(localizacao)
        erros.update(erros_localizacao)

    erros = {campo: erro for campo, erro in erros.items() if erro is not None}

    return _ordenar(dados), _ordenar(erros)


def _campo(campo: str, valor):
    """`(valor normalizado, erro)` de um campo que não é da localização."""
    if campo == "nome":
        return _nome(valor)
    if campo == "fase":
        return _fase(valor)
    if campo == "regiao_id":
        return _regiao(valor)
    if campo == "codigo_postal":
        return campos_loja.codigo_postal(valor)
    if campo == "telefone":
        return campos_loja.telefone(valor)
    if campo == "notas":
        return campos_loja.notas(valor)
    if campo == "dias_fechada":
        return campos_loja.dias_fechada(valor)
    if campo in janelas.CAMPOS:
        return janelas.hora(valor)
    return campos_loja.texto(valor, *TEXTOS[campo])


def _nome(valor):
    # Como no PHP, o que não for texto conta como vazio ("Indique o nome."),
    # e com erro o nome fica nos dados (que então não se usam).
    nome = aparar(valor) if isinstance(valor, str) else ""

    if nome == "":
        return nome, "Indique o nome."
    if len(nome) > NOME_MAXIMO:
        return nome, f"O nome tem no máximo {NOME_MAXIMO} caracteres."
    return nome, None


def _fase(valor):
    if valor is None or (isinstance(valor, str) and valor == ""):
        return None, "Indique a fase."
    if not fase_valida(valor):
        return None, "A fase não é válida."
    return valor, None


def _regiao(valor):
    """`None` é "sem região"; senão um uuid4 em texto, tal e qual (sem aparar)."""
    if valor is None:
        return None, None
    if isinstance(valor, str) and _UUID4.fullmatch(valor) is not None:
        return valor, None
    return None, "A região não é válida."


def _localizacao(campos: dict):
    """lat, lng, origem_coords e precisao_m, validados juntos (a precisão depende da origem)."""
    dados = {}
    erros = {}
    dados["lat"], erros["lat"] = _coordenada(campos.get("lat"), "A latitude", contem_latitude)
    dados["lng"], erros["lng"] = _coordenada(campos.get("lng"), "A longitude", contem_longitude)

    origem = campos.get("origem_coords")
    dados["origem_coords"] = origem if isinstance(origem, str) and origem in ORIGENS else None
    if origem is None or (isinstance(origem, str) and origem == ""):
        erros["origem_coords"] = "Indique a origem das coordenadas."
    elif dados["origem_coords"] is None:
        erros["origem_coords"] = "A origem das coordenadas não é válida."
    else:
        erros["origem_coords"] = None

    # Só a origem "gps", tal e qual, tem precisão; nas outras ignora-se o que vier.
    precisao = campos.get("precisao_m")
    gps = isinstance(origem, str) and origem == "gps"
    gps_aceitavel = gps and precisao_aceitavel(precisao)
    dados["precisao_m"] = int(arredondar(precisao)) if gps_aceitavel else None
    erros["precisao_m"] = MENSAGEM_GPS if gps and not gps_aceitavel else None

    return dados, erros


def _coordenada(valor, nome: str, dentro):
    """`(coordenada arredondada às 6 casas, erro)`. Fora de Portugal, o valor arredondado fica nos dados."""
    if valor is None:
        return None, "Coloque o pino no mapa."
    if not e_numero_json(valor):
        return None, f"{nome} tem de ser um número."

    arredondada = arredondar(valor, 6)

    return arredondada, (None if dentro(arredondada) else MENSAGEM_PORTUGAL)


def _so_campos(dados: dict) -> dict:
    return {campo: valor for campo, valor in dados.items() if campo in CAMPOS}


def _ordenar(por_campo: dict) -> dict:
    """Um dicionário novo pela ordem de `CAMPOS`."""
    return {campo: por_campo[campo] for campo in CAMPOS if campo in por_campo}
