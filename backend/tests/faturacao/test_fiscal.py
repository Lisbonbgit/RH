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


# --- Duplo de base de dados, com uniqueness REAL ------------------------------


def _corresponde(item, filtro):
    if not filtro:
        return True
    return all(item.get(chave) == valor for chave, valor in filtro.items())


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
        return None


class DbFalsa:
    def __init__(self, coleccoes):
        self._coleccoes = coleccoes

    def __getitem__(self, nome):
        return self._coleccoes[nome]


def _db(vendas=None, documentos=None, refs=None, tipos_pagamento=None):
    return DbFalsa({
        COLECOES["vendas"]: ColeccaoFalsa(vendas),
        COLECOES["documentos"]: ColeccaoFalsa(documentos, indices_unicos=["vendus_document_id", "atcud"]),
        COLECOES["refs_fiscais"]: ColeccaoFalsa(refs, indices_unicos=["ext_ref"]),
        COLECOES["tipos_pagamento"]: ColeccaoFalsa(tipos_pagamento),
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


# --- Itens Vendus, com o desconto GLOBAL dobrado por linha --------------------
#
# O Vendus só aceita um desconto por linha (€ OU %) e não há um desconto
# fiável ao nível do documento inteiro independente do recurso de "cartões
# de desconto" (ver o relatório da tarefa) — por isso o desconto GLOBAL da
# venda tem de se dobrar dentro do desconto de CADA linha, como uma única
# discount_percentage. Mesmo raciocínio do `combine_global` da Pizzaria
# (~/dev/pizzaria/backend/pos/pricing.py), já validado em produção:
# composição multiplicativa, o global aplica-se sempre por cima do da linha.


def test_itens_vendus_sem_nenhum_desconto():
    venda = _venda(linhas=[_linha(quantidade=2)])
    itens = _itens_vendus(venda)
    assert itens == [{"title": "Açaí Regular", "qty": 2, "gross_price": 8.99, "tax_id": "INT"}]


def test_itens_vendus_mantem_o_desconto_proprio_da_linha_sem_desconto_global():
    venda = _venda(linhas=[_linha(desconto_pct=10)])
    itens = _itens_vendus(venda)
    assert itens[0]["discount_percentage"] == 10.0


def _liquido_dos_itens(itens):
    """O líquido que o Vendus calcularia destes itens: soma de
    qty*gross_price*(1-discount_percentage/100), arredondado a 2 casas —
    usado para provar que _itens_vendus produz um total que bate com
    venda._totais (a MESMA fonte de verdade dos totais mostrados no ecrã),
    nunca uma soma inventada à parte (mesma regra de ouro do Task 2)."""
    total = 0.0
    for it in itens:
        gross = it["qty"] * it["gross_price"]
        pct = it.get("discount_percentage", 0.0)
        total += gross * (1 - pct / 100.0)
    return round(total, 2)


def test_itens_vendus_com_desconto_global_percentagem_sem_desconto_de_linha():
    """Uma linha sem desconto próprio recebe uma discount_percentage tal que
    o líquido resultante bate com venda._totais — não um número
    hard-coded (o desconto global já passou por um arredondamento a
    cêntimos dentro de _desconto_global_eur, por isso a percentagem
    equivalente NÃO é exactamente 10.0, é a que reproduz esse cêntimo)."""
    venda = _venda(linhas=[_linha()], desconto_global_pct=10)
    itens = _itens_vendus(venda)
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_com_desconto_global_em_euros_bate_com_totais():
    venda = _venda(linhas=[_linha()], desconto_global_eur=2.0)
    itens = _itens_vendus(venda)
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_combina_desconto_de_linha_com_desconto_global_multiplicativamente():
    """10% na linha + 10% global não é 20% (soma), é composição
    multiplicativa — 1-(1-0.1)(1-0.1) ≈ 19%, nunca 20%."""
    venda = _venda(linhas=[_linha(desconto_pct=10)], desconto_global_pct=10)
    itens = _itens_vendus(venda)
    assert itens[0]["discount_percentage"] < 20.0
    assert itens[0]["discount_percentage"] == pytest.approx(19.0, abs=0.05)
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_com_desconto_de_linha_em_euros_e_global_em_percentagem():
    venda = _venda(linhas=[_linha(desconto_eur=1.0)], desconto_global_pct=10)
    itens = _itens_vendus(venda)
    assert _liquido_dos_itens(itens) == _totais(venda)["total"]


def test_itens_vendus_com_duas_linhas_e_desconto_global_aplica_a_ambas():
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
    assert itens[0]["discount_percentage"] == pytest.approx(10.0, abs=0.05)
    assert itens[1]["discount_percentage"] == pytest.approx(10.0, abs=0.05)
    assert itens[1]["title"] == "Sumo"
    assert abs(_liquido_dos_itens(itens) - _totais(venda)["total"]) <= 0.02  # tolerância de arredondamento por linha


def test_itens_vendus_sem_desconto_algum_nao_tem_discount_percentage():
    venda = _venda(linhas=[_linha()])
    itens = _itens_vendus(venda)
    assert "discount_percentage" not in itens[0]
    assert "discount_amount" not in itens[0]


def test_itens_vendus_venda_sem_linhas_devolve_lista_vazia():
    assert _itens_vendus(_venda(linhas=[])) == []


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


def test_verificacao_apos_timeout_e_uma_so_chamada_nunca_um_varrimento():
    """A defesa explícita do brief: nunca 'emitir à mesma se a consulta de
    verificação rebentar', e a verificação em si é UMA chamada exacta — não
    há aqui espaço para um varrimento de dias/páginas, o contrato é UM único
    `await verificar(ext_ref)`."""
    db = _db(vendas=[_venda()])

    async def emitir(ref):
        raise VendusIndisponivel("timeout simulado")

    contagem = {"chamadas": 0}

    async def verificar(ref):
        contagem["chamadas"] += 1
        raise VendusIndisponivel("a própria verificação também rebentou")

    with pytest.raises(VendusIndisponivel):
        _corre(finalizar_venda(db, _venda(), emitir, verificar, esperar=_instantaneo))

    assert contagem["chamadas"] == 1  # nunca insiste a verificar às cegas
    assert db[COLECOES["refs_fiscais"]]._documentos == []  # reserva libertada


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


def test_verificar_feliz_bate_certo_nao_diz_nada(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(tipos_pagamento=[_tipo_pagamento()])
    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", ClienteEmissaoVendusFalso)
    ClienteEmissaoVendusFalso.instancias.clear()

    def fabrica(chave):
        cliente = ClienteEmissaoVendusFalso(chave)
        cliente.listar_documentos_por_dia = lambda data, register_id: [_doc_vendus()]
        return cliente

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", fabrica)

    resultado = _corre(verificar_vendas_dinheiro_no_vendus(db, _sessao_fake(), 8.99))
    assert resultado is None


def test_verificar_feliz_nao_bate_avisa(monkeypatch):
    _configura_vendus_env(monkeypatch)
    db = _db(tipos_pagamento=[_tipo_pagamento()])

    def fabrica(chave):
        cliente = ClienteEmissaoVendusFalso(chave)
        cliente.listar_documentos_por_dia = lambda data, register_id: [_doc_vendus()]
        return cliente

    monkeypatch.setattr(fiscal_mod, "ClienteEmissaoVendus", fabrica)

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
