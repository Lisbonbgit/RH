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
import asyncio

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


def _corresponde(item, filtro):
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


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


class CursorFalso:
    def __init__(self, itens):
        self._itens = itens

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, n=None):
        return self._itens


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
        return CursorFalso([d for d in self._documentos if _corresponde(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        await asyncio.sleep(0)
        encontrados = [d for d in self._documentos if _corresponde(d, filtro)]
        return encontrados[0] if encontrados else None

    async def insert_one(self, doc):
        await asyncio.sleep(0)  # ponto de "corrida" — simula I/O real
        for campo in self._indices_unicos:
            valor = doc.get(campo)
            if valor is not None and any(d.get(campo) == valor for d in self._documentos):
                raise DuplicateKeyError("chave duplicada: %s=%r" % (campo, valor))
        self.chamadas_insert += 1
        self._documentos.append(dict(doc))
        return None

    async def delete_one(self, filtro):
        await asyncio.sleep(0)
        alvo = next((d for d in self._documentos if _corresponde(d, filtro)), None)
        if alvo is not None:
            self._documentos.remove(alvo)
        return None

    async def update_one(self, filtro, atualizacao):
        await asyncio.sleep(0)
        alvos = [d for d in self._documentos if _corresponde(d, filtro)]
        if alvos:
            alvos[0].update(atualizacao.get("$set", {}))
        return ResultadoUpdateFalso(matched_count=len(alvos))


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes[nome]


def _db(vendas=None, documentos=None, refs=None, tipos_pagamento=None, sessoes=None):
    # Por omissão, uma sessão ABERTA "sessao-1" — o sessao_id da _venda()
    # por omissão — para os testes que não são sobre a sessão de caixa (a
    # maioria) não terem de a passar sempre à mão (I1: finalizar recusa
    # emitir contra uma sessão fechada, ver os testes dedicados a isso).
    if sessoes is None:
        sessoes = [{"id": "sessao-1", "loja_id": "loja-1", "caixa_id": "caixa-1", "estado": "aberta"}]
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(vendas),
        COLECOES["documentos"]: ColeccaoFalsa(documentos, indices_unicos=["vendus_document_id", "atcud"]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(refs, indices_unicos=["ext_ref"]),
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
# B1: rota de gestão — listar reservas incertas (nunca há saída nem
# visibilidade hoje: se o Vendus ficar em baixo, a venda fica presa em 503;
# quando o turno fecha, passa a ser recusada para sempre (I1) e o dinheiro
# fica sem Z nenhum — a única saída era mexer no Mongo à mão. Esta rota dá
# por onde começar a investigar.)
# ============================================================================

from faturacao.fiscal import listar_reservas_incertas  # noqa: E402


def test_lista_reservas_incertas_devolve_so_as_marcadas_incertas(monkeypatch):
    db = _db(
        vendas=[_venda(id="venda-1", loja_id="loja-1"), _venda(id="venda-2", loja_id="loja-2")],
        refs=[
            {"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
             "incerta": True, "criado_em": "2026-08-15T09:00:00+00:00"},
            {"id": "r2", "ext_ref": "pos-loja-2-sessao-1-venda-2", "venda_id": "venda-2",
             "incerta": False, "criado_em": "2026-08-15T09:00:00+00:00"},
            {"id": "r3", "ext_ref": "pos-loja-1-sessao-1-venda-3", "venda_id": "venda-3"},
        ],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_incertas(_={}))
    assert [r["ext_ref"] for r in resultado] == ["pos-loja-1-sessao-1-venda-1"]


def test_lista_reservas_incertas_inclui_a_loja_da_venda(monkeypatch):
    db = _db(
        vendas=[_venda(id="venda-1", loja_id="loja-3")],
        refs=[{"id": "r1", "ext_ref": "pos-loja-3-sessao-1-venda-1", "venda_id": "venda-1",
               "incerta": True, "criado_em": "2026-08-15T09:00:00+00:00"}],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_incertas(_={}))
    assert resultado[0]["loja_id"] == "loja-3"
    assert resultado[0]["venda_id"] == "venda-1"


def test_lista_reservas_incertas_com_venda_inexistente_nao_rebenta(monkeypatch):
    """Defesa (dados corrompidos, ou uma reserva órfã): a venda referida já
    não existe — a rota não pode rebentar, só devolve loja_id=None."""
    db = _db(
        vendas=[],
        refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
               "incerta": True, "criado_em": "2026-08-15T09:00:00+00:00"}],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_incertas(_={}))
    assert resultado[0]["loja_id"] is None


def test_lista_reservas_incertas_calcula_ha_quanto_tempo_estao_presas(monkeypatch):
    from datetime import datetime, timedelta, timezone
    ha_dez_minutos = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    db = _db(
        vendas=[_venda(id="venda-1", loja_id="loja-1")],
        refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
               "incerta": True, "criado_em": ha_dez_minutos}],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_incertas(_={}))
    assert resultado[0]["presa_ha_segundos"] > 590  # ~10 minutos, com folga


def test_lista_reservas_incertas_diz_se_ja_esta_em_retoma(monkeypatch):
    db = _db(
        vendas=[_venda(id="venda-1", loja_id="loja-1")],
        refs=[{"id": "r1", "ext_ref": "pos-loja-1-sessao-1-venda-1", "venda_id": "venda-1",
               "incerta": True, "em_retoma": True, "criado_em": "2026-08-15T09:00:00+00:00"}],
    )
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    resultado = _corre(listar_reservas_incertas(_={}))
    assert resultado[0]["em_retoma"] is True


def test_lista_reservas_incertas_vazia_quando_nao_ha_nenhuma(monkeypatch):
    db = _db(vendas=[], refs=[])
    monkeypatch.setattr(fiscal_mod, "obter_db", lambda: db)
    assert _corre(listar_reservas_incertas(_={})) == []
