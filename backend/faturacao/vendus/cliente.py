"""Cliente de leitura do catálogo Vendus (Task 21 — importação).

SÓ LEITURA: usado apenas para TRAZER categorias e produtos da conta Vendus
para o catálogo próprio (faturacao/catalogo.py). Este ficheiro NUNCA escreve
no Vendus — a app L'Açaí, em produção, factura referenciando os artigos de
lá; mexer neles partia-lhe a faturação em silêncio.

Não importa nada de server.py (o pacote faturacao não pode — o server.py é
que importa faturacao, e seria um import circular). É um cliente novo, mas
não do zero: aprende com dois já existentes.

Duas armadilhas já mordidas noutros projectos do mesmo dono, e que este
cliente existe para não repetir:

1. `~/dev/pizzaria/backend/vendus/` (Financeiro, server.py::_fin_vendus_*):
   uma função que lê o catálogo Vendus chamava a API sem `per_page` — o
   Vendus devolve 20 resultados por omissão. Importava 20 produtos, dizia
   que tinha corrido bem, e ninguém deu por isso durante semanas. Aqui,
   `_paginar` pede sempre `per_page=100` e só pára quando o cabeçalho
   `X-Paginator-Pages` diz que já não há mais páginas — não confia só em "a
   página veio mais curta que per_page", que é o sinal fraco que
   `server.py::_fin_vendus_cost_map` usa (fica só como reserva, se um dia
   uma resposta vier sem o cabeçalho).

2. `~/dev/pizzaria/backend/vendus/client.py::list_app_invoices`: um filtro
   sem resultados devolve 404 com o corpo a incluir o código `A001` — NÃO é
   uma avaria, é "zero resultados". Uma loja nova sem produtos ainda no
   Vendus não pode rebentar a importação.

Padrão do `transport` injectável copiado do mesmo cliente da pizzaria
(`VendusClient`): os testes passam um `httpx.MockTransport` e nunca tocam a
rede real.
"""
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.vendus.pt/ws/v1.1/"
POR_PAGINA = 100  # o máximo aceite pela API Vendus (mesmo valor do Financeiro)

# Limite defensivo (mesmo espírito de _FIN_VENDUS_MAX_PROD_PAGES em
# server.py): um catálogo de lojas de açaí nunca chega perto disto. Se
# chegar, é configuração errada (ex.: um filtro que devolve tudo do Vendus,
# não só desta conta) — falhar alto é melhor do que ficar presa num loop.
MAX_PAGINAS = 500


class VendusErro(Exception):
    """Erro base desta integração de leitura do Vendus."""


class VendusIndisponivel(VendusErro):
    """Rede, timeout ou 5xx — falha transitória, não um dado inválido."""


class VendusHTTPErro(VendusErro):
    """Resposta HTTP de erro (4xx que não seja o 404/A001 de "zero resultados")."""

    def __init__(self, status_code: int, corpo: str):
        self.status_code = status_code
        self.corpo = corpo
        super().__init__("Vendus HTTP %d: %s" % (status_code, corpo[:300]))


@dataclass(frozen=True)
class ContaVendus:
    """Uma conta Vendus configurada em VENDUS_ACCOUNTS: a chave da API e o
    NIF da empresa a que pertence."""

    chave: str
    company_nif: str


def _so_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def obter_conta(fat_nif: Optional[str] = None) -> Optional[ContaVendus]:
    """Lê VENDUS_ACCOUNTS do ambiente (mesmo formato JSON já usado pelo
    Financeiro — ver server.py::_fin_vendus_accounts) e devolve a entrada
    cujo `company_nif` bate com `fat_nif` (por omissão a variável de
    ambiente FAT_NIF, ou "517542510" — Fordaimon Foods — se nem essa
    estiver definida).

    Devolve None se VENDUS_ACCOUNTS estiver ausente, malformado, sem chave
    numa entrada, ou sem nenhuma entrada com esse NIF — quem chama decide o
    que fazer. O endpoint de importação transforma isto numa mensagem clara
    (400), nunca um 500."""
    nif = _so_digitos(fat_nif if fat_nif is not None else os.environ.get("FAT_NIF") or "517542510")
    raw = os.environ.get("VENDUS_ACCOUNTS") or "[]"
    try:
        contas = json.loads(raw)
    except Exception as e:  # noqa: BLE001 — JSON inválido não é um 500
        logger.warning("[faturacao-vendus] VENDUS_ACCOUNTS inválido: %s", e)
        return None
    if not isinstance(contas, list):
        return None
    for conta in contas:
        if not isinstance(conta, dict):
            continue
        if _so_digitos(conta.get("company_nif")) != nif:
            continue
        chave = str(conta.get("key") or "").strip()
        if not chave:
            continue
        return ContaVendus(chave=chave, company_nif=nif)
    return None


def _paginas_totais(resposta: httpx.Response) -> Optional[int]:
    """Lê X-Paginator-Pages do cabeçalho da resposta. None se ausente ou não
    numérico — quem chama cai então para o sinal fraco (página incompleta)."""
    try:
        return int(resposta.headers.get("X-Paginator-Pages"))
    except (TypeError, ValueError):
        return None


def _corpo_como_lista(resposta: httpx.Response) -> List[dict]:
    if not resposta.content:
        return []
    dados = resposta.json()
    if isinstance(dados, dict):
        return [dados]
    if isinstance(dados, list):
        return dados
    return []


class ClienteVendus:
    """Cliente HTTP SÓ DE LEITURA para o catálogo Vendus (categorias e
    produtos). HTTP Basic com a chave da API como username (password
    vazia) — mesma autenticação do resto da casa. `transport` injectável
    para os testes (nunca tocam a rede real)."""

    def __init__(
        self, chave: str, transport: Optional[httpx.BaseTransport] = None, timeout: float = 20.0
    ):
        self._http = httpx.Client(
            base_url=BASE_URL, auth=(chave, ""), timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ClienteVendus":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def listar_categorias(self) -> List[dict]:
        return self._paginar("products/categories/")

    def listar_produtos(self) -> List[dict]:
        return self._paginar("products/")

    def _paginar(self, caminho: str) -> List[dict]:
        """GET paginado até esgotar. Pede sempre `per_page=100` (a armadilha
        da Task 21: sem isto o Vendus devolve só 20) e usa
        `X-Paginator-Pages` da PRIMEIRA resposta para saber quantas páginas
        tem de pedir. Sem o cabeçalho, cai para o sinal fraco (página mais
        curta que per_page = última)."""
        resultado: List[dict] = []
        pagina = 1
        total_paginas: Optional[int] = None
        while True:
            if pagina > MAX_PAGINAS:
                raise VendusErro(
                    "Catálogo Vendus com mais de %d páginas (%d itens já lidos) — "
                    "parece configuração errada; leitura interrompida em vez de "
                    "ficar presa." % (MAX_PAGINAS, len(resultado))
                )
            resposta = self._pedir(caminho, {"per_page": POR_PAGINA, "page": pagina})
            if resposta is None:
                break  # 404/A001 — zero resultados para este filtro
            pagina_dados = _corpo_como_lista(resposta)
            resultado.extend(pagina_dados)
            if total_paginas is None:
                total_paginas = _paginas_totais(resposta)
            if total_paginas is not None:
                if pagina >= total_paginas:
                    break
            elif len(pagina_dados) < POR_PAGINA:
                break
            pagina += 1
        return resultado

    def _pedir(self, caminho: str, parametros: Dict[str, Any]) -> Optional[httpx.Response]:
        try:
            resposta = self._http.get(
                caminho, params=parametros, headers={"Accept": "application/json"}
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VendusIndisponivel(str(e)) from e
        if resposta.status_code == 404:
            corpo = resposta.text or ""
            if "A001" in corpo:
                return None  # "No data" — zero resultados, não uma avaria
            raise VendusHTTPErro(resposta.status_code, corpo)
        if 500 <= resposta.status_code < 600:
            raise VendusIndisponivel("Vendus %d" % resposta.status_code)
        if resposta.status_code >= 400:
            raise VendusHTTPErro(resposta.status_code, resposta.text)
        return resposta
