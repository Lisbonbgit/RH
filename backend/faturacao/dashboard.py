"""Dashboard do módulo Faturação — o primeiro ecrã que o dono vê quando abre o
módulo.

Decisão do dono (2026-08-14): este ecrã lê as NOSSAS vendas (fat_documentos),
nunca o Vendus. Enquanto o POS próprio (Plano 2) não vendeu nada, a colecção
esteve vazia, os cartões a zero e `ha_vendas` a False; a partir da primeira
fatura o dashboard acende sozinho — não há aqui nenhuma chave de API, nenhum
pedido de rede, nada que dependa de um serviço de terceiros.

Acender sozinho, porém, depende de uma coisa que não se vê daqui: os NOMES
dos campos de valor que `fiscal.py::_gravar_documento` grava. Foi
precisamente aí que este ecrã esteve partido — somava dois campos que
ninguém escrevia e mostrava 0,00 € de toda a receita, todos os dias, sem um
único erro. Ver `_campo_valor` e `_valor_documento`.

O defeito do Vendus que este ecrã corrige (ver periodos.py para o porquê): ele
comparava períodos desiguais (13 dias de agosto contra julho inteiro). Aqui a
comparação é sempre com o período equivalente, e cada cartão diz por escrito
o que foi comparado com o quê (campo `comparacao`).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends

from .auth import gestor_atual
from .db import COLECOES, obter_db
from .relatorios import agregar, eventos_dos_documentos, tamanhos_por_produto
from .periodos import (
    LISBON_TZ,
    Janela,
    descreve_comparacao,
    hora_de_corte,
    janela_ano,
    janela_anterior_equivalente,
    janela_hoje,
    janela_mes,
    janela_ontem_inteiro,
    variacao,
)

router = APIRouter()

DIAS_SERIE_DIARIA = 30
MESES_SERIE_MENSAL = 6

# Tecto defensivo do to_list — não é um limite de negócio, é só para nunca
# ficar bloqueado a carregar um cursor infinito.
LIMITE_DOCUMENTOS = 100_000
LIMITE_LOJAS = 500


# --- lógica pura (sem I/O) — o essencial é testável sem Mongo --------------

def _campo_valor(com_iva: bool) -> str:
    """com_iva troca de CAMPO — nunca faz contas com uma taxa assumida. Mesma
    regra de ouro de precos.py: sem o campo certo, não se inventa nada.

    Estes dois nomes são o CONTRATO com quem grava os documentos
    (`fiscal.py::_gravar_documento`, alimentado por `vendus/emissao.py` a
    partir de `amount_gross`/`amount_net`). Durante um tempo este ecrã leu
    dois campos que ninguém escrevia — ver `_valor_documento`."""
    return "total_bruto" if com_iva else "total_liquido"


# O campo a ler quando o do contrato não está no documento — e SÓ para o
# bruto. `total` é rigorosamente o mesmo número que `total_bruto`: os dois
# saem do `amount_gross` do Vendus (`vendus/emissao.py`), um com o nome
# antigo e outro com o do contrato. Ler o antigo não é inventar nada, é
# reconhecer o mesmo valor com outro nome.
#
# O líquido NÃO tem alternativa nenhuma, de propósito: nenhum campo antigo o
# contém, e derivá-lo do bruto obrigava a assumir uma taxa de IVA — as lojas
# vendem a 13 % (comida) e a 23 % (refrigerantes), muitas vezes na mesma
# venda. Um documento sem `total_liquido` conta 0 do lado "sem IVA", que é
# uma falta visível, em vez de um número inventado que ninguém consegue
# contestar. É a mesma regra de `vendus/emissao.py::_valor_monetario`.
_CAMPO_ALTERNATIVO = {"total_bruto": "total"}


def _parse_utc(valor) -> Optional[datetime]:
    """Interpreta um `emitido_em` (ISO, UTC) guardado como string. Devolve
    None se estiver ausente ou for ilegível — um documento assim não conta
    para janela nenhuma, em vez de rebentar o dashboard inteiro."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _valor_documento(doc: Dict, campo: str) -> float:
    """Uma nota de crédito (NC) conta com sinal negativo; um documento
    anulado não conta nada. O abs() só se aplica à NC — defende contra uma NC
    que já viesse guardada negativa (sem duplicar o sinal); um FS não é
    tocado, para não mascarar silenciosamente um valor errado na origem.

    **O defeito que o `_CAMPO_ALTERNATIVO` fecha.** Este ecrã somava
    `total_bruto`/`total_liquido`, mas o único escritor de `fat_documentos`
    em todo o backend gravava só `total` — nenhum dos dois campos do
    contrato existia em documento nenhum. `float(None or 0)` dá 0.0 sem
    levantar nada: o dono via HOJE 0,00 €, MÊS 0,00 €, ANO 0,00 €, todos os
    dias, com as faturas reais a entrarem na AT ao lado. Medido no caminho
    feliz: um açaí de 8,99 € em dinheiro, FS real emitida, Z com
    `vendas_dinheiro=8,99` — e o dashboard a 0,00 €.

    O contrato passou a ser cumprido na origem (`fiscal.py::
    _gravar_documento` grava agora os dois), mas a alternativa fica: os
    documentos gravados ANTES disso continuam em `fat_documentos` para
    sempre, e um ecrã que mostrasse a receita a começar do zero no dia do
    deploy seria o mesmo defeito com outra data. `is None`, e não `or`: um
    documento com `total_bruto: 0.0` (uma fatura de 0 €) é um valor
    legítimo e não pode cair para o campo alternativo."""
    if doc.get("anulado"):
        return 0.0
    bruto = doc.get(campo)
    if bruto is None:
        bruto = doc.get(_CAMPO_ALTERNATIVO.get(campo))
    valor = float(bruto or 0)
    if doc.get("tipo") == "NC":
        return -abs(valor)
    return valor


def documentos_no_periodo(documentos: List[Dict], janela: Janela,
                          loja_id: Optional[str] = None) -> List[Dict]:
    """Os documentos que caem dentro da janela — o CRIVO, uma vez só.

    Está separado da soma porque os cartões de artigos («Mais Vendidos»,
    «Mais Rentáveis») precisam dos MESMOS documentos que o cartão «Hoje»
    soma, mas para lhes ir buscar as linhas em vez do total. Escrito duas
    vezes, bastava um `<=` virar `<` num dos lados para o painel mostrar um
    total de dinheiro e um top de artigos de dois conjuntos diferentes de
    faturas — e nenhum dos dois números parecer errado.

    Um documento anulado fica de fora aqui (`_valor_documento` já lhe dava
    zero, portanto as somas não mudam): é o que impede que os artigos de uma
    fatura anulada contem para o top.
    """
    dentro = []
    for doc in documentos:
        if loja_id is not None and doc.get("loja_id") != loja_id:
            continue
        if doc.get("anulado"):
            continue
        dt = _parse_utc(doc.get("emitido_em"))
        if dt is None or not (janela.inicio <= dt < janela.fim):
            continue
        dentro.append(doc)
    return dentro


def _soma_periodo(documentos: List[Dict], campo: str, janela: Janela, loja_id: Optional[str] = None) -> float:
    return sum(_valor_documento(doc, campo)
               for doc in documentos_no_periodo(documentos, janela, loja_id))


def _arredonda_opcional(valor: Optional[float]) -> Optional[float]:
    return None if valor is None else round(valor, 2)


def _janela_de_mes(ano: int, mes: int, agora: datetime) -> Janela:
    """Janela [dia 1 às 00:00 Lisboa, dia 1 do mês seguinte) — excepto para o
    mês corrente (ou um mês no futuro, defensivamente), em que o fim fica em
    "agora": nunca se conta um dia que ainda não aconteceu."""
    inicio = datetime(ano, mes, 1, tzinfo=LISBON_TZ).astimezone(timezone.utc)
    if mes == 12:
        proximo_mes = datetime(ano + 1, 1, 1, tzinfo=LISBON_TZ)
    else:
        proximo_mes = datetime(ano, mes + 1, 1, tzinfo=LISBON_TZ)
    fim = proximo_mes.astimezone(timezone.utc)
    agora_utc = agora.astimezone(timezone.utc)
    if agora_utc < fim:
        fim = agora_utc
    return Janela(inicio, fim)


def _serie_diaria(documentos: List[Dict], campo: str, agora: datetime, dias: int,
                   loja_id: Optional[str] = None) -> List[Dict]:
    hoje_lisboa = agora.astimezone(LISBON_TZ).date()
    serie = []
    for offset in range(dias - 1, -1, -1):
        dia = hoje_lisboa - timedelta(days=offset)
        # Meio-dia em Lisboa reaproveita janela_hoje sem repetir a conversão
        # de fuso aqui — janela_hoje só olha para a DATA do instante recebido.
        janela = janela_hoje(datetime(dia.year, dia.month, dia.day, 12, tzinfo=LISBON_TZ))
        serie.append({
            "data": dia.isoformat(),
            "valor": round(_soma_periodo(documentos, campo, janela, loja_id), 2),
        })
    return serie


def _serie_mensal(documentos: List[Dict], campo: str, agora: datetime, meses: int,
                   loja_id: Optional[str] = None) -> List[Dict]:
    agora_lisboa = agora.astimezone(LISBON_TZ)
    serie = []
    for offset in range(meses - 1, -1, -1):
        ano, mes = agora_lisboa.year, agora_lisboa.month - offset
        while mes < 1:
            mes += 12
            ano -= 1
        janela = _janela_de_mes(ano, mes, agora)
        serie.append({
            "mes": "%04d-%02d" % (ano, mes),
            "valor": round(_soma_periodo(documentos, campo, janela, loja_id), 2),
        })
    return serie


def _cartao(documentos: List[Dict], campo: str, janela_actual: Janela, janela_ant: Janela,
            loja_id: Optional[str] = None) -> Dict:
    """`loja_id` opcional: quando vem preenchido, o cartão isola-se a essa
    loja (mesmo filtro que `_soma_periodo` já aplica) — sem loja_id, mantém-
    -se o comportamento de sempre (o total de todas as lojas). É esta função,
    e só esta, que sabe calcular "valor, valor_comparado, variação,
    descrição" — reutilizá-la para cada loja evita ter uma segunda cópia da
    lógica de comparação (a mesma que corrigiu os defeitos do Vendus em
    periodos.py) só porque agora também serve por loja."""
    valor_actual = _soma_periodo(documentos, campo, janela_actual, loja_id)
    valor_anterior = _soma_periodo(documentos, campo, janela_ant, loja_id)
    return {
        "valor": round(valor_actual, 2),
        "valor_comparado": round(valor_anterior, 2),
        "variacao": _arredonda_opcional(variacao(valor_actual, valor_anterior)),
        "comparacao": descreve_comparacao(janela_actual, janela_ant),
    }


# Quantas linhas cabem em cada cartão de artigos. Cinco é o que o cartão do
# ecrã mostra — devolver mais era mandar pela rede o que ninguém vê.
TOP_ARTIGOS = 5


def topos_de_artigos(eventos: List[Dict], com_iva: bool = True,
                     documentos_por_repartir: int = 0) -> Dict:
    """Os dois cartões de artigos: o que mais saiu e o que mais deu.

    `eventos` são as faturas do dia já repartidas por artigo
    (`relatorios.eventos_dos_documentos`). **A soma é a do motor dos
    Relatórios** (`relatorios.agregar`, dimensão "produto") e não uma conta
    nova: é o que faz o top do painel e o relatório de Produtos, no mesmo dia,
    darem exactamente os mesmos números.

    **Vendidos ordena-se por QUANTIDADE, rentáveis por RESULTADO.** São duas
    perguntas diferentes — «o que é que sai mais da loja?» e «o que é que dá
    mais dinheiro ao fim do dia?» — e um cartão ordenado por euros ao lado de
    outro ordenado por euros seria a mesma lista duas vezes.

    **O resultado é sempre sem IVA**, mesmo com `com_iva=True`. O IVA não é
    dinheiro do negócio: é dinheiro do Estado a passar pela caixa, e uma
    margem calculada por cima dele diria que cada açaí dá mais 23% do que dá.
    O `com_iva` só decide o que se escreve na coluna de vendas, que é a mesma
    escolha que os cartões do topo já fazem.

    **Um artigo sem preço de custo não entra com margem zero — não entra de
    todo**, e conta-se em `artigos_sem_custo`. Zero ali fazia o açaí parecer
    lucro inteiro, que é a mentira mais cara que este painel podia contar (a
    regra de ouro está escrita no cabeçalho de `relatorios.py`). É esse número
    que o ecrã usa para dizer o que falta em vez de ficar mudo.
    """
    # `agregar` recusa uma dimensão desconhecida, mas não uma lista vazia:
    # sem eventos devolve zero linhas, que é exactamente o que se quer.
    linhas = agregar(eventos, "produto")["linhas"] if eventos else []
    por_tamanho = tamanhos_por_produto(eventos)

    vendidos = sorted(
        (l for l in linhas if (l["quantidade"] or 0) > 0),
        # Desempate pelo dinheiro e depois pelo nome: sem ele, dois artigos com
        # a mesma quantidade trocavam de lugar a cada recarga do ecrã.
        key=lambda l: (-(l["quantidade"] or 0), -l["bruto"], l["rotulo"] or ""),
    )
    rentaveis = sorted(
        # **O MESMO crivo do cartão irmão** (`quantidade > 0`), e não só o
        # "tem custo". Sem ele, um artigo vendido e depois devolvido no mesmo
        # dia entrava aqui com 0,00 € de margem — ruído puro —, e um artigo
        # devolvido a mais do que se vendeu entrava com margem NEGATIVA, num
        # cartão que se chama «Mais Rentáveis».
        #
        # Não se filtra por `resultado > 0`, que era o passo seguinte e mais
        # tentador: um artigo que se vendeu MESMO abaixo do custo tem de
        # continuar a aparecer, no fundo da lista. Esconder o «vendo a perder»
        # é a única coisa que este cartão não pode fazer.
        (l for l in linhas
         if l["resultado"] is not None and (l["quantidade"] or 0) > 0),
        key=lambda l: (-l["resultado"], l["rotulo"] or ""),
    )

    return {
        "mais_vendidos": [{
            "produto_id": l["chave"],
            "nome": l["rotulo"],
            "quantidade": l["quantidade"],
            "valor": l["bruto"] if com_iva else l["liquido"],
            "tamanhos": por_tamanho.get(l["chave"]) or [],
        } for l in vendidos[:TOP_ARTIGOS]],
        "mais_rentaveis": [{
            "produto_id": l["chave"],
            "nome": l["rotulo"],
            "resultado": l["resultado"],
            "vendas": l["liquido"],
            "margem_pct": (
                round(l["resultado"] * 100.0 / l["liquido"], 1)
                if l["liquido"] > 0 else None
            ),
        } for l in rentaveis[:TOP_ARTIGOS]],
        # **Contam-se os artigos VENDIDOS no período, não o catálogo inteiro.**
        # É esta a frase que responde à pergunta que o cartão vazio levanta
        # («porque é que não mostra nada?»): dos que se venderam hoje, tantos
        # não têm preço de custo. Contar os 33 do catálogo dava um número
        # maior e menos verdadeiro — os artigos que ninguém vendeu hoje não
        # eram o que faltava a ESTE cartão.
        "artigos_sem_custo": sum(1 for l in linhas if l["custo_incompleto"]),
        "artigos_vendidos": len(linhas),
        # Faturas de hoje que não se deixaram repartir por artigo (ver o
        # travão em `relatorios.eventos_dos_documentos`). Quase sempre zero.
        # Vai para o ecrã porque o dinheiro delas ESTÁ no cartão «Hoje» e não
        # está aqui: sem esta linha, os dois números discordavam sem nada a
        # explicar — e é a terceira vez neste painel que dois números certos
        # lado a lado, sem legenda, dão uma leitura falsa.
        "documentos_por_repartir": documentos_por_repartir,
    }


def calcula_dashboard(documentos: List[Dict], lojas: List[Dict], agora: datetime,
                       com_iva: bool = True,
                       eventos_de_hoje: Optional[List[Dict]] = None,
                       documentos_por_repartir: int = 0) -> Dict:
    """Constrói toda a resposta do dashboard a partir de dados já em memória —
    puro no sentido em que não toca em Mongo nem na rede; só o endpoint (mais
    abaixo) é que vai buscar `documentos`/`lojas` à base de dados."""
    campo = _campo_valor(com_iva)

    j_hoje = janela_hoje(agora)
    # **"Ontem" é o dia anterior INTEIRO** — e isto foi uma inversão
    # consciente, pedida pelo dono depois de ver o custo escrito.
    #
    # Até aqui parava à mesma hora do relógio a que "hoje" ia
    # (`janela_ontem_equivalente`), para a percentagem não mostrar uma queda
    # enorme todas as manhãs — comparar cinco horas com vinte e quatro. Esse
    # raciocínio continua a valer e a queda matinal voltou com esta mudança.
    #
    # O que o desmontou foi o caso real: o Oeiras facturou 45,90 € às 19:09, o
    # dono abriu o painel às 17:25 do dia seguinte e leu «Ontem: 0,00 €». A
    # conta estava certa e a leitura era falsa — e a pergunta que ele faz a
    # este ecrã é «quanto é que a loja fez ONTEM?», que tem uma só resposta
    # certa: o dia inteiro. «à medida que vai sendo facturado vai mudando a
    # percentagem. como é no vendus.»
    #
    # A percentagem passa a subir ao longo do dia até fechar a diferença. É o
    # que o painel do Vendus lhe mostra há anos e é como ele o lê.
    #
    # O MÊS e o ANO continuam a comparar-se de forma equivalente
    # (`janela_anterior_equivalente`, mais abaixo): ninguém se queixou deles, e
    # um mês a meio contra um mês inteiro é a mesma injustiça multiplicada por
    # trinta. Se um dia isso também mudar, muda-se aqui e ali com a mesma
    # conversa — não em silêncio.
    j_hoje_anterior = janela_ontem_inteiro(agora)

    # janela_anterior_equivalente devolve os DOIS lados (actual, anterior):
    # o anterior termina sempre à mesma hora do relógio que o actual (C2), e
    # se o mês/ano anterior for mais curto, o actual também é encurtado
    # (I1) — daí reatribuir j_mes/j_ano aqui, em vez de só ler ".anterior".
    j_mes_bruto = janela_mes(agora)
    j_mes, j_mes_anterior = janela_anterior_equivalente(j_mes_bruto.inicio, j_mes_bruto.fim, "mes")

    j_ano_bruto = janela_ano(agora)
    j_ano, j_ano_anterior = janela_anterior_equivalente(j_ano_bruto.inicio, j_ano_bruto.fim, "ano")

    cartoes = {
        "hoje": _cartao(documentos, campo, j_hoje, j_hoje_anterior),
        "mensal": _cartao(documentos, campo, j_mes, j_mes_anterior),
        "anual": _cartao(documentos, campo, j_ano, j_ano_anterior),
    }

    por_loja = []
    for loja in sorted(lojas, key=lambda l: l.get("nome") or ""):
        loja_id = loja.get("id")
        # Mesma lógica dos cartões do total (_cartao), com loja_id — nunca
        # uma segunda conta à parte. As janelas (j_hoje/j_hoje_anterior,
        # j_mes/j_mes_anterior) são também as mesmas calculadas acima para o
        # total: uma loja não pode comparar-se com um período diferente do
        # que o cartão do total usa.
        cartao_hoje_loja = _cartao(documentos, campo, j_hoje, j_hoje_anterior, loja_id)
        cartao_mensal_loja = _cartao(documentos, campo, j_mes, j_mes_anterior, loja_id)
        por_loja.append({
            "loja_id": loja_id,
            "nome": loja.get("nome"),
            "hoje": cartao_hoje_loja["valor"],
            "hoje_anterior": cartao_hoje_loja["valor_comparado"],
            "variacao_hoje": cartao_hoje_loja["variacao"],
            "mensal": cartao_mensal_loja["valor"],
            "mensal_anterior": cartao_mensal_loja["valor_comparado"],
            "variacao_mensal": cartao_mensal_loja["variacao"],
            "serie_diaria": _serie_diaria(documentos, campo, agora, DIAS_SERIE_DIARIA, loja_id),
            "serie_mensal": _serie_mensal(documentos, campo, agora, MESES_SERIE_MENSAL, loja_id),
        })

    # NOTA: `ha_vendas` não faz parte desta resposta (I3) — é o endpoint que
    # a acrescenta, com uma pergunta directa à base de dados (`_existe_venda`).
    # `documentos` aqui está limitado à janela que os cartões/gráficos
    # precisam (desde o início do ano anterior, ver o endpoint) — deduzir
    # "alguma vez existiu uma venda?" a partir dessa janela dava um "não"
    # errado sempre que o negócio tivesse vendas mais antigas do que ela.
    # **A hora a que a comparação foi cortada**, para o ecrã a poder escrever.
    #
    # O «Ontem» dos cartões não é ontem inteiro: é ontem desde a meia-noite até
    # à mesma hora do relógio a que hoje ainda vai
    # (`janela_ontem_equivalente`), e é assim de propósito — comparar cinco
    # horas de hoje com vinte e quatro de ontem mostrava uma queda enorme todas
    # as manhãs.
    #
    # O dono apanhou o preço disso: o Oeiras abriu a caixa às 19:09, ele viu o
    # painel às 17:25, e a linha dizia «Ontem: 0,00 €» — que se lê como «ontem
    # a loja não fez nada», quando ontem a loja fez 45,90 €. A conta estava
    # certa; a etiqueta é que mentia.
    #
    # A frase inteira (`comparacao`) já vai nos cartões do topo. Nas linhas por
    # loja não cabe — mas a HORA cabe, e é ela que transforma «Anterior» em
    # «Anterior até às 17:25».
    #
    # Sai do MÊS e não do dia: desde que «ontem» passou a ser o dia inteiro, o
    # cartão «Hoje» não tem corte nenhum a assinalar — mas o mensal continua a
    # comparar-se de forma equivalente (um mês a meio contra o mesmo pedaço do
    # mês anterior), e é lá que a etiqueta sem hora enganaria agora.
    #
    # `None` quando não há corte (o mês fechado, os dois lados à meia-noite):
    # aí escrever uma hora era ruído.
    corte = hora_de_corte(j_mes, j_mes_anterior)

    return {
        "cartoes": cartoes,
        "hora_de_corte": "%02d:%02d" % (corte.hour, corte.minute) if corte else None,
        "serie_diaria": _serie_diaria(documentos, campo, agora, DIAS_SERIE_DIARIA),
        "ultimos_6_meses": _serie_mensal(documentos, campo, agora, MESES_SERIE_MENSAL),
        "por_loja": por_loja,
        # Os dois cartões de artigos, do DIA de hoje (a mesma janela do cartão
        # «Hoje», pelo mesmo crivo — ver `documentos_no_periodo`).
        #
        # `eventos_de_hoje` vem de fora porque ir buscar as linhas de cada
        # venda é I/O, e esta função é pura de propósito. Sem eles — que é o
        # caso de qualquer teste que só passe documentos — os cartões ficam
        # vazios, e o ecrã diz que ainda não há artigos: nunca se inventa um
        # top a partir do total do documento, que é a única coisa que
        # `fat_documentos` sabe sozinho.
        **topos_de_artigos(eventos_de_hoje or [], com_iva, documentos_por_repartir),
    }


# --- endpoint ----------------------------------------------------------------

async def _existe_venda(db) -> bool:
    """Pergunta DIRECTAMENTE à base de dados se alguma vez existiu um
    documento de venda não anulado (I3) — independente da janela de datas
    que a consulta principal usa (essa está limitada ao ano anterior para
    trás, só para alimentar os cartões/gráficos). Um negócio pode ter
    vendido antes dessa janela; a faixa "ainda não há vendas" não pode
    ignorar isso só porque a janela dos gráficos não chega lá.

    **`$ne: True` e não `False`, e isto é uma decisão.** No Mongo, `$ne`
    casa também com o documento a que o campo FALTA — e é isso que se quer:
    o POS nunca grava `anulado` (`fiscal.py::_gravar_documento`), e uma
    fatura sem esse campo é uma venda como todas as outras. Trocar por
    `{"anulado": False}` exigia o campo presente e respondia "ainda não há
    vendas" a um dia inteiro de faturas reais.

    Esta pergunta e os valores dos cartões têm de CONCORDAR: enquanto o
    valor vinha a 0,00 € (ver `_valor_documento`), o ecrã afirmava que havia
    vendas — pela pergunta certa — e mostrava zero em tudo, que é a pior das
    combinações: parece que o negócio não vendeu nada, e nem sequer há a
    faixa a explicar porquê. Corrigido o valor, os dois voltam a dizer a
    mesma coisa, e é isso que o teste de ponta a ponta prende."""
    doc = await db[COLECOES["documentos"]].find_one({"anulado": {"$ne": True}}, {"_id": 1})
    return doc is not None


@router.get("/dashboard")
async def obter_dashboard(com_iva: bool = True, _: dict = Depends(gestor_atual)) -> Dict:
    db = obter_db()
    agora = datetime.now(timezone.utc)

    # A maior janela que o dashboard usa não é o ano corrente — é o cartão
    # Anual, que compara com o ANO ANTERIOR equivalente (janela_anterior_
    # equivalente começa sempre a 1 de Janeiro do ano passado). Ir buscar só
    # desde o início do ano corrente deixava o ano anterior inteiro de fora,
    # sem erro nem aviso: o cartão Anual ficava sempre "Sem período anterior
    # comparável" e as séries ficavam a zero perto do início do ano. Compa-
    # ração por string funciona porque emitido_em é sempre ISO em UTC (mesmo
    # padrão do server.py: LISBON_TZ, day_start_utc = ...isoformat(), filtro
    # por $gte sobre a string).
    j_ano = janela_ano(agora)
    _, j_ano_anterior = janela_anterior_equivalente(j_ano.inicio, j_ano.fim, "ano")
    inicio_consulta = j_ano_anterior.inicio.isoformat()
    documentos = await db[COLECOES["documentos"]].find(
        {"emitido_em": {"$gte": inicio_consulta}}, {"_id": 0}
    ).to_list(LIMITE_DOCUMENTOS)

    lojas = await db[COLECOES["lojas"]].find(
        {}, {"_id": 0, "id": 1, "nome": 1}
    ).to_list(LIMITE_LOJAS)

    # Os artigos vendidos HOJE, para os dois cartões do topo de artigos.
    #
    # Sai dos documentos JÁ LIDOS acima — não é uma segunda ida à colecção de
    # documentos. O que custa I/O aqui são as vendas e os produtos desses
    # documentos, e só os de hoje: enriquecer o ano inteiro para desenhar
    # cinco linhas era pagar mil vezes o preço do que se mostra.
    docs_de_hoje = documentos_no_periodo(documentos, janela_hoje(agora))
    eventos_de_hoje = await eventos_dos_documentos(db, docs_de_hoje)

    resultado = calcula_dashboard(
        documentos, lojas, agora, com_iva, eventos_de_hoje,
        # Sem filtros de categoria nem de utilizador, o único motivo para um
        # documento não sair de lá é não se deixar repartir por artigos.
        documentos_por_repartir=len(docs_de_hoje) - len(eventos_de_hoje))
    # I3: pergunta à parte, nunca deduzida de `documentos` (essa janela é
    # limitada, ver acima — não serve para responder "alguma vez vendeu?").
    resultado["ha_vendas"] = await _existe_venda(db)
    return resultado
