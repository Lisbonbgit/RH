"""O PROGRAMA DE IMPRESSÃO DA LOJA — tudo o que não é Windows.

O ficheiro ao lado (`windows.py`) tem UMA função que fala com o Windows.
Está tudo o resto aqui de propósito: buscar trabalho, decidir a ordem,
repetir, o que fazer quando falha, e o que dizer quando não se consegue falar
com o servidor. **Isto corre e testa-se num Mac; aquilo não.**

## A DIRECÇÃO: o programa VAI BUSCAR, o servidor não empurra

O POS é uma página **https**, e uma página https não fala com um programa em
`localhost` sem certificados que alguém tem de instalar e renovar em cinco
lojas. Por isso é o PC da loja que liga para fora e PERGUNTA se há trabalho —
como o browser já faz.

Três coisas saem de graça, e a terceira é a que interessa ao balcão: não há
nada a configurar na rede e funciona atrás de qualquer firewall; não há
certificado nenhum a instalar; e **se o browser fechar a meio, o talão sai na
mesma** — o trabalho está no servidor, não no ecrã.

## A ORDEM DOS TRÊS PASSOS, e é a decisão inteira deste ficheiro

Buscar → **IMPRIMIR** → dizer que imprimiu. Nesta ordem, e nunca ao contrário.

Confirmar primeiro e imprimir depois tornava cada falha de impressora num
cliente sem documento: o servidor dava o trabalho por resolvido e ninguém
voltava a ele. Imprimir primeiro deixa uma janela aberta — a confirmação pode
perder-se com o papel já cortado — e nessa janela o servidor devolve o
trabalho à fila e o papel sai OUTRA VEZ.

**É a escolha certa, e é a mesma que o servidor faz (`faturacao/impressao.py`):
antes duas vezes do que nenhuma.** Um talão a mais é papel — a operadora
deita-o fora. Um talão a menos é um cliente sem documento: é a obrigação legal
por cumprir, é o QR da fidelização que ele não consegue ler, e é a operadora a
explicar-lhe que o sistema falhou. Os dois estragos não têm o mesmo tamanho.

## O QUE ESTE FICHEIRO NÃO SABE

Não sabe se a impressora é USB ou de rede, e é deliberado. A frase do dono
manda aqui: «não deve ser preocupação se a impressora está ligada em usb ou
cabo. porque na minha cabeça como é o vendus, ele usa a impressora instalada
no pc.» Ele tem razão — imprime-se na impressora **instalada no Windows, pelo
nome**, e quem trata do cabo é o Windows. O que este programa tem de garantir
é que os bytes chegam **em cru**, e isso é o que `windows.py` faz e o que a
página de teste prova.
"""
import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("agente_impressao")

# Os dois PAPÉIS que existem, e não mais. São os mesmos nomes que o servidor
# usa (`faturacao/impressao.CAIXA` e `COZINHA`) — não são marcas nem portas: o
# dono tem UM PC por loja com as duas impressoras instaladas nele, e é a
# configuração deste programa que diz qual é a impressora do Windows que faz
# cada papel.
CAIXA = "caixa"
COZINHA = "cozinha"
PAPEIS = (CAIXA, COZINHA)

# De quanto em quanto tempo se pergunta ao servidor se há trabalho, quando a
# última pergunta correu bem. Três segundos é o que separa "a operadora
# carregou em Finalizar" de "o papel começou a sair" — abaixo disto o ganho
# deixa de se notar ao balcão e o servidor leva cinco lojas a bater-lhe à
# porta o dia inteiro.
INTERVALO_SEGUNDOS = 3

# Quando a pergunta FALHA, espera-se mais de cada vez — até um tecto. Uma loja
# com a internet em baixo não deve martelar o servidor de 3 em 3 segundos
# durante a tarde inteira; mas o tecto é curto (um minuto) porque o que
# interessa é voltar depressa ao normal assim que a linha voltar, e não
# poupar pedidos a um servidor que já não os está a receber.
ESPERA_MAXIMA_SEGUNDOS = 60

# Ao fim de quantas falhas seguidas é que o programa passa a GRITAR em vez de
# se queixar baixinho. Uma falha é a rede a soluçar; três seguidas (uns dez
# segundos) já é alguém que tem de saber — um programa de impressão
# silenciosamente morto é pior do que nenhum.
FALHAS_ATE_AVISAR = 3

_TIMEOUT_SEGUNDOS = 20

# ONDE o módulo de faturação está montado no servidor (`faturacao/__init__.py`:
# `APIRouter(prefix="/api/faturacao")`). Escrito UMA vez, e é aqui: as rotas do
# POS declaram-se como `/pos/...` dentro do módulo, e é assim que elas se leem
# em `impressao.py`. Um caminho absoluto copiado para dentro de cada método era
# a terceira vez que este repositório escrevia o prefixo à mão — as duas
# primeiras puseram o POS inteiro a responder 404 «Not Found» em inglês à
# funcionária. Há um guarda que confronta os cinco caminhos deste ficheiro com
# as rotas a sério do FastAPI: `backend/tests/faturacao/test_caminhos_do_pos.py`.
PREFIXO_DO_MODULO = "/api/faturacao"

MSG_SEM_SERVIDOR = (
    "SEM LIGAÇÃO AO SERVIDOR — nada está a sair em papel.\n"
    "Veja a internet da loja. Os talões não se perdem: ficam à espera no "
    "servidor e saem quando a ligação voltar."
)
MSG_POR_CONFIGURAR = (
    "POR CONFIGURAR — carregue em Definições e escolha o servidor, o código "
    "da loja e as duas impressoras."
)
MSG_SEM_IMPRESSORA = (
    "Não há nenhuma impressora escolhida para o papel «%s». Abra as "
    "Definições deste programa e escolha-a na lista do Windows."
)


# --- As definições, o que o funcionário escolheu uma vez -----------------------


def caminho_das_definicoes() -> str:
    """Onde fica o ficheiro de configuração deste PC.

    `%APPDATA%` e não a pasta do programa: o `.exe` pode estar em
    `C:\\Program Files`, onde um programa normal não consegue escrever, e
    pode ser substituído por uma versão nova sem levar a configuração à
    frente. Fora do Windows (aqui, no Mac, a correr os testes) cai para a
    pasta pessoal — o programa não serve para nada num Mac, mas os testes
    servem."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "AgenteImpressaoLacai", "definicoes.json")


def caminho_do_log() -> str:
    """O `agente.log` deste PC — **com a pasta já criada**.

    A pasta só nascia ao GRAVAR as definições. Na primeira vez que alguém faz
    duplo clique no `.exe` de um PC novo (passo 4 do INSTALAR-IMPRESSAO.md)
    ela ainda não existe, e o `logging.basicConfig` do arranque rebentava com
    `FileNotFoundError` antes de a janela chegar a abrir. Com `console=False`
    no `.exe` (ver `agente.spec`) isso não é um erro no ecrã: é **nada** —
    sem janela, sem mensagem, sem log. Quem foi à loja ficava ali parado a
    olhar para um duplo clique que não fazia rigorosamente nada."""
    pasta = os.path.dirname(caminho_das_definicoes())
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, "agente.log")


def ler_definicoes(caminho: Optional[str] = None) -> Dict:
    """As definições gravadas, ou um dicionário vazio.

    **Nunca levanta excepção.** Um ficheiro apagado, meio escrito ou com o
    JSON partido (o PC foi abaixo a meio da gravação) tem de dar um programa
    que abre a pedir configuração — e não um `.exe` que arranca com o
    Windows, rebenta em silêncio, e deixa a loja a achar que está a
    imprimir."""
    caminho = caminho or caminho_das_definicoes()
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            valor = json.load(f)
        return valor if isinstance(valor, dict) else {}
    except Exception:  # noqa: BLE001 — ver a docstring
        return {}


def gravar_definicoes(definicoes: Dict, caminho: Optional[str] = None) -> None:
    caminho = caminho or caminho_das_definicoes()
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(definicoes, f, ensure_ascii=False, indent=2)


def esta_configurado(definicoes: Dict) -> bool:
    """Falta alguma coisa para este programa poder trabalhar?

    O `device_token` é o que prova que este PC foi emparelhado com a loja; as
    duas impressoras são o que diz onde sai cada papel. Sem qualquer um
    deles, o programa abre a pedir configuração em vez de fingir que está a
    trabalhar."""
    return bool(
        definicoes.get("servidor")
        and definicoes.get("device_token")
        and definicoes.get("impressoras", {}).get(CAIXA)
        and definicoes.get("impressoras", {}).get(COZINHA)
    )


def impressora_de(definicoes: Dict, papel: str) -> Optional[str]:
    """O nome da impressora do Windows que faz este papel, ou `None`."""
    return (definicoes.get("impressoras") or {}).get(papel) or None


# --- O servidor ---------------------------------------------------------------


class ErroDoServidor(Exception):
    """Não se conseguiu falar com o servidor, ou ele respondeu o que não devia."""


class Servidor:
    """As quatro conversas que este programa tem com o servidor.

    `urllib` da biblioteca padrão e não `requests`: são quatro pedidos JSON, e
    uma dependência a menos é um `.exe` mais pequeno e menos uma coisa que
    pode faltar no dia em que se voltar a compilar isto daqui a dois anos.

    O `abrir` é injectável para os testes poderem correr a conversa toda sem
    servidor nenhum — que é a única forma de a provar num Mac."""

    def __init__(self, url: str, device_token: str = "", abrir: Optional[Callable] = None):
        self.url = (url or "").rstrip("/")
        self.device_token = device_token or ""
        self._abrir = abrir or self._abrir_mesmo

    @staticmethod
    def _abrir_mesmo(pedido, timeout):
        # `create_default_context` verifica o certificado. Não se desliga: o
        # que passa nestes pedidos são bytes de Faturas Simplificadas reais e
        # o token que autoriza este PC a ir buscá-los.
        return urllib.request.urlopen(pedido, timeout=timeout, context=ssl.create_default_context())

    def _falar(self, caminho: str, corpo: Optional[Dict] = None, metodo: str = "POST") -> Dict:
        if not self.url:
            raise ErroDoServidor("O endereço do servidor não está configurado.")
        dados = json.dumps(corpo or {}).encode("utf-8")
        pedido = urllib.request.Request(
            self.url + PREFIXO_DO_MODULO + caminho, data=dados, method=metodo,
            headers={"Content-Type": "application/json"},
        )
        if self.device_token:
            pedido.add_header("X-Device-Token", self.device_token)
        try:
            with self._abrir(pedido, _TIMEOUT_SEGUNDOS) as resposta:
                bruto = resposta.read().decode("utf-8") or "{}"
            return json.loads(bruto)
        except urllib.error.HTTPError as e:
            # O 409 do `marcar_impresso` chega aqui, e é ESPERADO: quer dizer
            # que o arrendamento expirou e o trabalho já é de outra entrega.
            # Quem chama é que decide o que fazer com ele — ver `uma_volta`.
            raise ErroDoServidor("O servidor respondeu %s" % e.code) from e
        except Exception as e:  # noqa: BLE001 — rede, DNS, TLS, JSON partido
            raise ErroDoServidor(str(e)) from e

    def emparelhar(self, codigo: str) -> Dict:
        """Troca o código que o gestor gerou no backoffice por um token deste
        PC. É a mesma rota e o mesmo código que o POS usa no browser
        (`faturacao/pos_auth.emparelhar`) — de uso único e válido 15 minutos."""
        return self._falar("/pos/emparelhar", {"codigo": codigo.strip().upper()})

    def pagina_de_teste(self, papel: str) -> bytes:
        """Os bytes da página de teste, construídos pelo SERVIDOR.

        Vêm de lá e não daqui para não haver duas cópias do ESC/POS: os dois
        números que se afinam quando uma impressora discorda (a tabela de
        caracteres e o comando de corte) vivem numa constante só, em
        `faturacao/escpos.py`. Uma cópia dentro do `.exe` fazia com que afinar
        um deles corrigisse os talões e não a página que os devia
        diagnosticar."""
        import base64
        resposta = self._falar(
            "/pos/impressao/pagina-de-teste", {"impressora": papel})
        return base64.b64decode(resposta.get("bytes_b64") or "")

    def recolher(self) -> List[Dict]:
        return self._falar("/pos/impressao/recolher").get("trabalhos") or []

    def impresso(self, trabalho_id: str, recibo: str) -> None:
        self._falar(
            "/pos/impressao/trabalhos/%s/impresso" % trabalho_id, {"recibo": recibo})

    def falhou(self, trabalho_id: str, recibo: str, erro: str) -> None:
        self._falar(
            "/pos/impressao/trabalhos/%s/falhou" % trabalho_id,
            {"recibo": recibo, "erro": erro[:500]},
        )


# --- A volta da fila ----------------------------------------------------------


def bytes_do_trabalho(trabalho: Dict) -> bytes:
    """Os bytes ESC/POS que vieram do servidor, em base64.

    Levanta se não se perceberem — e é de propósito que não devolve `b""`:
    mandar zero bytes para a impressora é papel em branco a sair e a
    operadora a pensar que o sistema imprimiu."""
    import base64
    dados = base64.b64decode(trabalho.get("bytes_b64") or "", validate=True)
    if not dados:
        raise ValueError("O trabalho veio sem bytes nenhuns.")
    return dados


def uma_volta(
    servidor: Servidor,
    definicoes: Dict,
    imprimir: Callable[[str, bytes], None],
) -> int:
    """Pergunta ao servidor, imprime o que houver, e confirma. Devolve quantos
    papéis saíram.

    **A ordem é buscar → imprimir → confirmar**, e a razão está na docstring
    do módulo: antes duas vezes do que nenhuma.

    **Uma avaria não cala a outra impressora.** Cada trabalho é tratado
    sozinho: o talão do cliente que não sai porque a impressora do balcão
    está sem papel não impede a ficha de ir para a cozinha. Por isso o `for`
    continua em vez de desistir da volta.

    **A confirmação que falha não faz reimprimir agora.** Já se imprimiu; o
    servidor é que devolve o trabalho à fila quando o arrendamento expirar
    (60 s), e aí sai segunda vez — que é o lado por que este sistema optou.
    Tentar outra vez aqui, no mesmo segundo, era a mesma repetição sem
    esperar por ninguém.

    Um erro a BUSCAR sobe (é o que acende o aviso de "sem ligação"); um erro
    a imprimir ou a confirmar não sobe — a volta seguinte volta a tentar."""
    trabalhos = servidor.recolher()
    saidos = 0
    for trabalho in trabalhos:
        trabalho_id = trabalho.get("id")
        recibo = trabalho.get("recibo")
        papel = trabalho.get("impressora")
        nome = impressora_de(definicoes, papel)
        if not nome:
            # Não se guarda para depois nem se deita fora aqui: diz-se ao
            # servidor que falhou, com a razão por extenso. Ele conta a
            # tentativa, e o ecrã do POS mostra o trabalho como falhado — que
            # é o que faz alguém ir configurar isto.
            _dizer_que_falhou(servidor, trabalho_id, recibo, MSG_SEM_IMPRESSORA % papel)
            continue
        try:
            dados = bytes_do_trabalho(trabalho)
        except Exception as e:  # noqa: BLE001
            _dizer_que_falhou(
                servidor, trabalho_id, recibo,
                "Os bytes deste trabalho vieram ilegíveis: %s" % e)
            continue
        try:
            imprimir(nome, dados)
        except Exception as e:  # noqa: BLE001 — a impressora é do mundo real
            logger.warning("não imprimiu %s em %r: %s", trabalho.get("tipo"), nome, e)
            _dizer_que_falhou(servidor, trabalho_id, recibo, str(e))
            continue
        saidos += 1
        try:
            servidor.impresso(trabalho_id, recibo)
        except ErroDoServidor as e:
            # O papel JÁ SAIU. Não há nada a corrigir daqui — o servidor
            # devolve o trabalho à fila e ele sai outra vez. Fica escrito no
            # log para quem um dia perguntar porque saíram dois iguais.
            logger.warning(
                "o papel de %s saiu mas a confirmação não chegou ao servidor "
                "(%s) — ele vai voltar à fila e sair segunda vez.",
                trabalho.get("tipo"), e)
    return saidos


def _dizer_que_falhou(servidor: Servidor, trabalho_id, recibo, erro: str) -> None:
    """Avisa o servidor, e nunca deixa esse aviso rebentar a volta.

    Se nem isto passar, o arrendamento trata do assunto sozinho ao fim de um
    minuto — o trabalho volta à fila na mesma."""
    try:
        servidor.falhou(trabalho_id, recibo, erro)
    except ErroDoServidor as e:
        logger.warning("nem a queixa chegou ao servidor: %s", e)


def espera_apos_falhas(falhas_seguidas: int) -> int:
    """Quantos segundos esperar antes de voltar a perguntar.

    Zero falhas → o intervalo normal. Depois disso, dobra de cada vez até ao
    tecto: 3, 6, 12, 24, 48, 60, 60… O tecto é curto de propósito (ver
    `ESPERA_MAXIMA_SEGUNDOS`): o que interessa é voltar depressa ao normal
    assim que a linha voltar."""
    if falhas_seguidas <= 0:
        return INTERVALO_SEGUNDOS
    return min(INTERVALO_SEGUNDOS * (2 ** falhas_seguidas), ESPERA_MAXIMA_SEGUNDOS)


def estado_legivel(definicoes: Dict, falhas_seguidas: int, ultimo_erro: str = "") -> str:
    """A frase que a janela mostra. É a única coisa que este programa diz a
    uma pessoa, por isso diz sempre o que fazer a seguir e nunca só o que
    correu mal.

    Pura de propósito — sem isto, a única forma de ver o que a janela escreve
    era abrir a janela, e num Mac ela não abre."""
    if not esta_configurado(definicoes):
        return MSG_POR_CONFIGURAR
    if falhas_seguidas >= FALHAS_ATE_AVISAR:
        return MSG_SEM_SERVIDOR + (("\n(%s)" % ultimo_erro) if ultimo_erro else "")
    loja = definicoes.get("loja_nome") or definicoes.get("loja_id") or "esta loja"
    return "A trabalhar. A imprimir os talões de %s." % loja


def ha_problema(definicoes: Dict, falhas_seguidas: int) -> bool:
    """A janela deve estar a gritar? É o que decide a cor e o que faz o
    programa saltar para a frente em vez de ficar calado na barra de tarefas."""
    return not esta_configurado(definicoes) or falhas_seguidas >= FALHAS_ATE_AVISAR
