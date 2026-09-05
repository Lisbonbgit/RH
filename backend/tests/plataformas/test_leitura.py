"""A leitura da caixa de email — tudo o que se pode confirmar sem rede nenhuma.

O IMAP e o Gemini são substituídos por duplos; o que se testa é o que este
módulo decide: de quem é a mensagem, o que se consegue ler dela, a que período
pertence o relatório, e o que fica gravado.
"""
import email as _email
from datetime import date

import pytest

from plataformas import leitura


@pytest.fixture(autouse=True)
def estado_limpo():
    """O módulo guarda quais os modelos já esgotados e quanto tempo esperou —
    e isso é POR RECOLHA. Sem limpar entre testes, um teste que esgota os
    modelos deixava os seguintes a falhar por uma razão que não é a deles."""
    leitura.reiniciar_orcamento()
    leitura._ultima_chamada = 0.0
    yield
    leitura.reiniciar_orcamento()


def mensagem(*, de="relatorios@uber.com", assunto="Resumo semanal",
             texto=None, html=None, anexos=()):
    """Uma mensagem de email a sério, montada a partir do texto em cru — é
    assim que ela chega do IMAP, e é assim que o módulo a vai ver."""
    fronteira = "----limite"
    partes = []
    if texto is not None:
        partes.append('Content-Type: text/plain; charset="utf-8"\r\n\r\n%s' % texto)
    if html is not None:
        partes.append('Content-Type: text/html; charset="utf-8"\r\n\r\n%s' % html)
    for nome, tipo, conteudo in anexos:
        partes.append(
            'Content-Type: %s; name="%s"\r\n'
            'Content-Disposition: attachment; filename="%s"\r\n\r\n%s'
            % (tipo, nome, nome, conteudo))
    corpo = ("\r\n--%s\r\n" % fronteira).join([""] + partes) + "\r\n--%s--\r\n" % fronteira
    cru = (
        'From: %s\r\nSubject: %s\r\nDate: Mon, 31 Aug 2026 03:12:00 +0100\r\n'
        'MIME-Version: 1.0\r\n'
        'Content-Type: multipart/mixed; boundary="%s"\r\n\r\n%s'
        % (de, assunto, fronteira, corpo))
    return _email.message_from_string(cru)


# --- De quem é a mensagem ---------------------------------------------------

# Remetentes e assuntos COPIADOS de uma caixa a sério (2026-09-05).
@pytest.mark.parametrize("de, assunto, esperado", [
    # --- os relatórios que interessam -------------------------------------
    ("Uber Eats <noreply@uber.com>",
     "Resumo dos Pagamentos Uber Eats para L'açaí Amadora Aug 24, 2026 - Aug 30, 2026",
     "uber"),
    ("portugal-food@bolt.eu", "Relatório semanal da Bolt Food", "bolt"),
    ("no-reply@glovoapp.com",
     "Glovoapp Spain Platform S.L. - Extrato I26LQPOMT1000017", "glovo"),
    # --- a publicidade das MESMAS plataformas, que não pode entrar ---------
    ("eats@uber.com", "Campanha nacional: 40% de desconto", None),
    ("eats@uber.com", "Uma atualização das suas Taxas de Serviço no Uber Eats", None),
    ("portugal@delivery-partner-marketing.bolt.eu",
     "Aumente as vendas com as promoções inteligentes", None),
    ("portugal@delivery-partner-marketing.bolt.eu",
     "A celebrar 2 anos de parceria com a Bolt Food", None),
    ('"Glovo Store" <no-reply@email.glovostore.com>',
     "VOLTA ÀS AULAS! 📖 -10€ em Sacos Glovo", None),
    ("Glovo Partners <updates@partner.glovoapp.com>",
     "⏰ Atualize a sua ementa hoje", None),
    # --- do remetente certo mas de outro assunto ---------------------------
    ("no-reply@glovoapp.com", "Avaliações dos clientes Glovo", None),
    ("noreply@uber.com", "Your Uber Eats Monthly Statement is Ready", None),
    ("", "", None),
])
def test_classificar_so_deixa_passar_relatorios(de, assunto, esperado):
    """**Exige o remetente E o assunto.**

    A primeira versão procurava só a palavra "uber"/"bolt"/"glovo" em qualquer
    sítio. Numa caixa real isso apanhou 73 mensagens em 20 dias, quase todas
    publicidade, e as 73 iam à IA — que a partir da 21.ª por minuto recusa
    tudo por quota. A recolha acabava sem encontrar um único relatório.
    """
    assert leitura.classificar(de, assunto) == esperado


def test_um_assunto_codificado_e_descodificado_antes_de_se_procurar_a_marca():
    """O assunto vem muitas vezes em `=?UTF-8?B?...?=`. Comparar contra esse
    texto não acertava em nada."""
    msg = mensagem(de="Uber Eats <noreply@uber.com>",
                   assunto="=?UTF-8?B?UmVzdW1vIGRvcyBQYWdhbWVudG9zIFViZXIgRWF0cw==?=",
                   texto="olá")
    assunto = leitura._cabecalho(msg, "Subject")
    assert assunto.startswith("Resumo dos Pagamentos")
    assert leitura.classificar(leitura._cabecalho(msg, "From"), assunto) == "uber"


# --- O que se lê do corpo ---------------------------------------------------

def test_prefere_se_o_texto_simples_ao_html():
    msg = mensagem(texto="Total: 1234,56 EUR", html="<p>outra coisa</p>")
    assert leitura.texto_da_mensagem(msg) == "Total: 1234,56 EUR"


def test_sem_texto_simples_desmonta_se_o_html():
    msg = mensagem(html="<style>p{color:red}</style><p>Total</p><p>1234,56 EUR</p>")
    lido = leitura.texto_da_mensagem(msg)
    assert "Total" in lido and "1234,56 EUR" in lido
    # O CSS de um email da Uber é maior do que o relatório e é só ruído.
    assert "color:red" not in lido


def test_uma_tabela_em_html_nao_cola_as_celulas_umas_as_outras():
    msg = mensagem(html="<table><tr><td>Pedidos</td><td>120</td></tr></table>")
    assert "Pedidos" in leitura.texto_da_mensagem(msg)
    assert "Pedidos120" not in leitura.texto_da_mensagem(msg)


def test_a_data_da_mensagem_sai_do_cabecalho():
    assert leitura.data_da_mensagem(mensagem(texto="x")) == date(2026, 8, 31)


# --- Anexos -----------------------------------------------------------------

def test_o_pdf_e_o_csv_sao_lidos_e_o_xlsx_fica_assinalado():
    msg = mensagem(texto="x", anexos=[
        ("detalhe.csv", "text/csv", "loja,total\nAlfragide,100"),
        ("resumo.pdf", "application/pdf", "%PDF-1.4 fingido"),
        ("livro.xlsx", "application/vnd.openxmlformats-officedocument."
                       "spreadsheetml.sheet", "PK fingido"),
    ])
    anexos = leitura.anexos_da_mensagem(msg)
    assert sorted(a["nome"] for a in anexos["lidos"]) == ["detalhe.csv", "resumo.pdf"]
    # O que não se consegue ler NÃO se cala: é o que explica um número em falta.
    assert anexos["ignorados"] == ["livro.xlsx"]


def test_um_anexo_grande_de_mais_e_ignorado_em_vez_de_ir_para_a_IA():
    msg = mensagem(texto="x", anexos=[
        ("enorme.pdf", "application/pdf", "a" * (leitura.MAX_BYTES_POR_ANEXO + 10)),
    ])
    anexos = leitura.anexos_da_mensagem(msg)
    assert anexos["lidos"] == [] and anexos["ignorados"] == ["enorme.pdf"]


# --- O que a IA devolveu ----------------------------------------------------

def test_uma_resposta_estragada_da_erro_e_nunca_levanta():
    for cru in ("", "não é json", "ERRO:sem chave", "[1,2,3]", "{isto: não fecha"):
        assert "erro" in leitura.ler_json_da_ia(cru)


def test_um_json_valido_passa():
    assert leitura.ler_json_da_ia('{"e_relatorio": true}') == {"e_relatorio": True}


@pytest.mark.parametrize("entrada, esperado", [
    (1234.5, 1234.5), ("1234.50", 1234.5), ("1.234,56", 1234.56),
    ("1234,56", 1234.56), ("1 234,56 €", 1234.56),
    (None, None), ("", None), ("n/d", None), (True, None),
])
def test_os_numeros_que_a_IA_manda(entrada, esperado):
    assert leitura._numero(entrada) == esperado


def test_um_valor_ilegivel_fica_a_None_e_NUNCA_a_zero():
    """Zero num relatório de dinheiro lê-se «não vendemos nada»."""
    assert leitura._numero("não consta") is None
    assert leitura._numero(None) is None


# --- A que período pertence o relatório -------------------------------------

HOJE = date(2026, 8, 31)


def test_acredita_se_nas_datas_do_relatorio_quando_fazem_sentido():
    periodo = leitura.periodo_do_relatorio(
        {"periodo_inicio": "2026-08-24", "periodo_fim": "2026-08-30"},
        "uber", date(2026, 8, 31), HOJE)
    assert periodo["inicio"] == date(2026, 8, 24)
    assert periodo["origem"] == "relatório"


def test_uma_semana_com_a_duracao_errada_e_recusada_e_usa_se_o_calendario():
    """Uma data mal lida não é um número errado: é o relatório desta semana a
    ser arquivado na semana errada, e o da semana errada a ser reescrito."""
    periodo = leitura.periodo_do_relatorio(
        {"periodo_inicio": "2026-08-01", "periodo_fim": "2026-08-30"},
        "uber", date(2026, 8, 31), HOJE)
    assert (periodo["inicio"], periodo["fim"]) == (date(2026, 8, 24), date(2026, 8, 30))
    assert periodo["origem"] == "calendário"


def test_um_periodo_no_futuro_e_recusado():
    periodo = leitura.periodo_do_relatorio(
        {"periodo_inicio": "2026-09-07", "periodo_fim": "2026-09-13"},
        "uber", date(2026, 8, 31), HOJE)
    assert periodo["origem"] == "calendário"


def test_sem_datas_no_relatorio_deriva_se_da_data_do_email():
    periodo = leitura.periodo_do_relatorio({}, "uber", date(2026, 8, 31), HOJE)
    assert (periodo["inicio"], periodo["fim"]) == (date(2026, 8, 24), date(2026, 8, 30))


def test_a_glovo_deriva_para_a_quinzena_e_nao_para_a_semana():
    periodo = leitura.periodo_do_relatorio({}, "glovo", date(2026, 8, 20), HOJE)
    assert periodo["tipo"] == "quinzena"
    assert (periodo["inicio"], periodo["fim"]) == (date(2026, 8, 1), date(2026, 8, 15))


def test_uma_quinzena_de_dezasseis_dias_e_aceite():
    """Julho tem 31 dias: a segunda quinzena vai de 16 a 31, que são dezasseis."""
    periodo = leitura.periodo_do_relatorio(
        {"periodo_inicio": "2026-07-16", "periodo_fim": "2026-07-31"},
        "glovo", date(2026, 8, 5), HOJE)
    assert periodo["origem"] == "relatório"


# --- O registo que fica gravado ---------------------------------------------

PERIODO = {"tipo": "semana", "inicio": date(2026, 8, 24),
           "fim": date(2026, 8, 30), "origem": "relatório"}


def test_o_registo_tem_a_chave_da_idempotencia_e_os_valores_limpos():
    registo = leitura.montar_registo(
        {"loja": "L'açaí Amadora", "liquido": "1.234,56", "pedidos": "120",
         "comissao": 300,
         "lojas": [{"nome": " Alfragide ", "liquido": "600", "pedidos": 60},
                   {"nome": "", "liquido": 1}],
         "problemas": ["  2 cancelados  ", ""], "notas": "tudo bem"},
        plataforma="uber", periodo=PERIODO, origem={"assunto": "Resumo"})
    assert registo["id"] == "uber:2026-08-24..2026-08-30:l-acai-amadora"
    assert registo["loja"] == "L'açaí Amadora"
    assert registo["valores"]["liquido"] == 1234.56
    assert registo["valores"]["pedidos"] == 120
    assert registo["valores"]["bruto"] is None       # não veio: fica a None
    assert [l["nome"] for l in registo["lojas"]] == ["Alfragide"]  # a sem nome cai
    assert registo["problemas"] == ["2 cancelados"]


def test_duas_leituras_do_mesmo_relatorio_dao_a_MESMA_chave():
    """É isto que faz o cron a correr duas vezes escrever duas vezes o mesmo
    documento, em vez de dois documentos."""
    dados = {"loja": "L'açaí Amadora"}
    a = leitura.montar_registo(dados, plataforma="uber", periodo=PERIODO, origem={})
    b = leitura.montar_registo(dados, plataforma="uber", periodo=PERIODO, origem={})
    assert a["id"] == b["id"]


def test_LOJAS_DIFERENTES_dao_chaves_diferentes():
    """**O defeito que isto guarda custava dinheiro.** A Uber manda um email
    por loja — quatro por semana. Com a loja fora da chave, os quatro tinham o
    mesmo `id`, escreviam por cima uns dos outros, e o email de segunda
    mostrava o valor de UMA loja como se fosse o da semana inteira."""
    chaves = {
        leitura.montar_registo({"loja": nome}, plataforma="uber",
                               periodo=PERIODO, origem={})["id"]
        for nome in ("L'açaí Amadora", "L'açaí Alfragide", "L'açai Oeiras",
                     "L’açaí (Algueirão)")
    }
    assert len(chaves) == 4


def test_a_MESMA_loja_escrita_de_duas_maneiras_e_a_mesma_loja():
    """A Uber escreve `L'açai Oeiras` numa semana e `L'açaí Oeiras` noutra.
    Sem normalizar, eram duas lojas — e o aviso de «faltou uma loja»
    disparava todas as semanas."""
    a = leitura.montar_registo({"loja": "L'açai Oeiras"}, plataforma="uber",
                               periodo=PERIODO, origem={})
    b = leitura.montar_registo({"loja": "L’açaí  OEIRAS"}, plataforma="uber",
                               periodo=PERIODO, origem={})
    assert a["id"] == b["id"] == "uber:2026-08-24..2026-08-30:l-acai-oeiras"


def test_sem_loja_conhecida_os_relatorios_NAO_se_comem_uns_aos_outros():
    """Dois relatórios sem loja identificada ficam como dois registos (e o
    ecrã di-lo). Juntá-los na mesma chave perdia o dinheiro de um deles em
    silêncio, que é o pior dos dois desfechos."""
    a = leitura.montar_registo({}, plataforma="bolt", periodo=PERIODO,
                               origem={}, chave_de_recurso="<msg-1@bolt.eu>")
    b = leitura.montar_registo({}, plataforma="bolt", periodo=PERIODO,
                               origem={}, chave_de_recurso="<msg-2@bolt.eu>")
    assert a["id"] != b["id"]
    assert a["loja"] is None


# --- Os links da Bolt: seguir um endereço que veio dentro de um email --------

# Como a Bolt escreve o link no email: embrulhado num redireccionador da
# Amazon, com o destino verdadeiro codificado dentro do caminho.
def embrulhado(destino):
    return ("https://3zf1wp45.r.eu-central-1.awstrack.me/L0/"
            + destino.replace(":", "%3A").replace("/", "%2F") + "/1/0102abc")


HTML_DA_BOLT = """
<a href="{pdf}">Descarregar fatura</a>
<a href="{csv}">Descarregar relatório semanal: CSV</a>
<a href="{mau}">Promoção</a>
<a href="https://bolt.eu/en/support/articles/78534/">Ajuda</a>
""".format(
    pdf=embrulhado("https://doclink.live.boltsvc.net/invoice/pdf?id=1"),
    csv=embrulhado("https://delivery-reporting.bolt.eu/weekly-report/x.csv"),
    mau=embrulhado("https://sitio-estranho.example.com/relatorio.csv"),
)


def test_so_se_aceitam_links_para_os_servidores_da_propria_plataforma():
    alvos = leitura.alvos_de_descarga(HTML_DA_BOLT, "bolt")
    assert len(alvos) == 2
    assert all("sitio-estranho" not in a for a in alvos)


def test_uma_plataforma_sem_descargas_declaradas_nao_segue_link_nenhum():
    """A Uber e a Glovo trazem tudo no email. Seguir links delas era abrir uma
    porta que não é precisa para nada."""
    assert leitura.alvos_de_descarga(HTML_DA_BOLT, "uber") == []
    assert leitura.alvos_de_descarga(HTML_DA_BOLT, "glovo") == []


def test_um_servidor_permitido_metido_no_QUERY_nao_abre_a_porta():
    """`https://mau.example.com/x?next=https://delivery-reporting.bolt.eu` não
    é um endereço da Bolt. Procurar o destino em qualquer sítio do endereço
    era exactamente como esta barreira se contornava."""
    html = ('<a href="https://mau.example.com/x?next=https%3A%2F%2F'
            'delivery-reporting.bolt.eu%2Fweekly-report%2Fx.csv">r</a>')
    assert leitura.alvos_de_descarga(html, "bolt") == []


class _RespostaFalsa:
    def __init__(self, url, status=200, tipo="text/csv", conteudo=b"a,b\n1,2\n"):
        self.url = url
        self.status_code = status
        self.headers = {"content-type": tipo}
        self.content = conteudo


class _ClienteFalso:
    """Um duplo do httpx.Client. `parou_em` diz onde o redireccionamento
    acabou — é isso que a segunda verificação tem de olhar."""
    parou_em = None
    pedidos = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        _ClienteFalso.pedidos.append(url)
        return _RespostaFalsa(_ClienteFalso.parou_em or url)


def test_a_descarga_traz_o_ficheiro_quando_acaba_no_servidor_certo(monkeypatch):
    _ClienteFalso.pedidos = []
    _ClienteFalso.parou_em = "https://delivery-reporting.bolt.eu/weekly-report/x.csv"
    monkeypatch.setattr(leitura.httpx, "Client", _ClienteFalso)

    saida = leitura.descarregar_ligados(HTML_DA_BOLT, "bolt")
    assert [f["nome"] for f in saida["lidos"]] == ["x.csv", "x.csv"]
    assert saida["lidos"][0]["mime"] == "text/plain"


def test_uma_descarga_que_ACABA_noutro_servidor_e_deitada_fora(monkeypatch):
    """Os links passam por um redireccionador. Verificar só o endereço escrito
    no email deixava um redireccionamento levar-nos para qualquer lado."""
    _ClienteFalso.pedidos = []
    _ClienteFalso.parou_em = "https://sitio-estranho.example.com/x.csv"
    monkeypatch.setattr(leitura.httpx, "Client", _ClienteFalso)

    saida = leitura.descarregar_ligados(HTML_DA_BOLT, "bolt")
    assert saida["lidos"] == []
    assert any("recusada" in i for i in saida["ignorados"])


def test_um_xlsx_nao_e_falha_nenhuma(monkeypatch):
    """A API não lê `.xlsx` em linha, e o mesmo relatório vem sempre também em
    CSV — que é o que traz os totais escritos. Não se assinala como problema."""
    class SoXlsx(_ClienteFalso):
        def get(self, url):
            return _RespostaFalsa(
                "https://delivery-reporting.bolt.eu/weekly-report/x.xlsx",
                tipo="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    monkeypatch.setattr(leitura.httpx, "Client", SoXlsx)
    saida = leitura.descarregar_ligados(HTML_DA_BOLT, "bolt")
    assert saida["lidos"] == [] and saida["ignorados"] == []


# --- O IMAP: a leitura não pode marcar as mensagens como lidas ---------------

class _ImapFalso:
    """Um duplo do `imaplib.IMAP4_SSL` que regista o que lhe foi pedido."""

    pedidos = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        _ImapFalso.pedidos = []

    def login(self, user, pwd):
        _ImapFalso.pedidos.append(("login", user))

    def select(self, pasta, readonly=False):
        _ImapFalso.pedidos.append(("select", pasta, readonly))

    def search(self, charset, *criterios):
        _ImapFalso.pedidos.append(("search",) + criterios)
        return "OK", [b"1"]

    def fetch(self, numero, o_que):
        _ImapFalso.pedidos.append(("fetch", o_que))
        cru = b"From: a@uber.com\r\nSubject: x\r\n\r\nola"
        return "OK", [(b"1", cru)]

    def logout(self):
        _ImapFalso.pedidos.append(("logout",))


def test_a_leitura_usa_PEEK_e_abre_a_caixa_em_modo_de_leitura(monkeypatch):
    """`RFC822` marca a mensagem como LIDA. Isto corre todas as segundas de
    madrugada na caixa real do dono: sem `PEEK`, esvaziava-lhe os não-lidos
    sem ninguém perceber porquê."""
    monkeypatch.setattr(leitura.imaplib, "IMAP4_SSL", _ImapFalso)
    leitura._mensagens_da_caixa({"host": "imap.exemplo.pt", "user": "u", "pass": "p"}, 20)

    fetches = [p for p in _ImapFalso.pedidos if p[0] == "fetch"]
    assert fetches, "não chegou a ler nenhuma mensagem"
    for _, comando in fetches:
        assert "BODY.PEEK[" in comando
        assert "RFC822" not in comando
    assert ("select", "INBOX", True) in _ImapFalso.pedidos


def test_sem_caixas_configuradas_o_aviso_e_explicito(monkeypatch):
    monkeypatch.delenv("IMAP_MAILBOXES", raising=False)
    saida = leitura.recolher(HOJE)
    assert saida["registos"] == []
    assert "IMAP_MAILBOXES" in saida["avisos"][0]


def test_uma_caixa_que_nao_responde_nao_derruba_a_recolha(monkeypatch):
    def rebenta(caixa, dias):
        raise OSError("ligação recusada")

    monkeypatch.setattr(leitura, "_mensagens_da_caixa", rebenta)
    saida = leitura.recolher(HOJE, caixas=[{"host": "a", "user": "u@x.pt"}])
    assert saida["registos"] == []
    assert "u@x.pt" in saida["avisos"][0]


# --- O ritmo dos pedidos à IA ------------------------------------------------

def test_os_pedidos_a_IA_sao_espacados_para_nao_esgotar_a_quota(monkeypatch):
    """O plano gratuito permite 20 por minuto. Disparar quinze de seguida
    esgota-a, e a partir daí cada pedido custa quase um minuto de espera — a
    recolha passava de segundos a mais de uma hora."""
    dormiu = []
    monkeypatch.setattr(leitura.time, "sleep", lambda s: dormiu.append(s))
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")

    class Resposta:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    class Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return Resposta()

    monkeypatch.setattr(leitura.httpx, "Client", Cliente)
    leitura._ultima_chamada = 0.0
    leitura._chamar_gemini([{"text": "a"}])
    leitura._chamar_gemini([{"text": "b"}])
    # O segundo pedido esperou pelo intervalo; o primeiro não tinha por quem.
    assert any(0 < s <= leitura.INTERVALO_ENTRE_CHAMADAS for s in dormiu)


def test_a_espera_pelo_modelo_ocupado_tem_um_tecto(monkeypatch):
    """Uma recolha que demore mais do que o orçamento é uma recolha que
    ninguém vê acabar — o botão do ecrã desiste aos cinco minutos. Desiste-se
    com um erro claro, e a próxima corrida apanha o que ficou por ler.

    (O tecto é para o 503, que se resolve esperando. O 429 não espera: muda de
    modelo, porque a quota é diária e nenhuma espera a devolve.)"""
    monkeypatch.setattr(leitura.time, "sleep", lambda s: None)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")

    class Ocupado:
        status_code = 503

        def json(self):
            return {"error": {"message": "High demand. Please retry in 55s."}}

    class Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return Ocupado()

    monkeypatch.setattr(leitura.httpx, "Client", Cliente)
    respostas = [leitura._chamar_gemini([{"text": "x"}]) for _ in range(4)]
    assert any("tempo de espera desta recolha esgotou-se" in r for r in respostas)


def test_o_modelo_da_IA_e_fixo_e_nao_um_alias_flutuante():
    """Medido na conta a sério: a quota gratuita é 20 pedidos por DIA e por
    modelo, e `gemini-flash-latest` aponta para o mais recente — que é o que
    tem a quota mais apertada. Um alias também muda de modelo debaixo dos pés,
    e um relatório de dinheiro não deve mudar de leitor sem alguém decidir."""
    assert "latest" not in leitura.MODELO_POR_OMISSAO
    assert leitura.MODELO_POR_OMISSAO.startswith("gemini-")


def test_a_variavel_do_modelo_nao_e_a_da_ingestao_de_faturas(monkeypatch):
    """`GEMINI_MODEL` é a da ingestão de facturas. Se este módulo a lesse,
    mudá-la aqui mudava o modelo que lê as facturas dos fornecedores."""
    registados = {}

    class Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **k):
            registados["url"] = url
            raise RuntimeError("chega")

    monkeypatch.setenv("GEMINI_API_KEY", "chave")
    monkeypatch.setenv("GEMINI_MODEL", "modelo-da-ingestao-de-faturas")
    monkeypatch.setattr(leitura.time, "sleep", lambda s: None)
    monkeypatch.setattr(leitura.httpx, "Client", Cliente)
    leitura._ultima_chamada = 0.0
    leitura._chamar_gemini([{"text": "x"}])
    assert "modelo-da-ingestao-de-faturas" not in registados["url"]
    assert leitura.MODELO_POR_OMISSAO in registados["url"]

    # E a variável PRÓPRIA manda, para se poder trocar sem tocar em código.
    monkeypatch.setenv("PLATAFORMAS_GEMINI_MODEL", "gemini-outro-qualquer")
    leitura._ultima_chamada = 0.0
    leitura._chamar_gemini([{"text": "x"}])
    assert "gemini-outro-qualquer" in registados["url"]


def test_a_comissao_guarda_se_sempre_positiva():
    """Na primeira corrida a sério, o mesmo relatório da mesma semana devolveu
    `280.92` de uma loja e `-217.29` de outra. Somar as duas dava um total que
    não quer dizer nada."""
    a = leitura.montar_registo({"loja": "A", "comissao": 280.92, "taxas": -45.0},
                               plataforma="uber", periodo=PERIODO, origem={})
    b = leitura.montar_registo({"loja": "B", "comissao": -217.29},
                               plataforma="uber", periodo=PERIODO, origem={})
    assert a["valores"]["comissao"] == 280.92
    assert a["valores"]["taxas"] == 45.0
    assert b["valores"]["comissao"] == 217.29
    # Um valor que não veio continua a NÃO existir — nunca zero.
    assert b["valores"]["taxas"] is None


def test_os_ajustes_MANTEM_o_sinal():
    """Ao contrário da comissão, aqui o sinal diz alguma coisa: um estorno
    desconta, uma compensação soma."""
    r = leitura.montar_registo({"loja": "A", "ajustes": -53.20},
                               plataforma="uber", periodo=PERIODO, origem={})
    assert r["valores"]["ajustes"] == -53.20


def test_as_mensagens_sao_lidas_da_mais_recente_para_a_mais_antiga(monkeypatch):
    """A quota é limitada. Ao ler pela ordem de chegada, o orçamento gastava-se
    nas semanas velhas (já gravadas) e a semana ATUAL — a única de que o email
    fala — ficava por ler. Medido: 20 relatórios lidos, todos de semanas
    passadas, e a semana em causa sem um único."""
    class Imap(_ImapFalso):
        def search(self, charset, *criterios):
            return "OK", [b"1 2 3 10 11"]

    lidas = []

    class ImapQueRegista(Imap):
        def fetch(self, numero, o_que):
            lidas.append(int(numero))
            return "OK", [(numero, b"From: a@uber.com\r\nSubject: x\r\n\r\nola")]

    monkeypatch.setattr(leitura.imaplib, "IMAP4_SSL", ImapQueRegista)
    leitura._mensagens_da_caixa({"host": "h", "user": "u", "pass": "p"}, 20)
    assert lidas == sorted(lidas, reverse=True), "leu da mais antiga para a mais nova"
    assert lidas[0] == 11


def test_um_503_do_modelo_tambem_se_retenta(monkeypatch):
    """«This model is currently experiencing high demand» apareceu na primeira
    corrida a sério e custou quatro relatórios. Resolve-se esperando, tal como
    a quota — desistir à primeira era deitar fora um relatório por causa de um
    pico de segundos."""
    tentativas = []

    class Ocupado:
        status_code = 503

        def json(self):
            return {"error": {"message": "This model is currently experiencing "
                                         "high demand. Please try again."}}

    class Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            tentativas.append(1)
            return Ocupado()

    monkeypatch.setenv("GEMINI_API_KEY", "chave")
    monkeypatch.setattr(leitura.time, "sleep", lambda s: None)
    monkeypatch.setattr(leitura.httpx, "Client", Cliente)
    leitura.reiniciar_orcamento()
    leitura._ultima_chamada = 0.0
    leitura._chamar_gemini([{"text": "x"}])
    assert len(tentativas) > 1, "desistiu à primeira num erro que passa sozinho"


# --- A quota é por modelo e por dia: passa-se ao modelo seguinte -------------

def _cliente_que_responde(mapa, registo):
    """Um duplo do httpx.Client: `mapa` diz o que cada modelo responde."""
    class Resposta:
        def __init__(self, codigo):
            self.status_code = codigo

        def json(self):
            if self.status_code == 200:
                return {"candidates": [{"content": {"parts": [{"text": '{"ok":1}'}]}}]}
            return {"error": {"message": "Quota exceeded, retry in 55s."}}

    class Cliente:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **k):
            modelo = url.split("/models/")[1].split(":")[0]
            registo.append(modelo)
            return Resposta(mapa.get(modelo, 200))

    return Cliente


def test_com_a_quota_de_um_modelo_esgotada_vai_se_ao_seguinte(monkeypatch):
    """Esperar não devolve uma quota DIÁRIA. Medido na conta a sério: com o
    primeiro modelo esgotado, os outros respondiam à primeira."""
    tentados = []
    monkeypatch.setenv("GEMINI_API_KEY", "chave")
    monkeypatch.setattr(leitura.time, "sleep", lambda s: None)
    monkeypatch.setattr(leitura.httpx, "Client",
                        _cliente_que_responde({leitura.MODELO_POR_OMISSAO: 429},
                                              tentados))
    leitura.reiniciar_orcamento()
    leitura._ultima_chamada = 0.0
    assert "ok" in leitura._chamar_gemini([{"text": "x"}])
    assert tentados[0] == leitura.MODELO_POR_OMISSAO
    assert tentados[1] in leitura.MODELOS_DE_RECURSO


def test_um_modelo_esgotado_nao_e_tentado_outra_vez_na_mesma_recolha(monkeypatch):
    """Sem isto, cada uma das quinze mensagens voltava a bater à mesma porta
    fechada — quinze pedidos deitados fora e o tempo todo a passar."""
    tentados = []
    monkeypatch.setenv("GEMINI_API_KEY", "chave")
    monkeypatch.setattr(leitura.time, "sleep", lambda s: None)
    monkeypatch.setattr(leitura.httpx, "Client",
                        _cliente_que_responde({leitura.MODELO_POR_OMISSAO: 429},
                                              tentados))
    leitura.reiniciar_orcamento()
    leitura._ultima_chamada = 0.0
    leitura._chamar_gemini([{"text": "a"}])
    leitura._chamar_gemini([{"text": "b"}])
    assert tentados.count(leitura.MODELO_POR_OMISSAO) == 1


def test_com_TODOS_os_modelos_esgotados_diz_se_por_extenso(monkeypatch):
    tentados = []
    esgotados = {m: 429 for m in
                 (leitura.MODELO_POR_OMISSAO,) + leitura.MODELOS_DE_RECURSO}
    monkeypatch.setenv("GEMINI_API_KEY", "chave")
    monkeypatch.setattr(leitura.time, "sleep", lambda s: None)
    monkeypatch.setattr(leitura.httpx, "Client",
                        _cliente_que_responde(esgotados, tentados))
    leitura.reiniciar_orcamento()
    leitura._ultima_chamada = 0.0
    resposta = leitura._chamar_gemini([{"text": "x"}])
    assert "esgotou-se hoje em todos os modelos" in resposta
    assert "próxima recolha" in resposta


def test_a_lista_de_esgotados_limpa_se_a_cada_recolha(monkeypatch):
    """A quota é diária — a corrida seguinte pode ser noutro dia."""
    leitura._modelos_esgotados.add("gemini-qualquer")
    leitura.reiniciar_orcamento()
    assert leitura._modelos_esgotados == set()


# --- Não pagar duas vezes pelo mesmo email -----------------------------------

class _ImapComUmRelatorio(_ImapFalso):
    """Uma caixa com uma mensagem que É um relatório da Uber."""

    CRU = (b"From: Uber Eats <noreply@uber.com>\r\n"
           b"Subject: Resumo dos Pagamentos Uber Eats para A\r\n"
           b"Message-ID: <ja-lido@uber.com>\r\n"
           b"Date: Mon, 31 Aug 2026 03:12:00 +0100\r\n\r\n"
           b"Pagamento liquido 100,00 EUR")

    def fetch(self, numero, o_que):
        return "OK", [(numero, self.CRU)]


def test_um_email_ja_lidO_nao_volta_a_ir_a_IA(monkeypatch):
    """A janela é de vinte dias, mas de uma segunda para a outra só há meia
    dúzia de emails novos. Sem esta lista, cada recolha voltava a pagar à IA
    pelas três semanas anteriores — que já estão na base de dados."""
    foi_a_ia = []
    monkeypatch.setattr(leitura.imaplib, "IMAP4_SSL", _ImapComUmRelatorio)
    monkeypatch.setattr(leitura, "_chamar_gemini",
                        lambda partes, timeout=180: foi_a_ia.append(1) or '{"e_relatorio": true}')

    caixa = [{"host": "h", "user": "u", "pass": "p"}]
    leitura.recolher(HOJE, caixas=caixa, ja_lidos={"<ja-lido@uber.com>"})
    assert foi_a_ia == [], "pagou a IA por um email que já estava gravado"

    # E sem a marca, lê-se na mesma.
    leitura.recolher(HOJE, caixas=caixa)
    assert len(foi_a_ia) == 1


def test_o_registo_guarda_o_message_id_para_a_proxima_corrida(monkeypatch):
    monkeypatch.setattr(leitura.imaplib, "IMAP4_SSL", _ImapComUmRelatorio)
    monkeypatch.setattr(leitura, "_chamar_gemini",
                        lambda partes, timeout=180:
                        '{"e_relatorio": true, "loja": "A", "liquido": 100}')
    saida = leitura.recolher(HOJE, caixas=[{"host": "h", "user": "u", "pass": "p"}])
    assert saida["registos"][0]["origem"]["message_id"] == "<ja-lido@uber.com>"
