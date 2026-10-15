"""Verificadores do formato dos instantes, para os testes do CRM (correções do
plano, linha "§1 Decisões (Tempo) / T2.8"; provados em
test_instantes_gravados.py).

- `instantes_fora_do_formato(documento)`: num documento gravado (ou numa
  resposta), os `*_em` e `*_desde` têm de ser `AAAA-MM-DDTHH:MM:SSZ` ou null,
  e o `atualizado_em` um carimbo `AAAA-MM-DDTHH:MM:SS.ffffffZ` (nunca null).
  Os testes das escritas aplicam-no ao que o duplo guardou: T2.10 ao
  `documento_loja` e à loja gravada, T2.11 à interação e ao `$set` do PATCH,
  T2.13 às definições.
- `usos_proibidos_do_relogio(codigo, e_o_relogio=False)`: o varrimento do
  código do pacote `crm` — nunca `.isoformat` e, fora do `crm/relogio.py`,
  nem `strftime` nem leituras do relógio.
- `escritas_no_terreno(atualizacao)` (T3.14, plano F3 §1 "O terreno ganha"):
  numa atualização do Mongo (ou num documento a inserir), as violações ao
  contrato com a F4 — o escritório só escreve em `paragens.<índice>.<campo do
  escritório>` e acrescenta paragens novas com o terreno em
  `pendente`/null/null. As tarefas das rotas aplicam-no a todas as
  atualizações do registo do duplo.

As expressões são escritas aqui de propósito, sem as do `crm/relogio.py`: um
erro no formato da produção não pode passar por estar copiado no teste.
"""
import ast
import re
from datetime import datetime

_INSTANTE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_CARIMBO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")


def _existe(texto, formato):
    try:
        datetime.strptime(texto, formato)
    except ValueError:
        return False
    return True


def _instante_valido(valor):
    return (
        isinstance(valor, str)
        and _INSTANTE.fullmatch(valor) is not None
        and _existe(valor, "%Y-%m-%dT%H:%M:%SZ")
    )


def _carimbo_valido(valor):
    return (
        isinstance(valor, str)
        and _CARIMBO.fullmatch(valor) is not None
        and _existe(valor, "%Y-%m-%dT%H:%M:%S.%fZ")
    )


def _e_instante(campo):
    return isinstance(campo, str) and (campo.endswith("_em") or campo.endswith("_desde"))


def instantes_fora_do_formato(documento):
    """[(caminho, valor)] dos instantes fora do formato, pela ordem do
    documento; procura também em subdocumentos e listas (caminho com pontos,
    ex.: "paragens.1.feita_em"). [] quando está tudo certo."""
    problemas = []

    def _visitar(valor, caminho):
        if isinstance(valor, dict):
            for campo, dentro in valor.items():
                aqui = f"{caminho}.{campo}" if caminho else str(campo)
                if campo == "atualizado_em":
                    if not _carimbo_valido(dentro):
                        problemas.append((aqui, dentro))
                elif _e_instante(campo):
                    if dentro is not None and not _instante_valido(dentro):
                        problemas.append((aqui, dentro))
                else:
                    _visitar(dentro, aqui)
        elif isinstance(valor, list):
            for posicao, dentro in enumerate(valor):
                _visitar(dentro, f"{caminho}.{posicao}" if caminho else str(posicao))

    _visitar(documento, "")
    return problemas


# Formatam ou leem o relógio: só o crm/relogio.py os pode usar.
_SO_NO_RELOGIO = {"now", "utcnow", "today", "fromtimestamp", "utcfromtimestamp", "strftime"}
# time.time() e time.time_ns(): só com o módulo time à esquerda (o `time` de
# outro objeto — ex.: uma hora `datetime.time` — não é o relógio).
_DO_MODULO_TIME = {"time", "time_ns"}


def usos_proibidos_do_relogio(codigo, e_o_relogio=False):
    """[(linha, nome)] dos usos proibidos no código-fonte `codigo`, pela ordem
    em que aparecem. Lê o AST: as docstrings e os comentários que explicam a
    regra não contam. `e_o_relogio=True` para o próprio crm/relogio.py, onde
    só o isoformat é proibido."""
    encontrados = []
    for no in ast.walk(ast.parse(codigo)):
        if not isinstance(no, ast.Attribute):
            continue
        if no.attr == "isoformat":
            encontrados.append((no.lineno, no.col_offset, "isoformat"))
        elif e_o_relogio:
            continue
        elif no.attr in _SO_NO_RELOGIO:
            encontrados.append((no.lineno, no.col_offset, no.attr))
        elif no.attr in _DO_MODULO_TIME and isinstance(no.value, ast.Name) and no.value.id == "time":
            encontrados.append((no.lineno, no.col_offset, "time." + no.attr))
    encontrados.sort(key=lambda e: (e[0], e[1]))  # estável: na mesma posição fica a ordem do ast.walk
    return [(linha, nome) for (linha, _coluna, nome) in encontrados]


# --- As escritas nas rotas: o escritório nunca toca no terreno (T3.14) ------------------

# Os campos do terreno (F4) e os valores com que uma paragem nasce. Escritos
# aqui à parte dos do domínio (crm/dominio/rotas.py), como as expressões dos
# instantes; test_instantes_gravados prova que são os mesmos.
CAMPOS_DO_TERRENO = ("estado", "resultado", "concluida_em")
TERRENO_INICIAL = {"estado": "pendente", "resultado": None, "concluida_em": None}

# Os motivos das violações (o 3.º elemento de cada tuplo devolvido).
OPERADOR_PROIBIDO = "operador proibido em paragens (só $set/$inc por índice e $push de paragens novas)"
SUBSTITUI_A_LISTA = "escreve a lista de paragens inteira"
SUBSTITUI_A_PARAGEM = "escreve uma paragem inteira (levava o terreno)"
CAMINHO_SEM_INDICE = "caminho em paragens sem índice numérico"
CAMINHO_POSICIONAL = "caminho posicional ($, $[] ou $[x]) em paragens"
CAMPO_DO_TERRENO = "campo do terreno"
PUSH_DENTRO_DA_PARAGEM = "$push dentro de uma paragem"
PARAGEM_NOVA_FORA_DO_FORMATO = "paragem nova sem estado pendente, resultado null e concluida_em null"

# Operadores que nunca entram em `paragens…` (apagam, tiram ou mudam de nome).
_OPERADORES_PROIBIDOS = ("$pull", "$pullAll", "$pop", "$unset", "$addToSet", "$rename")
# Os únicos operadores que escrevem num campo de uma paragem (por índice).
_OPERADORES_POR_INDICE = ("$set", "$inc")

_SEM_VALOR = object()


def escritas_no_terreno(atualizacao):
    """[(operador, caminho, motivo)] das violações ao contrato com a F4 numa
    escrita do escritório, pela ordem da atualização. [] quando está tudo certo.

    `atualizacao` é uma atualização do Mongo (`{"$set": …, "$inc": …,
    "$push": …}`) ou um documento inteiro a inserir (sem chaves `$`; o
    operador devolvido é "documento" e só a lista `paragens` é verificada).
    TypeError com outra coisa (um texto, uma lista, um operador sem dicionário
    ou operadores misturados com campos).

    O escritório só escreve em `paragens.<índice>.<campo do escritório>` com
    `$set`/`$inc` e acrescenta paragens novas com `$push` em `paragens`, com o
    terreno em `pendente`/null/null. Tudo o resto em `paragens…` é violação:
    `$pull`/`$pop`/`$unset`/`$addToSet`/`$rename` (ou outro operador), a lista
    inteira, uma paragem inteira, um caminho sem índice ou posicional
    (`paragens.$…`, correção "T3.26 / T3.14"), um campo do terreno (mesmo por
    baixo, `paragens.0.estado.x`) e um `$push` dentro de uma paragem.
    """
    if not isinstance(atualizacao, dict):
        raise TypeError("escritas_no_terreno espera uma atualização do Mongo ou um documento: %r" % (atualizacao,))
    com_dolar = [chave.startswith("$") for chave in atualizacao]
    if any(com_dolar) and not all(com_dolar):
        raise TypeError("operadores misturados com campos: %r" % sorted(atualizacao))
    if atualizacao and not any(com_dolar):
        return _violacoes_do_documento(atualizacao)
    violacoes = []
    for operador, campos in atualizacao.items():
        if not isinstance(campos, dict):
            raise TypeError("o operador %s não traz um dicionário: %r" % (operador, campos))
        for caminho, valor in campos.items():
            alvo = caminho
            if operador == "$rename" and not _toca_em_paragens(caminho) and isinstance(valor, str):
                alvo = valor  # mudar o nome de outro campo PARA paragens…
            if not _toca_em_paragens(alvo):
                continue
            motivo = _motivo(operador, alvo, valor)
            if motivo is not None:
                violacoes.append((operador, alvo, motivo))
    return violacoes


def _toca_em_paragens(caminho):
    return isinstance(caminho, str) and (caminho == "paragens" or caminho.startswith("paragens."))


def _paragem_nova(valor):
    return isinstance(valor, dict) and {c: valor.get(c, _SEM_VALOR) for c in CAMPOS_DO_TERRENO} == TERRENO_INICIAL


def _motivo(operador, caminho, valor):
    partes = caminho.split(".")
    if any(parte.startswith("$") for parte in partes[1:]):
        return CAMINHO_POSICIONAL
    if operador in _OPERADORES_PROIBIDOS:
        return OPERADOR_PROIBIDO
    if operador == "$push":
        if len(partes) > 1:
            return PUSH_DENTRO_DA_PARAGEM
        return None if _paragem_nova(valor) else PARAGEM_NOVA_FORA_DO_FORMATO
    if len(partes) == 1:
        return SUBSTITUI_A_LISTA
    if operador not in _OPERADORES_POR_INDICE:
        return OPERADOR_PROIBIDO
    if not (partes[1].isascii() and partes[1].isdigit()):
        return CAMINHO_SEM_INDICE
    if len(partes) == 2:
        return SUBSTITUI_A_PARAGEM
    if partes[2] in CAMPOS_DO_TERRENO:
        return CAMPO_DO_TERRENO
    return None


def _violacoes_do_documento(documento):
    paragens = documento.get("paragens", _SEM_VALOR)
    if paragens is _SEM_VALOR:
        return []
    if not isinstance(paragens, list):
        return [("documento", "paragens", SUBSTITUI_A_LISTA)]
    return [
        ("documento", "paragens.%d" % posicao, PARAGEM_NOVA_FORA_DO_FORMATO)
        for posicao, paragem in enumerate(paragens)
        if not _paragem_nova(paragem)
    ]
