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


class NotaDeCreditoSemMotivo(VendusErro):
    """Uma nota de crédito sem motivo — recusada ANTES de qualquer pedido à
    rede, como o `register_id` errado e o modo em falta.

    O motivo não é uma formalidade nossa: a API do Vendus exige `notes` numa
    NC («You also have to specify notes stating the reason for issuing the
    credit note») e a lei portuguesa exige que uma nota de crédito diga o que
    rectifica e porquê. Sem ele o Vendus recusaria o documento — mas a recusa
    chegaria à operadora como um 4xx opaco à frente do cliente, e é por isso
    que se recusa aqui, com uma frase que diz o que falta.

    É `VendusErro` (e `VendusHTTPErro` não): entra na lista curta de
    `fiscal._ERROS_COM_PROVA_DE_QUE_NADA_SAIU` pela mesma porta dos outros
    dois erros de pré-voo — a prova de que nada saiu é que o pedido não
    chegou a existir."""


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
    saiu".

    **Também a LEITURA, e não só a criação.** A mesma incapacidade de ler um
    2xx acontece nos GET deste módulo (`procurar_por_referencia_externa`,
    `listar_documentos_por_dia`), e o estrago é o simétrico: quem lê tem de
    poder distinguir "o Vendus disse que não existe" de "o Vendus respondeu e
    eu não consigo ler o que disse". Um erro cru na leitura sobe pela rota de
    RECONCILIAR (que só apanha `VendusErro`) e sai 500 do FastAPI, com a venda
    ainda `aberta`, sem documento e com a reserva incerta — o ecrã lê isso
    como "não há nada, pode repetir". Medido nesta ronda com um
    `amount_gross='8,99'` (vírgula decimal, plausível numa API portuguesa):
    «ValueError CRU — a rota não o apanha, o FastAPI devolve 500»."""


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
        modo: Optional[str] = None,
    ) -> Dict:
        """`POST documents/` com `type=FS` e `output=escpos` — o Vendus
        devolve o talão JÁ EM ESC/POS, por isso este módulo não desenha o
        layout da fatura, vem certificado de lá. Devolve id, número, ATCUD,
        total e os BYTES do talão (já descodificados de base64).

        `register_id` é comparado com o único configurado em
        VENDUS_REGISTER_ID ANTES de qualquer pedido — ver a docstring do
        módulo. `linhas` são o formato que `precos.linha_de_venda` já
        produz: **id** (o produto no Vendus, quando o nosso artigo tem
        `vendus_ref`), title, qty, gross_price, tax_id e o desconto.

        O `id` não é decorativo e não se pode deixar cair: é ele que faz o
        Vendus LIGAR a linha ao produto que já lá existe. Sem ele o Vendus
        não casa por nome e **cria um produto novo a cada venda** — foi
        assim que a conta real ficou com 14 "Açaí Mini", 13 deles sem
        categoria nenhuma, com referências VACA…. Medido contra a conta a
        sério: com `id`, o Vendus respeita o nosso título, o nosso preço e
        o nosso tax_id (mesmo diferente do do produto), aplica o desconto
        ao cêntimo, e deixa o produto original intacto.

        `pagamentos` no
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
        # Ver a docstring de VendusModoInvalido: sem um modo explícito
        # ('tests' ou 'normal'), a emissão recusa-se ANTES de qualquer
        # pedido à rede — nunca assume um valor por omissão.
        #
        # `modo` vem de fora desde que ele passou a poder mudar-se no
        # backoffice: isto corre numa thread e não consegue ler a base de
        # dados. Quem o resolve é `fiscal.py`, pela fonte única
        # (`modo.modo_efectivo`). Sem ele, cai-se na variável de ambiente —
        # que é o comportamento de sempre, e o certo para quem nunca tocou no
        # botão. Há um teste a exigir que o `fiscal.py` o passe: sem essa
        # exigência, tirá-lo da chamada fazia o botão MENTIR em silêncio.
        modo = _modo_valido(modo) if modo is not None else _modo_configurado()

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
        #
        # E é o BLOCO INTEIRO que está debaixo dessa promessa, não uma linha
        # escolhida a dedo. A ronda anterior tipificou o `resposta.json()` e
        # deixou o `round(float(amount_gross))` do dicionário de saída FORA do
        # try — com um `amount_gross='8,99'` (vírgula decimal, plausível numa
        # API portuguesa) saía um `ValueError` cru, medido: «é VendusErro?
        # False». Tipificar linha a linha é uma lista que fica desactualizada
        # à primeira linha nova; o que vale é a fronteira — depois do 2xx,
        # NADA sai daqui por tipificar (ver `_documento_da_criacao`).
        try:
            return _documento_da_criacao(resposta, external_reference, modo)
        except VendusErro:
            # Já é da família certa (o `json()` ilegível, o 2xx sem
            # identidade, o total que não se lê) — sobe tal e qual, com a
            # mensagem própria que cada um traz.
            raise
        except Exception as e:  # noqa: BLE001 — ver o comentário acima: a fronteira
            raise _resposta_ilegivel(
                resposta, external_reference, "ao ler o documento criado", e
            ) from e

    def criar_nota_credito(
        self,
        linhas: List[Dict],
        pagamentos: List[Dict],
        external_reference: str,
        register_id: int,
        motivo: str,
        modo: Optional[str] = None,
    ) -> Dict:
        """`POST documents/` com `type=NC` — a Nota de Crédito, o documento
        que corrige uma fatura já entregue à Autoridade Tributária. Mesma
        forma, mesmas defesas e mesmo formato de saída de
        `criar_fatura_simplificada` (ver lá): a fronteira do 2xx, o
        `register_id` comparado antes de sair para a rede, o `mode`
        obrigatório, e o talão já em ESC/POS.

        **O que é PRÓPRIO da NC, e está confirmado na documentação oficial
        do Vendus** (`https://www.vendus.pt/ws/v1.1/documents.doc`, secção
        *Credit Notes*, lida a 22/08/2026 — citada à letra):

            «When creating a NC, you must specify `reference_document` for
            each item, passing `document_number` and `document_row` which
            unequivocally identifies an existing line on the original
            invoice, along with `id` and `qty`. You also have to specify
            `notes` stating the reason for issuing the credit note.»

        Daí as duas diferenças no corpo: cada linha leva um
        `reference_document` (`{document_number, document_row}`) — que é
        quem CHAMA que monta, porque é ele que sabe de que fatura e de que
        linha se trata — e o documento leva `notes` com o motivo. O motivo
        NÃO é decorativo: é exigido pela lei portuguesa (a NC tem de dizer
        porque rectifica) e pela API, e por isso é recusado aqui se vier
        vazio, ANTES de qualquer pedido à rede — a mesma regra do
        `register_id`.

        **O que NÃO se confirmou, e por isso não se inventou.** Não há chave
        de API nesta máquina: nada disto foi exercido ao vivo. Em concreto
        (a) o `document_row` de cada linha é assumido como a POSIÇÃO da
        linha no documento original, 1 a N pela ordem em que foi enviada —
        é o que "a row number of the document where the product is" quer
        dizer, e não há na resposta do `GET documents/` nenhum campo que
        devolva esse número para o confirmar; e (b) as linhas vão com
        `gross_price`, `tax_id` e desconto como foram na fatura, e não só
        com `id`+`qty`. A alternativa a (b) era deixar o Vendus buscar o
        preço ao PRODUTO — que pode ter mudado desde a fatura, e creditaria
        um valor diferente do que o cliente pagou. Quem chama compara o
        total devolvido com o que calculou e assinala a divergência em vez
        de a esconder (`nota_credito.py`).
        """
        esperado = _register_id_configurado()
        if esperado is None or register_id != esperado:
            raise RegisterIdInvalido(
                "register_id %r não bate com o único configurado "
                "(VENDUS_REGISTER_ID=%r) — emissão da nota de crédito "
                "recusada antes de sair para a rede." % (register_id, esperado)
            )
        if not (motivo or "").strip():
            raise NotaDeCreditoSemMotivo(
                "Uma nota de crédito tem de dizer PORQUÊ: o campo `notes` é "
                "exigido pela API do Vendus e pela lei. Recusada antes de "
                "sair para a rede (external_reference=%s)." % external_reference
            )
        modo = _modo_valido(modo) if modo is not None else _modo_configurado()

        corpo: Dict[str, Any] = {
            "type": "NC",
            "register_id": register_id,
            "items": linhas,
            "payments": pagamentos,
            "external_reference": external_reference,
            "notes": motivo.strip(),
            "output": "escpos",
            "mode": modo,
        }

        resposta = self._pedir_com_retentativas("documents/", corpo)
        # A MESMA fronteira da Fatura Simplificada: a partir do 2xx o
        # documento fiscal JÁ EXISTE do lado da AT, e tudo o que falhe a
        # seguir sai TIPADO — nunca um erro cru que quem chama confundiria
        # com "o Vendus recusou e não criou nada".
        try:
            return _documento_da_criacao(resposta, external_reference, modo)
        except VendusErro:
            raise
        except Exception as e:  # noqa: BLE001 — ver o comentário acima: a fronteira
            raise _resposta_ilegivel(
                resposta, external_reference, "ao ler a nota de crédito criada", e
            ) from e

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
        # A MESMA fronteira da criação, do lado da LEITURA: o GET respondeu
        # 2xx e a partir daqui tudo o que rebente é "respondeu e não consigo
        # ler", nunca "não existe". Quem chama trata as duas de forma
        # OPOSTA — `None` autoriza emitir, um erro tipado obriga a manter a
        # reserva incerta — e um `ValueError` cru pelo meio saltava a rota
        # de RECONCILIAR inteira (`except VendusErro`) e saía 500.
        try:
            for doc in _corpo_como_lista(resposta):
                if (
                    str(doc.get("external_reference") or "") == external_reference
                    and doc.get("status") != "A"
                ):
                    return _normaliza_documento(doc)
            return None
        except VendusErro:
            raise
        except Exception as e:  # noqa: BLE001 — ver o comentário acima: a fronteira
            raise _resposta_ilegivel(
                resposta, external_reference, "à procura por referência externa", e
            ) from e

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
            # A mesma fronteira das outras duas: um 2xx cujo corpo não se lê
            # é `VendusRespostaIlegivel`, nunca um erro cru. Quem chama (a
            # verificação do fecho de caixa) traduz isso em "não consegui
            # verificar" — e NUNCA em "o Vendus não tem nada nesse dia", que
            # é o número que a operadora usaria para justificar dinheiro.
            try:
                pagina_dados = _corpo_como_lista(resposta)
            except VendusErro:
                raise
            except Exception as e:  # noqa: BLE001 — ver o comentário acima
                raise _resposta_ilegivel(
                    resposta, "documentos de %s (página %d)" % (data, pagina),
                    "a listar os documentos do dia", e,
                ) from e
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

    def ler_documento(self, documento_id: int) -> Optional[Dict]:
        """UM documento do Vendus, cru, com o ATCUD e as linhas.

        **Porque é que isto não é a lista.** Medido a 2026-09-04: a lista
        (`GET documents/`), mesmo com `view=detailed`, devolve 18 campos e
        nenhum deles é `atcud` ou `items` — traz `payments` e `amount_gross`,
        que é para o que foi feita. O ATCUD é obrigatório para gravar (o índice
        é único) e as linhas são o que faz a fatura valer mais do que zero nos
        Relatórios. Os dois só existem aqui.

        **E este pedido não leva `view`.** O Vendus responde 403 P001 a um
        `view` num GET por id — o detalhe já vem todo (ver a docstring deste
        módulo).

        `None` no 404 (o documento não existe) — não é avaria. Um 2xx cujo
        corpo não se lê continua a ser `VendusRespostaIlegivel`, nunca um
        documento vazio: quem chama tem de saber a diferença entre «não há»
        e «não consegui ler» (a mesma fronteira de `listar_documentos_por_dia`
        acima)."""
        resposta = self._pedir_get_com_retentativas(
            "documents/%d/" % int(documento_id), None)
        if resposta is None:
            return None
        try:
            dados = _corpo_como_lista(resposta)
        except VendusErro:
            raise
        except Exception as e:  # noqa: BLE001 — ver o comentário acima
            raise _resposta_ilegivel(
                resposta, "documento %d" % documento_id, "a ler o documento", e,
            ) from e
        return dados[0] if dados else None

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


def _resposta_ilegivel(
    resposta: httpx.Response, referencia: str, momento: str, erro: Exception
) -> VendusRespostaIlegivel:
    """A excepção TIPADA para "o Vendus respondeu 2xx e não consigo ler o que
    disse" — a única forma de erro que pode sair deste módulo depois de uma
    resposta bem sucedida (ver `VendusRespostaIlegivel`).

    Uma função, e não a mensagem escrita duas vezes: a criação e a leitura
    têm de dizer o MESMO a quem as apanha, senão a próxima ronda tipifica uma
    e esquece a outra — que é exactamente o que aconteceu com o
    `round(float(amount_gross))`."""
    return VendusRespostaIlegivel(
        "O Vendus respondeu %d mas não foi possível ler a resposta %s "
        "(%s: %s) — não é possível saber o que ele disse. "
        "external_reference=%s" % (
            resposta.status_code, momento, type(erro).__name__, erro, referencia,
        )
    )


def _total_do_documento(valor, referencia: str) -> float:
    """O `amount_gross` do Vendus como número — ou um erro TIPADO desta
    família se vier um valor que não se sabe ler.

    **Não se "conserta" a vírgula.** Um `'8,99'` interpretado à mão como 8,99
    parece inofensivo até ao dia em que o separador de milhares aparecer
    (`'1.234,56'` lido como 1,23 €) ou em que o campo trocar de significado.
    Um número que não sabemos ler é um facto a assinalar, não um valor a
    adivinhar: sai `VendusRespostaIlegivel`, quem chama trata a emissão como
    INCERTA (reserva mantida, 503) e alguém vai ver o que o Vendus mandou.

    Ausente, vazio ou zero continua a ser 0,00 €, como sempre foi — é o
    campo a faltar, não um campo ilegível, e o valor com que o Dashboard
    conta (`total_bruto`) tem regra própria e mais exigente: `None`, nunca
    um zero inventado (ver `_valor_monetario`)."""
    if not valor:
        return 0.0
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError) as e:
        raise VendusRespostaIlegivel(
            "O Vendus devolveu um total (`amount_gross`) que não é um número "
            "legível: %r — não se adivinha o valor de uma fatura. "
            "external_reference=%s" % (valor, referencia)
        ) from e


def _documento_da_criacao(
    resposta: httpx.Response, external_reference: str, modo: str
) -> Dict:
    """O documento (formato interno) a partir da resposta 2xx do `POST
    documents/`. Chamada de dentro da fronteira de `criar_fatura_simplificada`
    — tudo o que aqui rebentar sai tipado, seja qual for a linha."""
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
        "total": _total_do_documento(dados.get("amount_gross"), external_reference),
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


def _valor_monetario(valor) -> Optional[float]:
    """Um valor em euros vindo do Vendus, ou `None` quando o campo não vem
    (ou não é legível) — NUNCA 0,00 €.

    A diferença importa nos relatórios: um zero inventado soma-se em
    silêncio e faz um dia de vendas parecer um dia sem IVA; um `None` não
    finge número nenhum. É a mesma regra de ouro de `precos.py` — sem o
    campo certo, não se inventa nada (e muito menos se deriva o líquido do
    bruto por uma taxa assumida: as lojas vendem a 13 % e a 23 %).

    Um campo PRESENTE mas ilegível deixa aviso no log: continua a valer
    `None` (não se inventa nada), mas silenciar isto era o Dashboard perder
    documentos sem ninguém saber porquê. O `total` do documento, esse, nem
    `None` aceita — é um erro tipado, ver `_total_do_documento`."""
    if valor is None or valor == "":
        return None
    try:
        return round(float(valor), 2)
    except (TypeError, ValueError):
        logger.warning(
            "[faturacao] valor monetário ilegível vindo do Vendus: %r — fica "
            "`None` (nunca 0,00 €), e o Dashboard não o soma.", valor,
        )
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
    referencia = str(doc.get("external_reference") or "")
    return {
        "id": doc.get("id"),
        "numero": doc.get("number"),
        "atcud": doc.get("atcud"),
        # A MESMA linha que rebentava crua na criação, e aqui pela rota de
        # RECONCILIAR — que só apanha `VendusErro` e por isso dava 500 do
        # FastAPI, deixando a venda `aberta`, sem documento e com a reserva
        # ainda incerta. Ver `_total_do_documento`.
        "total": _total_do_documento(doc.get("amount_gross"), referencia),
        "talao_escpos": _talao_de(doc, referencia),
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


def _modo_valido(valor) -> str:
    """`'tests'` ou `'normal'`, ou levanta. Não há terceira saída.

    **A recusa é a funcionalidade.** Ausente, vazio, com maiúsculas, com um
    espaço ao fim, ou com um valor inventado — tudo cai aqui, e a emissão
    para. Devolver `'tests'` por omissão era escolher um dos dois enganos
    caros em silêncio (ver `VendusModoInvalido`).

    Separado do sítio de onde o valor VEM: desde que o modo passou a poder ser
    mudado no backoffice, quem o vai buscar é a camada assíncrona
    (`modo.modo_efectivo`), que sabe ler a base de dados. Esta função continua
    a ser a única que decide se um valor serve — as duas coisas nunca podem
    divergir porque só há uma a validar.
    """
    if valor not in _MODOS_VALIDOS:
        raise VendusModoInvalido(
            "O modo de emissão tem de ser 'tests' ou 'normal' — valor "
            "actual: %r. A emissão recusa-se em vez de assumir 'tests' em "
            "silêncio (ver a docstring de VendusModoInvalido)." % (valor,)
        )
    return valor


def _modo_configurado() -> str:
    """O modo escrito na variável de ambiente — a origem de recurso.

    Continua a existir porque é o que vale enquanto ninguém tocar no botão do
    backoffice: no dia do deploy, uma instalação que só tem `VENDUS_MODE` no
    `.env` não pode mudar de comportamento.
    """
    return _modo_valido(os.environ.get("VENDUS_MODE"))
