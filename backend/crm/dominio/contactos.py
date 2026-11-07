"""Os contactos de uma loja: as regras, sem base nem relógio (2026-11-07).

Cada contacto é uma linha de `crm_interacoes`, a linha do tempo da loja, com o
resumo em `notas` (desenho dos contactos §3; dossiê §5.11). Aqui valida-se o
corpo, decide-se quem pode alterar, o que um PATCH muda de facto, a numeração e
o que sobe o "último contacto" da loja; `crm/contactos.py` só lê, grava e
responde. O `hoje` e os dias são `date` (`datas.ler_data`, `relogio.hoje`): o
relógio fica sempre do lado de quem chama.

`mensagem` é um tipo novo e uma exceção ao §4.2 do desenho original: também
atualiza `ultima_interacao_em`, e por isso na F5 cala o alerta dos 7 dias.
"""
from datetime import date

from . import campos_loja
from .datas import ler_data
from .ids import e_uuid4

# Igual a TIPOS_CONTACTO em frontend/src/lib/crm/contactos.js (test_consistencia_frontend.py): manter numa só linha.
TIPOS_CONTACTO = ("visita", "chamada", "mensagem")

# O que conta para cada um dos dois campos da loja, ao recalcular (§4.2 do
# desenho original, com a exceção da `mensagem`). As `amostra` e `entrega` só
# nascem na F4. Do segundo campo só contam as com sucesso: um contacto da ficha
# (`resultado: null`) conta como sucesso, e os resultados de falha só nascem na
# F4, que os junta a esta regra.
TIPOS_ULTIMA_INTERACAO = (*TIPOS_CONTACTO, "amostra", "entrega")
TIPOS_VISITA_OU_ENTREGA = ("visita", "amostra", "entrega")

# A data de um contacto vai daqui até ao `hoje`: contactos antigos sim, futuros não.
DATA_MINIMA = date(2000, 1, 1)
RESUMO_MAXIMO = 5000

MENSAGEM_TIPO = "Escolha o tipo: visita, chamada ou mensagem."
MENSAGEM_DATA = "Indique o dia no formato AAAA-MM-DD."
MENSAGEM_DATA_FORA = "Escolha um dia entre 1 de janeiro de 2000 e hoje."
MENSAGEM_RESUMO = "Escreva o resumo do contacto."
MENSAGEM_CLIENT_UUID = "O identificador do contacto não é válido."
MENSAGEM_CLIENT_UUID_DE_OUTRA_LOJA = "Este identificador já foi usado noutra loja."

# Os campos de cada corpo, pela ordem dos erros.
_CAMPOS_CRIACAO = ("tipo", "data", "resumo", "client_uuid")
_CAMPOS_ALTERACAO = ("tipo", "data", "resumo")


def criacao(corpo: dict, hoje: date):
    """O corpo do POST: `(dados, erros)`, com `tipo`, `data` (uma `date`),
    `resumo` e `client_uuid`. Os dados só se usam sem erros; as outras chaves
    ignoram-se."""
    return _validar({campo: corpo.get(campo) for campo in _CAMPOS_CRIACAO}, hoje)


def alteracao(corpo: dict, hoje: date):
    """O corpo do PATCH: `(dados, erros)`, só com as chaves enviadas. Uma chave
    presente com `null` ou vazio é erro do campo: nada num contacto se limpa.
    O `client_uuid` não se muda."""
    return _validar({campo: corpo[campo] for campo in _CAMPOS_ALTERACAO if campo in corpo}, hoje)


def pode_alterar(linha: dict, perfil, user_id) -> bool:
    """Quem escreveu o contacto e os administradores do CRM (`perfil`, nunca o
    `role` do portal). O que veio de uma paragem é registo do terreno (F4), e
    do escritório ninguém o altera."""
    if linha.get("paragem_id") is not None:
        return False
    return perfil == "admin" or linha["utilizador_id"] == user_id


def mudancas(linha: dict, dia_gravado: date, dados: dict) -> dict:
    """O que os `dados` do PATCH mudam de facto na `linha`, cujo dia é
    `dia_gravado`: só as chaves com outro valor. Vazio, o PATCH não escreve."""
    atuais = {"tipo": linha["tipo"], "data": dia_gravado, "resumo": linha["notas"]}
    return {campo: valor for campo, valor in dados.items() if valor != atuais[campo]}


def numerados(linhas: list) -> list:
    """`[(numero, linha)]` do mais recente para o mais antigo. A ordem é
    `ocorrida_em`, `criado_em`, `id`, e o número é a posição, com 1 para o mais
    antigo: inserir um contacto antigo ou apagar um renumera os outros. Quem
    escreve na F4 pode não trazer o `criado_em`."""
    ordenadas = sorted(linhas, key=lambda linha: (linha["ocorrida_em"], linha.get("criado_em") or "", linha["id"]))
    return list(enumerate(ordenadas, start=1))[::-1]


def ultimos_instantes(tipo: str, ocorrida_em: str) -> dict:
    """Os campos da loja que um contacto novo sobe, para o `$max`. Dos tipos da
    ficha, só a visita conta como `ultima_visita_ou_entrega_em`."""
    campos = {"ultima_interacao_em": ocorrida_em}
    if tipo == "visita":
        campos["ultima_visita_ou_entrega_em"] = ocorrida_em
    return campos


def _validar(campos: dict, hoje: date):
    """Os `campos` enviados, validados: `(dados, erros)` pela ordem recebida."""
    dados = {}
    erros = {}
    for campo, valor in campos.items():
        dados[campo], erros[campo] = _campo(campo, valor, hoje)
    return dados, {campo: erro for campo, erro in erros.items() if erro is not None}


def _campo(campo: str, valor, hoje: date):
    """`(valor normalizado, erro)` de um campo do corpo."""
    if campo == "tipo":
        return _tipo(valor)
    if campo == "data":
        return _data(valor, hoje)
    if campo == "resumo":
        return _resumo(valor)
    return _client_uuid(valor)


def _tipo(valor):
    if isinstance(valor, str) and valor in TIPOS_CONTACTO:
        return valor, None
    return None, MENSAGEM_TIPO


def _data(valor, hoje: date):
    dia = ler_data(valor)
    if dia is None:
        return None, MENSAGEM_DATA
    if not DATA_MINIMA <= dia <= hoje:
        return None, MENSAGEM_DATA_FORA
    return dia, None


def _resumo(valor):
    """Obrigatório depois de aparado, até `RESUMO_MAXIMO` caracteres."""
    resumo, erro = campos_loja.texto(valor, "O resumo", RESUMO_MAXIMO)
    if erro is None and resumo is None:
        return None, MENSAGEM_RESUMO
    return resumo, erro


def _client_uuid(valor):
    """Ausente ou `null` grava-se `null`; senão tem de ser um uuid4 em texto, e
    assim nunca chega ao `find_one` um operador do Mongo."""
    if valor is None or e_uuid4(valor):
        return valor, None
    return None, MENSAGEM_CLIENT_UUID
