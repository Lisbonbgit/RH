"""Emissão de documentos fiscais no Vendus (Plano 2B, Task 1).

Módulo À PARTE do cliente de leitura (`vendus/cliente.py`), de propósito:
aquele foi revisto com o critério de ser SÓ DE LEITURA e assim fica — a app
L'Açaí, em produção, factura referenciando o catálogo de lá, e mexer-lhe
partia essa faturação em silêncio. A EMISSÃO fiscal (que ESCREVE — cria
documentos reais que vão à Autoridade Tributária) vive aqui, num ficheiro
cujo nome já diz quem pode escrever: quem revê `cliente.py` sabe, só pelo
nome do módulo ao lado, que não precisa de se preocupar com escrita ali.

Duas armadilhas documentadas no código de produção do mesmo dono
(`~/dev/pizzaria/backend/vendus/client.py`), aplicadas aqui:

1. O campo `mode` ("tests"/"normal") tem de ir em TODO POST a `documents/` —
   sem ele o Vendus não sabe se é ensaio ou fatura real. (O `register_movement`
   da Pizzaria mostra o oposto — REJEITA `mode` — mas esse endpoint,
   `registers/{id}/movements`, é precisamente o que este módulo NUNCA chama,
   ver a regra abaixo.)
2. O GET de UM documento (`documents/{id}/`) não aceita `view` (403 P001) —
   já traz o detalhe. Não se aplica às leituras deste módulo, que são sempre
   sobre a COLECÇÃO (`documents/` com filtro), onde `view=detailed` é
   aceite e necessário para trazer `payments`/`amount_gross`.

Este módulo também LÊ — mas só o mínimo estritamente exigido pela
idempotência da própria emissão (Plano 2B Task 3), nunca contas em aberto
nem nada que pertença à leitura de catálogo (`vendus/cliente.py` continua
SÓ DE LEITURA de catálogo, à parte, ver acima):

- `procurar_por_referencia_externa`: UMA chamada exacta
  (`GET documents/?external_reference=`), usada só depois de uma emissão
  falhar por timeout, para saber se o Vendus chegou a processar o pedido
  antes de repetir.
- `listar_documentos_por_dia`: leitura PAGINADA (nunca a armadilha
  `per_page=200` sem paginar) usada pelo fecho de caixa (Task 4) para
  reconciliar as vendas em dinheiro da sessão contra o que o Vendus tem
  registado — só leitura, nunca decide nada sozinha (o fecho nunca bloqueia
  por isto, só avisa).

Duas regras que este módulo aplica e que ninguém pode contornar (Plano 2B —
Global Constraints, e spec §5.2/§10/§12):

- **`register_id` nunca vem de fora.** É lido de `VENDUS_REGISTER_ID`
  (variável de ambiente, a MESMA caixa API que a app L'Açaí já usa em
  produção — spec §5.2) e comparado com o `register_id` que o chamador passa.
  Se não bater, a emissão é recusada ANTES de qualquer pedido à rede — não há
  selector de `register_id` em lado nenhum da interface nem de nenhum modelo
  de entrada; esta função é a última linha de defesa contra um valor errado
  chegar aqui por engano.
- **Nunca `registers/{id}/movements`.** Esse endpoint abre/fecha a caixa
  partilhada com a app L'Açaí — fechá-la, mesmo sem querer, deixava a app a
  cobrar no Stripe sem conseguir emitir fatura nenhuma, em silêncio. Este
  módulo só fala com `documents/`.

Retentativas: a spec (§5.3) manda "num 429, esperar o Rate-Limit-Reset e
repetir" — os créditos da chave são o único limite realista (o volume das 5
lojas é ~116 vendas/dia, uma ordem de grandeza abaixo do exemplo oficial do
Vendus). Um 5xx é falha do LADO do Vendus, não dos nossos dados — também se
repete, um número limitado de vezes, antes de desistir com um erro tipado.
Um erro de REDE (timeout/ligação) não se repete aqui: não sabemos se o
pedido chegou a ser processado do outro lado, e repetir às cegas um POST que
cria um documento fiscal arriscava emitir a fatura a dobrar. Decidir o que
fazer nesse caso (confirmar por `external_reference` antes de repetir) é do
Plano 2B Task 3 (`fiscal.py`) — este módulo só sabe fazer UM pedido (com as
suas retentativas de RESPOSTA, nunca de AUSÊNCIA de resposta), não decide se
já foi emitido antes.

O `dormir` (por omissão `time.sleep`) é injectável para os testes nunca
esperarem a sério — mesmo espírito do `transport` injectável.

**Investigação do `tx_id` (Plano 2B Task 3, spec §6.3):** a documentação
oficial do Vendus (`POST documents/`, cache local — não há chave de API
nesta máquina para um teste ao vivo) descreve `tx_id` como "Transaction
unique identifier. If set, this will ensure that only a document may be
created using the same tx_id, even if multiple requests are made by
mistake." Isto seria, em teoria, uma quarta defesa de graça — mas
NÃO se acrescentou ao payload: não há forma de confirmar sem chave (a) se um
`tx_id` repetido devolve o documento original ou um ERRO, nem (b) se essa
verificação é ao nível da conta inteira ou só do `register_id`. Sem saber a
FORMA da resposta, "usar às cegas" arriscava um caminho de erro não tratado
exactamente no código que mais precisa de comportamento previsível. Fica
registado para quem tiver a chave confirmar em `mode=tests` antes de ligar.
"""
import base64
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from .cliente import (
    BASE_URL,
    VendusErro,
    VendusHTTPErro,
    VendusIndisponivel,
    _corpo_como_lista,
    _paginas_totais,
)

logger = logging.getLogger(__name__)

# O Vendus é um sistema português e as datas dos documentos vêm sem fuso
# (`date`, `local_time`). Lêem-se como hora de Lisboa e guardam-se em UTC —
# ver `_instante_do_vendus`.
_LISBOA = ZoneInfo("Europe/Lisbon")

# Máximo de páginas na leitura por dia (Task 4). Generoso de propósito (mesmo
# espírito de MAX_PAGINAS em vendus/cliente.py): as 5 lojas juntas fazem
# ~116 vendas/dia — a um per_page de 100, isto nunca devia passar de 2
# páginas num dia real. Se chegar aqui, é configuração errada (ex.: filtro
# a trazer documentos de outra caixa) — falhar alto em vez de ficar presa.
_MAX_PAGINAS_LEITURA = 200
_POR_PAGINA_LEITURA = 100

# 1 pedido original + até 2 repetições. Um 429/5xx persistente ao fim disto
# não é "mais um pouco de paciência" — é uma avaria a comunicar, não uma
# venda ao balcão pendurada a repetir para sempre.
_MAX_TENTATIVAS = 3

# Tecto defensivo ao `Rate-Limit-Reset`: um cabeçalho hostil (ou um valor
# absurdo) não pode pendurar a emissão minutos a fio numa venda ao balcão.
_ESPERA_MAXIMA_S = 30.0

# Espera entre tentativas num 5xx (o Vendus não manda um "reset" para isto,
# ao contrário do 429) — backoff curto e fixo, índice = tentativa-1.
_BACKOFF_5XX_S = (1.0, 2.0)


class RegisterIdInvalido(VendusErro):
    """O `register_id` pedido não bate com o único configurado em
    VENDUS_REGISTER_ID — recusado ANTES de qualquer pedido à rede (ver a
    docstring do módulo)."""


class VendusModoInvalido(VendusErro):
    """`VENDUS_MODE` não está definido como 'tests' nem 'normal' — a emissão
    recusa-se ANTES de qualquer pedido à rede.

    Buraco achado no Plano 2B, Task 3: a versão anterior caía em 'tests' em
    silêncio quando a variável faltava (`os.environ.get("VENDUS_MODE") or
    "tests"`). Isso significa que uma loja podia passar o dia inteiro a
    emitir documentos SEM VALOR FISCAL sem ninguém dar por isso — as vendas
    não existiam para a Autoridade Tributária, e cada cliente que apontasse o
    QR na app levava "fatura não encontrada". O modo tem de ser EXPLÍCITO:
    sem configuração válida, recusa-se em vez de assumir um valor."""


class VendusRateLimitado(VendusErro):
    """429 (créditos esgotados) mesmo depois de esperar `Rate-Limit-Reset` e
    repetir o número de vezes permitido."""


class VendusRespostaIlegivel(VendusErro):
    """O Vendus respondeu **2xx** — ou seja, CRIOU o documento fiscal — mas o
    corpo dessa resposta não se consegue ler, e por isso não sabemos QUAL
    documento criou (nem o id, nem o número, nem o ATCUD).

    Reproduzido em processo: um proxy à frente do Vendus devolve 200 com o
    HTML de uma página de manutenção; o `resposta.json()` a seguir ao POST
    bem-sucedido levanta `JSONDecodeError`, que não é `VendusErro` nenhum —
    escapava CRU pela pilha, o `except Exception` de `fiscal.
    _emitir_e_gravar` libertava a reserva ("sabemos que o Vendus não criou
    nada" — não sabíamos), o ecrã relia a venda, via `emissao_por_confirmar:
    False` e convidava a operadora a emitir outra vez: **duas Faturas
    Simplificadas REAIS da mesma venda**.

    Existe para isto ser um erro TIPADO desta família ("criou, não consigo
    ler qual") e não um `ValueError` cru: quem chama tem de o poder
    distinguir de um 4xx (onde o documento não existe) e tratá-lo como
    incerto — reserva mantida e 503, nunca um 500 que o ecrã lê como "nada
    saiu"."""


def _ler_rate_limit_reset(resposta: httpx.Response) -> float:
    """Segundos a esperar antes de repetir, do cabeçalho `Rate-Limit-Reset`.
    Sem cabeçalho (ou valor não numérico), cai para 1s — a ausência do
    cabeçalho não pode impedir a retentativa. Sempre limitado a
    `_ESPERA_MAXIMA_S`."""
    try:
        valor = float(resposta.headers.get("Rate-Limit-Reset", "1"))
    except (TypeError, ValueError):
        valor = 1.0
    return max(0.0, min(valor, _ESPERA_MAXIMA_S))


class ClienteEmissaoVendus:
    """Cliente HTTP que ESCREVE no Vendus — usado só para emitir documentos
    fiscais (`POST documents/`). Mesma autenticação e o mesmo padrão de
    `transport` injectável do cliente de leitura (`vendus/cliente.py`), num
    ficheiro à parte de propósito (ver a docstring do módulo)."""

    def __init__(
        self,
        chave: str,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 30.0,
        dormir: Optional[Callable[[float], None]] = None,
    ):
        self._http = httpx.Client(
            base_url=BASE_URL, auth=(chave, ""), timeout=timeout, transport=transport
        )
        self._dormir = dormir if dormir is not None else time.sleep

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ClienteEmissaoVendus":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def criar_fatura_simplificada(
        self,
        linhas: List[Dict],
        pagamentos: List[Dict],
        cliente: Optional[Dict],
        external_reference: str,
        register_id: int,
    ) -> Dict:
        """`POST documents/` com `type=FS` e `output=escpos` — o Vendus
        devolve o talão JÁ EM ESC/POS, por isso este módulo não desenha o
        layout da fatura, vem certificado de lá. Devolve id, número, ATCUD,
        total e os BYTES do talão (já descodificados de base64).

        `register_id` é comparado com o único configurado em
        VENDUS_REGISTER_ID ANTES de qualquer pedido — ver a docstring do
        módulo. `linhas` são o formato que `precos.linha_de_venda` já
        produz (title/qty/gross_price/tax_id/desconto); `pagamentos` no
        formato do Vendus ([{"id": ..., "amount": ...}]); `cliente` opcional
        (ex.: {"fiscal_id": NIF}) — sem ele o Vendus assume Consumidor
        Final."""
        esperado = _register_id_configurado()
        if esperado is None or register_id != esperado:
            raise RegisterIdInvalido(
                "register_id %r não bate com o único configurado "
                "(VENDUS_REGISTER_ID=%r) — emissão recusada antes de sair "
                "para a rede." % (register_id, esperado)
            )
        # Ver a docstring de VendusModoInvalido: sem VENDUS_MODE explícito
        # ('tests' ou 'normal'), a emissão recusa-se ANTES de qualquer
        # pedido à rede — nunca assume um valor por omissão.
        modo = _modo_configurado()

        corpo: Dict[str, Any] = {
            "type": "FS",
            "register_id": register_id,
            "items": linhas,
            "payments": pagamentos,
            "external_reference": external_reference,
            "output": "escpos",
            "mode": modo,
        }
        if cliente:
            corpo["client"] = cliente

        resposta = self._pedir_com_retentativas("documents/", corpo)
        # A PARTIR DAQUI o documento fiscal JÁ EXISTE do lado da AT: a
        # resposta foi 2xx. Tudo o que falhar a seguir é "criou, mas não
        # consigo ler" e tem de sair TIPADO (`VendusRespostaIlegivel`) —
        # nunca um `ValueError`/`binascii.Error` cru, que quem chama
        # confundiria com "o Vendus recusou e não criou nada" (ver a
        # docstring dessa excepção: era assim que saíam duas FS reais).
        try:
            dados = resposta.json() if resposta.content else {}
        except ValueError as e:
            raise VendusRespostaIlegivel(
                "O Vendus respondeu %d (documento CRIADO) mas o corpo não é "
                "JSON legível (%s) — não é possível saber que documento saiu. "
                "external_reference=%s" % (resposta.status_code, e, external_reference)
            ) from e
        if not isinstance(dados, dict) or (dados.get("id") is None and not dados.get("atcud")):
            # Um 2xx sem identidade nenhuma do documento (nem id nem ATCUD)
            # é o mesmo caso: gravá-lo assim escrevia uma linha em
            # `fat_documentos` com `vendus_document_id=None` e `atcud=None`,
            # que colide com a PRÓXIMA igual (os índices únicos tratam o
            # nulo como valor) e esconde a fatura real atrás de um conflito.
            raise VendusRespostaIlegivel(
                "O Vendus respondeu %d (documento CRIADO) mas a resposta não "
                "traz nem `id` nem `atcud` — não é possível saber que "
                "documento saiu. external_reference=%s"
                % (resposta.status_code, external_reference)
            )

        return {
            "id": dados.get("id"),
            "numero": dados.get("number"),
            "atcud": dados.get("atcud"),
            "total": round(float(dados.get("amount_gross") or 0), 2),
            # O talão é uma CONVENIÊNCIA (reimprimir), não a identidade do
            # documento: um `output` estragado não pode transformar uma
            # emissão bem sucedida num erro — perde-se o papel, nunca o
            # registo da fatura. Ver `_talao_de`.
            "talao_escpos": _talao_de(dados, external_reference),
            # O Dashboard soma por estes dois campos (`dashboard.py::
            # _campo_valor`: `total_bruto` com IVA, `total_liquido` sem) —
            # `total` sozinho deixava a receita das 5 lojas a 0,00 €. Nunca
            # se deriva um do outro por uma taxa assumida: sem o campo do
            # Vendus, fica `None` (ver `_valor_monetario`).
            "total_bruto": _valor_monetario(dados.get("amount_gross")),
            "total_liquido": _valor_monetario(dados.get("amount_net")),
            # O ecrã tem de poder avisar em que modo o documento saiu — um
            # documento em modo 'tests' não tem valor fiscal nenhum.
            "modo": modo,
        }

    def procurar_por_referencia_externa(self, external_reference: str, register_id: int) -> Optional[Dict]:
        """Confirma se uma emissão que falhou por TIMEOUT chegou a ser
        processada do outro lado — UMA chamada exacta
        (`GET documents/?external_reference=...`), nunca um varrimento dos
        documentos do dia (a armadilha da Pizzaria: `per_page=200` sem
        paginar, que numa loja com 240 talões não encontrava a fatura
        original e emitia uma segunda real — ver a docstring do módulo).

        Devolve o documento (normalizado, mesmo formato de
        `criar_fatura_simplificada`) se existir e não estiver ANULADO
        (`status != "A"`); `None` se não existir — quem chama decide repetir
        a emissão."""
        esperado = _register_id_configurado()
        if esperado is None or register_id != esperado:
            raise RegisterIdInvalido(
                "register_id %r não bate com o único configurado "
                "(VENDUS_REGISTER_ID=%r) — verificação recusada antes de "
                "sair para a rede." % (register_id, esperado)
            )
        resposta = self._pedir_get_com_retentativas(
            "documents/",
            {
                "external_reference": external_reference,
                "register_id": register_id,
                "view": "detailed",
            },
        )
        if resposta is None:
            return None
        for doc in _corpo_como_lista(resposta):
            if (
                str(doc.get("external_reference") or "") == external_reference
                and doc.get("status") != "A"
            ):
                return _normaliza_documento(doc)
        return None

    def listar_documentos_por_dia(self, data: str, register_id: int) -> List[Dict]:
        """`GET documents/` de UM dia (formato `YYYY-MM-DD`), PAGINADO até
        esgotar — pede sempre `per_page=100` e usa `X-Paginator-Pages` da
        primeira resposta para saber quantas páginas tem de pedir (nunca a
        armadilha `per_page=200` sem paginar, ver a docstring do módulo).
        Usada pelo fecho de caixa (Task 4) para reconciliar; quem chama
        filtra pelo prefixo `pos-` e descarta os documentos anulados
        (`status == "A"`) — esta função só lê e devolve tudo o que houver
        nesse dia na caixa configurada."""
        esperado = _register_id_configurado()
        if esperado is None or register_id != esperado:
            raise RegisterIdInvalido(
                "register_id %r não bate com o único configurado "
                "(VENDUS_REGISTER_ID=%r) — leitura recusada antes de sair "
                "para a rede." % (register_id, esperado)
            )
        resultado: List[Dict] = []
        pagina = 1
        total_paginas: Optional[int] = None
        while True:
            if pagina > _MAX_PAGINAS_LEITURA:
                raise VendusErro(
                    "Documentos de %s com mais de %d páginas (%d já lidos) — "
                    "parece configuração errada; leitura interrompida em vez "
                    "de ficar presa." % (data, _MAX_PAGINAS_LEITURA, len(resultado))
                )
            resposta = self._pedir_get_com_retentativas(
                "documents/",
                {
                    "since": data,
                    "until": data,
                    "register_id": register_id,
                    "view": "detailed",
                    "per_page": _POR_PAGINA_LEITURA,
                    "page": pagina,
                },
            )
            if resposta is None:
                break  # 404/A001 — sem documentos nesse dia, não é avaria
            pagina_dados = _corpo_como_lista(resposta)
            resultado.extend(pagina_dados)
            if total_paginas is None:
                total_paginas = _paginas_totais(resposta)
            if total_paginas is not None:
                if pagina >= total_paginas:
                    break
            elif len(pagina_dados) < _POR_PAGINA_LEITURA:
                break
            pagina += 1
        return resultado

    def _pedir_com_retentativas(self, path: str, corpo: Dict) -> httpx.Response:
        return self._enviar_com_retentativas("POST", path, json=corpo)

    def _pedir_get_com_retentativas(self, path: str, parametros: Dict) -> Optional[httpx.Response]:
        """GET com as MESMAS retentativas de 429/5xx do POST (ver
        `_enviar_com_retentativas`). Devolve `None` no 404/A001 do Vendus
        ("sem resultados" — não é avaria, mesma armadilha documentada em
        `vendus/cliente.py`)."""
        try:
            return self._enviar_com_retentativas("GET", path, params=parametros)
        except VendusHTTPErro as e:
            if e.status_code == 404 and ("A001" in e.corpo or "No data" in e.corpo):
                return None
            raise

    def _enviar_com_retentativas(self, metodo: str, path: str, **kwargs: Any) -> httpx.Response:
        tentativa = 0
        while True:
            tentativa += 1
            try:
                resposta = self._http.request(metodo, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                # Ver a docstring do módulo: um erro de rede não se repete
                # aqui — não sabemos se o Vendus chegou a processar o
                # pedido, e repetir às cegas arriscava emitir a dobrar (ou,
                # numa leitura, mascarar uma falha real de verificação).
                raise VendusIndisponivel(str(e)) from e

            if resposta.status_code == 429:
                if tentativa >= _MAX_TENTATIVAS:
                    raise VendusRateLimitado(
                        "Vendus 429 (limite de créditos) mesmo após %d tentativas." % tentativa
                    )
                self._dormir(_ler_rate_limit_reset(resposta))
                continue

            if 500 <= resposta.status_code < 600:
                if tentativa >= _MAX_TENTATIVAS:
                    raise VendusIndisponivel(
                        "Vendus %d mesmo após %d tentativas." % (resposta.status_code, tentativa)
                    )
                indice = min(tentativa - 1, len(_BACKOFF_5XX_S) - 1)
                self._dormir(_BACKOFF_5XX_S[indice])
                continue

            if resposta.status_code >= 400:
                raise VendusHTTPErro(resposta.status_code, resposta.text)

            return resposta


def _valor_monetario(valor) -> Optional[float]:
    """Um valor em euros vindo do Vendus, ou `None` quando o campo não vem
    (ou não é legível) — NUNCA 0,00 €.

    A diferença importa nos relatórios: um zero inventado soma-se em
    silêncio e faz um dia de vendas parecer um dia sem IVA; um `None` não
    finge número nenhum. É a mesma regra de ouro de `precos.py` — sem o
    campo certo, não se inventa nada (e muito menos se deriva o líquido do
    bruto por uma taxa assumida: as lojas vendem a 13 % e a 23 %)."""
    if valor is None or valor == "":
        return None
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return None


def _talao_de(doc: Dict, referencia: str) -> bytes:
    """Os bytes ESC/POS do talão, ou `b""` se o `output` não for base64
    legível — com aviso no log.

    Ao contrário do corpo da resposta (ver `VendusRespostaIlegivel`), um
    talão estragado NÃO põe em causa a identidade do documento: o id, o
    número e o ATCUD já vieram. Deixar um `binascii.Error` subir daqui
    transformava uma emissão bem sucedida numa falha — e uma falha de
    emissão é exactamente o que faz emitir outra vez."""
    output_b64 = doc.get("output")
    if not output_b64:
        return b""
    try:
        return base64.b64decode(output_b64)
    except Exception as e:  # noqa: BLE001 — ver a docstring: o papel, nunca o registo
        logger.warning(
            "[faturacao] talão ESC/POS ilegível no documento %s (%s): %s — o "
            "documento fiscal fica gravado à mesma, só não se consegue "
            "reimprimir o papel.", referencia, doc.get("id"), e,
        )
        return b""


def _instante_do_vendus(doc: Dict) -> Optional[str]:
    """O instante em que o documento existe do lado da AT, em ISO/UTC — ou
    `None` se o Vendus não o disser de forma legível.

    **Porquê e o que se estragava sem isto.** Um documento trazido por
    verificação ou por reconciliação ficava carimbado com o instante em que
    NÓS o descobrimos: a fatura das 23h de ontem, reconciliada às 9h de hoje,
    entrava no cartão de HOJE do Dashboard e a receita de ontem ficava a
    faltar. O relógio certo é o do documento.

    `local_time` primeiro: é o campo cuja semântica é inequívoca (hora local
    da loja) — o código de produção do mesmo dono usa-o exactamente assim
    (`~/dev/pizzaria/backend/vendus/client.py::list_creditable`, `lt[:10]` /
    `lt[11:16]`). Só depois `date`, que a mesma API usa para filtrar por dia.
    Um valor JÁ com fuso é respeitado tal e qual; um valor SEM fuso lê-se
    como hora de Lisboa (é uma conta portuguesa, e a alternativa — assumir
    UTC — atirava as vendas depois das 23h para o dia seguinte no Verão).

    Não legível é `None`, nunca uma data inventada: quem chama cai no
    instante actual (e este aviso fica no log a dizer que caiu)."""
    for campo in ("local_time", "date"):
        valor = doc.get(campo)
        if not valor:
            continue
        texto = str(valor).strip().replace("Z", "+00:00")
        try:
            momento = datetime.fromisoformat(texto)
        except ValueError:
            logger.warning(
                "[faturacao] data %r do Vendus (campo %s, documento %s) não é "
                "legível — o documento vai ficar com o instante actual.",
                valor, campo, doc.get("id"),
            )
            continue
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=_LISBOA)
        return momento.astimezone(timezone.utc).isoformat()
    return None


def _normaliza_documento(doc: Dict) -> Dict:
    """O mesmo formato devolvido por `criar_fatura_simplificada`, a partir de
    um documento lido (não criado agora) — usado pela verificação por
    referência externa, para quem chama não ter de saber a diferença entre
    'acabei de criar' e 'já existia'.

    `modo` e `emitido_em` vinham a faltar, e as duas ausências tinham
    consequência medida: sem `mode`, uma fatura recuperada nunca trazia o
    aviso "documento em modo tests, sem valor fiscal" que o ecrã mostra a
    partir desse campo; sem a data, ficava com o instante em que a
    descobrimos em vez daquele em que a AT a recebeu (ver
    `_instante_do_vendus`)."""
    return {
        "id": doc.get("id"),
        "numero": doc.get("number"),
        "atcud": doc.get("atcud"),
        "total": round(float(doc.get("amount_gross") or 0), 2),
        "talao_escpos": _talao_de(doc, str(doc.get("external_reference") or "")),
        "external_reference": doc.get("external_reference"),
        # O contrato com o Dashboard (ver `criar_fatura_simplificada`).
        "total_bruto": _valor_monetario(doc.get("amount_gross")),
        "total_liquido": _valor_monetario(doc.get("amount_net")),
        # O modo VEM DO DOCUMENTO, não da configuração de agora: uma fatura
        # emitida ontem em `tests` continua a não ter valor fiscal, mesmo
        # que o VENDUS_MODE de hoje já seja `normal`.
        "modo": doc.get("mode"),
        "emitido_em": _instante_do_vendus(doc),
    }


def _register_id_configurado() -> Optional[int]:
    valor = os.environ.get("VENDUS_REGISTER_ID")
    if not valor:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


_MODOS_VALIDOS = frozenset({"tests", "normal"})


def _modo_configurado() -> str:
    valor = os.environ.get("VENDUS_MODE")
    if valor not in _MODOS_VALIDOS:
        raise VendusModoInvalido(
            "VENDUS_MODE tem de estar definido como 'tests' ou 'normal' — "
            "valor actual: %r. A emissão recusa-se em vez de assumir 'tests' "
            "em silêncio (ver a docstring de VendusModoInvalido)." % valor
        )
    return valor
