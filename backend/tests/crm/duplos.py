"""Duplos do MongoDB/Motor para os testes do CRM — sem Mongo nenhum.

Molde: `_como_o_motor` de tests/faturacao/test_catalogo.py e o duplo de
tests/faturacao/test_fiscal.py. O que se copia do Motor, de propósito:

- **Cópias fundas** em tudo o que entra e sai: o `find`/`find_one` reais
  descodificam BSON de fresco, e um duplo que devolvesse o objeto guardado
  deixava passar por aliasing um código que muta o que leu sem escrever nada.
- **`insert_one` acrescenta `_id`** (ObjectId) ao próprio dicionário de quem
  chama, como o PyMongo. Uma rota que devolva esse dicionário dá um ObjectId
  que o FastAPI não serializa — os testes das rotas apanham-no aqui.
- **Campos únicos** com a semântica do Mongo: um campo em falta conta como
  null e dois null colidem (é a armadilha de pôr `id` único em
  crm_definicoes). Por omissão a coleção impõe os únicos que `crm.db.INDICES`
  declara para ela (`unicos_declarados`); índices parciais, esparsos ou
  compostos não são modelados (o ensaio no Mongo local, T2.17, cobre-os).
- **Cada operação cede o controlo** (`await asyncio.sleep(0)`) antes de
  operar e depois opera sem mais nenhum `await` — o "verifica e escreve" é
  atómico para o ciclo de eventos, como um índice único em produção.
- **Caminhos com pontos** (T3.14, as rotas): nos filtros, `"paragens.loja_id"`
  atravessa a lista com a semântica do Mongo (a igualdade, `$in`, `$gt`… casam
  se ALGUM elemento casar; `$ne`/`$nin` se NENHUM casar) e `"paragens.2.estado"`
  entra pelo índice. Nas atualizações, `$set`/`$inc`/`$push` escrevem em
  `"paragens.1.ordem"` e criam os subdocumentos que faltam; uma lista NUNCA
  se estica (índice para lá do fim → NotImplementedError). Dois caminhos em
  que um é prefixo do outro (`$push paragens` + `$set paragens.0.x`) dão o
  erro 40 do Mongo antes de procurar o documento.
- **`antes_de(operacao, funcao)`** corre `funcao(docs)` antes da operação:
  simula a escrita concorrente do motorista (F4) entre a leitura e a escrita
  do escritório.
- **O que não está modelado rebenta** com NotImplementedError em vez de
  mentir (operadores de filtro ou de atualização desconhecidos, `$or`,
  modificadores do `$push`, comparações fora de números e textos, …).

Simplificação documentada: `$geoWithin` devolve TODOS os documentos com `loc`
(não faz geometria). A regra exata dos 50 m é provada no domínio (T2.3) e no
Mongo local (T2.17).

As corrotinas correm com `correr(coro)`, nunca com o asyncio.run (ver a sua
docstring).
"""
import asyncio
import operator
from copy import deepcopy

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure

# As operações que o duplo conhece — e as únicas chaves aceites em `falhar` e
# em `antes_de`.
OPERACOES = (
    "find_one",
    "find",
    "insert_one",
    "update_one",
    "find_one_and_update",
    "delete_one",
    "delete_many",
    "count_documents",
    "create_index",
)

_OPERADORES_DE_ATUALIZACAO = ("$set", "$setOnInsert", "$inc", "$push")

# $gt/$gte/$lt/$lte: só entre números (sem booleanos) ou entre textos.
_COMPARACOES = {"$gt": operator.gt, "$gte": operator.ge, "$lt": operator.lt, "$lte": operator.le}

_EM_FALTA = object()


def correr(coro):
    """Corre uma corrotina num ciclo de eventos novo, que fecha no fim.

    Nunca chama set_event_loop: o asyncio.run, ao terminar, deixa a thread
    principal SEM ciclo de eventos (set_event_loop(None)), e cerca de 45
    ficheiros da Faturação/Financeiro que usam asyncio.get_event_loop()
    rebentavam a seguir na suite completa (tests/crm corre antes deles).
    Molde: test_relatorio_diario_com_app.py.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def unicos_declarados(nome):
    """Os campos únicos que `crm.db.INDICES` declara para a coleção `nome`
    (índices de um só campo, sem `partialFilterExpression` nem `sparse`).
    Uma coleção que não aparece nos índices (ex.: `users` do portal) fica com
    `("id",)`. Lido a cada chamada, para respeitar um monkeypatch de INDICES."""
    from crm import db as bd

    declarados = [entrada for entrada in bd.INDICES if entrada[0] == nome]
    if not declarados:
        return ("id",)
    return tuple(
        chaves[0][0]
        for (_c, chaves, opcoes) in declarados
        if opcoes.get("unique")
        and len(chaves) == 1
        and not opcoes.get("partialFilterExpression")
        and not opcoes.get("sparse")
    )


# --- Resultados (só os campos que o código do portal usa) ---------------------


class ResultadoInsert:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class ResultadoUpdate:
    def __init__(self, matched_count, modified_count, upserted_id=None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class ResultadoDelete:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


# --- Filtros, projeções e ordenação --------------------------------------------


class _Varios(list):
    """Os valores apanhados ao atravessar uma lista num caminho com pontos
    (`"paragens.estado"`): um por elemento, `_EM_FALTA` nos elementos sem o
    campo. Uma condição casa se ALGUM casar (`$ne`/`$nin`: se nenhum casar),
    como no Mongo."""


def _indice(parte):
    """O índice numérico de um segmento do caminho ("2"), ou None."""
    return int(parte) if parte.isascii() and parte.isdigit() else None


def _obter(doc, caminho):
    """O valor de `caminho` (com pontos para subdocumentos; um índice numérico
    entra numa lista, "paragens.2.estado"; sem índice, uma lista dá `_Varios`)
    ou _EM_FALTA."""
    return _descer(doc, caminho.split("."))


def _descer(atual, partes):
    for posicao, parte in enumerate(partes):
        if isinstance(atual, dict):
            if parte not in atual:
                return _EM_FALTA
            atual = atual[parte]
        elif isinstance(atual, list):
            indice = _indice(parte)
            if indice is None:
                varios = _Varios()
                for elemento in atual:
                    valor = _descer(elemento, partes[posicao:])
                    if isinstance(valor, _Varios):
                        varios.extend(valor)
                    else:
                        varios.append(valor)
                return varios
            if indice >= len(atual):
                return _EM_FALTA
            atual = atual[indice]
        else:
            return _EM_FALTA
    return atual


def _iguais(a, b):
    """Igualdade do Mongo nos pontos que importam: True não é 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _valor_casa(valor, esperado):
    """Igualdade do Mongo: null casa com campo em falta, um valor casa com
    uma lista que o contenha e, através de uma lista, com algum elemento."""
    if valor is _EM_FALTA:
        return esperado is None
    if isinstance(valor, _Varios):
        if not valor:
            return esperado is None
        return any(_valor_casa(v, esperado) for v in valor)
    if isinstance(valor, list) and not isinstance(esperado, list):
        return any(_iguais(v, esperado) for v in valor)
    return _iguais(valor, esperado)


def _existe(valor):
    if isinstance(valor, _Varios):
        return any(v is not _EM_FALTA for v in valor)
    return valor is not _EM_FALTA


def _comparavel(valor):
    return isinstance(valor, str) or _numero(valor)


def _numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _compara(valor, operador, argumento):
    """$gt/$gte/$lt/$lte só entre números (sem booleanos) ou entre textos,
    como a comparação por tipos do Mongo; numa lista, algum elemento."""
    if not _comparavel(argumento):
        raise NotImplementedError("o duplo só compara números ou textos: %s %r" % (operador, argumento))
    if isinstance(valor, list):  # _Varios ou um campo-lista
        return any(_compara(v, operador, argumento) for v in valor)
    if not _comparavel(valor) or isinstance(valor, str) != isinstance(argumento, str):
        return False
    return _COMPARACOES[operador](valor, argumento)


def _e_expressao(condicao):
    if not isinstance(condicao, dict) or not condicao:
        return False
    com_dolar = [k.startswith("$") for k in condicao]
    if any(com_dolar) and not all(com_dolar):
        raise NotImplementedError("o duplo não mistura operadores com campos: %r" % (condicao,))
    return all(com_dolar)


def _lista(argumento, operador):
    if not isinstance(argumento, (list, tuple)):
        raise OperationFailure("%s needs an array" % operador)
    return argumento


def _condicao_casa(valor, condicao):
    if not _e_expressao(condicao):
        return _valor_casa(valor, condicao)
    for operador, argumento in condicao.items():
        if operador == "$ne":
            ok = not _valor_casa(valor, argumento)
        elif operador == "$in":
            ok = any(_valor_casa(valor, a) for a in _lista(argumento, operador))
        elif operador == "$nin":
            ok = not any(_valor_casa(valor, a) for a in _lista(argumento, operador))
        elif operador == "$exists":
            ok = _existe(valor) == bool(argumento)
        elif operador in _COMPARACOES:
            ok = _compara(valor, operador, argumento)
        elif operador == "$geoWithin":
            # Simplificação documentada no docstring do módulo.
            ok = valor is not _EM_FALTA and valor is not None
        else:
            raise NotImplementedError("operador %s não suportado pelo duplo" % operador)
        if not ok:
            return False
    return True


def corresponde(doc, filtro):
    """O documento passa no filtro? (igualdade, $ne, $in, $nin, $exists,
    $gt/$gte/$lt/$lte, $geoWithin; caminhos com pontos, índices e listas)"""
    for campo, condicao in (filtro or {}).items():
        if campo.startswith("$"):
            raise NotImplementedError("operador %s não suportado pelo duplo" % campo)
        if not _condicao_casa(_obter(doc, campo), condicao):
            return False
    return True


def _projetar(doc, projecao):
    """Uma cópia funda do documento com a projeção aplicada (inclusão ou
    exclusão de campos de topo; `_id` sai só com `_id: 0`)."""
    if projecao is None:
        return deepcopy(doc)
    if isinstance(projecao, (list, tuple)):
        projecao = {campo: 1 for campo in projecao}
    campos = dict(projecao)
    mostrar_id = bool(campos.pop("_id", 1))
    if any("." in campo for campo in campos):
        raise NotImplementedError("o duplo não projeta subcampos: %r" % (projecao,))
    modos = {bool(v) for v in campos.values()}
    if len(modos) > 1:
        raise OperationFailure("Cannot do exclusion and inclusion in the same projection")
    if modos == {True}:
        resultado = {c: v for c, v in doc.items() if c in campos and c != "_id"}
    else:
        resultado = {c: v for c, v in doc.items() if c not in campos and c != "_id"}
    if mostrar_id and "_id" in doc:
        resultado = {"_id": doc["_id"], **resultado}
    return deepcopy(resultado)


def _chave_de_ordem(valor):
    """Ordem dos tipos do BSON: null/em falta < números < texto < … < booleanos."""
    if valor is _EM_FALTA or valor is None:
        return (0, 0)
    if isinstance(valor, bool):
        return (8, valor)
    if isinstance(valor, (int, float)):
        return (1, valor)
    if isinstance(valor, str):
        return (2, valor)
    return (5, repr(valor))


# --- Cursor e coleção ------------------------------------------------------------


class CursorFalso:
    """Imita find().sort().limit().to_list(n) do Motor. Lê a coleção só no
    `to_list` (como o Motor, que só pergunta ao Mongo ao iterar)."""

    def __init__(self, coleccao, filtro, projecao):
        self._coleccao = coleccao
        self._filtro = filtro
        self._projecao = projecao
        self._ordem = []
        self._limite = 0

    def sort(self, chave_ou_lista, direcao=1):
        if isinstance(chave_ou_lista, str):
            self._ordem = [(chave_ou_lista, direcao)]
        else:
            self._ordem = list(chave_ou_lista)
        return self

    def limit(self, n):
        self._limite = n
        return self

    async def to_list(self, length=None):
        await asyncio.sleep(0)
        self._coleccao._antes_de_operar("find")
        docs = [d for d in self._coleccao.docs if corresponde(d, self._filtro)]
        for campo, direcao in reversed(self._ordem):
            docs.sort(key=lambda d: _chave_de_ordem(_obter(d, campo)), reverse=direcao == -1)
        if self._limite:
            docs = docs[: self._limite]
        if length is not None:
            docs = docs[:length]
        return [_projetar(d, self._projecao) for d in docs]

    def __aiter__(self):
        return self._iterar()

    async def _iterar(self):
        for doc in await self.to_list(None):
            yield doc


class ColeccaoFalsa:
    """Duplo de uma coleção do Motor.

    - `docs`: os documentos guardados (cópias; cada um com `_id`).
    - `registo`: as chamadas por ordem, em cópia, como tuplos
      `("find_one", filtro, projecao)`, `("find", filtro, projecao)`,
      `("insert_one", doc)`, `("update_one", filtro, atualizacao, upsert)`,
      `("find_one_and_update", filtro, atualizacao, projecao, upsert,
      return_document)`,
      `("delete_one", filtro)`, `("delete_many", filtro)`,
      `("count_documents", filtro)`, `("create_index", chaves, opcoes)`.
      `chamadas(op)` filtra por operação.
    - `unicos`: campos únicos (um a um), com a semântica do Mongo.
    - `falhar`: `{operacao: excecao}` — a operação regista a chamada e levanta
      essa exceção (ex.: `{"insert_one": DuplicateKeyError("…")}` para a
      corrida). No `find`, levanta no `to_list`.
    - `antes_de(operacao, funcao)`: `funcao(docs)` corre antes de cada
      `operacao` (depois de ceder ao ciclo e antes da falha injetada), sobre a
      própria lista guardada — a escrita concorrente entre a leitura e a
      escrita de quem chama. No `find`, corre no `to_list`.
    """

    def __init__(self, docs=None, unicos=("id",), falhar=None, nome=None):
        self.nome = nome
        self.unicos = tuple(unicos)
        self.falhar = dict(falhar or {})
        desconhecidas = set(self.falhar) - set(OPERACOES)
        if desconhecidas:
            raise ValueError("falhar com operações que o duplo não conhece: %s" % sorted(desconhecidas))
        self.registo = []
        self.docs = []
        self._antes = {}
        for doc in docs or []:
            novo = deepcopy(doc)
            novo.setdefault("_id", ObjectId())
            self.docs.append(novo)

    # -- apoio aos testes --

    def chamadas(self, operacao):
        return [c for c in self.registo if c[0] == operacao]

    def sem_id(self):
        """Cópia dos documentos guardados sem o `_id` (para comparar nos testes)."""
        return [{c: deepcopy(v) for c, v in d.items() if c != "_id"} for d in self.docs]

    def antes_de(self, operacao, funcao):
        """Regista `funcao(docs)` para correr antes de cada `operacao` (ver o
        docstring da classe). `None` retira o gancho. Uma operação que o duplo
        não conhece é um erro do teste (ValueError)."""
        if operacao not in OPERACOES:
            raise ValueError("antes_de com uma operação que o duplo não conhece: %r" % (operacao,))
        if funcao is None:
            self._antes.pop(operacao, None)
        else:
            self._antes[operacao] = funcao

    # -- interno --

    def _registar(self, *chamada):
        self.registo.append(deepcopy(chamada))

    def _antes_de_operar(self, operacao):
        gancho = self._antes.get(operacao)
        if gancho is not None:
            gancho(self.docs)
        erro = self.falhar.get(operacao)
        if erro is not None:
            raise erro

    def _verificar_unicos(self, novo, ignorar=None):
        for campo in ("_id",) + self.unicos:
            valor = _obter(novo, campo)
            valor = None if valor is _EM_FALTA else valor
            for doc in self.docs:
                if doc is ignorar:
                    continue
                outro = _obter(doc, campo)
                outro = None if outro is _EM_FALTA else outro
                if _iguais(outro, valor):
                    raise DuplicateKeyError(
                        "E11000 duplicate key error collection: %s index: %s_1 dup key: { %s: %r }"
                        % (self.nome, campo, campo, valor),
                        11000,
                    )

    # -- operações do Motor --

    async def find_one(self, filtro=None, projecao=None, *, projection=None):
        projecao = projecao if projecao is not None else projection
        self._registar("find_one", filtro, projecao)
        await asyncio.sleep(0)
        self._antes_de_operar("find_one")
        for doc in self.docs:
            if corresponde(doc, filtro):
                return _projetar(doc, projecao)
        return None

    def find(self, filtro=None, projecao=None, *, projection=None):
        projecao = projecao if projecao is not None else projection
        self._registar("find", filtro, projecao)
        return CursorFalso(self, filtro, projecao)

    async def insert_one(self, doc):
        self._registar("insert_one", doc)
        await asyncio.sleep(0)
        self._antes_de_operar("insert_one")
        if "_id" not in doc:
            doc["_id"] = ObjectId()  # como o PyMongo: muda o dicionário de quem chama
        novo = deepcopy(doc)
        self._verificar_unicos(novo)
        self.docs.append(novo)
        return ResultadoInsert(doc["_id"])

    async def update_one(self, filtro, atualizacao, upsert=False):
        self._registar("update_one", filtro, atualizacao, upsert)
        await asyncio.sleep(0)
        self._antes_de_operar("update_one")
        _validar_atualizacao(atualizacao)
        alvo = next((d for d in self.docs if corresponde(d, filtro)), None)
        if alvo is None:
            if not upsert:
                return ResultadoUpdate(0, 0)
            novo = {
                campo: deepcopy(valor)
                for campo, valor in (filtro or {}).items()
                if not campo.startswith("$") and not _e_expressao(valor)
            }
            _aplicar_atualizacao(novo, atualizacao, ao_criar=True)
            novo.setdefault("_id", ObjectId())
            self._verificar_unicos(novo)
            self.docs.append(novo)
            return ResultadoUpdate(0, 0, novo["_id"])
        novo = deepcopy(alvo)
        _aplicar_atualizacao(novo, atualizacao)
        if novo == alvo:
            return ResultadoUpdate(1, 0)
        self._verificar_unicos(novo, ignorar=alvo)
        posicao = next(i for i, d in enumerate(self.docs) if d is alvo)
        self.docs[posicao] = novo
        return ResultadoUpdate(1, 1)

    async def find_one_and_update(
        self, filtro, atualizacao, projection=None, *, upsert=False, return_document=ReturnDocument.BEFORE
    ):
        """Como o do Motor: atualiza o primeiro que coincide e devolve-o (antes
        ou depois, com a projeção), ou None se nenhum coincidir. Sem upsert
        (não está modelado: rebenta em vez de mentir)."""
        self._registar("find_one_and_update", filtro, atualizacao, projection, upsert, return_document)
        await asyncio.sleep(0)
        self._antes_de_operar("find_one_and_update")
        if upsert:
            raise NotImplementedError("find_one_and_update com upsert não suportado pelo duplo")
        _validar_atualizacao(atualizacao)
        alvo = next((d for d in self.docs if corresponde(d, filtro)), None)
        if alvo is None:
            return None
        novo = deepcopy(alvo)
        _aplicar_atualizacao(novo, atualizacao)
        if novo != alvo:
            self._verificar_unicos(novo, ignorar=alvo)
            posicao = next(i for i, d in enumerate(self.docs) if d is alvo)
            self.docs[posicao] = novo
        return _projetar(novo if return_document == ReturnDocument.AFTER else alvo, projection)

    async def delete_one(self, filtro):
        self._registar("delete_one", filtro)
        await asyncio.sleep(0)
        self._antes_de_operar("delete_one")
        for posicao, doc in enumerate(self.docs):
            if corresponde(doc, filtro):
                del self.docs[posicao]
                return ResultadoDelete(1)
        return ResultadoDelete(0)

    async def delete_many(self, filtro):
        self._registar("delete_many", filtro)
        await asyncio.sleep(0)
        self._antes_de_operar("delete_many")
        ficam = [d for d in self.docs if not corresponde(d, filtro)]
        apagados = len(self.docs) - len(ficam)
        self.docs[:] = ficam
        return ResultadoDelete(apagados)

    async def count_documents(self, filtro):
        self._registar("count_documents", filtro)
        await asyncio.sleep(0)
        self._antes_de_operar("count_documents")
        return sum(1 for d in self.docs if corresponde(d, filtro))

    async def create_index(self, chaves, **opcoes):
        self._registar("create_index", chaves, opcoes)
        await asyncio.sleep(0)
        self._antes_de_operar("create_index")
        if isinstance(chaves, str):
            chaves = [(chaves, 1)]
        return opcoes.get("name") or "_".join("%s_%s" % (c, d) for c, d in chaves)


# --- Atualizações ($set, $setOnInsert, $inc, $push) --------------------------------


def _validar_atualizacao(atualizacao):
    """O que o PyMongo recusa (vazia, sem operadores), o que o Mongo recusa ao
    ler a atualização — antes de procurar o documento: um `$inc` que não é
    número (14) e dois caminhos em conflito (40) — e o que o duplo não conhece."""
    if not isinstance(atualizacao, dict) or not atualizacao:
        raise ValueError("update cannot be empty")
    if not all(k.startswith("$") for k in atualizacao):
        raise ValueError("update only works with $ operators")
    for operador, campos in atualizacao.items():
        if operador not in _OPERADORES_DE_ATUALIZACAO:
            raise NotImplementedError("operador %s não suportado pelo duplo" % operador)
        if not isinstance(campos, dict):
            raise ValueError("Modifiers operate on fields but we found type %s" % type(campos).__name__)
    for caminho, valor in atualizacao.get("$inc", {}).items():
        if not _numero(valor):
            raise OperationFailure("Cannot increment with non-numeric argument: {%s: %r}" % (caminho, valor), 14)
    for caminho, valor in atualizacao.get("$push", {}).items():
        if isinstance(valor, dict) and any(k.startswith("$") for k in valor):
            raise NotImplementedError("o duplo não conhece os modificadores do $push ($each, $position, …): %s" % caminho)
    _verificar_conflitos(atualizacao)


def _prefixo(curto, longo):
    return curto == longo or longo.startswith(curto + ".")


def _verificar_conflitos(atualizacao):
    """Dois caminhos iguais ou em que um é prefixo do outro, por segmentos
    (`paragens` e `paragens.0.x`; não `paragens` e `paragensx`), em qualquer
    operador: o erro 40 do Mongo (ConflictingUpdateOperators)."""
    vistos = []
    for campos in atualizacao.values():
        for caminho in campos:
            for anterior in vistos:
                if _prefixo(anterior, caminho) or _prefixo(caminho, anterior):
                    curto, longo = sorted((anterior, caminho), key=len)
                    raise OperationFailure(
                        "Updating the path '%s' would create a conflict at '%s'" % (longo, curto), 40
                    )
            vistos.append(caminho)


def _tipo_bson(valor):
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "bool"
    if isinstance(valor, str):
        return "string"
    if isinstance(valor, list):
        return "array"
    if isinstance(valor, dict):
        return "object"
    return type(valor).__name__


def _alcancar(doc, caminho, criar):
    """(contentor, chave) do último segmento de `caminho`, descendo pelos
    subdocumentos (criados quando faltam, se `criar`) e pelos índices das
    listas. Sem `criar`, (None, None) quando falta um subdocumento pelo
    caminho. Uma lista nunca se estica (NotImplementedError). Através de null
    ou de um escalar, ou numa lista sem índice numérico: o erro 28 do Mongo."""
    partes = caminho.split(".")
    atual = doc
    for posicao, parte in enumerate(partes):
        ultimo = posicao == len(partes) - 1
        if isinstance(atual, dict):
            if ultimo:
                return atual, parte
            if parte not in atual:
                if not criar:
                    return None, None
                atual[parte] = {}
            atual = atual[parte]
        elif isinstance(atual, list):
            indice = _indice(parte)
            if indice is None:
                raise OperationFailure(
                    "Cannot create field '%s' in element {%s: %r}" % (parte, partes[posicao - 1], atual), 28
                )
            if indice >= len(atual):
                raise NotImplementedError(
                    "o duplo não estica a lista: %s (índice %d, %d elementos)" % (caminho, indice, len(atual))
                )
            if ultimo:
                return atual, indice
            atual = atual[indice]
        else:
            raise OperationFailure(
                "Cannot create field '%s' in element {%s: %r}" % (parte, partes[posicao - 1], atual), 28
            )
    raise AssertionError("caminho vazio: %r" % caminho)


def _escrever(doc, caminho, valor):
    contentor, chave = _alcancar(doc, caminho, criar=True)
    contentor[chave] = valor


def _ler_para_escrever(doc, caminho):
    """O valor atual de `caminho` (o próprio objeto guardado) ou _EM_FALTA."""
    contentor, chave = _alcancar(doc, caminho, criar=False)
    if contentor is None:
        return _EM_FALTA
    if isinstance(contentor, dict):
        return contentor.get(chave, _EM_FALTA)
    return contentor[chave]


def _aplicar_atualizacao(doc, atualizacao, *, ao_criar=False):
    """Aplica os operadores a `doc` (já uma cópia de quem chama). O
    `$setOnInsert` só ao criar (upsert). Como os caminhos nunca estão em
    conflito (`_verificar_conflitos`), a ordem entre operadores não conta."""
    for caminho, valor in atualizacao.get("$set", {}).items():
        _escrever(doc, caminho, deepcopy(valor))
    if ao_criar:
        for caminho, valor in atualizacao.get("$setOnInsert", {}).items():
            _escrever(doc, caminho, deepcopy(valor))
    for caminho, valor in atualizacao.get("$inc", {}).items():
        atual = _ler_para_escrever(doc, caminho)
        if atual is _EM_FALTA:
            _escrever(doc, caminho, valor)
        elif not _numero(atual):
            raise OperationFailure(
                "Cannot apply $inc to a value of non-numeric type. {_id: %s} has the field '%s' of non-numeric type %s"
                % (doc.get("_id"), caminho, _tipo_bson(atual)),
                14,
            )
        else:
            _escrever(doc, caminho, atual + valor)
    for caminho, valor in atualizacao.get("$push", {}).items():
        atual = _ler_para_escrever(doc, caminho)
        if atual is _EM_FALTA:
            _escrever(doc, caminho, [deepcopy(valor)])
        elif not isinstance(atual, list):
            raise OperationFailure(
                "The field '%s' must be an array but is of type %s in document {_id: %s}"
                % (caminho, _tipo_bson(atual), doc.get("_id")),
                2,
            )
        else:
            atual.append(deepcopy(valor))


class BaseFalsa:
    """Duplo da Database do Motor: `base["nome"]` e `base.nome` devolvem a
    MESMA ColeccaoFalsa (criada à primeira vez, com `unicos_declarados`).

    `BaseFalsa({"users": [docs…], "crm_definicoes": ColeccaoFalsa(…)})` aceita
    listas de documentos (copiadas) ou coleções já feitas.

    Nomes começados por `_` levantam AttributeError, como no Motor — senão o
    copy/inspect/pytest, que procuram `__deepcopy__`, `__wrapped__`, `_pytest…`,
    recebiam uma coleção e davam erros estranhos.
    """

    def __init__(self, colecoes=None):
        self._colecoes = {}
        for nome, valor in (colecoes or {}).items():
            if isinstance(valor, ColeccaoFalsa):
                if valor.nome is None:
                    valor.nome = nome
                self._colecoes[nome] = valor
            else:
                self._colecoes[nome] = ColeccaoFalsa(valor, unicos=unicos_declarados(nome), nome=nome)

    def __getitem__(self, nome):
        if nome not in self._colecoes:
            self._colecoes[nome] = ColeccaoFalsa(unicos=unicos_declarados(nome), nome=nome)
        return self._colecoes[nome]

    def __getattr__(self, nome):
        if nome.startswith("_"):
            raise AttributeError(nome)
        return self[nome]
