"""**Como correu a gaveta de cada loja** — a vista do backoffice.

O dono mostrou os Movimentos de Caixa do Vendus e pediu o mesmo. O que se
mede aqui é sobretudo que este ecrã NÃO inventa uma segunda contabilidade: os
números de um turno têm de ser exactamente os do Z desse turno, porque saem da
MESMA função (`caixa._resumo_do_turno`). Um relatório que discorde do papel
que a funcionária assinou é pior do que não existir — obriga a escolher em
qual acreditar.

E duas coisas que o Vendus não faz, e que aqui são propositadas:

- o Vendus mostra «Fecho de Caixa = abertura + entradas em numerário», que é o
  ESPERADO. Ele não sabe quanto a funcionária contou. Nós sabemos, e é o
  contado — com a diferença — que responde à pergunta que interessa;
- o Vendus deixa ALTERAR a abertura e o fecho. Aqui não há por onde: um Z
  assinado é o retrato de um instante, e reescrevê-lo destrói a única prova de
  que a gaveta bateu certo nesse dia.
"""
import asyncio

import pytest
from fastapi import HTTPException

from faturacao import historico_caixa as hist


def _corre(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Coleccao:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.filtros = []

    def _casa(self, doc, filtro):
        for chave, valor in (filtro or {}).items():
            if isinstance(valor, dict):
                if "$gte" in valor and str(doc.get(chave) or "") < valor["$gte"]:
                    return False
                if "$lte" in valor and str(doc.get(chave) or "") > valor["$lte"]:
                    return False
                if "$in" in valor and doc.get(chave) not in valor["$in"]:
                    return False
            elif doc.get(chave) != valor:
                return False
        return True

    def find(self, filtro=None, projecao=None):
        self.filtros.append(filtro)
        return _Cursor([d for d in self.docs if self._casa(d, filtro)])

    async def find_one(self, filtro, projecao=None):
        for d in self.docs:
            if self._casa(d, filtro):
                return dict(d)
        return None


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, campo, direcao=1):
        # O `sort` do duplo tinha de ORDENAR mesmo: enquanto era um `return
        # self`, o teste da ordem passava com o código a devolver o que lhe
        # apetecesse. Medido — foi o que aconteceu à primeira.
        self._docs = sorted(self._docs, key=lambda d: str(d.get(campo) or ""),
                            reverse=(direcao == -1))
        return self

    async def to_list(self, limite):
        return [dict(d) for d in self._docs[:limite]]


class _Db:
    def __init__(self, colecoes):
        self.colecoes = colecoes

    def __getitem__(self, nome):
        return self.colecoes.setdefault(nome, _Coleccao())


def _pagamento(nome, valor):
    return {"tipo_pagamento_id": nome.lower(), "nome": nome, "valor": valor,
            "tipo_fiscal": "NU" if nome == "Dinheiro" else "CD"}


def _linha(nome, quantidade=1, preco=8.99, opcoes=None):
    return {"produto_nome": nome, "quantidade": quantidade, "produto_preco": preco,
            "produto_tax_id": "INT", "opcoes": opcoes or []}


def _venda(sessao_id, loja_id, pagamentos, linhas=None):
    return {"id": "v-%s" % sessao_id, "sessao_id": sessao_id, "loja_id": loja_id,
            "estado": "emitida", "pagamentos": pagamentos, "linhas": linhas or []}


def _sessao(id_, loja_id="l1", fundo=50.0, contado=None, estado="fechada",
            aberta="2026-08-26T11:21:00+00:00", fechada="2026-08-26T20:56:00+00:00"):
    return {"id": id_, "loja_id": loja_id, "caixa_id": "c1", "fundo": fundo,
            "estado": estado, "contado": contado,
            "aberta_em": aberta, "fechada_em": fechada if estado == "fechada" else None,
            "aberta_por": {"nome": "Wallison Rodrigues"},
            "fechada_por": {"nome": "Wallison Rodrigues"} if estado == "fechada" else None}


def _movimento(sessao_id, tipo, valor, motivo=None, por="Wallison Rodrigues"):
    return {"id": "m-%s-%s" % (sessao_id, valor), "sessao_id": sessao_id, "tipo": tipo,
            "valor": valor, "motivo": motivo, "por": {"nome": por},
            "em": "2026-08-26T15:00:00+00:00"}


def _db(sessoes=(), vendas=(), movimentos=(), lojas=None, caixas=None):
    from faturacao.db import COLECOES
    return _Db({
        COLECOES["sessoes_caixa"]: _Coleccao(sessoes),
        COLECOES["vendas"]: _Coleccao(vendas),
        COLECOES["movimentos_caixa"]: _Coleccao(movimentos),
        COLECOES["notas_credito"]: _Coleccao([]),
        COLECOES["lojas"]: _Coleccao(lojas or [{"id": "l1", "nome": "L'açaí Algueirão"},
                                               {"id": "l2", "nome": "L'açaí Oeiras"}]),
        COLECOES["caixas"]: _Coleccao(caixas or [{"id": "c1", "loja_id": "l1",
                                                  "nome": "Caixa Algueirão"}]),
    })


# --- A lista -----------------------------------------------------------------


def test_a_lista_traz_a_abertura_e_o_fecho_de_cada_turno(monkeypatch):
    db = _db(sessoes=[_sessao("s1", fundo=50.60, contado=70.85)],
             vendas=[_venda("s1", "l1", [_pagamento("Dinheiro", 20.25)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    turnos = _corre(hist.historico(loja_id=None, de=None, ate=None, _={}))
    assert len(turnos) == 1
    t = turnos[0]
    assert t["loja_nome"] == "L'açaí Algueirão"
    assert t["abertura"]["valor"] == 50.60
    assert t["abertura"]["por"] == "Wallison Rodrigues"
    assert t["fecho"]["contado"] == 70.85


def test_o_esperado_e_o_CONTADO_vem_os_DOIS(monkeypatch):
    """O Vendus mostra só o esperado («abertura + entradas em numerário») —
    ele não sabe quanto a funcionária contou. É o contado que responde à
    pergunta que interessa, e a diferença entre os dois."""
    db = _db(sessoes=[_sessao("s1", fundo=50.0, contado=68.0)],
             vendas=[_venda("s1", "l1", [_pagamento("Dinheiro", 20.0)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    fecho = _corre(hist.historico(loja_id=None, de=None, ate=None, _={}))[0]["fecho"]
    assert fecho["esperado"] == 70.0     # 50 de fundo + 20 em dinheiro
    assert fecho["contado"] == 68.0
    assert fecho["diferenca"] == -2.0


def test_um_turno_ABERTO_nao_inventa_contado_nenhum(monkeypatch):
    db = _db(sessoes=[_sessao("s1", estado="aberta")],
             vendas=[_venda("s1", "l1", [_pagamento("Dinheiro", 20.0)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    t = _corre(hist.historico(loja_id=None, de=None, ate=None, _={}))[0]
    assert t["fecho"]["estado"] == "aberto"
    assert t["fecho"]["contado"] is None
    assert t["fecho"]["diferenca"] is None


def test_a_FATURACAO_do_turno_aparece_em_destaque(monkeypatch):
    """É o número grande do cartão, como no Vendus."""
    db = _db(sessoes=[_sessao("s1", contado=70.0)],
             vendas=[_venda("s1", "l1", [_pagamento("Dinheiro", 12.0),
                                         _pagamento("Multibanco", 8.25)],
                            linhas=[_linha("Açaí", 1, 20.25)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    assert _corre(hist.historico(loja_id=None, de=None, ate=None, _={}))[0]["faturacao"] == 20.25


def test_o_filtro_de_LOJA_nao_deixa_passar_turnos_de_outra(monkeypatch):
    db = _db(sessoes=[_sessao("s1", loja_id="l1", contado=50.0),
                      _sessao("s2", loja_id="l2", contado=50.0)])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    turnos = _corre(hist.historico(loja_id="l2", de=None, ate=None, _={}))
    assert [t["id"] for t in turnos] == ["s2"]


def test_os_turnos_vem_do_MAIS_RECENTE_para_o_mais_antigo(monkeypatch):
    """É o de hoje que se procura, e não o de há três semanas."""
    db = _db(sessoes=[
        _sessao("velho", aberta="2026-08-20T11:00:00+00:00", contado=1.0),
        _sessao("novo", aberta="2026-08-26T11:00:00+00:00", contado=1.0)])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    assert [t["id"] for t in _corre(hist.historico(
        loja_id=None, de=None, ate=None, _={}))] == ["novo", "velho"]


# --- O detalhe ---------------------------------------------------------------


def test_o_detalhe_traz_a_LISTA_dos_movimentos_com_motivo_e_autor(monkeypatch):
    """O que o Vendus mostra sem dizer quem — e é o quem que interessa quando
    saíram 30 € da gaveta."""
    db = _db(sessoes=[_sessao("s1", contado=50.0)],
             movimentos=[_movimento("s1", "saida", 30.0, "Compra de guardanapos"),
                         _movimento("s1", "entrada", 20.0)])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    d = _corre(hist.detalhe_do_turno("s1", _={}))
    saida = next(m for m in d["movimentos"] if m["tipo"] == "saida")
    assert saida["valor"] == 30.0
    assert saida["motivo"] == "Compra de guardanapos"
    assert saida["por"] == "Wallison Rodrigues"


def test_o_detalhe_traz_os_PRODUTOS_vendidos_com_os_tamanhos(monkeypatch):
    db = _db(sessoes=[_sessao("s1", contado=50.0)],
             vendas=[_venda("s1", "l1", [_pagamento("Dinheiro", 20.0)], linhas=[
                 _linha("Açaí", 3, opcoes=[{"grupo_nome": "Tamanho", "nome": "Small"}]),
                 _linha("Água", 2)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    artigos = _corre(hist.detalhe_do_turno("s1", _={}))["artigos"]
    acai = next(a for a in artigos if a["nome"] == "Açaí")
    assert acai["quantidade"] == 3
    assert [v["nome"] for v in acai["variantes"]] == ["Small"]


def test_o_detalhe_traz_os_pagamentos_e_o_MAPA_DE_IMPOSTOS(monkeypatch):
    db = _db(sessoes=[_sessao("s1", contado=50.0)],
             vendas=[_venda("s1", "l1", [_pagamento("Multibanco", 11.30)],
                            linhas=[_linha("Açaí", 1, 11.30)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    d = _corre(hist.detalhe_do_turno("s1", _={}))
    assert d["pagamentos"][0]["nome"] == "Multibanco"
    assert d["mapa_imposto"]
    assert d["total_faturado"] == 11.30


def test_os_numeros_do_detalhe_SAO_OS_MESMOS_do_Z(monkeypatch):
    """**O guarda central.** Este ecrã e o papel que a funcionária assinou têm
    de dizer o mesmo, ao cêntimo — saem da mesma função. Um relatório que
    discorde do Z obriga alguém a escolher em qual acreditar, e essa escolha
    nunca é informada."""
    from faturacao.caixa import _resumo_do_turno
    sessao = _sessao("s1", fundo=50.0, contado=68.0)
    vendas = [_venda("s1", "l1", [_pagamento("Dinheiro", 20.0)],
                     linhas=[_linha("Açaí", 1, 20.0)])]
    movimentos = [_movimento("s1", "saida", 2.0, "Troco")]
    db = _db(sessoes=[sessao], vendas=vendas, movimentos=movimentos)
    monkeypatch.setattr(hist, "obter_db", lambda: db)

    do_ecra = _corre(hist.detalhe_do_turno("s1", _={}))
    do_z = _resumo_do_turno(sessao, movimentos, vendas, [])
    for campo in ("esperado", "entradas", "saidas", "total_faturado",
                  "base_tributavel", "iva_total", "vendas_dinheiro"):
        assert do_ecra[campo] == do_z[campo], campo
    assert do_ecra["pagamentos"] == do_z["pagamentos"]


def test_um_turno_que_nao_existe_da_404(monkeypatch):
    monkeypatch.setattr(hist, "obter_db", lambda: _db())
    with pytest.raises(HTTPException) as e:
        _corre(hist.detalhe_do_turno("nao-existe", _={}))
    assert e.value.status_code == 404


# --- As portas ---------------------------------------------------------------


def test_as_rotas_do_historico_EXIGEM_gestor():
    """São os números de dinheiro de todas as lojas — não se servem a um
    dispositivo do balcão."""
    from faturacao import router
    from faturacao.auth import gestor_atual
    from faturacao.pos_auth import dispositivo_atual, operador_atual

    def dependencias(rota):
        encontrados = set()

        def procura(d):
            for filha in d.dependencies:
                encontrados.add(filha.call)
                procura(filha)

        procura(rota.dependant)
        return encontrados

    caminhos = {r.path: r for r in router.routes if hasattr(r, "dependant")}
    for caminho in ("/api/faturacao/caixa/historico",
                    "/api/faturacao/caixa/historico/{sessao_id}"):
        assert caminho in caminhos, caminho
        deps = dependencias(caminhos[caminho])
        assert gestor_atual in deps, caminho
        assert dispositivo_atual not in deps and operador_atual not in deps, caminho


def test_NAO_ha_por_onde_alterar_a_abertura_nem_o_fecho():
    """O Vendus tem botões «Alterar» nos dois. Aqui não: um Z assinado é o
    retrato de um instante, e reescrevê-lo destrói a única prova de que a
    gaveta bateu certo nesse dia. Corrige-se com um movimento, que fica com o
    nome de quem o fez."""
    from faturacao import router
    escritas = [r.path for r in router.routes
                if "historico" in r.path
                and {"POST", "PUT", "PATCH", "DELETE"} & set(getattr(r, "methods", ()))]
    assert escritas == [], escritas


# --- Os dois casos que só a mutação revelou ---------------------------------


def test_um_turno_aberto_com_um_contado_VELHO_ignora_o(monkeypatch):
    """Hoje este estado não se alcança: o fecho grava `estado` e `contado` na
    MESMA escrita, e não há reabrir caixa. O guarda fica na mesma, e o teste
    existe para o tornar observável — no dia em que houver um «reabrir», ou um
    fecho que falhe a meio, o ecrã não pode mostrar como contagem de hoje um
    número que alguém contou ontem.

    Sem este teste a condição era invisível: mutei-a para deixar passar o
    contado e NENHUM teste ficou vermelho."""
    sessao = _sessao("s1", estado="aberta")
    sessao["contado"] = 999.0          # sobra de um fecho que não terminou
    db = _db(sessoes=[sessao],
             vendas=[_venda("s1", "l1", [_pagamento("Dinheiro", 20.0)])])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    fecho = _corre(hist.historico(loja_id=None, de=None, ate=None, _={}))[0]["fecho"]
    assert fecho["contado"] is None, "Mostrou uma contagem que ninguém fez neste turno."
    assert fecho["diferenca"] is None


def test_um_movimento_POR_CONFIRMAR_nao_aparece_na_lista(monkeypatch):
    """Um movimento `por_confirmar` nunca chegou a ser dinheiro: perdeu a
    corrida contra o fecho e não entrou em soma nenhuma (ver
    `caixa.registar_movimento`). Listá-lo aqui punha no ecrã uma saída de
    dinheiro que o Z não conhece — e alguém a procurar 30 € que nunca saíram.

    Também só a mutação o apanhou: o teste anterior não criava nenhum."""
    db = _db(sessoes=[_sessao("s1", contado=50.0)], movimentos=[
        _movimento("s1", "saida", 30.0, "Compra de guardanapos"),
        dict(_movimento("s1", "saida", 99.0, "Perdeu a corrida"), por_confirmar=True),
    ])
    monkeypatch.setattr(hist, "obter_db", lambda: db)
    valores = [m["valor"] for m in _corre(hist.detalhe_do_turno("s1", _={}))["movimentos"]]
    assert valores == [30.0], valores
