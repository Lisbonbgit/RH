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
2. O GET de um documento não aceita `view` (403 P001). Não se aplica
   directamente aqui (este módulo só EMITE, não lê documentos), mas fica
   registado para quem ler os dois módulos lado a lado.

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
"""
import base64
import os
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from .cliente import BASE_URL, VendusErro, VendusHTTPErro, VendusIndisponivel

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


class VendusRateLimitado(VendusErro):
    """429 (créditos esgotados) mesmo depois de esperar `Rate-Limit-Reset` e
    repetir o número de vezes permitido."""


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

        corpo: Dict[str, Any] = {
            "type": "FS",
            "register_id": register_id,
            "items": linhas,
            "payments": pagamentos,
            "external_reference": external_reference,
            "output": "escpos",
            "mode": _modo_configurado(),
        }
        if cliente:
            corpo["client"] = cliente

        resposta = self._pedir_com_retentativas("documents/", corpo)
        dados = resposta.json() if resposta.content else {}

        output_b64 = dados.get("output")
        talao = base64.b64decode(output_b64) if output_b64 else b""

        return {
            "id": dados.get("id"),
            "numero": dados.get("number"),
            "atcud": dados.get("atcud"),
            "total": round(float(dados.get("amount_gross") or 0), 2),
            "talao_escpos": talao,
        }

    def _pedir_com_retentativas(self, path: str, corpo: Dict) -> httpx.Response:
        tentativa = 0
        while True:
            tentativa += 1
            try:
                resposta = self._http.post(path, json=corpo)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                # Ver a docstring do módulo: um erro de rede não se repete
                # aqui — não sabemos se o Vendus chegou a processar o
                # pedido, e repetir às cegas arriscava emitir a dobrar.
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


def _register_id_configurado() -> Optional[int]:
    valor = os.environ.get("VENDUS_REGISTER_ID")
    if not valor:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _modo_configurado() -> str:
    return os.environ.get("VENDUS_MODE") or "tests"
