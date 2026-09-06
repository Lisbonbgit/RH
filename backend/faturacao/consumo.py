"""**O que saiu do armazém** — o relatório que dá sentido às gramagens.

As personalizações passaram a poder dizer o que gastam (`catalogo.OpcaoEntrada`:
`consumo`, `consumo_unidade`, `estoque_produto_id`) e a venda carimba isso em
cada opção da linha (`venda._carimbar_sai_na_fatura`). Aqui soma-se: «entre 1 e
7 de setembro saíram 4,2 kg de granola».

**Porque é que isto existe antes da baixa automática.** É contra este número
que se confere uma contagem do armazém. Uma gramagem errada com o desconto
automático já ligado faz o stock mentir com autoridade — e ninguém dá por isso
até ao fim do mês. Um mês de relatório comparado com uma contagem custa nada e
diz tudo.

Três coisas que este ficheiro tem de acertar, e que são exactamente onde uma
soma ingénua se engana:

1. **Uma dose é uma ENTRADA REPETIDA, não uma quantidade.** Cada toque na
   Nutella acrescenta outro dicionário igual à lista de opções da linha
   (`PosPersonalizacoes.tocar`). Quem contar opções DISTINTAS subavalia todas
   as doses duplas — metade da granola desaparecia da conta.

2. **A quantidade da linha é FRACCIONÁRIA.** Uma conta dividida por três grava
   quantidades como `0,3337` e as opções vão INTEIRAS para cada parte
   (`venda.dividir`). Somar por opção sem multiplicar pela quantidade da parte
   TRIPLICA o consumo de uma conta dividida.

3. **As vendas da app não trazem opções nenhumas.** Entram como documentos
   lidos do Vendus (`sincronizacao_app`), com `origem='app'` e `linhas_vendus`
   — o que a app manda ao Vendus é `{reference, qty, gross_price}` e mais
   nada, portanto os toppings nunca saíram da app e o Vendus nunca os teve.
   Não se inventa: contam-se à parte e diz-se quantos documentos ficaram de
   fora. Um relatório que os somasse como zero dizia «a app não gasta
   granola», que é falso e parece verdade.

**O eixo da origem nasce já aqui, com a app a zero de propósito.** Quando a
porta de leitura da app existir, o número do mês passado não pode mudar
sozinho — e sem este eixo mudava, sem ninguém perceber porquê.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .periodos import janela_de_datas
from .relatorios import _data, _TECTO_DOCUMENTOS

router = APIRouter()


# A conversão vive em `unidades.py`, partilhada com a validação do catálogo:
# duas cópias do mapa erram por um factor de mil quando divergem.
from .unidades import UNIDADE_BASE as _UNIDADE_BASE, _FAMILIAS  # noqa: E402


def _consumo_da_opcao(opcao: Dict, quantidade_da_linha: float) -> Optional[Dict]:
    """O que UMA entrada de opção gasta, já multiplicada pela linha.

    Devolve `None` para tudo o que não é uma medição utilizável: a opção sem
    gramagem carimbada (a esmagadora maioria), e a que traga uma unidade que
    ninguém sabe converter. Silenciar a segunda seria pior do que não somar —
    por isso quem chama conta-as em `por_medir`.
    """
    consumo = opcao.get("consumo")
    if consumo is None:
        return None
    familia = _FAMILIAS.get(opcao.get("consumo_unidade"))
    if familia is None:
        return None
    nome_da_familia, factor = familia
    return {
        # Sem artigo do Estoque escolhido, a chave é o NOME da opção: a
        # gramagem escreve-se de uma assentada e ligar cada opção ao artigo é
        # o passo seguinte. Entre as duas coisas o relatório tem de continuar
        # a dizer alguma coisa — «Granola: 4,2 kg (por ligar)» é útil, uma
        # linha em falta não é.
        "destino_id": opcao.get("estoque_produto_id"),
        "destino_nome": opcao.get("nome"),
        # A unidade em que o ARTIGO conta, tal como foi carimbada na linha.
        # Não é usada na soma do relatório (que soma na unidade de base da
        # ficha) — é o desconto que a lê, para não converter às cegas.
        "unidade_do_artigo": opcao.get("estoque_unidade_medida"),
        "familia": nome_da_familia,
        # `float(quantidade)` e não `int`: uma conta dividida por três grava
        # 0,3337 e um `int()` aqui apagava o consumo dessa parte por inteiro.
        "quantidade": float(consumo) * factor * float(quantidade_da_linha or 0),
        # **A dose conta COPOS, não toques.** Uma linha de 2 açaís com uma
        # escolha de granola serviu DUAS doses, e uma conta dividida por três
        # serviu UMA (as três partes trazem a opção inteira, cada uma com um
        # terço da quantidade). Contar `+= 1` por entrada errava para os dois
        # lados ao mesmo tempo — e as duas colunas da tabela deixavam de
        # reconciliar: quem dividisse os quilos pelas doses para conferir a
        # ficha não fechava a conta e desconfiava da gramagem certa.
        "doses": float(quantidade_da_linha or 0),
    }


def consumo_de_uma_venda(venda: Optional[Dict]) -> List[Dict]:
    """Tudo o que uma venda do balcão gastou, uma entrada por dose.

    Percorre as opções TAL COMO ESTÃO GRAVADAS — repetidas quando houve mais
    do que uma dose, que é como o POS as grava. Sem `set()` e sem agrupar por
    id: é aí que as doses duplas se perdem.
    """
    saida = []
    for linha in (venda or {}).get("linhas") or []:
        quantidade = linha.get("quantidade") or 0
        for opcao in linha.get("opcoes") or []:
            gasto = _consumo_da_opcao(opcao, quantidade)
            if gasto is not None:
                saida.append(gasto)
    return saida


def agregar_consumo(documentos: List[Dict], vendas: Dict[str, Dict]) -> Dict:
    """Junta o consumo de todos os documentos de um período.

    `vendas` é o mapa `venda_id -> venda`; um documento sem venda do nosso
    lado (o caso da app) não tem opções nenhumas e conta-se como não medido.
    """
    por_chave: Dict = {}
    documentos_da_app = 0
    documentos_do_balcao = 0
    sem_venda = 0

    notas_de_credito = 0
    for doc in documentos:
        # **Uma nota de crédito não vendeu nada a ninguém.** Vive na MESMA
        # colecção das faturas, com `tipo: "NC"`, e — de propósito — sem
        # `venda_id`. Sem esta saída ia contada como venda do balcão E como
        # documento por medir: num dia com 650 faturas e 3 devoluções, o
        # rodapé dizia 653 vendas. Do lado da app era pior, porque a
        # sincronização também aceita NC: o aviso «faltam N vendas da app»
        # contava as devoluções dela como vendas em falta.
        #
        # O consumo em si já estava certo por construção (a NC não tem venda
        # de onde ler opções, e a decisão do dono é que uma devolução não
        # repõe stock) — o que mentia eram os contadores que ele vai
        # comparar com uma contagem.
        if doc.get("tipo") == "NC":
            notas_de_credito += 1
            continue
        # A origem é do DOCUMENTO e não da venda: é o `sincronizacao_app` que
        # a carimba, e é a única coisa que distingue um copo vendido no
        # balcão de um vendido na app.
        da_app = doc.get("origem") == "app"
        venda = vendas.get(doc.get("venda_id")) if doc.get("venda_id") else None
        if da_app:
            documentos_da_app += 1
        else:
            documentos_do_balcao += 1
        if venda is None:
            sem_venda += 1
            continue
        for gasto in consumo_de_uma_venda(venda):
            # A chave junta o destino com a FAMÍLIA: o mesmo artigo escrito
            # em gramas e em unidades são duas contas diferentes, e somá-las
            # dava um número que não quer dizer nada.
            chave = (gasto["destino_id"] or gasto["destino_nome"], gasto["familia"])
            linha = por_chave.get(chave)
            if linha is None:
                linha = por_chave[chave] = {
                    "estoque_produto_id": gasto["destino_id"],
                    "nome": gasto["destino_nome"],
                    "unidade": _UNIDADE_BASE[gasto["familia"]],
                    "quantidade": 0.0,
                    "doses": 0,
                    "ligado_ao_estoque": bool(gasto["destino_id"]),
                }
            linha["quantidade"] += gasto["quantidade"]
            linha["doses"] += gasto["doses"]

    linhas = sorted(
        por_chave.values(), key=lambda l: (-l["quantidade"], l["nome"] or "")
    )
    # Arredonda só na saída: somar já arredondado come milésimas a cada dose,
    # e são milhares de doses num mês.
    for linha in linhas:
        linha["quantidade"] = round(linha["quantidade"], 3)
        # As doses vêm somadas em fracções (as contas divididas) — arredondam
        # com a quantidade, pela mesma razão e no mesmo sítio.
        linha["doses"] = round(linha["doses"], 2)
    return {
        "linhas": linhas,
        "documentos_do_balcao": documentos_do_balcao,
        # **A app, contada e dita.** Fica a zero enquanto não houver porta de
        # leitura do lado dela — mas o número de documentos aparece, para o
        # ecrã poder dizer «e faltam aqui 214 vendas da app».
        "documentos_da_app": documentos_da_app,
        "documentos_por_medir": sem_venda,
        # Ditas e não escondidas, como tudo o resto neste relatório: quem
        # confere quer saber que houve devoluções, mesmo que elas não mexam
        # em quilo nenhum.
        "notas_de_credito": notas_de_credito,
    }


@router.get("/consumo")
async def relatorio_de_consumo(
    de: str,
    ate: str,
    loja_id: Optional[str] = None,
    _: dict = Depends(gestor_atual),
) -> dict:
    """O que saiu do armazém num intervalo de dias de Lisboa, `ate` incluído.

    Mesmo filtro dos outros relatórios, incluindo o `anulado: {"$ne": True}` —
    e pela mesma razão: o campo é AUSENTE em toda a gente, e um
    `{"anulado": False}` exigia-o presente e devolvia o relatório vazio. Uma
    fatura anulada no Vendus não gastou granola nenhuma.
    """
    try:
        janela = janela_de_datas(_data(de), _data(ate))
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))

    db = obter_db()
    filtro = {
        "emitido_em": {"$gte": janela.inicio.isoformat(), "$lt": janela.fim.isoformat()},
        "anulado": {"$ne": True},
    }
    if loja_id:
        filtro["loja_id"] = loja_id
    documentos = await (
        db[COLECOES["documentos"]]
        .find(filtro, {"_id": 0, "venda_id": 1, "origem": 1, "loja_id": 1, "tipo": 1})
        .to_list(_TECTO_DOCUMENTOS)
    )

    ids = [d["venda_id"] for d in documentos if d.get("venda_id")]
    vendas = {}
    if ids:
        vendas = {
            v["id"]: v for v in await (
                db[COLECOES["vendas"]]
                .find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "linhas": 1})
                .to_list(len(ids))
            )
        }

    agregado = agregar_consumo(documentos, vendas)
    agregado.update({
        "de": de, "ate": ate,
        "truncado": len(documentos) >= _TECTO_DOCUMENTOS,
    })
    return agregado
