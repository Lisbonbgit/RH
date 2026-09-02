"""**A leitura da caixa de email** — encontrar os relatórios da Uber, da Bolt e
da Glovo e transformá-los em números.

O caminho é o mesmo que o Financeiro já usa para as facturas dos fornecedores
(`server.py::fin_cron_ingest`): as caixas vêm da variável `IMAP_MAILBOXES` que
já está configurada no servidor, a extracção é feita pelo Gemini, e cada
mensagem está envolvida num `try/except` para que uma falha não leve a
execução inteira.

**Duas coisas são diferentes daquele caminho, e são-no de propósito.**

1. **Lê-se com `BODY.PEEK[]` e nunca com `RFC822`.** É a caixa de email REAL
   do dono. `RFC822` marca a mensagem como lida, e um agente que corre todas
   as segundas de madrugada esvaziava-lhe os não-lidos sem ninguém perceber
   porquê. `PEEK` é a mesma leitura sem tocar nas marcas.
2. **Interessa o CORPO da mensagem, e não só os anexos.** A factura de um
   fornecedor vem sempre em PDF; o resumo semanal da Uber traz os números no
   próprio email, e o detalhe (quando existe) num CSV ou PDF anexo. Manda-se
   tudo o que se conseguir ler.

**A regra que este módulo não pode quebrar: um valor que não esteja escrito no
relatório fica a `None`.** Nunca zero, nunca estimado, nunca calculado a
partir dos outros. Zero num relatório de dinheiro lê-se como "não vendemos
nada", e é uma afirmação que este módulo não tem como fazer.
"""
import base64
import email as _email
import imaplib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional

import httpx

from .calendario import quinzena_fechada, semana_fechada

logger = logging.getLogger(__name__)

# Quantos dias para trás se procura na caixa. Vinte cobre a quinzena da Glovo
# (que pode ter dezasseis dias) mais a folga de o relatório dela chegar uns
# dias depois de o período fechar. A semana da Uber/Bolt cabe aqui de sobra.
DIAS_DE_PROCURA = 20

# Travões defensivos: uma caixa com muita coisa não pode fazer o cron demorar
# minutos nem mandar dezenas de megabytes para a IA.
MAX_MENSAGENS_POR_CAIXA = 400
MAX_ANEXOS_POR_MENSAGEM = 4
MAX_BYTES_POR_ANEXO = 8 * 1024 * 1024
MAX_CARACTERES_DO_CORPO = 60000

# Como se reconhece cada plataforma. Procura-se no remetente E no assunto: a
# Uber manda de vários subdomínios ao longo do ano, e o assunto ("Uber Eats")
# apanha o que um domínio novo deixaria passar.
MARCAS = {
    "uber": ("uber.com", "ubereats", "uber eats", "uber portugal"),
    "bolt": ("bolt.eu", "boltfood", "bolt food", "bolt.food"),
    "glovo": ("glovoapp", "glovo.com", "glovo"),
}

# Os tipos de anexo que a IA consegue mesmo ler. O `.xlsx` fica de fora de
# propósito: não é aceite em linha pela API, e mandá-lo devolvia um erro que
# depois se lia como "o relatório não tinha números". Fica registado como
# anexo não lido, para o email o poder dizer por extenso.
MIMES_ACEITES = {
    ".pdf": "application/pdf",
    ".csv": "text/plain",
    ".txt": "text/plain",
    ".tsv": "text/plain",
}

PROMPT = (
    "És um assistente que lê relatórios de plataformas de entregas ao domicílio "
    "(Uber Eats, Bolt Food, Glovo) enviados por email a um restaurante em "
    "Portugal. Recebes o texto do email e, quando existirem, os anexos.\n\n"
    "Devolve APENAS um JSON válido com esta forma:\n"
    '{"e_relatorio": true se for um relatório/extracto/resumo de vendas, de '
    'pagamento ou de facturação — false se for publicidade, uma newsletter, um '
    'aviso de sistema ou qualquer outra coisa,\n'
    '"plataforma": "uber" | "bolt" | "glovo" | null,\n'
    '"periodo_inicio": "YYYY-MM-DD" ou null (a data em que começa o período a '
    "que o relatório diz respeito, se estiver escrita),\n"
    '"periodo_fim": "YYYY-MM-DD" ou null,\n'
    '"liquido": número ou null — o valor que a plataforma vai PAGAR ao '
    "restaurante (o líquido, depois de comissões e retenções),\n"
    '"bruto": número ou null — o total das vendas antes de descontos da '
    "plataforma,\n"
    '"pedidos": número inteiro ou null — quantos pedidos/encomendas,\n'
    '"comissao": número ou null — a comissão cobrada pela plataforma,\n'
    '"taxas": número ou null — outras taxas/serviços cobrados (marketing, '
    "publicidade, entrega, embalagem),\n"
    '"ajustes": número ou null — estornos, reembolsos, correcções e '
    "compensações (negativo se for a descontar),\n"
    '"iva": número ou null,\n'
    '"moeda": "EUR" ou o código que constar,\n'
    '"lojas": [{"nome": "nome da loja", "liquido": número ou null, "pedidos": '
    "número ou null}] — só se o relatório separar por loja; [] se não separar,\n"
    '"problemas": ["frase curta"] — pedidos cancelados, reembolsos a clientes, '
    "reclamações, cobranças inesperadas, avisos ou penalizações mencionados; [] "
    "se não houver nenhum,\n"
    '"notas": "uma frase curta com o que mais importa" ou null}\n\n'
    "REGRAS ABSOLUTAS:\n"
    "- NÃO INVENTES NENHUM NÚMERO. Um valor que não esteja escrito no documento "
    "é null. Nunca zero para dizer 'não sei'.\n"
    "- Não calcules valores que não estejam escritos (não somes, não subtraias, "
    "não convershas moedas).\n"
    "- Os valores são números, sem símbolo de moeda e com ponto decimal.\n"
    "- Escreve os 'problemas' e as 'notas' em português de Portugal."
)


# --- O que se lê de uma mensagem (puro: recebe uma mensagem já construída) ---

class _SoTexto(HTMLParser):
    """Tira as etiquetas de um corpo em HTML.

    `HTMLParser` é da biblioteca padrão e chega bem para isto: o que interessa
    à IA são os números e as palavras à volta deles, não a marcação. O `style`
    e o `script` são saltados porque o CSS de um email da Uber é maior do que
    o relatório e enchia o pedido de ruído.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: List[str] = []
        self._saltar = False

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._saltar = True
        elif tag in ("br", "tr", "p", "div", "table", "li"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._saltar = False
        elif tag in ("td", "th"):
            self.partes.append("\t")

    def handle_data(self, dados):
        if not self._saltar:
            self.partes.append(dados)

    def texto(self) -> str:
        junto = "".join(self.partes)
        # Linhas vazias a mais não acrescentam nada e pagam-se em tokens.
        junto = re.sub(r"[ \t]+", " ", junto)
        return re.sub(r"\n\s*\n+", "\n", junto).strip()


def _cabecalho(msg, nome: str) -> str:
    """Um cabeçalho já descodificado (o `Subject` vem muitas vezes em
    `=?UTF-8?B?...?=`, e comparar marcas contra isso não acertava em nada)."""
    bruto = msg.get(nome)
    if not bruto:
        return ""
    try:
        return str(make_header(decode_header(bruto)))
    except Exception:  # noqa: BLE001 — um cabeçalho estragado não pára a leitura
        return str(bruto)


def classificar(remetente: str, assunto: str) -> Optional[str]:
    """De que plataforma é esta mensagem, ou `None` se não for de nenhuma."""
    alvo = ("%s %s" % (remetente or "", assunto or "")).lower()
    for chave, marcas in MARCAS.items():
        if any(marca in alvo for marca in marcas):
            return chave
    return None


def texto_da_mensagem(msg) -> str:
    """O corpo da mensagem em texto simples.

    Prefere-se a parte `text/plain` quando ela existe (é o mesmo conteúdo sem
    a marcação); só quando não existe é que se desmonta o HTML.
    """
    simples, html = [], []
    for parte in msg.walk():
        if parte.get_content_maintype() == "multipart":
            continue
        if parte.get_filename():  # é anexo, trata-se noutro sítio
            continue
        tipo = (parte.get_content_type() or "").lower()
        if tipo not in ("text/plain", "text/html"):
            continue
        try:
            carga = parte.get_payload(decode=True) or b""
            texto = carga.decode(parte.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        (simples if tipo == "text/plain" else html).append(texto)

    if simples:
        junto = "\n".join(simples).strip()
        if junto:
            return junto[:MAX_CARACTERES_DO_CORPO]
    if html:
        leitor = _SoTexto()
        try:
            leitor.feed("\n".join(html))
        except Exception:  # noqa: BLE001
            return ""
        return leitor.texto()[:MAX_CARACTERES_DO_CORPO]
    return ""


def anexos_da_mensagem(msg) -> Dict:
    """`{"lidos": [{nome, mime, bytes}], "ignorados": [nome]}`.

    Os ignorados não se calam: um `.xlsx` que não se consegue ler é
    exactamente a informação que falta ao email para explicar um número em
    falta.
    """
    lidos, ignorados = [], []
    for parte in msg.walk():
        if parte.get_content_maintype() == "multipart":
            continue
        nome = parte.get_filename()
        if not nome:
            continue
        try:
            nome = str(make_header(decode_header(nome)))
        except Exception:  # noqa: BLE001
            pass
        extensao = os.path.splitext(nome.lower())[1]
        mime = MIMES_ACEITES.get(extensao)
        if not mime:
            ignorados.append(nome)
            continue
        if len(lidos) >= MAX_ANEXOS_POR_MENSAGEM:
            ignorados.append(nome)
            continue
        try:
            carga = parte.get_payload(decode=True) or b""
        except Exception:  # noqa: BLE001
            ignorados.append(nome)
            continue
        if not carga or len(carga) > MAX_BYTES_POR_ANEXO:
            ignorados.append(nome)
            continue
        lidos.append({"nome": nome, "mime": mime, "bytes": carga})
    return {"lidos": lidos, "ignorados": ignorados}


def data_da_mensagem(msg) -> Optional[date]:
    """O dia em que a mensagem foi enviada, em hora de Lisboa aproximada pelo
    fuso que vem no próprio cabeçalho. Serve de recurso quando o relatório não
    diz a que período diz respeito."""
    bruto = msg.get("Date")
    if not bruto:
        return None
    try:
        instante = parsedate_to_datetime(bruto)
    except Exception:  # noqa: BLE001
        return None
    if instante is None:
        return None
    return instante.date()


# --- A extracção pela IA -----------------------------------------------------

def _chamar_gemini(partes: List[Dict], timeout: int = 180) -> str:
    """O pedido ao Gemini. Devolve o texto em cru, ou `"ERRO:..."`.

    É uma segunda cópia do `_fin_gemini_call` do `server.py`, e é-o de
    propósito: este pacote é importado PELO `server.py`, e importá-lo de volta
    fechava um ciclo que impedia a API de arrancar. Difere no que interessa —
    aqui vão várias partes (o texto do email mais os anexos) e não um PDF só.
    """
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        return "ERRO:sem GEMINI_API_KEY no servidor"
    modelo = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    corpo = {
        "contents": [{"parts": partes}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
           % modelo)
    try:
        with httpx.Client(timeout=timeout) as cliente:
            # A chave vai no cabeçalho e não no URL: no URL aparecia nos registos.
            resposta = cliente.post(
                url,
                headers={"content-type": "application/json", "x-goog-api-key": chave},
                json=corpo,
            )
    except Exception as e:  # noqa: BLE001
        return "ERRO:rede: %s" % e
    if resposta.status_code >= 400:
        try:
            detalhe = resposta.json().get("error", {}).get("message")
        except Exception:  # noqa: BLE001
            detalhe = None
        return "ERRO:%s" % (detalhe or "HTTP %d" % resposta.status_code)
    try:
        dados = resposta.json()
        candidato = (dados.get("candidates") or [{}])[0]
        pedacos = (candidato.get("content") or {}).get("parts") or [{}]
        return "".join(p.get("text", "") for p in pedacos if isinstance(p, dict))
    except Exception:  # noqa: BLE001
        return "ERRO:resposta da IA ilegível"


def ler_json_da_ia(cru: str) -> Dict:
    """O dicionário que a IA devolveu, ou `{"erro": "..."}`.

    Nunca levanta: uma resposta estragada tem de virar uma linha "não foi
    possível ler" no email, e não um cron que rebenta a meio e deixa as outras
    plataformas por ler.
    """
    if not cru:
        return {"erro": "a IA não respondeu"}
    if cru.startswith("ERRO:"):
        return {"erro": cru[len("ERRO:"):]}
    encontrado = re.search(r"\{[\s\S]*\}", cru)
    if not encontrado:
        return {"erro": "a IA não devolveu JSON"}
    try:
        dados = json.loads(encontrado.group(0))
    except Exception:  # noqa: BLE001
        return {"erro": "o JSON da IA está mal formado"}
    return dados if isinstance(dados, dict) else {"erro": "o JSON da IA não é um objecto"}


# --- Do que a IA devolveu para o registo que se guarda -----------------------

def _numero(valor) -> Optional[float]:
    """Um número, ou `None`. **Nunca zero por omissão** — ver a docstring do
    módulo. Uma string com vírgula decimal (a IA às vezes escapa-se) é aceite;
    tudo o resto que não seja número vira `None`."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return round(float(valor), 2)
    texto = str(valor).strip().replace("€", "").replace(" ", "")
    if not texto:
        return None
    # "1.234,56" -> "1234.56"; "1234.56" fica como está.
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return round(float(texto), 2)
    except ValueError:
        return None


def _inteiro(valor) -> Optional[int]:
    numero = _numero(valor)
    return None if numero is None else int(round(numero))


def _data(valor) -> Optional[date]:
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def periodo_do_relatorio(extraido: Dict, plataforma: str,
                         data_do_email: Optional[date], hoje: date) -> Dict:
    """A que período pertence este relatório — e porque é que se acredita nisso.

    Prefere-se o que vem escrito no documento. Só que uma data mal lida arquiva
    o relatório debaixo da semana errada, e a semana errada não é um número
    errado: é o relatório desta semana a não aparecer e o da passada a ser
    reescrito. Por isso o que vem da IA é CONFERIDO — tem de ser um intervalo
    com a duração certa (uma semana tem 7 dias, uma quinzena entre 13 e 16) e
    não pode estar no futuro.

    Falhando isso, deriva-se do calendário a partir da data do email: os
    relatórios chegam depois de o período fechar, por isso o período é o último
    que fechou antes da mensagem. Sem data no email, usa-se o dia de hoje.
    """
    tipo = "quinzena" if plataforma == "glovo" else "semana"
    inicio = _data(extraido.get("periodo_inicio"))
    fim = _data(extraido.get("periodo_fim"))
    if inicio and fim and inicio <= fim and fim <= hoje:
        dias = (fim - inicio).days + 1
        aceitavel = (dias == 7) if tipo == "semana" else (13 <= dias <= 16)
        if aceitavel:
            return {"tipo": tipo, "inicio": inicio, "fim": fim, "origem": "relatório"}

    referencia = data_do_email or hoje
    if tipo == "quinzena":
        inicio, fim = quinzena_fechada(referencia)
    else:
        inicio, fim = semana_fechada(referencia)
    return {"tipo": tipo, "inicio": inicio, "fim": fim, "origem": "calendário"}


def montar_registo(extraido: Dict, *, plataforma: str, periodo: Dict,
                   origem: Dict) -> Dict:
    """O documento que vai para a base de dados, com uma linha por plataforma e
    período. O `id` é a chave da idempotência: correr o cron duas vezes escreve
    duas vezes o mesmo documento, e não dois documentos."""
    lojas = []
    for loja in extraido.get("lojas") or []:
        if not isinstance(loja, dict):
            continue
        nome = str(loja.get("nome") or "").strip()
        if not nome:
            continue
        lojas.append({
            "nome": nome[:120],
            "liquido": _numero(loja.get("liquido")),
            "pedidos": _inteiro(loja.get("pedidos")),
        })

    problemas = []
    for problema in extraido.get("problemas") or []:
        texto = str(problema or "").strip()
        if texto:
            problemas.append(texto[:300])

    inicio, fim = periodo["inicio"].isoformat(), periodo["fim"].isoformat()
    return {
        "id": "%s:%s..%s" % (plataforma, inicio, fim),
        "plataforma": plataforma,
        "tipo": periodo["tipo"],
        "periodo_inicio": inicio,
        "periodo_fim": fim,
        "periodo_origem": periodo["origem"],
        "valores": {
            "liquido": _numero(extraido.get("liquido")),
            "bruto": _numero(extraido.get("bruto")),
            "pedidos": _inteiro(extraido.get("pedidos")),
            "comissao": _numero(extraido.get("comissao")),
            "taxas": _numero(extraido.get("taxas")),
            "ajustes": _numero(extraido.get("ajustes")),
            "iva": _numero(extraido.get("iva")),
            "moeda": str(extraido.get("moeda") or "EUR")[:8],
        },
        "lojas": lojas,
        "problemas": problemas,
        "notas": (str(extraido.get("notas")).strip()[:500]
                  if extraido.get("notas") else None),
        "origem": origem,
        "lido_em": datetime.now(timezone.utc).isoformat(),
    }


# --- O IMAP (a única parte que fala com a rede) ------------------------------

def _mensagens_da_caixa(caixa: Dict, dias: int) -> List:
    """As mensagens dos últimos `dias`, SEM as marcar como lidas.

    `BODY.PEEK[]` e não `RFC822`: ver a docstring do módulo. É a caixa de email
    do dono, e um agente automático não lhe pode mexer nos não-lidos.
    """
    ligacao = imaplib.IMAP4_SSL(caixa.get("host"), int(caixa.get("port") or 993))
    try:
        ligacao.login(caixa.get("user"), caixa.get("pass"))
        ligacao.select("INBOX", readonly=True)
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        estado, resultado = ligacao.search(None, "SINCE", desde)
        numeros = resultado[0].split() if (estado == "OK" and resultado and resultado[0]) else []
        numeros = list(reversed(numeros))[:MAX_MENSAGENS_POR_CAIXA]
        mensagens = []
        for numero in numeros:
            try:
                estado, dados = ligacao.fetch(numero, "(BODY.PEEK[])")
                if estado != "OK" or not dados or not dados[0]:
                    continue
                mensagens.append(_email.message_from_bytes(dados[0][1]))
            except Exception:  # noqa: BLE001 — uma mensagem estragada não pára o resto
                continue
        return mensagens
    finally:
        try:
            ligacao.logout()
        except Exception:  # noqa: BLE001
            pass


def caixas_configuradas() -> List[Dict]:
    """As caixas do `IMAP_MAILBOXES` — a MESMA variável que o Financeiro já
    usa para as facturas. Não há variável nova para isto: a caixa é a mesma, e
    duplicá-la era arriscar que uma delas ficasse por actualizar."""
    cru = os.environ.get("IMAP_MAILBOXES") or "[]"
    try:
        caixas = json.loads(cru)
    except Exception:  # noqa: BLE001
        logger.warning("[plataformas] IMAP_MAILBOXES não é JSON válido (len=%d)", len(cru))
        return []
    return [c for c in caixas if isinstance(c, dict) and c.get("host")] \
        if isinstance(caixas, list) else []


def recolher(hoje: date, caixas: Optional[List[Dict]] = None,
             dias: int = DIAS_DE_PROCURA) -> Dict:
    """Lê as caixas, manda o que encontrar à IA e devolve
    `{"registos": [...], "avisos": [...]}`.

    Síncrona de propósito (imaplib e httpx são-no): quem chama corre-a numa
    thread, como o `fin_cron_ingest` faz.

    Quando a mesma plataforma e o mesmo período aparecem em duas mensagens (um
    reenvio, ou a mensagem em duas caixas), fica a MAIS RECENTE — é a que a
    plataforma corrigiu.
    """
    caixas = caixas if caixas is not None else caixas_configuradas()
    registos: Dict[str, Dict] = {}
    avisos: List[str] = []
    if not caixas:
        avisos.append("Não há nenhuma caixa de email configurada no servidor "
                      "(IMAP_MAILBOXES).")
        return {"registos": [], "avisos": avisos}

    for caixa in caixas:
        etiqueta = str(caixa.get("user") or caixa.get("host") or "caixa")
        try:
            mensagens = _mensagens_da_caixa(caixa, dias)
        except Exception as e:  # noqa: BLE001
            avisos.append("Não foi possível ler a caixa %s: %s" % (etiqueta, e))
            continue

        for msg in mensagens:
            remetente = _cabecalho(msg, "From")
            assunto = _cabecalho(msg, "Subject")
            plataforma = classificar(remetente, assunto)
            if not plataforma:
                continue

            corpo = texto_da_mensagem(msg)
            anexos = anexos_da_mensagem(msg)
            if not corpo and not anexos["lidos"]:
                continue

            partes = [{"text": PROMPT}, {"text": "ASSUNTO: %s\nDE: %s\n\n%s"
                                                 % (assunto, remetente, corpo)}]
            for anexo in anexos["lidos"]:
                partes.append({"inline_data": {
                    "mime_type": anexo["mime"],
                    "data": base64.b64encode(anexo["bytes"]).decode(),
                }})

            extraido = ler_json_da_ia(_chamar_gemini(partes))
            if extraido.get("erro"):
                avisos.append("«%s» não foi lido: %s" % (assunto[:80], extraido["erro"]))
                continue
            if not extraido.get("e_relatorio"):
                continue

            periodo = periodo_do_relatorio(
                extraido, plataforma, data_da_mensagem(msg), hoje)
            enviada_em = data_da_mensagem(msg)
            registo = montar_registo(
                extraido, plataforma=plataforma, periodo=periodo,
                origem={
                    "assunto": assunto[:200],
                    "remetente": remetente[:200],
                    "data": enviada_em.isoformat() if enviada_em else None,
                    "caixa": etiqueta,
                    "anexos_lidos": [a["nome"] for a in anexos["lidos"]],
                    "anexos_ignorados": anexos["ignorados"],
                })
            if anexos["ignorados"]:
                avisos.append(
                    "%s: o anexo %s não pôde ser lido (formato não suportado)."
                    % (assunto[:60], ", ".join(anexos["ignorados"][:3])))

            anterior = registos.get(registo["id"])
            if anterior is None or (registo["origem"].get("data") or "") >= \
                    (anterior["origem"].get("data") or ""):
                registos[registo["id"]] = registo

    return {"registos": list(registos.values()), "avisos": avisos}
