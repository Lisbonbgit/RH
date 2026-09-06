"""**A ingestão não pode mexer na caixa de correio de uma pessoa a sério.**

Três defeitos que estavam em produção, todos no mesmo sítio:

1. `select("INBOX")` sem `readonly=True` mais `fetch("(RFC822)")` marcava como
   LIDAS todas as mensagens dos últimos 7 dias das três caixas, todos os dias.
   O módulo das Plataformas foi escrito de propósito para não fazer isto; este
   fazia. O dono abria a caixa e já não sabia o que tinha por ler.

2. Sem filtro de remetente, cada PDF do banco e cada relatório da Teya era
   enviado ao Gemini só para ele responder "isto não é uma fatura". Medido na
   caixa a sério a 2026-09-05: 80 avisos do Millennium e 31 relatórios da Teya
   em 30 dias. A quota do plano gratuito são 20 pedidos por DIA, partilhada com
   a leitura das plataformas — e estava esgotada (429 ao vivo).

3. Ao deitar fora, marcava o ficheiro como visto para sempre, sem dizer de que
   leitor era a marca. Um leitor de extratos escrito depois encontrava lá os
   sha1 dos extratos e importava zero, com 200 OK e sem se queixar.
"""
import asyncio
import email.message
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "teste_sem_ligacao")

import server  # noqa: E402


def _mensagem(de, nome_anexo="fatura.pdf", conteudo=b"%PDF-1.4" + b"x" * 400):
    msg = email.message.EmailMessage()
    msg["From"] = de
    msg["Subject"] = "assunto"
    msg.set_content("corpo")
    msg.add_attachment(conteudo, maintype="application", subtype="pdf",
                       filename=nome_anexo)
    return msg.as_bytes()


class ImapFalso:
    """Guarda como foi aberto e como foram pedidas as mensagens."""

    def __init__(self, mensagens):
        self.mensagens = mensagens
        self.select_args = None
        self.fetch_specs = []

    def login(self, u, p):
        return ("OK", [b""])

    def select(self, caixa, readonly=False):
        self.select_args = (caixa, readonly)
        return ("OK", [b"1"])

    def search(self, charset, *criterios):
        return ("OK", [b" ".join(str(i + 1).encode() for i in range(len(self.mensagens)))])

    def fetch(self, num, spec):
        self.fetch_specs.append(spec)
        return ("OK", [(b"1 (BODY[] {1})", self.mensagens[int(num) - 1])])

    def logout(self):
        return ("BYE", [b""])


def _corre_com(monkeypatch, mensagens):
    falso = ImapFalso(mensagens)
    monkeypatch.setattr(server.imaplib, "IMAP4_SSL", lambda host, port: falso)
    anexos = server._fin_fetch_pdf_attachments_sync(
        {"host": "imap.exemplo.com", "port": 993, "user": "u", "pass": "p"})
    return falso, anexos


def test_a_caixa_abre_se_em_leitura_e_as_mensagens_nao_se_marcam_como_lidas(monkeypatch):
    falso, _ = _corre_com(monkeypatch, [_mensagem("Fornecedor <geral@fornecedor.pt>")])

    assert falso.select_args == ("INBOX", True), (
        "a INBOX foi aberta para escrita — o servidor marca as mensagens como lidas"
    )
    assert falso.fetch_specs == ["(BODY.PEEK[])"], (
        f"pediu {falso.fetch_specs} em vez de BODY.PEEK — RFC822 põe a flag \\Seen"
    )


def test_o_aviso_do_banco_nao_chega_a_pagar_uma_chamada_a_ia(monkeypatch):
    _, anexos = _corre_com(monkeypatch, [
        _mensagem('"alertas.empresas@millenniumbcp.pt" <alertas.empresas@millenniumbcp.pt>',
                  "NL 20260905082612.pdf"),
    ])

    assert anexos == [], (
        "o aviso do banco passou e vai ser enviado ao Gemini só para ele dizer "
        "que não é uma fatura — são 80 chamadas por mês numa quota de 20 por dia"
    )


def test_o_relatorio_da_teya_tambem_nao(monkeypatch):
    _, anexos = _corre_com(monkeypatch, [
        _mensagem("Teya <reporting@teya.com>", "Teya_settlement_report.pdf"),
    ])
    assert anexos == []


def test_a_fatura_de_um_fornecedor_continua_a_passar(monkeypatch):
    _, anexos = _corre_com(monkeypatch, [
        _mensagem("NESTLÉ PORTUGAL <faturas@nestle.pt>", "FT2026-812.pdf"),
    ])

    assert len(anexos) == 1, "a lista de exclusão apanhou uma fatura a sério"
    assert anexos[0]["file_name"] == "FT2026-812.pdf"


def test_a_glovo_nao_esta_excluida_porque_manda_faturas_de_comissao(monkeypatch):
    # A Glovo manda relatórios E faturas de comissão pelo mesmo domínio.
    # Excluí-la pouparia quota e perderia dinheiro a sério.
    _, anexos = _corre_com(monkeypatch, [
        _mensagem('"Glovo" <no-reply@glovoapp.com>', "fatura-comissao.pdf"),
    ])
    assert len(anexos) == 1
