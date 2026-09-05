"""A leitura da caixa de email — tudo o que se pode confirmar sem rede nenhuma.

O IMAP e o Gemini são substituídos por duplos; o que se testa é o que este
módulo decide: de quem é a mensagem, o que se consegue ler dela, a que período
pertence o relatório, e o que fica gravado.
"""
import email as _email
from datetime import date

import pytest

from plataformas import leitura


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

@pytest.mark.parametrize("de, assunto, esperado", [
    ("no-reply@uber.com", "O teu resumo", "uber"),
    ("restaurantes@bolt.eu", "Pagamento semanal", "bolt"),
    ("partners@glovoapp.com", "Fatura quinzenal", "glovo"),
    ("qualquer@coisa.pt", "Uber Eats — relatório", "uber"),
    ("marketing@newsletter.pt", "Promoções de Verão", None),
    ("", "", None),
])
def test_classificar_a_plataforma(de, assunto, esperado):
    assert leitura.classificar(de, assunto) == esperado


def test_um_assunto_codificado_e_descodificado_antes_de_se_procurar_a_marca():
    """O assunto vem muitas vezes em `=?UTF-8?B?...?=`. Comparar as marcas
    contra esse texto não acertava em nada."""
    msg = mensagem(de="parceiros@exemplo.pt",
                   assunto="=?UTF-8?B?VWJlciBFYXRzIC0gcmVsYXTDs3Jpbw==?=",
                   texto="olá")
    assunto = leitura._cabecalho(msg, "Subject")
    assert assunto.startswith("Uber Eats")
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

def test_o_registo_tem_a_chave_da_idempotencia_e_os_valores_limpos():
    registo = leitura.montar_registo(
        {"liquido": "1.234,56", "pedidos": "120", "comissao": 300,
         "lojas": [{"nome": " Alfragide ", "liquido": "600", "pedidos": 60},
                   {"nome": "", "liquido": 1}],
         "problemas": ["  2 cancelados  ", ""], "notas": "tudo bem"},
        plataforma="uber",
        periodo={"tipo": "semana", "inicio": date(2026, 8, 24),
                 "fim": date(2026, 8, 30), "origem": "relatório"},
        origem={"assunto": "Resumo"})
    assert registo["id"] == "uber:2026-08-24..2026-08-30"
    assert registo["valores"]["liquido"] == 1234.56
    assert registo["valores"]["pedidos"] == 120
    assert registo["valores"]["bruto"] is None       # não veio: fica a None
    assert [l["nome"] for l in registo["lojas"]] == ["Alfragide"]  # a sem nome cai
    assert registo["problemas"] == ["2 cancelados"]


def test_duas_leituras_do_mesmo_relatorio_dao_a_MESMA_chave():
    """É isto que faz o cron a correr duas vezes escrever duas vezes o mesmo
    documento, em vez de dois documentos."""
    periodo = {"tipo": "semana", "inicio": date(2026, 8, 24),
               "fim": date(2026, 8, 30), "origem": "relatório"}
    a = leitura.montar_registo({}, plataforma="uber", periodo=periodo, origem={})
    b = leitura.montar_registo({}, plataforma="uber", periodo=periodo, origem={})
    assert a["id"] == b["id"]


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
