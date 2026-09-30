"""**A loja da app no email das 23:30** — com faturação, sem caixa.

A app L'Açaí cobra por Stripe e as suas Faturas Simplificadas entram no portal
pela sincronização do Vendus: ficam em `fat_documentos` com `origem: "app"`,
numa loja só delas, e **sem venda nenhuma por trás** — sem sessão de caixa, sem
operador, sem gaveta.

O email do dia não pode escrever "Sem turno de caixa aberto neste dia" nem
"Turno ainda aberto" por cima de uma loja que não tem gaveta e nunca vai ter —
isso lê-se como uma acusação a alguém que se esqueceu de fechar. Nem pode
somar a receita da app à repartição por tipo de pagamento das outras cinco, que
existe para se conferir dinheiro CONTADO.

Mas a faturação da app é receita a sério, e por isso entra no número grande.

**A loja da app identifica-se pela definição `sincronizacao_app.loja_id`, e não
por ter documentos com `origem: "app"`.** É a mesma definição que manda a
sincronização gravar lá, e é a única que continua a valer num dia em que a app
não vendeu nada — que é o dia em que o critério pelos documentos falhava
exactamente ao contrário do que interessa, com o email a acusar de gaveta
aberta a única loja que não tem gaveta.
"""
from faturacao.relatorio_diario import montar_relatorio
from faturacao.relatorio_email import _cartao_de_loja, html_do_relatorio

LOJAS = [{"id": "loja-app", "nome": "App Online"},
         {"id": "loja-1", "nome": "L'açaí Belém"}]

DOC_APP = {"id": "d1", "tipo": "FS", "loja_id": "loja-app",
           "emitido_em": "2026-09-01T13:43:25+00:00",
           "total_bruto": 6.85, "total_liquido": 6.06, "origem": "app"}


def _dados(turnos=(), documentos=(DOC_APP,), lojas=LOJAS):
    return montar_relatorio(dia="2026-09-01", ate="23:30", com_iva=True,
                            documentos=list(documentos), lojas=list(lojas),
                            turnos=list(turnos), loja_da_app="loja-app")


def _linha_da_app(**kw):
    return [l for l in _dados(**kw)["lojas"] if l["nome"] == "App Online"][0]


def test_a_loja_da_app_aparece_com_facturacao():
    linha = _linha_da_app()
    assert linha["faturacao"] == 6.85
    assert linha["documentos"] == 1


def test_nao_diz_que_a_loja_da_app_nao_fechou_a_caixa():
    linha = _linha_da_app()
    assert linha["caixa"] is None
    assert linha["sem_vendas"] is False


def test_a_app_nao_entra_na_reparticao_por_tipo_de_pagamento():
    # A app cobra por Stripe: não passa pela gaveta de ninguém. Somá-la aqui
    # punha a repartição a discordar do dinheiro contado nas lojas.
    linha = _linha_da_app()
    assert linha["pagamentos"] == []


def test_a_facturacao_geral_inclui_a_app_na_mesma():
    assert _dados()["geral"]["faturacao"] == 6.85


def test_num_dia_SEM_VENDAS_da_app_a_loja_continua_a_nao_ter_caixa():
    """O dia em que o critério pelos documentos falhava.

    Sem documentos com `origem: "app"` não há por onde reconhecer a loja, e o
    email voltava a acusá-la de não ter fechado a gaveta — precisamente no dia
    em que ela não fez nada.
    """
    linha = _linha_da_app(documentos=())
    assert linha["caixa"] is None
    assert linha["sem_vendas"] is True


def test_uma_loja_A_SERIO_sem_turno_CONTINUA_a_ser_assinalada():
    """A guarda é para a loja da app e mais nenhuma. Uma das cinco lojas com
    gaveta que passe o dia inteiro sem abrir sessão é uma anomalia que o dono
    TEM de ver — tapá-la seria trocar uma mentira por outra."""
    belem = [l for l in _dados()["lojas"] if l["id"] == "loja-1"][0]
    assert belem["caixa"]["estado"] == "sem_turno"


def test_sem_loja_da_app_configurada_nada_muda():
    """O portal viveu meses sem esta definição e as cinco lojas continuam a
    depender de a caixa vir sempre preenchida."""
    r = montar_relatorio(dia="2026-09-01", ate="23:30", lojas=LOJAS,
                         documentos=[DOC_APP], turnos=[])
    assert all(l["caixa"] is not None for l in r["lojas"])


# --- O email desenhado -------------------------------------------------------


def _cartao():
    """O CARTÃO da loja da app, e não o email inteiro.

    O bloco «Caixa · todas as lojas» diz «Sem turno de caixa aberto neste dia»
    quando nenhuma das cinco lojas abriu a gaveta, e nesse caso está certo: é
    sobre as lojas com gaveta, não sobre esta. A pergunta aqui é só se o
    CARTÃO da app acusa alguém.
    """
    return _cartao_de_loja(_linha_da_app(), 6.85)


def test_o_cartao_da_app_NAO_acusa_ninguem_de_nada():
    html = _cartao()
    assert "Sem turno de caixa aberto neste dia" not in html
    assert "Turno ainda aberto" not in html
    # "Sem pagamentos registados" era outra maneira de mentir: a app FOI paga.
    assert "Sem pagamentos registados" not in html


def test_o_cartao_da_app_DIZ_porque_e_que_nao_tem_caixa():
    """Meio cartão em branco lê-se como uma avaria do relatório."""
    assert "sem caixa" in _cartao().lower()


def test_o_email_INTEIRO_mostra_a_loja_da_app_com_o_valor_dela():
    html = html_do_relatorio(_dados())
    assert "App Online" in html
    assert "6,85" in html


def test_o_cartao_de_uma_loja_A_SERIO_sem_turno_CONTINUA_a_assinalar():
    """A metade do cartão que a app perde tem de continuar a existir para
    quem tem gaveta — senão trocou-se uma mentira por outra."""
    belem = [l for l in _dados()["lojas"] if l["id"] == "loja-1"][0]
    assert "Sem turno de caixa aberto neste dia" in _cartao_de_loja(belem, 6.85)


# --- A ligação à definição, na única peça que lê o Mongo ----------------------
#
# O módulo das contas é puro: se ninguém lhe disser qual é a loja da app, a
# guarda acima nunca chega a valer nada em produção. É este par de testes que
# separa "o código está lá" de "o email das 23:30 usa-o".


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **kw):
        return self

    async def to_list(self, limite):
        return list(self._docs)[:limite]


def _casa(doc, filtro):
    """Igualdade e `$gte` — o mínimo que este ficheiro precisa, e o mínimo que
    faz um teste de contagem valer alguma coisa. Sem isto, `_Coleccao` devolvia
    tudo a qualquer filtro e a contagem das faturas por email ficava verde com
    o tipo errado, com o campo de data errado, ou sem filtro nenhum."""
    for chave, valor in (filtro or {}).items():
        atual = doc.get(chave)
        if isinstance(valor, dict) and "$gte" in valor:
            if atual is None or not atual >= valor["$gte"]:
                return False
        elif atual != valor:
            return False
    return True


class _Coleccao:
    def __init__(self, docs=(), por_id=None):
        self._docs = list(docs)
        self._por_id = por_id or {}

    async def find_one(self, filtro, projeccao=None):
        return self._por_id.get(filtro.get("id"))

    def find(self, filtro=None, projeccao=None):
        return _Cursor([d for d in self._docs if _casa(d, filtro)])

    async def count_documents(self, filtro=None):
        return len([d for d in self._docs if _casa(d, filtro)])


class _Db:
    def __init__(self, colecoes):
        self._colecoes = colecoes

    def __getitem__(self, nome):
        return self._colecoes.get(nome) or _Coleccao()


def _corre(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_rota_LE_a_loja_da_app_da_definicao_da_sincronizacao():
    from faturacao.db import COLECOES
    from faturacao.relatorio_rota import _juntar_dados
    from faturacao.sincronizacao_rota import CHAVE

    db = _Db({COLECOES["definicoes"]: _Coleccao(
        por_id={CHAVE: {"id": CHAVE, "loja_id": "loja-app", "ativo": True}})})
    partes = _corre(_juntar_dados(db, "2026-09-01"))
    assert partes["loja_da_app"] == "loja-app"


def test_sem_a_definicao_a_rota_nao_INVENTA_loja_nenhuma():
    from faturacao.relatorio_rota import _juntar_dados
    assert _corre(_juntar_dados(_Db({}), "2026-09-01"))["loja_da_app"] is None


def test_o_relatorio_e_montado_COM_a_loja_da_app(monkeypatch):
    """Perguntado ao caminho a sério: ler a definição e não a passar adiante
    era exactamente o mesmo email de antes, com mais uma leitura ao Mongo."""
    from faturacao import relatorio_rota as rota

    vistos = {}

    async def juntar(db, dia):
        return {"documentos": [], "lojas": [], "turnos": [],
                "loja_da_app": "loja-app"}

    def montar(**kw):
        vistos.update(kw)
        return {"dia": kw["dia"], "geral": {"faturacao": 0.0}, "lojas": []}

    async def enviar(html, para, assunto):
        return {"id": "e1"}

    monkeypatch.setattr(rota, "obter_db", lambda: _Db({}))
    monkeypatch.setattr(rota, "_juntar_dados", juntar)
    monkeypatch.setattr(rota, "montar_relatorio", montar)
    monkeypatch.setattr(rota, "html_do_relatorio", lambda dados, url_do_painel=None: "<p></p>")
    monkeypatch.setattr(rota, "_enviar", enviar)

    _corre(rota._produzir_e_enviar(["a@b.pt"], None))
    assert vistos.get("loja_da_app") == "loja-app"


# --- A repartição por tipo de pagamento continua a ser só do dinheiro contado -


DOC_BELEM = {"id": "d2", "tipo": "FS", "loja_id": "loja-1",
             "emitido_em": "2026-09-01T19:10:00+01:00",
             "total_bruto": 12.00, "total_liquido": 10.62}

TURNO_BELEM = {
    "sessao": {"id": "s1", "loja_id": "loja-1", "fundo": 50.0,
               "estado": "fechada", "contado": 62.0},
    "movimentos": [],
    "vendas": [{"id": "v1", "loja_id": "loja-1", "estado": "emitida",
                "pagamentos": [{"tipo_pagamento_id": "din", "nome": "Dinheiro",
                                "valor": 12.0, "tipo_fiscal": "NU"}],
                "linhas": [{"produto_nome": "Açaí", "quantidade": 1,
                            "produto_preco": 12.0, "produto_tax_id": "INT",
                            "opcoes": []}]}],
    "notas_credito": [],
}


def test_o_quadro_dos_pagamentos_fica_SO_com_o_dinheiro_que_passou_pela_gaveta():
    """A app cobra por Stripe. Se a receita dela entrasse aqui — nem que fosse
    como uma linha "Online" bem-intencionada — este quadro deixava de bater com
    o que se conta nas gavetas, que é a única coisa para que ele serve.

    E o número grande do email tem de continuar a incluí-la: é receita a
    sério.
    """
    r = _dados(turnos=[TURNO_BELEM], documentos=[DOC_APP, DOC_BELEM])
    assert r["geral"]["faturacao"] == 18.85
    assert sum(p["total"] for p in r["geral"]["pagamentos"]) == 12.00


def test_uma_loja_SEM_ID_nao_casa_com_a_ausencia_de_definicao():
    """`None == None` dava-se por a loja da app e apagava-lhe a caixa em
    silêncio, num portal que nunca configurou a sincronização."""
    r = montar_relatorio(dia="2026-09-01", ate="23:30",
                         lojas=[{"id": None, "nome": "?"}],
                         documentos=[], turnos=[])
    assert r["lojas"][0]["caixa"] is not None


# --- «X faturas por email, Y em papel» -------------------------------------------
#
# A medição que transforma a promessa num número, no canal que já existe. O
# tecto desta funcionalidade é a adopção do QR — que no dia em que foi construída
# era ZERO — e o número a vigiar é este, não o código.


def test_o_relatorio_diz_quantas_faturas_foram_por_EMAIL_e_quantas_em_PAPEL():
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[dict(DOC_APP, id="d%d" % i) for i in range(10)],
        turnos=[], faturas_por_email=3)

    assert dados["geral"]["faturas_por_email"] == 3
    assert dados["geral"]["faturas_em_papel"] == 7


def test_uma_NOTA_DE_CREDITO_nao_conta_como_papel_desta_linha():
    """As notas saem sempre em papel, mas esta linha é sobre o talão da COMPRA
    — misturá-las fazia o número em papel subir sem nada ter mudado."""
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[DOC_APP, dict(DOC_APP, id="n1", tipo="NC", total_bruto=-6.85)],
        turnos=[], faturas_por_email=1)

    assert (dados["geral"]["faturas_por_email"], dados["geral"]["faturas_em_papel"]) == (1, 0)


def test_a_contagem_nunca_passa_o_total_de_faturas_do_dia():
    """A fila conta-se pelo dia UTC e os documentos pelo dia de LISBOA: na
    fronteira, os dois podem discordar. Duas linhas do mesmo email a dizerem
    «4 por email, -1 em papel» era o relatório a acusar-se a si próprio."""
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[DOC_APP], turnos=[], faturas_por_email=4)

    assert (dados["geral"]["faturas_por_email"], dados["geral"]["faturas_em_papel"]) == (1, 0)


def test_a_linha_aparece_escrita_no_EMAIL_que_o_dono_abre():
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[dict(DOC_APP, id="d%d" % i) for i in range(10)],
        turnos=[], faturas_por_email=3)

    assert "3 faturas por email, 7 em papel" in html_do_relatorio(dados)


def test_num_dia_SEM_FATURAS_a_linha_nao_aparece():
    """Zero por email e zero em papel não é uma medição — é um dia fechado."""
    dados = montar_relatorio(dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
                             documentos=[], turnos=[], faturas_por_email=0)

    assert "em papel" not in html_do_relatorio(dados)


def test_a_ROTA_conta_as_linhas_do_DIA_e_so_as_do_EMAIL():
    """O módulo das contas é puro: se ninguém lhe disser quantas foram, o número
    nunca chega ao email das 23:30.

    A fixture traz de propósito uma linha de CRÉDITO e uma fatura por email de
    ONTEM: contar tudo, filtrar pelo campo errado ou não filtrar nada dá 4 e não
    2 — que são os três enganos que este teste vem prender."""
    from faturacao.db import COLECOES
    from faturacao.relatorio_rota import _juntar_dados

    db = _Db({COLECOES["pontos_app"]: _Coleccao([
        {"tipo": "fatura_email", "estado": "feito",
         "criado_em": "2026-09-01T12:00:00+00:00"},
        {"tipo": "fatura_email", "estado": "pendente",
         "criado_em": "2026-09-01T19:30:00+00:00"},
        {"tipo": "fatura_email", "estado": "feito",
         "criado_em": "2026-08-31T20:00:00+00:00"},
        {"tipo": "credito", "estado": "feito",
         "criado_em": "2026-09-01T12:00:01+00:00"},
    ])})
    assert _corre(_juntar_dados(db, "2026-09-01"))["faturas_por_email"] == 2


def test_o_relatorio_e_montado_COM_a_contagem_do_email(monkeypatch):
    from faturacao import relatorio_rota as rota

    vistos = {}

    async def juntar(db, dia):
        return {"documentos": [], "lojas": [], "turnos": [],
                "loja_da_app": None, "faturas_por_email": 5}

    def montar(**kw):
        vistos.update(kw)
        return {"dia": kw["dia"], "geral": {"faturacao": 0.0}, "lojas": []}

    async def enviar(html, para, assunto):
        return {"id": "e1"}

    monkeypatch.setattr(rota, "obter_db", lambda: _Db({}))
    monkeypatch.setattr(rota, "_juntar_dados", juntar)
    monkeypatch.setattr(rota, "montar_relatorio", montar)
    monkeypatch.setattr(rota, "html_do_relatorio", lambda dados, url_do_painel=None: "<p></p>")
    monkeypatch.setattr(rota, "_enviar", enviar)

    _corre(rota._produzir_e_enviar(["a@b.pt"], None))
    assert vistos.get("faturas_por_email") == 5


def test_as_faturas_da_LOJA_DA_APP_nao_contam_como_papel():
    """A app cobra por Stripe e as suas FS nunca passaram por uma impressora.

    Somá-las ao «em papel» punha um chão permanente no número que o dono foi
    mandado vigiar — a adopção do QR ao balcão — feito de faturas que nunca
    podem mudar de balde: não há QR para ler numa encomenda paga por Stripe. É
    a mesma invariante da `caixa`: a loja da app não entra nos números do
    balcão.
    """
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS), loja_da_app="loja-app",
        documentos=[dict(DOC_APP, id="a1"), dict(DOC_APP, id="a2")],
        turnos=[], faturas_por_email=0)

    assert (dados["geral"]["faturas_por_email"], dados["geral"]["faturas_em_papel"]) == (0, 0)
    assert "em papel" not in html_do_relatorio(dados)


def test_um_documento_SEM_LOJA_conta_como_papel_num_portal_sem_app():
    """O `loja_da_app and` da exclusão, pela mesma razão que o da `caixa`.

    Sem ele, `None == None` dava por loja da app todo o documento gravado sem
    `loja_id` — e num portal que nunca configurou a sincronização o «em papel»
    calava-se em silêncio, que é o pior desfecho para um número que existe para
    ser vigiado.
    """
    dados = montar_relatorio(
        dia="2026-09-01", ate="23:30", lojas=list(LOJAS),
        documentos=[dict(DOC_APP, id="s1", loja_id=None)],
        turnos=[], faturas_por_email=0)

    assert (dados["geral"]["faturas_por_email"], dados["geral"]["faturas_em_papel"]) == (0, 1)
