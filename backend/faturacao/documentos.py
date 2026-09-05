"""O separador **Faturação** do POS — a lista dos documentos já emitidos, e a
fatura aberta com as três acções que o dono pediu (imprimir, nota de crédito,
copiar para a venda).

Até aqui **não existia rota nenhuma que lesse `fat_documentos`** — nem uma. O
POS emitia, mostrava o número no ecrã da confirmação, e a fatura desaparecia
para sempre: a única forma de lá voltar era o `GET /pos/venda/{venda_id}`, e
esse exige o id da VENDA, que ninguém guardou. Um cliente que volte dez
minutos depois com o talão rasgado não traz um uuid.

## O ÂMBITO da lista, e porque é este

A pergunta que o balcão faz não é «que documentos emiti neste turno?». É
**«onde está a fatura daquele cliente?»** — e o cliente que volta não sabe em
que turno comprou.

- **NÃO é só o turno a decorrer.** O caso que o dono nomeou é o cliente que
  volta AMANHÃ; uma lista limitada à sessão aberta está VAZIA às 9h da manhã,
  que é precisamente a hora a que ele aparece. Uma lista assim não é uma lista
  incompleta: é uma lista que falha sempre no único caso para que existe.
- **É a LOJA, e não a caixa.** O dono escreveu «desta caixa» e hoje isso é o
  MESMO conjunto — uma loja tem uma caixa e um PC. No dia em que houver duas,
  o conjunto certo continua a ser o da loja: o cliente foi servido pela LOJA,
  não pelo posto, e uma lista por caixa fazia o balcão não encontrar o talão
  do drive-thru — o cliente ficava sem reimpressão por uma fronteira que
  ninguém do lado dele consegue ver. É o inverso da regra do
  `venda._contas_do_balcao`: ali o âmbito estreito PROTEGE (o cliente do
  balcão não paga o açaí do drive), aqui estreitá-lo só ESCONDE.
  E o índice `("fat_documentos", [("loja_id", 1), ("emitido_em", 1)])` de
  `db.py` já serve exactamente esta leitura, ordem incluída; por caixa não há
  índice nenhum — o `caixa_id` nem sequer está gravado no documento, só na
  venda.
- **Com tecto, e a dizer que tem tecto.** `_LIMITE_LISTA` documentos, do mais
  recente para o mais antigo. Uma loja movimentada faz ~200 vendas por dia,
  por isso isto é o dia de hoje e a noite de ontem — que é o alcance do
  cliente que volta. A resposta traz `ha_mais`, e o ecrã DIZ que está a
  mostrar as N mais recentes: uma lista truncada que não se assume é uma
  lista que mente sobre o que não encontrou.

## O dinheiro é do servidor, e vem de quem já o somou

Nada aqui soma euros de novo:

- as LINHAS da fatura saem de `fiscal._itens_vendus` — a MESMA função que
  construiu as linhas entregues à AT — e o líquido de cada uma de
  `mapa_imposto._liquido_da_linha`, a mesma fórmula que o Vendus aplica do
  lado dele;
- o MAPA DE IMPOSTO é `mapa_imposto.mapa_de_imposto`, tal e qual: hoje ele
  agrega um turno, aqui recebe um documento (uma lista de uma venda). O IVA é
  o RESTO (`total − base`), por isso `base + iva == total` é exacto por
  construção, e não por sorte;
- o TOTAL é o do DOCUMENTO — o número que o Vendus devolveu e que a AT tem.
  A soma das linhas vai à mesma na resposta (`total_das_linhas`) e, quando os
  dois não baterem ao cêntimo, `total_divergente` diz que sim. Escolher um
  deles em silêncio era esconder exactamente o tipo de erro que este ecrã
  serve para apanhar.

Tudo comparado em CÊNTIMOS INTEIROS (`_centimos`), nunca em vírgula
flutuante.

## O que este módulo NÃO faz

Não emite, não anula, não altera um documento fiscal e não toca em reserva
nenhuma. A ÚNICA escrita que sai daqui é `copiar_para_venda` — e mesmo essa
não escreve nada por sua conta: chama `venda.abrir_venda` e
`venda.juntar_linha`, as rotas de sempre, com os guardas de sempre. Ver a
docstring dessa função.
"""
import asyncio
import base64
import logging
import math
import os
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .db import COLECOES, obter_db
from .fiscal import _itens_vendus
from .mapa_imposto import (
    _TAXA_DO_CODIGO, _base_em_centimos, _liquido_da_linha, mapa_de_imposto,
    totais_do_mapa,
)
from .auth import gestor_atual
from .periodos import janela_de_datas
from .pos_auth import operador_atual
from .vendus.cliente import ClienteVendus, VendusErro, obter_conta

# O mesmo NIF por omissão da importação (importacao.py) — a conta Vendus da
# Fordaimon Foods. Escrito nos dois sítios porque são dois módulos que não se
# importam um ao outro; o `.env` do servidor manda em ambos.
_NIF_POR_OMISSAO = "517542510"

logger = logging.getLogger(__name__)

router = APIRouter()

# Quantos documentos a lista traz. Ver o âmbito, no cabeçalho: ~200 vendas/dia
# numa loja movimentada, portanto isto é o dia de hoje mais a noite de ontem —
# o alcance do cliente que volta. Lê-se um a mais para saber se há mais, e é
# esse que faz o `ha_mais` ser um facto e não um palpite.
_LIMITE_LISTA = 200

# Quantos artigos cabem no resumo de uma linha da lista. Três chegam para a
# operadora reconhecer o pedido de relance ("Açaí Regular, Saco"); o resto
# conta-se em `mais_artigos`, que é honesto e cabe.
_ARTIGOS_NO_RESUMO = 3

_MSG_DOCUMENTO_INEXISTENTE = "Documento não encontrado."
_MSG_SEM_TALAO = (
    "Este documento não tem o talão certificado guardado — não há bytes para "
    "reimprimir. O talão volta a poder tirar-se do Vendus, mas não por aqui."
)
_MSG_COPIA_SEM_LINHAS = (
    "Não há nada para copiar: não sobrou nenhum artigo desta fatura que ainda "
    "exista no catálogo de hoje."
)


def _centimos(valor) -> int:
    """Euros para cêntimos inteiros. A mesma conversão de
    `mapa_imposto._centimos`, e pela mesma razão: o dinheiro compara-se em
    inteiros."""
    return int(round(float(valor or 0) * 100))


# --- As linhas que vêm da API do Vendus (as faturas da app) -------------------
#
# **Não passam por validação nenhuma.** A sincronização confere o
# `amount_gross` do DOCUMENTO e mais nada (`sincronizacao_app.deve_importar`);
# os `items` ficam gravados como a API os mandou. Um `qty` a dizer `"abc"`
# levantava `ValueError` no `float()`, um `amounts` a vir como lista levantava
# `AttributeError` no `.get` — e o gestor levava um **500 ao abrir a fatura**:
# uma linha ilegível fechava o ecrã inteiro, incluindo as linhas boas, o
# número, o ATCUD e o mapa de imposto.
#
# O leitor da MESMA API no Financeiro guarda-se assim há meses
# (`server.py::_fin_clean_num` e o `isinstance` dos `items`/`it`), e isto é o
# mesmo padrão no mesmo sítio. Nos Relatórios não é preciso: ali a leitura das
# mesmas linhas já corre dentro de um `try` que conta o documento como "não se
# deixou repartir" (`relatorios.py`).


def _numero_do_vendus(valor) -> Optional[float]:
    """Um número que veio do Vendus, ou `None` se não se conseguir ler.

    Aceita a vírgula decimal (`"1,00"`), o outro formato que a API usa. Não
    tenta o `"1.234,56"` do Financeiro: uma FS da app são uns euros, não há
    milhares nenhuns, e uma leitura que se engane de casa é pior do que uma que
    diga que não sabe.
    """
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def _linhas_do_vendus(documento: Dict) -> List[Dict]:
    """As `linhas_vendus` que dá para ler — as outras nem chegam ao ciclo."""
    linhas = documento.get("linhas_vendus")
    if not isinstance(linhas, list):
        return []
    return [linha for linha in linhas if isinstance(linha, dict)]


def _campo_dict(linha: Dict, nome: str) -> Dict:
    """`amounts`/`tax` da linha, e `{}` se vier outra coisa qualquer."""
    valor = linha.get(nome)
    return valor if isinstance(valor, dict) else {}


async def _documento_da_loja(db, documento_id: str, loja_id: str) -> Dict:
    """O documento pelo `id`, e só se for DESTA loja.

    O âmbito é o de `venda._obter_venda_da_loja`, palavra por palavra: o de
    outra loja é 404 e não 403, porque o id vem do browser e responder 403
    confirmava a quem perguntasse que aquele documento existe.
    """
    documento = await db[COLECOES["documentos"]].find_one({"id": documento_id})
    if not documento or documento.get("loja_id") != loja_id:
        raise HTTPException(status_code=404, detail=_MSG_DOCUMENTO_INEXISTENTE)
    return documento


async def _vendas_por_id(db, venda_ids: List[str]) -> Dict[str, Dict]:
    """As vendas destes documentos, numa leitura só.

    Uma leitura e não N: a lista traz até 200 documentos, e 200 `find_one`
    seguidos num PC de loja com fila à frente é o género de coisa que se sente
    no dedo. O índice é o `id`, que é a chave de tudo neste módulo.
    """
    if not venda_ids:
        return {}
    vendas = await (
        db[COLECOES["vendas"]]
        .find({"id": {"$in": list(venda_ids)}})
        .to_list(len(venda_ids))
    )
    return {v["id"]: v for v in vendas if v.get("id")}


def _resumo_dos_artigos(venda: Optional[Dict]) -> Tuple[List[Dict], int]:
    """O que o cliente levou, resumido — os primeiros artigos e quantos
    ficaram de fora.

    **É esta a coluna que faz a lista servir para alguma coisa.** O cliente
    que volta raramente sabe o número da fatura, e muitas vezes nem o total
    exacto; sabe que comprou um açaí grande. Sem o que lá vai, a operadora
    fica a abrir faturas uma a uma com a fila a crescer.

    Vem de `venda["linhas"]` e não de `_itens_vendus`: o título do Vendus
    traz os toppings todos entre parêntesis ("Açaí Regular (Nutella 2×,
    Morango)") e não cabe numa linha de lista. O nome do produto cabe, e é
    por ele que se reconhece o pedido; a fatura aberta mostra o resto.

    **As repetições AGREGAM-SE**, pela ordem da primeira — a mesma regra (e a
    mesma razão) de `precos._descricao_das_opcoes` e de `talao._doses`:
    "1× Coca-Cola · 1× Coca-Cola · 1× Coca-Cola" é a mesma informação que
    "3× Coca-Cola" e ilegível de relance. Medido no ecrã: uma fatura de cinco
    refrigerantes ocupava a linha inteira a dizer três vezes o mesmo e
    escondia atrás de um "+2" que os outros dois também eram refrigerantes.
    O tecto conta ARTIGOS DIFERENTES, e é isso que faz o "+2" querer dizer
    "há mais dois artigos diferentes" e não "há mais duas linhas iguais".

    A quantidade é SOMADA aqui, e é a única soma deste módulo: não é dinheiro
    (a regra do dinheiro somado pelo servidor não lhe toca) e pode ser
    fraccionária — a parte de uma conta dividida é 0.3337 de um açaí. Quem a
    formata é o ecrã.
    """
    linhas = (venda or {}).get("linhas") or []
    quantidades: Dict[str, float] = {}
    ordem: List[str] = []
    for li in linhas:
        nome = li.get("produto_nome") or "?"
        if nome not in quantidades:
            ordem.append(nome)
            quantidades[nome] = 0
        try:
            quantidades[nome] += float(li.get("quantidade", 1) or 0)
        except (TypeError, ValueError):
            # Uma quantidade ilegível não pode apagar o artigo da lista: o que
            # não se pode perder é a EXISTÊNCIA do artigo (a regra de
            # `por_resolver._total_da_venda`). Fica sem somar nada.
            pass
    artigos = [
        {"nome": nome, "quantidade": quantidades[nome]}
        for nome in ordem[:_ARTIGOS_NO_RESUMO]
    ]
    return artigos, max(0, len(ordem) - _ARTIGOS_NO_RESUMO)


def _pagamentos_publicos(venda: Optional[Dict]) -> List[Dict]:
    """Como o cliente pagou — o retrato gravado na venda pela emissão
    (`fiscal.finalizar`, campo `pagamentos`), nunca o tipo de pagamento como
    ele está configurado HOJE: o gestor pode renomeá-lo, e o que saiu no papel
    não muda.

    Está na lista e não só na fatura aberta de propósito: «paguei em
    multibanco» é uma das três coisas que o cliente diz ao voltar, a par do
    total e do que levou.
    """
    return [
        {"nome": p.get("nome"), "valor": p.get("valor")}
        for p in (venda or {}).get("pagamentos") or []
    ]


def _documento_na_lista(documento: Dict, venda: Optional[Dict]) -> Dict:
    artigos, mais = _resumo_dos_artigos(venda)
    return {
        "id": documento.get("id"),
        # A referência que está impressa no talão que o cliente traz na mão.
        "numero": documento.get("numero"),
        "atcud": documento.get("atcud"),
        "emitido_em": documento.get("emitido_em"),
        "total": documento.get("total"),
        "tipo": documento.get("tipo"),
        # O carimbo do modo daquele documento — não o modo de agora. Um
        # documento emitido em `tests` não vale nada, e a lista tem de o dizer
        # (mesma regra de `fiscal._resposta_documento` e da faixa do POS).
        "modo": documento.get("modo"),
        "artigos": artigos,
        "mais_artigos": mais,
        "pagamentos": _pagamentos_publicos(venda),
        # `False` quando a venda já não existe na base: sem ela não há artigos
        # nem pagamentos para mostrar, e o ecrã não pode ler a ausência dos
        # dois como "esta fatura não levou nada". Sempre presente, mesmo
        # `True`, pela regra de `_venda_publica`: o ecrã não adivinha se a
        # chave em falta quer dizer "não" ou "versão antiga da API".
        "tem_venda": venda is not None,
    }


@router.get("/pos/documentos")
async def listar_documentos(operador: Dict = Depends(operador_atual)) -> dict:
    """As faturas desta loja, da mais recente para a mais antiga.

    Ver o cabeçalho do módulo para o âmbito e para o porquê de ele ser a loja
    e não a sessão. Não recebe parâmetro de âmbito NENHUM — nem um `caixa_id`,
    nem um `sessao_id`, nem um `limite` — pela razão de `_contas_do_balcao`:
    um âmbito que viaja como argumento é um âmbito que dois chamadores acabam
    a passar diferente, e a partir daí há dois conjuntos que se dizem o mesmo.

    A loja vem do TOKEN do operador, como tudo neste módulo.
    """
    db = obter_db()
    # Um a mais do que o tecto: é o que transforma "há mais" num facto medido
    # em vez de uma inferência a partir de a lista ter vindo cheia (que dá a
    # resposta errada exactamente quando há 200 documentos e nem um a mais).
    documentos = await (
        db[COLECOES["documentos"]]
        .find({"loja_id": operador["loja_id"]})
        .sort("emitido_em", -1)
        .to_list(_LIMITE_LISTA + 1)
    )
    ha_mais = len(documentos) > _LIMITE_LISTA
    documentos = documentos[:_LIMITE_LISTA]

    vendas = await _vendas_por_id(
        db, [d["venda_id"] for d in documentos if d.get("venda_id")]
    )
    return {
        "documentos": [
            _documento_na_lista(d, vendas.get(d.get("venda_id"))) for d in documentos
        ],
        # O tecto vai na resposta para o ecrã poder dizer o número em vez de
        # uma vaga "as mais recentes" — duas cópias do mesmo limite, uma de
        # cada lado, acabam sempre com o ecrã a prometer um alcance que já não
        # é o real (a lição do `SEGUNDOS_DE_ESPERA` no PosVenda).
        "limite": _LIMITE_LISTA,
        "ha_mais": ha_mais,
    }


def _linhas_da_fatura(venda: Optional[Dict]) -> List[Dict]:
    """As linhas como o print do Vendus as mostra: Produto · Preço/Uni. ·
    Qtd. · Preço.

    O «Produto» é o `title` de `fiscal._itens_vendus` — com os toppings entre
    parêntesis, exactamente como saiu no papel e como foi entregue à AT. Não é
    o `produto_nome` da linha: numa reimpressão o cliente confere o que pagou,
    e o que ele pagou incluía a Nutella.

    O «Preço» é o LÍQUIDO da linha (`mapa_imposto._liquido_da_linha`) — já com
    o desconto próprio e com a fatia do desconto global que lhe calhou, pela
    mesma fórmula que o Vendus aplicou. Não é `qtd × preço/uni.`: numa fatura
    com desconto esses dois números são diferentes, e o que o cliente pagou é
    este.

    **E é por isso que o `desconto` vai junto.** Visto no ecrã, «Preço/Uni.
    € 10,20 · Qtd. 1 · Preço € 9,94» lê-se como um erro de soma: não há na
    fatura uma única palavra a dizer para onde foram os 26 cêntimos, e quem
    confere um talão para de conferir ali. O valor é a diferença entre o bruto
    (`qtd × preço/uni.`, arredondado como o Vendus o arredonda) e o líquido, e
    é SOMADO AQUI e não no ecrã — cêntimos inteiros, como todo o dinheiro deste
    módulo. Vai a `0.0` quando não houve desconto nenhum, que é o caso normal:
    o ecrã não pode ter de adivinhar se a ausência do campo quer dizer «não
    houve» ou «esta versão da API não responde a isso».
    """
    if venda is None:
        return []
    linhas = []
    for item in _itens_vendus(venda):
        bruto = round(item["qty"] * item["gross_price"], 2)
        liquido = _liquido_da_linha(item)
        # **O IVA vai NA LINHA, e não só no mapa lá em baixo.** É onde quem
        # confere um talão o procura — o print do Vendus tem-no como coluna — e
        # sem ele uma fatura com duas taxas (o açaí a 13 % e o refrigerante a
        # 23 %, que é o caso normal do cardápio) obriga a adivinhar qual linha
        # é qual. A taxa sai do MESMO sítio que o mapa usa
        # (`mapa_imposto._TAXA_DO_CODIGO`), nunca de uma tabela escrita aqui.
        codigo = item.get("tax_id")
        linhas.append({
            "titulo": item.get("title"),
            "quantidade": item.get("qty"),
            "preco_unitario": item.get("gross_price"),
            "desconto": (_centimos(bruto) - _centimos(liquido)) / 100.0,
            "total": liquido,
            "tax_id": codigo,
            "taxa": _TAXA_DO_CODIGO.get(codigo),
        })
    return linhas


def _linhas_das_linhas_vendus(documento: Dict) -> List[Dict]:
    """As linhas de uma fatura que não tem conta de balcão nenhuma.

    O ecrã de Documentos monta as linhas a partir da venda. Estes documentos
    não têm venda, e a ausência das linhas não pode ser lida como "esta fatura
    não levou nada" — pior, `total_divergente` compara o total com a soma das
    linhas e acendia um aviso de fatura estragada numa fatura sã.

    **A FORMA é a de `_linhas_da_fatura`, campo por campo**, porque é a MESMA
    tabela do MESMO ecrã: `FatDocumentos.js` lê `titulo`, `taxa`,
    `preco_unitario`, `quantidade` e `total`. Um nome diferente aqui não dava
    erro nenhum no servidor — dava uma coluna «Produto» em branco numa fatura
    sã, que é o género de defeito que só aparece com o ecrã à frente.

    O «P. Unit.» sai do total a dividir pela quantidade: o Vendus manda o
    dinheiro da LINHA (`amounts.gross_total`, o número que a AT tem), e o preço
    por unidade que interessa a quem confere é o que ele pagou por cada um —
    repetir ali o total fazia uma linha de três águas parecer três vezes mais
    cara. Pela mesma razão o `desconto` vai a `0.0`: já não há gap nenhum entre
    `qtd × p. unit.` e o total para explicar (ver `_linhas_da_fatura`).
    """
    linhas = []
    for linha in _linhas_do_vendus(documento):
        montantes = _campo_dict(linha, "amounts")
        imposto = _campo_dict(linha, "tax")
        # **Uma linha ilegível fica no ecrã, com o valor a zero — não se
        # esconde.** Saltá-la deixava a fatura com ar de completa e um artigo a
        # menos, que é a versão silenciosa do mesmo defeito; a zero, ela aparece
        # com o nome que o Vendus mandou E o `total_divergente` acende sozinho
        # («a soma das linhas não bate com o total»), que é o aviso que já
        # existe para "esta fatura não está bem, veja-a no Vendus".
        total = _numero_do_vendus(montantes.get("gross_total")) or 0.0
        quantidade = _numero_do_vendus(linha.get("qty")) or 0.0
        linhas.append({
            # Não há produto nosso do outro lado: o ecrã escreve o nome que o
            # Vendus mandou e não finge que conhece o artigo. `str()` porque o
            # ecrã põe isto directamente numa célula: um `title` que viesse como
            # objeto rebentava o React ("Objects are not valid as a React
            # child") e o ecrã ficava branco em vez de 500.
            "titulo": str(linha.get("title") or "—"),
            "quantidade": quantidade,
            "preco_unitario": round(total / quantidade, 2) if quantidade else total,
            "desconto": 0.0,
            "total": total,
            "tax_id": imposto.get("id"),
            "taxa": imposto.get("rate"),
        })
    return linhas


def _mapa_das_linhas_vendus(documento: Dict) -> List[Dict]:
    """O mapa de imposto de uma fatura da app, agrupado por taxa.

    **A FORMA é a de `mapa_imposto.mapa_de_imposto`** — `tax_id`, `taxa`,
    `documentos`, `base`, `iva`, `total` — porque é o MESMO campo da MESMA
    resposta, e `totais_do_mapa` soma a chave `total` de cada linha a direito:
    um dicionário com menos chaves levantava `KeyError` e a fatura abria com um
    500. Pela mesma razão o mapa tem de ser feito AQUI e não deixado a
    `mapa_de_imposto([])`: um mapa vazio dava «€ 0,00» de base e de IVA por
    baixo de uma tabela de 6,85 €.

    A base é a do PRÓPRIO documento (`amounts.net_total`, o número que o Vendus
    entregou à AT) e o IVA é o RESTO — `base + iva == total` ao cêntimo por
    construção, como no Z. Uma linha sem `net_total` decompõe-se pelo código de
    imposto (`_base_em_centimos`, a fórmula do Z); uma que não tenha nem um nem
    outro conta para o total e não para as outras duas colunas — não se inventa
    imposto, que é a regra de `mapa_de_imposto` para uma taxa desconhecida.

    A ordem é a das linhas do documento: um documento não é um turno, e a
    ordem em que o Vendus as mandou é determinística e é a do papel.
    """
    por_taxa: Dict = {}
    for linha in _linhas_do_vendus(documento):
        montantes = _campo_dict(linha, "amounts")
        imposto = _campo_dict(linha, "tax")
        # O código é a CHAVE do agrupamento: um `id` que viesse como lista era
        # `TypeError: unhashable` no `setdefault`, outra vez 500 ao abrir. Um
        # código que não seja texto é código nenhum — e um código desconhecido
        # já tem regra escrita aqui em baixo (conta para o total, não inventa
        # imposto).
        codigo = imposto.get("id") if isinstance(imposto.get("id"), str) else None
        entrada = por_taxa.setdefault(codigo, {
            "tax_id": codigo, "taxa": imposto.get("rate"),
            # Um documento, uma vez em cada taxa que tocou — a mesma contagem
            # de `mapa_de_imposto` (é o que a contabilista conta).
            "documentos": 1, "base": 0, "iva": 0, "total": 0,
        })
        total_centimos = _centimos(_numero_do_vendus(montantes.get("gross_total")))
        entrada["total"] += total_centimos
        # `_numero_do_vendus` e não `is not None`: uma base ilegível lida como
        # "presente" dava base 0 e punha o IVA a valer a linha inteira. Ilegível
        # é o mesmo que ausente — decompõe-se pelo código, como sempre.
        base = _numero_do_vendus(montantes.get("net_total"))
        if base is not None:
            base_centimos = _centimos(base)
        elif _TAXA_DO_CODIGO.get(codigo) is not None:
            base_centimos = _base_em_centimos(
                total_centimos, _TAXA_DO_CODIGO[codigo])
        else:
            continue
        entrada["base"] += base_centimos
        entrada["iva"] += total_centimos - base_centimos
    return [
        dict(entrada, base=entrada["base"] / 100.0, iva=entrada["iva"] / 100.0,
             total=entrada["total"] / 100.0)
        for entrada in por_taxa.values()
    ]


@router.get("/pos/documentos/{documento_id}")
async def obter_documento(
    documento_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """A fatura aberta — cabeçalho, cliente, artigos, pagamento, mapa de
    imposto e total.

    **O total que sai daqui é o do DOCUMENTO**, o número que o Vendus
    devolveu e que a AT tem. A soma das linhas vai junto (`total_das_linhas`)
    e `total_divergente` diz quando os dois não batem ao cêntimo. Deviam bater
    sempre — as linhas são as mesmas que foram enviadas e a repartição do
    desconto global é exacta ao cêntimo (`fiscal._distribuir_centimos`) — e é
    precisamente por isso que uma divergência tem de aparecer em vez de ser
    escolhida em silêncio: se um dia aparecer, aconteceu alguma coisa que
    ninguém previu e alguém tem de a ver.

    Uma venda que já não exista na base dá uma fatura sem artigos e sem mapa,
    com `tem_venda: false` — e não um 404: o DOCUMENTO existe, tem número e
    ATCUD, e escondê-lo por causa da venda era esconder um documento fiscal
    real.
    """
    db = obter_db()
    documento = await _documento_da_loja(db, documento_id, operador["loja_id"])
    return await _detalhe_do_documento(db, documento)


async def _quem_e_onde(db, documento: Dict, venda: Optional[Dict]) -> Dict:
    """**Quem emitiu, em que loja e em que caixa** — as três perguntas que a
    fatura não responde sozinha e que são as primeiras que o gestor faz quando
    olha para um documento que não reconhece.

    Os nomes vão RESOLVIDOS e não em ids: um ecrã que mostrasse
    `operador_id: 3f2a…` obrigava o gestor a ir procurar a quem pertence, e a
    pergunta dele é «quem fez esta venda?». Um id que já não exista (a pessoa
    saiu da empresa e a ficha foi apagada) dá `None` — e o ecrã escreve «—», que
    é a verdade, em vez de esconder a fatura.

    Só o backoffice pede isto. O POS já sabe em que loja está, e três leituras
    a mais no caminho da reimpressão eram três leituras a mais com o cliente à
    frente."""
    async def nome(coleccao: str, id_: Optional[str]) -> Optional[str]:
        if not id_:
            return None
        doc = await db[COLECOES[coleccao]].find_one({"id": id_}, {"_id": 0, "nome": 1})
        return (doc or {}).get("nome")

    return {
        "loja_nome": await nome("lojas", documento.get("loja_id")),
        "caixa_nome": await nome("caixas", (venda or {}).get("caixa_id")),
        "operador_nome": await nome("utilizadores", (venda or {}).get("operador_id")),
        "loja_id": documento.get("loja_id"),
        "caixa_id": (venda or {}).get("caixa_id"),
        "operador_id": (venda or {}).get("operador_id"),
        # De onde veio a venda. A app não tem operador nem caixa, e a linha do
        # ecrã tem de o DIZER em vez de deixar dois traços sem explicação: dois
        # "—" numa fatura lêem-se como "a ficha do operador foi apagada", e a
        # primeira coisa que o gestor faz com isso é ir procurar quem vendeu.
        "origem": "App L'Açaí" if documento.get("origem") == "app" else "POS",
        "criada_em": (venda or {}).get("criada_em"),
    }


async def _detalhe_do_documento(db, documento: Dict, com_contexto: bool = False) -> dict:
    """A fatura aberta, sem decidir QUEM a pode ver — isso é de quem chama.

    Vive à parte desde que o backoffice ganhou o seu próprio ecrã de
    Documentos: o POS lê pela loja do token do operador, a gestão lê qualquer
    loja com o JWT do portal, e o que os dois mostram tem de ser EXACTAMENTE a
    mesma fatura. Duas montagens da mesma fatura acabam a dizer números
    diferentes, e a primeira vez que isso acontecer é o dono a perguntar qual
    delas está certa."""
    venda = await db[COLECOES["vendas"]].find_one({"id": documento.get("venda_id")})

    # Sem venda mas com as linhas do Vendus: é uma fatura da app. O `venda is
    # None` é metade da guarda e tem de lá estar — um documento NOSSO que
    # ganhasse `linhas_vendus` um dia passava a ignorar a venda, e os toppings,
    # o desconto e o pagamento desapareciam do ecrã (a mesma guarda, e a mesma
    # razão, de `relatorios.py`).
    da_app = venda is None and bool(documento.get("linhas_vendus"))

    linhas = (_linhas_das_linhas_vendus(documento) if da_app
              else _linhas_da_fatura(venda))
    # Somado em CÊNTIMOS INTEIROS, nunca com `sum()` sobre floats — é a regra
    # da casa, e aqui serve para responder a uma pergunta sobre o cêntimo.
    total_das_linhas = sum(_centimos(li["total"]) for li in linhas)
    total_documento = documento.get("total")

    # O mapa de imposto DESTE documento: a mesma função do Z, com uma lista de
    # uma venda. Ela filtra `estado == "emitida"` — a venda de um documento
    # emitido está sempre nesse estado (`fiscal._gravar_documento` põe-na lá
    # incondicionalmente), e uma que não esteja produz um mapa vazio em vez de
    # inventar imposto sobre uma conta que não é fatura nenhuma.
    mapa = (_mapa_das_linhas_vendus(documento) if da_app
            else mapa_de_imposto([venda] if venda else []))

    # **Em valor ABSOLUTO, mas SÓ NA NOTA DE CRÉDITO.** O sinal de uma NC lida
    # do Vendus não é nosso: a API tanto devolve as linhas negativas como
    # positivas (é o que `relatorios._artigos_das_linhas_vendus` documenta, e
    # testa nos dois sentidos), e comparar com sinal fazia uma nota SÃ acender o
    # aviso de "chame quem trata do sistema" — o alarme falso que esta tarefa
    # existe para tirar do ecrã.
    #
    # **Só na NC**, porque é a regra que a casa já escreve sobre estas MESMAS
    # `linhas_vendus` (`relatorios.py:449`): «Numa fatura, uma linha negativa é
    # um desconto legítimo, e um `abs()` incondicional transformava-o em
    # receita.» Aqui o estrago do `abs()` incondicional é o simétrico:
    # `abs(a) != abs(b)` só perde um caso — `a == -b` — e é precisamente esse
    # que esta rede de segurança existe para apanhar. Uma FS com o sinal
    # trocado (no total, ou numa linha) passava por sã, calada.
    total_c, linhas_c = _centimos(total_documento), total_das_linhas
    if documento.get("tipo") == "NC":
        total_c, linhas_c = abs(total_c), abs(linhas_c)

    return {
        "id": documento.get("id"),
        "numero": documento.get("numero"),
        "atcud": documento.get("atcud"),
        "tipo": documento.get("tipo"),
        "modo": documento.get("modo"),
        "emitido_em": documento.get("emitido_em"),
        "vendus_document_id": documento.get("vendus_document_id"),
        # O NIF que o cliente pediu na altura, ou `None` — que o ecrã lê como
        # "Consumidor Final", que é o que o Vendus assume quando não vai NIF
        # nenhum (`fiscal.finalizar`).
        "cliente_nif": (venda or {}).get("cliente_nif"),
        "tem_venda": venda is not None,
        "venda_id": documento.get("venda_id"),
        "linhas": linhas,
        "pagamentos": _pagamentos_publicos(venda),
        "mapa_imposto": mapa,
        "totais_imposto": totais_do_mapa(mapa),
        "total": total_documento,
        "total_das_linhas": total_das_linhas / 100.0,
        # Ver o `total_c`/`linhas_c` acima: o `abs()` é só o da NC. Nada muda
        # para os documentos do POS — ali as duas parcelas saem da MESMA venda
        # e são positivas por construção.
        "total_divergente": (
            total_documento is not None
            and bool(linhas)
            and total_c != linhas_c
        ),
        # Há bytes de talão guardados com esta fatura? É o que decide se o
        # botão de reimprimir tem alguma coisa para mandar à impressora
        # quando o agente existir. Ver `talao_do_documento`.
        "tem_talao": bool(documento.get("talao_escpos")),
        **(await _quem_e_onde(db, documento, venda) if com_contexto else {}),
    }


# --- O ecrã de Documentos do BACKOFFICE ---------------------------------------
#
# **Porque não se reaproveitam as rotas do POS.** As de cima respondem à
# pergunta do balcão — «onde está a fatura daquele cliente?» — e por isso o
# âmbito delas é a loja do TOKEN, sem filtro nenhum e com um tecto pequeno. A
# do gestor é outra pergunta: «o que é que se emitiu, em que loja, naquele
# intervalo?». Loja passa a FILTRO, entram datas e pesquisa, e o tecto dá lugar
# a paginação. Uma rota a servir as duas acabava com um `âmbito` a viajar por
# argumento — que é exactamente o que a docstring de `listar_documentos` recusa.
#
# O que NÃO muda é a fatura: o detalhe sai do mesmo `_detalhe_do_documento`.

_POR_PAGINA = 50
# Tecto do que se soma para o resumo. Uma loja faz ~200 documentos por dia, por
# isso isto são uns 25 dias de uma loja ou uma semana das cinco. Passando daí,
# o resumo diz que está truncado em vez de mentir com um número parcial.
_TECTO_DO_RESUMO = 5000
_TIPOS = {"FS", "NC"}


def _regex_literal(texto: str) -> Dict:
    """Uma pesquisa por texto que é MESMO por texto. Sem isto, um `(` escrito
    na caixa de pesquisa é um regex inválido e a rota devolve 500 — e um `.*`
    devolvia a lista toda como se fosse um resultado."""
    return {"$regex": re.escape(texto), "$options": "i"}


async def _filtro_dos_documentos(
    db, de: Optional[str], ate: Optional[str], loja_id: Optional[str],
    tipo: Optional[str], q: Optional[str],
) -> Dict:
    filtro: Dict = {}
    if de or ate:
        if not (de and ate):
            raise HTTPException(
                status_code=422,
                detail="Escolha as duas datas do intervalo, ou nenhuma.")
        try:
            janela = janela_de_datas(date.fromisoformat(de), date.fromisoformat(ate))
        except ValueError as erro:
            raise HTTPException(status_code=422, detail=str(erro))
        # **As fronteiras são as de LISBOA, convertidas para UTC** — é o que o
        # `periodos.janela_de_datas` devolve. Filtrar pela data em cru punha a
        # venda das 00h30 no dia anterior (o `emitido_em` é UTC), e o dia 1 do
        # mês aparecia sempre a menos.
        filtro["emitido_em"] = {
            "$gte": janela.inicio.isoformat(), "$lt": janela.fim.isoformat()}
    if loja_id:
        filtro["loja_id"] = loja_id
    if tipo:
        if tipo not in _TIPOS:
            raise HTTPException(status_code=422, detail="Tipo desconhecido: %s" % tipo)
        filtro["tipo"] = tipo
    if q:
        procurado = q.strip()
        # **O NIF não está no documento, está na VENDA** — e é por isso que a
        # pesquisa vai buscar primeiro as vendas com aquele NIF e só depois
        # procura os documentos delas. Procura-se pelas duas coisas ao mesmo
        # tempo (número OU NIF) em vez de adivinhar qual é qual pelo formato:
        # quem escreve na caixa não sabe que são dois campos diferentes.
        vendas = await (
            db[COLECOES["vendas"]]
            .find({"cliente_nif": _regex_literal(procurado)}, {"id": 1, "_id": 0})
            .to_list(_TECTO_DO_RESUMO)
        )
        alternativas = [{"numero": _regex_literal(procurado)}]
        if vendas:
            alternativas.append({"venda_id": {"$in": [v["id"] for v in vendas]}})
        filtro["$or"] = alternativas
    return filtro


def _resumo(documentos: List[Dict]) -> Dict:
    """Quantos e quanto — com as NOTAS DE CRÉDITO A SUBTRAIR.

    É a regra desta casa e não uma opção: uma NC devolve dinheiro, e somá-la
    como positiva faz o resumo declarar o dobro do que entrou. As contagens
    vão separadas, como no rodapé dos relatórios do Vendus: um documento de
    venda e uma rectificação não se somam no mesmo número."""
    faturas = [d for d in documentos if d.get("tipo") != "NC"]
    notas = [d for d in documentos if d.get("tipo") == "NC"]
    centimos = (
        sum(_centimos(d.get("total") or 0) for d in faturas)
        - sum(_centimos(d.get("total") or 0) for d in notas)
    )
    return {
        "faturas": len(faturas),
        "notas_credito": len(notas),
        "total": centimos / 100.0,
    }


@router.get("/documentos")
async def documentos_do_backoffice(
    de: Optional[str] = None,
    ate: Optional[str] = None,
    loja_id: Optional[str] = None,
    tipo: Optional[str] = None,
    q: Optional[str] = None,
    pagina: int = 1,
    _: dict = Depends(gestor_atual),
) -> dict:
    """As faturas e notas de crédito de TODAS as lojas, filtradas.

    `de`/`ate` são datas (AAAA-MM-DD) e o `ate` está INCLUÍDO — quem escolhe
    "1 a 25" quer o dia 25 inteiro.

    O resumo soma o conjunto FILTRADO (não a página), porque a pergunta é
    "quanto se faturou naquele intervalo" e não "quanto vale esta página".
    Acima de `_TECTO_DO_RESUMO` documentos ele vem `truncado: true` e o ecrã
    tem de o dizer: um total parcial apresentado como total é pior do que não
    haver total nenhum.
    """
    db = obter_db()
    filtro = await _filtro_dos_documentos(db, de, ate, loja_id, tipo, q)
    pagina = max(1, pagina)

    total = await db[COLECOES["documentos"]].count_documents(filtro)
    documentos = await (
        db[COLECOES["documentos"]]
        .find(filtro, {"_id": 0})
        .sort("emitido_em", -1)
        .skip((pagina - 1) * _POR_PAGINA)
        .to_list(_POR_PAGINA)
    )
    para_o_resumo = await (
        db[COLECOES["documentos"]]
        .find(filtro, {"_id": 0, "total": 1, "tipo": 1})
        .to_list(_TECTO_DO_RESUMO)
    )

    vendas = await _vendas_por_id(
        db, [d["venda_id"] for d in documentos if d.get("venda_id")]
    )
    return {
        # A lista do backoffice leva DUAS coisas a mais do que a do POS, e as
        # duas por a pergunta ser outra: a LOJA (lá é sempre a mesma, aqui é
        # uma coluna) e o NIF do cliente, que está na venda e é por onde o
        # gestor procura a fatura de uma empresa.
        "documentos": [
            dict(_documento_na_lista(d, vendas.get(d.get("venda_id"))),
                 loja_id=d.get("loja_id"),
                 cliente_nif=(vendas.get(d.get("venda_id")) or {}).get("cliente_nif"))
            for d in documentos
        ],
        "total": total,
        "pagina": pagina,
        "por_pagina": _POR_PAGINA,
        "resumo": dict(_resumo(para_o_resumo), truncado=len(para_o_resumo) >= _TECTO_DO_RESUMO),
    }


@router.get("/documentos/{documento_id}")
async def documento_do_backoffice(
    documento_id: str, _: dict = Depends(gestor_atual)
) -> dict:
    """A MESMA fatura que o POS mostra — mesmo montador, sem o âmbito da loja
    (o gestor vê todas)."""
    db = obter_db()
    documento = await db[COLECOES["documentos"]].find_one({"id": documento_id})
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return await _detalhe_do_documento(db, documento, com_contexto=True)


_MSG_SEM_ID_NO_VENDUS = (
    "Esta fatura não tem id do Vendus guardado — sem ele não há PDF para ir "
    "buscar. O documento fiscal continua bom; o talão certificado está no "
    "botão de reimprimir."
)
_MSG_SEM_CONTA_VENDUS = (
    "Conta Vendus não configurada no servidor (VENDUS_ACCOUNTS). Sem ela não "
    "se consegue ir buscar o PDF."
)


@router.get("/documentos/{documento_id}/pdf")
async def pdf_do_documento(documento_id: str, _: dict = Depends(gestor_atual)):
    """**O PDF certificado da fatura**, ido buscar ao Vendus e devolvido tal e
    qual — para descarregar, imprimir ou anexar a um email.

    **Não é um PDF nosso.** Desenhar um aqui era produzir um papel com ar de
    fatura que não é fatura nenhuma: o documento fiscal é o do Vendus, com o
    ATCUD, o hash e o QR que a Autoridade Tributária conhece. Por isso isto é
    uma ida buscar, e não uma geração.

    **O `mode` é o DO DOCUMENTO** (`documento["modo"]`), nunca o modo em que a
    loja está hoje: um documento emitido em `tests` pedido com `mode=normal`
    responde 404. Medido ao vivo na conta real — e é a mesma armadilha que já
    apanhou a app L'Açaí.

    Uma fatura sem `vendus_document_id` (não deve existir, mas a base é mais
    velha do que algumas regras) diz que não tem PDF em vez de devolver um
    ficheiro vazio com nome de fatura.
    """
    db = obter_db()
    documento = await db[COLECOES["documentos"]].find_one({"id": documento_id})
    if not documento:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    vendus_id = documento.get("vendus_document_id")
    if not vendus_id:
        raise HTTPException(status_code=422, detail=_MSG_SEM_ID_NO_VENDUS)

    conta = obter_conta(os.environ.get("FAT_NIF") or _NIF_POR_OMISSAO)
    if conta is None:
        raise HTTPException(status_code=503, detail=_MSG_SEM_CONTA_VENDUS)

    modo = documento.get("modo") or "normal"
    try:
        with ClienteVendus(conta.chave) as cliente:
            pdf = await asyncio.to_thread(cliente.pdf_do_documento, vendus_id, modo)
    except VendusErro as e:
        raise HTTPException(status_code=502, detail="Vendus indisponível: %s" % e)
    if not pdf:
        raise HTTPException(status_code=502, detail="O Vendus não devolveu PDF nenhum.")

    nome = "%s.pdf" % (documento.get("numero") or documento_id).replace("/", "-")
    return Response(
        content=pdf,
        media_type="application/pdf",
        # `inline` e não `attachment`: o browser abre-o e a pessoa decide se
        # descarrega ou imprime dali. Com `attachment` não havia forma de o
        # VER sem o gravar primeiro.
        headers={"Content-Disposition": 'inline; filename="%s"' % nome},
    )


@router.get("/pos/documentos/{documento_id}/talao")
async def talao_do_documento(
    documento_id: str, operador: Dict = Depends(operador_atual)
) -> dict:
    """Os bytes ESC/POS do talão certificado desta fatura, em base64.

    **É o caminho do servidor até ao ponto em que os bytes estão prontos** — o
    agente de impressão da loja ainda não existe, e quando existir liga-se
    aqui sem se mexer nisto. O botão do ecrã fica desligado até lá, com o mesmo
    «Brevemente» dos outros botões de impressão do POS.

    Reimprimir NÃO volta ao Vendus, de propósito: o talão certificado é o que
    saiu no papel da primeira vez, e uma segunda ida ao Vendus podia trazer
    outra coisa (ou não trazer nada, com a rede em baixo) precisamente no
    momento em que o cliente está à frente à espera do papel dele.

    **ATENÇÃO — e isto está medido, não suposto:** `vendus/emissao.py` traz o
    `talao_escpos` na resposta da emissão, mas `fiscal._gravar_documento`
    NÃO o grava em `fat_documentos` (o documento é construído campo a campo, e
    esse campo não está na lista). Hoje, portanto, esta rota responde 409 a
    todos os documentos. Falta uma linha no núcleo fiscal, que este trabalho
    não toca por instrução expressa — ver o relatório.

    Base64 e não bytes crus: a resposta é JSON, e um `bytes` não é
    serializável. Quem imprime descodifica e manda para a porta série.
    """
    db = obter_db()
    documento = await _documento_da_loja(db, documento_id, operador["loja_id"])
    talao = documento.get("talao_escpos")
    if not talao:
        # 409 e não 404: o DOCUMENTO existe (e o 404 mandava a operadora
        # procurá-lo outra vez); o que não existe é o papel. A frase diz qual
        # das duas coisas falta.
        raise HTTPException(status_code=409, detail=_MSG_SEM_TALAO)
    if isinstance(talao, str):
        # Um talão gravado já em base64 (texto) em vez de binário: devolve-se
        # tal e qual, sem o voltar a codificar — codificar duas vezes dava
        # bytes que a impressora não percebe, e em silêncio.
        return {"formato": "escpos-base64", "talao": talao}
    return {
        "formato": "escpos-base64",
        "talao": base64.b64encode(bytes(talao)).decode("ascii"),
    }


async def _opcoes_com_precos_de_hoje(
    db, opcoes: List[Dict]
) -> Tuple[List[Dict], List[str]]:
    """As MESMAS escolhas do cliente, com os nomes e os preços de HOJE — e a
    lista das que já não existem.

    **Isto é o cerne do «copiar para a venda» e a parte fácil de estragar.**
    Uma cópia é um pedido NOVO: se a Nutella subiu de 0,95 € para 1,15 €, o
    cliente paga 1,15 €. As `opcoes` gravadas na linha antiga trazem o preço
    do dia em que foram vendidas (é um retrato, e é assim que tem de ser para
    a fatura antiga não mudar) — e `precos.linha_de_venda` soma ao preço
    unitário o `preco` de CADA opção que lhe passarem. Reenviar as opções tal
    e qual fazia a conta nova ser cobrada aos preços de ontem, sem nada a
    dizê-lo. `preco_override` não é a mesma armadilha (esse é do produto e
    fica de fora, ver `copiar_para_venda`), mas as opções passariam
    despercebidas: viajam dentro de um `List[Dict]` cru.

    O casamento é pelo `id` da opção dentro do grupo — o campo que
    `catalogo.OpcaoEntrada` preserva de propósito, «para o histórico de vendas
    continuar a apontar para o mesmo id mesmo que o nome ou o preço mudem».

    O que já não existe (grupo apagado, opção apagada, opção desactivada,
    opção antiga sem `id`) NÃO viaja: é DEIXADO DE FORA e vem nomeado na
    segunda metade do par. Deixá-lo passar com o preço antigo era cobrar por
    uma coisa que o catálogo já não tem; deixá-lo passar sem preço era dá-la
    de graça. Nomeá-lo é a terceira saída, e é a única que a operadora
    consegue usar — ela lê o nome, olha para o ecrã e decide.

    O `sai_na_fatura` NÃO viaja: a linha nasce hoje e o carimbo tira-se hoje,
    que é exactamente o que `venda._carimbar_sai_na_fatura` faz a uma opção
    nova. Reenviá-lo era mandar ao servidor um carimbo escolhido pelo cliente.
    """
    ids_de_grupo = [o.get("grupo_id") for o in opcoes if o.get("grupo_id")]
    grupos: Dict[str, Dict] = {}
    if ids_de_grupo:
        for g in await db[COLECOES["grupos_personalizacao"]].find(
            {"id": {"$in": ids_de_grupo}}
        ).to_list(len(ids_de_grupo)):
            grupos[g["id"]] = g

    de_hoje: List[Dict] = []
    perdidas: List[str] = []
    for antiga in opcoes:
        nome_antigo = antiga.get("nome") or "?"
        grupo = grupos.get(antiga.get("grupo_id"))
        actual = None
        if grupo and antiga.get("id"):
            for o in grupo.get("opcoes") or []:
                if o.get("id") == antiga["id"] and o.get("ativa", True):
                    actual = o
                    break
        if actual is None:
            perdidas.append(nome_antigo)
            continue
        de_hoje.append({
            "id": actual.get("id"),
            "grupo_id": grupo["id"],
            # O nome de HOJE, pela mesma razão do preço: é este pedido que vai
            # sair no papel, e o papel tem de dizer o que o catálogo diz.
            "nome": actual.get("nome"),
            "preco": actual.get("preco", 0),
        })
    return de_hoje, perdidas


class PedidoCopiar(BaseModel):
    """A caixa em que a conta nova vai nascer.

    É o mesmo (e único) campo de `venda.PedidoNovaVenda`, e pela mesma razão:
    a sessão e o operador vêm do TOKEN, nunca do corpo. O `caixa_id` é o que o
    ecrã tem escolhido no localStorage, e quem o valida é o
    `_obter_caixa_da_loja` de `abrir_venda` — aqui só se exige que venha."""

    caixa_id: str = Field(min_length=1)


@router.post("/pos/documentos/{documento_id}/copiar-para-venda", status_code=201)
async def copiar_para_venda(
    documento_id: str,
    dados: PedidoCopiar,
    operador: Dict = Depends(operador_atual),
) -> dict:
    """Abre uma conta NOVA com as mesmas linhas desta fatura — «o cliente quer
    o mesmo outra vez».

    **Não escreve uma única vez por sua conta.** Chama `venda.abrir_venda` e
    `venda.juntar_linha`, as rotas de sempre, e é isso que faz esta cópia
    herdar TODOS os guardas sem os repetir: a caixa tem de ser desta loja, a
    sessão tem de estar aberta, o índice único do posto continua a decidir a
    corrida do duplo toque, o produto sem IVA continua a ser recusado com 422,
    e o carimbo do `sai_na_fatura` é tirado hoje. Uma segunda implementação
    «igual» aqui era a sexta cópia de um predicado deste módulo, e as cinco
    anteriores divergiram todas.

    **UM PC ATENDE UM CLIENTE DE CADA VEZ.** É `abrir_venda` que o impõe (409
    se este posto tiver conta por resolver), e a recusa dela sobe daqui tal e
    qual, com a frase dela — que já sabe dizer em que caixa ficou a conta. O
    ecrã pergunta ANTES do toque (`GET /pos/venda/aberta`) e mostra o botão
    morto com a razão à vista, mas quem recusa é a rota: os ecrãs do POS
    desenham-se sem servidor nenhum.

    **OS PREÇOS SÃO OS DE HOJE, e é preciso dizer as três metades disso:**

    1. o PRODUTO é relido do catálogo por `juntar_linha`, que grava um retrato
       novo (`produto_preco`, `produto_tax_id`, `produto_vendus_ref`) — o preço
       de hoje entra sozinho, sem nada ser feito aqui;
    2. as OPÇÕES não: viajam gravadas na linha antiga com o preço do dia em que
       foram vendidas, e `precos.linha_de_venda` soma-as tal e qual. São
       reavaliadas em `_opcoes_com_precos_de_hoje`, e é a metade que passava
       despercebida;
    3. o `preco_override`, o `tax_override`, os descontos de linha e o desconto
       GLOBAL **não são copiados**. Um override é um ajuste excepcional
       daquela venda (uma cortesia, um artigo avariado), não uma propriedade do
       pedido; repeti-lo às cegas era repetir uma decisão que ninguém tomou
       hoje — e, no caso do desconto, dar dinheiro. A operadora volta a
       aplicá-lo se quiser, com o dedo.

    O que já não existe **não faz a cópia falhar**: um produto apagado do
    catálogo, ou um sem IVA, é DEIXADO DE FORA e vem nomeado em
    `nao_copiados`. O contrário — 404 a meio — deixava uma conta meia feita no
    ecrã sem dizer o que lhe faltava, com o cliente à frente. Se não sobrar
    linha nenhuma, a conta que nasceu é cancelada e sai 409: uma conta vazia
    presa no posto é pior do que uma recusa.
    """
    from .venda import (
        PedidoJuntarLinha,
        PedidoNovaVenda,
        abrir_venda,
        cancelar_venda,
        juntar_linha,
    )

    db = obter_db()
    documento = await _documento_da_loja(db, documento_id, operador["loja_id"])
    origem = await db[COLECOES["vendas"]].find_one({"id": documento.get("venda_id")})
    if origem is None or not (origem.get("linhas") or []):
        raise HTTPException(status_code=409, detail=_MSG_COPIA_SEM_LINHAS)

    # A porta primeiro: se o posto estiver ocupado, isto levanta 409 ANTES de
    # se ter lido um único grupo de personalização.
    nova = await abrir_venda(
        PedidoNovaVenda(caixa_id=dados.caixa_id), operador=operador)

    nao_copiados: List[str] = []
    ultima = nova
    for linha in origem["linhas"]:
        nome = linha.get("produto_nome") or "?"
        opcoes, perdidas = await _opcoes_com_precos_de_hoje(
            db, linha.get("opcoes") or []
        )
        for perdida in perdidas:
            nao_copiados.append("%s: %s (já não está no catálogo)" % (nome, perdida))
        try:
            ultima = await juntar_linha(
                nova["id"],
                PedidoJuntarLinha(
                    produto_id=linha.get("produto_id") or "",
                    quantidade=linha.get("quantidade", 1),
                    opcoes=opcoes,
                    # O nome no copo e as outras respostas de texto viajam: é
                    # tão personalização como o topping, e o cliente que pede
                    # "o mesmo outra vez" continua a chamar-se o mesmo.
                    respostas_texto=linha.get("respostas_texto") or [],
                ),
                operador=operador,
            )
        except HTTPException as e:
            # 404 (produto apagado) e 422 (produto sem IVA/preço, quantidade
            # impossível) são os dois desfechos previstos, e os dois querem
            # dizer a mesma coisa a quem está ao balcão: este artigo já não se
            # pode vender. Qualquer outro estado (o posto trancou entretanto, a
            # sessão fechou) NÃO é para engolir — sobe, e a conta fica como
            # está para a operadora a ver.
            if e.status_code not in (404, 422):
                raise
            nao_copiados.append("%s (%s)" % (nome, e.detail))

    if not (ultima.get("linhas") or []):
        # Nada sobreviveu. A conta acabada de abrir fica a prender o posto e
        # não tem nada dentro — cancela-se, e é a MESMA rota de cancelamento
        # de sempre (que sabe recusar se entretanto houver emissão viva).
        try:
            await cancelar_venda(nova["id"], operador=operador)
        except HTTPException as e:  # noqa: BLE001 — ver a frase a seguir
            # Se o cancelamento não passar, o que NÃO se pode fazer é calar:
            # a operadora fica com uma conta vazia à frente e tem de saber
            # porquê. Fica no log e a recusa segue na mesma.
            logger.warning(
                "[faturacao] cópia sem linhas: a conta %s não foi cancelada (%s)",
                nova["id"], e.detail,
            )
        raise HTTPException(status_code=409, detail=_MSG_COPIA_SEM_LINHAS)

    return {
        "venda": ultima,
        "copiada_de": {
            "documento_id": documento.get("id"),
            "numero": documento.get("numero"),
        },
        # Sempre presente, mesmo vazia: o ecrã não pode ter de adivinhar se a
        # ausência quer dizer "copiou-se tudo" ou "esta versão não responde a
        # isso" — e a diferença aqui é entre a operadora conferir a conta ou
        # entregar ao cliente um pedido a que falta um artigo.
        "nao_copiados": nao_copiados,
    }
