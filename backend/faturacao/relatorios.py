"""**Os relatórios** — as nove vistas da mesma tabela.

O dono mandou os prints dos relatórios do Vendus, que é a subscrição que este
módulo existe para largar, e o que eles mostram é sempre A MESMA TABELA: muda a
primeira coluna e mudam os filtros. Produtos, Clientes, Categoria, Loja,
Utilizador, Diário, Por Hora, Dias da Semana e Mensal — nove vistas, um motor.

Nove somas escritas em nove sítios acabam a discordar entre si, e a primeira
vez que isso acontece é o dono a perguntar qual delas está certa. Por isso a
agregação é uma só, parametrizada pela DIMENSÃO, e o núcleo dela é puro: não
sabe o que é Mongo nem HTTP, recebe os documentos já lidos e devolve linhas.

## As colunas, e o que cada uma quer dizer

    [dimensão] · Vendas c/IVA · Vendas · Custos · Resultado · Quantidade ·
    Nº Vendas · Nº Rectificações

- **Vendas c/IVA** é o que o cliente pagou; **Vendas** é isso sem o IVA.
- **Custos** é o preço de custo dos artigos vendidos, e só existe onde ele
  estiver preenchido — ver `_custo_da_linha`.
- **Resultado** é Vendas − Custos, e por isso só existe quando o custo existe.
- **Quantidade** é a soma dos artigos, e só faz sentido nas dimensões que
  contam artigos (produto, categoria) ou onde o Vendus a mostra (cliente,
  dia). Nas outras vem a `None` e a coluna nem aparece.
- **Nº Vendas** e **Nº Rectificações** são DUAS contagens e não se somam: a
  primeira conta faturas, a segunda notas de crédito. É o rodapé dos prints,
  à letra.

## As três regras que decidem se estes números servem

1. **A nota de crédito SUBTRAI no dinheiro e conta à parte.** Somá-la como
   positiva declara o dobro do que entrou.
2. **A hora é a de Lisboa.** Um `emitido_em` em UTC agrupado em cru põe a
   venda das 00h30 no dia anterior e o pico das 17h às 16h — parte os
   relatórios Diário e Por Hora inteiros.
3. **Cêntimos inteiros do princípio ao fim.** A soma das linhas tem de bater
   com a linha TOTAL, e `round()` sobre float come cêntimos.

## O que NÃO se inventa

Um produto sem preço de custo não contribui com zero para os Custos: marca a
linha como INCOMPLETA (`custo_incompleto`) e o ecrã mostra "—". Um zero ali
fazia o Resultado parecer lucro inteiro — a mentira mais cara que um relatório
pode contar.
"""
from datetime import datetime
from typing import Dict, List, Optional

from .periodos import LISBON_TZ
from .precos import e_grupo_de_variante

# As nove vistas. A chave é o que viaja no URL.
DIMENSOES = (
    "produto", "categoria", "cliente", "loja", "utilizador",
    "dia", "hora", "dia_semana", "mes",
)

# As que contam ARTIGOS (precisam das linhas dos documentos). As outras
# respondem-se com o documento inteiro.
POR_ARTIGO = frozenset({"produto", "categoria"})

# Onde a coluna Quantidade aparece — é o que os prints do Vendus mostram:
# produto, cliente, categoria e diário têm-na; loja, utilizador, hora, dias da
# semana e mensal não (aí a linha é um agregado de documentos, não de artigos).
COM_QUANTIDADE = frozenset({"produto", "categoria", "cliente", "dia"})

_DIAS_DA_SEMANA = (
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
    "Sexta-feira", "Sábado", "Domingo",
)
_MESES = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)

_SEM_DEFINICAO = "Sem definição"


def centimos(valor) -> int:
    """Euros para cêntimos INTEIROS. A mesma conversão do resto do módulo, e
    pela mesma razão: o dinheiro compara-se e soma-se em inteiros."""
    return int(round(float(valor or 0) * 100))


def em_lisboa(iso: Optional[str]) -> Optional[datetime]:
    """O instante gravado (ISO, UTC) na hora de LISBOA.

    É aqui que se decide a que dia e a que hora uma venda pertence — e é a
    diferença entre um relatório certo e um que põe a venda das 00h30 no dia
    anterior. Um valor ilegível devolve `None` e a linha fica de fora, com a
    contagem a dizê-lo (nunca se inventa uma data para não perder a linha)."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)).astimezone(LISBON_TZ)
    except (TypeError, ValueError):
        return None


def _chave_e_rotulo(dimensao: str, evento: Dict, artigo: Optional[Dict]) -> tuple:
    """A que linha da tabela pertence este documento (ou este artigo dele)."""
    quando = evento.get("quando")
    if dimensao == "produto":
        nome = artigo.get("produto_nome") or _SEM_DEFINICAO
        # **Sem `produto_id`, a identidade do artigo é o NOME.** Os artigos das
        # faturas da app não têm produto do catálogo nenhum (vêm das linhas do
        # Vendus), e com a chave a `None` fundiam-se TODOS numa linha só, com o
        # rótulo do primeiro: uma fatura com um açaí e duas águas aparecia como
        # «Açaí Mini, 3, 9,85 €». O dinheiro total estava certo; a atribuição
        # por artigo é que mentia — que é exactamente o que esta vista existe
        # para responder.
        #
        # Só aqui: na CATEGORIA um `None` quer mesmo dizer uma coisa só («Sem
        # definição»), e separá-la por nome inventava categorias.
        return artigo.get("produto_id") or nome, nome
    if dimensao == "categoria":
        return artigo.get("categoria_id"), artigo.get("categoria_nome") or _SEM_DEFINICAO
    if dimensao == "cliente":
        nif = evento.get("cliente_nif")
        return nif, (evento.get("cliente_nome") or nif or "Consumidor Final")
    if dimensao == "loja":
        return evento.get("loja_id"), evento.get("loja_nome") or _SEM_DEFINICAO
    if dimensao == "utilizador":
        return evento.get("operador_id"), evento.get("operador_nome") or _SEM_DEFINICAO
    if quando is None:
        return None, _SEM_DEFINICAO
    if dimensao == "dia":
        return quando.strftime("%Y-%m-%d"), quando.strftime("%Y-%m-%d")
    if dimensao == "hora":
        return quando.hour, "%dh" % quando.hour
    if dimensao == "dia_semana":
        return quando.weekday(), _DIAS_DA_SEMANA[quando.weekday()]
    if dimensao == "mes":
        return quando.strftime("%Y-%m"), _MESES[quando.month - 1]
    raise ValueError("Dimensão desconhecida: %s" % dimensao)


def _linha_vazia(chave, rotulo: str) -> Dict:
    return {
        "chave": chave, "rotulo": rotulo,
        "bruto_c": 0, "liquido_c": 0, "custo_c": 0,
        "quantidade": 0.0, "faturas": 0, "rectificacoes": 0,
        "custo_incompleto": False,
        # Os documentos já contados nesta linha — é assim que "Nº Vendas" de um
        # produto conta FATURAS e não linhas: uma fatura com o mesmo artigo
        # duas vezes é uma venda, não duas (é o que os prints mostram: 967 de
        # quantidade para 774 vendas).
        "_documentos": set(),
    }


def agregar(eventos: List[Dict], dimensao: str) -> Dict:
    """As linhas da tabela e a linha TOTAL, para uma dimensão.

    `eventos` é uma lista de documentos já normalizados (ver
    `_evento_da_fatura` / `_evento_da_nota` no lado das rotas): cada um com o
    seu instante, a sua loja, o seu cliente, o seu operador, o dinheiro em
    cêntimos e — quando a dimensão os pede — os artigos.

    Pura: sem Mongo, sem HTTP, sem relógio. É o que permite prová-la com contas
    fabricadas em vez de com uma base de dados."""
    if dimensao not in DIMENSOES:
        raise ValueError("Dimensão desconhecida: %s" % dimensao)
    por_artigo = dimensao in POR_ARTIGO
    linhas: Dict = {}

    for evento in eventos:
        sinal = -1 if evento.get("tipo") == "NC" else 1
        partes = evento.get("artigos") or [] if por_artigo else [None]
        for artigo in partes:
            chave, rotulo = _chave_e_rotulo(dimensao, evento, artigo)
            linha = linhas.setdefault(chave, _linha_vazia(chave, rotulo))
            if artigo is None:
                linha["bruto_c"] += sinal * evento["bruto_c"]
                linha["liquido_c"] += sinal * evento["liquido_c"]
                linha["quantidade"] += sinal * (evento.get("quantidade") or 0.0)
                custo = evento.get("custo_c")
            else:
                linha["bruto_c"] += sinal * artigo["bruto_c"]
                linha["liquido_c"] += sinal * artigo["liquido_c"]
                linha["quantidade"] += sinal * (artigo.get("quantidade") or 0.0)
                custo = artigo.get("custo_c")
            if custo is None:
                # **Não se soma zero.** Um artigo sem custo conhecido faz a
                # linha inteira ficar sem Custos e sem Resultado — com um zero,
                # a margem aparecia inflacionada e ninguém dava por isso.
                linha["custo_incompleto"] = True
            else:
                linha["custo_c"] += sinal * custo
            if evento["id"] not in linha["_documentos"]:
                linha["_documentos"].add(evento["id"])
                if sinal < 0:
                    linha["rectificacoes"] += 1
                else:
                    linha["faturas"] += 1

    ordenadas = sorted(linhas.values(), key=_ordem_de(dimensao))
    total = _linha_vazia(None, "TOTAL")
    for linha in ordenadas:
        total["bruto_c"] += linha["bruto_c"]
        total["liquido_c"] += linha["liquido_c"]
        total["custo_c"] += linha["custo_c"]
        total["quantidade"] += linha["quantidade"]
        total["custo_incompleto"] = total["custo_incompleto"] or linha["custo_incompleto"]

    # **As contagens do TOTAL contam DOCUMENTOS DISTINTOS, não somam as
    # linhas.** Numa vista por artigo, uma fatura com três produtos aparece em
    # três linhas — somar as contagens dava "3 vendas" para uma. (O Vendus
    # resolve o mesmo problema deixando a célula vazia no total das vistas por
    # artigo; contar os documentos distintos responde à pergunta em vez de a
    # evitar.) Nas vistas de tempo ou de loja o número é o mesmo pelos dois
    # caminhos — cada documento cai numa linha só.
    for evento in eventos:
        if evento.get("tipo") == "NC":
            total["rectificacoes"] += 1
        else:
            total["faturas"] += 1

    com_quantidade = dimensao in COM_QUANTIDADE
    return {
        "linhas": [_publica(l, com_quantidade) for l in ordenadas],
        "total": _publica(total, com_quantidade),
    }


def tamanhos_por_produto(eventos: List[Dict]) -> Dict:
    """A repartição por TAMANHO de cada produto — `{produto_id: [{nome, quantidade}]}`.

    O dono, a olhar para o cartão: «no mais vendido devia ter também os
    tamanhos, pois só está Açaí». E tem razão: no nosso catálogo o açaí é UM
    produto e o tamanho é uma personalização dele, portanto o topo dizia «Açaí
    25» — que é verdade e não responde a nada. Vinte e cinco de qual?

    **Soma pela MESMA regra de `agregar`** — a nota de crédito subtrai — e é
    isso que faz estas parcelas somarem exactamente a quantidade da linha. Há
    um teste a prender essa igualdade: se um dia divergirem, o cartão mostra
    um total e umas parcelas que não batem, e nenhum dos dois parece errado.

    Os artigos SEM tamanho (uma água, um salgado) não entram: não há
    repartição nenhuma a fazer, e uma parcela «(sem tamanho)» debaixo de cada
    linha era ruído em todas as linhas menos uma.
    """
    contas: Dict = {}
    for evento in eventos:
        sinal = -1 if evento.get("tipo") == "NC" else 1
        for artigo in evento.get("artigos") or []:
            variante = artigo.get("variante")
            if not variante:
                continue
            por_produto = contas.setdefault(artigo.get("produto_id"), {})
            por_produto[variante] = por_produto.get(variante, 0.0) + sinal * float(
                artigo.get("quantidade") or 0)

    saida: Dict = {}
    for produto_id, tamanhos in contas.items():
        lista = [{"nome": nome, "quantidade": round(q, 3)}
                 for nome, q in tamanhos.items() if q > 0]
        lista.sort(key=lambda t: (-t["quantidade"], t["nome"]))
        if lista:
            saida[produto_id] = lista
    return saida


def _ordem_de(dimensao: str):
    """Como se ordena cada vista.

    As dimensões de TEMPO ordenam-se pelo tempo (um Diário por valor era
    ilegível); as outras pelo dinheiro, do maior para o menor, que é o que os
    prints mostram e a pergunta que se faz a elas («o que vende mais?»)."""
    if dimensao in {"dia", "hora", "dia_semana", "mes"}:
        return lambda l: (l["chave"] is None, l["chave"])
    return lambda l: (-l["bruto_c"], l["rotulo"] or "")


def _publica(linha: Dict, com_quantidade: bool) -> Dict:
    custo_conhecido = not linha["custo_incompleto"]
    return {
        "chave": linha["chave"],
        "rotulo": linha["rotulo"],
        "bruto": linha["bruto_c"] / 100.0,
        "liquido": linha["liquido_c"] / 100.0,
        # `None` e não zero: é o ecrã que escreve "—". Ver o cabeçalho.
        "custo": (linha["custo_c"] / 100.0) if custo_conhecido else None,
        "resultado": (
            (linha["liquido_c"] - linha["custo_c"]) / 100.0 if custo_conhecido else None
        ),
        "custo_incompleto": linha["custo_incompleto"],
        "quantidade": round(linha["quantidade"], 3) if com_quantidade else None,
        "faturas": linha["faturas"],
        "rectificacoes": linha["rectificacoes"],
    }


def serie_diaria(eventos: List[Dict]) -> List[Dict]:
    """A evolução dia a dia do período — o gráfico que TODOS os relatórios do
    Vendus mostram por cima da tabela, seja qual for a dimensão.

    Em dias de LISBOA, com as notas de crédito a subtrair, como o resto."""
    por_dia: Dict[str, int] = {}
    for evento in eventos:
        quando = evento.get("quando")
        if quando is None:
            continue
        sinal = -1 if evento.get("tipo") == "NC" else 1
        dia = quando.strftime("%Y-%m-%d")
        por_dia[dia] = por_dia.get(dia, 0) + sinal * evento["bruto_c"]
    return [
        {"rotulo": dia, "valor": valor / 100.0}
        for dia, valor in sorted(por_dia.items())
    ]


# --- A leitura: dos documentos para os eventos --------------------------------
#
# A partir daqui há Mongo. O que se lê é o mínimo para responder às nove vistas,
# e o que se constrói é a lista de EVENTOS que o núcleo puro lá em cima
# consome — um por documento, com os artigos dentro.

import logging  # noqa: E402

from fastapi import APIRouter, Depends, HTTPException  # noqa: E402

from .auth import gestor_atual  # noqa: E402
from .db import COLECOES, obter_db  # noqa: E402
from .fiscal import _itens_vendus  # noqa: E402
from .mapa_imposto import _TAXA_DO_CODIGO, _liquido_da_linha  # noqa: E402
from .periodos import janela_de_datas  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter()

# Tecto de documentos por leitura. Uma loja faz ~200 por dia; cinco lojas num
# mês são ~30 mil. Acima disto a resposta diz que está truncada em vez de
# apresentar um pedaço como se fosse o período todo.
_TECTO_DOCUMENTOS = 40000


def _base_sem_iva(liquido_c: int, taxa: Optional[float]) -> int:
    """O valor da linha SEM IVA, em cêntimos.

    O `liquido` de uma linha é o que o cliente pagou — já com IVA dentro. A
    base tira-o pela mesma aritmética do mapa de imposto: `total / (1 + taxa)`.
    Sem taxa conhecida devolve o próprio valor: inventar uma taxa era inventar
    imposto."""
    if not taxa:
        return liquido_c
    return int(round(liquido_c * 100 / (100 + float(taxa))))


def _variante_da_linha(linha: Optional[Dict]) -> Optional[str]:
    """O TAMANHO escolhido nesta linha — «Mini», «Supreme» — ou `None`.

    Vem das opções carimbadas na linha (`venda._carimbar_sai_na_fatura` grava
    o `nome_grupo` em cada uma), e é a MESMA pergunta que decide o artigo do
    Vendus (`precos.e_grupo_de_variante`): um tamanho é outro artigo, um
    topping não é.

    Uma linha gravada antes de o `nome_grupo` existir não tem grupo nenhum e
    devolve `None` — sem tamanho, e não com um tamanho adivinhado pelo nome
    da opção."""
    for opcao in (linha or {}).get("opcoes") or []:
        if e_grupo_de_variante(opcao.get("nome_grupo")):
            return opcao.get("nome")
    return None


def _artigo(produto: Optional[Dict], categorias: Dict[str, str],
            produto_id: Optional[str], nome: str, quantidade: float,
            liquido_c: int, taxa: Optional[float],
            variante: Optional[str] = None) -> Dict:
    custo_unitario = (produto or {}).get("preco_custo")
    return {
        "produto_id": produto_id,
        # O tamanho, para quem quiser repartir o artigo por ele. Nenhuma das
        # nove vistas dos Relatórios o usa — quem o usa é o cartão «Mais
        # Vendidos» do painel, onde 25 açaís sem tamanho não dizem nada.
        "variante": variante,
        "produto_nome": (produto or {}).get("nome") or nome,
        "categoria_id": (produto or {}).get("categoria_id"),
        "categoria_nome": categorias.get((produto or {}).get("categoria_id")),
        "quantidade": quantidade,
        "bruto_c": liquido_c,
        "liquido_c": _base_sem_iva(liquido_c, taxa),
        # `None` — e não zero — quando o artigo não tem custo. Ver o cabeçalho.
        "custo_c": (
            None if custo_unitario is None
            else int(round(float(custo_unitario) * 100 * float(quantidade or 0)))
        ),
    }


def _artigos_da_fatura(venda: Optional[Dict], produtos: Dict, categorias: Dict) -> List[Dict]:
    """Os artigos de uma Fatura Simplificada.

    O valor de cada linha é o MESMO que a fatura mostra
    (`mapa_imposto._liquido_da_linha` sobre os itens que foram enviados ao
    Vendus) — nunca `qtd × preço`, que numa conta com desconto é outro número.

    O `zip` com `venda["linhas"]` é seguro e não é sorte: `fiscal._itens_vendus`
    percorre as linhas da venda por ordem e devolve um item por linha. É de lá
    que vem o `produto_id`, que o item do Vendus não tem."""
    if not venda:
        return []
    artigos = []
    for linha, item in zip(venda.get("linhas") or [], _itens_vendus(venda)):
        produto_id = linha.get("produto_id")
        artigos.append(_artigo(
            produtos.get(produto_id), categorias, produto_id,
            linha.get("produto_nome") or item.get("title") or _SEM_DEFINICAO,
            float(linha.get("quantidade") or 0),
            centimos(_liquido_da_linha(item)),
            _TAXA_DO_CODIGO.get(item.get("tax_id")),
            _variante_da_linha(linha),
        ))
    return artigos


def _artigos_das_linhas_vendus(documento: Dict, categorias: Dict) -> List[Dict]:
    """Os artigos de um documento que não tem conta de balcão nenhuma.

    **Porque é que isto existe.** `_artigos_da_fatura` começa com
    `if not venda: return []`. Um `[]` não levanta excepção, portanto o
    documento não é descartado pelo `except` de quem chama: vira um evento com
    a soma de uma lista vazia, ou seja **zero**. Media-se assim — a fatura da
    app valia 6,85 € no cartão do Dashboard (que lê `total_bruto` do próprio
    documento) e 0,00 € nas nove vistas dos Relatórios, sem nenhum dos dois
    números parecer errado. E o aviso que existe para isto — «N faturas não se
    deixaram repartir» — conta documentos menos eventos, e o evento existia.

    As linhas vêm como o Vendus as mandou (`items` do `GET documents/{id}/`).
    Reaproveita-se `_artigo`, que é onde as regras do dinheiro já vivem: com
    `produto=None` o `custo_c` sai `None` sozinho — e tem mesmo de ser `None`,
    porque um custo de 0 € contra 6,85 € de venda dá 100% de margem no
    relatório de rentabilidade.
    """
    # **Numa nota de crédito, o valor entra POSITIVO.** Quem soma é `agregar`,
    # que aplica o sinal pelo `tipo` do documento — e um `-1 ×` sobre um valor
    # que a API já devolveu negativo é uma dupla negação: a nota passava a
    # SOMAR receita em vez de a subtrair. Medido: uma FS de 6,85 € da app e a
    # NC que a anula davam +13,70 € e quantidade 2, em vez de zero.
    #
    # Não é hipótese: o Financeiro lê a MESMA API das MESMAS lojas e faz o
    # mesmo há meses (`server.py::_fin_signed_amount`, «a API pode devolver o
    # valor já negativo»; e ao nível do item, «a devolução reverte o custo,
    # venha a quantidade positiva ou já negativa da API»).
    #
    # **Só na NC.** Numa fatura, uma linha negativa é um desconto legítimo, e
    # um `abs()` incondicional transformava-o em receita.
    eh_nc = documento.get("tipo") == "NC"
    artigos = []
    for linha in documento.get("linhas_vendus") or []:
        montantes = linha.get("amounts") or {}
        bruto_c = centimos(montantes.get("gross_total"))
        quantidade = float(linha.get("qty") or 0)
        if eh_nc:
            bruto_c, quantidade = abs(bruto_c), abs(quantidade)
        artigos.append(_artigo(
            None, categorias, None,
            linha.get("title") or _SEM_DEFINICAO,
            quantidade,
            bruto_c,
            (linha.get("tax") or {}).get("rate"),
        ))
    return artigos


def _artigos_da_nota(nota: Optional[Dict], venda: Optional[Dict],
                     produtos: Dict, categorias: Dict) -> List[Dict]:
    """Os artigos CREDITADOS por uma nota de crédito.

    Uma nota não tem venda própria (`nota_credito._gravar_documento` não grava
    `venda_id` no documento, de propósito): o que ela tem são as linhas
    creditadas, cada uma com o `indice` da linha na fatura de origem. É por esse
    índice que se chega ao `produto_id` — sem ele, uma devolução não se conseguia
    atribuir ao artigo devolvido e o relatório de Produtos ficava a dizer que se
    vendeu o que foi devolvido."""
    if not nota:
        return []
    linhas_origem = (venda or {}).get("linhas") or []
    artigos = []
    for creditada in nota.get("linhas") or []:
        # **O `indice` da nota conta a partir de UM**, não de zero: é o número
        # da linha no talão, que a operadora lê em papel
        # (`nota_credito._linhas_creditaveis` faz `enumerate(itens, start=1)`).
        #
        # Lido como se fosse 0-based, este relatório atribuía a devolução ao
        # artigo SEGUINTE — devolver o açaí de 10,20 € descontava-os na
        # Coca-Cola —, e a última linha da fatura caía fora da guarda e criava
        # uma linha-fantasma sem produto nenhum, ao lado da verdadeira. O
        # dinheiro TOTAL do relatório continuava certo, que é o que fazia isto
        # passar despercebido: só a atribuição por artigo é que mentia.
        indice = creditada.get("indice")
        origem = (
            linhas_origem[indice - 1]
            if isinstance(indice, int) and 1 <= indice <= len(linhas_origem)
            else None
        )
        produto_id = (origem or {}).get("produto_id")
        artigos.append(_artigo(
            produtos.get(produto_id), categorias, produto_id,
            creditada.get("titulo") or _SEM_DEFINICAO,
            float(creditada.get("quantidade") or 0),
            centimos(creditada.get("total")),
            _TAXA_DO_CODIGO.get(creditada.get("tax_id")),
            # Da linha de ORIGEM: uma devolução tem de descontar no MESMO
            # tamanho que foi vendido, senão o Mini crescia e o Supreme
            # ficava por descontar.
            _variante_da_linha(origem),
        ))
    return artigos


async def _por_id(db, coleccao: str, ids: List[str], campos: Dict) -> Dict[str, Dict]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    docs = await (
        db[COLECOES[coleccao]].find({"id": {"$in": ids}}, dict(campos, _id=0))
        .to_list(len(ids))
    )
    return {d["id"]: d for d in docs}


async def _mapa_de_nomes(db, coleccao: str) -> Dict[str, str]:
    docs = await db[COLECOES[coleccao]].find({}, {"_id": 0, "id": 1, "nome": 1}).to_list(2000)
    return {d["id"]: d.get("nome") for d in docs}


async def eventos_dos_documentos(
    db, documentos: List[Dict], *,
    categoria_id: Optional[str] = None,
    utilizador_id: Optional[str] = None,
) -> List[Dict]:
    """Os documentos já lidos, transformados nos EVENTOS que `agregar` come.

    É aqui que uma fatura deixa de ser uma linha de `fat_documentos` e passa a
    ser dinheiro repartido por artigos: vai buscar a venda (ou a nota de
    crédito) que lhe deu origem, o produto de cada linha e a categoria dele.

    **Está fora do endpoint dos Relatórios de propósito.** O Dashboard precisa
    exactamente da mesma transformação para os cartões «Mais Vendidos» e «Mais
    Rentáveis», e uma segunda cópia dela era a garantia de que um dia o top de
    artigos do painel e o relatório de Produtos, no mesmo dia, dariam números
    diferentes — sem nenhum deles estar obviamente errado.

    Os filtros de categoria e de utilizador ficam aqui e não em quem chama
    porque o de CATEGORIA muda o dinheiro do evento (só conta os artigos dessa
    categoria), e não apenas as linhas que se mostram.
    """
    notas = await _por_id(
        db, "notas_credito",
        [d.get("nota_credito_id") for d in documentos if d.get("tipo") == "NC"],
        {"id": 1, "linhas": 1, "venda_id": 1, "operador": 1},
    )
    vendas = await _por_id(
        db, "vendas",
        [d.get("venda_id") for d in documentos] + [n.get("venda_id") for n in notas.values()],
        {"id": 1, "linhas": 1, "operador_id": 1, "cliente_nif": 1,
         "desconto_global_pct": 1, "desconto_global_eur": 1},
    )
    produtos = {
        p["id"]: p for p in await (
            db[COLECOES["produtos"]]
            .find({}, {"_id": 0, "id": 1, "nome": 1, "categoria_id": 1, "preco_custo": 1})
            .to_list(5000)
        )
    }
    categorias = await _mapa_de_nomes(db, "categorias")
    lojas = await _mapa_de_nomes(db, "lojas")
    utilizadores = await _mapa_de_nomes(db, "utilizadores")
    fichas = {
        c["nif"]: c.get("nome") for c in await (
            db[COLECOES["clientes"]].find({}, {"_id": 0, "nif": 1, "nome": 1}).to_list(5000)
        )
    }

    eventos = []
    for doc in documentos:
        ehNC = doc.get("tipo") == "NC"
        nota = notas.get(doc.get("nota_credito_id")) if ehNC else None
        venda = vendas.get((nota or doc).get("venda_id"))
        try:
            # Um documento sem venda mas com as linhas do Vendus reparte-se por
            # elas. É o caso das faturas da app (`origem: "app"`), que não têm
            # conta de balcão nenhuma — ver `_artigos_das_linhas_vendus`.
            if venda is None and doc.get("linhas_vendus"):
                artigos = _artigos_das_linhas_vendus(doc, categorias)
            else:
                artigos = (
                    _artigos_da_nota(nota, venda, produtos, categorias) if ehNC
                    else _artigos_da_fatura(venda, produtos, categorias)
                )
        except Exception:  # noqa: BLE001 — ver abaixo
            # **Uma venda estragada não pode levar o ecrã inteiro com ela.**
            #
            # Repartir a fatura pelos artigos passa por `_linha_vendus`, que
            # levanta um HTTPException 422 numa linha com dados impossíveis
            # (um produto que ficou sem preço, um override inválido). É o
            # mesmo travão que `fiscal._total_da_venda` já leva, e pela mesma
            # razão: a venda estragada é justamente a que mais precisa de ser
            # vista, e um relatório — ou, agora, o PRIMEIRO ECRÃ do módulo,
            # com cinco lojas a faturar — não pode ficar inacessível por
            # causa dela.
            #
            # Improvável, não impossível: `_produto_snapshot` lê o preço e o
            # IVA GRAVADOS na linha, não o produto de hoje, portanto uma
            # venda que emitiu bem volta a repartir-se bem. O que sobra são
            # as linhas escritas por versões antigas do POS.
            #
            # Fica de fora e fica CONTADO: quem chama compara `len(eventos)`
            # com os documentos que mandou. Desaparecer em silêncio era pôr o
            # cartão «Hoje» e o top de artigos a discordar sem explicação.
            logger.warning("Documento %s sem artigos: a venda não se deixa repartir.",
                         doc.get("id"), exc_info=True)
            continue
        # **Zero artigos não é um evento de 0,00 €.** É o defeito que esta
        # repartição existe para matar, e uma lista VAZIA ressuscitava-o: um
        # documento da app cujo `items` venha vazio grava-se na mesma
        # (`sincronizacao_app.py`: `cru.get("items") or []`) e ficava a valer
        # 0,00 € nas nove vistas para sempre — com o valor certo no cartão do
        # Dashboard, que lê `total_bruto`, e o contador «documentos por
        # repartir» a ZERO, portanto sem nada no ecrã a dizer que havia
        # dinheiro por atribuir.
        #
        # Ficando de fora, entra no aviso «N faturas de hoje não se deixaram
        # repartir por artigo» — a mesma porta do `except` acima, pela mesma
        # razão: o que não se sabe repartir diz-se, não se arredonda a zero.
        if not artigos:
            continue
        if categoria_id:
            artigos = [a for a in artigos if a.get("categoria_id") == categoria_id]
            if not artigos:
                continue
        operador_id = (
            ((nota or {}).get("operador") or {}).get("id") if ehNC
            else (venda or {}).get("operador_id")
        )
        if utilizador_id and operador_id != utilizador_id:
            continue
        nif = doc.get("cliente_nif") or (venda or {}).get("cliente_nif")
        eventos.append({
            "id": doc.get("id"),
            "tipo": doc.get("tipo"),
            "quando": em_lisboa(doc.get("emitido_em")),
            "loja_id": doc.get("loja_id"),
            "loja_nome": lojas.get(doc.get("loja_id")),
            "cliente_nif": nif,
            "cliente_nome": fichas.get(nif) if nif else None,
            "operador_id": operador_id,
            "operador_nome": utilizadores.get(operador_id),
            # **O dinheiro do documento é a soma dos artigos dele**, e não o
            # `total` gravado — é o que faz as nove vistas darem exactamente o
            # mesmo total no mesmo intervalo. Os dois batem por construção (a
            # repartição do desconto global é exacta ao cêntimo); quando não
            # baterem, é o `total_divergente` do ecrã de Documentos que o diz.
            "bruto_c": sum(a["bruto_c"] for a in artigos),
            "liquido_c": sum(a["liquido_c"] for a in artigos),
            "custo_c": (
                None if any(a["custo_c"] is None for a in artigos)
                else sum(a["custo_c"] for a in artigos)
            ),
            "quantidade": sum(a["quantidade"] for a in artigos),
            "artigos": artigos,
        })
    return eventos


@router.get("/relatorios/{dimensao}")
async def relatorio(
    dimensao: str,
    de: str,
    ate: str,
    loja_id: Optional[str] = None,
    utilizador_id: Optional[str] = None,
    categoria_id: Optional[str] = None,
    _: dict = Depends(gestor_atual),
) -> dict:
    """Uma das nove vistas, para um intervalo de datas.

    `de`/`ate` são datas (AAAA-MM-DD) em dias de LISBOA, e o `ate` está
    INCLUÍDO — escolher "1 a 25" quer dizer o dia 25 inteiro.

    **O filtro de CATEGORIA muda o que se soma, e não só o que se mostra.** Com
    ele activo, o dinheiro de cada documento passa a ser o dos artigos daquela
    categoria — não o total do documento. Era a única leitura honesta: um
    relatório de Lojas filtrado por "Bebidas" que somasse faturas inteiras
    estaria a atribuir às bebidas o açaí que ia na mesma fatura.
    """
    if dimensao not in DIMENSOES:
        raise HTTPException(status_code=404, detail="Relatório desconhecido: %s" % dimensao)
    try:
        janela = janela_de_datas(
            datetime.fromisoformat(de).date() if len(de) > 10 else _data(de),
            datetime.fromisoformat(ate).date() if len(ate) > 10 else _data(ate),
        )
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))

    db = obter_db()
    filtro = {"emitido_em": {"$gte": janela.inicio.isoformat(), "$lt": janela.fim.isoformat()}}
    if loja_id:
        filtro["loja_id"] = loja_id
    documentos = await (
        db[COLECOES["documentos"]].find(filtro, {"_id": 0}).to_list(_TECTO_DOCUMENTOS)
    )

    eventos = await eventos_dos_documentos(
        db, documentos, categoria_id=categoria_id, utilizador_id=utilizador_id)

    agregado = agregar(eventos, dimensao)

    # **Os TAMANHOS, na vista de Produtos.** No catálogo há UM açaí e o
    # tamanho é uma personalização dele — a linha dizia «Açaí 25», que é
    # verdade e não responde a nada: vinte e cinco de qual? A mesma
    # repartição que o cartão «Mais Vendidos» do painel mostra, pela mesma
    # função, para os dois nunca discordarem no mesmo dia.
    #
    # Só nesta dimensão: um tamanho reparte um ARTIGO. Repartir uma loja ou
    # um utilizador por tamanhos misturava o açaí com tudo o resto que essa
    # loja vendeu.
    linhas = agregado["linhas"]
    if dimensao == "produto":
        por_tamanho = tamanhos_por_produto(eventos)
        linhas = [dict(l, tamanhos=por_tamanho.get(l["chave"]) or []) for l in linhas]

    return {
        "dimensao": dimensao,
        "de": de, "ate": ate,
        "linhas": linhas,
        "total": agregado["total"],
        "serie": (
            [{"rotulo": l["rotulo"], "valor": l["bruto"]} for l in agregado["linhas"]]
            if dimensao in {"dia", "hora", "dia_semana", "mes"}
            else serie_diaria(eventos)
        ),
        "com_quantidade": dimensao in COM_QUANTIDADE,
        "truncado": len(documentos) >= _TECTO_DOCUMENTOS,
    }


def _data(texto: str):
    from datetime import date as _date
    return _date.fromisoformat(texto)
