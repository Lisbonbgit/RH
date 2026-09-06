"""**O stock a descer sozinho quando uma fatura sai** — a Fase 2.

A Fase 1 pôs as gramagens nas personalizações e um relatório a somar o que
saiu. Aqui o número deixa de ser só para ler: cada fatura emitida tira do
armazém o que o copo gastou.

**Nada neste ficheiro pode impedir uma fatura de sair.** É a regra que manda
sobre todas as outras, e não é teórica: as excepções que a rota `finalizar`
apanha são nomeadas uma a uma, nenhuma é genérica — uma excepção que suba
daqui devolve 500 ao balcão com a fatura JÁ entregue à AT, e o ecrã lê um 500
como «não saiu nada» e convida a operadora a emitir outra vez. Por isso quem
chama envolve isto num `try/except Exception` e engole tudo; e por isso a
chamada ao Estoque tem quatro segundos e não quinze.

**Onde isto se pendura, e porquê esse sítio.** No fim de
`fiscal._ligar_venda_ao_documento`, que é a ÚNICA escrita de `estado:
"emitida"` numa venda em todo o backend, e por onde convergem os cinco
caminhos que acabam num documento fiscal: a emissão feliz, a retoma de uma
reserva incerta, a retoma que acaba por emitir, e os dois ramos da
reconciliação de reservas presas. O sítio óbvio — ao lado do
`enfileirar_venda_emitida`, que põe o talão na fila — parecia servir e não
serve: tem um só chamador, dentro da rota `finalizar`, e deixava sem stock,
em silêncio, toda a venda salva por reconciliação.

**Não desconta duas vezes.** `_ligar_venda_ao_documento` corre mais do que uma
vez para a mesma venda (o retry que reencontra o documento por
`DuplicateKeyError`, e a reconciliação a passar por cima de uma emissão em
voo) e o `POST /integ/movimento` não aceita chave de idempotência nenhuma. A
defesa é uma marca na própria venda, escrita ANTES de se descontar e com a
condição de estar ausente: quem a conseguir escrever é quem desconta, e é um
só. Escrita antes e não depois de propósito — se o processo morrer a meio, o
erro é não descontar (visível no relatório, recuperável à mão) e não descontar
a dobrar (invisível, e só aparece na contagem do mês como um roubo que não
houve).

**As vendas da app nunca passam por aqui**, e é correcto: entram como
documentos lidos do Vendus, sem venda nossa e sem opções nenhumas. O relatório
de Consumo já o diz em letra visível; quem ligar o interruptor tem de saber
que o stock desce só pelo que sai do balcão.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .auth import gestor_atual
from .consumo import consumo_de_uma_venda
from .db import COLECOES, obter_db
from .unidades import FAMILIA_DO_ARTIGO

logger = logging.getLogger(__name__)

# A chave do interruptor em `fat_definicoes` — a colecção genérica onde as
# definições deste módulo já vivem, para não nascer uma colecção por pergunta.
CHAVE_DEFINICOES = "desconto_stock"


async def desconto_ligado(db) -> bool:
    """Se o desconto automático está ligado.

    **Ausente quer dizer DESLIGADO.** É o contrário do que o relatório diário
    faz (devolve activo quando não há documento) e é deliberado: aquele manda
    um email a mais, este mexe no stock de cinco lojas. Uma definição que se
    liga sozinha no dia do deploy é a pior maneira de estrear isto.

    `db` vem por parâmetro e nunca de um `obter_db()` cá dentro — é o que
    torna a função testável sem base de dados, e o molde é o `modo_efectivo`.
    """
    doc = await db[COLECOES["definicoes"]].find_one({"id": CHAVE_DEFINICOES}, {"_id": 0})
    return bool((doc or {}).get("ativo"))


async def _ligado_desde(db) -> Optional[str]:
    """Quando o interruptor foi ligado — para não descontar o passado.

    Uma reconciliação de reserva presa pode salvar hoje uma venda de há
    semanas. Sem esta data, ligar o interruptor fazia sair do armazém o copo
    que já tinha saído, e o stock ficava a menos sem ninguém perceber porquê.
    """
    doc = await db[COLECOES["definicoes"]].find_one({"id": CHAVE_DEFINICOES}, {"_id": 0})
    return (doc or {}).get("mudado_em")


def saidas_de_uma_venda(venda: Optional[Dict]) -> List[Dict]:
    """As saídas de stock que esta venda provoca, já na unidade do artigo.

    Reaproveita `consumo.consumo_de_uma_venda` e não repete a soma: é lá que
    estão presas as duas armadilhas que uma conta ingénua não vê — a dose é
    uma entrada REPETIDA (dois toques na Nutella são duas linhas iguais) e a
    quantidade da linha é FRACCIONÁRIA (uma conta dividida por três grava
    0,3337 e leva as opções inteiras para cada parte).

    Só entra o que tem artigo do Estoque escolhido: uma gramagem escrita sem
    artigo conta no relatório (pelo nome) mas não tem de onde sair.

    A quantidade que sai daqui está na unidade de BASE da família (kg, L ou
    un), que é exactamente a unidade em que o artigo conta — a validação do
    catálogo garante que as duas famílias batem certo. É por isso que se pode
    mandar o número cru para um movimento que não leva unidade nenhuma.
    """
    por_chave: Dict = {}
    for gasto in consumo_de_uma_venda(venda):
        artigo = gasto.get("destino_id")
        if not artigo:
            continue
        # **A unidade do ARTIGO lê-se aqui, e não se confia na configuração.**
        #
        # O validador do catálogo só corre quando alguém grava um grupo: tudo
        # o que ficou gravado na Fase 1 tem artigo e NÃO tem esta unidade, e um
        # artigo pode mudar de unidade do lado do Estoque depois do carimbo.
        # Sem ler isto no ponto de uso, a defesa contra o factor de mil era
        # uma frase numa docstring — o desconto convertia pela unidade da
        # FICHA e mandava 0,03 para um artigo contado em pacotes.
        #
        # Uma ficha por acertar não desconta nada. Nunca desconta errado.
        medida = gasto.get("unidade_do_artigo")
        familia_do_artigo = FAMILIA_DO_ARTIGO.get(medida)
        if familia_do_artigo is None:
            logger.warning(
                "[faturacao] a personalização «%s» está ligada ao artigo %s mas não se "
                "sabe em que unidade ele conta (%r) — não desconta",
                gasto.get("destino_nome"), artigo, medida)
            continue
        if familia_do_artigo != gasto["familia"]:
            logger.error(
                "[faturacao] a personalização «%s» está escrita em %s e o artigo %s conta "
                "em «%s» — medidas de coisas diferentes, não desconta",
                gasto.get("destino_nome"), gasto["familia"], artigo, medida)
            continue
        # Junta-se por artigo antes de telefonar: um copo com três toppings do
        # mesmo artigo é UMA saída, não três chamadas de rede com a operadora
        # à espera. E a família entra na chave, como no relatório: o mesmo
        # artigo escrito em quilos e em unidades são duas contas diferentes,
        # e somá-las dava um número que não quer dizer nada.
        chave = (artigo, gasto["familia"])
        por_chave[chave] = por_chave.get(chave, 0.0) + gasto["quantidade"]
    saidas = []
    for (artigo, _familia), quantidade in sorted(por_chave.items()):
        # Arredonda ANTES de decidir se vale a pena telefonar: um consumo
        # minúsculo arredondava a zero e ia à mesma, e um movimento de zero só
        # faz lixo no histórico do Estoque.
        quantidade = round(quantidade, 4)
        if quantidade > 0:
            saidas.append({"produto_id": artigo, "quantidade": quantidade})
    return saidas


async def _reclama_a_venda(db, venda_id: str, quando: str) -> bool:
    """Marca a venda como descontada, e diz se foi ESTA chamada a consegui-lo.

    A condição `{"stock_descontado_em": None}` casa tanto o campo ausente como
    o campo a nulo (é assim que o Mongo lê `None` numa igualdade), e o
    `modified_count` distingue quem chegou primeiro — `matched_count` não
    serviria: as duas chamadas CASAM com a venda, só uma é que a MUDA. É o mesmo desenho de
    reclamação que o núcleo fiscal já usa para as reservas.
    """
    r = await db[COLECOES["vendas"]].update_one(
        {"id": venda_id, "stock_descontado_em": None},
        {"$set": {"stock_descontado_em": quando}},
    )
    return getattr(r, "modified_count", 0) == 1


async def descontar_venda(db, venda_id: str, *, agora: Optional[str] = None) -> Dict:
    """Tira do armazém o que esta venda gastou. Devolve o que fez, para o log.

    A ordem é do mais barato para o mais caro, e a reclamação fica mesmo antes
    de telefonar: não se escreve marca nenhuma numa venda que não tinha nada
    para descontar (senão uma venda sem gramagens ficava marcada e, no dia em
    que as gramagens fossem escritas, uma reconciliação já não a apanhava).
    """
    if not await desconto_ligado(db):
        return {"estado": "desligado"}

    venda = await db[COLECOES["vendas"]].find_one(
        {"id": venda_id}, {"_id": 0, "id": 1, "linhas": 1, "loja_id": 1,
                           "stock_descontado_em": 1, "criada_em": 1})
    if not venda:
        return {"estado": "sem-venda"}
    # Uma venda anterior ao dia em que o interruptor foi ligado não desconta:
    # o copo saiu antes de isto existir, e a reconciliação de reservas presas
    # pode trazê-la de volta semanas depois.
    ligado_desde = await _ligado_desde(db)
    criada_em = venda.get("criada_em")
    if ligado_desde and criada_em and str(criada_em) < str(ligado_desde):
        logger.info(
            "[faturacao] venda %s é de antes de o desconto ser ligado (%s < %s) — "
            "não desconta", venda_id, criada_em, ligado_desde)
        return {"estado": "anterior-ao-interruptor"}
    if venda.get("stock_descontado_em"):
        return {"estado": "ja-descontado"}

    saidas = saidas_de_uma_venda(venda)
    if not saidas:
        return {"estado": "nada-a-descontar"}

    loja = await db[COLECOES["lojas"]].find_one(
        {"id": venda.get("loja_id")}, {"_id": 0, "estoque_unidade_id": 1, "nome": 1})
    unidade = (loja or {}).get("estoque_unidade_id")
    if not unidade:
        # Não é uma avaria: é uma loja por ligar. Fica dito no log uma vez por
        # venda, e o relatório de Consumo continua a contar o que devia ter
        # saído — que é o que permite recuperar isto à mão depois.
        logger.warning(
            "[faturacao] venda %s: a loja %s não está ligada a nenhuma unidade do "
            "Estoque, o stock não desceu", venda_id, venda.get("loja_id"))
        return {"estado": "loja-sem-unidade"}

    quando = agora or datetime.now(timezone.utc).isoformat()
    if not await _reclama_a_venda(db, venda_id, quando):
        # Outra chamada chegou primeiro — o retry do DuplicateKeyError, ou a
        # reconciliação a passar por cima de uma emissão em voo.
        return {"estado": "ja-descontado"}

    # O import é local de propósito: um erro de importação neste módulo não
    # pode acontecer no arranque do pacote, que é montado sem `try` e leva o
    # portal inteiro atrás — RH e Financeiro incluídos.
    from estoque_cliente import descontar_saida

    # **Em paralelo, e não uma a uma.** As saídas são independentes entre si e
    # o tecto de espera é POR CHAMADA: em fila, um copo com quatro artigos
    # ligados fazia a operadora esperar quatro vezes quatro segundos com o
    # cliente à frente. Em paralelo, o pior caso volta a ser quatro.
    async def _uma(saida):
        try:
            await descontar_saida(
                unidade_id=unidade,
                produto_id=saida["produto_id"],
                quantidade=saida["quantidade"],
                actor="Faturação (venda %s)" % venda_id,
            )
            return None
        except Exception as e:  # noqa: BLE001 — nada aqui pode parar uma fatura
            logger.error(
                "[faturacao] venda %s: a saída de %s de %s falhou: %s",
                venda_id, saida["quantidade"], saida["produto_id"], e)
            return saida

    resultados = await asyncio.gather(*[_uma(s) for s in saidas])
    falhadas = [r for r in resultados if r is not None]
    feitas = [s for s, r in zip(saidas, resultados) if r is None]

    if falhadas:
        # A marca fica na mesma, e é a escolha menos má: tirá-la abria a porta
        # a descontar duas vezes o que já saiu (as `feitas` deste mesmo ciclo).
        # O que falhou fica no log e na diferença entre o relatório de Consumo
        # e o stock — visível, e recuperável à mão.
        logger.error(
            "[faturacao] venda %s: %d de %d saídas falharam; o stock ficou por "
            "acertar nesses artigos", venda_id, len(falhadas), len(saidas))
    return {"estado": "descontado", "feitas": len(feitas), "falhadas": len(falhadas)}


# --- As portas do interruptor -------------------------------------------------

router = APIRouter()


class InterruptorEntrada(BaseModel):
    ativo: bool


@router.get("/desconto-stock")
async def ler_desconto_stock(_: dict = Depends(gestor_atual)) -> dict:
    """O estado do interruptor, e o que o dono precisa de saber antes de o ligar.

    Não devolve só o `ativo`: devolve também as lojas que ainda não estão
    ligadas a uma unidade do Estoque. Ligar o desconto com lojas por ligar não
    dá erro nenhum — o stock dessas simplesmente não desce, em silêncio, e a
    diferença só aparece na contagem do mês.

    Só conta as lojas ACTIVAS: uma loja fechada não vende, e enchia o aviso de
    nomes que não importam até ninguém o ler.
    """
    db = obter_db()
    doc = await db[COLECOES["definicoes"]].find_one({"id": CHAVE_DEFINICOES}, {"_id": 0})
    lojas = await db[COLECOES["lojas"]].find(
        {}, {"_id": 0, "id": 1, "nome": 1, "estoque_unidade_id": 1, "ativa": 1}
    ).to_list(200)
    return {
        "ativo": bool((doc or {}).get("ativo")),
        "mudado_em": (doc or {}).get("mudado_em"),
        "lojas_por_ligar": [
            {"id": l["id"], "nome": l.get("nome")}
            for l in lojas
            if l.get("ativa", True) and not l.get("estoque_unidade_id")
        ],
    }


@router.put("/desconto-stock")
async def mudar_desconto_stock(
    dados: InterruptorEntrada, gestor: dict = Depends(gestor_atual)
) -> dict:
    db = obter_db()
    await db[COLECOES["definicoes"]].update_one(
        {"id": CHAVE_DEFINICOES},
        {"$set": {"ativo": dados.ativo,
                  "mudado_em": datetime.now(timezone.utc).isoformat(),
                  # Quem ligou isto fica escrito: é uma decisão com
                  # consequências no armazém, não uma preferência de ecrã.
                  "mudado_por": (gestor or {}).get("nome") or (gestor or {}).get("email")}},
        upsert=True,
    )
    return await ler_desconto_stock(_={})
