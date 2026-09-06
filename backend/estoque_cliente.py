"""**Falar com o serviço de Estoque** — de onde quer que seja do backend.

O stock vive noutra aplicação, noutro servidor, com base de dados própria: o
portal só lhe telefona por HTTP com uma chave de serviço partilhada. Isso
sempre foi verdade; o que muda com o desconto automático é QUEM telefona.

Até aqui só o `server.py` falava com o Estoque, e as rotas `/api/estoque/*`
bastavam. Agora a Faturação precisa de descontar stock quando uma fatura sai —
e `faturacao` não pode importar `server` (é o `server` que importa o pacote
`faturacao`; ao contrário é um ciclo que rebenta no arranque e leva o portal
inteiro atrás, RH e Financeiro incluídos).

Por isso este módulo, que não importa nada do portal e pode ser importado por
qualquer lado. Fica aqui só o que os dois lados partilham — o endereço, a
chave, e a saída de stock — e não o cliente todo: mudar seis funções de casa
dentro de um ficheiro de 9500 linhas que está em produção era um risco maior
do que o problema que resolvia.
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ESTOQUE_API_URL = os.environ.get("ESTOQUE_API_URL", "https://estoque.lisbonb.com/api")


class EstoqueNaoConfigurado(Exception):
    """Não há chave de serviço. Não é uma avaria — é uma instalação por acabar."""


def chave_de_servico() -> Optional[str]:
    # Lida a CADA chamada e não à importação: o `.env` do servidor pode ganhar
    # a chave sem o portal reiniciar, e uma constante de módulo congelava o
    # «não configurado» até ao próximo deploy.
    return os.environ.get("ESTOQUE_SERVICE_KEY")


def cabecalhos() -> dict:
    key = chave_de_servico()
    if not key:
        raise EstoqueNaoConfigurado("Integração de estoque não configurada.")
    # No HEADER e nunca no URL: um `?key=` acaba escrito nos registos do nginx.
    return {"X-Service-Key": key}


# 4 segundos, e não os 12-15 das rotas do backoffice.
#
# Quem espera por isto é a operadora com o cliente à frente: o desconto corre
# depois de a fatura estar emitida, mas ainda ANTES de a resposta chegar ao
# ecrã do POS. Quinze segundos pendurados num serviço em baixo seriam quinze
# segundos de fila. Falhar depressa e em silêncio é melhor do que descontar
# tarde: o relatório de Consumo continua a somar o que devia ter saído, e a
# diferença é visível e recuperável.
TIMEOUT_SAIDA_SEGUNDOS = 4.0


async def descontar_saida(
    unidade_id: str, produto_id: str, quantidade: float, actor: str,
    timeout: float = TIMEOUT_SAIDA_SEGUNDOS,
) -> dict:
    """Tira `quantidade` do stock de um artigo numa unidade.

    **A quantidade é POSITIVA e o que a torna uma saída é o `tipo`** — é assim
    que o resto do portal já fala com o Estoque (`MovimentoDialog`), e uma
    quantidade negativa aqui não subtrai duas vezes: entra como entrada de
    valor negativo, que é outra coisa.

    **E vai na unidade em que o ARTIGO conta**, não na que se escreveu na
    ficha: o movimento não leva unidade nenhuma, o número é interpretado do
    lado de lá. É por isso que quem chama converte primeiro — 30 g de um
    artigo contado em quilos são `0.03`, e mandar `30` esvaziava o armazém.

    Levanta em vez de devolver erro: quem chama está dentro de um `try/except`
    que engole tudo, porque nada aqui pode impedir uma fatura de sair.
    """
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        r = await http_client.post(
            f"{ESTOQUE_API_URL}/integ/movimento",
            json={
                "tipo": "saida",
                "unidade_id": unidade_id,
                "produto_id": produto_id,
                "quantidade": quantidade,
                "actor": actor,
            },
            headers=cabecalhos(),
        )
    if r.status_code >= 400:
        detalhe = None
        try:
            detalhe = r.json().get("detail")
        except Exception:
            detalhe = None
        raise RuntimeError(
            "O Estoque respondeu %s a uma saída: %s" % (r.status_code, detalhe or "sem detalhe")
        )
    try:
        return r.json()
    except Exception:
        return {}
