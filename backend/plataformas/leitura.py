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
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlparse
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

# **Quem manda relatórios a sério — e é o REMETENTE que os separa da
# publicidade.**
#
# A primeira versão disto procurava "uber", "bolt" e "glovo" em qualquer parte
# do remetente ou do assunto. Numa caixa real apanhou **73 mensagens em 20
# dias**, e a maioria era publicidade: «5% de desconto em Sacos
# Personalizados», «VOLTA ÀS AULAS! -10€ em Sacos Glovo», «Campanha nacional:
# 40% de desconto». Todas iam à IA. O plano gratuito do Gemini permite 20
# pedidos por minuto, por isso a partir da 21.ª todas falhavam por quota — e a
# recolha acabava sem encontrar um único relatório.
#
# As três plataformas separam bem os dois mundos por endereço de envio:
#
#   Uber   relatórios noreply@uber.com        publicidade eats@uber.com
#   Bolt   relatórios portugal-food@bolt.eu   publicidade *-marketing.bolt.eu
#   Glovo  relatórios no-reply@glovoapp.com   publicidade email.glovostore.com
#                                                         partner.glovoapp.com
#
# O assunto confirma. Os dois juntos deixam passar ~15 mensagens por janela em
# vez de 73 — e nenhuma delas é uma promoção.
RELATORIOS = {
    "uber": {
        # «Resumo dos Pagamentos Uber Eats para L'açaí Amadora Aug 24 - Aug 30, 2026»
        "de": ("noreply@uber.com",),
        "assunto": ("resumo dos pagamentos", "payments summary", "payment summary"),
    },
    "bolt": {
        # «Relatório semanal da Bolt Food»
        "de": ("portugal-food@bolt.eu",),
        "assunto": ("relatório semanal", "relatorio semanal", "weekly report"),
    },
    "glovo": {
        # «Glovoapp Spain Platform S.L. - Extrato I26LQPOMT1000017»
        "de": ("no-reply@glovoapp.com",),
        "assunto": ("extrato", "statement"),
    },
}

# **De onde é que se aceita descarregar um ficheiro.**
#
# A Bolt não põe um único número no email: manda links para o relatório semanal
# em XLSX/CSV/PDF, e esses links abrem sem login. Segui-los é a única forma de
# saber quanto ela vai pagar — mas seguir um endereço que veio DENTRO de um
# email é abrir uma porta, e por isso ela só abre para estes servidores.
#
# A verificação é feita DUAS vezes: no endereço de destino escrito no email, e
# outra vez no endereço onde a descarga acabou por parar. As duas são precisas
# porque os links da Bolt passam por um redireccionador da Amazon
# (`awstrack.me`) — o primeiro endereço não é o final, e confiar só num deles
# deixava passar um redireccionamento para outro sítio qualquer.
DOMINIOS_DE_DESCARGA = {
    "bolt": ("delivery-reporting.bolt.eu", "doclink.live.boltsvc.net"),
}

# Quantos ficheiros se descarregam por mensagem. Três chegam: o CSV (que traz
# os totais escritos), o XLSX e a fatura em PDF.
MAX_DESCARGAS_POR_MENSAGEM = 3

# **Espaçar os pedidos à IA, em vez de bater na parede e esperar.**
#
# O plano gratuito do Gemini permite 20 pedidos por minuto. Disparar quinze de
# seguida esgota a quota ao 20.º e a partir daí cada pedido custa uma espera de
# quase um minuto — uma recolha inteira passava de segundos a mais de uma hora,
# e o botão do ecrã desiste aos cinco minutos.
#
# Três segundos e dois décimos entre pedidos dão 18 por minuto, com folga. Uma
# recolha normal (~15 mensagens) paga com isto uns cinquenta segundos, e não
# apanha um único 429.
INTERVALO_ENTRE_CHAMADAS = 3.2

# **O modelo é FIXO, e não `gemini-flash-latest`.**
#
# Não é por causa de quota: **a quota do plano gratuito é por MINUTO, não por
# dia** — medido a 2026-09-06 com 25 pedidos seguidos, que passaram todos com
# duas esperas pelo meio, 107 segundos ao todo. (Escrevi aqui o contrário
# durante um dia inteiro, a partir da mensagem de erro, e construí a correcção
# errada em cima disso. Ver a nota do 429 mais abaixo.)
#
# É fixo porque um alias muda de modelo debaixo dos pés: o `-latest` aponta
# sempre para o mais recente, e um relatório que diz quanto dinheiro vamos
# receber não deve trocar de leitor sem alguém decidir.
#
# **Variável PRÓPRIA e não a `GEMINI_MODEL`**: essa é a da ingestão de
# facturas, e mexer-lhe mudava o modelo que lê as facturas dos fornecedores —
# outro problema, de outro dono.
MODELO_POR_OMISSAO = "gemini-3.5-flash"


# **O tecto do tempo que uma recolha pode passar à espera da quota.** Quando a
# ingestão de facturas já gastou o minuto, ainda há 429 — mas uma recolha que
# demore mais do que isto é uma recolha que ninguém vê acabar. Ao estourar,
# desiste-se: as mensagens por ler ficam como aviso, e a próxima corrida
# apanha-as (nada foi gravado a meio).
ORCAMENTO_DE_ESPERA_SEGUNDOS = 150.0

_ultima_chamada = 0.0
_espera_gasta = 0.0


def reiniciar_orcamento() -> None:
    """Chamado no início de cada recolha: o orçamento de espera E a lista de
    modelos esgotados são POR RECOLHA, não por processo. A quota é diária, mas
    a corrida seguinte tem de voltar a tentar — pode ser noutro dia."""
    global _espera_gasta
    _espera_gasta = 0.0

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
    '"loja": "o nome da loja/restaurante a que este relatório diz respeito, tal '
    "como aparece escrito (ex.: \"L'açaí Amadora\") — as plataformas mandam UM "
    'relatório POR LOJA; null se não estiver escrito em lado nenhum",\n'
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
    "- **USA SÓ O BLOCO DO PERÍODO QUE VEM NO ASSUNTO.** Estes relatórios trazem "
    "muitas vezes DOIS conjuntos de totais parecidos: o do período em causa e um "
    "resumo CONSOLIDADO de outro período (por exemplo, a Uber junta um 'Resumo "
    "consolidado do mês anterior' com o total do mês inteiro). O do período está "
    "debaixo de 'Discriminação dos pagamentos' e acaba em 'Pagamento líquido'; o "
    "consolidado acaba em 'Total líquido'. **Ignora por completo o consolidado** "
    "— nem o valor, nem o número de pedidos, nem as taxas. Se tiveres dúvida "
    "sobre qual é qual, escolhe aquele cujo número de pedidos bate com o total "
    "da tabela diária do período.\n"
    "- NÃO INVENTES NENHUM NÚMERO. Um valor que não esteja escrito no documento "
    "é null. Nunca zero para dizer 'não sei'.\n"
    "- Não calcules valores em dinheiro que não estejam escritos (não somes, não "
    "subtraias, não converhas moedas). Muitos destes relatórios trazem os totais "
    "escritos no fim (ex.: 'Ganhos Semanais', 'Comissão semanal', 'Pagamento "
    "líquido') — usa esses.\n"
    "- A ÚNICA conta que podes fazer é CONTAR as linhas de pedidos de uma "
    "listagem, para o campo 'pedidos', quando o total de pedidos não estiver "
    "escrito em lado nenhum.\n"
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
    """De que plataforma é este RELATÓRIO, ou `None`.

    Exige as duas coisas — o endereço de envio **e** o assunto. Uma promoção
    da Glovo tem "glovo" por todo o lado e não é um relatório; um relatório da
    Uber vem sempre do mesmo endereço. Ver a nota em `RELATORIOS`, e o que
    custou descobri-lo.
    """
    de = (remetente or "").lower()
    titulo = (assunto or "").lower()
    for chave, regra in RELATORIOS.items():
        if not any(endereco in de for endereco in regra["de"]):
            continue
        if any(pedaco in titulo for pedaco in regra["assunto"]):
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


def html_da_mensagem(msg) -> str:
    """O HTML em cru — só para se apanharem os `href`. O texto simples já os
    perdeu, e é neles que a Bolt esconde o relatório."""
    partes = []
    for parte in msg.walk():
        if (parte.get_content_type() or "").lower() != "text/html":
            continue
        if parte.get_filename():
            continue
        try:
            carga = parte.get_payload(decode=True) or b""
            partes.append(carga.decode(parte.get_content_charset() or "utf-8", "replace"))
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(partes)


def _destino_pretendido(url: str) -> str:
    """O servidor a que este endereço quer chegar.

    Os links da Bolt vão embrulhados num redireccionador da Amazon
    (`https://xxx.awstrack.me/L0/https:%2F%2Fdelivery-reporting.bolt.eu%2F...`),
    por isso o servidor escrito no endereço não é o servidor onde o ficheiro
    está. Desembrulha-se **um** nível: procura-se um endereço absoluto dentro
    do caminho e devolve-se o servidor desse.

    Nunca se procura no `?query`: um endereço permitido metido num parâmetro
    (`...?next=https://delivery-reporting.bolt.eu`) não faz de um servidor
    estranho um servidor de confiança — era exactamente assim que a barreira
    se contornava.
    """
    partido = urlparse(url)
    caminho = unquote(partido.path or "")
    encontrado = re.search(r"https?://([^/\s]+)", caminho)
    if encontrado:
        return encontrado.group(1).lower()
    return (partido.netloc or "").lower()


def alvos_de_descarga(html: str, plataforma: str) -> List[str]:
    """Os endereços deste email de onde se aceita descarregar um ficheiro.

    Só os das plataformas que precisam disso (hoje, a Bolt), e só os que
    apontam para os servidores declarados em `DOMINIOS_DE_DESCARGA`.
    """
    permitidos = DOMINIOS_DE_DESCARGA.get(plataforma)
    if not permitidos or not html:
        return []
    saida: List[str] = []
    for url in re.findall(r'href="(https?://[^"\s]+)"', html):
        destino = _destino_pretendido(url)
        if not any(destino == d or destino.endswith("." + d) for d in permitidos):
            continue
        if url not in saida:
            saida.append(url)
    return saida


def _tipo_do_ficheiro(content_type: str, url: str) -> Optional[str]:
    """O que se manda à IA e o que não vale a pena mandar.

    O `.xlsx` fica de fora: a API não o aceita em linha, e o mesmo relatório
    vem sempre também em CSV — que é o que traz os totais escritos.
    """
    tipo = (content_type or "").split(";")[0].strip().lower()
    if "pdf" in tipo:
        return "application/pdf"
    if "csv" in tipo or tipo in ("text/plain", "text/tab-separated-values"):
        return "text/plain"
    return None


def descarregar_ligados(html: str, plataforma: str,
                        limite: int = MAX_DESCARGAS_POR_MENSAGEM) -> Dict:
    """Vai buscar os relatórios que o email só referenciou por link.

    Devolve o mesmo formato de `anexos_da_mensagem`. Verifica o servidor
    **antes** de pedir e **outra vez** depois de seguir os
    redireccionamentos — ver a nota em `DOMINIOS_DE_DESCARGA`.
    """
    permitidos = DOMINIOS_DE_DESCARGA.get(plataforma) or ()
    lidos, ignorados = [], []
    for url in alvos_de_descarga(html, plataforma):
        if len(lidos) >= limite:
            break
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as cliente:
                resposta = cliente.get(url)
        except Exception as e:  # noqa: BLE001
            ignorados.append("descarga falhou: %s" % str(e)[:80])
            continue

        # Onde a descarga foi PARAR, e não onde ela dizia que ia.
        final = (urlparse(str(resposta.url)).netloc or "").lower()
        if not any(final == d or final.endswith("." + d) for d in permitidos):
            ignorados.append("descarga recusada: acabou em %s" % (final or "?"))
            continue
        if resposta.status_code != 200:
            ignorados.append("descarga devolveu %d" % resposta.status_code)
            continue

        mime = _tipo_do_ficheiro(resposta.headers.get("content-type", ""), url)
        carga = resposta.content or b""
        if not mime:
            # Um XLSX não é uma falha: o CSV do mesmo relatório vem a seguir.
            continue
        if not carga or len(carga) > MAX_BYTES_POR_ANEXO:
            ignorados.append("ficheiro vazio ou grande de mais")
            continue
        nome = os.path.basename(urlparse(str(resposta.url)).path) or "relatorio"
        lidos.append({"nome": nome[:120], "mime": mime, "bytes": carga})
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

def _pedir(modelo: str, partes: List[Dict], chave: str, timeout: int):
    """Um pedido. Devolve a resposta do httpx, ou levanta o que a rede levantar."""
    global _ultima_chamada
    # Espaçar em vez de bater na parede — ver `INTERVALO_ENTRE_CHAMADAS`.
    desde_a_ultima = time.monotonic() - _ultima_chamada
    if desde_a_ultima < INTERVALO_ENTRE_CHAMADAS:
        time.sleep(INTERVALO_ENTRE_CHAMADAS - desde_a_ultima)
    _ultima_chamada = time.monotonic()
    with httpx.Client(timeout=timeout) as cliente:
        # A chave no cabeçalho e não no URL: no URL aparecia nos registos.
        return cliente.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "%s:generateContent" % modelo,
            headers={"content-type": "application/json", "x-goog-api-key": chave},
            json={
                "contents": [{"parts": partes}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 4096,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingLevel": "low"},
                },
            },
        )


def _mensagem_de_erro(resposta) -> str:
    try:
        return resposta.json().get("error", {}).get("message", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _quanto_esperar(resposta, por_omissao: float) -> float:
    """O tempo que o próprio Google diz para esperar, entre 5 e 65 segundos."""
    encontrado = re.search(r"retry in ([\d.]+)s", _mensagem_de_erro(resposta))
    pedido = float(encontrado.group(1)) + 1.0 if encontrado else por_omissao
    return min(max(pedido, 5.0), 65.0)


def _chamar_gemini(partes: List[Dict], timeout: int = 180) -> str:
    """O pedido ao Gemini. Devolve o texto em cru, ou `"ERRO:..."`.

    É uma segunda cópia do `_fin_gemini_call` do `server.py`, e é-o de
    propósito: este pacote é importado PELO `server.py`, e importá-lo de volta
    fechava um ciclo que impedia a API de arrancar. Difere no que interessa —
    aqui vão várias partes (o texto do email mais os anexos) e não um PDF só.

    **O 429 espera-se. Não se troca de modelo.**

    Esta função já teve uma versão que, ao apanhar um 429, marcava o modelo
    como esgotado e passava ao seguinte de uma lista de quatro. Foi construída
    sobre uma conclusão errada — que a quota gratuita era de 20 pedidos por
    DIA, lida à pressa da mensagem de erro. **É por minuto**: medido a
    2026-09-06 com 25 pedidos seguidos ao mesmo modelo, que passaram todos com
    duas esperas pelo meio, 107 segundos ao todo. A ingestão de facturas
    espera desde sempre e leu 787 PDFs, 47 deles num só dia.

    Trocar de modelo **piorava** as coisas: com o minuto saturado, os quatro
    modelos apanhavam 429 em treze segundos, ficavam todos marcados como
    esgotados, e o resto da recolha falhava inteira — uma barreira de segundos
    transformada numa avaria da corrida toda. Esperar os vinte segundos que o
    Google indica resolve, e é tudo o que é preciso.
    """
    global _espera_gasta
    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        return "ERRO:sem GEMINI_API_KEY no servidor"
    modelo = os.environ.get("PLATAFORMAS_GEMINI_MODEL", MODELO_POR_OMISSAO)

    for tentativa in range(1, 7):
        try:
            resposta = _pedir(modelo, partes, chave, timeout)
        except Exception as e:  # noqa: BLE001
            return "ERRO:rede: %s" % e

        # 429 é a quota do minuto; 503 é «este modelo está com muita procura».
        # As duas passam sozinhas — o remédio das duas é o mesmo: esperar.
        if resposta.status_code in (429, 503) and tentativa < 6:
            espera = _quanto_esperar(resposta, 22.0 if resposta.status_code == 429 else 12.0)
            if _espera_gasta + espera > ORCAMENTO_DE_ESPERA_SEGUNDOS:
                return ("ERRO:a IA está a recusar por excesso de pedidos e o tempo "
                        "de espera desta recolha esgotou-se — o que ficou por ler "
                        "entra na próxima")
            _espera_gasta += espera
            logger.info("[plataformas] %s devolveu %d: a esperar %.0fs (gasto %.0fs)",
                        modelo, resposta.status_code, espera, _espera_gasta)
            time.sleep(espera)
            continue

        if resposta.status_code >= 400:
            return "ERRO:%s" % (_mensagem_de_erro(resposta)
                                or "HTTP %d" % resposta.status_code)

        try:
            dados = resposta.json()
            candidato = (dados.get("candidates") or [{}])[0]
            pedacos = (candidato.get("content") or {}).get("parts") or [{}]
            return "".join(p.get("text", "") for p in pedacos if isinstance(p, dict))
        except Exception:  # noqa: BLE001
            return "ERRO:resposta da IA ilegível"

    return ("ERRO:a IA recusou seis vezes seguidas por excesso de pedidos — o que "
            "ficou por ler entra na próxima recolha")


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


def pedidos_da_tabela_do_periodo(corpo: str) -> Optional[int]:
    """Quantos pedidos diz a TABELA DIÁRIA do período — lida por nós, não pela IA.

    Estes relatórios trazem uma tabela com uma linha por dia e uma linha de
    `Total`, e essa tabela é sempre a do período em causa. É o único número do
    email que se pode conferir sem perguntar a ninguém, e serve de padrão para
    apanhar a IA a ler o bloco errado.

    **Foi construído a partir de um erro real** (2026-09-07, L'açai Oeiras): a
    IA leu o «Resumo consolidado do mês anterior» em vez da semana e o email
    do dono anunciou 830,37 € em vez de 277,82 €. O número de pedidos
    denunciava-o — 79 (o mês) contra 24 (a semana) que a tabela diária dizia.

    `None` quando o relatório não traz tabela (a Bolt e a Glovo não trazem);
    aí não há conferência a fazer e os valores da IA passam como estão.
    """
    encontrado = re.search(r"^\s*Total\s+(\d{1,5})\s+[\d\s.,]+\s*€", corpo or "",
                           re.MULTILINE)
    return int(encontrado.group(1)) if encontrado else None


def _positivo(numero: Optional[float]) -> Optional[float]:
    """O mesmo número sem sinal — e `None` continua `None`, nunca zero."""
    return None if numero is None else abs(numero)


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


def chave_da_loja(nome) -> str:
    """`L'açaí Amadora` -> `lacai-amadora`. Sem acentos, sem apóstrofos e sem
    maiúsculas, para o mesmo nome escrito de duas maneiras dar a MESMA chave.

    A Uber escreve `L'açai Oeiras` numa semana e `L'açaí Oeiras` noutra (com e
    sem acento no i); sem esta normalização eram duas lojas diferentes, e o
    aviso de «faltou uma loja» disparava todas as semanas.
    """
    texto = unicodedata.normalize("NFD", str(nome or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn").lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:60]


def montar_registo(extraido: Dict, *, plataforma: str, periodo: Dict,
                   origem: Dict, chave_de_recurso: str = "") -> Dict:
    """O documento que vai para a base de dados: **um por plataforma, período e
    LOJA**.

    A loja entra na chave porque as plataformas mandam um relatório por loja —
    a Uber quatro por semana, a Glovo cinco por quinzena. Sem ela, os quatro
    documentos tinham o mesmo `id` e escreviam por cima uns dos outros: ficava
    o último, e o email de segunda mostrava o valor de UMA loja como se fosse o
    da semana inteira.

    `chave_de_recurso` (o `Message-ID` do email) só é usada quando não há
    maneira de saber a loja. É o menor dos males: dois relatórios sem loja
    ficam como dois registos (e o ecrã diz que não os soube identificar), em
    vez de um comer o outro em silêncio.
    """
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

    # A loja: o que a IA leu; senão, a única entrada da lista `lojas` (um
    # relatório de uma loja só costuma trazê-la aí).
    loja = str(extraido.get("loja") or "").strip()
    if not loja and len(lojas) == 1:
        loja = lojas[0]["nome"]
    chave = chave_da_loja(loja) or ("sem-loja-%s" % chave_da_loja(chave_de_recurso)
                                    or "sem-loja")

    inicio, fim = periodo["inicio"].isoformat(), periodo["fim"].isoformat()
    return {
        "id": "%s:%s..%s:%s" % (plataforma, inicio, fim, chave),
        "plataforma": plataforma,
        "loja": loja or None,
        "loja_chave": chave,
        "tipo": periodo["tipo"],
        "periodo_inicio": inicio,
        "periodo_fim": fim,
        "periodo_origem": periodo["origem"],
        "valores": {
            "liquido": _numero(extraido.get("liquido")),
            "bruto": _numero(extraido.get("bruto")),
            "pedidos": _inteiro(extraido.get("pedidos")),
            # **A comissão e as taxas guardam-se sempre POSITIVAS.** São
            # cobranças, e os relatórios escrevem-nas ora com sinal ora sem
            # ele — na primeira corrida a sério vieram `280.92` de uma loja e
            # `-217.29` de outra, no mesmo relatório da mesma semana. Somar as
            # duas dava um total que não quer dizer nada. Quem as mostra sabe
            # que são um custo (`ajustes` fica com sinal, porque aí ele diz
            # mesmo alguma coisa: um estorno desconta, uma compensação soma).
            "comissao": _positivo(_numero(extraido.get("comissao"))),
            "taxas": _positivo(_numero(extraido.get("taxas"))),
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


CORRECAO = (
    "ATENÇÃO: o número de pedidos que devolveste não bate com o total da tabela "
    "diária deste relatório, que diz %d pedidos. Isso quer dizer que leste o "
    "bloco errado — quase de certeza um resumo CONSOLIDADO de outro período "
    "(mês anterior), e não o período deste relatório. Lê outra vez, usando SÓ o "
    "bloco cujo total de pedidos é %d, e devolve o mesmo JSON."
)

# Os campos em dinheiro que se apagam quando não se consegue confiar na leitura.
# O `pedidos` fica de fora: quando a tabela diária o diz, ele é o único número
# que sabemos de certeza.
CAMPOS_DE_DINHEIRO = ("liquido", "bruto", "comissao", "taxas", "ajustes", "iva")


def conferir_contra_a_tabela(extraido: Dict, corpo: str, partes: List[Dict],
                             chamar=None) -> Dict:
    """Confere a leitura da IA contra a tabela diária do próprio relatório.

    **Nasceu de um erro que chegou ao email do dono** (2026-09-07): a IA leu o
    «Resumo consolidado do mês anterior» da Uber em vez da semana, e a loja de
    Oeiras foi anunciada com 830,37 € quando o que ela ia receber eram 277,82 €.
    Nas outras três lojas leu o bloco certo — e é essa inconsistência que faz
    de uma instrução melhor no prompt uma esperança, e não uma garantia.

    A tabela diária é o único número do email que se pode conferir sem
    perguntar a ninguém. Quando o total dela não bate com o que a IA devolveu,
    pergunta-se **uma** vez mais, a dizer-lhe qual é o total certo. Se ainda
    assim não bater, **apagam-se os valores em dinheiro** e diz-se porquê: um
    número errado num email sobre dinheiro é pior do que um «não consegui
    ler» — que é a regra deste módulo inteiro.
    """
    esperado = pedidos_da_tabela_do_periodo(corpo)
    if esperado is None:
        return extraido  # sem tabela não há conferência (Bolt e Glovo não trazem)
    if _inteiro(extraido.get("pedidos")) == esperado:
        return extraido

    chamar = chamar or _chamar_gemini
    segunda = ler_json_da_ia(chamar(partes + [{"text": CORRECAO % (esperado, esperado)}]))
    if not segunda.get("erro") and _inteiro(segunda.get("pedidos")) == esperado:
        return segunda

    seguro = dict(extraido)
    for campo in CAMPOS_DE_DINHEIRO:
        seguro[campo] = None
    seguro["pedidos"] = esperado
    seguro["problemas"] = list(extraido.get("problemas") or []) + [
        "Os valores deste relatório não puderam ser confirmados: a leitura "
        "devolveu %s pedidos e a tabela do período diz %d. Ficam por saber — "
        "vê o email original." % (extraido.get("pedidos"), esperado)]
    return seguro


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
        # **Pergunta-se ao servidor pelos remetentes, em vez de trazer a caixa
        # toda e filtrar aqui.** Uma destas caixas tem mil mensagens em vinte
        # dias; descarregar todas para deitar fora 985 era pagar a leitura
        # inteira de cada vez, e foi assim que a primeira versão ficou lenta.
        numeros = set()
        for regra in RELATORIOS.values():
            for endereco in regra["de"]:
                try:
                    estado, resultado = ligacao.search(
                        None, "SINCE", desde, "FROM", '"%s"' % endereco)
                except Exception:  # noqa: BLE001 — um critério recusado não pára os outros
                    continue
                if estado == "OK" and resultado and resultado[0]:
                    numeros.update(resultado[0].split())
        # **Do MAIS RECENTE para o mais antigo, e isto não é um detalhe.**
        #
        # A quota da IA é limitada e a recolha tem um orçamento de espera. Ao
        # ler pela ordem de chegada, o orçamento gastava-se nas semanas velhas
        # (que já estão gravadas de corridas anteriores) e a semana ATUAL — a
        # única de que o email de segunda fala — ficava por ler. Medido numa
        # caixa a sério: 20 relatórios lidos, todos de semanas passadas, e a
        # semana em causa sem um único.
        numeros = sorted(numeros, key=int, reverse=True)[:MAX_MENSAGENS_POR_CAIXA]
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
             dias: int = DIAS_DE_PROCURA,
             ja_lidos: Optional[set] = None) -> Dict:
    """Lê as caixas, manda o que encontrar à IA e devolve
    `{"registos": [...], "avisos": [...]}`.

    **`ja_lidos` são os `Message-ID` que já estão gravados, e é o que faz isto
    caber na quota.** A janela é de vinte dias, mas de uma corrida para a
    outra só há meia dúzia de emails novos — sem esta lista, cada recolha
    voltava a pagar à IA pelas três semanas anteriores, que já estão na base de
    dados. Uma mensagem que FALHOU a ser lida não está gravada, logo não está
    nesta lista, logo é tentada outra vez na corrida seguinte.

    Síncrona de propósito (imaplib e httpx são-no): quem chama corre-a numa
    thread, como o `fin_cron_ingest` faz.

    Quando a mesma plataforma e o mesmo período aparecem em duas mensagens (um
    reenvio, ou a mensagem em duas caixas), fica a MAIS RECENTE — é a que a
    plataforma corrigiu.
    """
    caixas = caixas if caixas is not None else caixas_configuradas()
    ja_lidos = ja_lidos or set()
    reiniciar_orcamento()
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
            # Já lido numa corrida anterior: nem se abre, quanto mais pagar a IA.
            if str(msg.get("Message-ID") or "")[:200] in ja_lidos:
                continue

            corpo = texto_da_mensagem(msg)
            anexos = anexos_da_mensagem(msg)

            # **A Bolt não põe um único número no email** — manda links para o
            # relatório semanal em CSV/XLSX/PDF, e é lá dentro que está o
            # «Ganhos Semanais». Sem isto, a linha dela ficava eternamente a
            # "recebido, sem valores".
            if plataforma in DOMINIOS_DE_DESCARGA:
                descarregados = descarregar_ligados(html_da_mensagem(msg), plataforma)
                anexos["lidos"].extend(descarregados["lidos"])
                anexos["ignorados"].extend(descarregados["ignorados"])

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
            extraido = conferir_contra_a_tabela(extraido, corpo, partes)

            periodo = periodo_do_relatorio(
                extraido, plataforma, data_da_mensagem(msg), hoje)
            enviada_em = data_da_mensagem(msg)
            registo = montar_registo(
                extraido, plataforma=plataforma, periodo=periodo,
                chave_de_recurso=str(msg.get("Message-ID") or ""),
                origem={
                    "assunto": assunto[:200],
                    # **A marca que evita pagar duas vezes pelo mesmo email.**
                    # Ver `ja_lidos` em `recolher`.
                    "message_id": str(msg.get("Message-ID") or "")[:200],
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
