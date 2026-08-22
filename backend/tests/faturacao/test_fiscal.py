"""A emissão da Fatura Simplificada com idempotência (Plano 2B, Task 3) —
o coração do módulo inteiro.

Nenhum teste liga a uma base de dados nem à rede. A "base de dados" é um
duplo com uniqueness REAL sobre os campos declarados como únicos em
`db.INDICES` (ext_ref em fat_refs_fiscais; vendus_document_id e atcud em
fat_documentos) — os testes de idempotência têm de exercitar a MESMA
garantia que o índice do Mongo dá em produção, não uma simulação à parte que
podia divergir dela.

O teste mais importante do ficheiro — e do plano inteiro — é o do
duplo-toque: duas chamadas CONCORRENTES (`asyncio.gather`, não sequenciais)
à mesma venda produzem uma só fatura. Funciona porque o asyncio é
cooperativo de uma só thread: cada duplo de colecção cede o controlo com um
`await asyncio.sleep(0)` antes de mexer nos dados, e entre esse ponto e o
resto da operação (síncrono, sem outro `await`) nenhuma outra tarefa pode
intrometer-se — é o suficiente para uma corrida real acontecer no teste, tal
como aconteceria com dois pedidos HTTP concorrentes num único processo
uvicorn.
"""
import re
import asyncio
from copy import deepcopy

import pytest
from pymongo.errors import DuplicateKeyError

from fastapi import HTTPException
from pydantic import ValidationError

from faturacao import db as db_mod
from faturacao import fiscal as fiscal_mod
from faturacao.db import COLECOES
from faturacao.fiscal import (
    ConflitoDocumentoFiscal,
    EmissaoEmCurso,
    PagamentoEntrada,
    PedidoFinalizarVenda,
    _datas_da_janela,
    _itens_vendus,
    _reconciliar_vendas_dinheiro,
    ext_ref_determinista,
    finalizar,
    finalizar_venda,
    verificar_vendas_dinheiro_no_vendus,
)
from faturacao.vendus.cliente import VendusHTTPErro, VendusIndisponivel
from faturacao.venda import _totais


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _arranque_saudavel_por_omissao():
    """I3: `finalizar` recusa-se (503) sem o índice de idempotência
    confirmado por `arrancar()`. Este ficheiro testa a ROTA directamente,
    sem nunca chamar `arrancar()` — por isso assume, como toda a suite já
    assumia implicitamente antes desta guarda existir, que o arranque
    correu bem; os testes que exercitam a PRÓPRIA guarda (I3) desligam-na
    explicitamente."""
    db_mod.marcar_indice_idempotencia(True)
    yield
    db_mod.marcar_indice_idempotencia(None)


# --- Duplo de base de dados, com uniqueness REAL ------------------------------


def _valores_no_caminho(item, chave):
    """Os valores que o Mongo compara para uma chave que pode ser um CAMINHO
    com pontos (`lista.campo`). Num array de subdocumentos, o Mongo casa o
    filtro contra CADA elemento — daí uma lista de valores e não um só."""
    if "." not in chave:
        return [item.get(chave)]
    primeiro, resto = chave.split(".", 1)
    valor = item.get(primeiro)
    if isinstance(valor, list):
        return [v for elemento in valor
                for v in _valores_no_caminho(elemento if isinstance(elemento, dict) else {}, resto)]
    if isinstance(valor, dict):
        return _valores_no_caminho(valor, resto)
    return [None]


def _corresponde(item, filtro):
    """Só o que o código de produção usa: igualdade, `$ne`, e caminhos com
    ponto. O `$ne` sobre um array de subdocumentos
    (`vendas_ligadas_depois_do_fecho.venda_id`) é o que torna idempotente a
    marca que a reconciliação deixa na sessão de caixa — sem o duplo o
    reproduzir, esse `$ne` ficava por testar e duas reconciliações da mesma
    conta gravavam os mesmos euros duas vezes."""
    if not filtro:
        return True
    for chave, valor in filtro.items():
        valores = _valores_no_caminho(item, chave)
        if isinstance(valor, dict) and "$ne" in valor:
            if valor["$ne"] in valores:
                return False
        elif isinstance(valor, dict) and "$regex" in valor:
            # Ver o mesmo ramo em test_venda.py: o travão do fecho pergunta
            # pelas reservas desta sessão pelo prefixo da `ext_ref`.
            if not any(re.search(valor["$regex"], str(v or "")) for v in valores):
                return False
        elif valor not in valores:
            return False
    return True


class ResultadoUpdateFalso:
    """Réplica minimalista do UpdateResult do pymongo/motor — só os dois
    campos de que `_reclamar_retoma` (B1) precisa para saber se a escrita
    CONDICIONAL encontrou mesmo uma reserva incerta ainda por reclamar, em
    vez de aplicar $set às cegas a 'o que quer que tenha calhado casar'.
    Mesmo duplo que test_caixa_endpoints.py já usa para I2 — a MESMA
    técnica, aqui aplicada à retoma de uma reserva incerta."""

    def __init__(self, matched_count):
        self.matched_count = matched_count
        self.modified_count = matched_count


class ResultadoDeleteFalso:
    """O mesmo, para o `delete_one` — `deleted_count` é o que decide a
    corrida em `_libertar_reserva_se_intacta` (a rota de gestão apaga a
    reserva CONDICIONALMENTE, e não pela leitura que fez quatro `await`s
    antes). Um duplo que devolvesse `None` deixava esse `deleted_count`
    impossível de testar — e era em cima dele que a defesa toda assentava."""

    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


def _como_o_motor(documento):
    """A cópia que o Motor devolve — e que este duplo tem de devolver também.

    O `find_one` real descodifica BSON de fresco a cada chamada: o resultado
    NUNCA está ligado ao que está no Mongo. Um duplo que devolvesse o próprio
    objecto guardado deixa um teste passar por ALIASING — o código de produção
    muta o que "leu", o Mongo falso muda sozinho, e a asserção fica verde sem
    que nenhuma escrita tenha acontecido. Já apanhou um caso real neste
    módulo: apagar o `venda.update(atualizacao)` de `cancelar_venda`
    (faturacao/venda.py) não punha um único teste vermelho.

    Cópia FUNDA, não `dict(d)`: é neste ficheiro que os documentos são mais
    aninhados — a venda traz `linhas`, cada linha traz `opcoes`, e depois de
    emitir traz `pagamentos`. Uma cópia rasa partilhava essas listas com o
    documento guardado, e o `linhas.append(...)` de `juntar_linha` ou o
    `alvo.update(...)` de `editar_linha` (faturacao/venda.py) continuavam a
    escrever no "Mongo" sem passar por nenhum `update_one` — exactamente o
    aliasing que isto vem fechar, uma camada abaixo.
    """
    return deepcopy(documento)


class CursorFalso:
    """Cursor de mentira que RESPEITA o limite do `to_list`.

    Devolver sempre a lista toda (era o que este duplo fazia) é um oráculo
    cego do mesmo género do `_liquido_dos_itens` mais abaixo: o código de
    produção podia pedir um limite e receber tudo, e um teste sobre "o que a
    listagem encontra" ficava verde mesmo quando em produção o limite cortava
    fora precisamente o documento procurado. Foi assim que a listagem das
    reservas presas passou a ter de filtrar em vez de ler tudo — ver
    `test_lista_encontra_a_reserva_presa_entre_milhares_de_resolvidas`."""

    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens if n is None else self._itens[:n]


class ColeccaoFalsa:
    """Duplo de uma colecção Mongo. `insert_one` cede o controlo (await
    sleep(0)) e SÓ DEPOIS verifica os campos únicos e insere — tudo isso sem
    mais nenhum `await` no meio, para o check-e-insere ser atómico do ponto
    de vista do event loop (a mesma garantia que um índice único dá em
    produção)."""

    def __init__(self, documentos=None, indices_unicos=None):
        self._documentos = documentos if documentos is not None else []
        self._indices_unicos = indices_unicos or []
        self.chamadas_insert = 0

    def find(self, filtro=None):
        return CursorFalso(
            [_como_o_motor(d) for d in self._documentos if _corresponde(d, filtro)]
        )

    async def find_one(self, filtro, projecao=None):
        await asyncio.sleep(0)
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return _como_o_motor(encontrados[0]) if encontrados else None

    async def insert_one(self, doc):
        await asyncio.sleep(0)  # ponto de "corrida" — simula I/O real
        for campo in self._indices_unicos:
            valor = doc.get(campo)
            if valor is not None and any(d.get(campo) == valor for d in self._documentos):
                raise DuplicateKeyError("chave duplicada: %s=%r" % (campo, valor))
        self.chamadas_insert += 1
        self._documentos.append(deepcopy(doc))
        return None

    async def delete_one(self, filtro):
        await asyncio.sleep(0)
        alvo = next((d for d in self._documentos if _corresponde(d, filtro)), None)
        if alvo is not None:
            self._documentos.remove(alvo)
        return ResultadoDeleteFalso(deleted_count=0 if alvo is None else 1)

    async def update_many(self, filtro, atualizacao):
        """`$set`/`$unset` em TODAS as que casam — hoje só o `$unset` da
        etiqueta do posto, que o fecho de caixa faz às contas que deixa
        abertas (`caixa._largar_o_posto_das_contas_abertas`). Sem isto o duplo
        levantava `AttributeError`, o `except` de lá engolia-o e o teste ficava
        verde a medir o contrário do que diz."""
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        for alvo in alvos:
            alvo.update(atualizacao.get("$set", {}))
            for campo in atualizacao.get("$unset", {}):
                alvo.pop(campo, None)
        return ResultadoUpdateFalso(matched_count=len(alvos))

    async def update_one(self, filtro, atualizacao):
        await asyncio.sleep(0)
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
            # `$push` — usado pela reconciliação para deixar na sessão de
            # caixa já fechada a marca de que uma venda lhe foi ligada
            # DEPOIS do Z. Tem de ser $push e não $set de uma lista relida:
            # duas reconciliações da mesma sessão perdiam uma das marcas.
            for campo, valor in (atualizacao.get("$push") or {}).items():
                alvos[0].setdefault(campo, []).append(deepcopy(valor))
        return ResultadoUpdateFalso(matched_count=len(alvos))


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes[nome]


def _unicos_de(coleccao):
    """Os campos com índice ÚNICO declarados em `db.INDICES` para esta
    colecção — LIDOS de lá, nunca copiados à mão.

    É o que liga este duplo à garantia real: se um `unique` desaparecer de
    `db.py`, os testes que dependem dele têm de ficar vermelhos. Uma lista
    escrita à mão aqui deixava-os verdes sobre uma garantia que em produção
    já não existia — exactamente o género de oráculo cego que este ficheiro
    passa a vida a evitar."""
    return [
        chave
        for (col, chaves, opcoes) in db_mod.INDICES
        if col == coleccao and opcoes.get("unique")
        for chave, _direccao in chaves
    ]


def _db(vendas=None, documentos=None, refs=None, tipos_pagamento=None, sessoes=None):
    # Por omissão, uma sessão ABERTA "sessao-1" — o sessao_id da _venda()
    # por omissão — para os testes que não são sobre a sessão de caixa (a
    # maioria) não terem de a passar sempre à mão (I1: finalizar recusa
    # emitir contra uma sessão fechada, ver os testes dedicados a isso).
    if sessoes is None:
        sessoes = [{"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "aberta"}]
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(vendas),
        # `ext_ref` é único em `fat_documentos` desde esta ronda (db.py): um
        # documento por venda. Sem o duplo o reproduzir, os testes da
        # duplicação silenciosa (duas linhas com a mesma ext_ref e ATCUDs
        # diferentes) passavam verdes sobre uma garantia que só existe em
        # produção — daí `_unicos_de`, que os lê de `db.INDICES`.
        COLECOES["documentos"]: ColeccaoFalsa(
            documentos, indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(
            refs, indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa(tipos_pagamento),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa(sessoes),
    })


def _operador(**over):
    o = {"operador_id": "op-1", "nome": "Rafaela", "perfil": "operador_caixa", "loja_id": "loja-1"}
    o.update(over)
    return o


def _tipo_pagamento(**over):
    t = {
        "id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU",
        "vendus_payment_method_id": "316430468", "ativo": True,
    }
    t.update(over)
    return t


class ClienteEmissaoVendusFalso:
    """Duplo de ClienteEmissaoVendus para os testes da ROTA — a emissão em
    si (payload, retentativas, register_id) já está testada com
    httpx.MockTransport em test_emissao.py; aqui só importa que a rota
    monta os itens/pagamentos certos e reage bem ao que este duplo devolve
    ou levanta."""

    instancias = []

    def __init__(self, chave):
        self.chave = chave
        self.chamadas_criar = []
        self.chamadas_procurar = []
        self.resposta_criar = _bruto()
        self.erro_criar = None
        self.resposta_procurar = None
        ClienteEmissaoVendusFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def criar_fatura_simplificada(self, linhas, pagamentos, cliente, external_reference, register_id):
        self.chamadas_criar.append({
            "linhas": linhas, "pagamentos": pagamentos, "cliente": cliente,
            "external_reference": external_reference, "register_id": register_id,
        })
        if self.erro_criar is not None:
            raise self.erro_criar
        return self.resposta_criar

    def procurar_por_referencia_externa(self, external_reference, register_id):
        self.chamadas_procurar.append(external_reference)
        return self.resposta_procurar


def _configura_vendus_env(monkeypatch, register_id="7", modo="tests"):
    monkeypatch.setenv("VENDUS_ACCOUNTS", '[{"key":"chave-teste","company_nif":"517542510"}]')
    monkeypatch.setenv("FAT_NIF", "517542510")
    monkeypatch.setenv("VENDUS_REGISTER_ID", register_id)
    monkeypatch.setenv("VENDUS_MODE", modo)


def _venda(**over):
    v = {
        "id": "venda-1", "loja_id": "loja-1", "sessao_id": "sessao-1", "caixa_id": "caixa-1",
        "operador_id": "op-1", "linhas": [], "estado": "aberta",
        "desconto_global_pct": None, "desconto_global_eur": None,
        "criada_em": "2026-08-15T09:05:00+00:00",
    }
    v.update(over)
    return v


def _linha(**over):
    li = {
        "id": "linha-1", "produto_id": "prod-1", "produto_nome": "Açaí Regular",
        "produto_preco": 8.99, "produto_tax_id": "INT", "quantidade": 1, "opcoes": [],
        "preco_override": None, "tax_override": None, "desconto_pct": None, "desconto_eur": None,
    }
    li.update(over)
    return li


def _bruto(**over):
    b = {"id": 501, "numero": "FS 2026/1", "atcud": "ATCUD-1", "total": 8.99,
         "talao_escpos": b"talao", "modo": "tests"}
    b.update(over)
    return b


async def _instantaneo(_segundos):
    await asyncio.sleep(0)


# --- Itens Vendus: B2 (a re-revisão do núcleo fiscal) — SEMPRE ---------------
# --- discount_percentage, NUNCA discount_amount --------------------------
#
# C3 tinha passado a enviar discount_amount (a distribuição do desconto
# GLOBAL em cêntimos exactos por linha, ver `_distribuir_centimos`). B2
# reverteu essa decisão: `discount_amount` NUNCA saiu deste código antes de
# C3, a sua semântica (desconto da linha INTEIRA vs desconto POR UNIDADE
# × qty) nunca foi confirmada contra o Vendus real, e o único outro sistema
# do dono a emitir Faturas Simplificadas reais pela MESMA API
# (`~/dev/pizzaria/backend/pos/pricing.py::combine_global`) recusa-se
# explicitamente a enviá-lo. A aritmética exacta ao cêntimo do C3
# (`_distribuir_centimos`) MANTÉM-SE — é só o ALVO interno de cada linha,
# nunca o que se envia — mas o campo final é sempre uma
# `discount_percentage`, reverse-engenheirada para REPRODUZIR esse alvo
# quando o Vendus a aplicar (`gross*(1-pct/100)`, arredondado ao cêntimo —
# ver `_percentagem_que_reproduz`).


def test_itens_vendus_sem_nenhum_desconto():
    venda = _venda(linhas=[_linha(quantidade=2)])
    itens = _itens_vendus(venda)
    assert itens == [{"title": "Açaí Regular", "qty": 2, "gross_price": 8.99, "tax_id": "INT"}]


def _liquido_dos_itens(itens):
    """O líquido que o Vendus calcularia destes itens: cada linha
    arredondada ao CÊNTIMO antes de somar — nunca uma soma sem arredondar
    linha a linha e só arredondar no fim (era isso, e não outra coisa, que
    escondia o defeito C3: uma soma sem arredondar por linha "batia certo"
    com `venda._totais` por coincidência do mesmo estilo de arredondamento
    nos dois lados, mesmo quando o Vendus real — que arredonda CADA linha —
    ia calcular outra coisa).

    B2: só sabe de `discount_percentage` — nunca `discount_amount`, que
    `_itens_vendus` já não deve produzir. Isto é deliberado: se
    `discount_amount` reaparecesse por engano num `item`, este helper
    IGNORA-O por completo (só olha para `discount_percentage`), por isso
    qualquer regressão que reintroduza `discount_amount` faz os testes
    abaixo DIVERGIREM de `venda._totais` em vez de continuarem a passar às
    escondidas — o mesmo "oráculo cego" que já escondeu C3 uma vez."""
    total = 0.0
    for it in itens:
        gross = round(it["qty"] * it["gross_price"], 2)
        pct = it.get("discount_percentage", 0.0)
        liquido_linha = round(gross * (1 - pct / 100.0), 2)
        total += liquido_linha
    return round(total, 2)


def test_itens_vendus_nunca_envia_discount_amount():
    """O cerne de B2, testado directamente: nenhum cenário de desconto —
    próprio da linha (€ ou %), global (€ ou %), ou os dois combinados —
    pode alguma vez produzir um item com `discount_amount`."""
    cenarios = [
        _venda(linhas=[_linha(desconto_pct=10)]),
        _venda(linhas=[_linha(desconto_eur=1.0)]),
        _venda(linhas=[_linha()], desconto_global_pct=10),
        _venda(linhas=[_linha()], desconto_global_eur=2.0),
        _venda(linhas=[_linha(desconto_pct=10)], desconto_global_pct=10),
        _venda(linhas=[_linha(desconto_eur=1.0)], desconto_global_eur=2.0),
    ]
    for venda in cenarios:
        for item in _itens_vendus(venda):
            assert "discount_amount" not in item, "venda=%r item=%r" % (venda, item)


def test_itens_vendus_com_tres_unidades_e_desconto_nunca_ambiguo_por_unidade_vs_linha():
    """O exemplo exacto da revisão B2: 3 unidades a 8,99€ com desconto —
    `discount_amount=5,13` numa linha `qty=3` seria ambíguo (21,84€ se o
    Vendus aplicar por linha, 11,58€ se for por unidade, 10,26€ de erro).
    Com `discount_percentage` a ambiguidade desaparece: a fórmula
    `gross*(1-pct/100)` é a MESMA independentemente de `qty`, porque
    `gross` já é o bruto da linha INTEIRA (`qty × gross_price`)."""
    venda = _venda(linhas=[_linha(quantidade=3, desconto_pct=19)])
    itens = _itens_vendus(venda)
    assert "discount_amount" not in itens[0]
    assert itens[0]["discount_percentage"] > 0
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_converte_o_desconto_proprio_da_linha_em_percentagem_mesmo_sem_desconto_global():
    venda = _venda(linhas=[_linha(desconto_pct=10)])
    itens = _itens_vendus(venda)
    assert "discount_amount" not in itens[0]
    assert itens[0]["discount_percentage"] > 0
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_com_desconto_global_percentagem_sem_desconto_de_linha():
    """Uma linha sem desconto próprio recebe a fatia inteira do desconto
    global, como discount_percentage — o líquido resultante bate
    EXACTAMENTE (não só "próximo") com venda._totais, a mesma fonte de
    verdade dos totais mostrados no ecrã."""
    venda = _venda(linhas=[_linha()], desconto_global_pct=10)
    itens = _itens_vendus(venda)
    assert "discount_percentage" in itens[0]
    assert "discount_amount" not in itens[0]
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_com_desconto_global_em_euros_bate_com_totais():
    venda = _venda(linhas=[_linha()], desconto_global_eur=2.0)
    itens = _itens_vendus(venda)
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_combina_desconto_de_linha_com_desconto_global_como_discount_percentage():
    """10% de desconto próprio da linha (0,90€) + 10% de desconto global
    sobre o líquido pós-linha (8,09€ × 10% = 0,81€, não 10% sobre o bruto —
    o global incide DEPOIS do desconto da linha, nunca em paralelo) somam
    1,71€ de desconto combinado — expresso como UMA ÚNICA
    discount_percentage que reproduz esse alvo. O líquido bate EXACTAMENTE
    com venda._totais."""
    venda = _venda(linhas=[_linha(desconto_pct=10)], desconto_global_pct=10)
    itens = _itens_vendus(venda)
    assert "discount_amount" not in itens[0]
    assert _liquido_dos_itens(itens) == _totais(venda)["total"] == 7.28


def test_itens_vendus_com_desconto_de_linha_em_euros_e_global_em_percentagem():
    venda = _venda(linhas=[_linha(desconto_eur=1.0)], desconto_global_pct=10)
    itens = _itens_vendus(venda)
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_com_duas_linhas_e_desconto_global_aplica_a_ambas():
    """O desconto global (1,15€) reparte-se pelas duas linhas PROPORCIONAL
    ao peso de cada uma (8,99€ vs 2,50€) — internamente ainda em cêntimos
    exactos (`_distribuir_centimos`, inalterado desde C3), só o campo FINAL
    é que passa a discount_percentage. O líquido bate EXACTAMENTE com
    venda._totais."""
    venda = _venda(
        linhas=[
            _linha(id="l1", quantidade=1),
            _linha(id="l2", produto_id="prod-2", produto_nome="Sumo", produto_preco=2.5,
                   produto_tax_id="NOR", quantidade=1),
        ],
        desconto_global_pct=10,
    )
    itens = _itens_vendus(venda)
    assert len(itens) == 2
    assert itens[1]["title"] == "Sumo"
    for item in itens:
        assert "discount_amount" not in item
    assert _liquido_dos_itens(itens) == _totais(venda)["total"] == 10.34


def test_itens_vendus_desconto_global_em_euros_bate_exactamente_com_o_que_o_vendus_calcularia():
    """A regressão de C3, revisitada por B2: 7 linhas a 1,15€ com 5€ de
    desconto global. ANTES de C3, o total mostrado à operadora
    (venda._totais) era 3,05€ mas uma discount_percentage composta e
    arredondada UMA VEZ sobre o total agregado dava 3,08€ ao Vendus — a
    aritmética exacta ao cêntimo de C3 (`_distribuir_centimos`, mantida por
    B2) é o que evita essa divergência: o ALVO de cada linha continua
    calculado ao cêntimo, só o campo enviado é que voltou a ser uma
    percentagem — reverse-engenheirada para REPRODUZIR esse alvo exacto,
    não uma composta e arredondada de outra forma. Os dois lados continuam
    a bater SEMPRE, mesmo sem discount_amount."""
    venda = _venda(
        linhas=[_linha(id="l%d" % i, produto_preco=1.15) for i in range(7)],
        desconto_global_eur=5.0,
    )
    itens = _itens_vendus(venda)
    for item in itens:
        assert "discount_amount" not in item
        assert item["discount_percentage"] > 0
    assert _liquido_dos_itens(itens) == _totais(venda)["total"] == 3.05


def test_itens_vendus_sem_desconto_algum_nao_tem_discount_percentage():
    venda = _venda(linhas=[_linha()])
    itens = _itens_vendus(venda)
    assert "discount_percentage" not in itens[0]
    assert "discount_amount" not in itens[0]


def test_itens_vendus_venda_sem_linhas_devolve_lista_vazia():
    assert _itens_vendus(_venda(linhas=[])) == []


# --- O `id` do produto atravessa a lista branca de `_itens_vendus` ----------
#
# `_itens_vendus` escolhe A DEDO as chaves que saem do item — o que não
# estiver na lista não vai para o Vendus, por muito que
# `precos.linha_de_venda` o produza. Foi aqui que o `id` do produto quase se
# perdeu em silêncio: construído na linha, deitado fora antes da rede, e o
# Vendus a continuar a criar um produto novo por cada venda (95 produtos e 13
# órfãos do "Açaí Mini" na conta real) como se a correcção não existisse.


def test_itens_vendus_leva_o_id_do_produto_no_vendus():
    venda = _venda(linhas=[_linha(produto_vendus_ref="171258472")])
    assert _itens_vendus(venda) == [
        {"id": 171258472, "title": "Açaí Regular", "qty": 1, "gross_price": 8.99,
         "tax_id": "INT"}
    ]


def test_itens_vendus_de_linha_sem_vendus_ref_nao_leva_o_campo():
    """Sem `vendus_ref` (artigo criado à mão no backoffice, ou linha gravada
    antes desta alteração) o item sai como saía — nunca com `id: null`."""
    itens = _itens_vendus(_venda(linhas=[_linha()]))
    assert "id" not in itens[0]
    assert itens[0] == {"title": "Açaí Regular", "qty": 1, "gross_price": 8.99,
                        "tax_id": "INT"}


def test_itens_vendus_com_id_nao_mexe_no_desconto_nem_no_dinheiro():
    """O `id` acompanha o desconto sem lhe tocar: os mesmos números com e sem
    ele, e o líquido continua a bater com `venda._totais` ao cêntimo."""
    def _venda_com(ref):
        return _venda(
            linhas=[
                _linha(id="l1", quantidade=3, produto_vendus_ref=ref),
                _linha(id="l2", produto_id="prod-2", produto_nome="Sumo",
                       produto_preco=2.5, produto_tax_id="NOR", quantidade=1,
                       produto_vendus_ref=ref),
            ],
            desconto_global_eur=5.0,
        )

    sem = _itens_vendus(_venda_com(None))
    com = _itens_vendus(_venda_com("171258472"))
    assert [i.pop("id") for i in com] == [171258472, 171258472]
    assert com == sem
    assert _liquido_dos_itens(com) == _totais(_venda_com("171258472"))["total"]


# --- _percentagem_que_reproduz (núcleo puro de B2) -----------------------------


def test_percentagem_que_reproduz_reproduz_o_alvo_exacto():
    from faturacao.fiscal import _percentagem_que_reproduz

    pct = _percentagem_que_reproduz(8.99, 8.09)
    assert round(8.99 * (1 - pct / 100.0), 2) == 8.09


def test_percentagem_que_reproduz_sem_alvo_menor_que_bruto_devolve_zero():
    from faturacao.fiscal import _percentagem_que_reproduz

    assert _percentagem_que_reproduz(8.99, 8.99) == 0.0


def test_percentagem_que_reproduz_com_bruto_zero_nao_rebenta():
    from faturacao.fiscal import _percentagem_que_reproduz

    assert _percentagem_que_reproduz(0.0, 0.0) == 0.0


def test_percentagem_que_reproduz_alvo_zero_e_cem_porcento():
    from faturacao.fiscal import _percentagem_que_reproduz

    assert _percentagem_que_reproduz(8.99, 0.0) == 100.0


def test_fuzz_itens_vendus_bate_sempre_com_totais_em_precos_realistas():
    """A prova por simulação (mesmo espírito do fuzz de 20000/30000 vendas
    de C3): para tamanhos de venda realistas para uma loja de açaí (linhas
    até 50€, até 100 unidades, até 10 linhas — muito acima de qualquer
    conta real das 5 lojas), `_itens_vendus` reproduzido linha a linha
    NUNCA diverge de `venda._totais`. Fica documentado no relatório da
    tarefa que, para vendas artificialmente enormes (a percentagem só tem
    4 casas decimais), pode sobrar um cêntimo — não observado nesta gama
    realista em 2000 simulações."""
    import random

    aleatorio = random.Random(20260815)
    divergencias = 0
    for _ in range(2000):
        n_linhas = aleatorio.randint(1, 6)
        linhas = []
        for i in range(n_linhas):
            preco = round(aleatorio.uniform(0.5, 50.0), 2)
            qty = aleatorio.randint(1, 20)
            r = aleatorio.random()
            desconto_pct = desconto_eur = None
            if r < 0.35:
                desconto_pct = round(aleatorio.uniform(1, 90), 0)
            elif r < 0.55:
                bruto_linha = round(preco * qty, 2)
                desconto_eur = round(aleatorio.uniform(0.01, max(0.01, bruto_linha * 0.9)), 2)
            linhas.append(_linha(
                id="l%d" % i, produto_preco=preco, quantidade=qty,
                desconto_pct=desconto_pct, desconto_eur=desconto_eur,
            ))

        r2 = aleatorio.random()
        g_pct = g_eur = None
        liquido_estimado = sum(round(li["produto_preco"] * li["quantidade"], 2) for li in linhas)
        if r2 < 0.4:
            g_pct = round(aleatorio.uniform(1, 60), 0)
        elif r2 < 0.7:
            g_eur = round(aleatorio.uniform(0.01, max(0.01, liquido_estimado * 0.5)), 2)

        venda = _venda(linhas=linhas, desconto_global_pct=g_pct, desconto_global_eur=g_eur)
        itens = _itens_vendus(venda)
        total_esperado = _totais(venda)["total"]
        if total_esperado <= 0:
            continue
        if _liquido_dos_itens(itens) != total_esperado:
            divergencias += 1

    assert divergencias == 0


# --- Referência determinística (nunca do relógio) -----------------------------


def test_ext_ref_tem_o_formato_pos_loja_sessao_venda():
    assert ext_ref_determinista("loja-1", "sessao-1", "venda-1") == "pos-loja-1-sessao-1-venda-1"


def test_ext_ref_e_a_mesma_para_duas_chamadas_da_mesma_venda():
    """Depende só da identidade da venda — nunca de um relógio."""
    a = ext_ref_determinista("loja-1", "sessao-1", "venda-1")
    b = ext_ref_determinista("loja-1", "sessao-1", "venda-1")
    assert a == b


def test_ext_ref_e_diferente_para_vendas_diferentes():
    a = ext_ref_determinista("loja-1", "sessao-1", "venda-1")
    b = ext_ref_determinista("loja-1", "sessao-1", "venda-2")
    assert a != b


# --- Emissão feliz -------------------------------------------------------------


def test_emissao_feliz_grava_o_documento_e_marca_a_venda_emitida():
    db = _db(vendas=[_venda()])
    chamadas = []

    async def emitir(ref):
        chamadas.append(ref)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não devia verificar numa emissão sem falhas")

    documento = _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert chamadas == ["pos-loja-1-sessao-1-venda-1"]
    assert documento["vendus_document_id"] == 501
    assert documento["atcud"] == "ATCUD-1"
    assert documento["ext_ref"] == "pos-loja-1-sessao-1-venda-1"
    venda_gravada = db[COLECOES["vendas"]]._documentos[0]
    assert venda_gravada["estado"] == "emitida"
    assert venda_gravada["documento_id"] == documento["id"]


# --- O TESTE MAIS IMPORTANTE: duplo-toque concorrente -------------------------


def test_duplo_toque_concorrente_emite_uma_so_fatura():
    """Duas chamadas CONCORRENTES (não sequenciais) à mesma venda — o
    duplo-toque no botão Emitir, ou um retry de rede a cruzar-se com o
    pedido original — produzem UMA só fatura.

    É a reserva atómica (índice único em ext_ref) que decide a corrida, não
    uma leitura antes de escrever. Mutação verificada manualmente (ver o
    relatório da tarefa): sem a reserva, este teste fica vermelho."""
    db = _db(vendas=[_venda()])
    chamadas_emitir = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        await asyncio.sleep(0)  # simula I/O real — dá espaço à outra tarefa avançar
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não devia haver timeout neste teste")

    async def correr():
        return await asyncio.gather(
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo),
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo),
        )

    resultados = _corre(correr())

    assert len(chamadas_emitir) == 1, "o Vendus só podia ter sido chamado UMA vez"
    assert resultados[0]["vendus_document_id"] == 501
    assert resultados[1]["vendus_document_id"] == 501
    assert resultados[0]["id"] == resultados[1]["id"]  # o MESMO documento local
    assert len(db[COLECOES["documentos"]]._documentos) == 1


def test_duplo_toque_com_tres_chamadas_concorrentes_emite_uma_so_fatura():
    """O mesmo teste com três tentativas concorrentes (ex.: duplo-toque +
    um retry automático a cruzar-se) — a garantia não é "no máximo duas"."""
    db = _db(vendas=[_venda()])
    chamadas_emitir = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        await asyncio.sleep(0)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não devia haver timeout neste teste")

    async def correr():
        return await asyncio.gather(*[
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo)
            for _ in range(3)
        ])

    resultados = _corre(correr())
    assert len(chamadas_emitir) == 1
    assert len({r["id"] for r in resultados}) == 1
    assert len(db[COLECOES["documentos"]]._documentos) == 1


# --- B1 (re-revisão do núcleo fiscal): reserva incerta sem exclusão mútua -----
#
# C1 fechou o caso SEQUENCIAL (uma reserva incerta obriga a retoma a
# verificar antes de emitir). Mas `_retomar_reserva_incerta` nunca RECLAMAVA
# a retoma — como a reserva já existe (não é um insert_one novo), `_reservar`
# deixa de decidir a corrida nenhuma. Duas ou mais tentativas concorrentes
# que encontrem a MESMA reserva incerta verificam TODAS, veem todas vazio, e
# EMITEM todas. Cenário real: a rede oscila, a 1ª tentativa dá 503 e deixa a
# reserva incerta; a operadora, já com a rede boa, carrega DUAS VEZES em
# FINALIZAR — sem uma reclamação com exclusão mútua, saem DUAS Faturas
# Simplificadas reais, cada uma com o seu ATCUD.


def test_duas_chamadas_concorrentes_sobre_reserva_incerta_emitem_uma_so_fatura():
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )
    chamadas_emitir = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        await asyncio.sleep(0)
        return _bruto()

    async def verificar(ref):
        await asyncio.sleep(0)
        return None  # o Vendus confirma que ainda não tem nada desta venda

    async def correr():
        return await asyncio.gather(
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo),
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo),
        )

    resultados = _corre(correr())

    assert len(chamadas_emitir) == 1, "o Vendus só podia ter sido chamado UMA vez"
    assert resultados[0]["id"] == resultados[1]["id"]
    assert len(db[COLECOES["documentos"]]._documentos) == 1


def test_tres_chamadas_concorrentes_sobre_reserva_incerta_emitem_uma_so_fatura():
    """A mesma garantia, com três tentativas concorrentes (duplo-toque + um
    retry automático a cruzar-se, por exemplo) — nunca 'no máximo duas'."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )
    chamadas_emitir = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        await asyncio.sleep(0)
        return _bruto()

    async def verificar(ref):
        await asyncio.sleep(0)
        return None

    async def correr():
        return await asyncio.gather(*[
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo)
            for _ in range(3)
        ])

    resultados = _corre(correr())

    assert len(chamadas_emitir) == 1
    assert len({r["id"] for r in resultados}) == 1
    assert len(db[COLECOES["documentos"]]._documentos) == 1


def test_reclamar_retoma_ganha_uma_so_vez_para_a_mesma_reserva():
    """O núcleo da correcção, isolado: `_reclamar_retoma` é a escrita
    CONDICIONAL (mesmo raciocínio de I2 nos fechos de caixa) que decide a
    corrida — chamá-la duas vezes CONCORRENTEMENTE sobre a MESMA reserva
    incerta só pode dar um `True` e o resto `False`."""
    from faturacao.fiscal import _reclamar_retoma

    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}])

    async def correr():
        return await asyncio.gather(*[_reclamar_retoma(db, ref) for _ in range(5)])

    resultados = _corre(correr())
    assert sorted(resultados) == [False, False, False, False, True]


def test_reserva_incerta_resolvida_limpa_a_marca_para_sempre():
    """'Um problema associado' da mesma revisão: hoje a reserva fica
    marcada `incerta` PARA SEMPRE, mesmo depois de o documento existir — a
    correcção limpa `incerta` (e a marca de retoma) assim que esta se
    resolve, para a listagem de gestão (reservas presas) não continuar a
    mostrar como 'presa' uma reserva que já tem documento fiscal."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )

    async def emitir(ref):
        return _bruto()

    async def verificar(ref):
        return None

    _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    reserva = db[COLECOES["refs_fiscais"]]._documentos[0]
    assert reserva.get("incerta") is False
    assert not reserva.get("em_retoma")


def test_reserva_incerta_que_falha_outra_vez_repoe_incerta_e_liberta_a_retoma():
    """Se a retoma falhar OUTRA VEZ (novo timeout + verificação também a
    falhar), a reserva continua incerta — mas a marca de RETOMA tem de se
    limpar à mesma, senão NENHUMA tentativa futura consegue voltar a
    reclamar: um impasse pior do que o defeito original. Prova-se pelo
    estado E pelo comportamento: uma tentativa SEGUINTE (a rede já boa)
    ainda tem de conseguir reclamar e resolver — não pode ficar presa atrás
    da marca da tentativa anterior."""
    from faturacao.fiscal import VerificacaoFiscalIncerta

    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )

    async def emitir_falha(ref):
        raise VendusIndisponivel("timeout simulado, outra vez")

    async def verificar_falha(ref):
        raise VendusIndisponivel("a verificação continua a falhar")

    with pytest.raises(VerificacaoFiscalIncerta):
        _corre(finalizar_venda(db, _venda(), emitir_falha, verificar_falha, esperar=_instantaneo))

    reserva = db[COLECOES["refs_fiscais"]]._documentos[0]
    assert reserva.get("incerta") is True
    assert not reserva.get("em_retoma")

    # A rede volta a ficar boa: uma tentativa SEGUINTE tem de conseguir
    # reclamar a retoma e resolver — nunca ficar presa atrás da marca que a
    # tentativa anterior deixou.
    async def emitir_ok(ref):
        return _bruto()

    async def verificar_ok(ref):
        return None

    documento = _corre(finalizar_venda(db, _venda(), emitir_ok, verificar_ok, esperar=_instantaneo))
    assert documento["vendus_document_id"] == 501


def test_quem_perde_a_reclamacao_da_retoma_espera_pelo_vencedor():
    """Quem NÃO reclama a retoma (porque outra tentativa já reclamou) cai
    no MESMO caminho de sempre de quem perde uma reserva — espera pelo
    documento do vencedor, nunca verifica/emite em paralelo."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True, "em_retoma": True}],
    )

    async def escrever_documento_daqui_a_pouco():
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await db[COLECOES["documentos"]].insert_one({
            "id": "doc-1", "vendus_document_id": 501, "atcud": "ATCUD-1",
            "ext_ref": ref, "venda_id": "venda-1", "total": 8.99,
        })

    async def emitir(ref):
        raise AssertionError("perdeu a reclamação da retoma — não devia tentar emitir")

    async def verificar(ref):
        raise AssertionError("perdeu a reclamação da retoma — não é chamado")

    async def correr():
        return await asyncio.gather(
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo),
            escrever_documento_daqui_a_pouco(),
        )

    resultado, _ = _corre(correr())
    assert resultado["vendus_document_id"] == 501


# --- Timeout seguido de verificação exacta -------------------------------------


def test_timeout_na_emissao_seguido_de_verificacao_que_encontra_nao_duplica():
    """Se `emitir` levantar VendusIndisponivel (rede/timeout), a verificação
    por external_reference é chamada — UMA vez — e, se encontrar o
    documento, é ESSE que se grava, sem uma segunda emissão."""
    db = _db(vendas=[_venda()])
    chamadas_emitir = []
    chamadas_verificar = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        raise VendusIndisponivel("timeout simulado")

    async def verificar(ref):
        chamadas_verificar.append(ref)
        return _bruto(id=777, atcud="ATCUD-777")

    documento = _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert len(chamadas_emitir) == 1
    assert chamadas_verificar == ["pos-loja-1-sessao-1-venda-1"]
    assert documento["vendus_document_id"] == 777
    assert documento["atcud"] == "ATCUD-777"
    venda_gravada = db[COLECOES["vendas"]]._documentos[0]
    assert venda_gravada["estado"] == "emitida"


def test_timeout_seguido_de_verificacao_sem_documento_propaga_o_erro_e_liberta_a_reserva():
    """Se a verificação NÃO encontrar nada, o Vendus não chegou a processar
    o pedido — propaga-se o erro original (o POS mostra "tente outra vez") e
    a reserva liberta-se, para a próxima tentativa poder reservar de novo."""
    db = _db(vendas=[_venda()])

    async def emitir(ref):
        raise VendusIndisponivel("timeout simulado")

    async def verificar(ref):
        return None

    with pytest.raises(VendusIndisponivel):
        _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert db[COLECOES["refs_fiscais"]]._documentos == []  # reserva libertada
    assert db[COLECOES["documentos"]]._documentos == []
    venda_gravada = db[COLECOES["vendas"]]._documentos[0]
    assert venda_gravada["estado"] == "aberta"  # não foi tocada


def test_verificacao_apos_timeout_que_tambem_falha_mantem_a_reserva_incerta():
    """C1: o POST em timeout E a própria verificação a rebentar é a falha
    CORRELACIONADA e mais provável (a mesma rede que derrubou o POST derruba
    o GET a seguir) — nunca se pode concluir daqui que é seguro reservar de
    novo. A verificação continua a ser UMA chamada exacta (nunca um
    varrimento), mas agora a reserva FICA — marcada incerta — em vez de se
    libertar (era isto que test_verificacao_apos_timeout_e_uma_so_chamada_
    nunca_um_varrimento defendia ao contrário: 'refs_fiscais == []')."""
    from faturacao.fiscal import VerificacaoFiscalIncerta

    db = _db(vendas=[_venda()])

    async def emitir(ref):
        raise VendusIndisponivel("timeout simulado")

    contagem = {"chamadas": 0}

    async def verificar(ref):
        contagem["chamadas"] += 1
        raise VendusIndisponivel("a própria verificação também rebentou")

    with pytest.raises(VerificacaoFiscalIncerta):
        _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert contagem["chamadas"] == 1  # nunca insiste a verificar às cegas
    refs = db[COLECOES["refs_fiscais"]]._documentos
    assert len(refs) == 1 and refs[0]["incerta"] is True  # a reserva FICA, marcada incerta
    assert db[COLECOES["documentos"]]._documentos == []
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_retry_apos_reserva_incerta_e_obrigado_a_verificar_antes_de_emitir():
    """O cenário da loja (C1): a rede oscila, o timeout da 1ª tentativa
    deixa a reserva incerta (teste acima), a operadora carrega outra vez em
    FINALIZAR. A 2ª tentativa NÃO pode emitir às cegas — tem de verificar
    primeiro. Aqui a verificação encontra o documento que a 1ª tentativa
    afinal tinha conseguido emitir no Vendus (só a resposta é que se
    perdeu) — reutiliza-o, NUNCA chama `emitir` uma segunda vez. Sem esta
    defesa, saíam duas Faturas Simplificadas reais da mesma venda."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )

    async def emitir(ref):
        raise AssertionError("a 2ª tentativa não podia emitir sem verificar primeiro")

    chamadas_verificar = []

    async def verificar(ref):
        chamadas_verificar.append(ref)
        return _bruto(id=888, atcud="ATCUD-888")

    documento = _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert chamadas_verificar == [ref]
    assert documento["vendus_document_id"] == 888
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "emitida"


def test_retry_apos_reserva_incerta_com_verificacao_limpa_emite_uma_so_vez():
    """Mesmo cenário, mas desta vez a verificação confirma que o Vendus
    NUNCA recebeu a 1ª tentativa (POST e GET falharam os dois, nada foi
    criado do outro lado) — só então a 2ª tentativa pode emitir a sério, e
    apenas uma vez."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )
    chamadas_emitir = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        return _bruto()

    async def verificar(ref):
        return None  # o Vendus confirma que não tem nada desta venda

    documento = _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert chamadas_emitir == [ref]
    assert documento["vendus_document_id"] == 501
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "emitida"


def test_retry_apos_reserva_incerta_com_verificacao_a_falhar_outra_vez_nao_emite():
    """Se a verificação voltar a falhar na 2ª tentativa, continua sem se
    poder concluir nada — não emite (nunca às cegas), e a reserva continua
    incerta para a tentativa seguinte."""
    from faturacao.fiscal import VerificacaoFiscalIncerta

    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda()],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}],
    )

    async def emitir(ref):
        raise AssertionError("não pode emitir sem confirmar primeiro")

    async def verificar(ref):
        raise VendusIndisponivel("a verificação continua a falhar")

    with pytest.raises(VerificacaoFiscalIncerta):
        _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    refs = db[COLECOES["refs_fiscais"]]._documentos
    assert len(refs) == 1 and refs[0]["incerta"] is True


# --- Falha depois da reserva liberta-a -----------------------------------------


def test_falha_normal_na_emissao_liberta_a_reserva():
    """Um erro que NÃO é de indisponibilidade (ex.: 400 do Vendus — dados
    inválidos) não passa pela verificação: sabemos que o Vendus recusou o
    pedido e não criou nada. A reserva liberta-se para a operadora poder
    corrigir e tentar de novo."""
    db = _db(vendas=[_venda()])

    async def emitir(ref):
        raise VendusHTTPErro(400, "dados inválidos")

    async def verificar(ref):
        raise AssertionError("um 400 não é timeout — não se verifica")

    with pytest.raises(VendusHTTPErro):
        _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert db[COLECOES["refs_fiscais"]]._documentos == []
    assert db[COLECOES["documentos"]]._documentos == []
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"


def test_falha_ao_gravar_o_documento_nao_liberta_a_reserva_e_alerta():
    """Caso extremo: o Vendus emitiu mesmo um documento (temos `bruto`), mas
    gravá-lo localmente colide com OUTRO documento (mesmo vendus_document_id
    OU atcud, referência externa DIFERENTE) — não pode acontecer com um
    Vendus saudável, mas se acontecer a reserva NÃO se liberta (o documento
    fiscal existe, libertar convidava a emitir outra vez) e o erro tem de
    ser alto e claro, para investigação manual."""
    documento_existente = {
        "id": "doc-existente", "vendus_document_id": 999, "atcud": "ATCUD-1",
        "ext_ref": "pos-loja-1-sessao-1-venda-OUTRA",
    }
    db = _db(vendas=[_venda()], documentos=[documento_existente])

    async def emitir(ref):
        return _bruto(id=501, atcud="ATCUD-1")  # mesmo atcud do documento existente

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    with pytest.raises(ConflitoDocumentoFiscal):
        _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    # A reserva desta venda continua lá — NÃO se liberta.
    refs = db[COLECOES["refs_fiscais"]]._documentos
    assert any(r["ext_ref"] == "pos-loja-1-sessao-1-venda-1" for r in refs)
    # Nenhum documento novo foi gravado (o índice único recusou-o).
    assert len(db[COLECOES["documentos"]]._documentos) == 1


# --- atcud repetido é recusado pelo índice -------------------------------------


def test_atcud_repetido_e_recusado_pelo_indice():
    """A quarta defesa: mesmo que a reserva por ext_ref falhasse por alguma
    razão, um atcud repetido nunca fica gravado duas vezes — é o próprio
    índice único de fat_documentos que recusa, não uma verificação
    aplicacional que se podia esquecer de chamar."""
    colecao = ColeccaoFalsa(
        documentos=[{"id": "d1", "vendus_document_id": 1, "atcud": "ATCUD-X", "ext_ref": "pos-a"}],
        indices_unicos=["vendus_document_id", "atcud"],
    )
    with pytest.raises(DuplicateKeyError):
        _corre(colecao.insert_one({"id": "d2", "vendus_document_id": 2, "atcud": "ATCUD-X", "ext_ref": "pos-b"}))


def test_vendus_document_id_repetido_e_recusado_pelo_indice():
    colecao = ColeccaoFalsa(
        documentos=[{"id": "d1", "vendus_document_id": 42, "atcud": "ATCUD-A", "ext_ref": "pos-a"}],
        indices_unicos=["vendus_document_id", "atcud"],
    )
    with pytest.raises(DuplicateKeyError):
        _corre(colecao.insert_one({"id": "d2", "vendus_document_id": 42, "atcud": "ATCUD-B", "ext_ref": "pos-b"}))


# --- Reserva sem documento ainda: espera pelo vencedor -------------------------


def test_reserva_perdida_espera_e_devolve_o_documento_do_vencedor():
    """Quando a reserva já existe mas o documento ainda não foi gravado (o
    vencedor está a meio da chamada ao Vendus), quem perde a corrida ESPERA
    — não falha imediatamente nem inventa nada."""
    db = _db(vendas=[_venda()], refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1"}])

    async def escrever_documento_daqui_a_pouco():
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await db[COLECOES["documentos"]].insert_one({
            "id": "doc-1", "vendus_document_id": 501, "atcud": "ATCUD-1",
            "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1", "total": 8.99,
        })

    async def emitir(ref):
        raise AssertionError("perdeu a corrida — não devia tentar emitir")

    async def verificar(ref):
        raise AssertionError("perdeu a corrida — não é um timeout")

    async def correr():
        return await asyncio.gather(
            finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo),
            escrever_documento_daqui_a_pouco(),
        )

    resultado, _ = _corre(correr())
    assert resultado["vendus_document_id"] == 501


def test_reserva_perdida_sem_documento_a_tempo_desiste_com_erro_claro():
    """Se o vencedor nunca escrever o documento dentro do orçamento de
    espera (ex.: crashou a meio), quem perde a corrida não fica bloqueado
    para sempre nem inventa um documento — desiste com um erro claro."""
    db = _db(vendas=[_venda()], refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1"}])

    async def emitir(ref):
        raise AssertionError("não devia tentar emitir")

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    with pytest.raises(EmissaoEmCurso):
        _corre(finalizar_venda(
            db, _venda(), emitir, verificar, esperar=_instantaneo, tentativas_espera=3,
        ))


# ============================================================================
# A ROTA: POST /pos/venda/{venda_id}/finalizar
# ============================================================================


def test_finalizar_com_sucesso_emite_grava_e_marca_a_venda(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    resultado = _corre(finalizar(
        "venda-1",
        PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
        operador=_operador(),
    ))

    assert resultado["estado"] == "emitida"
    assert resultado["documento"]["vendus_document_id"] == 501
    assert resultado["documento"]["atcud"] == "ATCUD-1"
    assert resultado["documento"]["modo"] == "tests"
    assert resultado["pagamentos"] == [
        {"tipo_pagamento_id": "tipo-dinheiro", "nome": "Dinheiro", "tipo_fiscal": "NU", "valor": 8.99}
    ]
    cliente = ClienteEmissaoVendusFalso.instancias[0]
    assert len(cliente.chamadas_criar) == 1
    chamada = cliente.chamadas_criar[0]
    assert chamada["external_reference"] == "pos-loja-1-sessao-1-venda-1"
    assert chamada["register_id"] == 7
    assert chamada["pagamentos"] == [{"id": "316430468", "amount": 8.99}]
    assert chamada["cliente"] is None


def test_finalizar_com_nif_inclui_o_cliente_no_pedido_ao_vendus(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    resultado = _corre(finalizar(
        "venda-1",
        PedidoFinalizarVenda(
            pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)],
            nif="123 456 789",
        ),
        operador=_operador(),
    ))
    assert resultado["cliente_nif"] == "123456789"
    cliente = ClienteEmissaoVendusFalso.instancias[0]
    assert cliente.chamadas_criar[0]["cliente"] == {"fiscal_id": "123456789"}


def test_finalizar_com_pagamento_misto_grava_o_tipo_fiscal_de_cada_um(monkeypatch):
    """Dinheiro + multibanco (Task 4 vai somar só a parte 'NU')."""
    _configura_vendus_env(monkeypatch)
    tipo_mb = _tipo_pagamento(
        id="tipo-mb", nome="Multibanco", tipo_fiscal="CD", vendus_payment_method_id="316430469"
    )
    db = _db(
        vendas=[_venda(linhas=[_linha(quantidade=2)])],  # 17.98
        tipos_pagamento=[_tipo_pagamento(), tipo_mb],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    resultado = _corre(finalizar(
        "venda-1",
        PedidoFinalizarVenda(pagamentos=[
            PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=10.0),
            PagamentoEntrada(tipo_pagamento_id="tipo-mb", valor=7.98),
        ]),
        operador=_operador(),
    ))
    assert {p["tipo_fiscal"]: p["valor"] for p in resultado["pagamentos"]} == {"NU": 10.0, "CD": 7.98}


def test_finalizar_grava_pagamento_e_nif_so_depois_de_ganhar_a_reserva(monkeypatch):
    """C2: pagamentos/cliente_nif eram gravados no CORPO da rota, ANTES de a
    reserva sequer ser tentada, e sem nenhuma condição — reproduzido aqui
    observando a ORDEM real das operações na base de dados: o registo dos
    pagamentos escolhidos pela operadora tem de vir DEPOIS da reserva (dela
    depender), nunca antes. Sem isto, uma tentativa que perca a corrida
    grava à mesma o que escolheu, mesmo sem ter sido ela a emitir — cenário
    da loja: Dinheiro grava primeiro, a operadora repete com Multibanco, sai
    UMA fatura (idempotência funciona) mas fica gravado o tipo errado, e o Z
    não explica a diferença na gaveta."""
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    ordem = []
    colecao_vendas = db[COLECOES["vendas"]]
    colecao_refs = db[COLECOES["refs_fiscais"]]
    update_original = colecao_vendas.update_one
    insert_original = colecao_refs.insert_one

    async def update_vendas_rastreado(filtro, atualizacao):
        if "pagamentos" in atualizacao.get("$set", {}):
            ordem.append("grava_pagamento")
        return await update_original(filtro, atualizacao)

    async def insert_refs_rastreado(doc):
        ordem.append("reserva")
        return await insert_original(doc)

    colecao_vendas.update_one = update_vendas_rastreado
    colecao_refs.insert_one = insert_refs_rastreado

    _corre(finalizar(
        "venda-1",
        PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
        operador=_operador(),
    ))

    assert "grava_pagamento" in ordem and "reserva" in ordem
    assert ordem.index("reserva") < ordem.index("grava_pagamento"), (
        "os pagamentos gravaram-se ANTES da reserva (ordem=%r) — uma "
        "tentativa que perca a corrida grava à mesma o que a operadora "
        "escolheu, mesmo sem ter sido esta a emitir" % ordem
    )


def test_duplo_toque_com_pagamentos_diferentes_so_o_vencedor_grava_o_seu(monkeypatch):
    """O mesmo cenário C2, ao nível do núcleo: duas tentativas CONCORRENTES
    da mesma venda, com escolhas de pagamento DIFERENTES (Dinheiro vs
    Multibanco) — só a que realmente ganhou a reserva (e por isso emitiu)
    pode gravar o seu `pagamentos`/`cliente_nif`; a que só esperou e
    reaproveitou o documento nunca pode sobrepor-se."""
    db = _db(vendas=[_venda()])
    chamadas_emitir = []

    async def emitir(ref):
        chamadas_emitir.append(ref)
        await asyncio.sleep(0)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não devia haver timeout neste teste")

    dinheiro = {"pagamentos": [{"tipo_pagamento_id": "tipo-dinheiro", "valor": 8.99}], "cliente_nif": None}
    multibanco = {"pagamentos": [{"tipo_pagamento_id": "tipo-mb", "valor": 8.99}], "cliente_nif": "123456789"}

    async def correr():
        return await asyncio.gather(
            finalizar_venda(
                db, _venda(), emitir, verificar, esperar=_instantaneo, dados_pagamento=dinheiro,
            ),
            finalizar_venda(
                db, _venda(), emitir, verificar, esperar=_instantaneo, dados_pagamento=multibanco,
            ),
        )

    _corre(correr())

    assert len(chamadas_emitir) == 1  # idempotência: continua a sair UMA só fatura
    venda_gravada = db[COLECOES["vendas"]]._documentos[0]
    # O que ficou gravado tem de ser de UMA das duas tentativas por inteiro
    # — nunca uma mistura (ex.: pagamentos de uma, cliente_nif de outra).
    assert (venda_gravada["pagamentos"], venda_gravada["cliente_nif"]) in [
        (dinheiro["pagamentos"], dinheiro["cliente_nif"]),
        (multibanco["pagamentos"], multibanco["cliente_nif"]),
    ]


def test_finalizar_venda_ja_emitida_e_recusado_409(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(estado="emitida", linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 409


def test_finalizar_com_sessao_de_caixa_fechada_e_recusado_409(monkeypatch):
    """I1: finalizar verificava o estado da VENDA mas nunca o da SESSÃO de
    caixa — uma venda aberta ANTES do fecho, mas só finalizada DEPOIS
    (ex.: a operadora esqueceu-se de fechar a conta, ou o ecrã ficou aberto
    numa mesa/balcão), emitia à mesma. O dinheiro entrava na gaveta sem
    pertencer a fecho nenhum, nem hoje nem amanhã (o Z de hoje já foi
    emitido, e o de amanhã só vai contar as vendas da PRÓXIMA sessão)."""
    _configura_vendus_env(monkeypatch)
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        tipos_pagamento=[_tipo_pagamento()],
        sessoes=[{"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "fechada"}],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 409
    assert ClienteEmissaoVendusFalso.instancias == []  # nunca chega a falar com o Vendus


def test_finalizar_com_sessao_de_caixa_inexistente_e_recusado_409(monkeypatch):
    """Caso extremo: a sessão referida pela venda nem sequer existe mais
    (dados corrompidos, ou uma migração) — trata-se exactamente como
    'fechada', nunca como 'aberta por omissão'."""
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()], sessoes=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 409


def test_finalizar_com_venda_sem_sessao_id_e_recusado_409_nao_500(monkeypatch):
    """Pequena correcção da re-revisão do núcleo fiscal:
    `_garante_sessao_da_venda_aberta` lia `venda["sessao_id"]` directamente
    — uma venda sem esse campo (dados corrompidos, uma migração incompleta)
    dava KeyError e um 500 em vez do 409 que já protege o caso 'a sessão
    referida não existe'. Trata-se da MESMA forma que uma sessão
    inexistente: recusa-se, nunca rebenta."""
    _configura_vendus_env(monkeypatch)
    venda_sem_sessao = _venda(linhas=[_linha()])
    del venda_sem_sessao["sessao_id"]
    db = _db(vendas=[venda_sem_sessao], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 409
    assert ClienteEmissaoVendusFalso.instancias == []  # nunca chega a falar com o Vendus


def test_finalizar_com_sessao_de_caixa_aberta_prossegue(monkeypatch):
    """Confirma que a guarda nova não bloqueia o caminho feliz — _db() já dá
    uma sessão aberta por omissão, mas este teste torna a intenção
    explícita."""
    _configura_vendus_env(monkeypatch)
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        tipos_pagamento=[_tipo_pagamento()],
        sessoes=[{"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "aberta"}],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    resultado = _corre(finalizar(
        "venda-1",
        PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
        operador=_operador(),
    ))
    assert resultado["estado"] == "emitida"


def test_finalizar_venda_de_outra_loja_e_recusado_404(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(loja_id="loja-2", linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 404


def test_finalizar_venda_sem_linhas_e_recusado_422(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=1.0)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422


def test_finalizar_com_desconto_global_maior_que_o_total_e_recusado_422(monkeypatch):
    """O segundo buraco fechado nesta tarefa também protege o desconto
    GLOBAL: um desconto maior do que a própria venda produziria um total
    negativo/zero — a rota recusa-o (422) ANTES de tocar em qualquer
    reserva ou no Vendus, nunca emite uma fatura com total ≤ 0."""
    _configura_vendus_env(monkeypatch)
    venda = _venda(linhas=[_linha()], desconto_global_eur=100.0)  # linha vale 8.99
    assert _totais(venda)["total"] < 0  # confirma a premissa do teste
    db = _db(vendas=[venda], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=0.01)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422


def test_finalizar_com_soma_de_pagamentos_diferente_do_total_e_recusado_422(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=5.0)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422
    assert "não bate" in excinfo.value.detail


def test_finalizar_com_tipo_de_pagamento_inexistente_e_recusado_422(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="nao-existe", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422


def test_finalizar_com_tipo_de_pagamento_inactivo_e_recusado_422(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento(ativo=False)])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422


def test_finalizar_com_tipo_de_pagamento_sem_vendus_id_e_recusado_422(monkeypatch):
    _configura_vendus_env(monkeypatch)
    tipo = _tipo_pagamento(vendus_payment_method_id=None)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[tipo])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 422


def test_finalizar_sem_conta_vendus_configurada_e_recusado_502(monkeypatch):
    monkeypatch.delenv("VENDUS_ACCOUNTS", raising=False)
    monkeypatch.setenv("FAT_NIF", "517542510")
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.setenv("VENDUS_MODE", "tests")
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 502


def test_finalizar_sem_register_id_configurado_e_recusado_502(monkeypatch):
    _configura_vendus_env(monkeypatch)
    monkeypatch.delenv("VENDUS_REGISTER_ID", raising=False)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 502


def test_finalizar_recusa_sem_indice_de_idempotencia_confirmado(monkeypatch):
    """I3: sem a confirmação explícita (por `arrancar()`) de que o índice
    único de `fat_refs_fiscais.ext_ref` existe mesmo, o POS recusa emitir —
    nunca serve 'às cegas' sem a defesa contra o duplo-toque. É a PRIMEIRA
    verificação da rota: nem chega a tocar na venda nem no Vendus."""
    db_mod.marcar_indice_idempotencia(False)
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 503
    assert ClienteEmissaoVendusFalso.instancias == []  # nunca chega a falar com o Vendus


def test_finalizar_com_vendus_indisponivel_devolve_502_e_nao_marca_emitida(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    ClienteEmissaoVendusFalso.instancias.clear()

    def fabrica(chave):
        cliente = ClienteEmissaoVendusFalso(chave)
        cliente.erro_criar = VendusIndisponivel("timeout simulado")
        cliente.resposta_procurar = None  # a verificação também não encontra nada
        return cliente

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", fabrica)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))
    assert excinfo.value.status_code == 502
    assert db[COLECOES["vendas"]]._documentos[0]["estado"] == "aberta"
    assert db[COLECOES["refs_fiscais"]]._documentos == []  # reserva libertada


# --- Validação do NIF e dos pagamentos (nível Pydantic) ------------------------


def test_nif_com_menos_de_9_digitos_e_recusado():
    with pytest.raises(ValidationError):
        PedidoFinalizarVenda(
            pagamentos=[PagamentoEntrada(tipo_pagamento_id="t1", valor=1.0)], nif="12345"
        )


def test_nif_none_e_aceite_consumidor_final():
    dados = PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="t1", valor=1.0)])
    assert dados.nif is None


def test_pagamentos_vazio_e_recusado():
    with pytest.raises(ValidationError):
        PedidoFinalizarVenda(pagamentos=[])


def test_pagamento_com_valor_zero_e_recusado():
    with pytest.raises(ValidationError):
        PagamentoEntrada(tipo_pagamento_id="t1", valor=0)


def test_pagamento_com_valor_negativo_e_recusado():
    with pytest.raises(ValidationError):
        PagamentoEntrada(tipo_pagamento_id="t1", valor=-5.0)


def test_pagamento_com_3_casas_decimais_e_recusado():
    with pytest.raises(ValidationError):
        PagamentoEntrada(tipo_pagamento_id="t1", valor=8.995)


# ============================================================================
# Verificação de leitura contra o Vendus (Task 4 do Plano 2B)
# ============================================================================


def _doc_vendus(**over):
    d = {
        "id": 900, "external_reference": "pos-loja-1-sessao-1-venda-1", "status": "N",
        "payments": [{"id": "316430468", "amount": 8.99}],
    }
    d.update(over)
    return d


# --- _reconciliar_vendas_dinheiro (núcleo puro) --------------------------------


def test_reconciliar_bate_certo_nao_diz_nada():
    resultado = _reconciliar_vendas_dinheiro(
        8.99, [_doc_vendus()], "pos-loja-1-sessao-1-", {"316430468"}
    )
    assert resultado is None


def test_reconciliar_nao_bate_avisa_com_os_dois_valores():
    resultado = _reconciliar_vendas_dinheiro(
        5.0, [_doc_vendus()], "pos-loja-1-sessao-1-", {"316430468"}
    )
    assert resultado is not None
    assert "8.99" in resultado["aviso"]
    assert "5.00" in resultado["aviso"]


def test_reconciliar_ignora_documento_de_outra_sessao():
    """Um documento com um prefixo diferente (outra sessão, ou da app
    L'Açaí) não pode contaminar a soma desta sessão."""
    doc_de_outra_sessao = _doc_vendus(external_reference="pos-loja-1-sessao-OUTRA-venda-9")
    resultado = _reconciliar_vendas_dinheiro(
        0.0, [doc_de_outra_sessao], "pos-loja-1-sessao-1-", {"316430468"}
    )
    assert resultado is None  # 0.0 local == 0.0 do Vendus (o documento foi ignorado)


def test_reconciliar_descarta_documento_anulado():
    doc_anulado = _doc_vendus(status="A")
    resultado = _reconciliar_vendas_dinheiro(
        0.0, [doc_anulado], "pos-loja-1-sessao-1-", {"316430468"}
    )
    assert resultado is None


def test_reconciliar_ignora_pagamento_que_nao_e_dinheiro():
    doc_multibanco = _doc_vendus(payments=[{"id": "999", "amount": 8.99}])
    resultado = _reconciliar_vendas_dinheiro(
        0.0, [doc_multibanco], "pos-loja-1-sessao-1-", {"316430468"}
    )
    assert resultado is None  # o pagamento existe mas não é do id 'dinheiro'


def test_reconciliar_soma_varios_documentos_da_sessao():
    docs = [_doc_vendus(id=1), _doc_vendus(id=2, payments=[{"id": "316430468", "amount": 2.5}])]
    resultado = _reconciliar_vendas_dinheiro(11.49, docs, "pos-loja-1-sessao-1-", {"316430468"})
    assert resultado is None


# --- _datas_da_janela -----------------------------------------------------------


def test_datas_da_janela_sessao_aberta_hoje_e_um_so_dia():
    from datetime import datetime, timezone
    hoje = datetime.now(timezone.utc).isoformat()
    datas = _datas_da_janela({"aberta_em": hoje})
    assert len(datas) == 1


def test_datas_da_janela_com_aberta_em_invalido_nao_rebenta():
    datas = _datas_da_janela({"aberta_em": "isto-nao-e-uma-data"})
    assert len(datas) == 1  # cai para hoje, não rebenta


def test_datas_da_janela_sem_aberta_em_nao_rebenta():
    assert len(_datas_da_janela({})) == 1


def test_datas_da_janela_cobre_do_inicio_ate_hoje_inclusive():
    from datetime import datetime, timedelta, timezone
    ha_tres_dias = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    datas = _datas_da_janela({"aberta_em": ha_tres_dias})
    assert len(datas) == 4  # 3 dias atrás + os 2 entre + hoje


# --- verificar_vendas_dinheiro_no_vendus (I/O) ---------------------------------


def test_verificar_sem_register_id_diz_nao_verificado(monkeypatch):
    monkeypatch.delenv("VENDUS_REGISTER_ID", raising=False)
    db = _db()
    resultado = _corre(verificar_vendas_dinheiro_no_vendus(db, _sessao_fake(), 8.99))
    assert "nao_verificado" in resultado


def test_verificar_sem_conta_configurada_diz_nao_verificado(monkeypatch):
    monkeypatch.setenv("VENDUS_REGISTER_ID", "7")
    monkeypatch.delenv("VENDUS_ACCOUNTS", raising=False)
    monkeypatch.setenv("FAT_NIF", "517542510")
    db = _db()
    resultado = _corre(verificar_vendas_dinheiro_no_vendus(db, _sessao_fake(), 8.99))
    assert "nao_verificado" in resultado


def _fabrica_com_um_documento_hoje(**over):
    """Duplo de ClienteEmissaoVendus para a verificação de leitura: devolve
    UM documento (o da venda de hoje), e SÓ na data pedida — nunca em
    qualquer data, ao contrário do que este duplo fazia antes.

    Causa raiz do teste instável (`test_verificar_feliz_bate_certo_nao_diz_nada`):
    `_sessao_fake()["aberta_em"]` está fixo em "2026-08-15", mas
    `_datas_da_janela` (propositadamente — ver o comentário em fiscal.py)
    percorre TODOS os dias entre a abertura da sessão e HOJE. O duplo antigo
    ignorava por completo o parâmetro `data` e devolvia sempre o mesmo
    documento de 8,99€ — por isso o "total do Vendus" calculado crescia
    8,99€ por cada dia que passasse desde 15/08, sem nenhuma venda nova
    nenhures: 1 dia (no próprio 15/08) somava 8,99€ e o teste passava; 4 dias
    depois (18/08, quando isto foi apanhado) já somava 4×8,99=35,96€ e o
    teste falhava. Não havia estado a vazar de OUTRO teste — o duplo em si é
    que não respeitava o contrato da API real (um documento só aparece na
    consulta do dia em que foi emitido), e o "estado partilhado" aparente
    era só o relógio do sistema a avançar entre corridas.

    A correcção não é repor um duplo entre testes (não há nada para repor:
    cada teste já cria a sua própria instância) — é fazer o duplo responder
    por dia, como o Vendus real, para o resultado deixar de depender de que
    dia é hoje."""

    from datetime import datetime

    def fabrica(chave):
        cliente = ClienteEmissaoVendusFalso(chave)
        hoje = datetime.now(fiscal_mod._LISBOA).date().isoformat()
        cliente.listar_documentos_por_dia = (
            lambda data, register_id: [_doc_vendus(**over)] if data == hoje else []
        )
        return cliente

    return fabrica


def test_verificar_feliz_bate_certo_nao_diz_nada(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", _fabrica_com_um_documento_hoje())

    resultado = _corre(verificar_vendas_dinheiro_no_vendus(db, _sessao_fake(), 8.99))
    assert resultado is None


def test_verificar_feliz_nao_bate_avisa(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(tipos_pagamento=[_tipo_pagamento()])

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", _fabrica_com_um_documento_hoje())

    resultado = _corre(verificar_vendas_dinheiro_no_vendus(db, _sessao_fake(), 20.0))
    assert resultado is not None
    assert "aviso" in resultado


def test_verificar_com_leitura_a_rebentar_diz_nao_verificado(monkeypatch):
    """Nunca deixa a excepção propagar — mesmo se listar_documentos_por_dia
    (que já pagina até esgotar ou levanta um erro tipado, nunca devolve uma
    lista truncada em silêncio) rebentar."""
    _configura_vendus_env(monkeypatch)
    db = _db(tipos_pagamento=[_tipo_pagamento()])

    def fabrica(chave):
        cliente = ClienteEmissaoVendusFalso(chave)

        def rebenta(data, register_id):
            raise VendusIndisponivel("falha de leitura simulada")
        cliente.listar_documentos_por_dia = rebenta
        return cliente

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", fabrica)

    resultado = _corre(verificar_vendas_dinheiro_no_vendus(db, _sessao_fake(), 8.99))
    assert "nao_verificado" in resultado


def _sessao_fake(**over):
    s = {
        "id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "aberta_em": "2026-08-15T09:00:00+00:00", "estado": "aberta",
    }
    s.update(over)
    return s



# ============================================================================
# A corrida CANCELAR/EMITIR: a releitura depois de GANHAR a reserva
# ============================================================================
#
# A verificação da reserva no `venda.py::cancelar_venda` estreitou esta
# corrida mas não a fechou: entre o `_garante_aberta` da rota `finalizar` e o
# `_reservar` corre a validação toda (sessão da venda, um find_one por cada
# tipo de pagamento, conta e register_id) — tudo `await`s. Um cancelamento
# que caia INTEIRA nessa janela passa as DUAS perguntas pela reserva (ainda
# não existe nenhuma), responde 200 "cancelada", e a seguir o $set
# incondicional do `_gravar_documento` escreve `emitida` por cima: a
# operadora ouviu "conta cancelada", saiu uma FS real com ATCUD, ela pica
# tudo outra vez e o cliente leva DUAS faturas.

from datetime import datetime, timedelta, timezone  # noqa: E402

from faturacao import venda as venda_mod  # noqa: E402
from faturacao.fiscal import (  # noqa: E402
    PedidoLibertarReserva,
    VendaJaNaoAberta,
    _gravar_documento,
    libertar_reserva_presa,
    listar_reservas_incertas,
    listar_reservas_presas,
)
from faturacao.venda import cancelar_venda  # noqa: E402


def _refs_de(db):
    return db._coleccoes[COLECOES["refs_fiscais"]]._documentos


def _vendas_de(db):
    return db._coleccoes[COLECOES["vendas"]]._documentos


def test_venda_cancelada_na_janela_de_validacao_nao_emite_e_liberta_a_reserva():
    """O núcleo do defeito: quem chama `finalizar_venda` traz um retrato da
    venda de ANTES da validação (`estado: aberta`), mas na base de dados ela
    já está `cancelada`. Ganhar a reserva não dá o direito de emitir — a
    releitura tem de a apanhar."""
    db = _db(vendas=[_venda(
        linhas=[_linha()], estado="cancelada",
        cancelada_em="2026-08-15T09:07:00+00:00",
        cancelada_por={"id": "op-ana", "nome": "Ana"},
    )])
    emitiu = []

    async def emitir(ref):
        emitiu.append(ref)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não devia sequer verificar")

    with pytest.raises(VendaJaNaoAberta):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo
        ))

    assert emitiu == [], "saiu uma Fatura Simplificada real de uma conta cancelada"
    assert _refs_de(db) == [], (
        "a reserva ficou para trás — a conta fica trancada para sempre, sem "
        "se poder cancelar nem finalizar"
    )
    assert _vendas_de(db)[0]["estado"] == "cancelada", "o cancelamento foi pisado"


def test_venda_desaparecida_depois_de_reservar_tambem_aborta_sem_emitir():
    """Dados estragados (a venda já não existe): o mesmo caminho, nunca um
    500 nem uma emissão às cegas contra um retrato antigo."""
    db = _db(vendas=[])
    emitiu = []

    async def emitir(ref):
        emitiu.append(ref)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não devia sequer verificar")

    with pytest.raises(VendaJaNaoAberta):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo
        ))
    assert emitiu == []
    assert _refs_de(db) == []


def test_venda_ainda_aberta_depois_de_reservar_emite_normalmente():
    """A outra metade da prova: a releitura só trava quem tem de ser travado.
    Uma guarda que abortasse sempre passava o teste de cima e partia o balcão
    inteiro — este é o teste que fica vermelho nesse caso."""
    db = _db(vendas=[_venda(linhas=[_linha()])])
    emitiu = []

    async def emitir(ref):
        emitiu.append(ref)
        return _bruto()

    async def verificar(ref):
        return None

    documento = _corre(finalizar_venda(
        db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo
    ))
    assert emitiu == ["pos-loja-1-sessao-1-venda-1"]
    assert documento["atcud"] == "ATCUD-1"
    assert _vendas_de(db)[0]["estado"] == "emitida"


class TiposComCancelamentoAMeio(ColeccaoFalsa):
    """A janela real, na rota real: a colecção dos tipos de pagamento — que a
    rota `finalizar` consulta DEPOIS de ver a venda aberta e ANTES de
    reservar — corre o cancelamento no meio da validação. É o guião de
    reprodução (`repro_corrida_cancelar.py`) reduzido a uma ordem
    determinística, sem duas tarefas a correr à sorte."""

    def __init__(self, documentos, cancelar):
        super().__init__(documentos)
        self._cancelar = cancelar

    async def find_one(self, filtro, projecao=None):
        if self._cancelar is not None:
            cancelar, self._cancelar = self._cancelar, None
            await cancelar()
        return await super().find_one(filtro, projecao)


def test_cancelar_dentro_da_janela_de_validacao_nao_deixa_sair_fatura(monkeypatch):
    """O cenário inteiro, ponta a ponta e com o `cancelar_venda` REAL: a Ana
    carrega em Cancelar enquanto o FINALIZAR da Rafaela ainda está a validar
    os tipos de pagamento. O cancelamento é honesto (200, a conta fica mesmo
    cancelada) e a emissão aborta sem tocar no Vendus — nunca as duas
    coisas ao mesmo tempo, que era o estrago: 'cancelada' à operadora e uma
    FS real com ATCUD à Autoridade Tributária."""
    _configura_vendus_env(monkeypatch)
    cancelamentos = []

    async def cancelar():
        resposta = await cancelar_venda(
            "venda-1", operador=_operador(operador_id="op-ana", nome="Ana")
        )
        cancelamentos.append(resposta["estado"])

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(
            None, indices_unicos=["vendus_document_id", "atcud"]
        ),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(None, indices_unicos=["ext_ref"]),
        COLECOES["tipos_pagamento"]: TiposComCancelamentoAMeio([_tipo_pagamento()], cancelar),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([
            {"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "aberta"}
        ]),
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(
                pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]
            ),
            operador=_operador(),
        ))

    assert cancelamentos == ["cancelada"], "o cancelamento não chegou a acontecer"
    assert excinfo.value.status_code == 409
    assert "cancelada" in excinfo.value.detail
    assert "não saiu" in excinfo.value.detail.lower()
    cliente = ClienteEmissaoVendusFalso.instancias[0]
    assert cliente.chamadas_criar == [], (
        "saiu uma Fatura Simplificada real depois de a operadora ouvir "
        "'conta cancelada'"
    )
    assert _vendas_de(db)[0]["estado"] == "cancelada"
    assert _refs_de(db) == [], "a reserva abortada ficou a trancar a conta"


# ============================================================================
# A marca do documento na reserva (é ela que torna a listagem de gestão
# possível sem varrer ~365 mil documentos por ano)
# ============================================================================


def test_gravar_documento_marca_a_reserva_com_o_documento_e_so_depois_da_venda():
    """Duas coisas na mesma prova: a marca fica lá, e fica DEPOIS de a venda
    já estar `emitida`. A ordem não é cosmética — pela ordem contrária, um
    processo morto entre as duas escritas deixava uma reserva marcada como
    resolvida a esconder uma venda presa em `aberta` com um documento fiscal
    REAL."""
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1",
               "venda_id": "venda-1", "criado_em": "2026-08-15T09:06:00+00:00"}],
    )
    ordem = []
    colecao_vendas = db[COLECOES["vendas"]]
    colecao_refs = db[COLECOES["refs_fiscais"]]
    update_vendas = colecao_vendas.update_one
    update_refs = colecao_refs.update_one

    async def vendas_rastreado(filtro, atualizacao):
        if atualizacao.get("$set", {}).get("estado") == "emitida":
            ordem.append("venda_emitida")
        return await update_vendas(filtro, atualizacao)

    async def refs_rastreado(filtro, atualizacao):
        if "documento_id" in atualizacao.get("$set", {}):
            ordem.append("reserva_marcada")
        return await update_refs(filtro, atualizacao)

    colecao_vendas.update_one = vendas_rastreado
    colecao_refs.update_one = refs_rastreado

    documento = _corre(_gravar_documento(
        db, "pos-loja-1-sessao-1-venda-1", _venda(linhas=[_linha()]), _bruto(),
        reserva_id="r1",
    ))

    assert _refs_de(db)[0]["documento_id"] == documento["id"]
    assert ordem == ["venda_emitida", "reserva_marcada"], (
        "a reserva foi marcada antes de a venda ficar emitida (ordem=%r)" % ordem
    )


def test_falhar_a_marcar_a_reserva_nao_estraga_uma_emissao_que_correu_bem():
    """A marca é uma conveniência para uma listagem de gestão, nunca uma
    garantia fiscal: um soluço do Mongo nessa escrita não pode transformar
    uma emissão bem sucedida (documento gravado, venda emitida) num 500 no
    ecrã do balcão — que mandava a operadora repetir uma fatura que já
    saiu."""

    class RefsQueRebentamAoMarcar(ColeccaoFalsa):
        async def update_one(self, filtro, atualizacao):
            if "documento_id" in atualizacao.get("$set", {}):
                raise RuntimeError("Mongo com soluços")
            return await super().update_one(filtro, atualizacao)

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(
            None, indices_unicos=["vendus_document_id", "atcud"]
        ),
        COLECOES["refs_fiscais"]: RefsQueRebentamAoMarcar(
            [{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1",
              "venda_id": "venda-1", "criado_em": "2026-08-15T09:06:00+00:00"}],
            indices_unicos=["ext_ref"],
        ),
    })

    documento = _corre(_gravar_documento(
        db, "pos-loja-1-sessao-1-venda-1", _venda(linhas=[_linha()]), _bruto(),
        reserva_id="r1",
    ))
    assert documento["atcud"] == "ATCUD-1"
    assert _vendas_de(db)[0]["estado"] == "emitida"


# ============================================================================
# Rota de gestão: TODAS as reservas presas (não só as marcadas `incerta`)
# ============================================================================
#
# Nem toda a reserva sobrevivente é `incerta`: o processo pode morrer entre o
# `_reservar` e o `_gravar_documento` (restart, deploy, OOM), e o caminho
# `ConflitoDocumentoFiscal` mantém a reserva DE PROPÓSITO. Em nenhum desses
# casos alguém chega ao `_marcar_reserva_incerta` — e com o cancelamento
# fechado (409) a conta ficava sem saída nenhuma, invisível para a gestão,
# numa sexta à noite.


def _agora_iso(segundos_atras=0):
    return (
        datetime.now(timezone.utc) - timedelta(seconds=segundos_atras)
    ).isoformat()


def _reserva_presa(**over):
    r = {
        "id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
        "criado_em": _agora_iso(3600),
    }
    r.update(over)
    return r


def test_lista_mostra_a_reserva_orfa_que_ninguem_via(monkeypatch):
    """O caso que não tinha saída NEM visibilidade: sem `incerta`, sem
    `em_retoma`, e antiga."""
    db = _db(vendas=[_venda(id="venda-1", loja_id="loja-1", linhas=[_linha()])],
             refs=[_reserva_presa()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resultado = _corre(listar_reservas_presas(_={}))
    assert len(resultado) == 1
    assert resultado[0]["ext_ref"] == "pos-loja-1-sessao-1-venda-1"
    assert resultado[0]["motivo"] == "orfa"
    assert resultado[0]["loja_id"] == "loja-1"
    assert resultado[0]["estado_da_venda"] == "aberta"
    assert resultado[0]["total_da_venda"] == 8.99
    assert resultado[0]["presa_ha_segundos"] > 3500


def test_lista_distingue_incerta_de_em_retoma_de_orfa_de_emissao_a_decorrer(monkeypatch):
    """Cada uma diz PORQUE está presa — sem isso o gestor não sabe qual pode
    tocar. E uma reserva recente sem marca nenhuma é uma emissão a DECORRER,
    não uma órfã: sem essa distinção, a lista aberta a meio do serviço
    convidava a libertar a reserva de uma fatura a nascer."""
    db = _db(
        vendas=[_venda(id="venda-%d" % n, linhas=[_linha()]) for n in (1, 2, 3, 4)],
        refs=[
            _reserva_presa(id="r1", venda_id="venda-1", ext_ref="ref-1"),
            _reserva_presa(id="r2", venda_id="venda-2", ext_ref="ref-2", incerta=True),
            _reserva_presa(id="r3", venda_id="venda-3", ext_ref="ref-3",
                           incerta=True, em_retoma=True),
            _reserva_presa(id="r4", venda_id="venda-4", ext_ref="ref-4",
                           criado_em=_agora_iso(2)),
        ],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    por_ref = {r["ext_ref"]: r for r in _corre(listar_reservas_presas(_={}))}
    assert por_ref["ref-1"]["motivo"] == "orfa"
    assert por_ref["ref-2"]["motivo"] == "incerta"
    assert por_ref["ref-3"]["motivo"] == "em_retoma"
    assert por_ref["ref-4"]["motivo"] == "em_emissao"
    # E em português, que quem lê isto é o gestor da loja.
    assert "Vendus" in por_ref["ref-2"]["descricao"]


def test_lista_nao_mostra_a_reserva_de_uma_venda_ja_emitida(monkeypatch):
    """A reserva de uma venda emitida fica lá PARA SEMPRE de propósito — é
    ela que sustenta a idempotência. Mostrá-la como "presa" enchia a lista de
    ruído e convidava a libertar exactamente a que nunca se pode libertar.

    Aqui sem `documento_id` de propósito: é o caso das reservas anteriores a
    esse campo existir (e daquelas em que a marca falhou), que o filtro
    barato deixa passar e a junção com a venda tem de descartar."""
    db = _db(
        vendas=[_venda(id="venda-1", estado="emitida", documento_id="doc-1")],
        refs=[_reserva_presa()],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    assert _corre(listar_reservas_presas(_={})) == []


def test_lista_ignora_as_reservas_ja_ligadas_a_um_documento(monkeypatch):
    """O filtro barato (`documento_id: None`) é o que evita ler a colecção
    inteira — ~365 mil reservas ao fim de um ano, das quais um `.to_list()`
    devolvia as MAIS ANTIGAS (todas resolvidas) e nunca a presa desta
    noite."""
    db = _db(
        vendas=[_venda(id="venda-1", estado="emitida", documento_id="doc-1")],
        refs=[_reserva_presa(documento_id="doc-1")],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    assert _corre(listar_reservas_presas(_={})) == []


def test_lista_com_venda_inexistente_nao_rebenta(monkeypatch):
    """Defesa (dados estragados, ou uma reserva de uma venda apagada à mão):
    a rota não pode rebentar — é a única visibilidade que existe."""
    db = _db(vendas=[], refs=[_reserva_presa()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_presas(_={}))
    assert resultado[0]["loja_id"] is None
    assert resultado[0]["estado_da_venda"] is None
    assert resultado[0]["total_da_venda"] is None


def test_lista_com_venda_de_linhas_impossiveis_mostra_a_reserva_na_mesma(monkeypatch):
    """Uma venda com uma linha que já não se consegue valorizar (o produto
    ficou sem preço) não pode fazer desaparecer a listagem inteira com um
    422 — é justamente a venda que mais precisa de ser vista. O total vem a
    None; a reserva aparece à mesma."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha(produto_preco=None)])],
        refs=[_reserva_presa()],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_presas(_={}))
    assert len(resultado) == 1
    assert resultado[0]["total_da_venda"] is None


def test_lista_encontra_a_reserva_presa_entre_milhares_de_resolvidas(monkeypatch):
    """O filtro `{"documento_id": None}` não é uma optimização — é o que faz
    esta listagem estar CERTA. A colecção nunca encolhe (a reserva de uma
    venda emitida fica lá para sempre a sustentar a idempotência: ~365 mil
    documentos ao fim de um ano), e uma leitura sem filtro devolve as
    primeiras N pela ordem natural — as MAIS ANTIGAS, todas resolvidas. A
    reserva presa desta noite, a que tem o balcão parado, era a última da
    fila e não aparecia a ninguém."""
    resolvidas = [
        {"id": "r-%d" % n, "ext_ref": "ref-%d" % n, "venda_id": "venda-%d" % n,
         "criado_em": _agora_iso(86400), "documento_id": "doc-%d" % n}
        for n in range(fiscal_mod._LIMITE_RESERVAS_PRESAS + 50)
    ]
    presa = _reserva_presa(id="r-presa", ext_ref="ref-presa", venda_id="venda-presa")
    db = _db(
        vendas=[_venda(id="venda-presa", linhas=[_linha()])],
        refs=resolvidas + [presa],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resultado = _corre(listar_reservas_presas(_={}))
    assert [r["ext_ref"] for r in resultado] == ["ref-presa"]


def test_lista_vazia_quando_nao_ha_nenhuma(monkeypatch):
    db = _db(vendas=[], refs=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    assert _corre(listar_reservas_presas(_={})) == []


def test_o_nome_antigo_da_listagem_continua_a_funcionar():
    """`/fiscal/reservas-incertas` já anda escrito em mensagens de erro e na
    documentação do ecrã de finalizar — o caminho novo acrescenta-se, o
    antigo não se parte."""
    from faturacao import router as router_do_modulo

    caminhos = {getattr(r, "path", None) for r in router_do_modulo.routes}
    assert "/api/faturacao/fiscal/reservas-presas" in caminhos
    assert "/api/faturacao/fiscal/reservas-incertas" in caminhos
    assert listar_reservas_incertas is listar_reservas_presas


# ============================================================================
# Rota de gestão: LIBERTAR uma reserva presa (a saída que não existia)
# ============================================================================


def _confirmado():
    return PedidoLibertarReserva(confirmado_no_vendus=True, nota="conferido no Vendus")


def test_libertar_destranca_a_conta_e_diz_o_que_o_gestor_confirmou(monkeypatch):
    db = _db(vendas=[_venda(id="venda-1", linhas=[_linha()])], refs=[_reserva_presa()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa(
        "venda-1", _confirmado(), gestor={"email": "dono@lacai.pt", "role": "admin"}
    ))

    assert resposta["libertada"] is True
    assert resposta["motivo"] == "orfa"
    assert _refs_de(db) == [], "a reserva não foi libertada — a conta continua trancada"
    # A venda NÃO se toca: é ficar `aberta` que devolve o balcão ao serviço.
    assert _vendas_de(db)[0]["estado"] == "aberta"
    # E a resposta diz, com todas as letras, o que ele acabou de declarar.
    assert "SEGUNDA Fatura Simplificada" in resposta["o_que_confirmou"]
    assert "pos-loja-1-sessao-1-venda-1" in resposta["o_que_confirmou"]


def test_libertar_sem_confirmar_no_vendus_e_recusado(monkeypatch):
    """Um clique distraído não pode libertar uma reserva fiscal: a
    confirmação é explícita, e a recusa diz exactamente o que há para ir
    ver primeiro."""
    db = _db(vendas=[_venda(id="venda-1", linhas=[_linha()])], refs=[_reserva_presa()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa(
            "venda-1", PedidoLibertarReserva(), gestor={"email": "dono@lacai.pt"}
        ))
    assert excinfo.value.status_code == 422
    assert "pos-loja-1-sessao-1-venda-1" in excinfo.value.detail
    assert "nota de crédito" in excinfo.value.detail
    assert _refs_de(db) != []


def test_libertar_reserva_com_documento_gravado_e_recusado(monkeypatch):
    """A recusa que existe para o caso em que a confirmação humana está
    ERRADA: libertar a reserva de uma fatura que SAIU é autorizar uma
    segunda emissão da mesma venda."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        documentos=[{"id": "doc-1", "ext_ref": "pos-loja-1-sessao-1-venda-1",
                     "venda_id": "venda-1", "numero": "FS 2026/1", "atcud": "ATCUD-1"}],
        refs=[_reserva_presa()],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert excinfo.value.status_code == 409
    assert "ATCUD-1" in excinfo.value.detail
    assert "nota de crédito" in excinfo.value.detail
    assert _refs_de(db) != [], "a reserva de uma fatura real foi apagada"


def test_libertar_reserva_de_venda_ja_emitida_e_recusado(monkeypatch):
    """Cinto e suspensórios: mesmo sem o documento em `fat_documentos` (a
    gravação da venda e a do documento são escritas diferentes), uma venda
    marcada `emitida` chega para recusar."""
    db = _db(
        vendas=[_venda(id="venda-1", estado="emitida", documento_id="doc-1")],
        refs=[_reserva_presa()],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert excinfo.value.status_code == 409
    assert _refs_de(db) != []


def test_libertar_reserva_recente_e_recusado_porque_pode_estar_a_emitir(monkeypatch):
    """A reserva com 2 segundos é quase de certeza uma emissão a decorrer
    AGORA (o POS ainda está à espera do Vendus) — e nenhum gestor consegue
    ter confirmado o Vendus nessa janela. Libertá-la é autorizar uma segunda
    fatura da mesma venda."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_presa(criado_em=_agora_iso(2))],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert excinfo.value.status_code == 409
    assert "emissão a decorrer" in excinfo.value.detail
    assert _refs_de(db) != []


def test_libertar_reserva_sem_criado_em_legivel_e_permitido(monkeypatch):
    """Uma emissão a decorrer tem SEMPRE um `criado_em` legível (escrito pelo
    próprio `_reservar`). Uma reserva sem ele é, por construção, dados
    estragados de há muito — exactamente o que esta rota existe para
    desentalar, e não pode ficar de fora por não se conseguir medir a
    idade."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_presa(criado_em="ontem à noite")],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert resposta["libertada"] is True
    assert resposta["presa_ha_segundos"] is None
    assert _refs_de(db) == []


def test_libertar_reserva_sem_ext_ref_e_recusado(monkeypatch):
    """Uma reserva estragada (sem `ext_ref`) não se liberta por aqui: a
    libertação apaga POR `ext_ref`, e um `delete_one({"ext_ref": None})`
    casava com qualquer OUTRA reserva estragada — libertava a reserva de
    outra venda, que é o estrago que esta rota existe para não cometer."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[
            {"id": "r1", "venda_id": "venda-1", "criado_em": _agora_iso(3600)},
            {"id": "r2", "venda_id": "venda-2", "criado_em": _agora_iso(3600)},
        ],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert excinfo.value.status_code == 409
    assert len(_refs_de(db)) == 2, "apagou reservas pela ausência de ext_ref"


def test_libertar_sem_reserva_nenhuma_e_404(monkeypatch):
    db = _db(vendas=[_venda(id="venda-1", linhas=[_linha()])], refs=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert excinfo.value.status_code == 404


def test_libertar_so_apaga_a_reserva_desta_venda(monkeypatch):
    """A conta do lado não pode ser destrancada por engano — é pelo
    `venda_id` que se procura, e é a `ext_ref` dessa reserva que se apaga."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()]), _venda(id="venda-2", linhas=[_linha()])],
        refs=[
            _reserva_presa(),
            _reserva_presa(id="r2", venda_id="venda-2", ext_ref="pos-loja-1-sessao-1-venda-2"),
        ],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert [r["venda_id"] for r in _refs_de(db)] == ["venda-2"]


def test_a_conta_destrancada_volta_a_poder_ser_cancelada(monkeypatch):
    """A prova de que isto serve mesmo para o que foi feito: antes de
    libertar, o balcão está preso (409 no cancelar); depois, a operadora
    consegue deitar a conta fora e voltar ao serviço."""
    db = _db(vendas=[_venda(id="venda-1", linhas=[_linha()])], refs=[_reserva_presa()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as antes:
        _corre(cancelar_venda("venda-1", operador=_operador()))
    assert antes.value.status_code == 409

    _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert _corre(cancelar_venda("venda-1", operador=_operador()))["estado"] == "cancelada"


# ============================================================================
# O RELÓGIO DA RETOMA — e a libertação que apagava a reserva de uma emissão
# que estava a falar com o Vendus naquele instante
# ============================================================================
#
# Reproduzido em processo, sobre as rotas reais: reserva `incerta` das 20h; à
# meia-noite a operadora carrega em FINALIZAR — isso é uma RETOMA, que reclama
# a reserva, não encontra documento na verificação, e começa a emitir de
# verdade (até ~150 s a falar com o Vendus). Nesse intervalo o gestor abre a
# listagem, procura a ext_ref no Vendus, não vê documento nenhum (é verdade —
# ainda vai a caminho) e liberta com confirmado_no_vendus=true. A rota
# aceitava, porque a guarda dos 300 s media o `criado_em` da reserva ORIGINAL
# (4 horas), e não a idade da RECLAMAÇÃO da retoma. Saíam duas Faturas
# Simplificadas reais da mesma venda: `FS 2026/901` e `FS 2026/902`.

from faturacao.fiscal import (  # noqa: E402
    PedidoReconciliarReserva,
    SessaoJaNaoAberta,
    _limpar_incerta_resolvida,
    _reclamar_retoma,
    _retoma_em_curso,
    _retomar_reserva_incerta,
    reconciliar_reserva_presa,
)


def _reserva_incerta_antiga(**over):
    """A reserva do cenário: `incerta` desde as 20h (4 horas), que é
    precisamente o que fazia a guarda da idade deixar passar."""
    r = {
        "id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
        "criado_em": _agora_iso(14400), "incerta": True,
    }
    r.update(over)
    return r


def test_reclamar_retoma_carimba_o_relogio_da_propria_reclamacao():
    """O carimbo que faltava. Sem `em_retoma_desde`, a única data da reserva
    é a da RESERVA — e essa, numa incerta de há horas, responde "4 horas" a
    quem pergunta "há quanto tempo é que isto está a emitir?"."""
    db = _db(vendas=[_venda()], refs=[_reserva_incerta_antiga()])
    assert _corre(_reclamar_retoma(db, "pos-loja-1-sessao-1-venda-1")) is True

    reserva = _refs_de(db)[0]
    assert reserva["em_retoma"] is True
    agora = datetime.now(timezone.utc)
    # O relógio da reclamação é de AGORA, não o das 20h da reserva.
    assert fiscal_mod._segundos_desde(reserva["em_retoma_desde"], agora) < 5
    assert fiscal_mod._segundos_desde(reserva["criado_em"], agora) > 14000
    assert _retoma_em_curso(reserva, agora) is True


def test_retoma_resolvida_limpa_o_relogio_junto_com_a_marca():
    """Uma reserva sem `em_retoma` mas com o relógio de uma retoma antiga é
    um dado que só pode enganar quem o leia a seguir.

    O `carimbo` passa-se às duas: é ele que liga a limpeza à reclamação que
    esta chamada fez, e não "à marca de retoma que houver nesta ext_ref" —
    ver `_limpar_incerta_resolvida` e o teste da reserva substituída."""
    db = _db(vendas=[_venda()], refs=[_reserva_incerta_antiga()])
    carimbo = fiscal_mod._agora()
    _corre(_reclamar_retoma(db, "pos-loja-1-sessao-1-venda-1", carimbo))
    _corre(_limpar_incerta_resolvida(db, "pos-loja-1-sessao-1-venda-1", carimbo))

    reserva = _refs_de(db)[0]
    assert reserva["em_retoma"] is None
    assert reserva["em_retoma_desde"] is None
    assert reserva["incerta"] is False
    assert _retoma_em_curso(reserva, datetime.now(timezone.utc)) is False


def test_retoma_que_falha_outra_vez_repoe_incerta_e_limpa_o_relogio():
    """O outro desfecho: continua incerta (novo timeout e nova falha da
    verificação), mas a RECLAMAÇÃO acaba — e o relógio dela também, senão a
    tentativa seguinte via uma retoma "a decorrer" que já não existe."""
    db = _db(vendas=[_venda(linhas=[_linha()])], refs=[_reserva_incerta_antiga()])

    async def emitir(ref):
        raise AssertionError("não devia chegar a emitir")

    async def verificar(ref):
        raise VendusIndisponivel("o GET de verificação voltou a falhar")

    with pytest.raises(fiscal_mod.VerificacaoFiscalIncerta):
        _corre(_retomar_reserva_incerta(
            db, "pos-loja-1-sessao-1-venda-1", _venda(linhas=[_linha()]),
            emitir, verificar, esperar=_instantaneo,
        ))

    reserva = _refs_de(db)[0]
    assert reserva["incerta"] is True
    assert reserva["em_retoma"] is None
    assert reserva["em_retoma_desde"] is None


def test_libertar_reserva_em_retoma_a_decorrer_e_recusado(monkeypatch):
    """O BLOQUEADOR. A reserva tem 4 horas (a guarda da idade deixa passar),
    mas a retoma foi reclamada há 12 segundos: pode estar a falar com o
    Vendus neste instante, e não haver documento lá AGORA não prova nada."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_incerta_antiga(em_retoma=True, em_retoma_desde=_agora_iso(12))],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "retoma" in excinfo.value.detail.lower()
    assert "SEGUNDA Fatura Simplificada" in excinfo.value.detail
    assert _refs_de(db) != [], "apagou a reserva de uma emissão em voo"


def test_libertar_reserva_com_retoma_abandonada_ha_muito_e_permitido(monkeypatch):
    """O critério de saída: uma retoma VIVA nunca dura mais do que
    `_SEGUNDOS_DE_RETOMA_NORMAL` (o pior caso das três chamadas ao Vendus
    que ela faz), e uma que termine limpa SEMPRE a marca. Logo, uma
    reclamação mais velha do que isso só pode ser de um processo que morreu
    a meio — e essa não pode trancar a conta para sempre."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_incerta_antiga(
            em_retoma=True,
            em_retoma_desde=_agora_iso(fiscal_mod._SEGUNDOS_DE_RETOMA_NORMAL + 60),
        )],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert resposta["libertada"] is True
    assert _refs_de(db) == []


def test_libertar_reserva_em_retoma_sem_relogio_legivel_e_permitido(monkeypatch):
    """A marca legada (anterior a este carimbo existir) conta como
    abandonada, não como viva: qualquer retoma reclamada por este código
    carimba sempre `em_retoma_desde`, e um restart não deixa retomas em voo.
    Tratá-la como viva trancava para sempre a única saída destas contas."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_incerta_antiga(em_retoma=True)],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert resposta["libertada"] is True
    assert _refs_de(db) == []


def test_libertar_durante_a_retoma_nao_deixa_sair_a_segunda_fatura(monkeypatch):
    """O cenário inteiro, ponta a ponta, com as três rotas reais: a retoma a
    emitir (pendurada no Vendus, como uma chamada HTTP fica), o gestor a
    tentar libertar no meio, e a operadora a carregar outra vez em FINALIZAR
    logo a seguir.

    Sem a pergunta que faltava, isto media-se assim: `emissões REAIS -> 2`,
    duas Faturas Simplificadas com ATCUDs diferentes, o cliente com o talão
    de uma e a venda a apontar para a outra, e a listagem de emergência a
    devolver `[]` — a duplicação não aparecia em lado nenhum depois de
    acontecer."""
    _configura_vendus_env(monkeypatch)
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_incerta_antiga()],
        tipos_pagamento=[_tipo_pagamento()],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    a_emitir = asyncio.Event()
    largar_o_vendus = asyncio.Event()
    emissoes_da_retoma = []

    async def emitir_lento(ref):
        emissoes_da_retoma.append(ref)
        a_emitir.set()
        await largar_o_vendus.wait()
        return _bruto(id=901, atcud="ATCUD-RETOMA", numero="FS 2026/901")

    async def verificar_vazio(ref):
        return None

    async def cenario():
        retoma = asyncio.ensure_future(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir_lento, verificar_vazio,
            esperar=_instantaneo,
        ))
        await a_emitir.wait()  # a retoma está mesmo a falar com o Vendus

        with pytest.raises(HTTPException) as libertacao:
            await libertar_reserva_presa(
                "venda-1", _confirmado(), gestor={"email": "dono@lacai.pt"}
            )

        # E mesmo que a operadora carregue outra vez em FINALIZAR: a reserva
        # continua lá, por isso esta tentativa nunca chega ao Vendus.
        with pytest.raises(HTTPException) as segunda:
            await finalizar(
                "venda-1",
                PedidoFinalizarVenda(pagamentos=[
                    PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
                operador=_operador(),
            )

        largar_o_vendus.set()
        documento = await retoma
        return libertacao.value, segunda.value, documento

    erro_libertar, erro_segunda, documento = _corre(cenario())

    assert erro_libertar.status_code == 409
    assert erro_segunda.status_code == 409
    assert len(emissoes_da_retoma) == 1
    emissoes_pelo_balcao = sum(
        len(c.chamadas_criar) for c in ClienteEmissaoVendusFalso.instancias
    )
    assert emissoes_pelo_balcao == 0, "saiu uma SEGUNDA Fatura Simplificada real"
    documentos = db._coleccoes[COLECOES["documentos"]]._documentos
    assert [d["atcud"] for d in documentos] == ["ATCUD-RETOMA"]
    assert documento["numero"] == "FS 2026/901"
    assert _vendas_de(db)[0]["documento_id"] == documentos[0]["id"]


def test_lista_distingue_a_retoma_a_decorrer_da_reclamacao_abandonada(monkeypatch):
    """As duas metades do `em_retoma` são opostas — numa não se toca em nada,
    na outra é preciso mesmo alguém tratar dela — e a listagem dava-as como
    uma só ("está a decorrer agora OU o processo morreu a meio")."""
    db = _db(
        vendas=[_venda(id="venda-%d" % n, linhas=[_linha()]) for n in (1, 2)],
        refs=[
            _reserva_incerta_antiga(
                id="r1", venda_id="venda-1", ext_ref="ref-viva",
                em_retoma=True, em_retoma_desde=_agora_iso(10),
            ),
            _reserva_incerta_antiga(
                id="r2", venda_id="venda-2", ext_ref="ref-morta",
                em_retoma=True,
                em_retoma_desde=_agora_iso(fiscal_mod._SEGUNDOS_DE_RETOMA_NORMAL + 600),
            ),
        ],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    por_ref = {r["ext_ref"]: r for r in _corre(listar_reservas_presas(_={}))}
    assert por_ref["ref-viva"]["motivo"] == "em_retoma"
    assert por_ref["ref-morta"]["motivo"] == "em_retoma"
    assert "NESTE MOMENTO" in por_ref["ref-viva"]["descricao"]
    assert "não é para mexer" in por_ref["ref-viva"]["descricao"].lower()
    assert "morreu a meio" in por_ref["ref-morta"]["descricao"]
    assert por_ref["ref-viva"]["retoma_reclamada_ha_segundos"] < 30
    assert por_ref["ref-morta"]["retoma_reclamada_ha_segundos"] > 900


# ============================================================================
# A releitura depois da reserva confirma a VENDA **e a SESSÃO**
# ============================================================================
#
# A rota `finalizar` faz duas perguntas sobre o mesmo retrato velho —
# `_garante_aberta` (a venda) e `_garante_sessao_da_venda_aberta` (a sessão, o
# defeito I1: "o dinheiro entrava na gaveta sem pertencer a fecho nenhum") — e
# durante uma ronda inteira só a primeira era refeita depois de ganhar a
# reserva. Medido, com dois PCs na mesma caixa: `FECHAR CAIXA -> 200; Z:
# vendas_dinheiro=0.00 esperado=50.00 contado=58.99 diferenca=+8.99` e a
# seguir `FINALIZAR -> 200 estado='emitida' ... sessão da venda: 'fechada'`.


def _sessao_aberta_doc(**over):
    s = {
        "id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1",
        "estado": "aberta", "fundo": 50.0,
        "aberta_por": {"id": "op-1", "nome": "Rafaela"},
        "aberta_em": "2026-08-18T08:00:00+00:00",
    }
    s.update(over)
    return s


def test_sessao_fechada_depois_de_reservar_aborta_sem_emitir_e_liberta_a_reserva():
    """O núcleo: quem chama traz um retrato de quando a sessão ainda estava
    aberta; na base de dados ela já está `fechada`. Ganhar a reserva não dá o
    direito de emitir para um turno fechado."""
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        sessoes=[_sessao_aberta_doc(estado="fechada")],
    )

    async def emitir(ref):
        raise AssertionError("emitiu para uma sessão de caixa já fechada")

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    with pytest.raises(SessaoJaNaoAberta):
        _corre(finalizar_venda(db, _venda(linhas=[_linha()]), emitir, verificar,
                               esperar=_instantaneo))

    assert _refs_de(db) == [], "a reserva abortada ficou a trancar a conta"
    assert _vendas_de(db)[0]["estado"] == "aberta"


def test_venda_sem_sessao_depois_de_reservar_tambem_aborta_sem_emitir():
    """Dados estragados (uma venda sem `sessao_id`) caem no MESMO aborto —
    nunca num KeyError/500 a meio de uma emissão fiscal."""
    db = _db(vendas=[_venda(linhas=[_linha()], sessao_id=None)], sessoes=[])

    async def emitir(ref):
        raise AssertionError("emitiu sem sessão de caixa nenhuma")

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    with pytest.raises(SessaoJaNaoAberta):
        _corre(finalizar_venda(db, _venda(linhas=[_linha()], sessao_id=None),
                               emitir, verificar, esperar=_instantaneo))
    assert _refs_de(db) == []


def test_sessao_ainda_aberta_depois_de_reservar_emite_normalmente():
    """O contrapeso: a releitura da sessão não pode travar o caminho normal
    (senão o balcão parava e ninguém saberia porquê)."""
    db = _db(vendas=[_venda(linhas=[_linha()])], sessoes=[_sessao_aberta_doc()])

    async def emitir(ref):
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    documento = _corre(finalizar_venda(db, _venda(linhas=[_linha()]), emitir,
                                       verificar, esperar=_instantaneo))
    assert documento["numero"] == "FS 2026/1"
    assert _vendas_de(db)[0]["estado"] == "emitida"


class TiposComFechoDeCaixaAMeio(ColeccaoFalsa):
    """A janela real, na rota real, com o `fechar_caixa` VERDADEIRO: a
    colecção dos tipos de pagamento — consultada DEPOIS de
    `_garante_sessao_da_venda_aberta` e ANTES do `_reservar` — corre o fecho
    da caixa no meio da validação. É o guião
    `repro_fecho_de_caixa_na_janela.py` reduzido a uma ordem
    determinística."""

    def __init__(self, documentos, fechar):
        super().__init__(documentos)
        self._fechar = fechar

    async def find_one(self, filtro, projecao=None):
        if self._fechar is not None:
            fechar, self._fechar = self._fechar, None
            await fechar()
        return await super().find_one(filtro, projecao)


def test_fechar_a_caixa_dentro_da_janela_de_validacao_nao_deixa_sair_fatura(monkeypatch):
    """O cenário dos dois PCs, ponta a ponta e com as duas rotas reais: a Ana
    fecha a caixa (200 — nesse instante ainda não existe reserva nenhuma, por
    isso o fecho é honesto) enquanto o FINALIZAR da Rafaela valida os tipos de
    pagamento. A emissão tem de abortar SEM tocar no Vendus: o Z já saiu, e
    uma FS emitida depois dele não entra em Z nenhum."""
    from faturacao import caixa as caixa_mod
    from faturacao.caixa import PedidoFecharCaixa, fechar_caixa

    _configura_vendus_env(monkeypatch)
    fechos = []

    async def fechar():
        z = await fechar_caixa(
            PedidoFecharCaixa(caixa_id="caixa-1", contado=58.99),
            operador=_operador(operador_id="op-ana", nome="Ana"),
        )
        fechos.append(z)

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(
            None, indices_unicos=["vendus_document_id", "atcud"]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(None, indices_unicos=["ext_ref"]),
        COLECOES["tipos_pagamento"]: TiposComFechoDeCaixaAMeio([_tipo_pagamento()], fechar),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([_sessao_aberta_doc()]),
        COLECOES["caixas"]: ColeccaoFalsa([{"id": "caixa-1", "loja_id": "loja-1"}]),
        COLECOES["movimentos_caixa"]: ColeccaoFalsa([]),
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(caixa_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    async def _sem_vendus(_db, _sessao, _valor):
        return {"nao_verificado": "desligado no teste"}
    monkeypatch.setattr(caixa_mod, "_verificar_vendas_dinheiro", _sem_vendus)

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[
                PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert fechos and fechos[0]["vendas_dinheiro"] == 0.0, "o fecho não chegou a acontecer"
    assert excinfo.value.status_code == 409
    assert "caixa" in excinfo.value.detail.lower()
    assert "não saiu" in excinfo.value.detail.lower()
    cliente = ClienteEmissaoVendusFalso.instancias[0]
    assert cliente.chamadas_criar == [], (
        "saiu uma Fatura Simplificada real DEPOIS do Z, para uma sessão fechada"
    )
    assert _vendas_de(db)[0]["estado"] == "aberta"
    assert _refs_de(db) == [], "a reserva abortada ficou a trancar a conta"


# ============================================================================
# B2 — quem espera pelo vencedor tem de descrever o estado do MOMENTO
# ============================================================================


def _espera_com_vencedor_que_desiste(db, venda_para_o_nucleo):
    """Quem perde a reserva fica à espera do documento; a "outra tentativa"
    aborta e liberta a reserva no meio dessa espera."""

    async def emitir(ref):
        raise AssertionError("perdeu a corrida — não devia tentar emitir")

    async def verificar(ref):
        raise AssertionError("perdeu a corrida — não é um timeout")

    async def o_vencedor_aborta():
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await db[COLECOES["refs_fiscais"]].delete_one(
            {"ext_ref": "pos-loja-1-sessao-1-venda-1"})

    async def correr():
        return await asyncio.gather(
            finalizar_venda(db, venda_para_o_nucleo, emitir, verificar,
                            esperar=_instantaneo),
            o_vencedor_aborta(),
        )

    return correr()


def test_quem_espera_pelo_vencedor_que_abortou_por_cancelamento_nao_manda_tentar_outra_vez():
    """B2: o vencedor abortou porque a venda foi CANCELADA (libertando a
    reserva sem emitir), e quem estava à espera do documento dele esgotava o
    orçamento e respondia "tente novamente dentro de momentos" — sobre uma
    conta já cancelada e sem reserva nenhuma. Um conselho impossível de
    seguir."""
    db = _db(
        vendas=[_venda(linhas=[_linha()], estado="cancelada")],
        refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1"}],
    )

    with pytest.raises(VendaJaNaoAberta) as excinfo:
        _corre(_espera_com_vencedor_que_desiste(db, _venda(linhas=[_linha()])))
    assert "cancelada" in str(excinfo.value)


def test_quem_espera_pelo_vencedor_que_falhou_sem_emitir_manda_carregar_outra_vez():
    """A outra metade: o vencedor libertou a reserva por a emissão ter
    falhado (4xx, dados inválidos) e a conta continua ABERTA — aí sim,
    carregar outra vez em FINALIZAR é exactamente o que há a fazer, e a
    mensagem di-lo em vez de mandar "esperar momentos" por um documento que
    ninguém vai escrever."""
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1"}],
    )

    with pytest.raises(EmissaoEmCurso) as excinfo:
        _corre(_espera_com_vencedor_que_desiste(db, _venda(linhas=[_linha()])))
    detalhe = str(excinfo.value)
    assert "NÃO saiu nenhuma Fatura" in detalhe
    assert "FINALIZAR" in detalhe


class DocumentosQueNascemNaPrimeiraPergunta(ColeccaoFalsa):
    """O vencedor grava o documento e a reserva desaparece EXACTAMENTE entre
    as duas leituras de quem está à espera — a única ordem que distingue as
    duas versões do código.

    O gancho corre depois de ESTA colecção responder pela primeira vez, e é
    isso que o torna um oráculo: com a reserva lida PRIMEIRO (a versão certa)
    esta iteração ainda vê o documento na leitura seguinte; com o documento
    lido primeiro (a versão trocada), a leitura da reserva vem depois do
    gancho, dá `None`, e conclui-se "ninguém emitiu" sobre uma Fatura
    Simplificada REAL que acabou de ser gravada."""

    def __init__(self, documentos, refs, documento_a_nascer):
        super().__init__(documentos, indices_unicos=["vendus_document_id", "atcud"])
        self._refs = refs
        self._documento_a_nascer = documento_a_nascer

    async def find_one(self, filtro, projecao=None):
        encontrado = await super().find_one(filtro, projecao)
        if self._documento_a_nascer is not None and "ext_ref" in (filtro or {}):
            self._documentos.append(self._documento_a_nascer)
            self._documento_a_nascer = None
            del self._refs._documentos[:]
        return encontrado


def test_a_espera_devolve_o_documento_que_nasce_entre_as_suas_duas_leituras():
    """A ordem das duas leituras (reserva primeiro, documento a seguir) não é
    indiferente: se o documento aparecer entre elas, quem espera tem de o
    devolver — nunca concluir "ninguém emitiu" sobre uma fatura real."""
    documento_real = {
        "id": "doc-1", "vendus_document_id": 501, "atcud": "ATCUD-1",
        "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
        "numero": "FS 2026/1", "total": 8.99,
    }
    refs = ColeccaoFalsa(
        [{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1"}],
        indices_unicos=["ext_ref"],
    )
    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: DocumentosQueNascemNaPrimeiraPergunta(
            None, refs, documento_real),
        COLECOES["refs_fiscais"]: refs,
        COLECOES["tipos_pagamento"]: ColeccaoFalsa(None),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([_sessao_aberta_doc()]),
    })

    async def emitir(ref):
        raise AssertionError("perdeu a corrida — não devia tentar emitir")

    async def verificar(ref):
        raise AssertionError("perdeu a corrida — não é um timeout")

    documento = _corre(finalizar_venda(
        db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo,
        tentativas_espera=3,
    ))
    assert documento["numero"] == "FS 2026/1"


class RefsComVencedorQueLiberta(ColeccaoFalsa):
    """A reserva do vencedor desaparece DENTRO da espera de quem perdeu: a
    primeira leitura ainda a encontra (a emissão parecia viva), a seguinte já
    não (o vencedor abortou e libertou-a). Ordem determinística, sem duas
    tarefas a correr à sorte."""

    def __init__(self, documentos, ao_libertar=None):
        super().__init__(documentos, indices_unicos=["ext_ref"])
        self._leituras_da_espera = 0
        self._ao_libertar = ao_libertar

    async def find_one(self, filtro, projecao=None):
        encontrado = await super().find_one(filtro, projecao)
        if "ext_ref" in (filtro or {}) and encontrado is not None:
            self._leituras_da_espera += 1
            if self._leituras_da_espera == 1:
                del self._documentos[:]
                if self._ao_libertar is not None:
                    self._ao_libertar()
        return encontrado


def test_a_rota_traduz_a_espera_falhada_por_cancelamento_num_409_que_nao_manda_repetir(monkeypatch):
    """O mesmo, visto do balcão: 409 a dizer que a conta foi cancelada e que
    NÃO saiu fatura nenhuma — nunca um "tente novamente" sobre uma conta que
    já não existe, com a operadora a carregar no mesmo botão."""
    _configura_vendus_env(monkeypatch)
    vendas = [_venda(linhas=[_linha()])]

    def cancela_a_venda():
        vendas[0]["estado"] = "cancelada"

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(vendas),
        COLECOES["documentos"]: ColeccaoFalsa(
            None, indices_unicos=["vendus_document_id", "atcud"]),
        COLECOES["refs_fiscais"]: RefsComVencedorQueLiberta(
            [{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1",
              "venda_id": "venda-1"}],
            ao_libertar=cancela_a_venda,
        ),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa([_tipo_pagamento()]),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([_sessao_aberta_doc()]),
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[
                PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert excinfo.value.status_code == 409
    assert "cancelada" in excinfo.value.detail
    assert "novamente" not in excinfo.value.detail
    assert "não saiu" in excinfo.value.detail.lower()
    assert ClienteEmissaoVendusFalso.instancias[0].chamadas_criar == []


# ============================================================================
# Rota de gestão: RECONCILIAR — trazer para o sistema a fatura que o Vendus
# já tem (a saída que faltava, e a única que salva o dinheiro)
# ============================================================================
#
# A retoma só existe através da rota `finalizar`, que começa por
# `_garante_sessao_da_venda_aberta`: com a caixa fechada dá 409 antes de
# chegar à reserva. A reserva presa de ontem à noite, vista na manhã seguinte
# (medido: `presa_ha_segundos=85731.2`), não tinha saída nenhuma — e se a FS
# chegou mesmo a sair, o documento nunca entrava em `fat_documentos`: a venda
# ficava `aberta` para sempre ou era cancelada, e a receita real desaparecia
# do Z e do dashboard sem nada que o assinalasse.


def _db_reconciliacao(sessao_estado="fechada", refs=None, documentos=None, venda=None):
    return _db(
        vendas=[venda if venda is not None else _venda(id="venda-1", linhas=[_linha()])],
        documentos=documentos,
        refs=refs if refs is not None else [_reserva_incerta_antiga()],
        sessoes=[_sessao_aberta_doc(estado=sessao_estado, fechada_em="2026-08-18T23:10:00+00:00")],
    )


def _vendus_que_tem(monkeypatch, bruto):
    """O Vendus com um documento para a referência externa desta venda — o
    que a verificação por `external_reference` vai encontrar."""
    _configura_vendus_env(monkeypatch)

    class ClienteComDocumento(ClienteEmissaoVendusFalso):
        def __init__(self, chave):
            super().__init__(chave)
            self.resposta_procurar = bruto

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteComDocumento)
    ClienteEmissaoVendusFalso.instancias.clear()


def test_reconciliar_traz_a_fatura_do_vendus_com_a_caixa_ja_fechada(monkeypatch):
    """O caso que não tinha saída nenhuma: a caixa está FECHADA, e é de
    propósito que isto funciona à mesma — não se está a emitir nada, está a
    registar-se um facto que já aconteceu do lado da AT."""
    db = _db_reconciliacao(sessao_estado="fechada")
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(id=777, atcud="ATCUD-REAL", numero="FS 2026/77"))

    resposta = _corre(reconciliar_reserva_presa(
        "venda-1", PedidoReconciliarReserva(nota="vi no Vendus"),
        gestor={"email": "dono@lacai.pt"},
    ))

    assert resposta["reconciliada"] is True
    assert resposta["veio_do_vendus_agora"] is True
    assert resposta["documento"]["numero"] == "FS 2026/77"
    assert resposta["documento"]["atcud"] == "ATCUD-REAL"
    # A venda passa a `emitida` e LIGADA ao documento — é isto que devolve a
    # receita ao Z do dia e ao dashboard.
    venda = _vendas_de(db)[0]
    documento = db._coleccoes[COLECOES["documentos"]]._documentos[0]
    assert venda["estado"] == "emitida"
    assert venda["documento_id"] == documento["id"]
    assert documento["vendus_document_id"] == 777
    # E não se emitiu NADA: só se leu.
    cliente = ClienteEmissaoVendusFalso.instancias[0]
    assert cliente.chamadas_criar == []
    assert cliente.chamadas_procurar == ["pos-loja-1-sessao-1-venda-1"]


def test_reconciliar_avisa_que_o_z_daquele_turno_fica_por_acertar(monkeypatch):
    """O Z de uma sessão já fechada não se reescreve por trás de quem o
    assinou — e não se finge que ficou tudo bem: diz-se ao gestor o que tem
    de acertar nesse turno.

    Sem os `pagamentos` gravados (a reserva ficou presa ANTES de a emissão
    os registar) não se sabe quanto foi em dinheiro — e não se inventa: o
    aviso diz o total da fatura e manda ver o documento."""
    db = _db_reconciliacao(sessao_estado="fechada")
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["z_por_acertar"] is True
    assert resposta["sessao_estado"] == "fechada"
    # O valor vem do DOCUMENTO (o que a AT tem), não dos totais da venda.
    assert "8.99 €" in resposta["aviso_do_z"]
    assert "sessao-1" in resposta["aviso_do_z"]
    # Sem repartição gravada não se anuncia nenhum valor "em dinheiro" — nem
    # sequer 0,00 €, que se leria como "não entrou dinheiro nenhum".
    assert resposta["dinheiro_por_acertar"] is None
    assert resposta["outros_meios"] is None
    assert "NÃO tem gravado como foi paga" in resposta["aviso_do_z"]


def test_reconciliar_com_a_caixa_ainda_aberta_nao_inventa_aviso_nenhum(monkeypatch):
    """Com a sessão aberta o Z ainda não saiu — esta venda entra nele
    normalmente, e um aviso a mandar acertar contas seria ruído perigoso."""
    db = _db_reconciliacao(sessao_estado="aberta")
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))
    assert resposta["z_por_acertar"] is False
    assert resposta["aviso_do_z"] is None


def test_reconciliar_sem_documento_no_vendus_nao_escreve_nada(monkeypatch):
    """Não há nada para trazer: a conta fica exactamente como estava, e a
    mensagem manda usar a rota certa (Libertar) em vez desta."""
    db = _db_reconciliacao()
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, None)

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "pos-loja-1-sessao-1-venda-1" in excinfo.value.detail
    assert "Libertar" in excinfo.value.detail
    assert db._coleccoes[COLECOES["documentos"]]._documentos == []
    assert _vendas_de(db)[0]["estado"] == "aberta"


def test_reconciliar_com_o_vendus_indisponivel_nao_conclui_que_nao_existe(monkeypatch):
    """A mesma regra de `VerificacaoFiscalIncerta`: de uma leitura que falhou
    não se conclui NADA — muito menos "não existe documento nenhum"."""
    db = _db_reconciliacao()
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _configura_vendus_env(monkeypatch)

    class ClienteQueRebenta(ClienteEmissaoVendusFalso):
        def procurar_por_referencia_externa(self, external_reference, register_id):
            raise VendusIndisponivel("timeout na leitura")

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteQueRebenta)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert excinfo.value.status_code == 502
    assert _vendas_de(db)[0]["estado"] == "aberta"
    assert _refs_de(db) != []


def test_reconciliar_nao_deixa_o_gestor_escrever_o_numero_nem_o_atcud():
    """O campo perigoso não se valida — não se declara (mesmo padrão do
    `sessao_id` em `caixa.PedidoMovimento`). Um número de documento fiscal
    escrito à mão é um número inventado à espera de acontecer: um dígito
    trocado liga esta venda à fatura de outro cliente."""
    pedido = PedidoReconciliarReserva(
        nota="conferido", numero="FS 2026/999", atcud="ATCUD-INVENTADO", total=1.0
    )
    assert pedido.model_dump() == {"nota": "conferido"}
    assert not hasattr(pedido, "numero")
    assert not hasattr(pedido, "atcud")


def test_reconciliar_repetido_nao_volta_a_perguntar_ao_vendus(monkeypatch):
    """Idempotente: o segundo pedido responde o mesmo, sem uma segunda
    leitura ao Vendus e sem escrever nada de novo."""
    db = _db_reconciliacao()
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    primeira = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))
    segunda = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert primeira["veio_do_vendus_agora"] is True
    assert segunda["veio_do_vendus_agora"] is False
    assert segunda["documento"]["atcud"] == primeira["documento"]["atcud"]
    assert len(db._coleccoes[COLECOES["documentos"]]._documentos) == 1
    leituras = sum(len(c.chamadas_procurar) for c in ClienteEmissaoVendusFalso.instancias)
    assert leituras == 1


def test_reconciliar_religa_a_venda_que_ficou_para_tras_com_o_documento_gravado(monkeypatch):
    """O processo morreu entre as duas escritas de `_gravar_documento`: o
    documento fiscal está gravado e a venda ficou em `aberta`. Isto
    resolve-se sem incomodar o Vendus — a fatura já está cá dentro."""
    documento = {
        "id": "doc-1", "vendus_document_id": 501, "atcud": "ATCUD-1",
        "numero": "FS 2026/1", "total": 8.99, "ext_ref": "pos-loja-1-sessao-1-venda-1",
        "venda_id": "venda-1", "loja_id": "loja-1",
    }
    db = _db_reconciliacao(documentos=[documento])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, None)  # se perguntasse, não encontrava nada

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["veio_do_vendus_agora"] is False
    assert _vendas_de(db)[0]["estado"] == "emitida"
    assert _vendas_de(db)[0]["documento_id"] == "doc-1"
    assert ClienteEmissaoVendusFalso.instancias == []


def test_a_religacao_carimba_a_reserva_que_esta_rota_leu_com_o_documento(monkeypatch):
    """A outra metade da religação, e a que não tinha rede nenhuma: a reserva
    fica marcada com o documento que a resolveu.

    O carimbo é o que torna POSSÍVEL perguntar pelas reservas PRESAS sem
    varrer a colecção inteira — `listar_reservas_presas` faz a primeira
    triagem por `{"documento_id": None}` antes sequer de olhar para a venda.
    E é o campo que um gestor lê, semanas depois, para perceber que documento
    saiu de que tentativa. Sem o `reserva.id` a viajar daqui até
    `_ligar_venda_ao_documento`, o filtro `{"ext_ref": ..., "id": None}` não
    casa com nada e o carimbo vira um no-op silencioso: a reserva
    reconciliada fica para sempre por marcar.

    O que este teste NÃO afirma, de propósito: que a reserva sai (ou entra) na
    listagem por causa disto. Medido, com e sem o carimbo, a listagem responde
    o mesmo — vazia — porque a MESMA operação põe a venda `emitida` e a junção
    descarta as emitidas. Quem defende a listagem é o estado da venda; o que
    o carimbo defende é a triagem e o que o gestor lê."""
    documento = {
        "id": "doc-1", "vendus_document_id": 501, "atcud": "ATCUD-1",
        "numero": "FS 2026/1", "total": 8.99, "ext_ref": "pos-loja-1-sessao-1-venda-1",
        "venda_id": "venda-1", "loja_id": "loja-1",
    }
    db = _db_reconciliacao(documentos=[documento])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, None)  # se perguntasse, não encontrava nada

    _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    reserva = _refs_de(db)[0]
    assert reserva["id"] == "r1", "é a reserva que a rota leu à entrada"
    assert reserva.get("documento_id") == "doc-1", (
        "a reserva reconciliada tem de ficar carimbada com o documento que a "
        "resolveu — sem isso não há triagem de presas nem rasto para o gestor"
    )


def test_reconciliar_durante_uma_retoma_a_decorrer_e_recusado(monkeypatch):
    """A mesma pergunta de `libertar`: o POS pode estar a emitir esta venda
    neste instante, e essa emissão grava o documento sozinha."""
    db = _db_reconciliacao(refs=[
        _reserva_incerta_antiga(em_retoma=True, em_retoma_desde=_agora_iso(5))
    ])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "retoma" in excinfo.value.detail.lower()
    assert ClienteEmissaoVendusFalso.instancias == []
    assert _vendas_de(db)[0]["estado"] == "aberta"


def test_reconciliar_limpa_a_marca_incerta_e_tira_a_reserva_da_listagem(monkeypatch):
    """Resolvida é resolvida: a reserva fica (é ela que impede uma segunda
    emissão), mas deixa de aparecer como presa."""
    db = _db_reconciliacao()
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    assert len(_corre(listar_reservas_presas(_={}))) == 1
    _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    reserva = _refs_de(db)[0]
    assert reserva["incerta"] is False
    assert reserva["documento_id"] is not None
    assert _corre(listar_reservas_presas(_={})) == []


def test_reconciliar_sem_reserva_nenhuma_usa_a_referencia_deterministica(monkeypatch):
    """O caso que a mensagem de `libertar` manda tratar como fatura já
    emitida: a reserva foi libertada e só depois é que apareceu o documento
    no Vendus. A referência é a mesma de sempre — `ext_ref_determinista`,
    nunca uma segunda fórmula."""
    db = _db_reconciliacao(refs=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["ext_ref"] == ext_ref_determinista("loja-1", "sessao-1", "venda-1")
    assert _vendas_de(db)[0]["estado"] == "emitida"
    assert ClienteEmissaoVendusFalso.instancias[0].chamadas_procurar == [resposta["ext_ref"]]


def test_reconciliar_venda_inexistente_e_404(monkeypatch):
    db = _db(vendas=[], refs=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-fantasma", None, gestor={"email": "x"}))
    assert excinfo.value.status_code == 404


def test_reconciliar_venda_sem_loja_ou_sessao_e_409_e_nao_500(monkeypatch):
    """Dados estragados não se reconciliam às cegas — e muito menos rebentam
    com um KeyError a meio de uma escrita fiscal."""
    db = _db(vendas=[_venda(id="venda-1", linhas=[_linha()], sessao_id=None)], refs=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))
    assert excinfo.value.status_code == 409


# ============================================================================
# A mensagem de LIBERTAR (e a listagem) deixam de prometer o que não existe
# ============================================================================


def test_libertar_com_a_caixa_fechada_nao_promete_finalizar(monkeypatch):
    """A rota dizia sempre "a conta voltou a poder ser alterada, cancelada ou
    finalizada no POS" — e das três, `finalizar` é FALSA com a caixa fechada,
    que é justamente o caso mais comum (a reserva presa de ontem à noite,
    vista na manhã seguinte)."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_presa()],
        sessoes=[_sessao_aberta_doc(estado="fechada")],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert resposta["sessao_estado"] == "fechada"
    assert "NÃO pode ser finalizada" in resposta["a_seguir"]
    assert "Reconciliar" in resposta["a_seguir"]


def test_libertar_com_a_caixa_aberta_continua_a_dizer_que_pode_finalizar(monkeypatch):
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()])],
        refs=[_reserva_presa()],
        sessoes=[_sessao_aberta_doc()],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))
    assert resposta["sessao_estado"] == "aberta"
    assert "finalizada no POS" in resposta["a_seguir"]


def test_lista_diz_que_finalizar_nao_e_saida_com_a_caixa_fechada(monkeypatch):
    """O gestor decide a partir desta lista: ela tem de dizer qual é o estado
    da caixa desta venda, porque é isso que muda as saídas possíveis."""
    db = _db(
        vendas=[_venda(id="venda-1", linhas=[_linha()]),
                _venda(id="venda-2", linhas=[_linha()], sessao_id="sessao-2")],
        refs=[_reserva_presa(),
              _reserva_presa(id="r2", venda_id="venda-2", ext_ref="ref-2")],
        sessoes=[_sessao_aberta_doc(estado="fechada"),
                 _sessao_aberta_doc(id="sessao-2", estado="aberta")],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    por_venda = {r["venda_id"]: r for r in _corre(listar_reservas_presas(_={}))}
    assert por_venda["venda-1"]["sessao_estado"] == "fechada"
    assert "FINALIZAR no POS já não é uma saída" in por_venda["venda-1"]["saidas"]
    assert "Reconciliar" in por_venda["venda-1"]["saidas"]
    assert por_venda["venda-2"]["sessao_estado"] == "aberta"
    assert "ainda está aberta" in por_venda["venda-2"]["saidas"]


def test_a_rota_de_reconciliar_existe_e_e_de_gestao():
    """A saída nova tem de estar mesmo montada no router (e do lado da
    GESTÃO, nunca do POS: o `gestor_atual` está provado em
    test_protecao_rotas.py, que varre todas as rotas do módulo)."""
    from faturacao import router as router_do_modulo

    caminhos = {
        getattr(r, "path", None) for r in router_do_modulo.routes
        if "POST" in (getattr(r, "methods", None) or set())
    }
    assert "/api/faturacao/fiscal/reservas/{venda_id}/reconciliar" in caminhos
    assert "/api/faturacao/fiscal/reservas/{venda_id}/libertar" in caminhos


def test_reconciliar_uma_venda_que_tinha_sido_cancelada_repoe_a_receita(monkeypatch):
    """O caso mais feio de todos, e o que esta rota existe para desfazer: a
    conta foi cancelada ao balcão (a reserva presa tinha sido libertada) e a
    Fatura Simplificada existe mesmo no Vendus. Uma venda `cancelada` com um
    documento fiscal real do outro lado é receita entregue à AT que não
    aparece no Z nem no dashboard — reconciliar põe a venda `emitida`, que é
    o estado VERDADEIRO dela.

    É a mesma decisão que a docstring de `_gravar_documento` defende para o
    `$set` incondicional: com o documento fiscal em mãos, `emitida` é a
    verdade, escreva o que escrever quem lá tenha passado."""
    db = _db_reconciliacao(
        refs=[],
        venda=_venda(id="venda-1", linhas=[_linha()], estado="cancelada",
                     cancelada_em="2026-08-18T23:59:00+00:00",
                     cancelada_por={"id": "op-1", "nome": "Rafaela"}),
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(numero="FS 2026/77", atcud="ATCUD-REAL"))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["documento"]["numero"] == "FS 2026/77"
    venda = _vendas_de(db)[0]
    assert venda["estado"] == "emitida"
    assert venda["documento_id"] is not None
    # Os carimbos do cancelamento ficam à VISTA (`_venda_publica` mostra-os):
    # não se apaga o rasto de quem cancelou, corrige-se o estado.
    assert venda["cancelada_por"] == {"id": "op-1", "nome": "Rafaela"}


# ============================================================================
# A CONTA que muda debaixo da emissão: recusar, nunca recompor
# ============================================================================
#
# A rota `finalizar` monta `itens = _itens_vendus(venda)` a partir do retrato
# que leu no princípio — antes da validação, antes do `_reservar` — e a função
# `emitir` fecha sobre esses itens. Nessa janela a venda ainda está `aberta` e
# ainda não tem reserva: `juntar_linha` (e as outras três rotas de escrita)
# passam o `_garante_sem_emissao` E a escrita condicional a
# `{"estado": "aberta"}`. A linha entra na conta e NÃO entra na fatura.
#
# A correcção NÃO é recompor os itens com as linhas novas: a soma dos
# pagamentos foi validada contra os `_totais` do retrato velho, por isso
# emitir a conta nova produzia uma FS real cujo total não é o dinheiro que
# entrou na gaveta. Recusa-se, liberta-se a reserva, e a operadora confirma a
# conta nova e finaliza outra vez. Guião: `verif_E_conta_muda_debaixo_da_
# emissao.py` (as rotas reais, a alteração injectada na janela).

from faturacao.fiscal import ContaAlteradaDepoisDeConfirmada  # noqa: E402
from faturacao.venda import (  # noqa: E402
    PedidoJuntarLinha,
    juntar_linha,
)


def _nunca_emite(ref):
    raise AssertionError(
        "saiu uma Fatura Simplificada REAL de uma conta que já não é a que a "
        "operadora confirmou"
    )


def _recusa_a_conta_mudada(db, retrato):
    """Corre o núcleo com um retrato que já não bate com a base de dados e
    devolve a excepção — as três asserções que interessam (não emitiu, a
    reserva não ficou a trancar a conta, a conta não foi tocada) ficam em cada
    teste, porque são elas que descrevem o estrago."""

    async def emitir(ref):
        _nunca_emite(ref)

    async def verificar(ref):
        raise AssertionError("não devia sequer verificar — nada foi ao Vendus")

    with pytest.raises(ContaAlteradaDepoisDeConfirmada) as excinfo:
        _corre(finalizar_venda(db, retrato, emitir, verificar, esperar=_instantaneo))
    return excinfo.value


def test_linha_acrescentada_na_janela_nao_emite_e_liberta_a_reserva():
    """O cenário do defeito: a Rafaela carrega em FINALIZAR com um açaí de
    8,99 € no ecrã e recebe 8,99 €; a Ana pica um segundo açaí no outro PC
    dentro da janela de validação. Emitir os itens do retrato dava uma FS real
    de 8,99 € numa conta de 17,98 € — o segundo açaí saía porta fora sem
    fatura nenhuma."""
    db = _db(vendas=[_venda(linhas=[_linha(), _linha(id="linha-2")])])

    _recusa_a_conta_mudada(db, _venda(linhas=[_linha()]))

    assert _refs_de(db) == [], (
        "a reserva ficou para trás — a conta fica trancada, e é justamente "
        "nela que a operadora tem de voltar a carregar em FINALIZAR"
    )
    venda = _vendas_de(db)[0]
    assert venda["estado"] == "aberta", "a conta tem de ficar utilizável"
    assert len(venda["linhas"]) == 2, "a linha nova foi pisada"


def test_desconto_global_alterado_na_janela_nao_emite_e_liberta_a_reserva():
    """O mesmo pela outra metade da conta: o desconto global entra na janela.
    A fatura sairia sem ele (8,99 € entregues à AT) numa conta que passou a
    valer 3,99 € — e a operadora, que ia devolver 5 €, ficava com um talão
    que diz outra coisa."""
    db = _db(vendas=[_venda(linhas=[_linha()], desconto_global_eur=5.0)])

    _recusa_a_conta_mudada(db, _venda(linhas=[_linha()]))

    assert _refs_de(db) == []
    assert _vendas_de(db)[0]["desconto_global_eur"] == 5.0


def test_linha_removida_na_janela_nao_emite():
    """A direcção contrária, que é a cara: a fatura sairia com um açaí que já
    não está na conta — o cliente pagava 8,99 € a mais, com uma FS real
    entregue à AT a dizer que sim."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    _recusa_a_conta_mudada(db, _venda(linhas=[_linha(), _linha(id="linha-2")]))

    assert _refs_de(db) == []


def test_troca_de_iva_na_janela_com_o_mesmo_total_nao_emite():
    """A prova de que o critério NÃO é o total: 8,99 € antes e 8,99 € depois,
    mas a linha passou de 13 % (INT) para 23 % (NOR) — o mesmo dinheiro com
    outro imposto. Uma comparação pelo total deixava sair uma Fatura
    Simplificada REAL com o IVA que ninguém confirmou; e o IVA é o que a AT
    cobra."""
    db = _db(vendas=[_venda(linhas=[_linha(tax_override="NOR")])])
    retrato = _venda(linhas=[_linha()])

    assert _totais(db._coleccoes[COLECOES["vendas"]]._documentos[0])["total"] == \
        _totais(retrato)["total"], "o cenário só prova alguma coisa se o total for o mesmo"

    _recusa_a_conta_mudada(db, retrato)
    assert _refs_de(db) == []


def test_troca_de_linhas_com_o_mesmo_total_nao_emite():
    """A mesma prova pelo lado dos artigos: dois açaís de 8,99 € trocados por
    um artigo de 17,98 €. O total bate ao cêntimo e a fatura é outra — outros
    artigos, outra descrição no talão do cliente."""
    db = _db(vendas=[_venda(linhas=[
        _linha(id="linha-x", produto_nome="Taça Família", produto_preco=17.98)
    ])])
    retrato = _venda(linhas=[_linha(), _linha(id="linha-2")])

    assert _totais(db._coleccoes[COLECOES["vendas"]]._documentos[0])["total"] == \
        _totais(retrato)["total"] == 17.98

    _recusa_a_conta_mudada(db, retrato)
    assert _refs_de(db) == []


def test_conta_igual_na_janela_emite_normalmente():
    """O caminho feliz, e o teste que prova que esta defesa não recusa de
    mais: a conta não mexeu (linhas E desconto), por isso emite-se como
    sempre. Uma guarda que recusasse sempre passava os testes de cima e
    parava as cinco lojas — é este que fica vermelho nesse caso."""
    db = _db(vendas=[_venda(linhas=[_linha()], desconto_global_pct=10)])
    emitiu = []

    async def emitir(ref):
        emitiu.append(ref)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    documento = _corre(finalizar_venda(
        db, _venda(linhas=[_linha()], desconto_global_pct=10),
        emitir, verificar, esperar=_instantaneo,
    ))

    assert emitiu == ["pos-loja-1-sessao-1-venda-1"]
    assert documento["numero"] == "FS 2026/1"
    assert _vendas_de(db)[0]["estado"] == "emitida"


def test_campos_que_nao_afectam_a_fatura_nao_travam_a_emissao():
    """A outra maneira de recusar de mais, e a razão de não se comparar o
    documento inteiro: a compensação de `cancelar_venda` repõe
    `cancelada_em`/`cancelada_por` a `None` numa venda que NÃO foi cancelada,
    e uma tentativa anterior pode ter gravado `pagamentos`/`cliente_nif`.
    Nenhum desses campos vai à fatura — as linhas e os descontos são os
    mesmos, e esta emissão é boa. Recusá-la era deixar a operadora a carregar
    em FINALIZAR sem nunca perceber porquê, com o cliente à frente."""
    db = _db(vendas=[_venda(
        linhas=[_linha()],
        cancelada_em=None, cancelada_por=None,
        pagamentos=[{"tipo_pagamento_id": "tipo-dinheiro", "valor": 8.99}],
        cliente_nif="517542510",
    )])
    emitiu = []

    async def emitir(ref):
        emitiu.append(ref)
        return _bruto()

    async def verificar(ref):
        raise AssertionError("não é um timeout")

    _corre(finalizar_venda(
        db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo
    ))
    assert emitiu == ["pos-loja-1-sessao-1-venda-1"]
    assert _vendas_de(db)[0]["estado"] == "emitida"


class TiposComLinhaNovaAMeio(ColeccaoFalsa):
    """A janela real, na rota real: a colecção dos tipos de pagamento — que a
    rota `finalizar` consulta DEPOIS de ler a venda e ANTES de reservar —
    corre a alteração da conta no meio da validação. Mesma técnica de
    `TiposComCancelamentoAMeio`/`TiposComFechoDeCaixaAMeio`: uma ordem
    determinística, sem duas tarefas à sorte."""

    def __init__(self, documentos, alterar):
        super().__init__(documentos)
        self._alterar = alterar

    async def find_one(self, filtro, projecao=None):
        if self._alterar is not None:
            alterar, self._alterar = self._alterar, None
            await alterar()
        return await super().find_one(filtro, projecao)


def test_juntar_linha_dentro_da_janela_de_validacao_nao_deixa_sair_fatura(monkeypatch):
    """O cenário inteiro, ponta a ponta e com as duas rotas REAIS: a Ana pica
    um segundo açaí (201 — nesse instante a conta está aberta e sem reserva,
    por isso a linha entra mesmo) enquanto o FINALIZAR da Rafaela valida os
    tipos de pagamento. Zero chamadas ao Vendus, reserva libertada, conta
    intacta com as duas linhas — e a operadora ouve o que aconteceu e o que
    fazer, sem chamar ninguém: não há nada de errado, basta confirmar a conta
    nova e repetir."""
    _configura_vendus_env(monkeypatch)
    juntadas = []

    async def juntar():
        resposta = await juntar_linha(
            "venda-1",
            PedidoJuntarLinha(produto_id="prod-1", quantidade=1),
            operador=_operador(operador_id="op-ana", nome="Ana"),
        )
        juntadas.append(len(resposta["linhas"]))

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(
            None, indices_unicos=["vendus_document_id", "atcud"]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(None, indices_unicos=["ext_ref"]),
        COLECOES["tipos_pagamento"]: TiposComLinhaNovaAMeio([_tipo_pagamento()], juntar),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([_sessao_aberta_doc()]),
        COLECOES["produtos"]: ColeccaoFalsa([{
            "id": "prod-1", "nome": "Açaí Regular", "preco": 8.99, "tax_id": "INT",
        }]),
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(venda_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[
                PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert juntadas == [2], "a linha nova não chegou a entrar — não houve corrida nenhuma"
    assert excinfo.value.status_code == 409
    detalhe = excinfo.value.detail
    assert "mudou" in detalhe.lower()
    assert "não saiu" in detalhe.lower()
    assert "finalize outra vez" in detalhe.lower(), (
        "a operadora tem de ficar a saber o que fazer a seguir"
    )
    assert "gestor" not in detalhe.lower(), (
        "não há nada de errado nesta conta — mandar chamar o gestor a uma loja "
        "cheia por causa de uma conta que só precisa de ser confirmada outra "
        "vez é o mesmo erro que dizer 'tente novamente' onde não se pode tentar"
    )
    cliente = ClienteEmissaoVendusFalso.instancias[0]
    assert cliente.chamadas_criar == [], (
        "saiu uma Fatura Simplificada REAL com os itens do retrato velho"
    )
    assert len(_vendas_de(db)[0]["linhas"]) == 2
    assert _vendas_de(db)[0]["estado"] == "aberta"
    assert _refs_de(db) == [], "a reserva abortada ficou a trancar a conta"


def test_conta_alterada_nao_grava_os_pagamentos_da_tentativa_recusada():
    """Recusar tem de deixar a conta EXACTAMENTE como estava — os pagamentos
    e o NIF que a operadora escolheu não se gravam numa venda que não foi
    faturada. `_emitir_e_gravar` é o único sítio que os grava (C2) e esta
    recusa acontece antes dele; se algum dia deixasse de acontecer, ficava no
    Mongo uma venda `aberta` com 8,99 € de pagamentos que nunca entraram em
    fatura nenhuma — e o Z, que soma os `pagamentos`, contava dinheiro que a
    gaveta não tem."""
    db = _db(vendas=[_venda(linhas=[_linha(), _linha(id="linha-2")])])

    async def emitir(ref):
        _nunca_emite(ref)

    async def verificar(ref):
        raise AssertionError("não devia sequer verificar")

    with pytest.raises(ContaAlteradaDepoisDeConfirmada):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo,
            dados_pagamento={
                "pagamentos": [{"tipo_pagamento_id": "tipo-dinheiro", "valor": 8.99}],
                "cliente_nif": "517542510",
            },
        ))

    venda = _vendas_de(db)[0]
    assert venda.get("pagamentos") is None, (
        "ficaram pagamentos gravados numa venda que NÃO foi faturada"
    )
    assert venda.get("cliente_nif") is None


def test_venda_cancelada_E_alterada_diz_que_foi_cancelada():
    """Quando as duas coisas acontecem na mesma janela, a que a operadora
    tem de ouvir é o CANCELAMENTO: "a conta mudou, confirme e finalize outra
    vez" mandava-a repetir numa conta cancelada, onde finalizar nunca mais
    vai passar — o mesmo tipo de conselho impossível de seguir que o resto do
    módulo evita. É a ordem das duas perguntas em `finalizar_venda` que
    decide isto, e é por isso que ela tem um teste."""
    db = _db(vendas=[_venda(
        linhas=[_linha(), _linha(id="linha-2")], estado="cancelada",
    )])

    async def emitir(ref):
        _nunca_emite(ref)

    async def verificar(ref):
        raise AssertionError("não devia sequer verificar")

    with pytest.raises(VendaJaNaoAberta):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo
        ))
    assert _refs_de(db) == []


# ============================================================================
# A decisão tomada sobre uma FOTOGRAFIA tem de ser aplicada com uma escrita
# que exija que a fotografia ainda seja verdade
# ============================================================================
#
# `libertar_reserva_presa` respondia às quatro guardas sobre a reserva lida no
# PRIMEIRO passo e só depois de mais três `await`s (o documento, a venda, a
# sessão) é que a apagava — incondicionalmente. Reproduzido em processo, com
# a saída medida: «1. gestor: libertar LEU a reserva → em_retoma=None / 3.
# retoma: EMISSÃO REAL nº1 a caminho do Vendus / 4. estado real da reserva
# AGORA: em_retoma=True / 5. gestor: libertar APAGA a reserva / 6. respondeu
# 200 libertada=True / 7. operadora: 2.º FINALIZAR → emitida nº FS 2026/902»
# → EMISSÕES REAIS pedidas ao Vendus = 2.
#
# É o `deleted_count` que decide esta corrida, como é o `matched_count` que
# decide a de `cancelar_venda` e a de `_reclamar_retoma`.

from faturacao.fiscal import (  # noqa: E402
    DesfechoDaEmissaoIncerto,
    PedidoReconciliarReserva,
    _emitir_e_gravar,
    _reparticao_do_pagamento,
    reconciliar_reserva_presa,
)
from faturacao.vendus.emissao import (  # noqa: E402
    RegisterIdInvalido,
    VendusModoInvalido,
    VendusRateLimitado,
    VendusRespostaIlegivel,
)


class ColeccaoQueMudaDepoisDaLeitura(ColeccaoFalsa):
    """Duplo que faz acontecer, DENTRO da janela da rota, o que em produção
    acontece noutro pedido: a leitura devolve a fotografia antiga e, logo a
    seguir, o mundo muda (uma retoma reclama a reserva, ou a emissão dela
    acaba e grava o documento).

    A rota fica exactamente com o que teria em produção — um retrato já
    velho — sem ser preciso orquestrar duas tarefas asyncio para o provar.

    O ponto onde se dispara importa, e é por isso que é escolhido caso a
    caso: a rota de libertar faz QUATRO leituras antes de apagar (a reserva,
    o documento, a venda e a sessão) e cada guarda só protege do que já
    aconteceu quando ela corre. Uma mudança disparada na PRIMEIRA leitura é
    apanhada pelas guardas seguintes; só a que se dá DEPOIS da última é que
    prova o `delete_one` condicional."""

    def __init__(self, documentos, mudanca, indices_unicos=None):
        super().__init__(documentos, indices_unicos=indices_unicos)
        self._mudanca = mudanca
        self.armado = True

    async def find_one(self, filtro, projecao=None):
        lido = await super().find_one(filtro, projecao)
        if self.armado:
            self.armado = False
            self._mudanca()
        return lido


# O nome antigo, mantido: é o que os cenários existentes usam para disparar
# na leitura da reserva.
class RefsQueMudamDepoisDaLeitura(ColeccaoQueMudaDepoisDaLeitura):
    async def find_one(self, filtro, projecao=None):
        lido = await ColeccaoFalsa.find_one(self, filtro, projecao)
        if self.armado and "venda_id" in (filtro or {}):
            self.armado = False
            self._mudanca()
        return lido


def _db_libertar(mudanca=None, mudanca_na_sessao=None, documentos=None, vendas=None):
    """A base de dados dos cenários de libertação. `mudanca` dispara na
    leitura da RESERVA (o primeiro passo da rota); `mudanca_na_sessao`
    dispara na leitura da SESSÃO, que é a última coisa que a rota faz antes
    de apagar — a janela onde nenhuma guarda anterior pode ajudar."""
    coleccoes = {}

    def refs_mudam():
        if mudanca is not None:
            mudanca(coleccoes)

    def sessao_muda():
        if mudanca_na_sessao is not None:
            mudanca_na_sessao(coleccoes)

    coleccoes.update({
        COLECOES["vendas"]: ColeccaoFalsa(
            vendas if vendas is not None else [_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(
            documentos, indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["refs_fiscais"]: RefsQueMudamDepoisDaLeitura(
            [_reserva_incerta_antiga()], refs_mudam,
            indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa([_tipo_pagamento()]),
        COLECOES["sessoes_caixa"]: ColeccaoQueMudaDepoisDaLeitura(
            [_sessao_aberta_doc()], sessao_muda),
    })
    return DbFalsa(coleccoes)


def _reservas_em(coleccoes):
    return coleccoes[COLECOES["refs_fiscais"]]._documentos


def test_libertar_nao_apaga_a_reserva_que_uma_retoma_reclamou_dentro_da_janela(monkeypatch):
    """O cenário reproduzido: o gestor confirmou no Vendus que não há nada
    (e não havia — a fatura ia a caminho) e carrega em Libertar; entre a
    leitura e o apagar, a operadora carrega em FINALIZAR e a retoma reclama a
    reserva. Apagá-la era autorizar a segunda Fatura Simplificada."""
    def reclama_a_retoma(coleccoes):
        _reservas_em(coleccoes)[0].update({
            "em_retoma": True, "em_retoma_desde": _agora_iso(1)})

    db = _db_libertar(reclama_a_retoma)
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "RECLAMADA" in excinfo.value.detail
    # E o essencial: a reserva CONTINUA lá, a impedir a segunda emissão.
    assert len(_refs_de(db)) == 1


def test_libertar_nao_apaga_a_reserva_de_uma_venda_que_ficou_emitida_na_janela(monkeypatch):
    """A retoma não só reclamou como ACABOU dentro da janela: a marca de
    retoma volta a `None` (é o que `_limpar_incerta_resolvida` faz) e o par
    `em_retoma`/`em_retoma_desde` do filtro já não a apanhava. O que a
    apanha é o `documento_id` carimbado na reserva — apagá-la era deitar
    fora a peça que sustenta a idempotência de uma venda JÁ emitida."""
    def a_retoma_acaba(coleccoes):
        # Dispara na leitura da SESSÃO — a última antes de apagar. Disparada
        # mais cedo, era a guarda do documento (que corre no segundo passo)
        # a apanhar isto, e o `delete_one` condicional ficava por provar.
        _reservas_em(coleccoes)[0].update({
            "incerta": False, "em_retoma": None, "em_retoma_desde": None,
            "documento_id": "doc-901",
        })
        coleccoes[COLECOES["documentos"]]._documentos.append({
            "id": "doc-901", "ext_ref": "pos-loja-1-sessao-1-venda-1",
            "numero": "FS 2026/901", "atcud": "ATCUD-901", "venda_id": "venda-1",
        })

    db = _db_libertar(mudanca_na_sessao=a_retoma_acaba)
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "FS 2026/901" in excinfo.value.detail
    assert len(_refs_de(db)) == 1


def test_libertar_responde_404_quando_outro_gestor_a_libertou_na_janela(monkeypatch):
    """Dois separadores do backoffice na mesma conta. Quem chega tarde não
    pode responder "libertada por si" a uma reserva que não foi ele que
    apagou — nem repetir a escrita às cegas."""
    def outro_liberta(coleccoes):
        del _reservas_em(coleccoes)[:]

    db = _db_libertar(outro_liberta)
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert excinfo.value.status_code == 404


def test_libertar_continua_a_apagar_quando_nada_muda_debaixo_dele(monkeypatch):
    """O outro lado da guarda: sem ninguém a mexer na reserva, a libertação
    faz exactamente o que sempre fez — senão a única saída destas contas
    passava a ser um 409 permanente, que é o estrago ao contrário."""
    db = _db_libertar()
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert resposta["libertada"] is True
    assert _refs_de(db) == []


def test_libertar_apaga_uma_retoma_ABANDONADA_ha_muito(monkeypatch):
    """O filtro condicional usa o valor LIDO da marca de retoma, e não
    `None` à força — senão uma reserva com uma retoma morta (o processo que
    a reclamou morreu num deploy) ficava trancada para sempre, e essa é
    precisamente a conta que esta rota existe para desentalar."""
    db = _db_libertar()
    db._coleccoes[COLECOES["refs_fiscais"]]._documentos[0].update({
        "em_retoma": True, "em_retoma_desde": _agora_iso(3600),  # há uma hora
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert resposta["libertada"] is True
    assert resposta["motivo"] == "em_retoma"
    assert _refs_de(db) == []


# ============================================================================
# O `except Exception` que libertava a reserva de uma fatura que JÁ existe
# ============================================================================
#
# Ele apanhava também o que rebenta DEPOIS de uma resposta 2xx, com o
# documento fiscal já criado (`vendus/emissao.py`: o corpo que não é JSON, o
# `output` que não é base64, o `amount_gross` que não é número). Reproduzido:
# «[VENDUS] documento fiscal REAL criado: FS 2026/900 → JSONDecodeError →
# estado no sistema: venda='aberta' | reservas=0 | fat_documentos=0» — e o
# ecrã, que relê a venda, recebia `emissao_por_confirmar: False` e convidava a
# emitir outra vez: 2 FS reais.


async def _nunca_verifica(_ref):
    raise AssertionError("não devia chegar a verificar")


def _emitir_que_levanta(erro):
    async def emitir(_ref):
        raise erro
    return emitir


def test_erro_desconhecido_na_emissao_marca_incerta_e_NAO_liberta_a_reserva():
    db = _db(vendas=[_venda(linhas=[_linha()])])

    with pytest.raises(DesfechoDaEmissaoIncerto):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]),
            _emitir_que_levanta(ValueError("Expecting value: line 1 column 1")),
            _nunca_verifica,
        ))

    reservas = _refs_de(db)
    assert len(reservas) == 1, "a reserva de uma fatura que pode existir NUNCA se liberta"
    assert reservas[0]["incerta"] is True


def test_resposta_ilegivel_do_vendus_e_tratada_como_incerta():
    """`VendusRespostaIlegivel` é `VendusErro` mas NÃO é `VendusHTTPErro` —
    e é essa a diferença que a mantém fora da lista de "prova de que nada
    saiu"."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    with pytest.raises(DesfechoDaEmissaoIncerto):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]),
            _emitir_que_levanta(VendusRespostaIlegivel("200 com HTML de manutenção")),
            _nunca_verifica,
        ))

    assert _refs_de(db)[0]["incerta"] is True


@pytest.mark.parametrize("erro", [
    RegisterIdInvalido("register_id 9 não bate com o configurado"),
    VendusModoInvalido("VENDUS_MODE não está definido"),
    VendusRateLimitado("429 mesmo após 3 tentativas"),
    VendusHTTPErro(400, "tax_id inválido"),
])
def test_os_erros_com_prova_de_que_nada_saiu_continuam_a_libertar_a_reserva(erro):
    """A lista curta do que É seguro libertar: os dois primeiros são
    recusados ANTES de qualquer pedido sair para a rede; o 429 é uma recusa a
    processar; um 4xx é o Vendus (ou o que estiver à frente dele) a rejeitar
    o pedido — o caso comum ao balcão, em que a conta TEM de destrancar para
    a operadora corrigir e voltar a finalizar."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    with pytest.raises(type(erro)):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), _emitir_que_levanta(erro), _nunca_verifica,
        ))

    assert _refs_de(db) == []


def test_a_rota_traduz_o_desfecho_desconhecido_para_503_e_nunca_500(monkeypatch):
    """O ecrã lê um 500 com a venda ainda `aberta` como "nada saiu, pode
    repetir" (`PosVenda.js::tipoDoErroDeEmissao`) — que é exactamente a
    segunda fatura. 503 é o balde do "não sabemos se saiu"."""
    db = _db(vendas=[_venda(linhas=[_linha()])], tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _configura_vendus_env(monkeypatch)

    class ClienteQueRebentaDepoisDo2xx(ClienteEmissaoVendusFalso):
        def criar_fatura_simplificada(self, **kwargs):
            self.chamadas_criar.append(kwargs)
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteQueRebentaDepoisDo2xx)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[
                PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert excinfo.value.status_code == 503
    assert "confirme no vendus" in excinfo.value.detail.lower()
    # E a venda continua trancada pela reserva incerta: é isso que o ecrã lê
    # como `emissao_por_confirmar` e o impede de convidar a emitir de novo.
    assert _refs_de(db)[0]["incerta"] is True


def test_depois_de_um_desfecho_desconhecido_a_tentativa_seguinte_verifica_em_vez_de_emitir():
    """O fecho do ciclo: a operadora carrega outra vez em FINALIZAR e a
    retoma é OBRIGADA a verificar primeiro — encontra a FS que já tinha
    saído e grava-a, sem uma segunda emissão."""
    db = _db(vendas=[_venda(linhas=[_linha()])])
    emissoes = []

    async def emitir_que_cria_e_rebenta(_ref):
        emissoes.append("criada no Vendus")
        raise ValueError("corpo ilegível de um 200")

    async def verificar_que_encontra(_ref):
        return _bruto(id=900, numero="FS 2026/900", atcud="ATCUD-900")

    with pytest.raises(DesfechoDaEmissaoIncerto):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir_que_cria_e_rebenta, _nunca_verifica,
        ))

    documento = _corre(finalizar_venda(
        db, _venda(linhas=[_linha()]), emitir_que_cria_e_rebenta,
        verificar_que_encontra, esperar=_instantaneo,
    ))

    assert documento["numero"] == "FS 2026/900"
    assert len(emissoes) == 1, "a segunda tentativa NÃO pode voltar a emitir"
    assert _vendas_de(db)[0]["estado"] == "emitida"


# ============================================================================
# O documento gravado: o que o resto do sistema precisa de lá encontrar
# ============================================================================


def _grava(db, bruto, ext_ref="pos-loja-1-sessao-1-venda-1", reserva_id=None):
    return _corre(_gravar_documento(
        db, ext_ref, _venda(linhas=[_linha()]), bruto, reserva_id=reserva_id))


def test_documento_gravado_traz_os_campos_que_o_dashboard_soma():
    """`dashboard.py::_campo_valor` lê `total_bruto` (com IVA) ou
    `total_liquido` (sem) e nenhum dos dois era gravado: toda a receita das 5
    lojas valia 0,00 €. `total` mantém-se — é o que o ecrã do POS lê."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    documento = _grava(db, _bruto(total=8.99, total_bruto=8.99, total_liquido=7.96))

    assert documento["total_bruto"] == 8.99
    assert documento["total_liquido"] == 7.96
    assert documento["total"] == 8.99


def test_documento_trazido_por_verificacao_fica_com_o_instante_do_vendus():
    """A receita de ontem à noite não pode cair no cartão de HOJE só porque
    foi hoje que a fomos buscar."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    documento = _grava(db, _bruto(emitido_em="2026-08-18T22:30:00+00:00"))

    assert documento["emitido_em"] == "2026-08-18T22:30:00+00:00"


def test_documento_sem_instante_do_vendus_cai_no_actual_e_nao_inventa_data():
    """Sem data legível do Vendus (ou num documento criado agora mesmo) o
    instante é o actual — nunca uma data inventada a partir de um campo que
    não se soube ler."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    documento = _grava(db, _bruto())

    assert documento["emitido_em"] is not None
    assert documento["emitido_em"].startswith(str(datetime.now(timezone.utc).year))


def test_documento_guarda_o_modo_em_que_saiu():
    db = _db(vendas=[_venda(linhas=[_linha()])])
    assert _grava(db, _bruto(modo="tests"))["modo"] == "tests"


def test_gravar_o_MESMO_documento_outra_vez_reutiliza_o_que_ja_la_esta():
    """O caminho normal de recuperação (um retry depois de a resposta se ter
    perdido): a mesma `ext_ref` e o mesmo documento fiscal — reutiliza-se,
    sem inventar um segundo e sem alarme nenhum."""
    db = _db(vendas=[_venda(linhas=[_linha()])])
    primeiro = _grava(db, _bruto(id=501, atcud="ATCUD-1"))

    # O id vem como string na leitura e como inteiro na criação — o mesmo
    # documento à mesma.
    segundo = _grava(db, _bruto(id="501", atcud="ATCUD-1"))

    assert segundo["id"] == primeiro["id"]
    assert len(db._coleccoes[COLECOES["documentos"]]._documentos) == 1


def test_um_SEGUNDO_documento_diferente_na_mesma_ext_ref_e_um_erro_ALTO():
    """A duplicação silenciosa que o índice único de `ext_ref` transforma em
    erro: duas linhas com a mesma referência e ATCUDs diferentes, a venda a
    apontar para uma, o ecrã a mostrar a que o Mongo calhasse e a listagem de
    presas a não a mostrar. Agora rebenta no instante em que acontece — e a
    reserva NÃO se liberta, porque os dois documentos fiscais existem."""
    db = _db(vendas=[_venda(linhas=[_linha()])])
    _grava(db, _bruto(id=901, atcud="ATCUD-901", numero="FS 2026/901"))

    with pytest.raises(ConflitoDocumentoFiscal) as excinfo:
        _grava(db, _bruto(id=902, atcud="ATCUD-902", numero="FS 2026/902"))

    assert "FS 2026/901" in str(excinfo.value)
    assert "ATCUD-902" in str(excinfo.value)
    assert len(db._coleccoes[COLECOES["documentos"]]._documentos) == 1


# ============================================================================
# Reconciliar: o que se diz ao gestor sobre o Z, e onde é que isso fica
# ============================================================================


def _pagamento(tipo_fiscal="NU", valor=8.99, nome="Dinheiro"):
    return {
        "tipo_pagamento_id": "tipo-%s" % tipo_fiscal.lower(), "nome": nome,
        "tipo_fiscal": tipo_fiscal, "valor": valor,
    }


def _venda_paga_misto():
    return _venda(
        id="venda-1", linhas=[_linha()],
        pagamentos=[_pagamento("NU", 4.50), _pagamento("CD", 4.49, "Multibanco")],
    )


def test_reconciliar_com_pagamento_misto_manda_acertar_SO_a_parte_em_dinheiro(monkeypatch):
    """O aviso mandava acertar a gaveta pelo total BRUTO da fatura. Num
    pagamento misto isso é falso e cria a diferença ao contrário: 8,99 € de
    fatura com 4,50 € em dinheiro e 4,49 € em multibanco mandava acertar
    8,99 € numa gaveta que já tinha sido contada e assinada."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["dinheiro_por_acertar"] == 4.50
    assert resposta["outros_meios"] == 4.49
    assert "4.50 €" in resposta["aviso_do_z"]
    assert "4.49 €" in resposta["aviso_do_z"]
    # O total da fatura continua a aparecer (é o que se procura no Vendus),
    # mas já não é o valor que ele é mandado acertar na gaveta.
    assert "8.99 €" in resposta["aviso_do_z"]
    assert "DINHEIRO" in resposta["aviso_do_z"]


def test_reconciliar_de_uma_venda_toda_em_dinheiro_acerta_pelo_total(monkeypatch):
    """O outro lado: quando tudo foi mesmo em dinheiro, o valor a acertar é o
    total — a correcção não pode ter partido o caso simples."""
    db = _db_reconciliacao(
        sessao_estado="fechada",
        venda=_venda(id="venda-1", linhas=[_linha()], pagamentos=[_pagamento("NU", 8.99)]),
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["dinheiro_por_acertar"] == 8.99
    assert resposta["outros_meios"] == 0.0


def test_reconciliar_deixa_a_marca_na_PROPRIA_sessao_de_caixa(monkeypatch):
    """O aviso vivia só no corpo daquela resposta e num `logger.warning`:
    passada uma semana não havia um único sítio onde se visse que aqueles
    euros existiram. O Z não se recalcula — REGISTA-SE que uma venda lhe foi
    ligada depois do fecho."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99, numero="FS 2026/77", atcud="ATCUD-REAL"))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "dono@lacai.pt"}))

    assert resposta["registada_na_sessao"] is True
    sessao = db._coleccoes[COLECOES["sessoes_caixa"]]._documentos[0]
    marcas = sessao["vendas_ligadas_depois_do_fecho"]
    assert len(marcas) == 1
    assert marcas[0]["venda_id"] == "venda-1"
    assert marcas[0]["numero"] == "FS 2026/77"
    assert marcas[0]["total"] == 8.99
    assert marcas[0]["dinheiro"] == 4.50
    assert marcas[0]["por"] == "dono@lacai.pt"
    assert marcas[0]["ligada_em"]
    # O Z assinado NÃO se toca: nem `esperado`, nem `contado`, nem
    # `diferenca` — o talão foi assinado com a gaveta contada à frente de
    # quem o assinou.
    assert sessao["estado"] == "fechada"
    assert "esperado" not in sessao or sessao.get("esperado") is None


def test_duas_reconciliacoes_da_mesma_sessao_deixam_as_DUAS_marcas(monkeypatch):
    """Duas contas presas da mesma noite (o caso normal quando um deploy
    apanha o serviço a meio). Com um `$set` de uma lista relida, uma das
    marcas perdia-se."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())
    db._coleccoes[COLECOES["vendas"]]._documentos.append(
        _venda(id="venda-2", sessao_id="sessao-1", linhas=[_linha()],
               pagamentos=[_pagamento("NU", 8.99)]))
    db._coleccoes[COLECOES["refs_fiscais"]]._documentos.append(
        _reserva_incerta_antiga(id="r2", venda_id="venda-2",
                                ext_ref="pos-loja-1-sessao-1-venda-2"))
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))
    _vendus_que_tem(monkeypatch, _bruto(id=502, atcud="ATCUD-2", numero="FS 2026/2", total=8.99))
    _corre(reconciliar_reserva_presa("venda-2", None, gestor={"email": "x"}))

    marcas = db._coleccoes[COLECOES["sessoes_caixa"]]._documentos[0][
        "vendas_ligadas_depois_do_fecho"]
    assert [m["venda_id"] for m in marcas] == ["venda-1", "venda-2"]


def test_reconciliar_com_a_caixa_AINDA_ABERTA_nao_marca_nada(monkeypatch):
    """Com a sessão aberta esta venda entra no Z normalmente — uma marca de
    "ligada depois do fecho" seria ruído a mandar acertar o que não precisa
    de acerto nenhum."""
    db = _db_reconciliacao(sessao_estado="aberta", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["registada_na_sessao"] is False
    assert resposta["aviso_do_z"] is None
    sessao = db._coleccoes[COLECOES["sessoes_caixa"]]._documentos[0]
    assert "vendas_ligadas_depois_do_fecho" not in sessao


def test_a_marca_que_falha_nao_derruba_uma_reconciliacao_ja_feita(monkeypatch):
    """A reconciliação em si JÁ correu bem — o documento fiscal está gravado
    e a venda está `emitida`. Um soluço do Mongo na marca de apoio não pode
    virar um 500 que manda o gestor repetir uma operação já feita."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())

    class SessoesQueRebentamAEscrever(ColeccaoFalsa):
        async def update_one(self, filtro, atualizacao):
            raise RuntimeError("Mongo indisponível")

    db._coleccoes[COLECOES["sessoes_caixa"]] = SessoesQueRebentamAEscrever(
        [_sessao_aberta_doc(estado="fechada")])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["reconciliada"] is True
    assert resposta["registada_na_sessao"] is False
    assert _vendas_de(db)[0]["estado"] == "emitida"


def test_reconciliar_nao_apaga_a_marca_de_uma_retoma_que_reclamou_na_janela(monkeypatch):
    """A mesma forma de defeito do `libertar`, na outra rota de gestão — e
    aqui a janela é MAIOR, porque inclui uma chamada HTTP ao Vendus. Limpar a
    marca da reclamação era apagar por baixo de quem está a emitir neste
    instante a própria marca que impede os dois botões de lhe tocarem."""
    db = _db_reconciliacao(sessao_estado="aberta", venda=_venda_paga_misto())

    def reclama_a_retoma():
        db._coleccoes[COLECOES["refs_fiscais"]]._documentos[0].update({
            "em_retoma": True, "em_retoma_desde": _agora_iso(1)})

    db._coleccoes[COLECOES["refs_fiscais"]] = RefsQueMudamDepoisDaLeitura(
        [_reserva_incerta_antiga()], reclama_a_retoma,
        indices_unicos=_unicos_de("fat_refs_fiscais"))
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto())

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    # O documento entra na mesma (é um facto do lado da AT que já aconteceu),
    # mas a marca da retoma fica INTACTA para quem a reclamou.
    assert resposta["reconciliada"] is True
    reserva = _refs_de(db)[0]
    assert reserva["em_retoma"] is True


def test_reparticao_do_pagamento_sem_pagamentos_gravados_devolve_none():
    """Zero não é "não sei": um 0,00 € em dinheiro leria-se como "não entrou
    dinheiro nenhum" e mandava não mexer numa gaveta que pode estar a menos."""
    assert _reparticao_do_pagamento(_venda(linhas=[_linha()])) is None


def test_reconciliar_a_MESMA_venda_duas_vezes_deixa_UMA_marca(monkeypatch):
    """A rota promete responder o mesmo a um pedido repetido "sem escrever
    nada de novo". Duas marcas dos MESMOS 8,99 € convidavam o gestor a
    acertar a gaveta daquele turno duas vezes — o estrago que este registo
    existe precisamente para evitar."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    primeira = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))
    segunda = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert primeira["registada_na_sessao"] is True
    # O pedido repetido continua a dizer que está registada — porque está.
    assert segunda["registada_na_sessao"] is True
    assert segunda["veio_do_vendus_agora"] is False
    marcas = db._coleccoes[COLECOES["sessoes_caixa"]]._documentos[0][
        "vendas_ligadas_depois_do_fecho"]
    assert len(marcas) == 1


def test_documento_gravado_diz_o_que_e_e_nao_grava_anulado():
    """O outro campo que o Dashboard lê de cada documento
    (`dashboard.py::_valor_documento`): uma NC conta com sinal negativo. Uma
    linha de documento fiscal que não diz o que é obriga quem a soma a
    adivinhar.

    `anulado` fica por gravar de propósito: o campo ausente já significa "não
    anulado" nos dois lados do Dashboard, e é isso que a consulta
    `_existe_venda` (`$ne: True`) assume — ver o teste que guarda essa
    ausência em test_dashboard.py."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    documento = _grava(db, _bruto())

    assert documento["tipo"] == "FS"
    assert "anulado" not in documento


# ============================================================================
# A FORMA de uma reserva não é a IDENTIDADE de uma reserva
# ============================================================================
#
# A ronda anterior tornou o apagar CONDICIONAL: só apaga se a reserva
# continuar "como estava" (`em_retoma`, `em_retoma_desde`, `documento_id`).
# Fechou o defeito que tinha à frente e abriu uma versão mais estreita de si
# próprio: esses três campos descrevem a FORMA de uma reserva intacta, e uma
# reserva NOVA — criada dois passos depois, com a MESMA `ext_ref`, porque a
# referência é determinística — tem exactamente essa forma.
#
# Reproduzido em processo, nas duas variantes (o Vendus recusa com 4xx, e o
# timeout com verificação vazia): «7. APAGOU 1 reserva(s) com o filtro {...}
# (estavam lá: ['75c14dbb-...'])» — o id da reserva NOVA, com uma emissão
# real em voo — «10. FINALIZAR nº3 → emitida nº FS 2026/902 / 11. a emissão
# que estava em voo acabou: 500 ConflitoDocumentoFiscal» → EMISSÕES REAIS
# pedidas ao Vendus = 2.
#
# A correcção é prender a IDENTIDADE (o `id`, o uuid4 que `_reservar` escreve)
# e não só a forma. Os testes abaixo são o par: um por cada sítio que decide
# sobre uma reserva lida antes.

from faturacao.fiscal import (  # noqa: E402
    SessaoEmFechoAgora,
    _limpar_incerta_se_intacta,
    _libertar_reserva_se_intacta,
)


def test_libertar_nao_apaga_a_reserva_NOVA_que_substituiu_a_que_o_gestor_leu(monkeypatch):
    """O cenário medido: a reserva que o gestor viu foi libertada (o Vendus
    recusou aquela tentativa com um 4xx — o caso COMUM ao balcão) e a
    operadora carregou outra vez em FINALIZAR. O que está no Mongo quando o
    `delete_one` corre é uma reserva NOVA, sem marca nenhuma, com uma emissão
    REAL a caminho do Vendus — e passa, campo a campo, no filtro desenhado
    para a velha."""
    def a_reserva_e_substituida(coleccoes):
        # Dispara na leitura da SESSÃO, a última antes de apagar: nenhuma
        # das guardas anteriores pode ajudar aqui.
        refs = _reservas_em(coleccoes)
        del refs[:]
        refs.append({
            "id": "r-nova", "ext_ref": "pos-loja-1-sessao-1-venda-1",
            "venda_id": "venda-1", "criado_em": _agora_iso(2),
        })

    db = _db_libertar(mudanca_na_sessao=a_reserva_e_substituida)
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    with pytest.raises(HTTPException) as excinfo:
        _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    # E a mensagem diz-lhe o que realmente aconteceu: não "a reserva mudou",
    # mas "há uma tentativa NOVA a emitir esta conta" — o que confirmou no
    # Vendus era sobre a tentativa anterior.
    assert "reserva NOVA" in excinfo.value.detail
    assert "segundos" in excinfo.value.detail
    # O essencial: a reserva da emissão em voo CONTINUA lá.
    assert [r["id"] for r in _refs_de(db)] == ["r-nova"]


def test_libertar_apaga_a_reserva_certa_quando_e_mesmo_a_que_o_gestor_leu(monkeypatch):
    """O outro lado da guarda, para o `id` no filtro não poder ser um 409
    permanente: sem ninguém a mexer, a libertação faz o que sempre fez.
    (O caso geral já está coberto; este fixa que é o `id` LIDO que casa, e
    não um acaso.)"""
    db = _db_libertar()
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)

    resposta = _corre(libertar_reserva_presa("venda-1", _confirmado(), gestor={"email": "x"}))

    assert resposta["libertada"] is True
    assert _refs_de(db) == []


def test_libertar_se_intacta_recusa_uma_reserva_com_outro_id_e_a_mesma_forma():
    """O mesmo, isolado da rota: a reserva lida e a que está lá agora têm a
    forma toda igual (sem retoma, sem documento) e só diferem no `id` — que é
    precisamente o caso de uma reserva substituída."""
    ref = "pos-loja-1-sessao-1-venda-1"
    lida = {"id": "r-velha", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}
    db = _db(refs=[{"id": "r-nova", "ext_ref": ref, "venda_id": "venda-1",
                    "criado_em": _agora_iso(1)}])

    assert _corre(_libertar_reserva_se_intacta(db, ref, lida)) is False
    assert [r["id"] for r in _refs_de(db)] == ["r-nova"]


def test_limpar_incerta_nao_desmarca_a_reserva_NOVA_que_substituiu_a_lida():
    """A MESMA forma de defeito na outra rota de gestão. A reconciliação lê a
    reserva, vai ao Vendus (SEGUNDOS de rede) e só depois limpa a marca
    `incerta`. Se nessa janela a reserva foi libertada e outra nasceu no
    lugar — igual em tudo menos no `id`, porque a `ext_ref` é determinística
    — a limpeza sem identidade apagava o `incerta` DELA: a marca que obriga a
    tentativa seguinte a verificar no Vendus antes de emitir seja o que for.
    Tirá-la é autorizar uma emissão às cegas sobre uma venda que pode já ter
    Fatura Simplificada real."""
    ref = "pos-loja-1-sessao-1-venda-1"
    lida = {"id": "r-velha", "ext_ref": ref, "venda_id": "venda-1", "incerta": True}
    db = _db(refs=[{"id": "r-nova", "ext_ref": ref, "venda_id": "venda-1",
                    "criado_em": _agora_iso(1), "incerta": True}])

    assert _corre(_limpar_incerta_se_intacta(db, ref, lida)) is False
    nova = _refs_de(db)[0]
    assert nova["incerta"] is True, (
        "desmarcou a reserva de outra tentativa — a seguinte emite sem verificar"
    )


def test_limpar_incerta_resolvida_so_desfaz_a_reclamacao_com_o_seu_carimbo():
    """O terceiro sítio com a mesma forma: o `finally` da retoma. Ele desfaz
    a marca de retoma — e tem de desfazer A SUA, identificada pelo carimbo
    que ele próprio escreveu, nunca "a marca que houver nesta ext_ref". Uma
    reserva substituída e já reclamada por OUTRA tentativa ficava sem a marca
    da reclamação, que é exactamente a peça que impede `libertar` (e a
    reconciliação) de mexer numa emissão em voo."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(refs=[{
        "id": "r-nova", "ext_ref": ref, "venda_id": "venda-1", "incerta": True,
        "em_retoma": True, "em_retoma_desde": _agora_iso(1),
    }])

    _corre(_limpar_incerta_resolvida(db, ref, "o-carimbo-da-retoma-que-acabou"))

    nova = _refs_de(db)[0]
    assert nova["em_retoma"] is True, "desarmou a defesa de uma emissão em voo"
    assert nova["incerta"] is True


def test_retoma_que_falha_nao_desfaz_a_reclamacao_de_uma_reserva_substituida():
    """O mesmo `finally`, agora pelo caminho real e no desfecho oposto (a
    retoma continua incerta). A reserva desta retoma desaparece e outra nasce
    no lugar, já reclamada por uma tentativa nova que está a falar com o
    Vendus neste instante."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(vendas=[_venda(linhas=[_linha()])], refs=[_reserva_incerta_antiga()])

    async def emitir(_ref):
        raise AssertionError("não devia chegar a emitir")

    async def verificar(_ref):
        refs = _refs_de(db)
        del refs[:]
        refs.append({
            "id": "r-nova", "ext_ref": ref, "venda_id": "venda-1", "incerta": True,
            "em_retoma": True, "em_retoma_desde": _agora_iso(1),
        })
        raise VendusIndisponivel("o GET de verificação falhou")

    with pytest.raises(fiscal_mod.VerificacaoFiscalIncerta):
        _corre(_retomar_reserva_incerta(
            db, ref, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo))

    nova = _refs_de(db)[0]
    assert nova["em_retoma"] is True, "desarmou a defesa de uma emissão em voo"


# ============================================================================
# Um fecho A DECORRER não é um fecho FEITO
# ============================================================================
#
# O estado intermédio `a_fechar` (caixa.py) fechou o buraco do Z e deixou a
# emissão a dizer à operadora uma coisa que podia não ter acontecido: o
# núcleo só sabia perguntar "a sessão está `aberta`?" e tratava tudo o resto
# como turno acabado. Varridas 300 interposições do FINALIZAR contra o
# FECHAR, 18 delas diziam-lhe «A caixa desta venda foi FECHADA [...] o Z
# desse turno já foi assinado sem ela. Pique a conta de novo na sessão de
# caixa nova» — e o estado real no fim era: sessão `aberta`, nenhum Z
# escrito, conta `aberta`, zero reservas, zero emissões ao Vendus. Quatro
# afirmações, as quatro falsas, com o cliente à frente.

_PEDACOS_DE_TURNO_ACABADO = ("foi FECHADA", "já não está aberta", "sessão de caixa nova")


def test_finalizar_com_a_caixa_a_meio_de_um_fecho_manda_esperar(monkeypatch):
    """A entrada da rota. A conta continua ali, faturável — o fecho ainda
    pode ser recusado e desfeito (é o que acontece sempre que ele encontra
    uma emissão viva nesta caixa)."""
    _configura_vendus_env(monkeypatch)
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        tipos_pagamento=[_tipo_pagamento()],
        sessoes=[_sessao_aberta_doc(estado="a_fechar")],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert excinfo.value.status_code == 409
    assert "está a FECHAR" in excinfo.value.detail
    assert "carregue outra vez em FINALIZAR" in excinfo.value.detail
    for pedaco in _PEDACOS_DE_TURNO_ACABADO:
        assert pedaco not in excinfo.value.detail, (
            "disse à operadora que o turno acabou com a caixa ainda por fechar"
        )
    assert ClienteEmissaoVendusFalso.instancias == []


def test_garante_venda_ainda_aberta_distingue_o_fecho_a_decorrer_do_fecho_feito():
    """A releitura do núcleo, isolada. A decisão é a mesma de sempre (não se
    emite, a reserva liberta-se, nada vai ao Vendus) — o TIPO é que passa a
    dizer qual dos dois casos é, e é uma subclasse de propósito, para quem só
    quer saber "deixou de estar aberta?" continuar a apanhar os dois."""
    ref = "pos-loja-1-sessao-1-venda-1"
    db = _db(
        vendas=[_venda(linhas=[_linha()])],
        refs=[{"id": "r1", "ext_ref": ref, "venda_id": "venda-1"}],
        sessoes=[_sessao_aberta_doc(estado="a_fechar")],
    )

    with pytest.raises(SessaoEmFechoAgora) as excinfo:
        _corre(fiscal_mod._garante_venda_ainda_aberta(db, ref, "venda-1", "r1"))

    assert isinstance(excinfo.value, fiscal_mod.SessaoJaNaoAberta)
    assert "a meio de um fecho" in str(excinfo.value)
    # A reserva liberta-se: enquanto ela existir, o fecho recusa-se a si
    # próprio (`caixa.py::_venda_com_emissao_viva`) e a caixa não fecha.
    assert _refs_de(db) == []


def test_fecho_que_comeca_depois_da_entrada_da_rota_ainda_manda_esperar(monkeypatch):
    """A corrida a sério, pela rota inteira: a sessão está `aberta` quando a
    rota a valida e passa a `a_fechar` antes de a emissão a reler (é a janela
    que as 300 interposições varreram). A operadora tem de ler a MESMA coisa
    dos dois lados — uma espera, não um fim."""
    _configura_vendus_env(monkeypatch)
    sessoes = ColeccaoQueMudaDepoisDaLeitura([_sessao_aberta_doc()], lambda: None)

    def o_outro_pc_comeca_a_fechar():
        sessoes._documentos[0]["estado"] = "a_fechar"

    sessoes._mudanca = o_outro_pc_comeca_a_fechar
    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(None, indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(None, indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa([_tipo_pagamento()]),
        COLECOES["sessoes_caixa"]: sessoes,
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert excinfo.value.status_code == 409
    assert "está a FECHAR" in excinfo.value.detail
    for pedaco in _PEDACOS_DE_TURNO_ACABADO:
        assert pedaco not in excinfo.value.detail
    # Nada foi ao Vendus e a reserva não ficou órfã a trancar a conta.
    assert all(c.chamadas_criar == [] for c in ClienteEmissaoVendusFalso.instancias)
    assert _refs_de(db) == []
    assert _vendas_de(db)[0]["estado"] == "aberta"


def test_com_a_caixa_mesmo_FECHADA_a_mensagem_continua_a_ser_a_do_turno_acabado(monkeypatch):
    """O outro lado: distinguir os dois casos não pode ter suavizado o que se
    diz a quem chega DEPOIS de um Z assinado. Aí a conta não se fatura mesmo
    mais neste turno, e a saída é picá-la na sessão nova."""
    _configura_vendus_env(monkeypatch)
    sessoes = ColeccaoQueMudaDepoisDaLeitura([_sessao_aberta_doc()], lambda: None)
    sessoes._mudanca = lambda: sessoes._documentos[0].update({"estado": "fechada"})
    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(None, indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(None, indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa([_tipo_pagamento()]),
        COLECOES["sessoes_caixa"]: sessoes,
    })
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(finalizar(
            "venda-1",
            PedidoFinalizarVenda(pagamentos=[PagamentoEntrada(tipo_pagamento_id="tipo-dinheiro", valor=8.99)]),
            operador=_operador(),
        ))

    assert excinfo.value.status_code == 409
    assert "foi FECHADA" in excinfo.value.detail
    assert "sessão de caixa nova" in excinfo.value.detail
    assert _refs_de(db) == []


# ============================================================================
# RECONCILIAR dentro da marca `a_fechar`: os mesmos euros contados duas vezes
# ============================================================================
#
# `reconciliar` decide o aviso do Z por "a sessão está aberta?" — e `a_fechar`
# não é "aberta". Só que essa marca é posta ANTES de o fecho ler as vendas:
# uma venda que passe a `emitida` dentro dela ENTRA no Z que sai a seguir E
# leva o aviso a dizer que o Z foi assinado sem ela. Reproduzido: «3. gestor:
# RECONCILIAR → venda emitida, z_por_acertar=True, dinheiro_por_acertar=8.99»
# e a seguir «4. fecho: Z escrito → vendas_dinheiro=8.99». O gestor lê "na
# GAVETA desse fecho faltam contar 8,99 €", acrescenta-os a uma gaveta que já
# os tinha, e fabrica uma diferença de +8,99 € num turno que estava certo — e
# fica registado na sessão a dizer o mesmo, para quem lá for daqui a um mês.


class SessoesQueMudamNaLeitura(ColeccaoFalsa):
    """Sessões de caixa que mudam de estado logo A SEGUIR à n-ésima leitura —
    o fecho do outro PC a acontecer no instante exacto que interessa a cada
    cenário. Contar as leituras (em vez de disparar sempre na primeira) é o
    que permite pôr a mudança de um lado ou do outro da escrita."""

    def __init__(self, documentos, na_leitura, novo_estado):
        super().__init__(documentos)
        self._na_leitura = na_leitura
        self._novo_estado = novo_estado
        self.leituras = 0

    async def find_one(self, filtro, projecao=None):
        lido = await super().find_one(filtro, projecao)
        self.leituras += 1
        if self.leituras == self._na_leitura:
            self._documentos[0]["estado"] = self._novo_estado
        return lido


def _db_reconciliacao_com_sessoes(sessoes, venda=None, refs=None):
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(
            [venda if venda is not None else _venda(id="venda-1", linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(None, indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(
            refs if refs is not None else [_reserva_incerta_antiga()],
            indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa([_tipo_pagamento()]),
        COLECOES["sessoes_caixa"]: sessoes,
    })


def test_reconciliar_com_a_caixa_a_meio_de_um_fecho_e_recusado(monkeypatch):
    """A recusa, e a razão dela: enquanto a marca lá está não se sabe de que
    lado do Z esta venda vai cair, e escrever à mesma põe os mesmos euros nos
    dois sítios. Esperar resolve tudo — um fecho dura três escritas locais."""
    db = _db_reconciliacao(sessao_estado="a_fechar", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99))

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "está a FECHAR o turno" in excinfo.value.detail
    # NADA foi escrito: nem documento, nem venda `emitida`, nem marca na
    # sessão — e nem sequer se foi ao Vendus (a recusa é à entrada).
    assert db._coleccoes[COLECOES["documentos"]]._documentos == []
    assert _vendas_de(db)[0]["estado"] == "aberta"
    assert "vendas_ligadas_depois_do_fecho" not in db._coleccoes[COLECOES["sessoes_caixa"]]._documentos[0]
    assert all(c.chamadas_procurar == [] for c in ClienteEmissaoVendusFalso.instancias)


def test_reconciliar_recusa_quando_o_fecho_comeca_DURANTE_a_chamada_ao_vendus(monkeypatch):
    """A pergunta à entrada não chega, e é esta a janela que interessa: entre
    ela e a escrita está uma chamada HTTP ao Vendus — SEGUNDOS — e um fecho
    inteiro cabe lá dentro à vontade. É a releitura imediatamente antes de
    escrever que fecha isto."""
    sessao = _sessao_aberta_doc()
    db = _db_reconciliacao_com_sessoes(ColeccaoFalsa([sessao]), venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _configura_vendus_env(monkeypatch)

    class VendusQueDemoraEOFechoComeca(ClienteEmissaoVendusFalso):
        def procurar_por_referencia_externa(self, external_reference, register_id):
            # A Ana carrega em FECHAR CAIXA enquanto este GET está a caminho.
            sessao["estado"] = "a_fechar"
            return _bruto(total=8.99, numero="FS 2026/77", atcud="ATCUD-REAL")

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", VendusQueDemoraEOFechoComeca)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert excinfo.value.status_code == 409
    assert "está a FECHAR o turno" in excinfo.value.detail
    assert db._coleccoes[COLECOES["documentos"]]._documentos == [], (
        "gravou o documento e passou a venda a `emitida` dentro da marca do fecho"
    )
    assert _vendas_de(db)[0]["estado"] == "aberta"


def test_reconciliar_com_o_fecho_a_atravessar_a_escrita_diz_que_nao_sabe(monkeypatch):
    """O resto da corrida, o que já não se pode recusar: a caixa não estava a
    fechar quando se escreveu e estava fechada logo a seguir. O fecho lê as
    vendas `emitida` entre a marca e o Z — esta venda tanto pode ter chegado
    a tempo dessa leitura como não, e daqui não há forma de saber.

    As duas respostas fáceis custam dinheiro, uma em cada sentido: dizer que
    o Z não a conta manda acertar euros que já lá estão; dizer que a conta
    esconde euros que faltam. Diz-se que não se sabe e manda-se confirmar no
    próprio Z, que é o único sítio onde a resposta existe."""
    sessoes = SessoesQueMudamNaLeitura([_sessao_aberta_doc()], na_leitura=2,
                                       novo_estado="fechada")
    db = _db_reconciliacao_com_sessoes(sessoes, venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99, numero="FS 2026/77"))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["z_por_acertar"] is True
    assert "ao MESMO TEMPO" in resposta["aviso_do_z"]
    assert "ABRA O Z" in resposta["aviso_do_z"]
    assert "assinado SEM ela" not in resposta["aviso_do_z"], (
        "afirmou que o Z não conta a venda sem ter como saber"
    )
    # E fica GRAVADO que esta marca é para confirmar, não para acertar às
    # cegas — quem a ler daqui a um mês tem de saber a diferença.
    marca = sessoes._documentos[0]["vendas_ligadas_depois_do_fecho"][0]
    assert marca["fecho_ao_mesmo_tempo"] is True


def test_reconciliar_sem_fecho_nenhum_pelo_meio_continua_a_dar_a_resposta_exacta(monkeypatch):
    """O outro lado: sem corrida nenhuma, a resposta é a de sempre — exacta,
    com o valor que falta na gaveta. O aviso do "não sei" é para a corrida, e
    só para ela."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _vendus_que_tem(monkeypatch, _bruto(total=8.99, numero="FS 2026/77"))

    resposta = _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert resposta["z_por_acertar"] is True
    assert "assinado SEM ela" in resposta["aviso_do_z"]
    assert "ao MESMO TEMPO" not in resposta["aviso_do_z"]
    assert resposta["dinheiro_por_acertar"] == 4.50
    marca = db._coleccoes[COLECOES["sessoes_caixa"]]._documentos[0][
        "vendas_ligadas_depois_do_fecho"][0]
    assert marca["fecho_ao_mesmo_tempo"] is False


def test_reconciliar_com_uma_resposta_ilegivel_do_vendus_da_502_e_nao_500(monkeypatch):
    """O outro lado do erro tipado, visto da rota: uma leitura que não se
    consegue ler NÃO é um "não existe" nem um 500. Um `ValueError` cru
    (`amount_gross='8,99'`) saltava o `except VendusErro` desta rota inteira
    e o FastAPI devolvia 500, deixando a venda `aberta`, sem documento e com
    a reserva ainda incerta — o ecrã lê isso como "nada saiu, pode repetir"."""
    db = _db_reconciliacao(sessao_estado="fechada", venda=_venda_paga_misto())
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    _configura_vendus_env(monkeypatch)

    class VendusComTotalIlegivel(ClienteEmissaoVendusFalso):
        def procurar_por_referencia_externa(self, external_reference, register_id):
            raise VendusRespostaIlegivel(
                "O Vendus devolveu um total (`amount_gross`) que não é um "
                "número legível: '8,99'"
            )

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", VendusComTotalIlegivel)
    ClienteEmissaoVendusFalso.instancias.clear()

    with pytest.raises(HTTPException) as excinfo:
        _corre(reconciliar_reserva_presa("venda-1", None, gestor={"email": "x"}))

    assert excinfo.value.status_code == 502
    assert "volte a tentar" in excinfo.value.detail
    assert db._coleccoes[COLECOES["documentos"]]._documentos == []
    assert _vendas_de(db)[0]["estado"] == "aberta"
    # A reserva mantém-se incerta: continua a obrigar quem vier a seguir a
    # verificar antes de emitir seja o que for.
    assert _refs_de(db)[0]["incerta"] is True


# ============================================================================
# A `ext_ref` repete-se: as escritas do NÚCLEO também prendem a identidade
# ============================================================================
#
# A sexta revisão fechou os dois últimos sítios do núcleo em que uma escrita
# prendia a FORMA (`{"ext_ref": ...}` e mais nada) e não a IDENTIDADE da
# reserva: `_libertar_reserva` e `_marcar_reserva_incerta`. Mais um terceiro,
# que nem sequer se via: o carimbo do `documento_id` em
# `_ligar_venda_ao_documento`.
#
# A `ext_ref` é determinística (`pos-{loja}-{sessão}-{venda}`) — é isso que a
# torna útil para a idempotência e é exactamente isso que a impede de ser
# única NO TEMPO: apagada uma reserva, a tentativa seguinte cria outra
# rigorosamente igual. Entre GANHAR a reserva e chegar a estas escritas podem
# ter passado ~300 s de rede.
#
# Reproduzido em processo, sobre as rotas reais: reserva `incerta` das 20h;
# FINALIZAR nº1 reclama a retoma e fica pendurado no Vendus; o gestor liberta
# (a reserva CERTA — era mesmo aquela que ele viu); FINALIZAR nº2 ganha uma
# reserva NOVA e está a EMITIR; a retoma nº1 acorda com o timeout e liberta
# «a reserva da ext_ref», que já é a NOVA; FINALIZAR nº3 emite outra vez →
# «EMISSÕES REAIS pedidas ao Vendus -> 2 ['FS 2026/901', 'FS 2026/902']».
# Na variante irmã, em vez de apagar marca-a `incerta` — e o FINALIZAR
# seguinte sente-se autorizado a retomá-la: também duas FS reais.

from faturacao.fiscal import (  # noqa: E402
    _libertar_reserva,
    _ligar_venda_ao_documento,
    _marcar_reserva_incerta,
)

_REF_ID = "pos-loja-1-sessao-1-venda-1"


def _reserva_nova_de_outra_tentativa(**over):
    """A reserva que a tentativa SEGUINTE criou: mesma `ext_ref`, mesma
    venda, sem marca nenhuma — e com uma emissão real a caminho do Vendus."""
    r = {"id": "r-nova", "ext_ref": _REF_ID, "venda_id": "venda-1",
         "criado_em": _agora_iso(1)}
    r.update(over)
    return r


def test_libertar_reserva_nao_apaga_a_de_outra_tentativa():
    """A reserva que está na `ext_ref` já não é a de quem chama: não se apaga
    NADA. Apagá-la era destrancar a conta debaixo de uma emissão em voo — e a
    tentativa seguinte reservava e emitia a SEGUNDA Fatura Simplificada."""
    db = _db(vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva_nova_de_outra_tentativa()])

    assert _corre(_libertar_reserva(db, _REF_ID, "r-velha")) is False
    assert [r["id"] for r in _refs_de(db)] == ["r-nova"]


def test_libertar_reserva_apaga_a_sua():
    """O outro lado, para o `id` no filtro não virar uma reserva que nunca
    mais se liberta: com a sua reserva lá, apaga-a e diz que a apagou."""
    db = _db(vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva_nova_de_outra_tentativa(id="r-minha")])

    assert _corre(_libertar_reserva(db, _REF_ID, "r-minha")) is True
    assert _refs_de(db) == []


def test_marcar_incerta_nao_marca_a_de_outra_tentativa():
    """O simétrico do apagar, e o mais insidioso dos dois: `incerta` é um
    convite escrito à tentativa seguinte para RETOMAR a reserva — marcá-la
    numa reserva alheia é autorizar uma emissão por cima de uma FS que pode
    estar a nascer neste instante."""
    db = _db(vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva_nova_de_outra_tentativa()])

    assert _corre(_marcar_reserva_incerta(db, _REF_ID, "r-velha")) is False
    assert "incerta" not in _refs_de(db)[0]


def test_marcar_incerta_marca_a_sua():
    db = _db(vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva_nova_de_outra_tentativa(id="r-minha")])

    assert _corre(_marcar_reserva_incerta(db, _REF_ID, "r-minha")) is True
    assert _refs_de(db)[0]["incerta"] is True


def test_carimbo_do_documento_nao_cai_na_reserva_de_outra_tentativa():
    """O terceiro sítio, o que não dá erro nenhum: o campo `documento_id`
    diz "o documento que saiu DESTA reserva". Carimbado na reserva de outra
    tentativa (que pode estar a falar com o Vendus neste instante) passa a
    dizer uma mentira — e é por ele que `listar_reservas_presas` faz a
    primeira triagem, e é ele que um gestor lê quando vai perceber, semanas
    depois, que documento é que saiu de que tentativa.

    A venda fica `emitida` à mesma: essa escrita é incondicional de propósito
    (ver `_gravar_documento`) e é o estado verdadeiro de quem tem um
    documento fiscal em mãos."""
    db = _db(vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva_nova_de_outra_tentativa()])

    _corre(_ligar_venda_ao_documento(
        db, _REF_ID, "venda-1", {"id": "doc-desta"}, reserva_id="r-velha"))

    assert "documento_id" not in _refs_de(db)[0]
    assert _vendas_de(db)[0]["estado"] == "emitida"


def test_carimbo_do_documento_marca_a_sua_reserva():
    """O outro lado, para o `id` no filtro não deixar a marca de fora sempre:
    com a sua reserva lá, o carimbo é escrito — e é ele que a tira da
    listagem de presas."""
    db = _db(vendas=[_venda(linhas=[_linha()])],
             refs=[_reserva_nova_de_outra_tentativa(id="r-minha")])

    _corre(_ligar_venda_ao_documento(
        db, _REF_ID, "venda-1", {"id": "doc-desta"}, reserva_id="r-minha"))

    assert _refs_de(db)[0]["documento_id"] == "doc-desta"


def test_emissao_que_falha_com_a_reserva_ja_substituida_nao_apaga_a_da_outra():
    """A coreografia inteira, pelo caminho real (`finalizar_venda`): esta
    tentativa ganha a reserva, e enquanto fala com o Vendus a reserva dela
    desaparece (o gestor libertou-a) e é substituída por outra, de uma
    tentativa NOVA que está a emitir. O Vendus recusa ESTA com um 400 — prova
    de que nada saiu, o caminho que liberta a reserva. O que não pode
    acontecer é a reserva da OUTRA ir com ela."""
    db = _db(vendas=[_venda(linhas=[_linha()])])

    async def emitir(_ref):
        # O que acontece durante os segundos de rede: a reserva desta
        # tentativa é libertada e a seguinte cria a sua, com a MESMA ext_ref.
        refs = _refs_de(db)
        del refs[:]
        refs.append(_reserva_nova_de_outra_tentativa())
        raise VendusHTTPErro(400, "dados inválidos")

    async def verificar(_ref):
        raise AssertionError("um 400 não é timeout — não se verifica")

    with pytest.raises(VendusHTTPErro):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir, verificar, esperar=_instantaneo))

    assert [r["id"] for r in _refs_de(db)] == ["r-nova"], (
        "a emissão em voo ficou sem reserva — a próxima tentativa emitia a 2.ª FS"
    )


def test_retoma_que_perde_a_sua_reserva_a_meio_nao_emite_nada():
    """A retoma reclama (e ganha), e a reserva que ela reclamou desaparece
    antes de ela conseguir saber QUAL era. Sem identidade não se emite às
    cegas por cima de uma `ext_ref` cujo dono já não se sabe qual é: cai-se no
    caminho de quem não tem reserva. Zero chamadas ao Vendus."""

    class RefsQueSomemDepoisDeReclamadas(ColeccaoFalsa):
        async def update_one(self, filtro, atualizacao):
            resultado = await super().update_one(filtro, atualizacao)
            if atualizacao.get("$set", {}).get("em_retoma") is True:
                del self._documentos[:]
            return resultado

    db = DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa([_venda(linhas=[_linha()])]),
        COLECOES["documentos"]: ColeccaoFalsa(
            None, indices_unicos=_unicos_de("fat_documentos")),
        COLECOES["refs_fiscais"]: RefsQueSomemDepoisDeReclamadas(
            [_reserva_incerta_antiga()],
            indices_unicos=_unicos_de("fat_refs_fiscais")),
        COLECOES["sessoes_caixa"]: ColeccaoFalsa([_sessao_aberta_doc()]),
    })

    async def emitir(_ref):
        raise AssertionError("não se emite sem se saber qual é a reserva")

    async def verificar(_ref):
        raise AssertionError("nem se verifica: a retoma nem chegou a começar")

    with pytest.raises(EmissaoEmCurso):
        _corre(finalizar_venda(
            db, _venda(linhas=[_linha()]), emitir, verificar,
            esperar=_instantaneo, tentativas_espera=1))

    assert db._coleccoes[COLECOES["documentos"]]._documentos == []
